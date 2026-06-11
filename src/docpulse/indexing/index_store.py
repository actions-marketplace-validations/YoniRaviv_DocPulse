from pathlib import Path

import pathspec

from docpulse.config import Config
from docpulse.indexing.chunk_rules import rules_for_path
from docpulse.indexing.code_chunker import chunk_source
from docpulse.indexing.doc_parser import parse_markdown
from docpulse.indexing.embeddings import Embedder
from docpulse.indexing.link_graph import build_links
from docpulse.models import Index


def _code_files(root: Path, config: Config) -> list[str]:
    return sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and config.code.matches(str(p.relative_to(root)))
    )


def _doc_files(root: Path, config: Config) -> list[str]:
    spec = pathspec.PathSpec.from_lines("gitwildmatch", [d.path for d in config.docs])
    return sorted(
        str(p.relative_to(root))
        for p in root.rglob("*.md")
        if p.is_file() and spec.match_file(str(p.relative_to(root)))
    )


def _embeddings(index_parts, embedder: Embedder | None):
    if embedder is None:
        return None
    chunks, sections = index_parts
    texts = {c.content_hash: c.content for c in chunks}
    texts |= {s.content_hash: s.content for s in sections}
    return embedder.embed(texts)


def _link(chunks, sections, config: Config, embedder):
    return build_links(
        sections, chunks, _embeddings((chunks, sections), embedder),
        threshold=config.linking.embedding_threshold,
        max_links_per_section=config.linking.max_links_per_section,
    )


def build_index(root: Path, config: Config, embedder: Embedder | None, base_commit: str) -> Index:
    chunks = [
        chunk
        for rel in _code_files(root, config)
        if rules_for_path(rel) is not None
        for chunk in chunk_source(rel, (root / rel).read_text())
    ]
    sections = [
        section
        for rel in _doc_files(root, config)
        for section in parse_markdown(rel, (root / rel).read_text())
    ]
    return Index(
        version=1, base_commit=base_commit, chunks=chunks, sections=sections,
        links=_link(chunks, sections, config, embedder),
    )


def update_index(
    index: Index, root: Path, config: Config, embedder: Embedder | None,
    changed_paths: list[str], base_commit: str,
) -> Index:
    changed = set(changed_paths)
    chunks = [c for c in index.chunks if c.path not in changed]
    sections = [s for s in index.sections if s.path not in changed]
    for rel in changed:
        file_path = root / rel
        if not file_path.exists():
            continue  # deleted file: stale entries already dropped above
        if rel.endswith(".md"):
            sections.extend(parse_markdown(rel, file_path.read_text()))
        else:
            if not config.code.matches(rel):
                continue  # excluded by code globs: skip
            if rules_for_path(rel) is None:
                continue  # unsupported file type: don't read
            chunks.extend(chunk_source(rel, file_path.read_text()))
    return Index(
        version=1, base_commit=base_commit, chunks=chunks, sections=sections,
        links=_link(chunks, sections, config, embedder),  # cheap: embeddings cached by hash
    )


def save_index(index: Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(index.model_dump_json())


def load_index(path: Path) -> Index:
    return Index.model_validate_json(path.read_text())
