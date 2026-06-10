import numpy as np

from docpulse.indexing.link_graph import build_links
from tests.unit.test_models import make_chunk  # reuse the factory

from docpulse.models import DocSection


def make_section(id="docs/auth.md#login", mentions=(), content="...") -> DocSection:
    return DocSection(
        id=id, path="docs/auth.md", heading_path=["Login"], content=content,
        content_hash=f"hash-{id}", mentions=list(mentions), start_line=1, end_line=5,
    )


def test_heuristic_link_on_qualified_and_short_name():
    chunk = make_chunk()  # name "AuthService.login"
    for mention in ("AuthService.login", "login"):
        links = build_links([make_section(mentions=[mention])], [chunk], embeddings=None)
        assert len(links) == 1
        assert links[0].source == "heuristic" and links[0].score == 1.0


def test_embedding_link_above_threshold_only():
    chunk = make_chunk()
    section = make_section(mentions=[])
    embeddings = {
        section.content_hash: np.array([1.0, 0.0]),
        chunk.content_hash: np.array([0.9, 0.1]),  # cosine ~0.994
    }
    links = build_links([section], [chunk], embeddings, threshold=0.75)
    assert len(links) == 1 and links[0].source == "embedding"
    assert 0.99 < links[0].score < 1.0

    far = {section.content_hash: np.array([1.0, 0.0]), chunk.content_hash: np.array([0.0, 1.0])}
    assert build_links([section], [chunk], far, threshold=0.75) == []


def test_heuristic_wins_over_embedding_duplicate():
    chunk = make_chunk()
    section = make_section(mentions=["login"])
    embeddings = {
        section.content_hash: np.array([1.0, 0.0]),
        chunk.content_hash: np.array([1.0, 0.0]),
    }
    links = build_links([section], [chunk], embeddings, threshold=0.75)
    assert len(links) == 1 and links[0].source == "heuristic"


def test_max_links_per_section_cap():
    chunks = [make_chunk(id=f"src/m.py::f{i}", name=f"f{i}", content_hash=f"c{i}") for i in range(5)]
    section = make_section(mentions=[])
    embeddings = {section.content_hash: np.array([1.0, 0.0])}
    embeddings |= {f"c{i}": np.array([1.0, 0.0]) for i in range(5)}
    links = build_links([section], chunks, embeddings, threshold=0.75, max_links_per_section=3)
    assert len(links) == 3
