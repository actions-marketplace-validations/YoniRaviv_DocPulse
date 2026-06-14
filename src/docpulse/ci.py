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
