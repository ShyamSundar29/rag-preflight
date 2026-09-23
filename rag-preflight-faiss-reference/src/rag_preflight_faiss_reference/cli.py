"""FAISS command entry point for the shared reference workflow."""
from rag_preflight_reference_common.cli import main as shared_main, parser as shared_parser
from .app import ReferenceApp
from .config import Settings
from .store import FaissStore


def parser():
    return shared_parser('rag-preflight-faiss-reference', 'FAISS', Settings.ROOT_ENV)


def main(argv: list[str] | None = None) -> int:
    return shared_main(argv, Settings, ReferenceApp, FaissStore, 'rag-preflight-faiss-reference', 'FAISS')
