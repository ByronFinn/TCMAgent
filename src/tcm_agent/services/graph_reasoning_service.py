"""Graph reasoning service for MVP candidate convergence.

This module implements the first practical version of TCMAgent's graph-driven
reasoning layer. The long-term design calls for Neo4j-backed medical reasoning,
but the system still needs a usable convergence engine before the full graph
repository/query stack is complete.

This service therefore provides a hybrid approach:

1. It accepts structured case facts from `CaseState`
2. It applies lightweight heuristic mappings to generate candidate:
   - diseases
   - patterns
   - pathogenesis
3. It computes a convergence score
4. It selects the next most useful question
5. It can project results back into the shared case state

Design goals
------------
- Work immediately with the current project scaffold
- Be deterministic and testable
- Return structured outputs
- Remain easy to replace with real Neo4j-backed logic later

This module should be treated as the MVP reasoning engine, not the final
clinical engine.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from tcm_agent.schemas.case import (
    CandidateItem,
    CandidateType,
    CaseStage,
    CaseState,
    FactType,
    NormalizedFact,
    QuestionRecommendation,
    QuestionType,
)
from tcm_agent.tools.case_tools import update_case_candidates


def _clip(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp a float to a bounded range."""
    return max(minimum, min(value, maximum))


def _fact_value_is_true(value: object) -> bool:
    """Interpret a normalized fact value as positive/true-ish."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "present", "positive", "有", "是"}
    if isinstance(value, list):
        return len(value) > 0
    return False


class CandidateAssessment(BaseModel):
    """Structured candidate assessment result."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_type: CandidateType
    name: str
    score: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    notes: str | None = None

    def to_candidate_item(self) -> CandidateItem:
        """Convert to shared schema type."""
        evidence_refs = [*self.supporting_evidence, *self.conflicting_evidence]
        return CandidateItem(
            candidate_id=self.candidate_id,
            candidate_type=self.candidate_type,
            name=self.name,
            score=self.score,
            confidence=self.confidence,
            evidence_refs=evidence_refs,
            notes=self.notes,
        )


class QuestionSelectionResult(BaseModel):
    """Recommended next-step question output."""

    model_config = ConfigDict(extra="forbid")

    recommended_questions: list[QuestionRecommendation] = Field(default_factory=list)
    selection_reason: str
    question_strategy: str


class ReasoningSummary(BaseModel):
    """Top-level reasoning output used by services, APIs, and tools."""

    model_config = ConfigDict(extra="forbid")

    candidate_diseases: list[CandidateAssessment] = Field(default_factory=list)
    candidate_patterns: list[CandidateAssessment] = Field(default_factory=list)
    candidate_pathogenesis: list[CandidateAssessment] = Field(default_factory=list)
    matched_facts: list[str] = Field(default_factory=list)
    missing_high_value_facts: list[str] = Field(default_factory=list)
    convergence_score: float = Field(ge=0.0, le=1.0)
    recommended_question: QuestionRecommendation | None = None
    question_rationale: str | None = None

    def top_candidate_gap(self) -> float:
        """Return the score gap between top-1 and top-2 pattern candidates."""
        if len(self.candidate_patterns) < 2:
            if self.candidate_patterns:
                return self.candidate_patterns[0].score
            return 0.0
        return max(0.0, self.candidate_patterns[0].score - self.candidate_patterns[1].score)


class CandidateQueryInput(BaseModel):
    """Input for candidate generation."""

    model_config = ConfigDict(extra="forbid")

    case_state: CaseState


class QuestionQueryInput(BaseModel):
    """Input for next-question recommendation."""

    model_config = ConfigDict(extra="forbid")

    case_state: CaseState
    reasoning_summary: ReasoningSummary | None = None
    max_questions: int = Field(default=1, ge=1, le=5)


@dataclass(slots=True, frozen=True)
class PatternRule:
    """Heuristic mapping from fact keys to pattern support."""

    candidate_id: str
    name: str
    triggers: tuple[str, ...]
    dampeners: tuple[str, ...] = ()
    pathogenesis_ids: tuple[str, ...] = ()
    base_score: float = 0.2


