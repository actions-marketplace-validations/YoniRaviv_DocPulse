import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from docpulse.cli import app

FIXTURE = Path(__file__).parent.parent / "fixtures" / "eval_mini"
runner = CliRunner()


def _verdict_response(status):
    """A litellm response whose single tool call submits the given status."""
    class Fn:
        name = "submit_verdict"
        arguments = json.dumps(
            {"status": status, "confidence": 0.9, "diagnosis": "x", "evidence": []}
        )

    class Call:
        id = "c1"
        type = "function"
        function = Fn()

    class Msg:
        content = None
        tool_calls = [Call()]

    class Choice:
        message = Msg()

    class Usage:
        total_tokens = 5

    class Resp:
        choices = [Choice()]
        usage = Usage()

    return Resp()


def test_eval_reports_precision_recall(tmp_path):
    # stale case -> "stale", accurate case -> "accurate": perfect scores.
    def route(model, messages, tools=None):
        body = messages[1]["content"]
        return _verdict_response("stale" if "login(user)" in body else "accurate")

    with patch("docpulse.llm.litellm.completion", side_effect=route):
        result = runner.invoke(
            app, ["eval", "--cases", str(FIXTURE), "--model", "test/model"]
        )
    assert result.exit_code == 0, result.output
    assert "precision" in result.output.lower()
    assert "1.00" in result.output            # precision and recall both 1.00
    assert "rename_stale" in result.output    # per-case table row


def test_eval_without_model_exits_2(tmp_path):
    # No --model and root has no docpulse.yml (empty tmp_path): friendly failure.
    # Point --root at an empty dir so a future repo-root docpulse.yml can't supply a model.
    result = runner.invoke(
        app, ["eval", "--cases", str(FIXTURE), "--root", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "model" in result.output.lower()


def test_eval_precision_gate_fails_when_below_threshold(tmp_path):
    # Force a false positive (accurate case predicted stale) -> precision 0.5.
    with patch("docpulse.llm.litellm.completion",
               side_effect=lambda model, messages, tools=None: _verdict_response("stale")):
        result = runner.invoke(
            app,
            ["eval", "--cases", str(FIXTURE), "--model", "test/model",
             "--min-precision", "0.9"],
        )
    assert result.exit_code == 1
    assert "below" in result.output.lower() or "gate" in result.output.lower()


def _tool_response(name, args):
    """A litellm response whose single tool call is `name` with `args`.

    Shape matches what LLMClient.complete reads: response.choices[0].message,
    response.usage.total_tokens.
    """
    fn = type("Fn", (), {"name": name, "arguments": json.dumps(args)})()
    call = type("Call", (), {"id": "c1", "type": "function", "function": fn})()
    msg = type("Msg", (), {"content": None, "tool_calls": [call]})()
    choice = type("Choice", (), {"message": msg})()
    usage = type("Usage", (), {"total_tokens": 5})()
    return type("Resp", (), {"choices": [choice], "usage": usage})()


def test_eval_repair_flag_runs_repair_eval():
    # Route each LLM call by the tool offered (tools[0] name) and, for verify,
    # by the doc body. The repair eval synthesizes stale verdicts itself.
    def route(model, messages, tools=None):
        tool_name = tools[0]["function"]["name"] if tools else ""
        if tool_name == "submit_verdict":
            body = messages[1]["content"]
            return _verdict_response("stale" if "login(user)" in body else "accurate")
        if tool_name == "submit_repair":
            return _tool_response("submit_repair", {
                "new_content": "repaired", "rationale": "fixed", "confidence": 0.9,
            })
        if tool_name == "submit_validation":
            return _tool_response("submit_validation", {
                "accurate_vs_code": True, "style_consistent": True, "notes": "ok",
            })
        if tool_name == "submit_rubric":
            return _tool_response("submit_rubric", {
                "accuracy": 5, "completeness": 5, "style_fidelity": 5,
                "needs_human_review": False, "justification": "good",
            })
        raise AssertionError(f"unexpected tool {tool_name}")

    with patch("docpulse.llm.litellm.completion", side_effect=route):
        result = runner.invoke(
            app,
            ["eval", "--cases", str(FIXTURE), "--model", "test/model", "--repair"],
        )
    assert result.exit_code == 0, result.output
    assert "repair" in result.output.lower()
    assert "preservation" in result.output.lower()
    assert "rename_stale" in result.output  # the one stale case in eval_mini
