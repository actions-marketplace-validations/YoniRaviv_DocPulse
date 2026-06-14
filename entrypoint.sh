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
