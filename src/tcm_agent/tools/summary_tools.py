"""Summary generation tools for patient-facing and clinician-facing views.

This module provides rule-based summary generation for TCMAgent's output layer.

Goals
-----
- Generate patient-visible plain-language summaries with safety notices
- Produce internal clinician-facing structured case summaries
- Export full case audit traces for compliance and debugging

All logic is intentionally rule-based (no LLM calls) to ensure:
- Deterministic, auditable output
- Zero latency overhead from model calls at the summary stage
- Safe-by-default behaviour when risk signals are present
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tcm_agent.schemas.case import (
    AuditEvent,
    CandidateItem,
    CaseStage,
    ClinicianSummary,
    EvidenceItem,
    EvidenceType,
    PatientSummary,
    RiskLevel,
    SummaryAudience,
)
from tcm_agent.tools.case_tools import CASE_STORE, CaseNotFoundError  # noqa: F401 (re-exported)

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    """Generate a stable prefixed UUID-based ID."""
    return f"{prefix}_{uuid4().hex}"


# ---------------------------------------------------------------------------
# ToolMetadata
# ---------------------------------------------------------------------------


class ToolMetadata(BaseModel):
    """Common metadata returned by every summary tool response."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    tool_name: str
    tool_version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utcnow)
    message: str = ""


class SummaryToolError(RuntimeError):
    """Raised when a summary operation cannot be completed."""


# ---------------------------------------------------------------------------
# Input / Output Pydantic models
# ---------------------------------------------------------------------------


class GeneratePatientSummaryInput(BaseModel):
    """Request payload for patient-facing summary generation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    actor: str = "system"
    trace_id: str | None = None


class PatientSummaryTemplateOutput(BaseModel):
    """Response payload for a patient-visible structured summary template."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    audience: str = "patient"
    summary_text: str
    next_step_hint: str | None = None
    safety_notice: str | None = None
    generated_at: datetime
    metadata: ToolMetadata


class GenerateClinicianSummaryInput(BaseModel):
    """Request payload for clinician-facing case summary generation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    actor: str = "system"
    trace_id: str | None = None


class RedFlagSummaryItem(BaseModel):
    """Minimal red-flag descriptor for the clinician summary output."""

    model_config = ConfigDict(extra="forbid")

    name: str
    severity: str


class ClinicianSummaryOutput(BaseModel):
    """Response payload for a clinician-facing full case summary."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    chief_complaint: str | None
    top_candidate_diseases: list[CandidateItem] = Field(default_factory=list)
    top_candidate_patterns: list[CandidateItem] = Field(default_factory=list)
    normalized_facts_count: int
    red_flags_summary: list[RedFlagSummaryItem] = Field(default_factory=list)
    risk_level: RiskLevel
    safe_to_continue: bool | None
    intake_completeness_score: float
    convergence_score: float
    missing_critical_facts: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    generated_at: datetime
    metadata: ToolMetadata


class ExportCaseTraceInput(BaseModel):
    """Request payload for full case-trace export."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    include_audit_log: bool = True
    include_evidence: bool = True
    actor: str = "system"
    trace_id: str | None = None


class CaseTraceOutput(BaseModel):
    """Response payload for a complete case audit trace."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    case_stage: CaseStage
    total_questions_asked: int
    total_facts_collected: int
    convergence_score: float
    audit_events_count: int
    audit_log: list[AuditEvent] | None = None
    evidence_items: list[EvidenceItem] | None = None
    exported_at: datetime
    metadata: ToolMetadata


# ---------------------------------------------------------------------------
# Internal pure-computation helpers
# ---------------------------------------------------------------------------

