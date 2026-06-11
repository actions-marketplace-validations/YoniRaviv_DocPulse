import json

from docpulse.eval.harness import EvalCase
from docpulse.eval.repair_harness import (
    RubricScore,
    evaluate_repairs,
    judge_repair,
    synthesize_verdict,
    unified_section_diff,
)


class FakeToolCall:
    def __init__(self, name, args, call_id="r1"):
        self.id = call_id
        self.type = "function"

        class Fn:
            pass

        self.function = Fn()
        self.function.name = name
        self.function.arguments = (
            args if isinstance(args, str) else json.dumps(args)
        )


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class ScriptedClient:
    """Returns scripted messages by tool name, regardless of call order."""

    def __init__(self, by_tool):
        self._by_tool = by_tool

    def complete(self, messages, tools=None):
        name = tools[0]["function"]["name"]
        return self._by_tool[name]


def _case(name="py_rename_param_stale"):
    return EvalCase(
        name=name,
        path=None,
        expected_status="stale",
        intent="Rename the retries parameter to attempts.",
        doc_content="Intro stays the same.\n\nPass `retries` to control attempts.",
        old_code="def run(retries): ...",
        new_code="def run(attempts): ...",
    )


def test_synthesize_verdict_is_stale_with_intent_diagnosis():
    v = synthesize_verdict(_case())
    assert v.status == "stale"
    assert v.confidence == 1.0
    assert "attempts" in v.diagnosis  # derived from intent


def test_unified_section_diff_shows_changes():
    diff = unified_section_diff("s", "old line", "new line")
    assert "-old line" in diff
    assert "+new line" in diff


def test_judge_repair_returns_rubric_score():
    client = ScriptedClient({
        "submit_rubric": FakeMessage(tool_calls=[FakeToolCall("submit_rubric", {
            "accuracy": 5, "completeness": 4, "style_fidelity": 5,
            "needs_human_review": False, "justification": "matches reference",
        })]),
    })
    score = judge_repair(client, "new doc", "reference doc")
    assert isinstance(score, RubricScore)
    assert score.accuracy == 5
    assert score.completeness == 4
    assert score.needs_human_review is False


def test_judge_repair_clamps_scores_to_1_5():
    client = ScriptedClient({
        "submit_rubric": FakeMessage(tool_calls=[FakeToolCall("submit_rubric", {
            "accuracy": 9, "completeness": 0, "style_fidelity": 3,
            "needs_human_review": True, "justification": "x",
        })]),
    })
    score = judge_repair(client, "n", "r")
    assert score.accuracy == 5      # clamped to 5
    assert score.completeness == 1  # clamped to 1
    assert score.needs_human_review is True


def test_judge_repair_fails_safe_on_llm_error():
    from docpulse.llm import LLMError

    class BoomClient:
        def complete(self, messages, tools=None):
            raise LLMError("boom")

    score = judge_repair(BoomClient(), "n", "r")
    assert score.accuracy == 1
    assert score.completeness == 1
    assert score.style_fidelity == 1
    assert score.needs_human_review is True


def test_judge_repair_flags_low_score_even_if_model_says_no():
    client = ScriptedClient({
        "submit_rubric": FakeMessage(tool_calls=[FakeToolCall("submit_rubric", {
            "accuracy": 5, "completeness": 3, "style_fidelity": 5,
            "needs_human_review": False, "justification": "borderline",
        })]),
    })
    score = judge_repair(client, "n", "r")
    assert score.needs_human_review is True  # min score 3 -> forced flag


def test_evaluate_repairs_over_one_stale_case(monkeypatch):
    # Stub load_cases (and reference lookup) so no filesystem is needed.
    import docpulse.eval.repair_harness as rh

    monkeypatch.setattr(rh, "load_cases", lambda d: [_case()])
    monkeypatch.setattr(
        rh, "_reference_correction",
        lambda case: "Intro stays the same.\n\nPass `attempts` to control attempts.",
    )

    repair_msg = FakeMessage(tool_calls=[FakeToolCall("submit_repair", {
        "new_content": "Intro stays the same.\n\nPass `attempts` to control attempts.",
        "rationale": "renamed retries->attempts", "confidence": 0.9,
    })])
    validation_msg = FakeMessage(tool_calls=[FakeToolCall("submit_validation", {
        "accurate_vs_code": True, "style_consistent": True, "notes": "ok",
    })])
    rubric_msg = FakeMessage(tool_calls=[FakeToolCall("submit_rubric", {
        "accuracy": 5, "completeness": 5, "style_fidelity": 5,
        "needs_human_review": False, "justification": "great",
    })])
    client = ScriptedClient({
        "submit_repair": repair_msg,
        "submit_validation": validation_msg,
        "submit_rubric": rubric_msg,
    })

    from docpulse.config import Config, DocGlob
    report = evaluate_repairs(client, cases_dir=None, config=Config(docs=[DocGlob(path="d.md")]))
    assert report.total == 1
    row = report.rows[0]
    assert row.name == "py_rename_param_stale"
    assert row.tier == "auto_fix"          # validated (0.5 preserved >= 0.5 gate) + confidence 1.0
    # First paragraph survives byte-identical (1 of 2 blocks) -> preservation 0.5,
    # which clears the 0.5 validation gate but not the 0.95 exit-report gate.
    assert row.preservation == 0.5
    assert report.pct_preserved_95 == 0.0
    assert report.mean_accuracy == 5.0
