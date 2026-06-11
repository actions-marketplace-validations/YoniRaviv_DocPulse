from docpulse.repair.repairer import RepairBundle

REPAIRER_SYSTEM_PROMPT = """\
You are DocPulse's documentation repairer. You are given a documentation section \
that has been confirmed STALE by a verifier, the diagnosis of what is wrong, and \
the code change (OLD and NEW) that caused it. Produce a corrected version of the \
section.

Hard constraints:
- Preserve the section's style, tone, formatting, and structure exactly.
- Touch ONLY the parts made inaccurate by the change. Leave every still-correct \
sentence, code block, and paragraph byte-for-byte identical. Do not reword, \
reorder, or "improve" anything that is already correct.
- Base the fix on what the NEW code actually does. Do not invent behavior.
- Return the FULL corrected section text in `new_content` (not a diff).

Call `submit_repair` exactly once with:
- new_content: the complete corrected section.
- rationale: one or two sentences citing the specific code change that caused the \
fix (include a path:line reference where possible).
- confidence: 0..1 — how sure you are the correction is accurate and complete.
"""


def build_repair_user_message(bundle: RepairBundle) -> dict[str, str]:
    evidence = "\n".join(f"- {e}" for e in bundle.evidence) or "(none)"
    intent = bundle.intent.strip() or "(no intent provided)"
    content = f"""\
## Stale documentation section: {bundle.section_id}

{bundle.doc_content}

## Diagnosis (why it is stale)

{bundle.diagnosis}

## Evidence

{evidence}

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

Rewrite the section, changing only what the code change made inaccurate, then \
call submit_repair."""
    return {"role": "user", "content": content}


VALIDATOR_SYSTEM_PROMPT = """\
You are DocPulse's repair validator. You are given a documentation section that \
was rewritten to fix staleness, plus the NEW code it should now describe. Judge \
the rewrite — do NOT rewrite it yourself.

Call `submit_validation` exactly once with:
- accurate_vs_code: true if the rewritten section correctly describes what the \
NEW code does (names, signatures, behavior). false if anything is wrong or invented.
- style_consistent: true if the rewrite keeps the original section's tone, \
formatting, and structure. false if it reworded or restructured correct parts.
- notes: one sentence justifying the judgment.
"""


def build_validation_user_message(new_content: str, new_code: str) -> dict[str, str]:
    content = f"""\
## Rewritten documentation section

{new_content}

## NEW code it must accurately describe

```
{new_code}
```

Judge accuracy and style, then call submit_validation."""
    return {"role": "user", "content": content}