@dataclass(slots=True, frozen=True)
class DiseaseRule:
    """Heuristic mapping from fact keys to disease support."""

    candidate_id: str
    name: str
    triggers: tuple[str, ...]
    dampeners: tuple[str, ...] = ()
    base_score: float = 0.2


@dataclass(slots=True, frozen=True)
class PathogenesisRule:
    """Heuristic mapping from fact keys to pathogenesis support."""

    candidate_id: str
    name: str
    triggers: tuple[str, ...]
    dampeners: tuple[str, ...] = ()
    base_score: float = 0.2


class GraphReasoningService:
    """MVP graph reasoning service.

    Notes
    -----
    - Current implementation is heuristic and deterministic.
    - The public interface is designed to survive a later switch to Neo4j-backed
      reasoning and question selection.
    """

    _pattern_rules: tuple[PatternRule, ...] = (
        PatternRule(
            candidate_id="pattern:wind-cold",
            name="风寒束表",
            triggers=("aversion_to_cold", "no_sweat", "clear_nasal_discharge", "body_aches"),
            dampeners=("thirst", "yellow_phlegm", "sore_throat"),
            pathogenesis_ids=("pathogenesis:wind-cold-exterior",),
        ),
        PatternRule(
            candidate_id="pattern:wind-heat",
            name="风热犯表",
            triggers=("fever", "sore_throat", "thirst", "yellow_phlegm"),
            dampeners=("aversion_to_cold", "clear_nasal_discharge"),
            pathogenesis_ids=("pathogenesis:wind-heat-exterior",),
        ),
        PatternRule(
            candidate_id="pattern:liver-qi-stagnation",
            name="肝郁气滞",
            triggers=("stress", "irritability", "distention_pain", "mood_swings"),
            dampeners=("severe_fatigue", "loose_stool"),
            pathogenesis_ids=("pathogenesis:qi-stagnation",),
        ),
        PatternRule(
            candidate_id="pattern:spleen-deficiency",
            name="脾气虚",
            triggers=("fatigue", "poor_appetite", "loose_stool", "abdominal_distention"),
            dampeners=("thirst", "irritability"),
            pathogenesis_ids=("pathogenesis:spleen-deficiency",),
        ),
        PatternRule(
            candidate_id="pattern:phlegm-dampness",
            name="痰湿内阻",
            triggers=("chest_oppression", "nausea", "heaviness", "greasy_tongue_coating"),
            dampeners=("dry_mouth",),
            pathogenesis_ids=("pathogenesis:phlegm-dampness",),
        ),
    )

    _disease_rules: tuple[DiseaseRule, ...] = (
        DiseaseRule(
            candidate_id="disease:common-cold",
            name="感冒",
            triggers=("fever", "aversion_to_cold", "runny_nose", "cough"),
            dampeners=("chronic_course",),
        ),
        DiseaseRule(
            candidate_id="disease:pharyngitis",
            name="咽痛相关问题",
            triggers=("sore_throat", "fever", "thirst"),
            dampeners=("abdominal_pain",),
        ),
        DiseaseRule(
            candidate_id="disease:insomnia",
            name="失眠",
            triggers=("insomnia", "difficulty_falling_asleep", "dream_disturbed_sleep"),
            dampeners=("acute_fever",),
        ),
        DiseaseRule(
            candidate_id="disease:functional-dyspepsia",
            name="胃脘不适",
            triggers=("abdominal_distention", "poor_appetite", "nausea"),
            dampeners=("sore_throat",),
        ),
        DiseaseRule(
            candidate_id="disease:headache",
            name="头痛",
            triggers=("headache", "dizziness", "temporal_pain"),
            dampeners=("poor_appetite",),
        ),
    )

    _pathogenesis_rules: tuple[PathogenesisRule, ...] = (
        PathogenesisRule(
            candidate_id="pathogenesis:wind-cold-exterior",
            name="外感风寒",
            triggers=("aversion_to_cold", "no_sweat", "runny_nose"),
            dampeners=("thirst", "sore_throat"),
        ),
        PathogenesisRule(
            candidate_id="pathogenesis:wind-heat-exterior",
            name="外感风热",
            triggers=("fever", "sore_throat", "thirst"),
            dampeners=("clear_nasal_discharge",),
        ),
        PathogenesisRule(
            candidate_id="pathogenesis:qi-stagnation",
            name="气滞",
            triggers=("stress", "distention_pain", "irritability"),
        ),
        PathogenesisRule(
            candidate_id="pathogenesis:spleen-deficiency",
            name="脾失健运",
            triggers=("fatigue", "poor_appetite", "loose_stool"),
        ),
        PathogenesisRule(
            candidate_id="pathogenesis:phlegm-dampness",
            name="痰湿阻滞",
            triggers=("nausea", "heaviness", "greasy_tongue_coating", "chest_oppression"),
        ),
    )

    _question_bank: tuple[QuestionRecommendation, ...] = (
        QuestionRecommendation(
            question_id="question:aversion-cold-or-heat",
            question_text="你现在更偏怕冷，还是更偏怕热？",
            question_type=QuestionType.SINGLE_CHOICE,
            goal="区分风寒与风热相关候选",
            discriminates_between=["pattern:wind-cold", "pattern:wind-heat"],
            target_domain="cold_heat",
            priority=0.88,
            safety_related=False,
            fatigue_cost=0.2,
            rationale="当前候选集中在表证分支，需要先区分寒热倾向。",
            expected_answers=["更怕冷", "更怕热", "都没有明显感觉"],
        ),
        QuestionRecommendation(
            question_id="question:thirst-preference",
            question_text="最近口渴明显吗？更想喝热水还是冷水？",
            question_type=QuestionType.SINGLE_CHOICE,
            goal="补充津液与寒热方向证据",
            discriminates_between=[
                "pattern:wind-cold",
                "pattern:wind-heat",
                "pattern:phlegm-dampness",
            ],
            target_domain="thirst",
            priority=0.82,
            safety_related=False,
            fatigue_cost=0.25,
            rationale="口渴与饮水偏好对寒热和痰湿方向都有区分价值。",
            expected_answers=["不太口渴", "口渴偏喜热饮", "口渴偏喜冷饮"],
        ),
        QuestionRecommendation(
            question_id="question:sweat-status",
            question_text="你现在有明显出汗吗？是无汗、少汗，还是容易出汗？",
            question_type=QuestionType.SINGLE_CHOICE,
            goal="补充表证与营卫状态证据",
            discriminates_between=["pattern:wind-cold", "pattern:wind-heat"],
            target_domain="sweating",
            priority=0.78,
            safety_related=False,
            fatigue_cost=0.2,
            rationale="汗出情况是外感类候选的重要分支证据。",
            expected_answers=["无汗", "少量出汗", "容易出汗"],
        ),
        QuestionRecommendation(
            question_id="question:stool-status",
            question_text="最近大便偏稀、偏干，还是基本正常？",
            question_type=QuestionType.SINGLE_CHOICE,
            goal="区分脾虚、津亏与一般候选",
            discriminates_between=["pattern:spleen-deficiency", "pattern:wind-heat"],
            target_domain="stool",
            priority=0.72,
            safety_related=False,
            fatigue_cost=0.2,
            rationale="二便信息对脾虚与热象鉴别很关键。",
            expected_answers=["偏稀", "偏干", "基本正常"],
        ),
        QuestionRecommendation(
            question_id="question:appetite-status",
            question_text="最近食欲怎么样？有明显胃口差或者吃一点就胀吗？",
            question_type=QuestionType.SINGLE_CHOICE,
            goal="补充脾胃功能与痰湿方向证据",
            discriminates_between=["pattern:spleen-deficiency", "pattern:phlegm-dampness"],
            target_domain="appetite",
            priority=0.7,
            safety_related=False,
            fatigue_cost=0.25,
            rationale="食欲和纳差有助于判断脾胃与痰湿方向。",
            expected_answers=["食欲差", "食欲一般", "食欲正常"],
        ),
        QuestionRecommendation(
            question_id="question:sleep-status",
            question_text="最近睡眠怎么样？是难入睡、易醒，还是睡后不解乏？",
            question_type=QuestionType.SINGLE_CHOICE,
            goal="补充失眠与情志方向证据",
            discriminates_between=["disease:insomnia", "pattern:liver-qi-stagnation"],
            target_domain="sleep",
            priority=0.68,
            safety_related=False,
            fatigue_cost=0.25,
            rationale="睡眠问题能帮助判断是否存在明显情志相关路径。",
            expected_answers=["难入睡", "容易醒", "睡了也不解乏", "问题不明显"],
        ),
        QuestionRecommendation(
            question_id="question:stress-irritability",
            question_text="最近压力、烦躁、生气后加重这种情况明显吗？",
            question_type=QuestionType.BOOLEAN,
            goal="评估情志与气机郁滞方向",
            discriminates_between=["pattern:liver-qi-stagnation", "pattern:spleen-deficiency"],
            target_domain="emotion",
            priority=0.66,
            safety_related=False,
            fatigue_cost=0.2,
            rationale="情志触发是肝郁气滞方向的重要线索。",
            expected_answers=["明显", "不明显"],
        ),
        QuestionRecommendation(
            question_id="question:red-flag-chest-breathing",
            question_text="有没有胸痛、呼吸困难、胸闷明显加重的情况？",
            question_type=QuestionType.BOOLEAN,
            goal="红旗复核",
            discriminates_between=[],
            target_domain="red_flag",
            priority=0.99,
            safety_related=True,
            fatigue_cost=0.1,
            rationale="这是安全必问问题，需要先排除高风险路径。",
            expected_answers=["有", "没有"],
        ),
    )

    def generate_candidates(self, case_state: CaseState) -> ReasoningSummary:
        """Generate heuristic candidate sets from the current case state."""
        facts = [
            fact
            for fact in case_state.normalized_facts
            if _fact_value_is_true(fact.normalized_value)
        ]
        fact_keys = {fact.normalized_key for fact in facts}
        matched_facts = sorted(fact_keys)

        disease_candidates = self._score_diseases(fact_keys)
        pattern_candidates = self._score_patterns(fact_keys)
        pathogenesis_candidates = self._score_pathogenesis(fact_keys)

        missing_high_value_facts = self._infer_missing_high_value_facts(
            fact_keys=fact_keys,
            pattern_candidates=pattern_candidates,
            disease_candidates=disease_candidates,
        )

        convergence_score = self._compute_convergence_score(
            pattern_candidates=pattern_candidates,
            disease_candidates=disease_candidates,
            fact_keys=fact_keys,
        )

        question_result = self.recommend_questions(
            QuestionQueryInput(
                case_state=case_state,
                max_questions=1,
                reasoning_summary=ReasoningSummary(
                    candidate_diseases=disease_candidates,
                    candidate_patterns=pattern_candidates,
                    candidate_pathogenesis=pathogenesis_candidates,
                    matched_facts=matched_facts,
                    missing_high_value_facts=missing_high_value_facts,
                    convergence_score=convergence_score,
                ),
            )
        )

        recommended_question = (
            question_result.recommended_questions[0]
            if question_result.recommended_questions
            else None
        )

        return ReasoningSummary(
            candidate_diseases=disease_candidates,
            candidate_patterns=pattern_candidates,
            candidate_pathogenesis=pathogenesis_candidates,
            matched_facts=matched_facts,
            missing_high_value_facts=missing_high_value_facts,
            convergence_score=convergence_score,
            recommended_question=recommended_question,
            question_rationale=recommended_question.rationale if recommended_question else None,
        )

    def recommend_questions(self, query: QuestionQueryInput) -> QuestionSelectionResult:
        """Recommend the next most useful question(s) for convergence."""
        case_state = query.case_state
        asked = set(case_state.asked_questions)

        summary = query.reasoning_summary or self.generate_candidates(case_state)
        candidate_ids = {candidate.candidate_id for candidate in summary.candidate_patterns}
        disease_ids = {candidate.candidate_id for candidate in summary.candidate_diseases}

        question_scores: list[tuple[float, QuestionRecommendation]] = []
        fact_keys = {fact.normalized_key for fact in case_state.normalized_facts}

        for question in self._question_bank:
            if question.question_id in asked:
                continue

            score = question.priority

            if question.safety_related:
                # Safety questions should surface early until explicitly answered.
                if not self._has_any_red_flag_screening_fact(fact_keys):
                    score += 0.25
            else:
                overlap = set(question.discriminates_between) & (candidate_ids | disease_ids)
                score += 0.08 * len(overlap)

                if question.target_domain and question.target_domain in fact_keys:
                    score -= 0.15

                # Promote questions tied to still-missing high-value facts.
                missing_match = any(
                    keyword in question.question_text or keyword in (question.goal or "")
                    for keyword in summary.missing_high_value_facts
                )
                if missing_match:
                    score += 0.1

            score -= question.fatigue_cost * 0.2
            question_scores.append((score, question))

        question_scores.sort(key=lambda item: item[0], reverse=True)
        selected = [question for _, question in question_scores[: query.max_questions]]

        strategy = (
            "safety-first"
            if selected and selected[0].safety_related
            else "candidate-disambiguation"
        )

        if selected:
            reason = (
                "Selected question(s) based on current candidate overlap, "
                "missing high-value facts, and safety priority."
            )
        else:
            reason = "No additional high-value questions were identified for the current state."

        return QuestionSelectionResult(
            recommended_questions=selected,
            selection_reason=reason,
            question_strategy=strategy,
        )

    def project_to_case_state(self, case_state: CaseState) -> CaseState:
        """Return a new case state with candidate and question fields updated."""
        summary = self.generate_candidates(case_state)
        updated = case_state.model_copy(deep=True)

        updated.candidate_diseases = [
            candidate.to_candidate_item() for candidate in summary.candidate_diseases
        ]
        updated.candidate_patterns = [
            candidate.to_candidate_item() for candidate in summary.candidate_patterns
        ]
        updated.candidate_pathogenesis = [
            candidate.to_candidate_item() for candidate in summary.candidate_pathogenesis
        ]
        updated.convergence_score = summary.convergence_score
        updated.recommended_next_question = summary.recommended_question
        updated.question_rationale = summary.question_rationale

        if updated.case_stage in {
            CaseStage.CREATED,
            CaseStage.TRIAGED,
        } and (updated.candidate_diseases or updated.candidate_patterns):
            updated.case_stage = CaseStage.INITIAL_CANDIDATES_GENERATED

        if summary.convergence_score >= 0.75 and updated.case_stage == CaseStage.INTAKE_IN_PROGRESS:
            updated.case_stage = CaseStage.INTAKE_CONVERGED

        return updated

    def update_case_state(self, case_state: CaseState, actor: str = "graph-reasoner") -> CaseState:
        """Persist candidate convergence results back into the shared case state."""
        summary = self.generate_candidates(case_state)
        response = update_case_candidates(
            case_id=case_state.case_id,
            candidate_diseases=[
                candidate.to_candidate_item() for candidate in summary.candidate_diseases
            ],
            candidate_patterns=[
                candidate.to_candidate_item() for candidate in summary.candidate_patterns
            ],
            candidate_pathogenesis=[
                candidate.to_candidate_item() for candidate in summary.candidate_pathogenesis
            ],
            recommended_next_question=summary.recommended_question,
            question_rationale=summary.question_rationale,
            convergence_score=summary.convergence_score,
            actor=actor,
        )
        return response.case_state

    def _score_patterns(self, fact_keys: set[str]) -> list[CandidateAssessment]:
        assessments: list[CandidateAssessment] = []
        for rule in self._pattern_rules:
            supporting = [key for key in rule.triggers if key in fact_keys]
            conflicting = [key for key in rule.dampeners if key in fact_keys]
            if not supporting and not conflicting:
                continue

            raw_score = rule.base_score + len(supporting) * 0.18 - len(conflicting) * 0.08
            score = _clip(raw_score, 0.0, 1.0)
            confidence = _clip(0.35 + len(supporting) * 0.12 - len(conflicting) * 0.05, 0.0, 1.0)

            assessments.append(
                CandidateAssessment(
                    candidate_id=rule.candidate_id,
                    candidate_type=CandidateType.PATTERN,
                    name=rule.name,
                    score=score,
                    confidence=confidence,
                    supporting_evidence=[f"fact:{item}" for item in supporting],
                    conflicting_evidence=[f"fact:{item}" for item in conflicting],
                    notes="Heuristic MVP pattern candidate.",
                )
            )

        assessments.sort(key=lambda item: item.score, reverse=True)
        return assessments[:5]

    def _score_diseases(self, fact_keys: set[str]) -> list[CandidateAssessment]:
        assessments: list[CandidateAssessment] = []
        for rule in self._disease_rules:
            supporting = [key for key in rule.triggers if key in fact_keys]
            conflicting = [key for key in rule.dampeners if key in fact_keys]
            if not supporting and not conflicting:
                continue

            raw_score = rule.base_score + len(supporting) * 0.16 - len(conflicting) * 0.08
            score = _clip(raw_score, 0.0, 1.0)
            confidence = _clip(0.3 + len(supporting) * 0.11 - len(conflicting) * 0.05, 0.0, 1.0)

            assessments.append(
                CandidateAssessment(
                    candidate_id=rule.candidate_id,
                    candidate_type=CandidateType.DISEASE,
                    name=rule.name,
                    score=score,
                    confidence=confidence,
                    supporting_evidence=[f"fact:{item}" for item in supporting],
                    conflicting_evidence=[f"fact:{item}" for item in conflicting],
                    notes="Heuristic MVP disease candidate.",
                )
            )

        assessments.sort(key=lambda item: item.score, reverse=True)
        return assessments[:5]

    def _score_pathogenesis(self, fact_keys: set[str]) -> list[CandidateAssessment]:
        assessments: list[CandidateAssessment] = []
        for rule in self._pathogenesis_rules:
            supporting = [key for key in rule.triggers if key in fact_keys]
            conflicting = [key for key in rule.dampeners if key in fact_keys]
            if not supporting and not conflicting:
                continue

            raw_score = rule.base_score + len(supporting) * 0.17 - len(conflicting) * 0.07
            score = _clip(raw_score, 0.0, 1.0)
            confidence = _clip(0.3 + len(supporting) * 0.1 - len(conflicting) * 0.04, 0.0, 1.0)

            assessments.append(
                CandidateAssessment(
                    candidate_id=rule.candidate_id,
                    candidate_type=CandidateType.PATHOGENESIS,
                    name=rule.name,
                    score=score,
                    confidence=confidence,
                    supporting_evidence=[f"fact:{item}" for item in supporting],
                    conflicting_evidence=[f"fact:{item}" for item in conflicting],
                    notes="Heuristic MVP pathogenesis candidate.",
                )
            )

        assessments.sort(key=lambda item: item.score, reverse=True)
        return assessments[:5]

    def _compute_convergence_score(
        self,
        *,
        pattern_candidates: list[CandidateAssessment],
        disease_candidates: list[CandidateAssessment],
        fact_keys: set[str],
    ) -> float:
        """Compute a simple convergence score from candidate sharpness and fact richness."""
        pattern_component = self._candidate_concentration_score(pattern_candidates)
        disease_component = self._candidate_concentration_score(disease_candidates)
        fact_component = _clip(len(fact_keys) / 10.0, 0.0, 1.0)

        return _clip(pattern_component * 0.5 + disease_component * 0.2 + fact_component * 0.3)

    def _candidate_concentration_score(self, candidates: list[CandidateAssessment]) -> float:
        """Estimate how concentrated a candidate ranking currently is."""
        if not candidates:
            return 0.0
        if len(candidates) == 1:
            return _clip(candidates[0].score)

        top = candidates[0].score
        second = candidates[1].score
        gap = max(0.0, top - second)

        # Blend top score and top-2 gap to represent convergence.
        return _clip(top * 0.6 + gap * 0.8)

    def _infer_missing_high_value_facts(
        self,
        *,
        fact_keys: set[str],
        pattern_candidates: list[CandidateAssessment],
        disease_candidates: list[CandidateAssessment],
    ) -> list[str]:
        """Infer which fact domains would most likely improve convergence."""
        priorities: list[str] = []

        top_pattern_ids = {candidate.candidate_id for candidate in pattern_candidates[:2]}
        top_disease_ids = {candidate.candidate_id for candidate in disease_candidates[:2]}

        if {"pattern:wind-cold", "pattern:wind-heat"} & top_pattern_ids:
            if "aversion_to_cold" not in fact_keys and "fever" not in fact_keys:
                priorities.append("寒热")
            if "thirst" not in fact_keys:
                priorities.append("口渴")
            if "sweating" not in fact_keys and "no_sweat" not in fact_keys:
                priorities.append("汗出")

        if {"pattern:spleen-deficiency", "pattern:phlegm-dampness"} & top_pattern_ids:
            if "poor_appetite" not in fact_keys:
                priorities.append("食欲")
            if "loose_stool" not in fact_keys and "dry_stool" not in fact_keys:
                priorities.append("大便")

        if "disease:insomnia" in top_disease_ids and "insomnia" not in fact_keys:
            priorities.append("睡眠")

        if "pattern:liver-qi-stagnation" in top_pattern_ids and "stress" not in fact_keys:
            priorities.append("情志")

        if not self._has_any_red_flag_screening_fact(fact_keys):
            priorities.insert(0, "红旗筛查")

        # Deduplicate while preserving order.
        result: list[str] = []
        seen: set[str] = set()
        for item in priorities:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)

        return result[:5]

    def _has_any_red_flag_screening_fact(self, fact_keys: set[str]) -> bool:
        """Return whether core red-flag screening has already happened."""
        red_flag_markers = {
            "chest_pain",
            "shortness_of_breath",
            "breathing_difficulty",
            "altered_consciousness",
            "persistent_high_fever",
            "bleeding",
        }
        return bool(red_flag_markers & fact_keys)


