from docpulse.models import RunResult, Verdict


def compute_exit_code(verdicts: list[Verdict], flag_threshold: float) -> int:
    """0 = clean, 1 = drift. (Exit 2 is raised at the CLI on tool/setup errors.)

    Drift means at least one verdict is `stale` with confidence >= flag_threshold.
    `unverified` never counts as drift — uncertainty must not block the build.
    """
    drift = any(
        v.status == "stale" and v.confidence >= flag_threshold for v in verdicts
    )
    return 1 if drift else 0


def render_summary(result: RunResult, fix_ref: str | None = None) -> str:
    """One-line health summary plus a token line, from a finished RunResult."""
    verified = sum(v.status == "accurate" for v in result.verdicts)
    unverified = sum(v.status == "unverified" for v in result.verdicts)
    flagged = sum(v.status == "stale" for v in result.verdicts)
    fixed = sum(r.validation_passed for r in result.repairs)
    not_checked = result.suspects_total - result.suspects_checked
    if fix_ref:
        fix_note = f" (PR {fix_ref})"
    elif fixed:
        fix_note = " (dry-run)"
    else:
        fix_note = ""
    return (
        f"\U0001fa7a DocPulse: {verified} verified · {fixed} fixed{fix_note} · "
        f"{flagged} flagged · {unverified} unverified · {not_checked} not checked\n"
        f"tokens: {result.tokens_used}"
    )
