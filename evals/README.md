# DocPulse Eval Cases

Each case is one directory:

```
<case-name>/
├── before/        # code BEFORE the change (mirrors a repo subtree)
├── after/         # code AFTER the change
├── doc.md         # the documentation section under test
└── label.yml      # ground truth
```

`label.yml`:

```yaml
status: stale | accurate     # is the doc now wrong because of the change?
intent: "one line: why the code changed (the PR-description equivalent)"
reference_correction: "the corrected doc text (used by Phase 4 repair eval; '' if accurate)"
```

`docpulse eval --cases evals/cases --model <m>` runs the verifier over every case
and reports precision/recall. Positive class = `stale`; `unverified` counts as
"not stale".

**Golden rule:** every real-world false positive becomes a new `accurate` case here.
Cases must be hand-verified — a wrong label silently corrupts the metric.
