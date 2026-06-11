import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from docpulse.config import Config
from docpulse.eval.harness import EvalCase, load_cases
from docpulse.llm import LLMError
from docpulse.models import Repair, Verdict
from docpulse.repair.repairer import RepairBundle, repair
from docpulse.repair.routing import Tier, route
from docpulse.repair.validator import preservation_ratio, validate

PRESERVE_GATE = 0.95  # exit-criterion threshold for "untouched paragraphs preserved"

SUBMIT_RUBRIC_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_rubric",
        "description": "Score a repaired doc section against the reference correction.",
        "parameters": {
            "type": "object",
            "properties": {
                "accuracy": {"type": "integer", "minimum": 1, "maximum": 5},
                "completeness": {"type": "integer", "minimum": 1, "maximum": 5},
                "style_fidelity": {"type": "integer", "minimum": 1, "maximum": 5},
                "needs_human_review": {"type": "boolean"},
                "justification": {"type": "string"},
            },
            "required": [
                "accuracy", "completeness", "style_fidelity",
                "needs_human_review", "justification",
            ],
        },
    },
}

RUBRIC_SYSTEM_PROMPT = """\
You are scoring a documentation repair against a hand-written reference \
correction. Score how well the CANDIDATE matches the REFERENCE on three axes \
(1=poor, 5=excellent):
- accuracy: does the candidate state the same correct facts as the reference?
- completeness: does it cover everything the reference fixed (nothing missed)?
- style_fidelity: does it match the reference's tone, formatting, and structure?
Set needs_human_review=true if any score is <= 3 or you are unsure. Call \
submit_rubric exactly once.
"""


@dataclass(frozen=True)
class RubricScore:
    accuracy: int
    completeness: int
    style_fidelity: int
    needs_human_review: bool
    justification: str


@dataclass(frozen=True)
class RepairCaseResult:
    name: str
    preservation: float
    tier: Tier
    rubric: RubricScore
    diff: str


@dataclass(frozen=True)
class RepairEvalReport:
    rows: list[RepairCaseResult]
    total: int
    mean_preservation: float
    pct_preserved_95: float       # fraction of cases with preservation >= 0.95
    mean_accuracy: float
    mean_completeness: float
    mean_style_fidelity: float
    n_flagged: int                # cases with needs_human_review


def synthesize_verdict(case: EvalCase) -> Verdict:
    """Build a stale Verdict from a ground-truth label (isolates repair quality)."""
    return Verdict(
        section_id=case.name,
        status="stale",
        confidence=1.0,
        diagnosis=case.intent or "The documentation is stale relative to the code.",
        evidence=[],
    )


def unified_section_diff(section_id: str, original: str, new: str) -> str:
    """Unified diff between the original section and the repaired section."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{section_id} (original)",
            tofile=f"{section_id} (repaired)",
        )
    )


def _clamp_1_5(value: Any) -> int:
    return max(1, min(5, int(value)))


def judge_repair(client: Any, new_content: str, reference_correction: str) -> RubricScore:
    """LLM rubric scoring the repair against the reference. Fails safe to a
    flagged all-1s score on any LLM/parse failure."""
    messages = [
        {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## REFERENCE correction\n\n{reference_correction}\n\n"
                f"## CANDIDATE repair\n\n{new_content}\n\n"
                "Score the candidate, then call submit_rubric."
            ),
        },
    ]
    try:
        message = client.complete(messages, tools=[SUBMIT_RUBRIC_SCHEMA])
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            raise ValueError("no tool call")
        args = json.loads(tool_calls[0].function.arguments or "{}")
        return RubricScore(
            accuracy=_clamp_1_5(args["accuracy"]),
            completeness=_clamp_1_5(args["completeness"]),
            style_fidelity=_clamp_1_5(args["style_fidelity"]),
            needs_human_review=bool(args["needs_human_review"]),
            justification=str(args.get("justification", "")),
        )
    except (LLMError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return RubricScore(1, 1, 1, True, f"rubric failed: {exc}")


def _reference_correction(case: EvalCase) -> str:
    """Read reference_correction from the case's label.yml."""
    label = yaml.safe_load((case.path / "label.yml").read_text())
    return label.get("reference_correction", "") or ""


def _run_case(client: Any, case: EvalCase, config: Config) -> RepairCaseResult:
    verdict = synthesize_verdict(case)
    bundle = RepairBundle(
        section_id=case.name,
        doc_content=case.doc_content,
        diagnosis=verdict.diagnosis,
        evidence=verdict.evidence,
        old_code=case.old_code,
        new_code=case.new_code,
        intent=case.intent,
    )
    proposed: Repair = repair(client, bundle)
    validated = validate(client, proposed, bundle)
    tier = route(verdict, validated, config)
    preservation = preservation_ratio(case.doc_content, validated.new_content)
    rubric = judge_repair(client, validated.new_content, _reference_correction(case))
    diff = unified_section_diff(case.name, case.doc_content, validated.new_content)
    return RepairCaseResult(
        name=case.name, preservation=preservation, tier=tier, rubric=rubric, diff=diff
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_repairs(client: Any, cases_dir: Path, config: Config) -> RepairEvalReport:
    """Run the repair pipeline over every STALE case and aggregate quality metrics."""
    stale = [c for c in load_cases(cases_dir) if c.expected_status == "stale"]
    rows = [_run_case(client, c, config) for c in stale]
    return RepairEvalReport(
        rows=rows,
        total=len(rows),
        mean_preservation=_mean([r.preservation for r in rows]),
        pct_preserved_95=_mean([1.0 if r.preservation >= PRESERVE_GATE else 0.0 for r in rows]),
        mean_accuracy=_mean([r.rubric.accuracy for r in rows]),
        mean_completeness=_mean([r.rubric.completeness for r in rows]),
        mean_style_fidelity=_mean([r.rubric.style_fidelity for r in rows]),
        n_flagged=sum(r.rubric.needs_human_review for r in rows),
    )
