"""Validate RAG ingestion and plan document-scoped updates without database writes."""
from .core import AuditReport, Issue, audit_chunks
from .ingestion import (
    AcceptancePolicy, DocumentSpec, ExtractionReceipt, Finding, ValidationError,
    ValidationReport, audit_embeddings, audit_ingestion,
)
from .reingestion import (
    ChunkState, DocumentState, Snapshot, UnsafePlanError, UpdatePlan,
    build_snapshot, plan_update, stable_chunk_id, audit_plan_embeddings,
)

from .storage import SQLiteSnapshotStore, StoredPlan

__version__ = "0.1.0"
__all__ = [
    "AuditReport", "Issue", "audit_chunks", "AcceptancePolicy", "DocumentSpec",
    "ExtractionReceipt", "Finding", "ValidationError", "ValidationReport",
    "audit_embeddings", "audit_ingestion", "ChunkState", "DocumentState",
    "Snapshot", "UnsafePlanError", "UpdatePlan", "build_snapshot", "plan_update",
    "stable_chunk_id", "audit_plan_embeddings", "SQLiteSnapshotStore", "StoredPlan",
]

from .extract import (ExtractionResult, receipt_from_callable, pypdf_receipt,
                      text_file_receipt, docx_receipt, pptx_receipt)
from .adapters import assign_chunk_keys, from_langchain_documents, from_llama_index_nodes
from .quality import YieldPolicy, audit_unit_yield, audit_chunk_unit_yield
from .reconcile import ReconciliationReport, reconcile
from .baseline import WarningBaseline, BaselineComparison
__all__ += ["ExtractionResult", "receipt_from_callable", "pypdf_receipt", "assign_chunk_keys",
    "text_file_receipt", "docx_receipt", "pptx_receipt",
    "from_langchain_documents", "from_llama_index_nodes", "YieldPolicy", "audit_unit_yield",
    "audit_chunk_unit_yield", "ReconciliationReport", "reconcile", "WarningBaseline", "BaselineComparison"]

from .existing import audit_existing_index
from .evidence import EvidenceReport
from .cost import EmbeddingCostEstimate, estimate_embedding_cost
from .runs import RunReceipt
from .folder import FolderCheckReport, check_source_folder
__all__ += ['audit_existing_index', 'EvidenceReport', 'EmbeddingCostEstimate',
            'estimate_embedding_cost', 'RunReceipt', 'FolderCheckReport', 'check_source_folder']
