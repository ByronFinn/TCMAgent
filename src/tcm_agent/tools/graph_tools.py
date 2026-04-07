"""Graph reasoning tools backed by the convergence service.

This module exposes the first MVP graph-oriented tool layer for TCMAgent.
The tools here are intentionally structured and deterministic:

- read the current `CaseState`
- invoke the graph reasoning service
- return structured candidate / question / evidence-style outputs
- optionally persist reasoning results back into the shared case state

These functions are suitable for:
- API routes
- service orchestration
- future agent-tool wrappers

The long-term project direction is to back these tools with richer Neo4j queries.
For now, they are powered by the MVP convergence engine in
`tcm_agent.services.graph_reasoning_service`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tcm_agent.schemas.case import (
    CandidateItem,
    CaseState,
    EvidenceEdgeRef,
    EvidenceNodeRef,
    EvidencePath,
    QuestionRecommendation,
)
from tcm_agent.services.graph_reasoning_service import (
    CandidateAssessment,
    GraphReasoningService,
    QuestionQueryInput,
    QuestionSelectionResult,
    ReasoningSummary,
    get_graph_reasoning_service,
)
from tcm_agent.tools.case_tools import (
    GetCaseStateInput,
    get_case_state,
    update_case_candidates,
)


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    """Generate a simple prefixed identifier."""
    return f"{prefix}_{uuid4().hex}"


class ToolMetadata(BaseModel):
    """Common metadata envelope returned by graph tools."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    tool_name: str
    tool_version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utcnow)
    message: str = ""


class CandidateContextInput(BaseModel):
    """Optional context for rationale and evidence generation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    candidate_ids: list[str] = Field(default_factory=list)
    candidate_type: str | None = None
    actor: str = "system"
    trace_id: str | None = None


class QueryGraphCandidatesInput(BaseModel):
    """Request payload for generating candidates from a case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    actor: str = "system"
    trace_id: str | None = None
    persist: bool = True


class QueryGraphCandidatesOutput(BaseModel):
    """Response payload for candidate generation."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    candidate_diseases: list[CandidateItem] = Field(default_factory=list)
    candidate_patterns: list[CandidateItem] = Field(default_factory=list)
    candidate_pathogenesis: list[CandidateItem] = Field(default_factory=list)
    matched_facts: list[str] = Field(default_factory=list)
    missing_high_value_facts: list[str] = Field(default_factory=list)
    convergence_score: float = Field(ge=0.0, le=1.0)
    recommended_next_question: QuestionRecommendation | None = None
    question_rationale: str | None = None
    case_state: CaseState | None = None
    metadata: ToolMetadata


class FindDiscriminativeQuestionsInput(BaseModel):
    """Request payload for selecting next-step questions."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    max_questions: int = Field(default=1, ge=1, le=5)
    actor: str = "system"
    trace_id: str | None = None

    @field_validator("max_questions")
    @classmethod
    def validate_max_questions(cls, value: int) -> int:
        return max(1, min(value, 5))


class FindDiscriminativeQuestionsOutput(BaseModel):
    """Response payload for question recommendation."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    recommended_questions: list[QuestionRecommendation] = Field(default_factory=list)
    selection_reason: str
    question_strategy: str
    convergence_score: float = Field(ge=0.0, le=1.0)
    case_state: CaseState | None = None
    metadata: ToolMetadata


class ExplainQuestionRationaleInput(BaseModel):
    """Request payload for explaining why a question was selected."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    question_id: str
    actor: str = "system"
    trace_id: str | None = None


class ExplainQuestionRationaleOutput(BaseModel):
    """Response payload for question rationale explanation."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    question_id: str
    rationale: str
    supports_targets: list[str] = Field(default_factory=list)
    conflicts_targets: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: ToolMetadata


class BuildEvidencePathInput(BaseModel):
    """Request payload for evidence path generation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    target_ids: list[str] = Field(default_factory=list)
    target_type: str = "candidate"
    actor: str = "system"
    trace_id: str | None = None


class BuildEvidencePathOutput(BaseModel):
    """Response payload for evidence paths."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    paths: list[EvidencePath] = Field(default_factory=list)
    metadata: ToolMetadata


class RankCandidateHypothesesInput(BaseModel):
    """Request payload for candidate ranking."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    actor: str = "system"
    trace_id: str | None = None
    persist: bool = False


