"""Triage tools for visit-route classification and initial case assessment.

This module provides rule-driven triage functionality for TCMAgent's intake layer.

Goals
-----
- Classify patient visit routes (online / offline / emergency / human-review)
- Tag special patient populations (pregnant, elderly, pediatric, etc.)
- Execute a full initial triage to set case stage and collect routing metadata

All logic is intentionally rule-based (no LLM calls) to ensure:
- Speed and reliability for first-contact decisions
- Full auditability via structured audit events
- Safe-by-default behaviour for clinical risk management
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tcm_agent.schemas.case import (
    AuditEvent,
    CaseStage,
    FactType,
    NormalizedFact,
    PatientProfile,
)
from tcm_agent.tools.case_tools import CASE_STORE, CaseNotFoundError  # noqa: F401

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    """Generate a stable prefixed UUID-based ID."""
    return f"{prefix}_{uuid4().hex}"


def _append_audit_event(
    state: Any,
    *,
    actor: str,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append an audit event to *state* and refresh ``updated_at``."""
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


# ---------------------------------------------------------------------------
# ToolMetadata
# ---------------------------------------------------------------------------


class ToolMetadata(BaseModel):
    """Common metadata returned by every triage tool response."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    tool_name: str
    tool_version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utcnow)
    message: str = ""


class TriageToolError(RuntimeError):
    """Raised when a triage operation cannot be completed."""


# ---------------------------------------------------------------------------
# Input / Output Pydantic models
# ---------------------------------------------------------------------------


class ClassifyVisitRouteInput(BaseModel):
    """Request payload for visit-route classification."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    chief_complaint: str
    duration_days: int | None = Field(default=None, ge=0)
    symptom_severity: Literal["low", "medium", "high", "critical"] | None = None
    channel: str | None = None
    actor: str = "system"
    trace_id: str | None = None


class ClassifyVisitRouteOutput(BaseModel):
    """Response payload for visit-route classification."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    recommended_route: Literal["online_continue", "offline_referral", "emergency", "human_review"]
    route_reason: str
    eligibility_notes: list[str] = Field(default_factory=list)
    metadata: ToolMetadata


class TagSpecialPopulationInput(BaseModel):
    """Request payload for tagging special patient populations."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    population_tags: list[str]
    tag_reasons: dict[str, str] = Field(default_factory=dict)
    actor: str = "system"
    trace_id: str | None = None


class TagSpecialPopulationOutput(BaseModel):
    """Response payload for special-population tagging."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    tagged_count: int
    tagged_labels: list[str] = Field(default_factory=list)
    updated_facts_count: int
    metadata: ToolMetadata


class RunTriageInput(BaseModel):
    """Request payload for a full initial triage assessment."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    chief_complaint: str
    patient_age: int | None = Field(default=None, ge=0, le=130)
    patient_gender: str | None = None
    symptom_duration_days: int | None = Field(default=None, ge=0)
    is_pregnant: bool | None = None
    existing_conditions: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    symptom_severity: Literal["low", "medium", "high", "critical"] | None = None
    actor: str = "system"
    trace_id: str | None = None