# Maps each CaseStage to a patient-facing next-step hint string.
_STAGE_NEXT_STEP_HINT: dict[CaseStage, str] = {
    CaseStage.CREATED: "我们即将为您进行初步评估，请稍候",
    CaseStage.TRIAGED: "首次分诊已完成，我们将进一步了解您的症状情况",
    CaseStage.INITIAL_CANDIDATES_GENERATED: "正在为您制定个性化问诊方案，请稍候",
    CaseStage.INTAKE_IN_PROGRESS: "请继续回答以下问题，以便更准确地分析您的症状",
    CaseStage.INTAKE_PAUSED_FOR_RISK: "问诊暂停，系统正在对您的情况进行安全评估，请稍候",
    CaseStage.INTAKE_CONVERGED: "症状信息已基本收集完毕，正在为您生成报告",
    CaseStage.SAFETY_REVIEWED: "安全评估已完成，您的报告正在生成中",
    CaseStage.SUMMARY_GENERATED: "您的问诊报告已生成，请查阅或等待医生跟进",
    CaseStage.HANDOFF_REQUIRED: "建议您前往线下医院就诊，医生将进一步为您评估",
    CaseStage.CLOSED: "本次问诊已结束，感谢您的使用",
}

# Patient-facing stage label for the summary text body.
_STAGE_DESCRIPTION: dict[CaseStage, str] = {
    CaseStage.CREATED: "正在进行初步评估",
    CaseStage.TRIAGED: "已完成首次分诊评估",
    CaseStage.INITIAL_CANDIDATES_GENERATED: "候选诊断已初步生成",
    CaseStage.INTAKE_IN_PROGRESS: "问诊正在进行中",
    CaseStage.INTAKE_PAUSED_FOR_RISK: "问诊因风险信号暂停，等待安全复核",
    CaseStage.INTAKE_CONVERGED: "信息收集已基本完成",
    CaseStage.SAFETY_REVIEWED: "安全评估已完成",
    CaseStage.SUMMARY_GENERATED: "报告已生成",
    CaseStage.HANDOFF_REQUIRED: "需要线下就诊跟进",
    CaseStage.CLOSED: "问诊已结束",
}

# Stage-specific action hints for clinicians.
_STAGE_CLINICIAN_ACTION: dict[CaseStage, str] = {
    CaseStage.CREATED: "病例刚创建，建议先完成导诊评估（run_triage）",
    CaseStage.TRIAGED: "已完成导诊，建议启动候选生成和深度问诊流程",
    CaseStage.INTAKE_IN_PROGRESS: "问诊进行中，建议继续追问以提高信息完整度和收敛分数",
    CaseStage.INTAKE_PAUSED_FOR_RISK: (
        "问诊因风险暂停，建议尽快完成安全复核（run_full_safety_check）"
    ),
    CaseStage.INTAKE_CONVERGED: "信息已收敛，建议执行最终安全评估并生成摘要",
    CaseStage.SAFETY_REVIEWED: "安全评估完毕，可生成医患双端摘要",
}


def _build_patient_summary_text(
    *,
    chief_complaint: str | None,
    facts_count: int,
    case_stage: CaseStage,
) -> str:
    """Assemble a patient-friendly plain-text summary from case signals.

    Parameters
    ----------
    chief_complaint:
        The patient's chief complaint string, or ``None`` if not yet recorded.
    facts_count:
        Total number of structured facts collected so far.
    case_stage:
        Current lifecycle stage of the case.

    Returns
    -------
    str:
        A concise, patient-readable summary paragraph.
    """
    parts: list[str] = []

    if chief_complaint:
        parts.append(f"您本次就诊的主诉为「{chief_complaint}」。")
    else:
        parts.append("您的基本信息已提交，主诉尚未填写。")

    if facts_count > 0:
        parts.append(f"我们已收集到 {facts_count} 项症状及相关健康信息。")

    stage_desc = _STAGE_DESCRIPTION.get(case_stage, "问诊进行中")
    parts.append(f"当前状态：{stage_desc}。")

    return "".join(parts)


