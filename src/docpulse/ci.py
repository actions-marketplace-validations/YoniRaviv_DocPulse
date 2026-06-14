"""CI self-prep primitives so the `docpulse` CLI works outside the Docker
entrypoint (k8s sidecar / installed CLI): git-ownership trust, base-ref
resolution on shallow checkouts, and the push loop-guard."""

import subprocess
from pathlib import Path


def loop_guard(root: Path, bot_email: str) -> bool:
    """True when HEAD's author email is the bot's — the caller should skip the
    push to avoid an endless loop (the pushed doc-sync would otherwise
    re-trigger DocPulse). False when there is no HEAD or git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ae"],
            cwd=root, capture_output=True, encoding="utf-8", errors="replace",
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip() == bot_email


def _ref_resolves(root: Path, ref: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root, capture_output=True, encoding="utf-8", errors="replace",
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return result.returncode == 0


def resolve_base_ref(root: Path, base: str) -> None:
    """Best-effort: ensure `base` resolves locally, fetching it if missing.

    On a shallow CI checkout `origin/<branch>` may be absent. If `base` already
    resolves, do nothing. Otherwise fetch it: `origin/<branch>` populates the
    matching remote-tracking ref; a bare ref/sha is fetched directly. Failures
    are swallowed -- the diff path raises a clear error if the ref is still
    missing.
    """
    if _ref_resolves(root, base):
        return
    if "/" in base:
        remote, branch = base.split("/", 1)
        args = [
            "git", "fetch", "--no-tags", "--depth=50", remote,
            f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}",
        ]
    else:
        args = ["git", "fetch", "--no-tags", "--depth=50", "origin", base]
    try:
        subprocess.run(
            args, cwd=root, capture_output=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return
