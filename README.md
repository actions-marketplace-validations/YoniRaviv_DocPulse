# DocPulse

![DocPulse — docs that stay in sync with the heartbeat of the codebase](https://raw.githubusercontent.com/YoniRaviv/DocPulse/main/.github/assets/banner.png)

> Docs that stay in sync with the heartbeat of the codebase.

[![GitHub Marketplace](https://img.shields.io/badge/GitHub%20Marketplace-DocPulse-purple?logo=github)](https://github.com/marketplace/actions/docpulse-self-healing-docs)

DocPulse detects documentation sections invalidated by a pull request's code
changes and commits surgical fixes directly onto the PR branch. A deterministic layer
(tree-sitter chunking → code↔doc link graph → diff-driven suspect selection)
decides *what to check*; a bounded agentic layer (an LLM verifier with read/grep
tools, then a style-preserving repairer with a validation pass) decides *stale
or not, and how to fix it*.

## Quickstart (GitHub Action)

```yaml
# .github/workflows/docpulse.yml
name: DocPulse
on: pull_request
jobs:
  docpulse:
    runs-on: ubuntu-latest
    permissions:
      contents: write          # repair mode commits doc fixes onto the PR branch
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.ref }}
          fetch-depth: 0
      - uses: YoniRaviv/DocPulse@v1
        with:
          mode: repair          # or "check" to comment-only
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DOCPULSE_PR_NUMBER: ${{ github.event.pull_request.number }}
```

Embeddings improve link recall and need an embedding key (`OPENAI_API_KEY`). To run without one, set the action input `heuristics-only: true` — linking then uses name mentions only.

In `repair` mode DocPulse commits the doc fix straight onto your PR's branch, so the fix lands in the same PR (same-repo PRs only — DocPulse can't push to a fork, so use `mode: check` for fork-based contributions). It skips itself when the most-recent commit on the branch is already a doc-sync commit, so the auto-fix push never re-triggers an endless loop.

Add a `docpulse.yml` at your repo root (see [Configuration](#configuration)).

## Quickstart (CLI)

```bash
uv tool install docpulse                              # or: pipx install docpulse
docpulse index --root .                               # build the code<->docs link index
docpulse check  --base origin/main                    # verify docs vs the PR diff (exit 1 on drift)
docpulse check  --base origin/main --suspects-only    # keyless: list suspect sections only
docpulse repair --base origin/main                    # print proposed fixes + the dry-run commit plan
docpulse repair --base origin/main --write            # apply fixes to doc files locally (no push)
docpulse repair --base origin/main --push             # commit+push doc fixes onto the current branch (needs GH_TOKEN)
```

`check` exits 0 (clean), 1 (a doc section is stale at/above `flag_threshold`),
or 2 (setup/tool error). `unverified` never fails the build. `repair` uses the same
codes — it exits 1 if drift was found, even after committing a fix, so the auto-fixed
PR still flags for human review.

## Eval numbers

Measured on 12 hand-labeled seed cases (4 per language; 6 stale / 6 accurate)
with `anthropic/claude-haiku-4-5`:

| Metric    | Value |
|-----------|-------|
| Precision | 1.00  |
| Recall    | 1.00  |

The seed cases are deliberately clear-cut; robustness grows as real-world
false-positives are added back as cases. Run `docpulse eval --cases evals/cases`
to reproduce.

## Architecture

```mermaid
flowchart LR
  subgraph Deterministic
    A[tree-sitter chunker] --> B[code↔doc link graph]
    B --> C[git diff → suspects]
  end
  subgraph Agentic
    C --> D[verifier<br/>read/grep tools]
    D --> E[repairer]
    E --> F[validator]
  end
  F --> G[destination:<br/>PR comment + doc-sync commit]
```

## Configuration

```yaml
model: anthropic/claude-sonnet-4-6        # any LiteLLM model string
embedding_model: openai/text-embedding-3-small
docs:
  - path: "docs/**/*.md"
  - path: "README.md"
code:
  include: ["src/**"]
  exclude: ["**/*.test.*", "tests/**"]
confidence:
  auto_fix_threshold: 0.85
  flag_threshold: 0.5
budget:
  max_suspects_per_run: 20
  max_tool_calls_per_suspect: 10
context: [git]
```

Secrets come only from env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …).
`docpulse index --heuristics-only` builds the link graph without embeddings (no key).

## Jenkins / any CI

```bash
# The image entrypoint is env-driven (it always runs `index` then the chosen
# mode with --push). Configure it with -e vars, not CLI args:
docker run --rm \
  -e ANTHROPIC_API_KEY -e GH_TOKEN \
  -e DOCPULSE_MODE=check \
  -e DOCPULSE_BASE_REF=origin/main \
  -e DOCPULSE_PR_NUMBER="$PR_NUMBER" \
  -e DOCPULSE_HEURISTICS_ONLY=true \
  -v "$PWD:/work" -w /work \
  ghcr.io/yoniraviv/docpulse:latest
```

Set `DOCPULSE_PR_NUMBER` to your CI's PR/MR number so the flag comment is posted to
the PR (without it, the comment is only printed to the log). Drop
`DOCPULSE_HEURISTICS_ONLY` and add `-e OPENAI_API_KEY` to use embedding-based linking.

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
    docpulse check --base "origin/$CHANGE_TARGET" --comment-via none --comment-out docpulse-flag.md
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
