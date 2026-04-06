"""Case management tools for structured state updates.

This module provides the first MVP implementation of case-state management for
TCMAgent. It is intentionally pragmatic:

- Works out of the box with an in-memory store
- Uses strongly typed Pydantic request / response models
- Operates on `CaseState` and related schema models
- Keeps business logic explicit and auditable
- Is ready to be wrapped as agent tools later

Design notes
------------
The long-term architecture should move storage behind a repository layer. For the
current scaffolding stage, this module includes a small in-memory store so the
rest of the system can start working immediately.

These functions are suitable for:
- API routes
- service layer calls
- future agent-tool wrappers
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tcm_agent.schemas.case import (
    AuditEvent,
    CandidateItem,
    CaseStage,
    CaseState,
    Channel,
    ClinicianSummary,
    ContradictionItem,
    EvidenceItem,
    MatchedRedFlag,
    NormalizedFact,
    PatientProfile,
    PatientSummary,
    QuestionRecommendation,
    RiskDecision,
    VisitType,
)


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    """Generate a stable prefixed ID."""
    return f"{prefix}_{uuid4().hex}"


class CaseToolError(RuntimeError):
    """Raised when a case-state operation cannot be completed."""


class CaseNotFoundError(CaseToolError):
    """Raised when a case does not exist."""


class CaseStageLockedError(CaseToolError):
    """Raised when a stage transition or mutation is blocked by a lock."""


class InvalidCaseTransitionError(CaseToolError):
    """Raised when a requested stage transition is not allowed."""


class ToolMetadata(BaseModel):
    """Common metadata returned by tool responses."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    tool_name: str
    tool_version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utcnow)
    message: str = ""


class PatientProfileInput(BaseModel):
    """Input model for creating or enriching patient profile data."""

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

    def to_schema(self) -> PatientProfile:
        """Convert input into the shared schema object."""
        return PatientProfile(**self.model_dump())


class CreateCaseInput(BaseModel):
    """Request payload for creating a new case."""

    model_config = ConfigDict(extra="forbid")

    patient_profile: PatientProfileInput | None = None
    visit_type: VisitType = VisitType.UNKNOWN
    channel: Channel = Channel.UNKNOWN
    chief_complaint: str | None = None
    source: str | None = None
    actor: str = "system"
    request_id: str | None = None
    trace_id: str | None = None

    @field_validator("chief_complaint")
    @classmethod
    def _normalize_chief_complaint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CreateCaseOutput(BaseModel):
    """Response for case creation."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    case_stage: CaseStage
    created_at: datetime
    initialized_fields: list[str]
    metadata: ToolMetadata


class GetCaseStateInput(BaseModel):
    """Request payload for fetching case state."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    actor: str = "system"
    trace_id: str | None = None


class GetCaseStateOutput(BaseModel):
    """Response for fetching case state."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_state: CaseState
    metadata: ToolMetadata


class UpdateCaseFactsInput(BaseModel):
    """Request payload for updating normalized facts."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    facts: list[NormalizedFact] = Field(default_factory=list)
    source: str = "unknown"
    actor: str = "system"
    request_id: str | None = None
    trace_id: str | None = None
    overwrite_strategy: str = Field(
        default="merge_by_key",
        description="Supported: merge_by_key, append_only",
    )


class UpdateCaseFactsOutput(BaseModel):
    """Response for fact updates."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    updated_fields: list[str] = Field(default_factory=list)
    contradictions: list[ContradictionItem] = Field(default_factory=list)
    facts_count: int = 0
    case_stage: CaseStage
    case_state: CaseState
    metadata: ToolMetadata


class RecordQuestionAskedInput(BaseModel):
    """Request payload for recording a question ask event."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    question_id: str
    question_text: str
    rationale: str | None = None
    actor: str = "system"
    trace_id: str | None = None


class RecordQuestionAskedOutput(BaseModel):
    """Response for recording a question."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    question_record_id: str
    asked_count: int
    case_state: CaseState
    metadata: ToolMetadata


class AppendCaseEvidenceInput(BaseModel):
    """Request payload for adding evidence items to a case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    actor: str = "system"
    trace_id: str | None = None