def _derive_patient_safety_notice(
    *,
    risk_level: RiskLevel,
    safe_to_continue: bool | None,
) -> str | None:
    """Generate a patient-facing safety notice from risk signals.

    Returns ``None`` when there is no notable safety message to show.
    """
    if safe_to_continue is False:
        return (
            "⚠️ 根据您描述的症状，系统建议您尽快前往线下医院就诊，"
            "请勿仅依赖在线问诊作为唯一诊断依据。"
        )
    if risk_level == RiskLevel.CRITICAL:
        return "🚨 您描述的症状存在高危信号，请立即前往急诊科或拨打急救电话（120），切勿延误。"
    if risk_level == RiskLevel.HIGH:
        return "⚠️ 您描述的症状存在需要重视的高风险信号，请尽快前往医院进行专业评估，避免病情加重。"
    if risk_level == RiskLevel.MEDIUM:
        return "请注意：您的症状已引起系统关注，如症状持续或加重，建议及时前往医院就诊。"
    return None


def _derive_recommended_actions(
    *,
    risk_level: RiskLevel,
    safe_to_continue: bool | None,
    case_stage: CaseStage,
    missing_critical_facts: list[str],
) -> list[str]:
    """Derive an ordered list of recommended clinical actions from case signals.

    Parameters
    ----------
    risk_level:
        Current aggregated risk level from the safety layer.
    safe_to_continue:
        Whether the case is cleared for continued online intake.
    case_stage:
        Current lifecycle stage.
    missing_critical_facts:
        Keys of facts that have been identified as missing but critical.

    Returns
    -------
    list[str]:
        Ordered action strings, most urgent first.
    """
    actions: list[str] = []

    # Risk-level driven actions (highest priority)
    if risk_level == RiskLevel.CRITICAL:
        actions.append("【紧急】存在高危信号，应立即安排线下急诊处理，不得延误")
    elif risk_level == RiskLevel.HIGH:
        actions.append("【高风险】建议尽快安排线下医院就诊，优先排查高危病因")
    elif risk_level == RiskLevel.MEDIUM:
        actions.append("存在中等风险信号，建议安排人工复核或线下评估")

    # Safe-to-continue override
    if safe_to_continue is False:
        actions.append("系统判断当前不适合继续线上问诊，请升级至线下或人工接诊")
    elif safe_to_continue is None and risk_level not in {
        RiskLevel.NONE,
        RiskLevel.LOW,
        RiskLevel.UNKNOWN,
    }:
        actions.append("安全评估尚未完成，建议在继续问诊前先执行安全检查")

    # Missing facts
    if missing_critical_facts:
        count = len(missing_critical_facts)
        preview = "、".join(missing_critical_facts[:3])
        suffix = f"等共 {count} 项" if count > 3 else ""
        actions.append(f"存在关键信息缺失，建议追问：{preview}{suffix}")

    # Stage-specific guidance
    if stage_action := _STAGE_CLINICIAN_ACTION.get(case_stage):
        actions.append(stage_action)

    return actions


