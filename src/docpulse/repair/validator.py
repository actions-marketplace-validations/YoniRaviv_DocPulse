import json
import re
from collections import Counter
from typing import Any

from docpulse.llm import LLMError
from docpulse.models import Repair
from docpulse.repair.repairer import RepairBundle

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def _blocks(text: str) -> list[str]:
    """Split text into paragraph blocks on blank lines (whitespace-only allowed)."""
    return [b for b in (p.strip("\n") for p in _BLANK_LINE.split(text)) if b.strip()]


def preservation_ratio(original: str, new: str) -> float:
    """Fraction of original paragraph blocks surviving byte-identical in `new`.

    Deterministic, no LLM. Counts with multiplicity: if the original has a block
    twice and the new text has it once, only one is counted as preserved.
    Returns 1.0 when the original has no blocks.
    """
    original_blocks = _blocks(original)
    if not original_blocks:
        return 1.0
    available = Counter(_blocks(new))
    kept = 0
    for block in original_blocks:
        if available[block] > 0:
            available[block] -= 1
            kept += 1
    return kept / len(original_blocks)


SUBMIT_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_validation",
        "description": "Submit the validation judgment for a repaired section.",
        "parameters": {
            "type": "object",
            "properties": {
                "accurate_vs_code": {"type": "boolean"},
                "style_consistent": {"type": "boolean"},
                "notes": {"type": "string"},
            },
            "required": ["accurate_vs_code", "style_consistent", "notes"],
        },
    },
}


def validate(
    client: Any,
    repair: Repair,
    bundle: RepairBundle,
    min_preservation: float = 0.5,
) -> Repair:
    """Set validation_passed on a Repair.

    validation_passed is True only when ALL hold:
    - preservation_ratio(original, new) >= min_preservation (deterministic), AND
    - the LLM judges the rewrite accurate vs the NEW code, AND
    - the LLM judges the style consistent with the original.

    min_preservation defaults to 0.5: at least half the original paragraph blocks
    must survive byte-identical in the repaired output.  This guards against the
    repairer doing a wholesale rewrite of a section instead of a surgical fix —
    only the stale block(s) should change; the surrounding context must be left
    untouched.

    Any LLM/parse failure fails safe (validation_passed=False). Returns a new
    Repair (the input is not mutated).
    """
    from docpulse.repair.prompts import (
        VALIDATOR_SYSTEM_PROMPT,
        build_validation_user_message,
    )

    preserved = preservation_ratio(bundle.doc_content, repair.new_content)
    messages = [
        {"role": "system", "content": VALIDATOR_SYSTEM_PROMPT},
        build_validation_user_message(repair.new_content, bundle.new_code),
    ]
    try:
        message = client.complete(messages, tools=[SUBMIT_VALIDATION_SCHEMA])
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            raise ValueError("no tool call")
        args = json.loads(tool_calls[0].function.arguments or "{}")
        accurate = bool(args["accurate_vs_code"])
        style_ok = bool(args["style_consistent"])
    except (LLMError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        accurate = style_ok = False

    passed = preserved >= min_preservation and accurate and style_ok
    return repair.model_copy(update={"validation_passed": passed})