def normalized_facts_from_case(
    case_state: CaseState, *, positive_only: bool = False
) -> list[NormalizedFact]:
    """Extract normalized facts from a case state."""
    if not positive_only:
        return list(case_state.normalized_facts)
    return [
        fact
        for fact in case_state.normalized_facts
        if fact.fact_type != FactType.OTHER and _fact_value_is_true(fact.normalized_value)
    ]


def summarize_fact_domains(case_state: CaseState) -> dict[str, int]:
    """Return a count of facts by fact type for debugging and UI support."""
    counts: dict[str, int] = defaultdict(int)
    for fact in case_state.normalized_facts:
        counts[fact.fact_type.value] += 1
    return dict(sorted(counts.items()))


DEFAULT_GRAPH_REASONING_SERVICE = GraphReasoningService()


def get_graph_reasoning_service() -> GraphReasoningService:
    """Return the default shared graph reasoning service."""
    return DEFAULT_GRAPH_REASONING_SERVICE


__all__ = [
    "DEFAULT_GRAPH_REASONING_SERVICE",
    "CandidateAssessment",
    "CandidateQueryInput",
    "GraphReasoningService",
    "QuestionQueryInput",
    "QuestionSelectionResult",
    "ReasoningSummary",
    "get_graph_reasoning_service",
    "normalized_facts_from_case",
    "summarize_fact_domains",
]
