# DocPulse

## Status

Phase 2 complete — `docpulse check --base <ref>` diffs base..head, filters comment/whitespace-only changes via tree-sitter token comparison, and prints linked doc sections ranked by link score × change size (capped by `budget.max_suspects_per_run`, honest "N of M" reporting). Still fully deterministic and keyless with `--heuristics-only` indexing.
