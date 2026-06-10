from docpulse.config import load_config

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