def _metadata(tool_name: str, trace_id: str | None, message: str) -> ToolMetadata:
    """Construct a :class:`ToolMetadata` instance."""
    return ToolMetadata(
        tool_name=tool_name,
        trace_id=trace_id or _new_id("trace"),
        message=message,
    )


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def generate_patient_summary_template(
    payload: GeneratePatientSummaryInput,
) -> PatientSummaryTemplateOutput:
    """Generate a patient-visible structured summary template from case state.

    This is a pure rule-based function with no LLM calls.  It assembles a
    plain-language summary text, a next-step hint, and—when risk signals
    warrant it—a safety notice for the patient.

    Parameters
    ----------
    payload:
        Minimal request containing only ``case_id`` and optional ``actor`` /
        ``trace_id`` for audit attribution.

    Returns
    -------
    PatientSummaryTemplateOutput:
        Structured output with ``summary_text``, ``next_step_hint``, and an
        optional ``safety_notice``.

    Side effects
    ------------
    - Writes the generated summary to ``case_state.patient_summary``.
    - Appends a ``patient_summary_generated`` audit event to the case.

    Raises
    ------
    CaseNotFoundError:
        If ``payload.case_id`` does not exist in the store.
    """
    record = CASE_STORE.get(payload.case_id)
    state = record.state
    now = utcnow()

    summary_text = _build_patient_summary_text(
        chief_complaint=state.chief_complaint,
        facts_count=len(state.normalized_facts),
        case_stage=state.case_stage,
    )
    next_step_hint = _STAGE_NEXT_STEP_HINT.get(state.case_stage)
    safety_notice = _derive_patient_safety_notice(
        risk_level=state.risk_level,
        safe_to_continue=state.safe_to_continue,
    )

    # Persist summary to case state
    state.patient_summary = PatientSummary(
        audience=SummaryAudience.PATIENT,
        summary_text=summary_text,
        next_step_hint=next_step_hint,
        safety_notice=safety_notice,
        generated_at=now,
    )
    state.updated_at = now
    state.audit_log.append(
        AuditEvent(
            event_type="patient_summary_generated",
            actor=payload.actor,
            message="患者摘要模板已生成",
            payload={
                "case_stage": state.case_stage.value,
                "risk_level": state.risk_level.value,
                "has_safety_notice": safety_notice is not None,
                "facts_count": len(state.normalized_facts),
            },
            created_at=now,
        )
    )

    CASE_STORE.save(record)

    return PatientSummaryTemplateOutput(
        case_id=payload.case_id,
        summary_text=summary_text,
        next_step_hint=next_step_hint,
        safety_notice=safety_notice,
        generated_at=now,
        metadata=_metadata(
            tool_name="generate_patient_summary_template",
            trace_id=payload.trace_id,
            message="Patient summary template generated successfully.",
        ),
    )


def generate_clinician_summary(
    payload: GenerateClinicianSummaryInput,
) -> ClinicianSummaryOutput:
    """Generate an internal clinician-facing full case summary.

    This function aggregates all key case signals—candidate hypotheses,
    red flags, risk decisions, evidence balance, and completeness scores—
    into a structured summary suitable for clinicians and operators.

    Parameters
    ----------
    payload:
        Minimal request containing only ``case_id`` and optional ``actor`` /
        ``trace_id`` for audit attribution.

    Returns
    -------
    ClinicianSummaryOutput:
        Rich structured output including top candidates, red-flag summary,
        risk level, completeness metrics, and recommended clinical actions.

    Side effects
    ------------
    - Writes the generated summary to ``case_state.clinician_summary``.
    - Appends a ``clinician_summary_generated`` audit event to the case.

    Raises
    ------
    CaseNotFoundError:
        If ``payload.case_id`` does not exist in the store.
    """
    record = CASE_STORE.get(payload.case_id)
    state = record.state
    now = utcnow()

    # Top candidates (score-descending, capped at 5)
    top_diseases = sorted(state.candidate_diseases, key=lambda c: c.score, reverse=True)[:5]
    top_patterns = sorted(state.candidate_patterns, key=lambda c: c.score, reverse=True)[:5]

    # Red-flag summary items
    red_flags_summary = [
        RedFlagSummaryItem(name=rf.name, severity=rf.severity.value) for rf in state.red_flags
    ]

    # Recommended actions
    recommended_actions = _derive_recommended_actions(
        risk_level=state.risk_level,
        safe_to_continue=state.safe_to_continue,
        case_stage=state.case_stage,
        missing_critical_facts=state.missing_critical_facts,
    )

    # Partition evidence by type
    supporting = [e for e in state.evidence_items if e.evidence_type == EvidenceType.SUPPORT]
    conflicting = [e for e in state.evidence_items if e.evidence_type == EvidenceType.CONFLICT]

    # Persist ClinicianSummary schema object to case state
    state.clinician_summary = ClinicianSummary(
        audience=SummaryAudience.CLINICIAN,
        chief_complaint=state.chief_complaint,
        normalized_facts=list(state.normalized_facts),
        candidate_diseases=list(top_diseases),
        candidate_patterns=list(top_patterns),
        candidate_pathogenesis=list(state.candidate_pathogenesis),
        supporting_evidence=supporting,
        conflicting_evidence=conflicting,
        red_flags=list(state.red_flags),
        risk_level=state.risk_level,
        missing_critical_facts=list(state.missing_critical_facts),
        next_recommended_actions=recommended_actions,
        generated_at=now,
    )
    state.updated_at = now
    state.audit_log.append(
        AuditEvent(
            event_type="clinician_summary_generated",
            actor=payload.actor,
            message="医生摘要已生成",
            payload={
                "top_disease_count": len(top_diseases),
                "top_pattern_count": len(top_patterns),
                "red_flag_count": len(red_flags_summary),
                "action_count": len(recommended_actions),
                "supporting_evidence_count": len(supporting),
                "conflicting_evidence_count": len(conflicting),
                "convergence_score": state.convergence_score,
                "intake_completeness_score": state.intake_completeness_score,
            },
            created_at=now,
        )
    )

    CASE_STORE.save(record)

    return ClinicianSummaryOutput(
        case_id=payload.case_id,
        chief_complaint=state.chief_complaint,
        top_candidate_diseases=top_diseases,
        top_candidate_patterns=top_patterns,
        normalized_facts_count=len(state.normalized_facts),
        red_flags_summary=red_flags_summary,
        risk_level=state.risk_level,
        safe_to_continue=state.safe_to_continue,
        intake_completeness_score=state.intake_completeness_score,
        convergence_score=state.convergence_score,
        missing_critical_facts=list(state.missing_critical_facts),
        recommended_actions=recommended_actions,
        generated_at=now,
        metadata=_metadata(
            tool_name="generate_clinician_summary",
            trace_id=payload.trace_id,
            message=(
                f"Clinician summary generated: {len(top_diseases)} disease candidate(s), "
                f"{len(top_patterns)} pattern candidate(s), "
                f"{len(red_flags_summary)} red flag(s)."
            ),
        ),
    )


