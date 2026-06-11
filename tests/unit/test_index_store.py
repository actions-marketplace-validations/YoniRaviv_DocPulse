from docpulse.config import Config, DocGlob
from docpulse.indexing.index_store import build_index, load_index, save_index, update_index


def write_repo(root):
    (root / "src").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "auth.py").write_text(
        "class AuthService:\n    def login(self, user):\n        return user\n"
    )
    (root / "docs" / "auth.md").write_text(
        "# Auth\n\nCall `AuthService.login` to sign in.\n"
    )


def make_config() -> Config:
    return Config(model="m", docs=[DocGlob(path="docs/**/*.md")])


def test_build_save_load_round_trip(tmp_path):
    write_repo(tmp_path)
    index = build_index(tmp_path, make_config(), embedder=None, base_commit="abc")
    assert any(c.id == "src/auth.py::AuthService.login" for c in index.chunks)
    assert any(s.id == "docs/auth.md#auth" for s in index.sections)
    assert any(link.source == "heuristic" for link in index.links)

    save_index(index, tmp_path / ".docpulse" / "index.json")
    assert load_index(tmp_path / ".docpulse" / "index.json") == index


def test_incremental_update_recomputes_only_changed_files(tmp_path):
    write_repo(tmp_path)
    config = make_config()
    index = build_index(tmp_path, config, embedder=None, base_commit="abc")
    (tmp_path / "src" / "auth.py").write_text(
        "class AuthService:\n    def login(self, user, mfa):\n        return user\n"
    )
    updated = update_index(
        index, tmp_path, config, embedder=None,
        changed_paths=["src/auth.py"], base_commit="def",
    )
    login = next(c for c in updated.chunks if c.id == "src/auth.py::AuthService.login")
    assert "mfa" in login.signature
    assert updated.base_commit == "def"
    # unchanged docs were not re-parsed away
    assert any(s.id == "docs/auth.md#auth" for s in updated.sections)


def test_binary_files_in_code_globs_are_skipped(tmp_path):
    write_repo(tmp_path)
    (tmp_path / "src" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")
    index = build_index(tmp_path, make_config(), embedder=None, base_commit="abc")
    assert any(c.id == "src/auth.py::AuthService.login" for c in index.chunks)

    (tmp_path / "src" / "icon.png").write_bytes(b"\x89PNG\xff\xfe")
    updated = update_index(
        index, tmp_path, make_config(), embedder=None,
        changed_paths=["src/icon.png"], base_commit="def",
    )
    assert updated.base_commit == "def"


def test_incremental_update_respects_code_excludes(tmp_path):
    write_repo(tmp_path)
    config = Config(
        model="m",
        docs=[DocGlob(path="docs/**/*.md")],
        code={"include": ["**"], "exclude": ["scripts/**"]},
    )
    index = build_index(tmp_path, config, embedder=None, base_commit="abc")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text("def helper():\n    return 1\n")
    updated = update_index(
        index, tmp_path, config, embedder=None,
        changed_paths=["scripts/tool.py"], base_commit="def",
    )
    assert not any(c.path == "scripts/tool.py" for c in updated.chunks)
