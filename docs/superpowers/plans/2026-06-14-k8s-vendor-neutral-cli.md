# DocPulse k8s Support — Self-Sufficient, Vendor-Neutral CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `docpulse` CLI work correctly when invoked outside the Docker entrypoint (k8s sidecar / installed CLI) and emit findings as a portable artifact, so DocPulse runs on any CI/SCM without a Docker daemon or vendor lock-in.

**Architecture:** Move the CI git-prep (safe.directory, base-ref fetch) and the push loop-guard out of `entrypoint.sh` into a new `src/docpulse/ci.py` module the `check`/`repair` commands call directly. Make the doc-sync commit bot-authored via inline `git -c user.*` (no config mutation). Add `--comment-out PATH` (portable markdown artifact) and `--comment-via {gh,none}` (default `gh`) so GitHub posting stays the default while other hosts let their own CI post the artifact. Slim `entrypoint.sh` to a thin wrapper.

**Tech Stack:** Python 3.12, Typer CLI, pytest, subprocess/git, Docker, GitHub Actions, Jenkins (k8s).

**Spec:** `docs/superpowers/specs/2026-06-14-k8s-vendor-neutral-cli-design.md`

---

## File Structure

- **Create** `src/docpulse/ci.py` — CI self-prep primitives: `ensure_safe_directory`, `resolve_base_ref`, `loop_guard`. Pure-ish, subprocess-backed, each one job.
- **Create** `tests/unit/test_ci.py` — unit tests for `ci.py` against real temp git repos.
- **Modify** `src/docpulse/cli.py` — add `_bot_identity` helper + bot-identity constants; add `--comment-out` / `--comment-via` options to `check` and `repair`; call `ci.*` in the right order; thread new args through `_build_destination`.
- **Modify** `src/docpulse/destinations/repo_markdown.py` — constructor gains `comment_out`, `comment_via`, `bot_name`, `bot_email`; `publish_findings` writes the artifact + routes posting; `build_fix_plan` commit command carries inline identity.
- **Modify** `tests/unit/test_repo_markdown.py` — update the commit-command assertion; add `--comment-out` / `--comment-via none` tests.
- **Modify** `tests/unit/test_cli_push.py` — add `_bot_identity` tests + a loop-guard-skip test.
- **Modify** `entrypoint.sh` — drop git-config/fetch/loop-guard lines; pass `--comment-via gh` (+ optional `--comment-out`).
- **Modify** `README.md` — add the k8s sidecar recipe to the "Jenkins / any CI" section.

---

## Task 1: Bot-identity resolver in the CLI

**Files:**
- Modify: `src/docpulse/cli.py` (add constants + `_bot_identity` near `_pr_number`, ~line 45)
- Test: `tests/unit/test_cli_push.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_cli_push.py` (extend the existing `from docpulse.cli import ...` line to include `_bot_identity`):

```python
from docpulse.cli import _bot_identity  # add to the existing cli import


def test_bot_identity_defaults():
    name, email = _bot_identity({})
    assert name == "docpulse[bot]"
    assert email == "docpulse-bot@users.noreply.github.com"


def test_bot_identity_env_override():
    name, email = _bot_identity(
        {"DOCPULSE_BOT_NAME": "Custom Bot", "DOCPULSE_BOT_EMAIL": "bot@corp.test"}
    )
    assert name == "Custom Bot"
    assert email == "bot@corp.test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_push.py::test_bot_identity_defaults -v`
Expected: FAIL with `ImportError: cannot import name '_bot_identity'`

- [ ] **Step 3: Write minimal implementation**

In `src/docpulse/cli.py`, add just below the imports (after line 27) the constants, and add `_bot_identity` right after `_pr_number` (after line 51):

```python
_DEFAULT_BOT_NAME = "docpulse[bot]"
_DEFAULT_BOT_EMAIL = "docpulse-bot@users.noreply.github.com"


def _bot_identity(env: dict[str, str]) -> tuple[str, str]:
    """(name, email) for the doc-sync commit + loop guard, from env or defaults."""
    return (
        env.get("DOCPULSE_BOT_NAME") or _DEFAULT_BOT_NAME,
        env.get("DOCPULSE_BOT_EMAIL") or _DEFAULT_BOT_EMAIL,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli_push.py -k bot_identity -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/docpulse/cli.py tests/unit/test_cli_push.py
git commit -m "feat(cli): bot-identity resolver (env-overridable defaults)"
```

