from pathlib import Path

import yaml
from pydantic import BaseModel


class DocGlob(BaseModel):
    path: str


class CodeGlobs(BaseModel):
    include: list[str] = ["src/**"]
    exclude: list[str] = []


class ConfidenceConfig(BaseModel):
    auto_fix_threshold: float = 0.85
    flag_threshold: float = 0.5


class LinkingConfig(BaseModel):
    embedding_threshold: float = 0.75
    max_links_per_section: int = 10


class BudgetConfig(BaseModel):
    max_suspects_per_run: int = 20
    max_tool_calls_per_suspect: int = 10


class Config(BaseModel):
    model: str
    embedding_model: str = "openai/text-embedding-3-small"
    docs: list[DocGlob]
    code: CodeGlobs = CodeGlobs()
    confidence: ConfidenceConfig = ConfidenceConfig()
    linking: LinkingConfig = LinkingConfig()
    budget: BudgetConfig = BudgetConfig()
    context: list[str] = ["git"]


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))
