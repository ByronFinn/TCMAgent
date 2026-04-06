"""Safety tools for red-flag screening and risk decisions.

This module provides the first MVP implementation of TCMAgent's safety layer.

Goals
-----
- Screen for obvious red-flag conditions from structured facts
- Apply special-population risk adjustments
- Check basic contraindication conditions
- Produce a structured risk decision
- Persist that decision back into case state

This is intentionally conservative and heuristic-driven. It is designed to be:
- immediately usable by API routes, services, and future agent-tool wrappers
- easy to audit
- straightforward to replace with richer rule engines later
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tcm_agent.schemas.case import (
    ContraindicationFlag,
    MatchedRedFlag,
    NormalizedFact,
    PopulationRiskAdjustment,
    RiskDecision,
    RiskLevel,
    Severity,
)
from tcm_agent.tools.case_tools import (
    GetCaseStateInput,
    SaveRiskDecisionInput,
    SaveRiskDecisionOutput,
    get_case_state,
    save_risk_decision,
)


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    """Generate a stable prefixed ID."""
    return f"{prefix}_{uuid4().hex}"


def _fact_value_is_true(value: object) -> bool:
    """Interpret a normalized fact value as true-ish."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "yes",
            "y",
            "present",
            "positive",
            "有",
            "是",
            "明显",
        }
    if isinstance(value, list):
        return len(value) > 0
    return False


class ToolMetadata(BaseModel):
    """Common metadata returned by safety tool responses."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    tool_name: str
    tool_version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utcnow)
    message: str = ""


class SafetyToolError(RuntimeError):
    """Raised when a safety operation cannot be completed."""


class ScreenRedFlagsInput(BaseModel):
    """Request payload for red-flag screening."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    facts: list[NormalizedFact] = Field(default_factory=list)
    population_tags: list[str] = Field(default_factory=list)
    actor: str = "system"
    trace_id: str | None = None


class ScreenRedFlagsOutput(BaseModel):
    """Response payload for red-flag screening."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    matched_red_flags: list[MatchedRedFlag] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.NONE
    requires_immediate_action: bool = False
    metadata: ToolMetadata


class CheckSpecialPopulationRisksInput(BaseModel):
    """Request payload for special-population risk checks."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    population_tags: list[str] = Field(default_factory=list)
    facts: list[NormalizedFact] = Field(default_factory=list)
    actor: str = "system"
    trace_id: str | None = None


class CheckSpecialPopulationRisksOutput(BaseModel):
    """Response payload for population-based risk checks."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    risk_adjustments: list[PopulationRiskAdjustment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: ToolMetadata


class CheckContraindicationsInput(BaseModel):
    """Request payload for contraindication checks."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    facts: list[NormalizedFact] = Field(default_factory=list)
    population_tags: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    actor: str = "system"
    trace_id: str | None = None


class CheckContraindicationsOutput(BaseModel):
    """Response payload for contraindication checks."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    contraindication_flags: list[ContraindicationFlag] = Field(default_factory=list)
    requires_human_review: bool = False
    requires_offline_visit: bool = False
    metadata: ToolMetadata


class IssueRiskDecisionInput(BaseModel):
    """Request payload for issuing a formal risk decision."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    red_flags: list[MatchedRedFlag] = Field(default_factory=list)
    contraindication_flags: list[ContraindicationFlag] = Field(default_factory=list)
    population_risks: list[PopulationRiskAdjustment] = Field(default_factory=list)
    current_stage: str
    actor: str = "system"
    trace_id: str | None = None


