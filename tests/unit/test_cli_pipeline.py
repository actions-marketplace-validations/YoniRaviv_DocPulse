from typer.testing import CliRunner

import docpulse.cli as cli
from docpulse.cli import app
from docpulse.models import Repair, RunResult, Verdict

runner = CliRunner()


class _FakeClient:
    tokens_used = 42

    def __init__(self, *a, **k):  # accepts model arg
        pass


def _stub_index_and_config(monkeypatch, tmp_path):
    (tmp_path / ".docpulse").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".docpulse" / "index.json").write_text("{}")
    from docpulse.config import Config, DocGlob
    from docpulse.models import Index

    monkeypatch.setattr(cli, "load_config", lambda p: Config(model="m", docs=[DocGlob(path="**/*.md")]))
    monkeypatch.setattr(cli, "load_index", lambda p: Index(version=1, base_commit="x",
                                                           chunks=[], sections=[], links=[]))
    monkeypatch.setattr(cli, "LLMClient", _FakeClient)


def test_check_exit_1_on_drift(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)
    result_obj = RunResult(
        verdicts=[Verdict(section_id="docs/a.md#x", status="stale", confidence=0.9,
                          diagnosis="renamed", evidence=["a.py:1"])],
        repairs=[], suspects_checked=1, suspects_total=1, tokens_used=42, exit_code=1,
    )
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: result_obj)
    out = runner.invoke(app, ["check", "--root", str(tmp_path), "--base", "main"])
    assert out.exit_code == 1, out.output
    assert "flagged documentation" in out.output
    assert "DocPulse:" in out.output  # summary line


def test_check_exit_0_when_clean(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)
    result_obj = RunResult(verdicts=[], repairs=[], suspects_checked=0, suspects_total=0,
                           tokens_used=0, exit_code=0)
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: result_obj)
    out = runner.invoke(app, ["check", "--root", str(tmp_path), "--base", "main"])
    assert out.exit_code == 0, out.output


def test_repair_prints_diff_and_dry_run_commands(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# X\n\nold body\n")
    from docpulse.models import DocSection, Index

    section = DocSection(id="docs/a.md#x", path="docs/a.md", heading_path=["X"],
                         content="# X\n\nold body", content_hash="h", mentions=[],
                         start_line=1, end_line=3)
    monkeypatch.setattr(cli, "load_index", lambda p: Index(version=1, base_commit="x",
                                                           chunks=[], sections=[section], links=[]))
    result_obj = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="renamed", evidence=[])],
        repairs=[Repair(section_id=section.id, new_content="# X\n\nnew body",
                        confidence=0.95, validation_passed=True, rationale="fix")],
        suspects_checked=1, suspects_total=1, tokens_used=42, exit_code=1,
    )
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: result_obj)
    out = runner.invoke(app, ["repair", "--root", str(tmp_path), "--base", "main"])
    assert out.exit_code == 1, out.output
    assert "new body" in out.output            # unified diff of the proposed fix
    assert "gh pr create" in out.output         # dry-run command listing
    assert (docs / "a.md").read_text() == "# X\n\nold body\n"  # not written without --write


def test_repair_write_applies_files(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# X\n\nold body\n")
    from docpulse.models import DocSection, Index

    section = DocSection(id="docs/a.md#x", path="docs/a.md", heading_path=["X"],
                         content="# X\n\nold body", content_hash="h", mentions=[],
                         start_line=1, end_line=3)
    monkeypatch.setattr(cli, "load_index", lambda p: Index(version=1, base_commit="x",
                                                           chunks=[], sections=[section], links=[]))
    result_obj = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="d", evidence=[])],
        repairs=[Repair(section_id=section.id, new_content="# X\n\nnew body",
                        confidence=0.95, validation_passed=True, rationale="fix")],
        suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: result_obj)
    runner.invoke(app, ["repair", "--root", str(tmp_path), "--base", "main", "--write"])
    assert "new body" in (docs / "a.md").read_text()


def test_check_exit_2_when_pipeline_raises_runtime_error(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("bad ref: no-such-base")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    out = runner.invoke(app, ["check", "--root", str(tmp_path), "--base", "no-such-base"])
    assert out.exit_code == 2, out.output
    assert "bad ref" in out.output


def test_check_exit_2_when_no_model_configured(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)

    def no_model(*a, **k):
        raise ValueError("no model configured; set `model:` in docpulse.yml or pass --model")

    monkeypatch.setattr(cli, "LLMClient", no_model)
    out = runner.invoke(app, ["check", "--root", str(tmp_path), "--base", "main"])
    assert out.exit_code == 2, out.output
    assert "no model configured" in out.output


def test_repair_exit_2_when_pipeline_raises_runtime_error(monkeypatch, tmp_path):
    _stub_index_and_config(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("bad ref: no-such-base")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    out = runner.invoke(app, ["repair", "--root", str(tmp_path), "--base", "no-such-base"])
    assert out.exit_code == 2, out.output
    assert "bad ref" in out.output