---

## Task 2: `ci.loop_guard`

**Files:**
- Create: `src/docpulse/ci.py`
- Test: `tests/unit/test_ci.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ci.py`:

```python
import subprocess
from pathlib import Path

from docpulse.ci import loop_guard

BOT = "docpulse-bot@users.noreply.github.com"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo_with_commit(tmp_path: Path, email: str) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", "f.txt")
    _git(repo, "-c", f"user.email={email}", "-c", "user.name=T", "commit", "-q", "-m", "c")
    return repo


def test_loop_guard_true_for_bot_author(tmp_path):
    repo = _repo_with_commit(tmp_path, BOT)
    assert loop_guard(repo, BOT) is True


def test_loop_guard_false_for_human_author(tmp_path):
    repo = _repo_with_commit(tmp_path, "dev@example.com")
    assert loop_guard(repo, BOT) is False


def test_loop_guard_false_when_no_commits(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    assert loop_guard(repo, BOT) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ci.py::test_loop_guard_true_for_bot_author -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docpulse.ci'`

- [ ] **Step 3: Write minimal implementation**

Create `src/docpulse/ci.py`:

```python
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
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ae"],
        cwd=root, capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return False
    return result.stdout.strip() == bot_email
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ci.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/docpulse/ci.py tests/unit/test_ci.py
git commit -m "feat(ci): loop_guard — detect a bot-authored HEAD"
```

---

## Task 3: `ci.resolve_base_ref`

**Files:**
- Modify: `src/docpulse/ci.py`
- Test: `tests/unit/test_ci.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ci.py` (extend the import to `from docpulse.ci import loop_guard, resolve_base_ref` and add `import docpulse.ci as ci`):

```python
import docpulse.ci as ci
from docpulse.ci import resolve_base_ref


def test_resolve_base_ref_noop_when_ref_resolves(tmp_path):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    # HEAD always resolves; must do nothing and not raise.
    resolve_base_ref(repo, "HEAD")


def test_resolve_base_ref_swallows_fetch_failure(tmp_path):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    # origin/main does not resolve and there is no 'origin' remote -> must not raise.
    resolve_base_ref(repo, "origin/main")


def test_resolve_base_ref_fetches_parsed_remote_branch(tmp_path, monkeypatch):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    calls = []

    class _R:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        return _R()

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    resolve_base_ref(repo, "origin/feature/x")
    assert [
        "git", "fetch", "--no-tags", "--depth=50", "origin",
        "+refs/heads/feature/x:refs/remotes/origin/feature/x",
    ] in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ci.py::test_resolve_base_ref_fetches_parsed_remote_branch -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_base_ref'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/docpulse/ci.py`:

```python
def _ref_resolves(root: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root, capture_output=True, encoding="utf-8", errors="replace",
    )
    return result.returncode == 0


def resolve_base_ref(root: Path, base: str) -> None:
    """Best-effort: ensure `base` resolves locally, fetching it if missing.

    On a shallow CI checkout `origin/<branch>` may be absent. If `base` already
    resolves, do nothing. Otherwise fetch it: `origin/<branch>` populates the
    matching remote-tracking ref; a bare ref/sha is fetched directly. Failures
    are swallowed — the diff path raises a clear error if the ref is still
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
    subprocess.run(
        args, cwd=root, capture_output=True, encoding="utf-8", errors="replace"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ci.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/docpulse/ci.py tests/unit/test_ci.py
git commit -m "feat(ci): resolve_base_ref — fetch base on shallow checkouts"
```

---

## Task 4: `ci.ensure_safe_directory`

**Files:**
- Modify: `src/docpulse/ci.py`
- Test: `tests/unit/test_ci.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ci.py` (extend import to also include `ensure_safe_directory`):

```python
from docpulse.ci import ensure_safe_directory


def test_is_dubious_ownership_detects_message():
    assert ci._is_dubious_ownership(
        "fatal: detected dubious ownership in repository at '/work'"
    )
    assert not ci._is_dubious_ownership("")
    assert not ci._is_dubious_ownership("fatal: not a git repository")


def test_ensure_safe_directory_noop_on_clean_repo(tmp_path):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    before = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        capture_output=True, text=True,
    ).stdout
    ensure_safe_directory(repo)  # same-uid repo -> probe succeeds -> no mutation
    after = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        capture_output=True, text=True,
    ).stdout
    assert before == after
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ci.py::test_is_dubious_ownership_detects_message -v`
Expected: FAIL with `AttributeError: module 'docpulse.ci' has no attribute '_is_dubious_ownership'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/docpulse/ci.py`:

