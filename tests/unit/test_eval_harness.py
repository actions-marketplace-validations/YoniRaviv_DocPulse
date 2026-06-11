from pathlib import Path

from docpulse.eval.harness import evaluate, load_cases
from docpulse.models import Verdict

FIXTURE = Path(__file__).parent.parent / "fixtures" / "eval_mini"


def test_load_cases_reads_label_and_files():
    cases = {c.name: c for c in load_cases(FIXTURE)}
    assert set(cases) == {"rename_stale", "refactor_accurate"}
    stale = cases["rename_stale"]
    assert stale.expected_status == "stale"
    assert "login(user)" in stale.doc_content
    assert "def login(user)" in stale.old_code
    assert "def login(username)" in stale.new_code
    assert "Rename the login parameter" in stale.intent


def test_evaluate_computes_precision_and_recall(monkeypatch):
    # Perfect predictions: stale->stale, accurate->accurate.
    def fake_verify(client, root, index, bundle, max_tool_calls):
        status = "stale" if "login" in bundle.doc_content else "accurate"
        return Verdict(section_id=bundle.section_id, status=status,
                       confidence=0.9, diagnosis="", evidence=[])

    monkeypatch.setattr("docpulse.eval.harness.verify", fake_verify)
    report = evaluate(client=object(), cases_dir=FIXTURE, max_tool_calls=5)
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.total == 2
    assert {r.name: r.predicted for r in report.rows} == {
        "rename_stale": "stale", "refactor_accurate": "accurate",
    }


def test_false_positive_drops_precision(monkeypatch):
    # Predict everything stale -> 1 TP, 1 FP -> precision 0.5, recall 1.0
    def fake_verify(client, root, index, bundle, max_tool_calls):
        return Verdict(section_id=bundle.section_id, status="stale",
                       confidence=0.9, diagnosis="", evidence=[])

    monkeypatch.setattr("docpulse.eval.harness.verify", fake_verify)
    report = evaluate(client=object(), cases_dir=FIXTURE, max_tool_calls=5)
    assert report.precision == 0.5
    assert report.recall == 1.0


def test_unverified_counts_as_not_stale(monkeypatch):
    # Predict unverified everywhere -> no positives -> recall 0, precision 0 (no TP/FP)
    def fake_verify(client, root, index, bundle, max_tool_calls):
        return Verdict(section_id=bundle.section_id, status="unverified",
                       confidence=0.0, diagnosis="", evidence=[])

    monkeypatch.setattr("docpulse.eval.harness.verify", fake_verify)
    report = evaluate(client=object(), cases_dir=FIXTURE, max_tool_calls=5)
    assert report.recall == 0.0
    assert report.precision == 0.0  # defined as 0 when there are no positive predictions