class TriageOutput(BaseModel):
    """Response payload for the full triage assessment."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    case_id: str
    triage_level: Literal["low", "medium", "high", "critical"]
    recommended_route: str
    red_flag_hints: list[str] = Field(default_factory=list)
    special_population_tags: list[str] = Field(default_factory=list)
    eligible_for_online: bool
    triage_reason: str
    metadata: ToolMetadata


# ---------------------------------------------------------------------------
# Red-flag keyword detection rules
# ---------------------------------------------------------------------------


class _RedFlagKeywordRule(NamedTuple):
    """A keyword-based red-flag detection rule for Chinese chief-complaint text."""

    hint: str
    keywords: tuple[str, ...]
    severity: str  # "critical" | "high" | "medium"


# Severity ordinal for comparison (higher = more severe)
_SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

_RED_FLAG_KEYWORD_RULES: tuple[_RedFlagKeywordRule, ...] = (
    # --- critical -----------------------------------------------------------
    _RedFlagKeywordRule(
        hint="呼吸困难",
        keywords=("呼吸困难", "呼吸急促", "喘不过气", "胸闷气急", "憋气", "气促"),
        severity="critical",
    ),
    _RedFlagKeywordRule(
        hint="意识障碍",
        keywords=(
            "意识丧失",
            "意识不清",
            "昏迷",
            "不省人事",
            "失去意识",
            "晕厥",
            "昏倒",
            "神志不清",
            "神志模糊",
        ),
        severity="critical",
    ),
    _RedFlagKeywordRule(
        hint="抽搐",
        keywords=("抽搐", "抽风", "癫痫发作", "惊厥", "全身抽动"),
        severity="critical",
    ),
    _RedFlagKeywordRule(
        hint="呕血/咯血",
        keywords=("呕血", "吐血", "咯血", "大量出血"),
        severity="critical",
    ),
    # --- high ---------------------------------------------------------------
    _RedFlagKeywordRule(
        hint="胸痛/胸闷",
        keywords=("胸痛", "心痛", "心绞痛", "胸部疼痛", "胸口痛", "左胸痛"),
        severity="high",
    ),
    _RedFlagKeywordRule(
        hint="消化道出血",
        keywords=("黑便", "便血", "血便", "柏油样便", "出血"),
        severity="high",
    ),
    _RedFlagKeywordRule(
        hint="高热",
        keywords=(
            "高热",
            "高烧",
            "发烧超过39",
            "发热超过39",
            "体温超过39",
            "持续高热",
            "持续发热",
        ),
        severity="high",
    ),
    _RedFlagKeywordRule(
        hint="突发剧烈头痛",
        keywords=("剧烈头痛", "突发头痛", "爆裂样头痛", "雷击样头痛", "霹雳样头痛"),
        severity="high",
    ),
    _RedFlagKeywordRule(
        hint="肢体无力/偏瘫",
        keywords=("偏瘫", "半身不遂", "肢体无力", "突然无力", "单侧无力"),
        severity="high",
    ),
    _RedFlagKeywordRule(
        hint="失语/言语障碍",
        keywords=("失语", "说话困难", "言语不清", "突然说不出话", "口齿不清"),
        severity="high",
    ),
    # --- medium -------------------------------------------------------------
    _RedFlagKeywordRule(
        hint="剧烈腹痛",
        keywords=("剧烈腹痛", "腹痛难忍", "持续腹痛", "撕裂样腹痛"),
        severity="medium",
    ),
    _RedFlagKeywordRule(
        hint="撕裂样疼痛",
        keywords=("撕裂样疼痛", "撕裂感", "胸背痛", "背部撕裂"),
        severity="medium",
    ),
)


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------


def _scan_red_flags(text: str) -> tuple[list[str], str | None]:
    """Scan chief-complaint text for Chinese red-flag keywords.

    Parameters
    ----------
    text:
        Raw chief-complaint string to scan.

    Returns
    -------
    hints:
        Human-readable hint names for each matched red-flag rule.
    worst_severity:
        The highest severity string found, or ``None`` if nothing matched.
    """
    if not text:
        return [], None

    hints: list[str] = []
    worst_severity: str | None = None

    for rule in _RED_FLAG_KEYWORD_RULES:
        if any(kw in text for kw in rule.keywords):
            hints.append(rule.hint)
            if worst_severity is None or (
                _SEVERITY_ORDER[rule.severity] > _SEVERITY_ORDER[worst_severity]
            ):
                worst_severity = rule.severity

    return hints, worst_severity


def _detect_population_tags(
    *,
    patient_age: int | None,
    patient_gender: str | None,
    is_pregnant: bool | None,
    existing_conditions: list[str],
    current_medications: list[str],
) -> tuple[list[str], dict[str, str]]:
    """Detect special-population tags from structured patient demographics.

    Parameters
    ----------
    patient_age, patient_gender, is_pregnant, existing_conditions, current_medications:
        Demographic and clinical inputs from the triage intake.

    Returns
    -------
    tags:
        Detected population-tag identifiers.
    reasons:
        Per-tag human-readable reason strings used for audit and fact source_text.
    """
    # patient_gender is reserved for future gender-specific logic
    tags: list[str] = []
    reasons: dict[str, str] = {}

    # Pregnancy
    if is_pregnant is True:
        tags.append("pregnant")
        reasons["pregnant"] = "患者处于孕期,需要提高风险敏感度并选择更保守的问诊策略"

    # Age-based groups
    if patient_age is not None:
        if patient_age < 14:
            tags.append("pediatric")
            reasons["pediatric"] = f"患者年龄为 {patient_age} 岁，属于儿童/青少年群体，需更保守阈值"
        elif patient_age >= 65:
            tags.append("elderly")
            reasons["elderly"] = f"患者年龄为 {patient_age} 岁，属于高龄群体，合并风险更高"

    # Chronic kidney disease (from existing conditions)
    kidney_keywords = ("肾病", "慢性肾", "肾功能不全", "肾衰", "kidney", "renal", "nephro")
    for cond in existing_conditions:
        if any(kw in cond.lower() for kw in kidney_keywords) and "chronic_kidney" not in tags:
            tags.append("chronic_kidney")
            reasons["chronic_kidney"] = f"患者既往病史中包含肾脏相关疾病：{cond}"

    # Anticoagulant medications
    anticoag_keywords = (
        "华法林",
        "warfarin",
        "利伐沙班",
        "rivaroxaban",
        "阿哌沙班",
        "apixaban",
        "达比加群",
        "dabigatran",
        "抗凝药",
        "anticoagulant",
        "肝素",
        "heparin",
        "低分子肝素",
    )
    for med in current_medications:
        if any(kw in med.lower() for kw in anticoag_keywords) and "on_anticoagulants" not in tags:
            tags.append("on_anticoagulants")
            reasons["on_anticoagulants"] = f"患者正在服用抗凝药物：{med}"

    return tags, reasons


def _derive_visit_route(
    *,
    symptom_severity: str | None,
    red_flag_severity: str | None,
    population_tags: list[str],
) -> tuple[
    Literal["online_continue", "offline_referral", "emergency", "human_review"],
    str,
    list[str],
]:
    """Map risk signals to a recommended visit route.

    Returns
    -------
    route:
        One of ``"online_continue"``, ``"offline_referral"``,
        ``"emergency"``, or ``"human_review"``.
    reason:
        Short rationale for the decision.
    notes:
        Additional eligibility / advisory notes for the caller.
    """
    notes: list[str] = []

    worst = max(
        _SEVERITY_ORDER.get(red_flag_severity or "low", 0),
        _SEVERITY_ORDER.get(symptom_severity or "low", 0),
    )

    if worst >= _SEVERITY_ORDER["critical"]:
        notes.append("检测到高危红旗症状或自述病情危急，建议立即拨打急救电话或前往急诊科")
        return (
            "emergency",
            "存在危及生命的高危症状，需立即急诊处理",
            notes,
        )
    elif worst >= _SEVERITY_ORDER["high"]:
        notes.append("存在需要优先评估的高风险症状，建议尽快前往线下医院就诊")
        return (
            "offline_referral",
            "存在高风险症状，需线下医院专业评估",
            notes,
        )
    elif population_tags:
        tag_str = "、".join(population_tags)
        notes.append(f"患者属于特殊人群（{tag_str}），建议人工审核后决定后续问诊策略")
        return (
            "human_review",
            f"患者属于特殊人群（{tag_str}），需人工复核路由决策",
            notes,
        )
    elif worst >= _SEVERITY_ORDER["medium"]:
        notes.append("症状严重程度为中等，建议结合医生审核确认是否适合继续线上问诊")
        return (
            "human_review",
            "中等风险症状，需人工确认后方可继续线上问诊",
            notes,
        )
    else:
        notes.append("暂未检测到明显高风险信号，可继续在线进行详细问诊")
        return (
            "online_continue",
            "无明显高危信号，适合继续线上问诊",
            notes,
        )


def _determine_triage_level(
    symptom_severity: str | None,
    red_flag_severity: str | None,
    population_tags: list[str],
) -> Literal["low", "medium", "high", "critical"]:
    """Map combined risk signals to a single triage level."""
    worst = max(
        _SEVERITY_ORDER.get(red_flag_severity or "low", 0),
        _SEVERITY_ORDER.get(symptom_severity or "low", 0),
    )
    if worst >= _SEVERITY_ORDER["critical"]:
        return "critical"
    if worst >= _SEVERITY_ORDER["high"]:
        return "high"
    if worst >= _SEVERITY_ORDER["medium"] or population_tags:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def _metadata(tool_name: str, trace_id: str | None, message: str) -> ToolMetadata:
    """Construct a ToolMetadata instance."""
    return ToolMetadata(
        tool_name=tool_name,
        trace_id=trace_id or _new_id("trace"),
        message=message,
    )


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def classify_visit_route(payload: ClassifyVisitRouteInput) -> ClassifyVisitRouteOutput:
    """Classify the recommended visit route based on chief complaint and declared severity.

    This is a pure rule-based function with no LLM calls. It scans the chief
    complaint text for Chinese red-flag keywords, combines that signal with the
    caller-declared ``symptom_severity``, and derives a routing decision.

    Parameters
    ----------
    payload:
        Structured input containing ``case_id``, ``chief_complaint``, and
        optional ``symptom_severity`` / ``duration_days`` / ``channel``.

    Returns
    -------
    ClassifyVisitRouteOutput:
        Contains ``recommended_route``, ``route_reason``, and
        ``eligibility_notes``.

    Side effects
    ------------
    - Appends a ``visit_route_classified`` audit event to the case state.
    - Updates ``case_state.chief_complaint`` if it was previously unset.

    Raises
    ------
    CaseNotFoundError:
        If ``payload.case_id`` does not exist in the store.
    """
    record = CASE_STORE.get(payload.case_id)
    state = record.state

    # Scan chief complaint for red-flag keywords
    red_flag_hints, red_flag_severity = _scan_red_flags(payload.chief_complaint)

    # Collect already-stored population tags from normalized facts
    existing_pop_tags = [
        fact.normalized_key
        for fact in state.normalized_facts
        if fact.fact_type == FactType.POPULATION_TAG
    ]

    # Derive the visit route
    route, route_reason, eligibility_notes = _derive_visit_route(
        symptom_severity=payload.symptom_severity,
        red_flag_severity=red_flag_severity,
        population_tags=existing_pop_tags,
    )

    # Persist chief_complaint if not yet recorded on the case
    if state.chief_complaint is None:
        stripped = payload.chief_complaint.strip()
        state.chief_complaint = stripped or None

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="visit_route_classified",
        message=f"就诊路径已分类：{route}",
        payload={
            "chief_complaint": payload.chief_complaint,
            "duration_days": payload.duration_days,
            "symptom_severity": payload.symptom_severity,
            "red_flag_hints": red_flag_hints,
            "red_flag_severity": red_flag_severity,
            "recommended_route": route,
            "route_reason": route_reason,
        },
    )

    CASE_STORE.save(record)

    return ClassifyVisitRouteOutput(
        case_id=payload.case_id,
        recommended_route=route,
        route_reason=route_reason,
        eligibility_notes=eligibility_notes,
        metadata=_metadata(
            tool_name="classify_visit_route",
            trace_id=payload.trace_id,
            message=f"Visit route classified as '{route}'.",
        ),
    )


def tag_special_population(payload: TagSpecialPopulationInput) -> TagSpecialPopulationOutput:
    """Write special-population tags into the case state as NormalizedFact entries.

    Each tag in ``population_tags`` is stored as a ``POPULATION_TAG``-typed
    ``NormalizedFact`` with ``normalized_value=True``. Existing facts with the
    same ``normalized_key`` are updated in-place (upsert semantics).

    Parameters
    ----------
    payload:
        ``case_id``, list of population tag strings, and optional per-tag
        reason strings written as ``source_text`` on the fact.

    Returns
    -------
    TagSpecialPopulationOutput:
        Includes the count and labels of tags written, plus the updated total
        fact count.

    Side effects
    ------------
    - Adds or updates ``POPULATION_TAG`` NormalizedFact entries in case state.
    - Appends a ``special_population_tagged`` audit event.

    Raises
    ------
    CaseNotFoundError:
        If ``payload.case_id`` does not exist in the store.
    """
    # Early exit when there is nothing to do
    if not payload.population_tags:
        record = CASE_STORE.get(payload.case_id)
        return TagSpecialPopulationOutput(
            case_id=payload.case_id,
            tagged_count=0,
            tagged_labels=[],
            updated_facts_count=len(record.state.normalized_facts),
            metadata=_metadata(
                tool_name="tag_special_population",
                trace_id=payload.trace_id,
                message="No population tags provided; no changes made.",
            ),
        )

    record = CASE_STORE.get(payload.case_id)
    state = record.state

    # Build a lookup index over existing POPULATION_TAG facts
    existing_index: dict[str, int] = {
        fact.normalized_key: idx
        for idx, fact in enumerate(state.normalized_facts)
        if fact.fact_type == FactType.POPULATION_TAG
    }

    written_labels: list[str] = []

    for raw_tag in payload.population_tags:
        tag = raw_tag.strip()
        if not tag:
            continue

        new_fact = NormalizedFact(
            fact_type=FactType.POPULATION_TAG,
            normalized_key=tag,
            normalized_value=True,
            source_text=payload.tag_reasons.get(tag),
            confidence=1.0,
        )

        idx = existing_index.get(tag)
        if idx is not None:
            state.normalized_facts[idx] = new_fact
        else:
            existing_index[tag] = len(state.normalized_facts)
            state.normalized_facts.append(new_fact)

        written_labels.append(tag)

    label_str = ", ".join(written_labels) if written_labels else "(none)"
    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="special_population_tagged",
        message=f"写入特殊人群标签：{label_str}",
        payload={
            "tagged_labels": written_labels,
            "tag_reasons": {k: v for k, v in payload.tag_reasons.items() if k in written_labels},
        },
    )

    CASE_STORE.save(record)

    return TagSpecialPopulationOutput(
        case_id=payload.case_id,
        tagged_count=len(written_labels),
        tagged_labels=written_labels,
        updated_facts_count=len(state.normalized_facts),
        metadata=_metadata(
            tool_name="tag_special_population",
            trace_id=payload.trace_id,
            message=f"Tagged {len(written_labels)} special population label(s).",
        ),
    )


def run_triage(payload: RunTriageInput) -> TriageOutput:
    """Execute a complete first-contact triage assessment for the case.

    This orchestrates the full intake triage pipeline:

    1. Updates the patient profile with any provided demographic data.
    2. Detects special patient populations from demographics and history.
    3. Writes detected population tags into the case state as structured facts.
    4. Scans the chief complaint for Chinese red-flag keywords.
    5. Classifies the recommended visit route.
    6. Transitions ``case_stage`` from ``CREATED`` to ``TRIAGED`` when applicable.
    7. Persists a ``triage_completed`` audit event with the full decision payload.

    All logic is rule-based; no LLM calls are made.

    Parameters
    ----------
    payload:
        Full intake triage request including demographics, chief complaint,
        existing conditions, medications, and optional severity override.

    Returns
    -------
    TriageOutput:
        Structured triage result containing level, route, detected red-flag
        hints, population tags, and eligibility flag.

    Side effects
    ------------
    - May create or enrich ``patient_profile`` in the case state.
    - Sets ``chief_complaint`` on the case if not previously stored.
    - Writes ``POPULATION_TAG`` normalized facts.
    - Transitions ``case_stage`` to ``TRIAGED`` (only from ``CREATED``).
    - Appends one or more audit events.

    Raises
    ------
    CaseNotFoundError:
        If ``payload.case_id`` does not exist in the store.
    """
    # ------------------------------------------------------------------
    # Step 1: Initialise / enrich patient profile and chief complaint
    # ------------------------------------------------------------------
    record = CASE_STORE.get(payload.case_id)
    state = record.state

    if state.patient_profile is None:
        state.patient_profile = PatientProfile()

    profile = state.patient_profile

    # Only update fields that are not yet set (non-destructive merge)
    profile_updates: dict[str, Any] = {}
    if payload.patient_age is not None and profile.age is None:
        profile_updates["age"] = payload.patient_age
    if payload.patient_gender is not None and profile.gender is None:
        profile_updates["gender"] = payload.patient_gender
    if payload.is_pregnant is not None and profile.is_pregnant is None:
        profile_updates["is_pregnant"] = payload.is_pregnant
    if payload.existing_conditions and not profile.known_conditions:
        profile_updates["known_conditions"] = list(payload.existing_conditions)
    if payload.current_medications and not profile.current_medications:
        profile_updates["current_medications"] = list(payload.current_medications)

    if profile_updates:
        state.patient_profile = profile.model_copy(update=profile_updates)

    if state.chief_complaint is None:
        stripped = payload.chief_complaint.strip()
        state.chief_complaint = stripped or None

    state.updated_at = utcnow()
    CASE_STORE.save(record)

    # ------------------------------------------------------------------
    # Step 2: Detect and tag special populations
    # ------------------------------------------------------------------
    pop_tags, tag_reasons = _detect_population_tags(
        patient_age=payload.patient_age,
        patient_gender=payload.patient_gender,
        is_pregnant=payload.is_pregnant,
        existing_conditions=payload.existing_conditions,
        current_medications=payload.current_medications,
    )

    if pop_tags:
        tag_special_population(
            TagSpecialPopulationInput(
                case_id=payload.case_id,
                population_tags=pop_tags,
                tag_reasons=tag_reasons,
                actor=payload.actor,
                trace_id=payload.trace_id,
            )
        )

    # ------------------------------------------------------------------
    # Step 3: Scan chief complaint for red flags and classify route
    # ------------------------------------------------------------------
    red_flag_hints, red_flag_severity = _scan_red_flags(payload.chief_complaint)

    route_result = classify_visit_route(
        ClassifyVisitRouteInput(
            case_id=payload.case_id,
            chief_complaint=payload.chief_complaint,
            duration_days=payload.symptom_duration_days,
            symptom_severity=payload.symptom_severity,
            actor=payload.actor,
            trace_id=payload.trace_id,
        )
    )

    # ------------------------------------------------------------------
    # Step 4: Determine triage level, finalize stage, persist decision
    # ------------------------------------------------------------------
    triage_level = _determine_triage_level(
        payload.symptom_severity,
        red_flag_severity,
        pop_tags,
    )
    eligible_for_online = route_result.recommended_route == "online_continue" and triage_level in {
        "low",
        "medium",
    }

    # Build a human-readable composite reason string
    reason_parts: list[str] = []
    if red_flag_hints:
        reason_parts.append("主诉中检测到红旗症状：" + "、".join(red_flag_hints))
    if pop_tags:
        reason_parts.append("特殊人群标签：" + "、".join(pop_tags))
    if payload.symptom_severity:
        reason_parts.append(f"患者自述症状严重程度：{payload.symptom_severity}")
    if payload.symptom_duration_days is not None:
        reason_parts.append(f"症状持续天数：{payload.symptom_duration_days} 天")
    if not reason_parts:
        reason_parts.append("未检测到明显高危信号，暂归入低风险路径")
    triage_reason = "；".join(reason_parts)

    # Re-fetch after sub-function saves to get the latest state
    record = CASE_STORE.get(payload.case_id)
    state = record.state

    # Stage transition: only advance from CREATED -> TRIAGED
    if state.case_stage == CaseStage.CREATED:
        state.case_stage = CaseStage.TRIAGED

    _append_audit_event(
        state,
        actor=payload.actor,
        event_type="triage_completed",
        message=(
            f"导诊完成：分级={triage_level}，"
            f"路径={route_result.recommended_route}，"
            f"可线上继续={eligible_for_online}"
        ),
        payload={
            "triage_level": triage_level,
            "recommended_route": route_result.recommended_route,
            "red_flag_hints": red_flag_hints,
            "red_flag_severity": red_flag_severity,
            "special_population_tags": pop_tags,
            "eligible_for_online": eligible_for_online,
            "triage_reason": triage_reason,
            "symptom_severity": payload.symptom_severity,
            "symptom_duration_days": payload.symptom_duration_days,
        },
    )

    CASE_STORE.save(record)

    return TriageOutput(
        case_id=payload.case_id,
        triage_level=triage_level,
        recommended_route=route_result.recommended_route,
        red_flag_hints=red_flag_hints,
        special_population_tags=pop_tags,
        eligible_for_online=eligible_for_online,
        triage_reason=triage_reason,
        metadata=_metadata(
            tool_name="run_triage",
            trace_id=payload.trace_id,
            message=(
                f"Triage completed: level={triage_level}, route={route_result.recommended_route}."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ClassifyVisitRouteInput",
    "ClassifyVisitRouteOutput",
    "RunTriageInput",
    "TagSpecialPopulationInput",
    "TagSpecialPopulationOutput",
    "ToolMetadata",
    "TriageOutput",
    "TriageToolError",
    "classify_visit_route",
    "run_triage",
    "tag_special_population",
]
