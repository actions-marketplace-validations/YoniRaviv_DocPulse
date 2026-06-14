# DocPulse k8s support — self-sufficient, vendor-neutral CLI

**Date:** 2026-06-14
**Status:** Approved design, pre-implementation

## Problem

DocPulse's documented CI recipe is `docker run -v $PWD:/work ghcr.io/...`, which
needs a Docker daemon. A Jenkins agent running as a Kubernetes pod has no daemon,
so the recipe doesn't work verbatim. The two viable k8s paths — running DocPulse
as a **pod sidecar container** (`container('docpulse'){ sh 'docpulse ...' }`) or
**installing the CLI** (`uv tool install` / `pipx`) into the agent image — both
invoke the `docpulse` CLI directly and therefore **bypass `entrypoint.sh`**.

That matters because every "make it work in CI" behavior currently lives only in
`entrypoint.sh`:

- `git config safe.directory` + bot git identity (`entrypoint.sh:14-16`)
- fetch `origin/<base>` so it resolves on a shallow checkout (`entrypoint.sh:19-20`)
- the **loop guard** that stops a pushed doc-sync commit from re-triggering forever
  (`entrypoint.sh:24-28`)

Bypassing the entrypoint loses all of it: `repair --push` fails on git identity /
`safe.directory`, `origin/main` may not resolve, and there is no loop guard.

There is also a vendor-lock issue: the flag comment is posted via `gh pr comment`
(`destinations/repo_markdown.py:127`), which is GitHub-only. GitLab and Bitbucket
have different APIs. Teaching DocPulse every vendor's comment API is a maintenance
treadmill (a new integration per host, forever).

## Goal

Make the `docpulse` CLI **self-sufficient** — correct behavior whether invoked via
the Docker entrypoint, a k8s sidecar, or a local/installed CLI — and
**vendor-neutral** for findings output, without owning per-vendor comment APIs.

Non-goal: in-tool multi-vendor comment posting (rejected — the lock-in treadmill).

## Design (Approach A: producer/consumer split)

DocPulse's job is to detect, fix, and *report*. Posting a comment to a specific
PR/MR UI is the CI platform's job. The core CLI does its own git prep, runs the
loop guard, pushes the doc-sync commit via plain git (already vendor-neutral), and
emits the flag comment as a portable artifact. GitHub posting via `gh` stays as the
default convenience; other hosts opt out and let their native CI plugin post the
artifact.

### Component 1 — Vendor-neutral findings output

`flag_comment()` (`destinations/repo_markdown.py:80`) already renders portable
markdown. Change only *how it is published*:

- New CLI options on `check` and `repair`:
  - `--comment-out PATH` — write the flag-comment markdown to `PATH` whenever a
    comment exists, **independent of `--push`** (so a non-live `check` still
    produces the artifact the CI posts).
  - `--comment-via {gh,none}` — default **`gh`**. GitHub posting is the default;
    other vendors pass `--comment-via none`.
- `gh pr comment` fires only when `comment_via == "gh"` **and** live (`--push`)
  **and** a PR number resolves (`_pr_number`) — the same guard as today, so a
  non-live `check` never touches `gh`.
- stdout printing of the comment is preserved **when `--comment-out` is not
  given** (useful in CI logs); when an artifact path is given, the file is the
  output and stdout is not also printed, avoiding double output.
- `publish_fix`'s `git push origin HEAD` (`destinations/repo_markdown.py:168-172`)
  is already vendor-neutral; it reuses the checkout's push credentials. No change
  beyond commit identity (Component 2).

Implementation: `RepoMarkdownDestination` gains `comment_out: Path | None` and
`comment_via: Literal["gh","none"]` (constructor + threaded into `publish_findings`).
`_build_destination` in `cli.py` passes them through from the new CLI options.

### Component 2 — CLI self-prep

New focused module `src/docpulse/ci.py`. Each function does one job and is gated so
local development is never affected:

- `ensure_safe_directory(root) -> None` — run a probe `git` command; only if it
  fails with a *dubious-ownership* error, run
  `git config --global --add safe.directory <abs root>` and let later git calls
  succeed. Triggers only under the Docker uid mismatch, never in local dev.
- `resolve_base_ref(root, base) -> None` — if `base` (e.g. `origin/main`) does not
  resolve (`git rev-parse --verify <base>^{commit}` fails), best-effort `git fetch`
  of that branch (mirrors `entrypoint.sh:19-20`: parse `origin/<branch>` →
  `git fetch --no-tags --depth=50 origin +refs/heads/<branch>:refs/remotes/origin/<branch>`;
  a bare ref → `git fetch origin <base>`). Failures are swallowed; the existing
  diff path then raises a clear error if the ref is still missing.
