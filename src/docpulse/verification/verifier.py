import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docpulse.llm import LLMError
from docpulse.models import Index, Verdict
from docpulse.verification.tools import READ_TOOL_SCHEMAS, make_dispatch


@dataclass(frozen=True)
class VerifyBundle:
    """Everything the verifier needs to judge one doc section."""

    section_id: str
    doc_content: str
    old_code: str
    new_code: str
    intent: str


SUBMIT_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_verdict",
        "description": "Submit the final verdict for the documentation section.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["stale", "accurate", "unverified"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "diagnosis": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "confidence", "diagnosis", "evidence"],
        },
    },
}


def _unverified(section_id: str, reason: str) -> Verdict:
    return Verdict(
        section_id=section_id, status="unverified", confidence=0.0,
        diagnosis=reason, evidence=[],
    )


def _verdict_from_args(section_id: str, args: dict[str, Any]) -> Verdict:
    """Build a Verdict from model-supplied args; section_id is injected (not trusted)."""
    status = args["status"]
    if status not in ("stale", "accurate", "unverified"):
        raise ValueError(f"bad status {status!r}")
    return Verdict(
        section_id=section_id,
        status=status,
        confidence=float(args.get("confidence", 0.0)),
        diagnosis=str(args.get("diagnosis", "")),
        evidence=[str(e) for e in args.get("evidence", [])],
    )


def verify(
    client: Any,
    root: Path,
    index: Index,
    bundle: VerifyBundle,
    max_tool_calls: int,
) -> Verdict:
    """Bounded tool-use loop. Returns a Verdict; failure modes -> 'unverified'.

    `client` must expose `complete(messages, tools) -> message` (see LLMClient).
    The loop offers the read tools plus a terminal `submit_verdict` tool and runs
    until the model submits a verdict or `max_tool_calls` model calls are spent.
    """
    # Imported lazily so prompts.py (which imports VerifyBundle from this module)
    # has no circular dependency at module load.
    from docpulse.verification.prompts import SYSTEM_PROMPT, build_user_message

    dispatch = make_dispatch(root, index)
    tools = [*READ_TOOL_SCHEMAS, SUBMIT_VERDICT_SCHEMA]
    messages: list[Any] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        build_user_message(bundle),
    ]

    for _ in range(max_tool_calls):
        try:
            message = client.complete(messages, tools=tools)
        except LLMError as exc:
            return _unverified(bundle.section_id, f"llm error: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _unverified(bundle.section_id, f"unexpected client error: {exc}")

        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            # Model replied with prose instead of a tool call: nudge once and retry.
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append({
                "role": "user",
                "content": "Call submit_verdict (or a read tool); do not answer in prose.",
            })
            continue

        messages.append(message)  # assistant turn carrying the tool_calls
        for call in tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            if name == "submit_verdict":
                if args is None:
                    # Malformed verdict args: tell the model, let it retry within budget.
                    messages.append({
                        "role": "tool", "tool_call_id": call.id, "name": name,
                        "content": "error: arguments were not valid JSON; resend.",
                    })
                    break  # re-enter the loop for a retry call
                try:
                    return _verdict_from_args(bundle.section_id, args)
                except (KeyError, ValueError) as exc:
                    messages.append({
                        "role": "tool", "tool_call_id": call.id, "name": name,
                        "content": f"error: {exc}; resend a valid verdict.",
                    })
                    break
            else:
                result = dispatch(name, args or {})
                messages.append({
                    "role": "tool", "tool_call_id": call.id, "name": name, "content": result,
                })

    return _unverified(bundle.section_id, "tool-call budget exhausted without a verdict")