```python
def _is_dubious_ownership(stderr: str) -> bool:
    return "dubious ownership" in stderr.lower()


def ensure_safe_directory(root: Path) -> None:
    """Trust `root` for git when it is owned by a different uid (the common
    container case), where git otherwise refuses every operation with a
    'dubious ownership' error. Adds the path to the global safe.directory list
    (idempotently) only when that error is detected, so local dev is untouched.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=root, capture_output=True, encoding="utf-8", errors="replace",
    )
    if probe.returncode == 0 or not _is_dubious_ownership(probe.stderr or ""):
        return
    abs_root = str(Path(root).resolve())
    existing = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if abs_root in (existing.stdout or "").splitlines():
        return
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", abs_root],
        capture_output=True, encoding="utf-8", errors="replace",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ci.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/docpulse/ci.py tests/unit/test_ci.py
git commit -m "feat(ci): ensure_safe_directory — trust the checkout under a uid mismatch"
```

---

## Task 5: Destination — portable artifact, comment routing, bot-authored commit

**Files:**
- Modify: `src/docpulse/destinations/repo_markdown.py:62-78` (constructor), `:122-129` (`publish_findings`), `:167-172` (commit command in `build_fix_plan`)
- Test: `tests/unit/test_repo_markdown.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_repo_markdown.py` (the `_stale_result` and `_section` helpers already exist in this file):

```python
def test_publish_findings_writes_comment_out_file(tmp_path):
    section = _section()
    out = tmp_path / "flag.md"
    dest = RepoMarkdownDestination(
        root=Path("."), sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abc",
        dry_run=True, comment_out=out,
    )
    dest.publish_findings(_stale_result(section))
    assert "param renamed" in out.read_text()


def test_publish_findings_comment_via_none_skips_gh():
    section = _section()
    calls = []
    dest = RepoMarkdownDestination(
        root=Path("."), sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abc",
        run_command=lambda a: calls.append(a) or "",
        dry_run=False, pr_number="42", comment_via="none",
    )
    dest.publish_findings(_stale_result(section))
    assert calls == []  # gh never invoked when comment_via='none'


def test_build_fix_plan_commit_is_bot_authored(tmp_path):
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "auth.md"
    doc.write_text("# Login\n\nCall login with a user.\n")
    section = parse_markdown("docs/auth.md", doc.read_text())[0]
    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        bot_name="docpulse[bot]", bot_email="docpulse-bot@users.noreply.github.com",
    )
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="renamed", evidence=[])],
        repairs=[Repair(section_id=section.id,
                        new_content="# Login\n\nCall login with a username.",
                        confidence=0.95, validation_passed=True, rationale="r")],
        suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    plan = dest.build_fix_plan(result)
    assert [
        "git", "-c", "user.name=docpulse[bot]",
        "-c", "user.email=docpulse-bot@users.noreply.github.com",
        "commit", "-m", plan.commit_message,
    ] in plan.commands
```

Also **update the existing** `test_build_fix_plan_groups_edits_and_routes` (its commit assertion at `tests/unit/test_repo_markdown.py:125`): replace

```python
    assert ["git", "commit", "-m", plan.commit_message] in plan.commands
```

with

```python
    assert [
        "git", "-c", "user.name=docpulse[bot]",
        "-c", "user.email=docpulse-bot@users.noreply.github.com",
        "commit", "-m", plan.commit_message,
    ] in plan.commands
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repo_markdown.py -k "comment_out or comment_via or bot_authored" -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'comment_out'`

- [ ] **Step 3: Write the implementation**

In `src/docpulse/destinations/repo_markdown.py`, update the imports at the top to include `Literal`:

```python
from pathlib import Path
from typing import Literal
```

Replace the constructor (`:62-78`) with:

