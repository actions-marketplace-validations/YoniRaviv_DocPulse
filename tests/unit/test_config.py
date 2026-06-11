from docpulse.config import Config, DocGlob, load_config

YAML = """\
model: anthropic/claude-sonnet-4-6
docs:
  - path: "docs/**/*.md"
code:
  include: ["src/**"]
  exclude: ["tests/**"]
"""


def test_load_with_defaults(tmp_path):
    config_file = tmp_path / "docpulse.yml"
    config_file.write_text(YAML)
    config = load_config(config_file)
    assert config.model == "anthropic/claude-sonnet-4-6"
    assert config.embedding_model == "openai/text-embedding-3-small"  # default
    assert config.docs[0].path == "docs/**/*.md"
    assert config.confidence.auto_fix_threshold == 0.85               # default
    assert config.linking.embedding_threshold == 0.75                 # default
    assert config.budget.max_suspects_per_run == 20                   # default


def test_missing_file_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yml")


def test_model_is_optional_for_llm_less_runs(tmp_path):
    config_file = tmp_path / "docpulse.yml"
    config_file.write_text('docs:\n  - path: "docs/**/*.md"\n')
    config = load_config(config_file)
    assert config.model is None


def test_code_globs_matches():
    from docpulse.config import CodeGlobs

    globs = CodeGlobs(include=["src/**"], exclude=["**/*.test.*", "tests/**"])
    assert globs.matches("src/auth.py")
    assert not globs.matches("tests/test_auth.py")
    assert not globs.matches("src/auth.test.ts")
    assert not globs.matches("README.md")


def test_negative_budget_rejected(tmp_path):
    import pytest

    config_file = tmp_path / "docpulse.yml"
    config_file.write_text(
        'docs:\n  - path: "docs/**/*.md"\nbudget:\n  max_suspects_per_run: -1\n'
    )
    with pytest.raises(ValueError):
        load_config(config_file)


def test_repair_model_defaults_to_none():
    cfg = Config(docs=[DocGlob(path="docs/**/*.md")])
    assert cfg.repair_model is None


def test_resolve_repair_model_falls_back_to_model():
    cfg = Config(docs=[DocGlob(path="d.md")], model="anthropic/big")
    assert cfg.resolve_repair_model() == "anthropic/big"


def test_resolve_repair_model_prefers_repair_model():
    cfg = Config(
        docs=[DocGlob(path="d.md")],
        model="anthropic/big",
        repair_model="anthropic/cheap",
    )
    assert cfg.resolve_repair_model() == "anthropic/cheap"
