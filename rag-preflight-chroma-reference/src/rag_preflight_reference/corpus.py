"""Compatibility imports for the shared source-inventory workflow."""
from rag_preflight_reference_common.corpus import (Candidate, CandidateRejected,
    load_manifest, prepare, split_page)

__all__ = ['Candidate', 'CandidateRejected', 'load_manifest', 'prepare', 'split_page']