class RankCandidateHypothesesOutput(BaseModel):
    """Response payload for candidate ranking."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    ranked_diseases: list[CandidateAssessment] = Field(default_factory=list)
    ranked_patterns: list[CandidateAssessment] = Field(default_factory=list)
    ranked_pathogenesis: list[CandidateAssessment] = Field(default_factory=list)
    convergence_score: float = Field(ge=0.0, le=1.0)
    uncertainty_notes: list[str] = Field(default_factory=list)
    case_state: CaseState | None = None
    metadata: ToolMetadata


class UpdateGraphEvidenceProjectionInput(BaseModel):
    """Request payload for syncing reasoning results back into case state."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    actor: str = "system"
    trace_id: str | None = None


class UpdateGraphEvidenceProjectionOutput(BaseModel):
    """Response payload for projection updates."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    projection_refs: list[str] = Field(default_factory=list)
    updated_domains: list[str] = Field(default_factory=list)
    case_state: CaseState
    metadata: ToolMetadata


def _metadata(*, tool_name: str, trace_id: str | None, message: str) -> ToolMetadata:
    """Create a shared metadata object."""
    return ToolMetadata(
        tool_name=tool_name,
        trace_id=trace_id or _new_id("trace"),
        message=message,
    )


def _fetch_case_state(case_id: str) -> CaseState:
    """Load case state through the case tool layer."""
    return get_case_state(GetCaseStateInput(case_id=case_id)).case_state


def _reasoning_service(service: GraphReasoningService | None = None) -> GraphReasoningService:
    """Resolve the active graph reasoning service."""
    return service or get_graph_reasoning_service()


def _assessment_items_to_candidates(
    assessments: list[CandidateAssessment],
) -> list[CandidateItem]:
    """Convert internal assessments to shared schema candidate items."""
    return [assessment.to_candidate_item() for assessment in assessments]


def query_graph_candidates(
    payload: QueryGraphCandidatesInput,
    *,
    service: GraphReasoningService | None = None,
) -> QueryGraphCandidatesOutput:
    """Generate candidate diseases, patterns, and pathogenesis for a case."""
    case_state = _fetch_case_state(payload.case_id)
    reasoning = _reasoning_service(service).generate_candidates(case_state)

    updated_case_state: CaseState | None = None
    if payload.persist:
        updated_case_state = update_case_candidates(
            case_id=payload.case_id,
            candidate_diseases=_assessment_items_to_candidates(reasoning.candidate_diseases),
            candidate_patterns=_assessment_items_to_candidates(reasoning.candidate_patterns),
            candidate_pathogenesis=_assessment_items_to_candidates(
                reasoning.candidate_pathogenesis
            ),
            recommended_next_question=reasoning.recommended_question,
            question_rationale=reasoning.question_rationale,
            convergence_score=reasoning.convergence_score,
            actor=payload.actor,
            trace_id=payload.trace_id,
        ).case_state

    return QueryGraphCandidatesOutput(
        case_id=payload.case_id,
        candidate_diseases=_assessment_items_to_candidates(reasoning.candidate_diseases),
        candidate_patterns=_assessment_items_to_candidates(reasoning.candidate_patterns),
        candidate_pathogenesis=_assessment_items_to_candidates(reasoning.candidate_pathogenesis),
        matched_facts=reasoning.matched_facts,
        missing_high_value_facts=reasoning.missing_high_value_facts,
        convergence_score=reasoning.convergence_score,
        recommended_next_question=reasoning.recommended_question,
        question_rationale=reasoning.question_rationale,
        case_state=updated_case_state,
        metadata=_metadata(
            tool_name="query_graph_candidates",
            trace_id=payload.trace_id,
            message="Graph candidates generated successfully.",
        ),
    )


def find_discriminative_questions(
    payload: FindDiscriminativeQuestionsInput,
    *,
    service: GraphReasoningService | None = None,
) -> FindDiscriminativeQuestionsOutput:
    """Recommend the next high-value question(s) for candidate convergence."""
    case_state = _fetch_case_state(payload.case_id)
    resolved_service = _reasoning_service(service)
    reasoning = resolved_service.generate_candidates(case_state)
    question_result: QuestionSelectionResult = resolved_service.recommend_questions(
        QuestionQueryInput(
            case_state=case_state,
            reasoning_summary=reasoning,
            max_questions=payload.max_questions,
        )
    )

    updated_case_state: CaseState | None = None
    if question_result.recommended_questions:
        updated_case_state = update_case_candidates(
            case_id=payload.case_id,
            recommended_next_question=question_result.recommended_questions[0],
            question_rationale=question_result.recommended_questions[0].rationale
            or question_result.selection_reason,
            convergence_score=reasoning.convergence_score,
            actor=payload.actor,
            trace_id=payload.trace_id,
        ).case_state

    return FindDiscriminativeQuestionsOutput(
        case_id=payload.case_id,
        recommended_questions=question_result.recommended_questions,
        selection_reason=question_result.selection_reason,
        question_strategy=question_result.question_strategy,
        convergence_score=reasoning.convergence_score,
        case_state=updated_case_state,
        metadata=_metadata(
            tool_name="find_discriminative_questions",
            trace_id=payload.trace_id,
            message="Question recommendation completed.",
        ),
    )


def explain_question_rationale(
    payload: ExplainQuestionRationaleInput,
    *,
    service: GraphReasoningService | None = None,
) -> ExplainQuestionRationaleOutput:
    """Explain why a given question is useful in the current case context."""
    case_state = _fetch_case_state(payload.case_id)
    resolved_service = _reasoning_service(service)
    reasoning = resolved_service.generate_candidates(case_state)

    all_questions = resolved_service.recommend_questions(
        QuestionQueryInput(case_state=case_state, reasoning_summary=reasoning, max_questions=5)
    ).recommended_questions

    selected = next(
        (question for question in all_questions if question.question_id == payload.question_id),
        None,
    )

    if selected is None:
        selected = case_state.recommended_next_question

    if selected is None or selected.question_id != payload.question_id:
        rationale = (
            "No active rationale was found for the requested question in the current case context."
        )
        supports_targets: list[str] = []
        evidence_refs: list[str] = []
    else:
        rationale = selected.rationale or selected.goal
        supports_targets = selected.discriminates_between
        evidence_refs = [f"question:{selected.question_id}", *supports_targets]

    return ExplainQuestionRationaleOutput(
        case_id=payload.case_id,
        question_id=payload.question_id,
        rationale=rationale,
        supports_targets=supports_targets,
        conflicts_targets=[],
        evidence_refs=evidence_refs,
        metadata=_metadata(
            tool_name="explain_question_rationale",
            trace_id=payload.trace_id,
            message="Question rationale explained.",
        ),
    )


def build_evidence_path(
    payload: BuildEvidencePathInput,
    *,
    service: GraphReasoningService | None = None,
) -> BuildEvidencePathOutput:
    """Build lightweight evidence paths for target candidates."""
    case_state = _fetch_case_state(payload.case_id)
    reasoning = _reasoning_service(service).generate_candidates(case_state)

    assessment_map: dict[str, CandidateAssessment] = {}
    for assessment in (
        reasoning.candidate_diseases
        + reasoning.candidate_patterns
        + reasoning.candidate_pathogenesis
    ):
        assessment_map[assessment.candidate_id] = assessment

    target_ids = payload.target_ids
    if not target_ids:
        if payload.target_type == "pattern":
            target_ids = [candidate.candidate_id for candidate in reasoning.candidate_patterns[:3]]
        elif payload.target_type == "disease":
            target_ids = [candidate.candidate_id for candidate in reasoning.candidate_diseases[:3]]
        else:
            target_ids = [
                candidate.candidate_id
                for candidate in (
                    reasoning.candidate_patterns[:2] + reasoning.candidate_diseases[:1]
                )
            ]

    paths: list[EvidencePath] = []
    for target_id in target_ids:
        assessment = assessment_map.get(target_id)
        if assessment is None:
            continue

        nodes: list[EvidenceNodeRef] = [
            EvidenceNodeRef(node_id=payload.case_id, node_type="case", name=payload.case_id),
            EvidenceNodeRef(
                node_id=target_id,
                node_type=assessment.candidate_type.value,
                name=assessment.name,
            ),
        ]
        edges: list[EvidenceEdgeRef] = []

        for evidence_ref in assessment.supporting_evidence:
            nodes.insert(
                -1,
                EvidenceNodeRef(
                    node_id=evidence_ref,
                    node_type="fact",
                    name=evidence_ref.replace("fact:", ""),
                ),
            )
            edges.append(
                EvidenceEdgeRef(
                    relation="supports",
                    source_id=evidence_ref,
                    target_id=target_id,
                    weight=assessment.score,
                )
            )

        paths.append(
            EvidencePath(
                target_id=target_id,
                target_type=assessment.candidate_type.value,
                path_nodes=nodes,
                path_edges=edges,
                summary=(
                    f"{assessment.name} is supported by {len(assessment.supporting_evidence)} "
                    "positive fact(s) and opposed by "
                    f"{len(assessment.conflicting_evidence)} fact(s)."
                ),
            )
        )

    return BuildEvidencePathOutput(
        case_id=payload.case_id,
        paths=paths,
        metadata=_metadata(
            tool_name="build_evidence_path",
            trace_id=payload.trace_id,
            message="Evidence paths built successfully.",
        ),
    )


def rank_candidate_hypotheses(
    payload: RankCandidateHypothesesInput,
    *,
    service: GraphReasoningService | None = None,
) -> RankCandidateHypothesesOutput:
    """Rank current candidate hypotheses and optionally persist the result."""
    case_state = _fetch_case_state(payload.case_id)
    reasoning: ReasoningSummary = _reasoning_service(service).generate_candidates(case_state)

    updated_case_state: CaseState | None = None
    if payload.persist:
        updated_case_state = update_case_candidates(
            case_id=payload.case_id,
            candidate_diseases=_assessment_items_to_candidates(reasoning.candidate_diseases),
            candidate_patterns=_assessment_items_to_candidates(reasoning.candidate_patterns),
            candidate_pathogenesis=_assessment_items_to_candidates(
                reasoning.candidate_pathogenesis
            ),
            recommended_next_question=reasoning.recommended_question,
            question_rationale=reasoning.question_rationale,
            convergence_score=reasoning.convergence_score,
            actor=payload.actor,
            trace_id=payload.trace_id,
        ).case_state

    uncertainty_notes: list[str] = []
    if not reasoning.candidate_patterns:
        uncertainty_notes.append(
            "No strong pattern candidates were identified from the current facts."
        )
    elif len(reasoning.candidate_patterns) > 1:
        top = reasoning.candidate_patterns[0].score
        second = reasoning.candidate_patterns[1].score
        if abs(top - second) < 0.1:
            uncertainty_notes.append(
                "Top pattern candidates remain close; further questioning is recommended."
            )

    if reasoning.recommended_question is None:
        uncertainty_notes.append("No additional high-value question was recommended.")

    return RankCandidateHypothesesOutput(
        case_id=payload.case_id,
        ranked_diseases=reasoning.candidate_diseases,
        ranked_patterns=reasoning.candidate_patterns,
        ranked_pathogenesis=reasoning.candidate_pathogenesis,
        convergence_score=reasoning.convergence_score,
        uncertainty_notes=uncertainty_notes,
        case_state=updated_case_state,
        metadata=_metadata(
            tool_name="rank_candidate_hypotheses",
            trace_id=payload.trace_id,
            message="Candidate ranking completed.",
        ),
    )


def update_graph_evidence_projection(
    payload: UpdateGraphEvidenceProjectionInput,
    *,
    service: GraphReasoningService | None = None,
) -> UpdateGraphEvidenceProjectionOutput:
    """Project current reasoning results back into case-state fields."""
    case_state = _fetch_case_state(payload.case_id)
    resolved_service = _reasoning_service(service)
    reasoning = resolved_service.generate_candidates(case_state)

    response = update_case_candidates(
        case_id=payload.case_id,
        candidate_diseases=_assessment_items_to_candidates(reasoning.candidate_diseases),
        candidate_patterns=_assessment_items_to_candidates(reasoning.candidate_patterns),
        candidate_pathogenesis=_assessment_items_to_candidates(reasoning.candidate_pathogenesis),
        recommended_next_question=reasoning.recommended_question,
        question_rationale=reasoning.question_rationale,
        convergence_score=reasoning.convergence_score,
        actor=payload.actor,
        trace_id=payload.trace_id,
    )

    updated_domains: list[str] = [
        "candidate_diseases",
        "candidate_patterns",
        "candidate_pathogenesis",
        "convergence_score",
    ]
    if reasoning.recommended_question is not None:
        updated_domains.extend(["recommended_next_question", "question_rationale"])

    projection_refs = [
        f"candidate:{candidate.candidate_id}"
        for candidate in (reasoning.candidate_patterns[:2] + reasoning.candidate_diseases[:2])
    ]

    return UpdateGraphEvidenceProjectionOutput(
        case_id=payload.case_id,
        projection_refs=projection_refs,
        updated_domains=updated_domains,
        case_state=response.case_state,
        metadata=_metadata(
            tool_name="update_graph_evidence_projection",
            trace_id=payload.trace_id,
            message="Graph evidence projection updated.",
        ),
    )


__all__ = [
    "BuildEvidencePathInput",
    "BuildEvidencePathOutput",
    "CandidateContextInput",
    "ExplainQuestionRationaleInput",
    "ExplainQuestionRationaleOutput",
    "FindDiscriminativeQuestionsInput",
    "FindDiscriminativeQuestionsOutput",
    "QueryGraphCandidatesInput",
    "QueryGraphCandidatesOutput",
    "RankCandidateHypothesesInput",
    "RankCandidateHypothesesOutput",
    "ToolMetadata",
    "UpdateGraphEvidenceProjectionInput",
    "UpdateGraphEvidenceProjectionOutput",
    "build_evidence_path",
    "explain_question_rationale",
    "find_discriminative_questions",
    "query_graph_candidates",
    "rank_candidate_hypotheses",
    "update_graph_evidence_projection",
]
