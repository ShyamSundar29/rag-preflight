"""FAISS adapter plugged into the shared guarded RAG workflow."""
from rag_preflight_reference_common.app import ReferenceApp as BaseReferenceApp
from .config import Settings
from .store import FaissStore, faiss_metadata


class ReferenceApp(BaseReferenceApp):
    def __init__(self, settings: Settings):
        super().__init__(settings, FaissStore, faiss_metadata)
