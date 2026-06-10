import numpy as np

from docpulse.models import CodeChunk, DocSection, Link


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def build_links(
    sections: list[DocSection],
    chunks: list[CodeChunk],
    embeddings: dict[str, np.ndarray] | None,
    threshold: float = 0.75,
    max_links_per_section: int = 10,
) -> list[Link]:
    links: list[Link] = []
    for section in sections:
        mentions = set(section.mentions)
        section_links: list[Link] = []
        linked_chunk_ids: set[str] = set()

        for chunk in chunks:
            short_name = chunk.name.rsplit(".", 1)[-1]
            if chunk.name in mentions or short_name in mentions:
                section_links.append(
                    Link(section_id=section.id, chunk_id=chunk.id, source="heuristic", score=1.0)
                )
                linked_chunk_ids.add(chunk.id)

        if embeddings is not None and section.content_hash in embeddings:
            section_vec = embeddings[section.content_hash]
            candidates: list[Link] = []
            for chunk in chunks:
                if chunk.id in linked_chunk_ids or chunk.content_hash not in embeddings:
                    continue
                score = _cosine(section_vec, embeddings[chunk.content_hash])
                if score >= threshold:
                    candidates.append(
                        Link(
                            section_id=section.id, chunk_id=chunk.id,
                            source="embedding", score=score,
                        )
                    )
            candidates.sort(key=lambda link: link.score, reverse=True)
            section_links.extend(candidates)

        links.extend(section_links[:max_links_per_section])
    return links
