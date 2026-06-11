from docpulse.diffing.change_filter import ChangedChunk
from docpulse.diffing.suspects import select_suspects
from docpulse.models import DocSection, Index, Link
from tests.unit.test_models import make_chunk


def make_section(id: str) -> DocSection:
    return DocSection(
        id=id, path=id.split("#")[0], heading_path=["X"], content="...",
        content_hash=f"hash-{id}", mentions=[], start_line=1, end_line=5,
    )


def make_index(sections, links) -> Index:
    return Index(version=1, base_commit="abc", chunks=[], sections=sections, links=links)


def link(section_id: str, chunk_id: str, score: float = 1.0) -> Link:
    return Link(section_id=section_id, chunk_id=chunk_id, source="heuristic", score=score)


def test_changed_chunk_surfaces_linked_sections_only():
    index = make_index(
        [make_section("docs/auth.md#login"), make_section("docs/auth.md#sessions")],
        [link("docs/auth.md#login", "src/auth.py::AuthService.login")],
    )
    changed = [ChangedChunk(chunk=make_chunk(), change_size=2)]
    suspects, total = select_suspects(changed, index, max_suspects=20)
    assert total == 1
    assert [s.section.id for s in suspects] == ["docs/auth.md#login"]
    assert suspects[0].changed_chunks[0].link_score == 1.0
    assert suspects[0].changed_chunks[0].change_size == 2
    assert suspects[0].score == 2.0  # 1.0 * 2


def test_unlinked_change_surfaces_nothing():
    index = make_index([make_section("docs/auth.md#login")], [])
    changed = [ChangedChunk(chunk=make_chunk(), change_size=2)]
    assert select_suspects(changed, index, max_suspects=20) == ([], 0)


def test_ranked_by_link_score_times_change_size_and_capped():
    chunk_a = make_chunk(id="src/m.py::a", name="a")
    chunk_b = make_chunk(id="src/m.py::b", name="b")
    index = make_index(
        [make_section("d.md#s1"), make_section("d.md#s2"), make_section("d.md#s3")],
        [
            link("d.md#s1", "src/m.py::a", score=0.8),
            link("d.md#s2", "src/m.py::b", score=1.0),
            link("d.md#s3", "src/m.py::a", score=0.9),
        ],
    )
    changed = [
        ChangedChunk(chunk=chunk_a, change_size=10),  # s1: 8.0, s3: 9.0
        ChangedChunk(chunk=chunk_b, change_size=1),   # s2: 1.0
    ]
    suspects, total = select_suspects(changed, index, max_suspects=2)
    assert total == 3
    assert [s.section.id for s in suspects] == ["d.md#s3", "d.md#s1"]


def test_section_with_two_changed_chunks_sums_and_dedupes():
    chunk_a = make_chunk(id="src/m.py::a", name="a")
    chunk_b = make_chunk(id="src/m.py::b", name="b")
    index = make_index(
        [make_section("d.md#s1")],
        [link("d.md#s1", "src/m.py::a", score=1.0), link("d.md#s1", "src/m.py::b", score=0.5)],
    )
    changed = [
        ChangedChunk(chunk=chunk_a, change_size=2),
        ChangedChunk(chunk=chunk_b, change_size=4),
    ]
    suspects, total = select_suspects(changed, index, max_suspects=20)
    assert total == 1
    assert len(suspects) == 1
    assert len(suspects[0].changed_chunks) == 2
    assert suspects[0].score == 4.0  # 1.0*2 + 0.5*4
