from pathlib import Path

import pathspec
import yaml
from pydantic import BaseModel, Field


class DocGlob(BaseModel):
    path: str


class CodeGlobs(BaseModel):
    include: list[str] = ["src/**"]
    exclude: list[str] = []

    def matches(self, path: str) -> bool:
        include = pathspec.PathSpec.from_lines("gitwildmatch", self.include)
        exclude = pathspec.PathSpec.from_lines("gitwildmatch", self.exclude)
        return include.match_file(path) and not exclude.match_file(path)


class ConfidenceConfig(BaseModel):
    auto_fix_threshold: float = 0.85
    flag_threshold: float = 0.5


class LinkingConfig(BaseModel):
    embedding_threshold: float = 0.75
    max_links_per_section: int = 10


class BudgetConfig(BaseModel):
    max_suspects_per_run: int = Field(default=20, ge=0)
    max_tool_calls_per_suspect: int = Field(default=10, ge=0)


class Config(BaseModel):
    model: str | None = None  # required for verify/repair; index/check run without it
    embedding_model: str = "openai/text-embedding-3-small"
    docs: list[DocGlob]
    code: CodeGlobs = CodeGlobs()
    confidence: ConfidenceConfig = ConfidenceConfig()
    linking: LinkingConfig = LinkingConfig()
    budget: BudgetConfig = BudgetConfig()
    context: list[str] = ["git"]


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))
