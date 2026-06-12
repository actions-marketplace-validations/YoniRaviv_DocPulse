#!/bin/sh
set -eu

MODE="${DOCPULSE_MODE:-check}"
CONFIG="${DOCPULSE_CONFIG:-docpulse.yml}"
WORK="${GITHUB_WORKSPACE:-$(pwd)}"

BOT_EMAIL="docpulse-bot@users.noreply.github.com"

BASE_REF="${GITHUB_BASE_REF:-main}"
BASE="${DOCPULSE_BASE_REF:-origin/${BASE_REF}}"

# Actions checks out into a dir owned by a different uid; mark it safe for git.
git config --global --add safe.directory "$WORK" || true
git config --global user.email "$BOT_EMAIL"
git config --global user.name "docpulse[bot]"
# Populate the remote-tracking ref so `origin/<base>` resolves even on a
# shallow PR checkout (plain `fetch origin <base>` only sets FETCH_HEAD).
git -C "$WORK" fetch --no-tags --depth=50 origin \
  "+refs/heads/${BASE_REF}:refs/remotes/origin/${BASE_REF}" || true

# Loop guard: if the latest commit is DocPulse's own doc-sync, do nothing
# (prevents the pushed fix from re-triggering an endless run).
LAST_AUTHOR_EMAIL="$(git -C "$WORK" log -1 --format='%ae' 2>/dev/null || true)"
if [ "$LAST_AUTHOR_EMAIL" = "$BOT_EMAIL" ]; then
  echo "DocPulse: latest commit is a DocPulse doc-sync; skipping to avoid a loop."
  exit 0
fi

docpulse index --root "$WORK" --config "$WORK/$CONFIG"
exec docpulse "$MODE" --base "$BASE" --root "$WORK" --config "$WORK/$CONFIG" --push
