#!/bin/sh
set -eu

MODE="${DOCPULSE_MODE:-check}"
CONFIG="${DOCPULSE_CONFIG:-docpulse.yml}"
WORK="${GITHUB_WORKSPACE:-$(pwd)}"

# Self-trigger guard: no-op on DocPulse's own fix branches.
case "${GITHUB_HEAD_REF:-}" in
  docpulse/fix-*)
    echo "DocPulse: on its own fix branch (${GITHUB_HEAD_REF}); nothing to do."
    exit 0
    ;;
esac

BASE_REF="${GITHUB_BASE_REF:-main}"
BASE="${DOCPULSE_BASE_REF:-origin/${BASE_REF}}"

# Actions checks out into a dir owned by a different uid; mark it safe for git.
git config --global --add safe.directory "$WORK" || true
git config --global user.email "docpulse-bot@users.noreply.github.com"
git config --global user.name "docpulse[bot]"
# Populate the remote-tracking ref so `origin/<base>` resolves even on a
# shallow PR checkout (plain `fetch origin <base>` only sets FETCH_HEAD).
git -C "$WORK" fetch --no-tags --depth=50 origin \
  "+refs/heads/${BASE_REF}:refs/remotes/origin/${BASE_REF}" || true

docpulse index --root "$WORK" --config "$WORK/$CONFIG"
exec docpulse "$MODE" --base "$BASE" --root "$WORK" --config "$WORK/$CONFIG" --push