class AppendCaseEvidenceOutput(BaseModel):
    """Response for appending evidence."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    appended_count: int
    case_state: CaseState
    metadata: ToolMetadata


class SetCaseStageInput(BaseModel):
    """Request payload for changing case stage."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    new_stage: CaseStage
    reason: str
    actor: str = "system"
    trace_id: str | None = None


class SetCaseStageOutput(BaseModel):
    """Response for stage transition."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    previous_stage: CaseStage
    current_stage: CaseStage
    case_state: CaseState
    metadata: ToolMetadata


class LockCaseStageInput(BaseModel):
    """Request payload for locking a stage."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    stage: CaseStage
    reason: str
    actor: str = "system"
    trace_id: str | None = None


class LockCaseStageOutput(BaseModel):
    """Response for locking a stage."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    locked: bool
    locked_stage: CaseStage
    case_state: CaseState
    metadata: ToolMetadata


class SaveCaseSummaryInput(BaseModel):
    """Request payload for attaching a patient/clinician summary to a case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    patient_summary: PatientSummary | None = None
    clinician_summary: ClinicianSummary | None = None
    actor: str = "system"
    trace_id: str | None = None


class SaveCaseSummaryOutput(BaseModel):
    """Response for summary updates."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_state: CaseState
    metadata: ToolMetadata


class SaveRiskDecisionInput(BaseModel):
    """Request payload for recording a risk decision."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    risk_decision: RiskDecision
    red_flags: list[MatchedRedFlag] = Field(default_factory=list)
    actor: str = "system"
    trace_id: str | None = None


class SaveRiskDecisionOutput(BaseModel):
    """Response for recording a risk decision."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_state: CaseState
    metadata: ToolMetadata


@dataclass(slots=True)
class CaseRecord:
    """Internal record containing mutable case state and lock metadata."""

    state: CaseState
    locked_stages: set[CaseStage] = field(default_factory=set)


class InMemoryCaseStore:
    """A minimal in-memory case store for scaffolding and local development."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, CaseRecord] = {}

    def create(self, state: CaseState) -> None:
        with self._lock:
            if state.case_id in self._records:
                raise CaseToolError(f"Case '{state.case_id}' already exists.")
            self._records[state.case_id] = CaseRecord(state=state)

    def get(self, case_id: str) -> CaseRecord:
        with self._lock:
            record = self._records.get(case_id)
            if record is None:
                raise CaseNotFoundError(f"Case '{case_id}' was not found.")
            return record

    def save(self, record: CaseRecord) -> None:
        with self._lock:
            self._records[record.state.case_id] = record

    def list_case_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._records.keys())

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


CASE_STORE = InMemoryCaseStore()

_ALLOWED_STAGE_TRANSITIONS: dict[CaseStage, set[CaseStage]] = {
    CaseStage.CREATED: {
        CaseStage.TRIAGED,
        CaseStage.INTAKE_IN_PROGRESS,
        CaseStage.HANDOFF_REQUIRED,
    },
    CaseStage.TRIAGED: {
        CaseStage.INITIAL_CANDIDATES_GENERATED,
        CaseStage.INTAKE_PAUSED_FOR_RISK,
        CaseStage.HANDOFF_REQUIRED,
    },
    CaseStage.INITIAL_CANDIDATES_GENERATED: {
        CaseStage.INTAKE_IN_PROGRESS,
        CaseStage.INTAKE_PAUSED_FOR_RISK,
    },
    CaseStage.INTAKE_IN_PROGRESS: {
        CaseStage.INTAKE_IN_PROGRESS,
        CaseStage.INTAKE_CONVERGED,
        CaseStage.INTAKE_PAUSED_FOR_RISK,
        CaseStage.HANDOFF_REQUIRED,
    },
    CaseStage.INTAKE_PAUSED_FOR_RISK: {
        CaseStage.SAFETY_REVIEWED,
        CaseStage.HANDOFF_REQUIRED,
        CaseStage.CLOSED,
    },
    CaseStage.INTAKE_CONVERGED: {
        CaseStage.SAFETY_REVIEWED,
        CaseStage.SUMMARY_GENERATED,
        CaseStage.HANDOFF_REQUIRED,
    },
    CaseStage.SAFETY_REVIEWED: {
        CaseStage.SUMMARY_GENERATED,
        CaseStage.HANDOFF_REQUIRED,
        CaseStage.CLOSED,
    },
    CaseStage.SUMMARY_GENERATED: {
        CaseStage.HANDOFF_REQUIRED,
        CaseStage.CLOSED,
    },
    CaseStage.HANDOFF_REQUIRED: {
        CaseStage.CLOSED,
    },
    CaseStage.CLOSED: set(),
}


