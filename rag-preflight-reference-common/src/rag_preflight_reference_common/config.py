"""Explicit experiment configuration and local paths."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
from typing import ClassVar, Self

@dataclass(frozen=True)
class Settings:
    ROOT_ENV: ClassVar[str] = 'RAG_PREFLIGHT_REFERENCE_ROOT'
    LEGACY_ROOT_ENVS: ClassVar[tuple[str, ...]] = ()
    DEFAULT_ROOT: ClassVar[Path | None] = None
    root: Path
    source_root: Path
    manifest: Path
    state_root: Path
    runs_root: Path
    namespace: str = 'research-papers'
    pipeline_id: str = 'pypdf-page-word-500tok-v1'
    embedding_model: str = 'text-embedding-3-small'
    embedding_dimensions: int = 1536
    generation_model: str | None = None
    embedding_price_per_million: str = '0.02'
    max_estimated_embedding_usd: str = '0.25'
    max_output_tokens: int = 300
    chunk_token_limit: int = 500
    chunk_overlap_words: int = 35
    collection_name: str = 'research_papers_preflight'

    def __post_init__(self) -> None:
        for name in ('embedding_price_per_million', 'max_estimated_embedding_usd'):
            try:
                price = Decimal(getattr(self, name))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(f'{name} must be a finite nonnegative price') from exc
            if not price.is_finite() or price < 0:
                raise ValueError(f'{name} must be a finite nonnegative price')
        if (type(self.embedding_dimensions) is not int or self.embedding_dimensions < 1
                or type(self.chunk_token_limit) is not int or self.chunk_token_limit < 32
                or type(self.chunk_overlap_words) is not int or self.chunk_overlap_words < 0
                or type(self.max_output_tokens) is not int or self.max_output_tokens < 1):
            raise ValueError('Invalid vector dimensions, chunk limits or output limit')

    @classmethod
    def local(cls, root: Path | None = None) -> Self:
        configured = [(name, os.environ[name]) for name in (cls.ROOT_ENV, *cls.LEGACY_ROOT_ENVS)
                      if os.environ.get(name)]
        if root is None and len({Path(value).expanduser().resolve() for _, value in configured}) > 1:
            names = ', '.join(name for name, _ in configured)
            raise ValueError(f'Conflicting application roots in {names}; set only {cls.ROOT_ENV}')
        selected = root or (Path(configured[0][1]).expanduser() if configured else cls.DEFAULT_ROOT)
        if selected is None:
            raise ValueError('Supply an application root for the shared reference pipeline')
        root = selected.resolve()
        os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(root / 'state/tokenizer-cache'))
        return cls(root, root.parent / 'pdfs', root / 'corpus/manifest.json',
                   root / 'state', root / 'runs')
