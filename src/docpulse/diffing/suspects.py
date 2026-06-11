from docpulse.diffing.change_filter import ChangedChunk
from docpulse.models import Index, Suspect, SuspectChunk


def select_suspects(
    changed: list[ChangedChunk], index: Index, max_suspects: int
) -> tuple[list[Suspect], int]:
    """Changed chunks -> ranked, capped suspect sections.

    Returns (capped suspects sorted by score desc, uncapped total) so callers
    can report "checked N of M" honestly.
    """
    changed_by_id = {item.chunk.id: item for item in changed}
    sections_by_id = {section.id: section for section in index.sections}

    chunks_by_section: dict[str, list[SuspectChunk]] = {}
    for link in index.links:
        item = changed_by_id.get(link.chunk_id)
        if item is None or link.section_id not in sections_by_id:
            continue
        chunks_by_section.setdefault(link.section_id, []).append(
            SuspectChunk(chunk=item.chunk, link_score=link.score, change_size=item.change_size)
        )

    suspects = [
        Suspect(
            section=sections_by_id[section_id],
            changed_chunks=suspect_chunks,
            score=sum(sc.link_score * sc.change_size for sc in suspect_chunks),
        )
        for section_id, suspect_chunks in chunks_by_section.items()
    ]
    suspects.sort(key=lambda s: s.score, reverse=True)
    return suspects[:max_suspects], len(suspects)