class IssueRiskDecisionOutput(BaseModel):
    """Response payload for the formal risk decision."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    decision_id: str
    risk_level: RiskLevel
    safe_to_continue: bool
    recommend_offline_visit: bool
    recommend_human_review: bool
    recommended_route: str | None = None
    decision_reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    persisted: bool = False
    metadata: ToolMetadata


@dataclass(slots=True, frozen=True)
class RedFlagRule:
    """A simple heuristic red-flag rule."""

    red_flag_id: str
    name: str
    trigger_keys: tuple[str, ...]
    severity: Severity
    recommended_route: str
    notes: str | None = None


_RED_FLAG_RULES: tuple[RedFlagRule, ...] = (
    RedFlagRule(
        red_flag_id="redflag:chest-pain",
        name="持续胸痛或胸闷明显加重",
        trigger_keys=("chest_pain", "chest_oppression"),
        severity=Severity.CRITICAL,
        recommended_route="offline_visit_or_emergency",
        notes="需优先排除心肺高风险问题。",
    ),
    RedFlagRule(
        red_flag_id="redflag:breathing-difficulty",
        name="呼吸困难",
        trigger_keys=("shortness_of_breath", "breathing_difficulty"),
        severity=Severity.CRITICAL,
        recommended_route="emergency_visit",
        notes="呼吸相关高风险需立即升级处理。",
    ),
    RedFlagRule(
        red_flag_id="redflag:altered-consciousness",
        name="意识异常",
        trigger_keys=("altered_consciousness", "confusion", "syncope"),
        severity=Severity.CRITICAL,
        recommended_route="emergency_visit",
        notes="存在神志异常时不应继续普通线上问诊。",
    ),
    RedFlagRule(
        red_flag_id="redflag:persistent-high-fever",
        name="高热不退",
        trigger_keys=("persistent_high_fever", "high_fever"),
        severity=Severity.HIGH,
        recommended_route="offline_visit",
        notes="高热持续需线下评估。",
    ),
    RedFlagRule(
        red_flag_id="redflag:bleeding",
        name="出血相关高风险",
        trigger_keys=("bleeding", "vomiting_blood", "black_stool"),
        severity=Severity.CRITICAL,
        recommended_route="emergency_visit",
        notes="出血相关情况应立即升级。",
    ),
    RedFlagRule(
        red_flag_id="redflag:severe-headache",
        name="突发剧烈头痛",
        trigger_keys=("sudden_severe_headache",),
        severity=Severity.HIGH,
        recommended_route="offline_visit_or_emergency",
        notes="需谨慎排除急症路径。",
    ),
    RedFlagRule(
        red_flag_id="redflag:seizure",
        name="抽搐",
        trigger_keys=("seizure", "convulsion"),
        severity=Severity.CRITICAL,
        recommended_route="emergency_visit",
        notes="抽搐属于高危信号。",
    ),
)


_POPULATION_WARNING_MAP: dict[str, tuple[float, str]] = {
    "pregnant": (0.25, "孕期需提高风险阈值，优先避免继续在线处理高风险问题。"),
    "child": (0.20, "儿童人群问诊需更保守，线下阈值应前移。"),
    "elderly": (0.15, "高龄人群合并风险更高，应提高升级敏感度。"),
    "chronic_disease": (0.15, "慢病患者需警惕基础病干扰与风险放大。"),
    "polypharmacy": (0.15, "多药联用人群需警惕潜在禁忌与相互作用。"),
    "immunocompromised": (0.20, "免疫低下人群需更保守处理。"),
}

_PREGNANCY_TAGS = {"pregnant", "孕妇", "pregnancy", "is_pregnant"}
_CHILD_TAGS = {"child", "儿童", "pediatric"}
_ELDERLY_TAGS = {"elderly", "高龄", "older_adult"}
_CHRONIC_TAGS = {"chronic_disease", "慢病", "hypertension", "diabetes"}
_POLYPHARMACY_TAGS = {"polypharmacy", "多药联用"}

_OFFLINE_CONTRA_KEYS = {
    "persistent_high_fever",
    "bleeding",
    "vomiting_blood",
    "black_stool",
    "shortness_of_breath",
    "breathing_difficulty",
    "altered_consciousness",
    "seizure",
}

_HIGH_RISK_CANDIDATE_IDS = {
    "disease:acute-abdominal-pain",
    "disease:cardiopulmonary-risk",
    "disease:stroke-risk",
}


def _metadata(tool_name: str, trace_id: str | None, message: str) -> ToolMetadata:
    """Build tool metadata."""
    return ToolMetadata(
        tool_name=tool_name,
        trace_id=trace_id or _new_id("trace"),
        message=message,
    )


def _normalize_population_tags(tags: list[str]) -> set[str]:
    """Normalize population tags into a lowercased set."""
    return {tag.strip().lower() for tag in tags if tag.strip()}


def _collect_positive_fact_keys(facts: list[NormalizedFact]) -> set[str]:
    """Collect positive normalized fact keys."""
    return {fact.normalized_key for fact in facts if _fact_value_is_true(fact.normalized_value)}


def screen_red_flags(payload: ScreenRedFlagsInput) -> ScreenRedFlagsOutput:
    """Screen structured facts for obvious red-flag conditions."""
    fact_keys = _collect_positive_fact_keys(payload.facts)
    matched: list[MatchedRedFlag] = []

    for rule in _RED_FLAG_RULES:
        if any(key in fact_keys for key in rule.trigger_keys):
            matched.append(
                MatchedRedFlag(
                    red_flag_id=rule.red_flag_id,
                    name=rule.name,
                    severity=rule.severity,
                    evidence_refs=[f"fact:{key}" for key in rule.trigger_keys if key in fact_keys],
                    recommended_route=rule.recommended_route,
                    notes=rule.notes,
                )
            )

    if any(flag.severity == Severity.CRITICAL for flag in matched):
        risk_level = RiskLevel.CRITICAL
    elif any(flag.severity == Severity.HIGH for flag in matched):
        risk_level = RiskLevel.HIGH
    else:
        risk_level = RiskLevel.NONE

    return ScreenRedFlagsOutput(
        matched_red_flags=matched,
        risk_level=risk_level,
        requires_immediate_action=risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        metadata=_metadata(
            tool_name="screen_red_flags",
            trace_id=payload.trace_id,
            message=f"Screened red flags: {len(matched)} matched.",
        ),
    )


def check_special_population_risks(
    payload: CheckSpecialPopulationRisksInput,
) -> CheckSpecialPopulationRisksOutput:
    """Apply risk adjustments for special populations."""
    tags = _normalize_population_tags(payload.population_tags)
    adjustments: list[PopulationRiskAdjustment] = []
    warnings: list[str] = []

    # Explicit tag-driven adjustments
    for tag, (risk_delta, reason) in _POPULATION_WARNING_MAP.items():
        if tag in tags:
            adjustments.append(
                PopulationRiskAdjustment(
                    population_tag=tag,
                    risk_delta=risk_delta,
                    reason=reason,
                    evidence_refs=[f"population:{tag}"],
                )
            )
            warnings.append(reason)

    # Infer tags from facts if possible
    fact_keys = _collect_positive_fact_keys(payload.facts)

    if "is_pregnant" in fact_keys and "pregnant" not in tags:
        adjustments.append(
            PopulationRiskAdjustment(
                population_tag="pregnant",
                risk_delta=0.25,
                reason="从结构化事实识别到孕期，需要提高风险敏感度。",
                evidence_refs=["fact:is_pregnant"],
            )
        )
        warnings.append("从结构化事实识别到孕期，需要提高风险敏感度。")

    return CheckSpecialPopulationRisksOutput(
        risk_adjustments=adjustments,
        warnings=warnings,
        metadata=_metadata(
            tool_name="check_special_population_risks",
            trace_id=payload.trace_id,
            message=f"Applied {len(adjustments)} population risk adjustment(s).",
        ),
    )


def check_contraindications(
    payload: CheckContraindicationsInput,
) -> CheckContraindicationsOutput:
    """Check for simple contraindication conditions in the MVP stage."""
    fact_keys = _collect_positive_fact_keys(payload.facts)
    tags = _normalize_population_tags(payload.population_tags)

    flags: list[ContraindicationFlag] = []
    requires_human_review = False
    requires_offline_visit = False

    if any(key in fact_keys for key in _OFFLINE_CONTRA_KEYS):
        matched_keys = sorted(key for key in _OFFLINE_CONTRA_KEYS if key in fact_keys)
        flags.append(
            ContraindicationFlag(
                contraindication_id="contra:unsafe-online-continue",
                name="不适合继续普通线上问诊",
                severity=Severity.HIGH,
                reason="命中了需要优先线下评估的高风险症状。",
                evidence_refs=[f"fact:{key}" for key in matched_keys],
            )
        )
        requires_offline_visit = True
        requires_human_review = True

    if tags & _PREGNANCY_TAGS and ("bleeding" in fact_keys or "severe_abdominal_pain" in fact_keys):
        flags.append(
            ContraindicationFlag(
                contraindication_id="contra:pregnancy-risk",
                name="孕期高风险症状",
                severity=Severity.CRITICAL,
                reason="孕期合并高风险症状时不应继续普通线上问诊。",
                evidence_refs=[
                    "population:pregnant",
                    *[
                        f"fact:{key}"
                        for key in ("bleeding", "severe_abdominal_pain")
                        if key in fact_keys
                    ],
                ],
            )
        )
        requires_offline_visit = True
        requires_human_review = True

    if tags & _CHILD_TAGS and "persistent_high_fever" in fact_keys:
        flags.append(
            ContraindicationFlag(
                contraindication_id="contra:child-persistent-fever",
                name="儿童持续高热",
                severity=Severity.HIGH,
                reason="儿童持续高热需尽快线下评估。",
                evidence_refs=["population:child", "fact:persistent_high_fever"],
            )
        )
        requires_offline_visit = True

    if set(payload.candidate_ids) & _HIGH_RISK_CANDIDATE_IDS:
        flags.append(
            ContraindicationFlag(
                contraindication_id="contra:high-risk-candidate",
                name="候选疾病存在高风险路径",
                severity=Severity.HIGH,
                reason="当前候选中存在需更谨慎处理的高风险方向。",
                evidence_refs=[
                    cid for cid in payload.candidate_ids if cid in _HIGH_RISK_CANDIDATE_IDS
                ],
            )
        )
        requires_human_review = True

    return CheckContraindicationsOutput(
        contraindication_flags=flags,
        requires_human_review=requires_human_review,
        requires_offline_visit=requires_offline_visit,
        metadata=_metadata(
            tool_name="check_contraindications",
            trace_id=payload.trace_id,
            message=f"Checked contraindications: {len(flags)} flag(s).",
        ),
    )


def _aggregate_population_risk(population_risks: list[PopulationRiskAdjustment]) -> float:
    """Aggregate population risk deltas."""
    return sum(item.risk_delta for item in population_risks)


def _derive_route(
    risk_level: RiskLevel,
    *,
    recommend_offline_visit: bool,
    red_flags: list[MatchedRedFlag],
) -> str | None:
    """Derive the recommended route from current safety state."""
    if risk_level == RiskLevel.CRITICAL:
        if any(flag.recommended_route == "emergency_visit" for flag in red_flags):
            return "emergency_visit"
        return "offline_visit_or_emergency"
    if recommend_offline_visit or risk_level == RiskLevel.HIGH:
        return "offline_visit"
    if risk_level == RiskLevel.MEDIUM:
        return "human_review"
    return None


def issue_risk_decision(payload: IssueRiskDecisionInput) -> IssueRiskDecisionOutput:
    """Issue and persist a structured risk decision."""
    red_flags = payload.red_flags
    contraindications = payload.contraindication_flags
    population_risks = payload.population_risks

    evidence_refs: list[str] = []
    evidence_refs.extend(ref for item in red_flags for ref in item.evidence_refs)
    evidence_refs.extend(ref for item in contraindications for ref in item.evidence_refs)
    evidence_refs.extend(ref for item in population_risks for ref in item.evidence_refs)

    population_risk_score = _aggregate_population_risk(population_risks)

    if any(flag.severity == Severity.CRITICAL for flag in red_flags) or any(
        flag.severity == Severity.CRITICAL for flag in contraindications
    ):
        risk_level = RiskLevel.CRITICAL
    elif any(flag.severity == Severity.HIGH for flag in red_flags + contraindications):
        risk_level = RiskLevel.HIGH
    elif population_risk_score >= 0.3:
        risk_level = RiskLevel.MEDIUM
    elif population_risk_score > 0:
        risk_level = RiskLevel.LOW
    else:
        risk_level = RiskLevel.NONE

    recommend_human_review = bool(contraindications) or population_risk_score >= 0.25
    recommend_offline_visit = risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} or any(
        flag.severity in {Severity.HIGH, Severity.CRITICAL} for flag in contraindications
    )

    safe_to_continue = not recommend_offline_visit and risk_level not in {
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
    }

    recommended_route = _derive_route(
        risk_level,
        recommend_offline_visit=recommend_offline_visit,
        red_flags=red_flags,
    )

    reasons: list[str] = []
    if red_flags:
        reasons.append(f"命中 {len(red_flags)} 个红旗信号")
    if contraindications:
        reasons.append(f"存在 {len(contraindications)} 个禁忌/升级因素")
    if population_risk_score > 0:
        reasons.append(f"特殊人群风险增量为 {population_risk_score:.2f}")
    if not reasons:
        reasons.append("未命中明显高风险信号，可继续受控问诊")

    decision = RiskDecision(
        risk_level=risk_level,
        safe_to_continue=safe_to_continue,
        recommend_offline_visit=recommend_offline_visit,
        recommend_human_review=recommend_human_review,
        recommended_route=recommended_route,
        decision_reason="；".join(reasons),
        evidence_refs=sorted(set(evidence_refs)),
    )

    persisted_result: SaveRiskDecisionOutput = save_risk_decision(
        SaveRiskDecisionInput(
            case_id=payload.case_id,
            risk_decision=decision,
            red_flags=red_flags,
            actor=payload.actor,
            trace_id=payload.trace_id,
        )
    )

    return IssueRiskDecisionOutput(
        decision_id=decision.decision_id,
        risk_level=decision.risk_level,
        safe_to_continue=decision.safe_to_continue,
        recommend_offline_visit=decision.recommend_offline_visit,
        recommend_human_review=decision.recommend_human_review,
        recommended_route=decision.recommended_route,
        decision_reason=decision.decision_reason,
        evidence_refs=decision.evidence_refs,
        persisted=True,
        metadata=_metadata(
            tool_name="issue_risk_decision",
            trace_id=payload.trace_id,
            message="Risk decision issued and persisted.",
        ),
    )


def run_full_safety_check(
    *,
    case_id: str,
    actor: str = "system",
    trace_id: str | None = None,
) -> dict[str, object]:
    """Convenience helper that executes the MVP full safety chain.

    This is useful for routes/services that want a single entry point while the
    internal safety layer is still simple.
    """
    case_state = get_case_state(
        GetCaseStateInput(case_id=case_id, actor=actor, trace_id=trace_id)
    ).case_state

    facts = case_state.normalized_facts
    population_tags = [
        fact.normalized_key
        for fact in facts
        if fact.normalized_key
        in {
            "pregnant",
            "child",
            "elderly",
            "chronic_disease",
            "polypharmacy",
            "immunocompromised",
            "is_pregnant",
        }
        and _fact_value_is_true(fact.normalized_value)
    ]

    red_flag_result = screen_red_flags(
        ScreenRedFlagsInput(
            case_id=case_id,
            facts=facts,
            population_tags=population_tags,
            actor=actor,
            trace_id=trace_id,
        )
    )

    population_result = check_special_population_risks(
        CheckSpecialPopulationRisksInput(
            case_id=case_id,
            population_tags=population_tags,
            facts=facts,
            actor=actor,
            trace_id=trace_id,
        )
    )

    candidate_ids = [
        *(item.candidate_id for item in case_state.candidate_diseases),
        *(item.candidate_id for item in case_state.candidate_patterns),
        *(item.candidate_id for item in case_state.candidate_pathogenesis),
    ]

    contraindication_result = check_contraindications(
        CheckContraindicationsInput(
            case_id=case_id,
            facts=facts,
            population_tags=population_tags,
            candidate_ids=candidate_ids,
            actor=actor,
            trace_id=trace_id,
        )
    )

    decision_result = issue_risk_decision(
        IssueRiskDecisionInput(
            case_id=case_id,
            red_flags=red_flag_result.matched_red_flags,
            contraindication_flags=contraindication_result.contraindication_flags,
            population_risks=population_result.risk_adjustments,
            current_stage=case_state.case_stage.value,
            actor=actor,
            trace_id=trace_id,
        )
    )

    return {
        "case_id": case_id,
        "red_flags": red_flag_result.model_dump(mode="json"),
        "population_risks": population_result.model_dump(mode="json"),
        "contraindications": contraindication_result.model_dump(mode="json"),
        "risk_decision": decision_result.model_dump(mode="json"),
    }


__all__ = [
    "CheckContraindicationsInput",
    "CheckContraindicationsOutput",
    "CheckSpecialPopulationRisksInput",
    "CheckSpecialPopulationRisksOutput",
    "IssueRiskDecisionInput",
    "IssueRiskDecisionOutput",
    "SafetyToolError",
    "ScreenRedFlagsInput",
    "ScreenRedFlagsOutput",
    "ToolMetadata",
    "check_contraindications",
    "check_special_population_risks",
    "issue_risk_decision",
    "run_full_safety_check",
    "screen_red_flags",
]