def export_case_trace(payload: ExportCaseTraceInput) -> CaseTraceOutput:
    """Export the complete case audit trace for debugging and compliance review.

    Assembles a snapshot of the case lifecycle trajectory, including optional
    full audit log and evidence items.  This function is **read-only**: it does
    not mutate any case state.

    Parameters
    ----------
    payload:
        Contains ``case_id``, ``include_audit_log``, and ``include_evidence``
        flags, plus optional ``actor`` / ``trace_id``.

    Returns
    -------
    CaseTraceOutput:
        Full trace with counts, stage, scores, and optionally the raw audit
        log and evidence items.

    Side effects
    ------------
    None.  This function does not modify case state.

    Raises
    ------
    CaseNotFoundError:
        If ``payload.case_id`` does not exist in the store.
    """
    record = CASE_STORE.get(payload.case_id)
    state = record.state
    now = utcnow()

    audit_log: list[AuditEvent] | None = (
        list(state.audit_log) if payload.include_audit_log else None
    )
    evidence_items: list[EvidenceItem] | None = (
        list(state.evidence_items) if payload.include_evidence else None
    )

    return CaseTraceOutput(
        case_id=payload.case_id,
        case_stage=state.case_stage,
        total_questions_asked=len(state.asked_questions),
        total_facts_collected=len(state.normalized_facts),
        convergence_score=state.convergence_score,
        audit_events_count=len(state.audit_log),
        audit_log=audit_log,
        evidence_items=evidence_items,
        exported_at=now,
        metadata=_metadata(
            tool_name="export_case_trace",
            trace_id=payload.trace_id,
            message=(
                f"Case trace exported: {len(state.audit_log)} audit event(s), "
                f"{len(state.evidence_items)} evidence item(s), "
                f"stage={state.case_stage.value}."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "CaseTraceOutput",
    "ClinicianSummaryOutput",
    "ExportCaseTraceInput",
    "GenerateClinicianSummaryInput",
    "GeneratePatientSummaryInput",
    "PatientSummaryTemplateOutput",
    "RedFlagSummaryItem",
    "SummaryToolError",
    "ToolMetadata",
    "export_case_trace",
    "generate_clinician_summary",
    "generate_patient_summary_template",
]