def _metadata(
    *,
    tool_name: str,
    trace_id: str | None,
    message: str,
) -> ToolMetadata:
    return ToolMetadata(tool_name=tool_name, trace_id=trace_id or _new_id("trace"), message=message)


def _deepcopy_state(state: CaseState) -> CaseState:
    """Return a detached copy of the case state."""
    return CaseState.model_validate(deepcopy(state.model_dump()))


def _append_audit_event(
    state: CaseState,
    *,
    actor: str,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    state.audit_log.append(
        AuditEvent(
            event_type=event_type,
            actor=actor,
            message=message,
            payload=payload or {},
            created_at=utcnow(),
        )
    )
    state.updated_at = utcnow()


def _normalize_string_list(values: Iterable[str]) -> list[str]:
    """Normalize and deduplicate string lists while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _check_stage_lock(record: CaseRecord, stage: CaseStage) -> None:
    if stage in record.locked_stages:
        raise CaseStageLockedError(f"Stage '{stage.value}' is locked for this case.")


def _validate_transition(previous: CaseStage, new: CaseStage) -> None:
    if previous == new:
        return
    allowed = _ALLOWED_STAGE_TRANSITIONS.get(previous, set())
    if new not in allowed:
        raise InvalidCaseTransitionError(
            f"Invalid case-stage transition: '{previous.value}' -> '{new.value}'."
        )


def create_case(payload: CreateCaseInput) -> CreateCaseOutput:
    """Create a new case and initialize its structured state."""
    case_id = _new_id("case")
    created_at = utcnow()

    patient_profile = payload.patient_profile.to_schema() if payload.patient_profile else None

    state = CaseState(
        case_id=case_id,
        patient_profile=patient_profile,
        visit_type=payload.visit_type,
        channel=payload.channel,
        chief_complaint=payload.chief_complaint,
        case_stage=CaseStage.CREATED,
        created_at=created_at,
        updated_at=created_at,
    )

    initialized_fields = ["case_id", "visit_type", "channel", "case_stage", "created_at"]
    if patient_profile is not None:
        initialized_fields.append("patient_profile")
    if payload.chief_complaint:
        initialized_fields.append("chief_complaint")

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="case_created",
        message="Case created successfully.",
        payload={
            "source": payload.source,
            "request_id": payload.request_id,
            "initialized_fields": initialized_fields,
        },
    )

    CASE_STORE.create(state)

    return CreateCaseOutput(
        case_id=case_id,
        case_stage=state.case_stage,
        created_at=created_at,
        initialized_fields=initialized_fields,
        metadata=_metadata(
            tool_name="create_case",
            trace_id=payload.trace_id,
            message="Case created successfully.",
        ),
    )


def get_case_state(payload: GetCaseStateInput) -> GetCaseStateOutput:
    """Fetch the full structured case state."""
    record = CASE_STORE.get(payload.case_id)
    return GetCaseStateOutput(
        case_state=_deepcopy_state(record.state),
        metadata=_metadata(
            tool_name="get_case_state",
            trace_id=payload.trace_id,
            message="Case state retrieved.",
        ),
    )


def update_case_facts(payload: UpdateCaseFactsInput) -> UpdateCaseFactsOutput:
    """Merge normalized facts into the case state.

    Strategy
    --------
    - `merge_by_key`: replace facts sharing `(fact_type, normalized_key)`
    - `append_only`: append facts without replacement
    """
    record = CASE_STORE.get(payload.case_id)
    _check_stage_lock(record, record.state.case_stage)

    state = record.state
    contradictions: list[ContradictionItem] = []
    updated_fields: list[str] = []

    if payload.overwrite_strategy not in {"merge_by_key", "append_only"}:
        raise CaseToolError(f"Unsupported overwrite strategy: {payload.overwrite_strategy}")

    facts = payload.facts
    if payload.overwrite_strategy == "append_only":
        state.normalized_facts.extend(facts)
        updated_fields.append("normalized_facts")
    else:
        existing_index: dict[tuple[str, str], int] = {
            (item.fact_type.value, item.normalized_key): idx
            for idx, item in enumerate(state.normalized_facts)
        }

        for fact in facts:
            key = (fact.fact_type.value, fact.normalized_key)
            existing_idx = existing_index.get(key)

            if existing_idx is None:
                state.normalized_facts.append(fact)
                existing_index[key] = len(state.normalized_facts) - 1
                continue

            existing = state.normalized_facts[existing_idx]
            if existing.normalized_value != fact.normalized_value:
                contradictions.append(
                    ContradictionItem(
                        field=f"{fact.fact_type.value}.{fact.normalized_key}",
                        previous_value=existing.normalized_value,
                        new_value=fact.normalized_value,
                        reason=f"Fact value changed from source '{payload.source}'.",
                    )
                )

            state.normalized_facts[existing_idx] = fact

        updated_fields.append("normalized_facts")

    if contradictions:
        state.contradictions.extend(contradictions)
        updated_fields.append("contradictions")

    # Heuristic completeness estimate for MVP scaffolding.
    unique_keys = {(f.fact_type.value, f.normalized_key) for f in state.normalized_facts}
    state.intake_completeness_score = min(len(unique_keys) / 12.0, 1.0)
    updated_fields.append("intake_completeness_score")

    # Stage promotion when facts arrive.
    if state.case_stage in {
        CaseStage.CREATED,
        CaseStage.TRIAGED,
        CaseStage.INITIAL_CANDIDATES_GENERATED,
    }:
        state.case_stage = CaseStage.INTAKE_IN_PROGRESS
        updated_fields.append("case_stage")

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="facts_updated",
        message=f"Updated {len(facts)} normalized fact(s).",
        payload={
            "source": payload.source,
            "request_id": payload.request_id,
            "overwrite_strategy": payload.overwrite_strategy,
            "updated_fields": updated_fields,
            "contradiction_count": len(contradictions),
        },
    )

    CASE_STORE.save(record)

    return UpdateCaseFactsOutput(
        updated_fields=updated_fields,
        contradictions=contradictions,
        facts_count=len(state.normalized_facts),
        case_stage=state.case_stage,
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="update_case_facts",
            trace_id=payload.trace_id,
            message=f"Updated {len(facts)} fact(s).",
        ),
    )


def record_question_asked(payload: RecordQuestionAskedInput) -> RecordQuestionAskedOutput:
    """Record that a question was asked during the consultation."""
    record = CASE_STORE.get(payload.case_id)
    _check_stage_lock(record, record.state.case_stage)

    state = record.state

    if payload.question_id not in state.asked_questions:
        state.asked_questions.append(payload.question_id)

    if (
        state.recommended_next_question
        and state.recommended_next_question.question_id == payload.question_id
    ):
        state.recommended_next_question = None
        state.question_rationale = payload.rationale or state.question_rationale

    question_record_id = _new_id("qrec")
    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="question_asked",
        message="Question recorded as asked.",
        payload={
            "question_record_id": question_record_id,
            "question_id": payload.question_id,
            "question_text": payload.question_text,
            "rationale": payload.rationale,
        },
    )

    CASE_STORE.save(record)

    return RecordQuestionAskedOutput(
        question_record_id=question_record_id,
        asked_count=len(state.asked_questions),
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="record_question_asked",
            trace_id=payload.trace_id,
            message="Question ask event recorded.",
        ),
    )


def append_case_evidence(payload: AppendCaseEvidenceInput) -> AppendCaseEvidenceOutput:
    """Append structured evidence items to the case."""
    record = CASE_STORE.get(payload.case_id)
    _check_stage_lock(record, record.state.case_stage)

    state = record.state
    state.evidence_items.extend(payload.evidence_items)

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="evidence_appended",
        message=f"Appended {len(payload.evidence_items)} evidence item(s).",
        payload={"count": len(payload.evidence_items)},
    )

    CASE_STORE.save(record)

    return AppendCaseEvidenceOutput(
        appended_count=len(payload.evidence_items),
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="append_case_evidence",
            trace_id=payload.trace_id,
            message=f"Appended {len(payload.evidence_items)} evidence item(s).",
        ),
    )


def set_case_stage(payload: SetCaseStageInput) -> SetCaseStageOutput:
    """Transition the case to a new stage with validation."""
    record = CASE_STORE.get(payload.case_id)
    previous_stage = record.state.case_stage

    _check_stage_lock(record, previous_stage)
    _validate_transition(previous_stage, payload.new_stage)

    record.state.case_stage = payload.new_stage
    _append_audit_event(
        record.state,
        actor=payload.actor,
        event_type="case_stage_changed",
        message=f"Case stage changed: {previous_stage.value} -> {payload.new_stage.value}",
        payload={"reason": payload.reason},
    )

    CASE_STORE.save(record)

    return SetCaseStageOutput(
        previous_stage=previous_stage,
        current_stage=record.state.case_stage,
        case_state=_deepcopy_state(record.state),
        metadata=_metadata(
            tool_name="set_case_stage",
            trace_id=payload.trace_id,
            message="Case stage updated.",
        ),
    )


def lock_case_stage(payload: LockCaseStageInput) -> LockCaseStageOutput:
    """Lock a case stage to prevent further unsafe mutation."""
    record = CASE_STORE.get(payload.case_id)
    record.locked_stages.add(payload.stage)

    _append_audit_event(
        record.state,
        actor=payload.actor,
        event_type="case_stage_locked",
        message=f"Locked stage '{payload.stage.value}'.",
        payload={"reason": payload.reason},
    )

    CASE_STORE.save(record)

    return LockCaseStageOutput(
        locked=True,
        locked_stage=payload.stage,
        case_state=_deepcopy_state(record.state),
        metadata=_metadata(
            tool_name="lock_case_stage",
            trace_id=payload.trace_id,
            message=f"Stage '{payload.stage.value}' locked.",
        ),
    )


def save_case_summary(payload: SaveCaseSummaryInput) -> SaveCaseSummaryOutput:
    """Attach patient and/or clinician summary objects to a case."""
    record = CASE_STORE.get(payload.case_id)
    state = record.state

    if payload.patient_summary is not None:
        state.patient_summary = payload.patient_summary
    if payload.clinician_summary is not None:
        state.clinician_summary = payload.clinician_summary

    if payload.patient_summary or payload.clinician_summary:
        if state.case_stage in {
            CaseStage.INTAKE_CONVERGED,
            CaseStage.SAFETY_REVIEWED,
            CaseStage.HANDOFF_REQUIRED,
        }:
            state.case_stage = CaseStage.SUMMARY_GENERATED

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="case_summary_saved",
        message="Case summary saved.",
        payload={
            "patient_summary": payload.patient_summary is not None,
            "clinician_summary": payload.clinician_summary is not None,
        },
    )

    CASE_STORE.save(record)

    return SaveCaseSummaryOutput(
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="save_case_summary",
            trace_id=payload.trace_id,
            message="Case summary saved.",
        ),
    )


def save_risk_decision(payload: SaveRiskDecisionInput) -> SaveRiskDecisionOutput:
    """Record a formal risk decision into the case state."""
    record = CASE_STORE.get(payload.case_id)
    state = record.state

    state.risk_decision = payload.risk_decision
    state.risk_level = payload.risk_decision.risk_level
    state.safe_to_continue = payload.risk_decision.safe_to_continue
    state.red_flags = payload.red_flags

    if not payload.risk_decision.safe_to_continue:
        state.case_stage = CaseStage.INTAKE_PAUSED_FOR_RISK
    else:
        if state.case_stage == CaseStage.INTAKE_CONVERGED:
            state.case_stage = CaseStage.SAFETY_REVIEWED

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="risk_decision_saved",
        message="Risk decision saved to case state.",
        payload={
            "decision_id": payload.risk_decision.decision_id,
            "risk_level": payload.risk_decision.risk_level.value,
            "safe_to_continue": payload.risk_decision.safe_to_continue,
            "red_flag_count": len(payload.red_flags),
        },
    )

    CASE_STORE.save(record)

    return SaveRiskDecisionOutput(
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="save_risk_decision",
            trace_id=payload.trace_id,
            message="Risk decision saved.",
        ),
    )


def update_case_candidates(
    *,
    case_id: str,
    candidate_diseases: list[CandidateItem] | None = None,
    candidate_patterns: list[CandidateItem] | None = None,
    candidate_pathogenesis: list[CandidateItem] | None = None,
    recommended_next_question: QuestionRecommendation | None = None,
    question_rationale: str | None = None,
    convergence_score: float | None = None,
    actor: str = "system",
    trace_id: str | None = None,
) -> GetCaseStateOutput:
    """Convenience helper for graph/service layers to update candidate fields."""
    record = CASE_STORE.get(case_id)
    state = record.state

    changed_fields: list[str] = []

    if candidate_diseases is not None:
        state.candidate_diseases = candidate_diseases
        changed_fields.append("candidate_diseases")

    if candidate_patterns is not None:
        state.candidate_patterns = candidate_patterns
        changed_fields.append("candidate_patterns")

    if candidate_pathogenesis is not None:
        state.candidate_pathogenesis = candidate_pathogenesis
        changed_fields.append("candidate_pathogenesis")

    if recommended_next_question is not None:
        state.recommended_next_question = recommended_next_question
        changed_fields.append("recommended_next_question")

    if question_rationale is not None:
        state.question_rationale = question_rationale
        changed_fields.append("question_rationale")

    if convergence_score is not None:
        state.convergence_score = max(0.0, min(convergence_score, 1.0))
        changed_fields.append("convergence_score")

    if state.case_stage in {CaseStage.TRIAGED, CaseStage.CREATED} and any(
        field_name in changed_fields
        for field_name in (
            "candidate_diseases",
            "candidate_patterns",
            "candidate_pathogenesis",
        )
    ):
        state.case_stage = CaseStage.INITIAL_CANDIDATES_GENERATED
        changed_fields.append("case_stage")

    _append_audit_event(
        state,
        actor=actor,
        event_type="case_candidates_updated",
        message="Updated candidate and reasoning fields.",
        payload={"changed_fields": changed_fields},
    )

    CASE_STORE.save(record)

    return GetCaseStateOutput(
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="update_case_candidates",
            trace_id=trace_id,
            message="Case candidates updated.",
        ),
    )


def enrich_patient_profile(
    *,
    case_id: str,
    profile: PatientProfileInput,
    actor: str = "system",
    trace_id: str | None = None,
) -> GetCaseStateOutput:
    """Merge new patient-profile information into an existing case."""
    record = CASE_STORE.get(case_id)
    state = record.state

    existing = state.patient_profile or PatientProfile()
    merged_data = existing.model_dump()
    new_data = profile.model_dump()

    for key, value in new_data.items():
        if value in (None, [], ""):
            continue

        if isinstance(value, list):
            previous = merged_data.get(key) or []
            merged_data[key] = _normalize_string_list([*previous, *value])
        else:
            merged_data[key] = value

    state.patient_profile = PatientProfile(**merged_data)

    _append_audit_event(
        state,
        actor=actor,
        event_type="patient_profile_enriched",
        message="Patient profile enriched.",
        payload={"fields": [k for k, v in new_data.items() if v not in (None, [], "")]},
    )

    CASE_STORE.save(record)

    return GetCaseStateOutput(
        case_state=_deepcopy_state(state),
        metadata=_metadata(
            tool_name="enrich_patient_profile",
            trace_id=trace_id,
            message="Patient profile updated.",
        ),
    )


__all__ = [
    "CASE_STORE",
    "AppendCaseEvidenceInput",
    "AppendCaseEvidenceOutput",
    "CaseNotFoundError",
    "CaseRecord",
    "CaseStageLockedError",
    "CaseToolError",
    "CreateCaseInput",
    "CreateCaseOutput",
    "GetCaseStateInput",
    "GetCaseStateOutput",
    "InMemoryCaseStore",
    "InvalidCaseTransitionError",
    "LockCaseStageInput",
    "LockCaseStageOutput",
    "PatientProfileInput",
    "RecordQuestionAskedInput",
    "RecordQuestionAskedOutput",
    "SaveCaseSummaryInput",
    "SaveCaseSummaryOutput",
    "SaveRiskDecisionInput",
    "SaveRiskDecisionOutput",
    "SetCaseStageInput",
    "SetCaseStageOutput",
    "ToolMetadata",
    "UpdateCaseFactsInput",
    "UpdateCaseFactsOutput",
    "append_case_evidence",
    "create_case",
    "enrich_patient_profile",
    "get_case_state",
    "lock_case_stage",
    "record_question_asked",
    "save_case_summary",
    "save_risk_decision",
    "set_case_stage",
    "update_case_candidates",
    "update_case_facts",
]
