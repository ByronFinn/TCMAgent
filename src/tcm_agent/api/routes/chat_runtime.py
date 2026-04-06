"""Runtime chat routes for the convergent consultation loop.

This module provides a practical MVP chat endpoint that wires together the
current project scaffold:

- Reads and updates structured `CaseState`
- Extracts a small set of normalized facts from free-text patient messages
- Runs candidate generation and question recommendation
- Executes the current safety pipeline
- Returns both patient-facing and internal structured outputs

This route is intentionally conservative. It is designed to be useful now,
while remaining easy to replace later with a richer orchestrated flow driven by
the full supervisor/subagent stack.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from tcm_agent.schemas.case import (
    CandidateItem,
    CaseStage,
    FactType,
    NormalizedFact,
    PatientSummary,
    QuestionRecommendation,
    RiskLevel,
    SummaryAudience,
)
from tcm_agent.tools.case_tools import (
    GetCaseStateInput,
    RecordQuestionAskedInput,
    SaveCaseSummaryInput,
    UpdateCaseFactsInput,
    get_case_state,
    record_question_asked,
    save_case_summary,
    update_case_facts,
)
from tcm_agent.tools.graph_tools import (
    FindDiscriminativeQuestionsInput,
    QueryGraphCandidatesInput,
    find_discriminative_questions,
    query_graph_candidates,
)
from tcm_agent.tools.safety_tools import run_full_safety_check

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    """HTTP request payload for a patient message."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    actor: str = "patient"
    trace_id: str | None = None
    request_id: str | None = None


