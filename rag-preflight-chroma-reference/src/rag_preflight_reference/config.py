"""Application-specific defaults for the shared reference pipeline."""
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from rag_preflight_reference_common.config import Settings as BaseSettings


@dataclass(frozen=True)
class Settings(BaseSettings):
    ROOT_ENV: ClassVar[str] = 'RAG_PREFLIGHT_CHROMA_ROOT'
    LEGACY_ROOT_ENVS: ClassVar[tuple[str, ...]] = ('RAG_PREFLIGHT_REFERENCE_ROOT',)
    DEFAULT_ROOT: ClassVar[Path] = Path(__file__).resolve().parents[2]
    collection_name: str = 'research_papers_preflight'
