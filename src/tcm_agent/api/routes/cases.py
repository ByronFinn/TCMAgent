"""Case API routes for case management."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from tcm_agent.schemas.case import CaseStage, NormalizedFact
from tcm_agent.state.case_store import get_case_store
from tcm_agent.tools.case_tools import (
    CaseNotFoundError,
    CaseStageLockedError,
    CaseToolError,
    CreateCaseInput,
    GetCaseStateInput,
    LockCaseStageInput,
    PatientProfileInput,
    RecordQuestionAskedInput,
    SetCaseStageInput,
    UpdateCaseFactsInput,
    create_case,
    enrich_patient_profile,
    get_case_state,
    lock_case_stage,
    record_question_asked,
    set_case_stage,
    update_case_facts,
)

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseListResponse(BaseModel):
    """Response model for listing cases."""

    model_config = ConfigDict(extra="forbid")

    total_cases: int
    case_ids: list[str]


class ErrorResponse(BaseModel):
    """Simple API error payload."""

    model_config = ConfigDict(extra="forbid")

    detail: str


class UpdateFactsRequest(BaseModel):
    """HTTP request body for appending/updating normalized facts."""

    model_config = ConfigDict(extra="forbid")

    facts: list[NormalizedFact] = Field(default_factory=list)
    source: str = "api"
    actor: str = "api"
    request_id: str | None = None
    trace_id: str | None = None
    overwrite_strategy: str = "merge_by_key"


class StageTransitionRequest(BaseModel):
    """HTTP request body for stage transitions."""

    model_config = ConfigDict(extra="forbid")

    new_stage: CaseStage
    reason: str
    actor: str = "api"
    trace_id: str | None = None


class LockStageRequest(BaseModel):
    """HTTP request body for locking a stage."""

    model_config = ConfigDict(extra="forbid")

    stage: CaseStage
    reason: str
    actor: str = "api"
    trace_id: str | None = None


class QuestionRecordRequest(BaseModel):
    """HTTP request body for recording asked questions."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_text: str
    rationale: str | None = None
    actor: str = "api"
    trace_id: str | None = None


class PatientProfileUpdateRequest(BaseModel):
    """HTTP request body for enriching patient profile data."""

    model_config = ConfigDict(extra="forbid")

    profile: PatientProfileInput
    actor: str = "api"
    trace_id: str | None = None


def _raise_http_from_case_error(exc: Exception) -> NoReturn:
    """Translate domain errors into HTTP responses."""
    if isinstance(exc, CaseNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if isinstance(exc, CaseStageLockedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if isinstance(exc, CaseToolError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected case management error.",
    ) from exc


@router.get(
    "",
    response_model=CaseListResponse,
    summary="List all case IDs",
)
async def list_cases() -> CaseListResponse:
    """Return a lightweight list of all cases currently available."""
    store = get_case_store()
    stats = store.stats()
    return CaseListResponse(
        total_cases=stats.total_cases,
        case_ids=stats.case_ids,
    )


@router.post(
    "",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new case",
)
async def create_case_route(payload: CreateCaseInput) -> dict[str, Any]:
    """Create a new structured consultation case."""
    try:
        result = create_case(payload)
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")


@router.get(
    "/{case_id}",
    response_model=dict[str, Any],
    responses={404: {"model": ErrorResponse}},
    summary="Fetch a case state",
)
async def get_case_route(case_id: str) -> dict[str, Any]:
    """Return the full structured case state for a given case."""
    try:
        result = get_case_state(GetCaseStateInput(case_id=case_id))
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")


@router.post(
    "/{case_id}/facts",
    response_model=dict[str, Any],
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Update normalized facts for a case",
)
async def update_case_facts_route(case_id: str, payload: UpdateFactsRequest) -> dict[str, Any]:
    """Merge normalized facts into an existing case."""
    try:
        result = update_case_facts(
            UpdateCaseFactsInput(
                case_id=case_id,
                facts=payload.facts,
                source=payload.source,
                actor=payload.actor,
                request_id=payload.request_id,
                trace_id=payload.trace_id,
                overwrite_strategy=payload.overwrite_strategy,
            )
        )
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")


@router.post(
    "/{case_id}/stage",
    response_model=dict[str, Any],
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Transition a case to a new stage",
)
async def set_case_stage_route(case_id: str, payload: StageTransitionRequest) -> dict[str, Any]:
    """Move a case through the workflow state machine."""
    try:
        result = set_case_stage(
            SetCaseStageInput(
                case_id=case_id,
                new_stage=payload.new_stage,
                reason=payload.reason,
                actor=payload.actor,
                trace_id=payload.trace_id,
            )
        )
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")


@router.post(
    "/{case_id}/lock-stage",
    response_model=dict[str, Any],
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Lock a case stage",
)
async def lock_case_stage_route(case_id: str, payload: LockStageRequest) -> dict[str, Any]:
    """Lock a stage to prevent unsafe or invalid future mutation."""
    try:
        result = lock_case_stage(
            LockCaseStageInput(
                case_id=case_id,
                stage=payload.stage,
                reason=payload.reason,
                actor=payload.actor,
                trace_id=payload.trace_id,
            )
        )
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")


@router.post(
    "/{case_id}/questions",
    response_model=dict[str, Any],
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Record that a question was asked",
)
async def record_question_route(case_id: str, payload: QuestionRecordRequest) -> dict[str, Any]:
    """Record a question ask event for auditability and repeat avoidance."""
    try:
        result = record_question_asked(
            RecordQuestionAskedInput(
                case_id=case_id,
                question_id=payload.question_id,
                question_text=payload.question_text,
                rationale=payload.rationale,
                actor=payload.actor,
                trace_id=payload.trace_id,
            )
        )
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")


@router.post(
    "/{case_id}/profile",
    response_model=dict[str, Any],
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Enrich patient profile data",
)
async def enrich_patient_profile_route(
    case_id: str,
    payload: PatientProfileUpdateRequest,
) -> dict[str, Any]:
    """Merge new patient profile information into the existing case."""
    try:
        result = enrich_patient_profile(
            case_id=case_id,
            profile=payload.profile,
            actor=payload.actor,
            trace_id=payload.trace_id,
        )
    except Exception as exc:
        _raise_http_from_case_error(exc)

    return result.model_dump(mode="json")
