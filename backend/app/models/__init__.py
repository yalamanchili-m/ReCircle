"""App models. Importing this package registers all models on Base.metadata."""

from .assistant import AssistantRun, KnowledgeChunk
from .data_ingestion import (
    ExternalDataRecord,
    ExternalDataSource,
    ExternalWarmFactor,
    IngestionRun,
    RawIngestionFile,
)
from .erp import ErpRecord, ErpRun
from .impact import ImpactEstimate
from .material_requirement import MaterialRequirement
from .match import Match
from .organization import Organization
from .passport import MaterialPassport
from .regulation import RegulationNewsItem, RegulationNewsSource, RegulationRefreshRun
from .system import AnalyticsRun, AuditLog, GraphSyncRun, Notification, SymbiosisRun
from .trade import Offer, RecoveryRecord, Transaction
from .user import User
from .waste_listing import WasteListing

__all__ = [
    "AnalyticsRun",
    "AssistantRun",
    "AuditLog",
    "ExternalDataRecord",
    "ExternalDataSource",
    "ExternalWarmFactor",
    "ErpRecord",
    "ErpRun",
    "GraphSyncRun",
    "ImpactEstimate",
    "IngestionRun",
    "RawIngestionFile",
    "KnowledgeChunk",
    "SymbiosisRun",
    "MaterialPassport",
    "MaterialRequirement",
    "Match",
    "Notification",
    "Offer",
    "Organization",
    "RecoveryRecord",
    "RegulationNewsItem",
    "RegulationNewsSource",
    "RegulationRefreshRun",
    "Transaction",
    "User",
    "WasteListing",
]
