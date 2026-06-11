from docpulse.models import Repair, RunResult, Verdict
from docpulse.report.summary import compute_exit_code, render_summary


def _v(status, conf):
    return Verdict(section_id="s", status=status, confidence=conf, diagnosis="d", evidence=[])


def test_stale_above_threshold_is_drift():
    assert compute_exit_code([_v("stale", 0.6)], 0.5) == 1


def test_stale_below_threshold_is_clean():
    assert compute_exit_code([_v("stale", 0.3)], 0.5) == 0


def test_unverified_never_drift():
    assert compute_exit_code([_v("unverified", 0.99)], 0.5) == 0


def test_accurate_is_clean():
    assert compute_exit_code([_v("accurate", 0.9)], 0.5) == 0


def test_render_summary_reports_counts_and_tokens():
    result = RunResult(
        verdicts=[_v("accurate", 0.9), _v("stale", 0.8), _v("unverified", 0.0)],
        repairs=[Repair(section_id="s", new_content="x", confidence=0.8,
                        validation_passed=True, rationale="r")],
        suspects_checked=3,
        suspects_total=5,
        tokens_used=1234,
        exit_code=1,
    )
    out = render_summary(result)
    assert "1 verified" in out
    assert "1 fixed" in out
    assert "1 flagged" in out
    assert "1 unverified" in out
    assert "2 not checked" in out  # 5 total - 3 checked
    assert "tokens: 1234" in out


def test_render_summary_fixed_counts_only_validated_repairs():
    result = RunResult(
        verdicts=[_v("stale", 0.9)],
        repairs=[
            Repair(section_id="a", new_content="x", confidence=0.9,
                   validation_passed=True, rationale="r"),
            Repair(section_id="b", new_content="y", confidence=0.9,
                   validation_passed=False, rationale="failed"),
        ],
        suspects_checked=2, suspects_total=2, tokens_used=0, exit_code=1,
    )
    out = render_summary(result)
    assert "1 fixed" in out  # only the validation_passed repair counts, not the skipped one
