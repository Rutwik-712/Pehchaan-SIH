from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    CONSTABLE = "constable"
    INVESTIGATOR = "investigator"
    SP = "sp"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignments: Mapped[List["CaseAssignment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="CaseAssignment.user_id"
    )
    refresh_sessions: Mapped[List["RefreshSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    jurisdiction: Mapped[str] = mapped_column(String(160))
    classification: Mapped[str] = mapped_column(String(40), default="RESTRICTED")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignments: Mapped[List["CaseAssignment"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class CaseAssignment(Base):
    __tablename__ = "case_assignments"
    __table_args__ = (UniqueConstraint("case_id", "user_id", name="uq_case_user_assignment"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assigned_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    case: Mapped["Case"] = relationship(back_populates="assignments")
    user: Mapped["User"] = relationship(back_populates="assignments", foreign_keys=[user_id])


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_sessions")


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"
    __table_args__ = (UniqueConstraint("case_id", "sha256", name="uq_case_evidence_sha256"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    storage_backend: Mapped[str] = mapped_column(String(20))
    object_etag: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    object_version_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="registered")
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    integrity_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    pipeline_name: Mapped[str] = mapped_column(String(80), default="evidence_preflight")
    pipeline_version: Mapped[str] = mapped_column(String(40), default="phase5-v1")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    current_stage: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    result_summary: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingStage(Base):
    __tablename__ = "processing_stages"
    __table_args__ = (UniqueConstraint("job_id", "stage_name", name="uq_job_stage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"), index=True)
    stage_name: Mapped[str] = mapped_column(String(80))
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    output_details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingStageAttempt(Base):
    __tablename__ = "processing_stage_attempts"
    __table_args__ = (UniqueConstraint("stage_id", "attempt_number", name="uq_stage_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    stage_id: Mapped[str] = mapped_column(ForeignKey("processing_stages.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class ExtractedDocument(Base):
    __tablename__ = "extracted_documents"
    __table_args__ = (UniqueConstraint("job_id", name="uq_extracted_document_job"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True)
    extracted_text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64), index=True)
    extraction_method: Mapped[str] = mapped_column(String(80))
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    mean_confidence_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    language_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    language_confidence_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ExtractedMention(Base):
    __tablename__ = "extracted_mentions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("extracted_documents.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[str] = mapped_column(String(500))
    normalized_value: Mapped[str] = mapped_column(String(500), index=True)
    start_char: Mapped[int] = mapped_column(Integer)
    end_char: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    source_excerpt: Mapped[str] = mapped_column(String(700), default="")
    extraction_method: Mapped[str] = mapped_column(String(80))
    confidence_percent: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ExtractedRelation(Base):
    __tablename__ = "extracted_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("extracted_documents.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True)
    subject_mention_id: Mapped[str] = mapped_column(ForeignKey("extracted_mentions.id", ondelete="CASCADE"), index=True)
    object_mention_id: Mapped[str] = mapped_column(ForeignKey("extracted_mentions.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(80), index=True)
    source_excerpt: Mapped[str] = mapped_column(String(700), default="")
    extraction_method: Mapped[str] = mapped_column(String(80))
    confidence_percent: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(30), index=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    original_value: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    corrected_value: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    reviewed_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ResolutionRun(Base):
    __tablename__ = "resolution_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    entity_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    settings_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ResolvedEntity(Base):
    __tablename__ = "resolved_entities"
    __table_args__ = (UniqueConstraint("case_id", "entity_type", "normalized_value", name="uq_case_resolved_entity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    canonical_value: Mapped[str] = mapped_column(String(500))
    normalized_value: Mapped[str] = mapped_column(String(500), index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    resolution_method: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    pagerank: Mapped[float] = mapped_column(Float, default=0.0)
    betweenness: Mapped[float] = mapped_column(Float, default=0.0)
    degree: Mapped[int] = mapped_column(Integer, default=0)
    community_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_level: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ResolvedMention(Base):
    __tablename__ = "resolved_mentions"

    mention_id: Mapped[str] = mapped_column(ForeignKey("extracted_mentions.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("resolved_entities.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("resolution_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    match_probability: Mapped[float] = mapped_column(Float, default=1.0)
    resolution_method: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResolutionCandidate(Base):
    __tablename__ = "resolution_candidates"
    __table_args__ = (
        UniqueConstraint("case_id", "left_mention_id", "right_mention_id", name="uq_resolution_candidate_pair"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    left_mention_id: Mapped[str] = mapped_column(ForeignKey("extracted_mentions.id", ondelete="CASCADE"), index=True)
    right_mention_id: Mapped[str] = mapped_column(ForeignKey("extracted_mentions.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    match_probability: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(80), default="splink_duckdb")
    status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    reviewed_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    resolution_run_id: Mapped[str] = mapped_column(ForeignKey("resolution_runs.id"), index=True)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="projected", index=True)
    analytics_version: Mapped[str] = mapped_column(String(80), default="neo4j-gds-phase6-v1")
    algorithm_details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class GraphAlert(Base):
    __tablename__ = "graph_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("graph_snapshots.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("resolved_entities.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(80), index=True)
    severity_level: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    explanation: Mapped[str] = mapped_column(String(700))
    evidence_summary: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AssistantQuery(Base):
    __tablename__ = "assistant_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(String(1000))
    answer_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="completed", index=True)
    evidence_sufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage_percent: Mapped[int] = mapped_column(Integer, default=0)
    limitations: Mapped[List[str]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(80), default="deterministic_grounded")
    model_id: Mapped[str] = mapped_column(String(160), default="reviewed-evidence-v1")
    prompt_version: Mapped[str] = mapped_column(String(80), default="assistant-phase8-v1")
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    feedback: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    feedback_notes: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AssistantCitation(Base):
    __tablename__ = "assistant_citations"
    __table_args__ = (UniqueConstraint("query_id", "citation_number", name="uq_query_citation_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    query_id: Mapped[str] = mapped_column(ForeignKey("assistant_queries.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("extracted_documents.id", ondelete="SET NULL"), nullable=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    citation_number: Mapped[int] = mapped_column(Integer)
    source_label: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    excerpt: Mapped[str] = mapped_column(String(700))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CaseReport(Base):
    __tablename__ = "case_reports"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_case_report_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(240))
    scope_note: Mapped[str] = mapped_column(String(1000), default="")
    classification: Mapped[str] = mapped_column(String(40), default="RESTRICTED")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    limitations: Mapped[List[str]] = mapped_column(JSON, default=list)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    object_key: Mapped[Optional[str]] = mapped_column(String(700), nullable=True, unique=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    approved_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approval_notes: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(60), index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    case_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cases.id"), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(30), default="success")
    request_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    previous_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)


@event.listens_for(Session, "before_flush")
def prevent_audit_mutation(session: Session, _flush_context, _instances) -> None:
    protected_types = (AuditLog, ReviewDecision)
    if any(isinstance(item, protected_types) for item in session.dirty):
        raise ValueError("Audit and review decision records are append-only and cannot be updated")
    if any(isinstance(item, protected_types) for item in session.deleted):
        raise ValueError("Audit and review decision records are append-only and cannot be deleted")