- `loop_guard(root, bot_email) -> bool` — True when HEAD's author email equals the
  bot's. Consulted on the `repair --push` path only; the command then exits 0.
- `ensure_commit_identity(root, runner, name, email) -> None` — if the repo has no
  `user.email` configured, set a **repo-local** (not `--global`) bot identity.
  Called inside `publish_fix` immediately before the commit, so it never leaks to
  other repos on a shared agent.

Bot identity is resolved from environment variables via a `_bot_identity(env)`
helper in `cli.py` (alongside `_pr_number`):

- `DOCPULSE_BOT_EMAIL` (default `docpulse-bot@users.noreply.github.com`)
- `DOCPULSE_BOT_NAME` (default `docpulse[bot]`)

Env-based, matching the existing env-driven entrypoint pattern; no `docpulse.yml`
schema churn.

**Call order** in `check` and `repair` (after config/index load, before diffing):

1. `ensure_safe_directory(root)`
2. (`repair` + `--push` only) `if loop_guard(root, bot_email): echo skip; raise Exit(0)`
3. `resolve_base_ref(root, base)`
4. existing flow

`ensure_commit_identity` is invoked inside `publish_fix`, just before commit.

### Component 3 — `entrypoint.sh` slims down

The git-config, base-ref fetch, and loop-guard lines move into the CLI and are
removed from `entrypoint.sh`. It becomes env-mapping plus:

```sh
docpulse index --root "$WORK" --config "$WORK/$CONFIG" $INDEX_FLAGS
# --comment-out is added only when DOCPULSE_COMMENT_OUT is set; otherwise the
# comment prints to stdout (CI logs) and gh posts it. Avoids double output.
COMMENT_OUT_FLAG=""
[ -n "${DOCPULSE_COMMENT_OUT:-}" ] && COMMENT_OUT_FLAG="--comment-out ${DOCPULSE_COMMENT_OUT}"
exec docpulse "$MODE" --base "$BASE" --root "$WORK" --config "$WORK/$CONFIG" \
  --push --comment-via gh $COMMENT_OUT_FLAG
```

The GitHub Action's externally observable behavior is unchanged (`--comment-via gh`
is the new default, so passing it is explicit-but-equivalent).

### Component 4 — Documentation

Extend the README "Jenkins / any CI" section with a **k8s sidecar recipe** (no
Docker daemon required):

```groovy
container('docpulse') {
  sh '''
    docpulse index --root .
    docpulse check --base origin/$CHANGE_TARGET --comment-out docpulse-flag.md
  '''
}
// post docpulse-flag.md via your SCM's Jenkins plugin (GitHub / GitLab / Bitbucket)
```

Notes to include: `repair --push` works on any host given push credentials in the
checkout; comment posting is intentionally the CI's job via the `--comment-out`
artifact; GitHub users get `gh` posting by default, other vendors add
`--comment-via none`; map Jenkins vars (`CHANGE_TARGET` for the base branch,
`CHANGE_ID` for the PR/MR number → `DOCPULSE_PR_NUMBER`). Keep the existing
daemon-based `docker run` recipe for CI that has a Docker daemon.

### Component 5 — Testing

- Unit tests for each `ci.py` function against a temp git repo + fake runner:
  - `resolve_base_ref`: ref already resolves → no fetch; missing → fetch invoked
    with the parsed remote/branch.
  - `loop_guard`: HEAD author email == bot → True; human author → False.
  - `ensure_commit_identity`: unset → sets repo-local identity; already set → no-op;
    asserts `--global` is never used.
  - `ensure_safe_directory`: simulated dubious-ownership error → adds
    `safe.directory`; clean probe → no-op.
- Destination tests:
  - `--comment-out` writes the markdown file when a comment exists (and in dry-run).
  - `comment_via="none"` → `gh` never invoked.
  - `comment_via="gh"` + live + pr_number → `gh pr comment` invoked once.
- `entrypoint.sh` stays covered by the existing self-dogfood Action.

## Tradeoffs

- **Loop guard lives in `repair` (single source of truth).** The sidecar recipe
  `docpulse index && docpulse repair --push` will still *index* on a bot-authored
  HEAD before short-circuiting — a few wasted seconds, but never an incorrect push
  (indexing writes only the local `.docpulse/index.json`; it pushes nothing).
  Chosen over duplicating the guard in `entrypoint.sh` + `index`.
- **`safe.directory` is set `--global`** (git's only mechanism for trusting a path).
  It is idempotent and only triggers under a uid mismatch, so local dev is
  unaffected.

## Out of scope

- Per-vendor comment posting APIs (GitLab/Bitbucket) inside DocPulse.
- Authentication portability for `git push` beyond reusing the checkout's existing
  credentials.