class ChatMessageResponse(BaseModel):
    """HTTP response payload for the consultation loop."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    patient_reply: str
    recommended_next_question: QuestionRecommendation | None = None
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    safe_to_continue: bool | None = None
    case_stage: CaseStage
    matched_facts: list[str] = Field(default_factory=list)
    candidate_patterns: list[CandidateItem] = Field(default_factory=list)
    candidate_diseases: list[CandidateItem] = Field(default_factory=list)
    internal_summary: dict[str, Any] = Field(default_factory=dict)


class ChatRouteErrorResponse(BaseModel):
    """Simple structured error payload for chat routes."""

    model_config = ConfigDict(extra="forbid")

    detail: str


SYMPTOM_KEYWORDS: dict[str, tuple[str, FactType, bool]] = {
    "发热": ("fever", FactType.SYMPTOM, True),
    "高热": ("persistent_high_fever", FactType.SYMPTOM, True),
    "怕冷": ("aversion_to_cold", FactType.OBSERVATION, True),
    "恶寒": ("aversion_to_cold", FactType.OBSERVATION, True),
    "怕热": ("aversion_to_heat", FactType.OBSERVATION, True),
    "口渴": ("thirst", FactType.OBSERVATION, True),
    "咽痛": ("sore_throat", FactType.SYMPTOM, True),
    "喉咙痛": ("sore_throat", FactType.SYMPTOM, True),
    "咳嗽": ("cough", FactType.SYMPTOM, True),
    "流鼻涕": ("runny_nose", FactType.SYMPTOM, True),
    "清鼻涕": ("clear_nasal_discharge", FactType.SYMPTOM, True),
    "黄痰": ("yellow_phlegm", FactType.SYMPTOM, True),
    "无汗": ("no_sweat", FactType.OBSERVATION, True),
    "出汗": ("sweating", FactType.OBSERVATION, True),
    "胸痛": ("chest_pain", FactType.SYMPTOM, True),
    "胸闷": ("chest_oppression", FactType.SYMPTOM, True),
    "呼吸困难": ("breathing_difficulty", FactType.SYMPTOM, True),
    "气短": ("shortness_of_breath", FactType.SYMPTOM, True),
    "头痛": ("headache", FactType.SYMPTOM, True),
    "剧烈头痛": ("sudden_severe_headache", FactType.SYMPTOM, True),
    "失眠": ("insomnia", FactType.SYMPTOM, True),
    "难入睡": ("difficulty_falling_asleep", FactType.OBSERVATION, True),
    "烦躁": ("irritability", FactType.OBSERVATION, True),
    "情绪差": ("mood_swings", FactType.OBSERVATION, True),
    "压力大": ("stress", FactType.OBSERVATION, True),
    "腹胀": ("abdominal_distention", FactType.SYMPTOM, True),
    "恶心": ("nausea", FactType.SYMPTOM, True),
    "乏力": ("fatigue", FactType.SYMPTOM, True),
    "纳差": ("poor_appetite", FactType.OBSERVATION, True),
    "食欲差": ("poor_appetite", FactType.OBSERVATION, True),
    "便稀": ("loose_stool", FactType.OBSERVATION, True),
    "大便稀": ("loose_stool", FactType.OBSERVATION, True),
    "黑便": ("black_stool", FactType.SYMPTOM, True),
    "呕血": ("vomiting_blood", FactType.SYMPTOM, True),
    "出血": ("bleeding", FactType.SYMPTOM, True),
    "抽搐": ("seizure", FactType.SYMPTOM, True),
    "怀孕": ("pregnant", FactType.POPULATION_TAG, True),
    "孕期": ("pregnant", FactType.POPULATION_TAG, True),
    "儿童": ("child", FactType.POPULATION_TAG, True),
    "高龄": ("elderly", FactType.POPULATION_TAG, True),
    "老人": ("elderly", FactType.POPULATION_TAG, True),
    "慢病": ("chronic_disease", FactType.POPULATION_TAG, True),
}

NEGATION_MARKERS = ("没有", "无", "未见", "并无", "否认")


def _contains_negation(text: str, keyword: str) -> bool:
    """Return whether the keyword appears in a negated context."""
    return any(marker + keyword in text for marker in NEGATION_MARKERS)


def _extract_facts(message: str) -> list[NormalizedFact]:
    """Extract a minimal set of normalized facts from free text.

    This is a deliberately lightweight MVP extractor. It should later be replaced
    by a richer normalization / NLP pipeline.
    """
    facts: list[NormalizedFact] = []

    for keyword, (normalized_key, fact_type, positive_value) in SYMPTOM_KEYWORDS.items():
        if keyword not in message:
            continue

        value = False if _contains_negation(message, keyword) else positive_value

        facts.append(
            NormalizedFact(
                fact_type=fact_type,
                normalized_key=normalized_key,
                normalized_value=value,
                source_text=keyword,
                confidence=0.75,
            )
        )

    return facts


def _patient_reply_from_state(
    *,
    safe_to_continue: bool | None,
    risk_level: RiskLevel,
    recommended_next_question: QuestionRecommendation | None,
) -> str:
    """Generate a safe, patient-facing reply."""
    if safe_to_continue is False:
        if risk_level in {RiskLevel.CRITICAL, RiskLevel.HIGH}:
            return (
                "基于你当前提供的信息，存在需要优先线下进一步评估的风险信号。"
                "建议不要继续普通线上问诊，尽快线下就医或急诊评估。"
            )
        return "基于你当前提供的信息，建议先暂停普通线上问诊，并由人工或线下进一步评估。"

    if recommended_next_question is not None:
        return recommended_next_question.question_text

    return "目前我已经收集到一部分信息，接下来建议结合结构化结果继续评估。"


def _build_internal_summary(
    *,
    candidate_result: Any,
    question_result: Any,
    safety_result: dict[str, Any],
) -> dict[str, Any]:
    """Build the internal structured summary returned by the route."""
    return {
        "missing_high_value_facts": candidate_result.missing_high_value_facts,
        "convergence_score": candidate_result.convergence_score,
        "selection_reason": question_result.selection_reason,
        "question_strategy": question_result.question_strategy,
        "risk_decision": safety_result["risk_decision"],
        "red_flags": safety_result["red_flags"],
        "contraindications": safety_result["contraindications"],
        "population_risks": safety_result["population_risks"],
    }


@router.post(
    "/{case_id}/message",
    response_model=ChatMessageResponse,
    responses={
        404: {"model": ChatRouteErrorResponse},
        500: {"model": ChatRouteErrorResponse},
    },
    summary="Process a patient message in the convergent consultation loop",
)
async def process_chat_message(case_id: str, payload: ChatMessageRequest) -> ChatMessageResponse:
    """Process one patient message against the current case state."""
    try:
        get_case_state(GetCaseStateInput(case_id=case_id, trace_id=payload.trace_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    extracted_facts = _extract_facts(payload.message)

    if extracted_facts:
        update_case_facts(
            UpdateCaseFactsInput(
                case_id=case_id,
                facts=extracted_facts,
                source="chat_message",
                actor=payload.actor,
                request_id=payload.request_id,
                trace_id=payload.trace_id,
            )
        )

    candidate_result = query_graph_candidates(
        QueryGraphCandidatesInput(
            case_id=case_id,
            actor="clinical-supervisor",
            trace_id=payload.trace_id,
            persist=True,
        )
    )

    question_result = find_discriminative_questions(
        FindDiscriminativeQuestionsInput(
            case_id=case_id,
            max_questions=1,
            actor="clinical-supervisor",
            trace_id=payload.trace_id,
        )
    )

    if question_result.recommended_questions:
        next_question = question_result.recommended_questions[0]
        record_question_asked(
            RecordQuestionAskedInput(
                case_id=case_id,
                question_id=next_question.question_id,
                question_text=next_question.question_text,
                rationale=next_question.rationale,
                actor="clinical-supervisor",
                trace_id=payload.trace_id,
            )
        )

    safety_result = cast(
        dict[str, Any],
        run_full_safety_check(
            case_id=case_id,
            actor="safety-agent",
            trace_id=payload.trace_id,
        ),
    )

    refreshed_state = get_case_state(
        GetCaseStateInput(case_id=case_id, trace_id=payload.trace_id)
    ).case_state

    decision = safety_result["risk_decision"]
    risk_level = RiskLevel(decision["risk_level"])
    safe_to_continue = bool(decision["safe_to_continue"])

    patient_reply = _patient_reply_from_state(
        safe_to_continue=safe_to_continue,
        risk_level=risk_level,
        recommended_next_question=refreshed_state.recommended_next_question,
    )

    if refreshed_state.case_stage == CaseStage.INTAKE_CONVERGED and safe_to_continue:
        summary = PatientSummary(
            audience=SummaryAudience.PATIENT,
            summary_text="当前信息已初步收敛，建议结合后续结构化评估继续判断。",
            next_step_hint="可进入下一阶段分析或由医生进一步复核。",
        )
        save_case_summary(
            SaveCaseSummaryInput(
                case_id=case_id,
                patient_summary=summary,
                clinician_summary=None,
                actor="clinical-supervisor",
                trace_id=payload.trace_id,
            )
        )
        refreshed_state = get_case_state(
            GetCaseStateInput(case_id=case_id, trace_id=payload.trace_id)
        ).case_state

    return ChatMessageResponse(
        case_id=case_id,
        patient_reply=patient_reply,
        recommended_next_question=refreshed_state.recommended_next_question,
        risk_level=risk_level,
        safe_to_continue=safe_to_continue,
        case_stage=refreshed_state.case_stage,
        matched_facts=candidate_result.matched_facts,
        candidate_patterns=refreshed_state.candidate_patterns,
        candidate_diseases=refreshed_state.candidate_diseases,
        internal_summary=_build_internal_summary(
            candidate_result=candidate_result,
            question_result=question_result,
            safety_result=safety_result,
        ),
    )