```python
    def __init__(
        self,
        root: Path,
        sections_by_id: dict[str, DocSection],
        config: Config,
        head_sha: str,
        run_command: CommandRunner | None = None,
        dry_run: bool = True,
        pr_number: str | None = None,
        comment_out: Path | None = None,
        comment_via: Literal["gh", "none"] = "gh",
        bot_name: str = "docpulse[bot]",
        bot_email: str = "docpulse-bot@users.noreply.github.com",
    ) -> None:
        self.root = root
        self.sections_by_id = sections_by_id
        self.config = config
        self.head_sha = head_sha
        self.run_command = run_command or default_runner(root)
        self.dry_run = dry_run
        self.pr_number = pr_number
        self.comment_out = comment_out
        self.comment_via = comment_via
        self.bot_name = bot_name
        self.bot_email = bot_email
```

Replace `publish_findings` (`:122-129`) with:

```python
    def publish_findings(self, result: RunResult) -> None:
        comment = self.flag_comment(result)
        if not comment:
            return
        if self.comment_out is not None:
            self.comment_out.write_text(comment)
        if self.comment_via == "gh" and not self.dry_run and self.pr_number:
            self.run_command(["gh", "pr", "comment", self.pr_number, "--body", comment])
            return  # posted to the PR; stdout not needed
        if self.comment_out is None:
            print(comment)  # no artifact + not posted -> log it
```

In `build_fix_plan`, replace the commit entry in the `commands` list (`:168-172`):

```python
        commands = [
            *[["git", "add", path] for path in sorted(file_writes)],
            ["git", "-c", f"user.name={self.bot_name}",
             "-c", f"user.email={self.bot_email}", "commit", "-m", commit_message],
            ["git", "push", "origin", "HEAD"],
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repo_markdown.py -v`
Expected: PASS (all, including the updated `test_build_fix_plan_groups_edits_and_routes` and the existing `test_publish_findings_live_posts_comment_to_pr` / `test_publish_findings_live_without_pr_number_prints`)

- [ ] **Step 5: Commit**

```bash
git add src/docpulse/destinations/repo_markdown.py tests/unit/test_repo_markdown.py
git commit -m "feat(dest): --comment-out artifact, gh/none routing, bot-authored commit"
```

---

## Task 6: Wire the CLI — options, ci-prep order, destination args

**Files:**
- Modify: `src/docpulse/cli.py` — `_build_destination` (`:54-62`), `check` (`:99-168`), `repair` (`:171-254`)
- Test: `tests/unit/test_cli_push.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_cli_push.py`:

```python
def test_repair_push_skips_when_head_is_bot_commit(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    # make the loop guard fire regardless of the repo's real HEAD
    monkeypatch.setattr(cli_mod.ci, "loop_guard", lambda root, email: True)
    monkeypatch.setattr(cli_mod, "_build_destination", lambda **kw: _FakeDest(**kw))
    monkeypatch.setattr(cli_mod, "LLMClient", lambda model: object())
    called = {"pipeline": False}

    def _pipeline(*a, **k):
        called["pipeline"] = True
        raise AssertionError("pipeline must not run when the loop guard fires")

    monkeypatch.setattr(cli_mod, "run_pipeline", _pipeline)
    result = runner.invoke(
        app, ["repair", "--base", "origin/main", "--root", str(repo), "--push"]
    )
    assert result.exit_code == 0, result.output
    assert "skipping to avoid a loop" in result.output
    assert called["pipeline"] is False


def test_check_passes_comment_options_to_destination(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(cli_mod, "_build_destination", lambda **kw: _FakeDest(**kw))
    monkeypatch.setattr(cli_mod, "LLMClient", lambda model: object())
    monkeypatch.setattr(
        cli_mod, "run_pipeline",
        lambda *a, **k: RunResult(verdicts=[], repairs=[], suspects_checked=0,
                                  suspects_total=0, tokens_used=0, exit_code=0),
    )
    monkeypatch.setattr(cli_mod, "GitContext", lambda *a, **k: type("C", (), {"get_intent": lambda self: ""})())
    out = tmp_path / "flag.md"
    result = runner.invoke(app, [
        "check", "--base", "origin/main", "--root", str(repo),
        "--comment-out", str(out), "--comment-via", "none",
    ])
    assert result.exit_code == 0, result.output
    assert _FakeDest.last["comment_out"] == out
    assert _FakeDest.last["comment_via"] == "none"
```

