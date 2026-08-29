from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    full_name: str
    email: str
    role: str
    is_active: bool
    permissions: List[str]


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    jurisdiction: str
    classification: str
    description: str
    is_active: bool


class AssignmentCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)


class AssignmentOut(BaseModel):
    case_id: str
    user_id: str
    username: str
    assigned_by_id: str


class AccessCheckOut(BaseModel):
    case_id: str
    user: str
    role: str
    permission: str
    allowed: bool = True


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    storage_backend: str
    status: str
    uploaded_by_id: str
    created_at: datetime
    integrity_verified_at: Optional[datetime]
    deduplicated: bool = False


class IntegrityOut(BaseModel):
    evidence_id: str
    valid: bool
    expected_sha256: str
    actual_sha256: str
    expected_size: int
    actual_size: int
    verified_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    occurred_at: datetime
    user_id: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    case_id: Optional[str]
    outcome: str
    request_id: Optional[str]
    client_ip: Optional[str]
    details: Dict[str, Any]
    previous_hash: str
    entry_hash: str


class AuditChainOut(BaseModel):
    valid: bool
    entries_checked: int
    first_invalid_entry_id: Optional[str]


class ProcessingStageAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_number: int
    celery_task_id: Optional[str]
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_ms: Optional[int]
    output_details: Dict[str, Any]
    error_code: Optional[str]
    error_message: Optional[str]


class ProcessingStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage_name: str
    sequence: int
    status: str
    progress_percent: int
    attempt_count: int
    output_details: Dict[str, Any]
    error_code: Optional[str]
    error_message: Optional[str]
    queued_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    attempts: List[ProcessingStageAttemptOut] = Field(default_factory=list)


class ProcessingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    evidence_id: str
    requested_by_id: str
    pipeline_name: str
    pipeline_version: str
    status: str
    current_stage: Optional[str]
    progress_percent: int
    celery_task_id: Optional[str]
    retry_count: int
    error_code: Optional[str]
    error_message: Optional[str]
    result_summary: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    reused: bool = False
    stages: List[ProcessingStageOut] = Field(default_factory=list)


class ExtractedDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    case_id: str
    evidence_id: str
    text_sha256: str
    extraction_method: str
    page_count: int
    mean_confidence_percent: Optional[int]
    language_code: Optional[str]
    language_name: Optional[str]
    language_confidence_percent: Optional[int]
    needs_review: bool
    created_at: datetime


class ExtractedTextOut(ExtractedDocumentOut):
    extracted_text: str


class ExtractedMentionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    document_id: str
    case_id: str
    evidence_id: str
    entity_type: str
    value: str
    normalized_value: str
    start_char: int
    end_char: int
    page_number: int
    source_excerpt: str
    extraction_method: str
    confidence_percent: int
    status: str
    needs_review: bool
    created_at: datetime
    updated_at: datetime


class ExtractedRelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    document_id: str
    case_id: str
    evidence_id: str
    subject_mention_id: str
    object_mention_id: str
    relation_type: str
    source_excerpt: str
    extraction_method: str
    confidence_percent: int
    status: str
    needs_review: bool
    created_at: datetime
    updated_at: datetime


class ExtractionBundleOut(BaseModel):
    document: ExtractedDocumentOut
    mentions: List[ExtractedMentionOut]
    relations: List[ExtractedRelationOut]


class ReviewRelationOut(ExtractedRelationOut):
    subject_value: str
    subject_entity_type: str
    object_value: str
    object_entity_type: str
    page_number: int


class ReviewQueueOut(BaseModel):
    mentions: List[ExtractedMentionOut]
    relations: List[ReviewRelationOut]
    total_pending: int


class ReviewRequest(BaseModel):
    decision: Literal["confirm", "reject", "correct"]
    corrected_value: Optional[str] = Field(default=None, max_length=500)
    corrected_type: Optional[str] = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=1000)


class ReviewDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    job_id: str
    target_type: str
    target_id: str
    decision: str
    original_value: Dict[str, Any]
    corrected_value: Dict[str, Any]
    notes: str
    reviewed_by_id: str
    created_at: datetime


class ResolutionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    status: str
    mention_count: int
    entity_count: int
    candidate_count: int
    settings_snapshot: Dict[str, Any]
    error_message: Optional[str]
    requested_by_id: str
    created_at: datetime
    completed_at: Optional[datetime]


class ResolutionCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    left_mention_id: str
    right_mention_id: str
    left_value: str
    right_value: str
    entity_type: str
    match_probability: float
    method: str
    status: str
    reviewed_by_id: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime


class ResolutionCandidateReview(BaseModel):
    decision: Literal["confirm", "reject"]
    notes: str = Field(default="", max_length=1000)


class ResolvedEntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    entity_type: str
    canonical_value: str
    normalized_value: str
    mention_count: int
    resolution_method: str
    confidence: float
    pagerank: float
    betweenness: float
    degree: int
    community_id: Optional[int]
    priority_score: float
    priority_level: int


class GraphNodeOut(BaseModel):
    id: str
    entity_type: str
    label: str
    aliases: List[str]
    mention_count: int
    evidence_count: int
    pagerank: float
    betweenness: float
    degree: int
    community_id: Optional[int]
    priority_score: float
    priority_level: int


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    relation_type: str
    evidence_id: str
    document_id: str
    page_number: int
    source_excerpt: str
    extraction_method: str
    confidence_percent: int
    observed_at: datetime


class GraphBundleOut(BaseModel):
    case_id: str
    snapshot_id: Optional[str]
    generated_at: Optional[datetime]
    nodes: List[GraphNodeOut]
    edges: List[GraphEdgeOut]
    disclaimer: str = "Structural prominence and alerts are investigative leads, not guilt determinations."


class GraphSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    resolution_run_id: str
    node_count: int
    edge_count: int
    status: str
    analytics_version: str
    algorithm_details: Dict[str, Any]
    created_by_id: str
    created_at: datetime


class GraphAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    snapshot_id: str
    entity_id: str
    rule_code: str
    severity_level: int
    title: str
    explanation: str
    evidence_summary: Dict[str, Any]
    status: str
    created_at: datetime


class GraphAlertReview(BaseModel):
    notes: str = Field(default="", max_length=1000)


class AssistantQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class AssistantCitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    citation_number: int
    evidence_id: str
    document_id: Optional[str]
    target_type: str
    target_id: str
    source_label: str
    page_number: int
    excerpt: str


class AssistantQueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    question: str
    answer_text: str
    status: str
    evidence_sufficient: bool
    coverage_percent: int
    limitations: List[str]
    provider: str
    model_id: str
    prompt_version: str
    requested_by_id: str
    feedback: Optional[str]
    feedback_notes: str
    created_at: datetime
    citations: List[AssistantCitationOut] = Field(default_factory=list)
    disclaimer: str = "Analytical assistance only. Verify every citation; this output does not determine guilt."


class AssistantFeedbackRequest(BaseModel):
    rating: Literal["correct", "incomplete", "unsupported", "access_problem"]
    notes: str = Field(default="", max_length=1000)


class ReportCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    scope_note: str = Field(default="", max_length=1000)


class ReportDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str = Field(default="", max_length=1000)


class CaseReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    version: int
    title: str
    scope_note: str
    classification: str
    status: str
    content: Dict[str, Any]
    limitations: List[str]
    citation_count: int
    sha256: Optional[str]
    size_bytes: Optional[int]
    celery_task_id: Optional[str]
    error_message: Optional[str]
    created_by_id: str
    approved_by_id: Optional[str]
    approval_notes: str
    created_at: datetime
    completed_at: Optional[datetime]
    approved_at: Optional[datetime]
    disclaimer: str = "This brief summarizes reviewed evidence and does not determine guilt."


class GraphAnalyticsOut(BaseModel):
    snapshot: GraphSnapshotOut
    rankings: List[ResolvedEntityOut]
    alerts: List[GraphAlertOut]
    disclaimer: str = "Scores describe graph structure and review priority; they do not indicate guilt."


class TimelineEventOut(BaseModel):
    relation_id: str
    observed_at: datetime
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    evidence_id: str
    source_excerpt: str


class EvidencePathOut(BaseModel):
    found: bool
    node_ids: List[str]
    edges: List[GraphEdgeOut]
    hop_count: int
    disclaimer: str = "A graph path shows reviewed connections, not guilt or causation."
