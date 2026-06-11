from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from docpulse.config import CodeGlobs, Config, DocGlob
from docpulse.indexing.index_store import build_index
from docpulse.verification.verifier import VerifyBundle, verify


@dataclass(frozen=True)
class EvalCase:
    name: str
    path: Path
    expected_status: str  # "stale" | "accurate"
    intent: str
    doc_content: str
    old_code: str
    new_code: str


@dataclass(frozen=True)
class CaseResult:
    name: str
    expected: str  # "stale" | "accurate"
    predicted: str  # "stale" | "accurate" | "unverified"
    confidence: float
    diagnosis: str


@dataclass(frozen=True)
class EvalReport:
    rows: list[CaseResult]
    precision: float
    recall: float
    total: int


def _read_tree(directory: Path) -> str:
    """Concatenate every file under `directory` with a path header, sorted."""
    parts = []
    for file in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = file.relative_to(directory)
        parts.append(f"### {rel}\n{file.read_text(errors='replace')}")
    return "\n\n".join(parts)


def load_cases(cases_dir: Path) -> list[EvalCase]:
    """Load every `<case>/` directory holding before/, after/, doc.md, label.yml."""
    cases = []
    for case_dir in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
        label = yaml.safe_load((case_dir / "label.yml").read_text())
        cases.append(
            EvalCase(
                name=case_dir.name,
                path=case_dir,
                expected_status=label["status"],
                intent=label.get("intent", "") or "",
                doc_content=(case_dir / "doc.md").read_text(),
                old_code=_read_tree(case_dir / "before"),
                new_code=_read_tree(case_dir / "after"),
            )
        )
    return cases


def _eval_index(after_dir: Path) -> Any:
    """Build a heuristics-only index of the after/ tree so list_symbols has data."""
    config = Config(
        docs=[DocGlob(path="**/*.md")],
        code=CodeGlobs(include=["**"], exclude=[]),
    )
    return build_index(after_dir, config, embedder=None, base_commit="after")


def run_case(client: Any, case: EvalCase, max_tool_calls: int) -> CaseResult:
    after_dir = case.path / "after"
    index = _eval_index(after_dir)
    bundle = VerifyBundle(
        section_id=case.name,
        doc_content=case.doc_content,
        old_code=case.old_code,
        new_code=case.new_code,
        intent=case.intent,
    )
    verdict = verify(client, after_dir, index, bundle, max_tool_calls)
    return CaseResult(
        name=case.name,
        expected=case.expected_status,
        predicted=verdict.status,
        confidence=verdict.confidence,
        diagnosis=verdict.diagnosis,
    )


def evaluate(client: Any, cases_dir: Path, max_tool_calls: int) -> EvalReport:
    rows = [run_case(client, c, max_tool_calls) for c in load_cases(cases_dir)]
    # Positive class = "stale". unverified/accurate are both "not stale" predictions.
    tp = sum(r.expected == "stale" and r.predicted == "stale" for r in rows)
    fp = sum(r.expected != "stale" and r.predicted == "stale" for r in rows)
    fn = sum(r.expected == "stale" and r.predicted != "stale" for r in rows)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return EvalReport(rows=rows, precision=precision, recall=recall, total=len(rows))