Note: `cli_mod.ci` requires `cli.py` to `import` the `ci` module (done in Step 3). The `_init_repo` helper inits a repo with **no commits**, so the real `loop_guard` returns False; the skip test monkeypatches it to True explicitly.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_push.py::test_check_passes_comment_options_to_destination -v`
Expected: FAIL — `_FakeDest.last` has no `comment_out` key (`KeyError`), because the CLI does not yet pass it.

- [ ] **Step 3: Write the implementation**

In `src/docpulse/cli.py`, add to the imports block (after line 11, `from docpulse.config import ...`):

```python
from docpulse import ci
```

Replace `_build_destination` (`:54-62`) with:

```python
def _build_destination(
    *, root: Path, sections_by_id, config, head_sha, dry_run, pr_number=None,
    comment_out=None, comment_via="gh", bot_name="docpulse[bot]",
    bot_email="docpulse-bot@users.noreply.github.com",
):
    run_command = checked_runner(root) if not dry_run else None
    return RepoMarkdownDestination(
        root, sections_by_id, config, head_sha,
        run_command=run_command, dry_run=dry_run, pr_number=pr_number,
        comment_out=comment_out, comment_via=comment_via,
        bot_name=bot_name, bot_email=bot_email,
    )
```

In `check` (`:99-115`), add two options after the `push` option (keep the existing ones):

```python
    comment_out: Path | None = typer.Option(
        None, "--comment-out", help="Write the flag-comment markdown to this file "
        "(any host's CI can post it)"
    ),
    comment_via: str = typer.Option(
        "gh", "--comment-via", help="Post the comment via 'gh' (GitHub, default) or 'none'"
    ),
```

In `check`, immediately after the `config`/`index` are loaded (right after the `except FileNotFoundError` block ending at `:126`), insert:

```python
    bot_name, bot_email = _bot_identity(dict(os.environ))
    ci.ensure_safe_directory(root)
    ci.resolve_base_ref(root, base)
```

In `check`, replace the `_build_destination(...)` call (`:153-157`) with:

```python
    dest = _build_destination(
        root=root, sections_by_id={s.id: s for s in index.sections},
        config=config, head_sha=_head_commit(root),
        dry_run=not push, pr_number=_pr_number(dict(os.environ)),
        comment_out=comment_out, comment_via=comment_via,
        bot_name=bot_name, bot_email=bot_email,
    )
```

In `repair` (`:171-187`), add the same two options after the `push` option:

```python
    comment_out: Path | None = typer.Option(
        None, "--comment-out", help="Write the flag-comment markdown to this file "
        "(any host's CI can post it)"
    ),
    comment_via: str = typer.Option(
        "gh", "--comment-via", help="Post the comment via 'gh' (GitHub, default) or 'none'"
    ),
```

In `repair`, immediately after the `config`/`index` load `except` block (ending at `:198`), insert (the loop guard runs only on the push path, before any expensive work in this command):

```python
    bot_name, bot_email = _bot_identity(dict(os.environ))
    ci.ensure_safe_directory(root)
    if push and ci.loop_guard(root, bot_email):
        typer.echo("DocPulse: latest commit is a DocPulse doc-sync; skipping to avoid a loop.")
        raise typer.Exit(0)
    ci.resolve_base_ref(root, base)
