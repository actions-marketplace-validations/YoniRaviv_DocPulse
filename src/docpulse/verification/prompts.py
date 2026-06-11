from docpulse.verification.verifier import VerifyBundle

SYSTEM_PROMPT = """\
You are DocPulse's documentation verifier. Given a documentation section and a \
code change (the OLD version and the NEW version), decide whether the code change \
made the documentation INACCURATE.

You have read-only tools (read_file, grep, list_symbols) to inspect the current \
(NEW) codebase. Use them to confirm what the code actually does before judging.

When you are ready, call `submit_verdict` exactly once with:
- status: "stale" if the doc now contradicts the code, "accurate" if it is still \
correct, "unverified" if you genuinely cannot tell.
- confidence: 0..1 (only meaningful for "stale").
- diagnosis: one or two sentences naming the specific inaccuracy (or why it is fine).
- evidence: a list of "path:line" references that justify the verdict.

Rules:
- Only say "stale" when you are confident the documentation is now WRONG. A \
refactor, rename of an internal symbol, comment change, or behavior-preserving \
change is NOT staleness.
- If you run out of tool calls, cannot find the relevant code, or are unsure, \
return "unverified". NEVER guess "stale". A false "stale" is worse than "unverified".
"""


def build_user_message(bundle: VerifyBundle) -> dict[str, str]:
    intent = bundle.intent.strip() or "(no intent provided)"
    content = f"""\
## Documentation section: {bundle.section_id}

{bundle.doc_content}

## Change intent (why the code changed)

{intent}

## Code BEFORE the change

```
{bundle.old_code}
```

## Code AFTER the change

```
{bundle.new_code}
```

Inspect the NEW codebase with the tools if needed, then call submit_verdict."""
    return {"role": "user", "content": content}
