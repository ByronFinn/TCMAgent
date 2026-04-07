from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VisitType(StrEnum):
    INITIAL = "initial"
    FOLLOW_UP = "follow_up"
    UNKNOWN = "unknown"


class Channel(StrEnum):
    WEB = "web"
    APP = "app"
    MINI_PROGRAM = "mini_program"
    API = "api"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class CaseStage(StrEnum):
    CREATED = "created"
    TRIAGED = "triaged"
    INITIAL_CANDIDATES_GENERATED = "initial_candidates_generated"
    INTAKE_IN_PROGRESS = "intake_in_progress"
    INTAKE_PAUSED_FOR_RISK = "intake_paused_for_risk"
    INTAKE_CONVERGED = "intake_converged"
    SAFETY_REVIEWED = "safety_reviewed"
    SUMMARY_GENERATED = "summary_generated"
    HANDOFF_REQUIRED = "handoff_required"
    CLOSED = "closed"


class FactType(StrEnum):
    SYMPTOM = "symptom"
    SIGN = "sign"
    OBSERVATION = "observation"
    POPULATION_TAG = "population_tag"
    RED_FLAG = "red_flag"
    HISTORY = "history"
    MEDICATION = "medication"
    ALLERGY = "allergy"
    DEMOGRAPHIC = "demographic"
    OTHER = "other"


class CandidateType(StrEnum):
    DISEASE = "disease"
    PATTERN = "pattern"
    PATHOGENESIS = "pathogenesis"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceType(StrEnum):
    SUPPORT = "support"
    CONFLICT = "conflict"
    EXCLUDE = "exclude"
    RISK = "risk"
    INFO = "info"


class QuestionType(StrEnum):
    BOOLEAN = "boolean"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    SCALE = "scale"
    FREE_TEXT = "free_text"


class SummaryAudience(StrEnum):
    PATIENT = "patient"
    CLINICIAN = "clinician"


class PatientProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str | None = None
    name: str | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    gender: str | None = None
    is_pregnant: bool | None = None
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    known_conditions: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    emergency_contact: str | None = None


class NormalizedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(default_factory=lambda: f"fact_{uuid4().hex}")
    fact_type: FactType
    normalized_key: str
    normalized_value: str | bool | int | float | list[str]
    source_text: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_turn_id: str | None = None
    source_question_id: str | None = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("normalized_key")
    @classmethod
    def validate_normalized_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("normalized_key cannot be empty")
        return value


class CandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_type: CandidateType
    name: str
    score: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    category: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str | None = None


class ContradictionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contradiction_id: str = Field(default_factory=lambda: f"contr_{uuid4().hex}")
    field: str
    previous_value: Any | None = None
    new_value: Any | None = None
    reason: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceNodeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: str
    name: str | None = None


class EvidenceEdgeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation: str
    source_id: str
    target_id: str
    weight: float | None = None


class EvidencePath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    target_type: str
    path_nodes: list[EvidenceNodeRef] = Field(default_factory=list)
    path_edges: list[EvidenceEdgeRef] = Field(default_factory=list)
    summary: str | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: f"evi_{uuid4().hex}")
    target_id: str
    target_type: str
    evidence_type: EvidenceType
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    weight: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MatchedRedFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    red_flag_id: str
    name: str
    severity: Severity
    evidence_refs: list[str] = Field(default_factory=list)
    recommended_route: str | None = None
    notes: str | None = None


class PopulationRiskAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    population_tag: str
    risk_delta: float
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)


class ContraindicationFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contraindication_id: str
    name: str
    severity: Severity
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)


class QuestionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_text: str
    question_type: QuestionType = QuestionType.FREE_TEXT
    goal: str
    discriminates_between: list[str] = Field(default_factory=list)
    target_domain: str | None = None
    priority: float = Field(default=0.0, ge=0.0)
    safety_related: bool = False
    fatigue_cost: float = Field(default=0.0, ge=0.0)
    rationale: str | None = None
    expected_answers: list[str] = Field(default_factory=list)


class RiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: f"risk_{uuid4().hex}")
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    safe_to_continue: bool = True
    recommend_offline_visit: bool = False
    recommend_human_review: bool = False
    recommended_route: str | None = None
    decision_reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"audit_{uuid4().hex}")
    event_type: str
    actor: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PatientSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: SummaryAudience = SummaryAudience.PATIENT
    summary_text: str
    next_step_hint: str | None = None
    safety_notice: str | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ClinicianSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: SummaryAudience = SummaryAudience.CLINICIAN
    chief_complaint: str | None = None
    normalized_facts: list[NormalizedFact] = Field(default_factory=list)
    candidate_diseases: list[CandidateItem] = Field(default_factory=list)
    candidate_patterns: list[CandidateItem] = Field(default_factory=list)
    candidate_pathogenesis: list[CandidateItem] = Field(default_factory=list)
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    red_flags: list[MatchedRedFlag] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    missing_critical_facts: list[str] = Field(default_factory=list)
    next_recommended_actions: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class CaseState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    patient_profile: PatientProfile | None = None
    visit_type: VisitType = VisitType.UNKNOWN
    channel: Channel = Channel.UNKNOWN
    chief_complaint: str | None = None

    normalized_facts: list[NormalizedFact] = Field(default_factory=list)
    asked_questions: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    contradictions: list[ContradictionItem] = Field(default_factory=list)
    missing_critical_facts: list[str] = Field(default_factory=list)

    candidate_diseases: list[CandidateItem] = Field(default_factory=list)
    candidate_patterns: list[CandidateItem] = Field(default_factory=list)
    candidate_pathogenesis: list[CandidateItem] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    evidence_paths: list[EvidencePath] = Field(default_factory=list)

    red_flags: list[MatchedRedFlag] = Field(default_factory=list)
    population_risk_adjustments: list[PopulationRiskAdjustment] = Field(default_factory=list)
    contraindication_flags: list[ContraindicationFlag] = Field(default_factory=list)
    risk_decision: RiskDecision | None = None
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    safe_to_continue: bool | None = None

    recommended_next_question: QuestionRecommendation | None = None
    question_rationale: str | None = None

    intake_completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    convergence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    case_stage: CaseStage = CaseStage.CREATED

    audit_log: list[AuditEvent] = Field(default_factory=list)
    clinician_summary: ClinicianSummary | None = None
    patient_summary: PatientSummary | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("chief_complaint")
    @classmethod
    def validate_chief_complaint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


__all__ = [
    "AuditEvent",
    "CandidateItem",
    "CandidateType",
    "CaseStage",
    "CaseState",
    "Channel",
    "ClinicianSummary",
    "ContradictionItem",
    "ContraindicationFlag",
    "EvidenceEdgeRef",
    "EvidenceItem",
    "EvidenceNodeRef",
    "EvidencePath",
    "EvidenceType",
    "FactType",
    "MatchedRedFlag",
    "NormalizedFact",
    "PatientProfile",
    "PatientSummary",
    "PopulationRiskAdjustment",
    "QuestionRecommendation",
    "QuestionType",
    "RiskDecision",
    "RiskLevel",
    "Severity",
    "SummaryAudience",
    "VisitType",
]