```

In `repair`, replace the `_build_destination(...)` call (`:215-220`) with:

```python
    dest = _build_destination(
        root=root, sections_by_id={s.id: s for s in index.sections},
        config=config, head_sha=_head_commit(root),
        dry_run=not push, pr_number=_pr_number(dict(os.environ)),
        comment_out=comment_out, comment_via=comment_via,
        bot_name=bot_name, bot_email=bot_email,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli_push.py -v`
Expected: PASS (all, including the pre-existing `test_check_push_passes_live_kwargs` and `test_repair_push_commits_to_branch`)

- [ ] **Step 5: Run the full suite + linters**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all tests PASS, ruff reports no errors.

- [ ] **Step 6: Commit**

```bash
git add src/docpulse/cli.py tests/unit/test_cli_push.py
git commit -m "feat(cli): self-prep (safe.directory, base fetch, loop guard) + comment options"
```

---

## Task 7: Slim `entrypoint.sh`

**Files:**
- Modify: `entrypoint.sh`

- [ ] **Step 1: Replace the script body**

The git-config, base-ref fetch, and loop-guard lines now live in the CLI. Replace `entrypoint.sh` entirely with:

```sh
#!/bin/sh
set -eu

MODE="${DOCPULSE_MODE:-check}"
CONFIG="${DOCPULSE_CONFIG:-docpulse.yml}"
WORK="${GITHUB_WORKSPACE:-$(pwd)}"

BASE_REF="${GITHUB_BASE_REF:-main}"
BASE="${DOCPULSE_BASE_REF:-origin/${BASE_REF}}"

INDEX_FLAGS=""
# Compared against the literal "true" (the value action.yml passes). Raw
# docker/Jenkins callers must use "true", not "1"/"yes".
if [ "${DOCPULSE_HEURISTICS_ONLY:-false}" = "true" ]; then
  INDEX_FLAGS="--heuristics-only"
fi

# The CLI now self-preps (git safe.directory, base-ref fetch, push loop guard)
# and is bot-identity aware, so this wrapper only maps env -> CLI invocation.
# shellcheck disable=SC2086
docpulse index --root "$WORK" --config "$WORK/$CONFIG" $INDEX_FLAGS

# --comment-out is added only when DOCPULSE_COMMENT_OUT is set; otherwise the
# comment prints to stdout (CI logs) and gh posts it (avoids double output).
COMMENT_OUT_FLAG=""
if [ -n "${DOCPULSE_COMMENT_OUT:-}" ]; then
  COMMENT_OUT_FLAG="--comment-out ${DOCPULSE_COMMENT_OUT}"
fi
# shellcheck disable=SC2086
exec docpulse "$MODE" --base "$BASE" --root "$WORK" --config "$WORK/$CONFIG" \
  --push --comment-via gh $COMMENT_OUT_FLAG
```

- [ ] **Step 2: Lint the shell script**

Run: `shellcheck entrypoint.sh` (skip if shellcheck is unavailable — the inline `disable` directives cover the intentional word-splitting).
Expected: no errors.

- [ ] **Step 3: Sanity-check the image build still works**

Run: `docker build -t docpulse-local .`
Expected: build succeeds (no behavioral change to the Action; entrypoint is just thinner).

- [ ] **Step 4: Commit**

```bash
git add entrypoint.sh
git commit -m "refactor(entrypoint): move git-prep + loop guard into the CLI"
```

---

## Task 8: Document the k8s sidecar recipe

**Files:**
- Modify: `README.md:119-137` (the "Jenkins / any CI" section)

- [ ] **Step 1: Extend the "Jenkins / any CI" section**

Keep the existing daemon-based `docker run` block, and append after it (after `README.md:137`):

````markdown
### Kubernetes (no Docker daemon)

A Jenkins agent that is itself a K8s pod has no Docker daemon, so `docker run`
won't work. Run DocPulse as a **pod sidecar container** (or `uv tool install
docpulse` / `pipx install docpulse` into the agent image) and call the CLI
directly — it self-preps (git `safe.directory`, base-ref fetch on shallow
checkouts, and the push loop guard), so no entrypoint wrapper is needed:

```groovy
container('docpulse') {
  sh '''
    docpulse index --root .
    docpulse check --base "origin/$CHANGE_TARGET" --comment-out docpulse-flag.md
  '''
}
// then post docpulse-flag.md with your SCM's Jenkins plugin (GitHub/GitLab/Bitbucket)
```

`--comment-out` writes the flag comment as portable markdown so **any** host's CI
posts it natively — DocPulse stays out of the per-vendor comment-API business.
GitHub users can instead let DocPulse post directly (the default `--comment-via
gh`, given `gh` + `GH_TOKEN` + `DOCPULSE_PR_NUMBER`); other hosts pass
`--comment-via none`. `repair --push` works on any host — it commits the doc-sync
fix with `git -c user.*` (bot-authored, so the loop guard catches it) and pushes
with the credentials your checkout already configured.

Map your CI's variables: Jenkins exposes the base branch as `$CHANGE_TARGET` and
the PR/MR number as `$CHANGE_ID` (set `DOCPULSE_PR_NUMBER="$CHANGE_ID"` for `gh`
posting). The bot identity is overridable via `DOCPULSE_BOT_NAME` /
`DOCPULSE_BOT_EMAIL`.
````

- [ ] **Step 2: Verify the markdown renders**

Run: `grep -n "Kubernetes (no Docker daemon)" README.md`
Expected: one match — the new heading is present.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): k8s sidecar recipe + vendor-neutral comment notes"
```

---

## Final Verification

- [ ] **Run the full test suite + linters one last time**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all tests pass; no lint errors.

- [ ] **Confirm the new CLI surface**

Run: `uv run docpulse check --help` and `uv run docpulse repair --help`
Expected: both show `--comment-out` and `--comment-via` options.
