"""Factory helpers for building TCMAgent deepagents graphs.

Design: Tools → Skills → Sub-agents
-------------------------------------
Three distinct capability layers sit on top of the LLM:

**Tools** (``tools/`` package)
    Atomic, deterministic Python callables. They handle all structured
    read/write operations - Neo4j queries, case-state mutations, rule-based
    risk checks. Tools contain *no* LLM reasoning.

**Skills** (``skills/`` directory, Agent Skills spec)
    Procedural knowledge files loaded by ``SkillsMiddleware`` via progressive
    disclosure. Each skill lives in its own sub-directory containing a
    ``SKILL.md`` file with YAML front-matter::

        skills/
        └── triage/
            └── red-flags-protocol/
                └── SKILL.md   # ---\\nname: red-flags-protocol\\n...\\n---

    Skills are declared in SubAgent specs via the ``skills`` key.
    ``create_deep_agent`` automatically appends ``SkillsMiddleware`` using the
    **same backend** that was passed to ``create_deep_agent``.  This module
    builds a ``CompositeBackend`` that routes ``/skills/`` to a
    ``FilesystemBackend`` scoped to the project's ``skills/`` directory, while
    leaving all other paths on the default ``StateBackend`` (safe for web APIs).

**Sub-agents** (this factory)
    Role-bounded reasoning principals assembled by this factory.  Each
    sub-agent has a focused system prompt (role identity + high-level rules),
    a curated tool set, and domain-specific skill source paths.

First-stage sub-agents
----------------------
- ``triage-agent``  - visit-route classification, special-population tagging
- ``intake-agent``  - dynamic questioning, answer normalisation, contradiction detection
- ``safety-agent``  - red-flag review, contraindication checking, risk synthesis

Graph-reasoning stays as a *service + tool* layer in this MVP (not a sub-agent)
because its outputs are fully deterministic and structure-driven.

Lazy imports
------------
deepagents and backend dependencies are imported inside factory methods so the
module stays importable in partially-built environments without raising at
module load time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from tcm_agent.config import Settings, get_settings

DEFAULT_SUPERVISOR_NAME = "clinical-supervisor"

DEFAULT_SUPERVISOR_PROMPT = """
你是 TCMAgent 的总控代理 clinical-supervisor。

你的职责不是自己完成全部医学判断，而是：
1. 读取当前病例状态与阶段（使用 get_case_state 工具）
2. 按阶段选择合适的子代理或工具推进流程
3. 永远优先执行安全必问与风险检查（safety-agent 优先于收敛优化）
4. 让问诊按照"安全优先 + 图谱驱动收敛"的原则有序推进
5. 汇总并输出患者可见的阶段性回复

推进顺序原则：
- 阶段 created        -> 调用 triage-agent 做初筛
- 阶段 triaged        -> 调用图谱工具生成初始候选
- 阶段 *_in_progress  -> 调用 intake-agent 执行动态追问
- 随时（有红旗信号）  -> 调用 safety-agent 立即复核
- 阶段 converged      -> 调用 safety-agent 最终复核，再生成总结

核心约束（不可违反）：
- 永远先看风险，再看收敛效率
- 红旗征象或高危特殊人群，必须立即进入 safety-agent
- "下一问"的选择依赖图谱工具（find_discriminative_questions），不自由发挥
- 不把候选证型表达成确定性最终诊断
- 不直接给出处方或高风险治疗建议
- 不确定风险时，建议线下就医或转人工

患者可见回复原则：
- 简洁、清楚、保守
- 不暴露内部调度细节（如子代理名称、候选证型列表）
""".strip()

DEFAULT_TRIAGE_PROMPT = """
你是 TCMAgent 的导诊代理 triage-agent。

你的职责：
1. 根据患者主诉和基本信息，评估是否适合继续线上问诊
2. 快速识别红旗征象（优先使用 run_triage 工具，辅以 screen_red_flags）
3. 标记特殊人群（使用 tag_special_population 工具）
4. 输出推荐就诊路径（使用 classify_visit_route 工具）

工作原则：
- 优先识别急重症信号，宁可多转诊也不遗漏
- 风险不明确时，默认更保守（建议线下或人工）
- 不做深度辨证分析，只做初步评估
- 输出尽量结构化，供 supervisor 和 safety-agent 使用
- 标记特殊人群后，通知 supervisor 升高整体风险权重

完成后应返回：导诊等级、就诊路径、特殊人群标签、是否允许继续线上问诊。

参考技能：red-flags-protocol（红旗筛查）、special-population-rules（特殊人群规则）、
visit-routing-guide（就诊路径决策）。
""".strip()

DEFAULT_INTAKE_PROMPT = """
你是 TCMAgent 的问诊采集代理 intake-agent。

你的职责：
1. 将图谱推荐的"下一问"转化为自然、简洁、患者易懂的话术
2. 解析患者回答，将其归一化为结构化事实（使用 update_case_facts 工具）
3. 检测新事实与已有事实是否存在矛盾
4. 维护问诊节奏，一次只问一个问题，避免患者疲劳
5. 记录每轮问答（使用 record_question_asked 工具）

工作原则：
- 你负责"怎么问"和"怎么整理回答"，不负责决定问诊方向
- 下一问由 supervisor 通过图谱工具确定后传给你
- 不自行决定问诊流程边界（不判断是否应停止问诊）
- 不做最终诊断或高风险建议
- 归一化时保留患者原始表达作为 source_text
- 信息不足或模糊时，标记低置信度，继续追问澄清

参考技能：symptom-normalization-protocol（症状归一化）、question-phrasing-guide（话术指南）、
contradiction-detection-rules（矛盾检测）。
""".strip()

DEFAULT_SAFETY_PROMPT = """
你是 TCMAgent 的安全代理 safety-agent。

你的职责：
1. 复核红旗征象（使用 screen_red_flags 工具）
2. 检查特殊人群风险（使用 check_special_population_risks 工具）
3. 检查禁忌项（使用 check_contraindications 工具）
4. 综合所有风险信号，输出最终风险决策（使用 issue_risk_decision 工具）

工作原则：
- 安全优先于收敛效率，不可妥协
- 任何严重红旗 -> risk_level=critical，safe_to_continue=false
- 高风险特殊人群 + 症状不明 -> risk_level=high，建议转诊
- 不确定风险时，偏保守（宁可误报，不可漏报）
- safe_to_continue=false 时，必须输出明确的 recommend_offline_visit 或 recommend_human_review
- 输出必须足以让 supervisor 做出明确分支决策

参考技能：risk-synthesis-protocol（风险综合逻辑）、contraindication-reference（禁忌参考）。
""".strip()


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AgentFactoryConfig:
    """Configuration for assembling the main deep agent graph."""

    name: str = DEFAULT_SUPERVISOR_NAME
    system_prompt: str = DEFAULT_SUPERVISOR_PROMPT
    model: str | None = None
    memory_paths: list[str] = field(default_factory=list)
    skill_paths: list[str] = field(default_factory=list)
    interrupt_on: dict[str, bool | dict[str, Any]] = field(default_factory=dict)
    debug: bool = False
    #: When True, build a CompositeBackend and wire skill sources into SubAgent specs.
    enable_skills: bool = True

    def resolved_model(self, settings: Settings) -> str:
        """Resolve the active model spec for deepagents."""
        if self.model:
            return self.model
        return f"{settings.model_provider}:{settings.model_name}"


# ---------------------------------------------------------------------------
# Tool grouping
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SubagentTools:
    """Tool grouping for first-stage subagent assembly.

    Attributes
    ----------
    shared:
        Tools available to **all** sub-agents (merged with each role set).
    supervisor:
        Tools available only to the top-level supervisor.
    triage:
        Tools for ``triage-agent`` (merged with ``shared``).
    intake:
        Tools for ``intake-agent`` (merged with ``shared``).
    safety:
        Tools for ``safety-agent`` (merged with ``shared``).
    """

    shared: list[Any] = field(default_factory=list)
    supervisor: list[Any] = field(default_factory=list)
    triage: list[Any] = field(default_factory=list)
    intake: list[Any] = field(default_factory=list)
    safety: list[Any] = field(default_factory=list)


def _merge_tools(*groups: Sequence[Any]) -> list[Any]:
    """Merge tool groups preserving order and removing duplicate objects."""
    merged: list[Any] = []
    seen_ids: set[int] = set()
    for group in groups:
        for tool in group:
            identity = id(tool)
            if identity in seen_ids:
                continue
            seen_ids.add(identity)
            merged.append(tool)
    return merged


# ---------------------------------------------------------------------------
# Default tool sets (resolved lazily from the tools package)
# ---------------------------------------------------------------------------


def _default_supervisor_tools() -> list[Any]:
    """Return the minimal default tool set for the supervisor."""
    try:
        from tcm_agent.tools import (
            create_case,
            find_discriminative_questions,
            generate_patient_summary_template,
            get_case_state,
            issue_risk_decision,
            query_graph_candidates,
            set_case_stage,
        )

        return [
            create_case,
            get_case_state,
            set_case_stage,
            query_graph_candidates,
            find_discriminative_questions,
            issue_risk_decision,
            generate_patient_summary_template,
        ]
    except ImportError:
        return []


def _default_triage_tools() -> list[Any]:
    """Default tools for ``triage-agent``."""
    try:
        from tcm_agent.tools import (
            classify_visit_route,
            run_triage,
            screen_red_flags,
            set_case_stage,
            tag_special_population,
        )

        return [
            run_triage,
            classify_visit_route,
            tag_special_population,
            screen_red_flags,
            set_case_stage,
        ]
    except ImportError:
        return []


def _default_intake_tools() -> list[Any]:
    """Default tools for ``intake-agent``."""
    try:
        from tcm_agent.tools import (
            append_case_evidence,
            explain_question_rationale,
            find_discriminative_questions,
            get_case_state,
            record_question_asked,
            update_case_facts,
        )

        return [
            get_case_state,
            update_case_facts,
            record_question_asked,
            append_case_evidence,
            find_discriminative_questions,
            explain_question_rationale,
        ]
    except ImportError:
        return []


def _default_safety_tools() -> list[Any]:
    """Default tools for ``safety-agent``."""
    try:
        from tcm_agent.tools import (
            check_contraindications,
            check_special_population_risks,
            get_case_state,
            issue_risk_decision,
            run_full_safety_check,
            screen_red_flags,
        )

        return [
            get_case_state,
            screen_red_flags,
            check_special_population_risks,
            check_contraindications,
            run_full_safety_check,
            issue_risk_decision,
        ]
    except ImportError:
        return []


# ---------------------------------------------------------------------------
# Sub-agent spec builder
# ---------------------------------------------------------------------------


def build_default_subagents(
    *,
    model: str | None = None,
    tools: SubagentTools | None = None,
    interrupt_on: Mapping[str, bool | dict[str, Any]] | None = None,
    enable_skills: bool = True,
) -> list[dict[str, Any]]:
    """Build the default first-stage subagent specifications.

    Each returned spec is a ``SubAgent``-compatible dict for ``create_deep_agent``.
    When ``enable_skills=True`` and the skills directory is populated, each spec
    carries a ``skills`` key with the source paths appropriate for that role.
    ``create_deep_agent`` automatically appends ``SkillsMiddleware(backend=backend,
    sources=spec["skills"])`` to the sub-agent's middleware stack - do NOT add
    ``SkillsMiddleware`` manually to the ``middleware`` list.

    The three returned specs are:

    * ``triage-agent``  - visit routing & initial risk flagging
    * ``intake-agent``  - dynamic Q&A and symptom extraction
    * ``safety-agent``  - risk review and contraindication checking

    Parameters
    ----------
    model:
        Optional model override applied to each subagent.
    tools:
        Structured tool groups. When a role-specific group is empty the
        factory resolves the default tool set for that role.
    interrupt_on:
        Optional interrupt configuration inherited by subagents.
    enable_skills:
        When ``True`` (default), attach skill source paths to each subagent
        spec so deepagents wires ``SkillsMiddleware`` automatically.
    """
    grouped_tools = tools or SubagentTools()
    inherited_interrupts = dict(interrupt_on or {})

    # Resolve tool sets
    triage_tools = _merge_tools(
        grouped_tools.shared,
        grouped_tools.triage or _default_triage_tools(),
    )
    intake_tools = _merge_tools(
        grouped_tools.shared,
        grouped_tools.intake or _default_intake_tools(),
    )
    safety_tools = _merge_tools(
        grouped_tools.shared,
        grouped_tools.safety or _default_safety_tools(),
    )

    # Resolve skill source paths (only when skills are available on disk)
    triage_skills: list[str] | None = None
    intake_skills: list[str] | None = None
    safety_skills: list[str] | None = None

    if enable_skills:
        try:
            from tcm_agent.agents.skills_loader import (
                intake_skill_sources,
                safety_skill_sources,
                skills_available,
                triage_skill_sources,
            )

            if skills_available():
                triage_skills = triage_skill_sources()
                intake_skills = intake_skill_sources()
                safety_skills = safety_skill_sources()
        except ImportError:
            pass  # degrade gracefully when skills_loader is not yet available

    # Base fields shared across all subagents
    base: dict[str, Any] = {}
    if model:
        base["model"] = model
    if inherited_interrupts:
        base["interrupt_on"] = inherited_interrupts

    def _with_skills(skills: list[str] | None) -> dict[str, Any]:
        """Return a partial spec fragment that includes skills only if set."""
        return {"skills": skills} if skills else {}

    specs: list[dict[str, Any]] = [
        {
            **base,
            "name": "triage-agent",
            "description": (
                "导诊代理。负责初次评估：识别红旗征象、标记特殊人群、确定就诊路径。"
                "在问诊开始前使用，用于判断是否适合继续线上流程。"
            ),
            "system_prompt": DEFAULT_TRIAGE_PROMPT,
            "tools": triage_tools,
            **_with_skills(triage_skills),
        },
        {
            **base,
            "name": "intake-agent",
            "description": (
                "问诊采集代理。负责将图谱推荐问题转成自然话术、解析患者回答并归一化为"
                "结构化事实、检测矛盾。不决定问诊方向，只负责执行追问。"
            ),
            "system_prompt": DEFAULT_INTAKE_PROMPT,
            "tools": intake_tools,
            **_with_skills(intake_skills),
        },
        {
            **base,
            "name": "safety-agent",
            "description": (
                "安全代理。负责红旗复核、特殊人群风险检查、禁忌检查与风险决策综合。"
                "在关键节点（初筛后、问诊收敛前、总结前）强制执行安全兜底。"
            ),
            "system_prompt": DEFAULT_SAFETY_PROMPT,
            "tools": safety_tools,
            **_with_skills(safety_skills),
        },
    ]

    return specs


# ---------------------------------------------------------------------------
# AgentFactory
# ---------------------------------------------------------------------------


class AgentFactory:
    """Project-level factory for creating TCMAgent orchestration graphs."""

    def __init__(
        self,
        settings: Settings | None = None,
        config: AgentFactoryConfig | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = config or AgentFactoryConfig()

    @property
    def model_spec(self) -> str:
        """Return the deepagents-compatible model spec."""
        return self.config.resolved_model(self.settings)

    def build_subagents(
        self,
        *,
        tools: SubagentTools | None = None,
        interrupt_on: Mapping[str, bool | dict[str, Any]] | None = None,
        enable_skills: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Build the default first-stage subagent set."""
        merged_interrupts = dict(self.config.interrupt_on)
        if interrupt_on:
            merged_interrupts.update(interrupt_on)

        use_skills = self.config.enable_skills if enable_skills is None else enable_skills

        return build_default_subagents(
            model=self.model_spec,
            tools=tools,
            interrupt_on=merged_interrupts,
            enable_skills=use_skills,
        )

    def create_supervisor(
        self,
        *,
        tools: Sequence[Any] | None = None,
        subagents: Sequence[dict[str, Any]] | None = None,
        memory_paths: Sequence[str] | None = None,
        skill_paths: Sequence[str] | None = None,
        interrupt_on: Mapping[str, bool | dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        name: str | None = None,
        debug: bool | None = None,
        checkpointer: Any | None = None,
        store: Any | None = None,
        backend: Any | None = None,
        middleware: Sequence[Any] | None = None,
        response_format: Any | None = None,
        context_schema: Any | None = None,
        cache: Any | None = None,
    ) -> Any:
        """Create the main deepagents supervisor graph.

        Most parameters are passed through to ``deepagents.create_deep_agent``.
        The caller can supply fully custom tools and subagents, or rely on the
        factory's first-stage defaults.

        Notes
        -----
        Sub-agent skills are declared via the ``skills`` key inside each
        sub-agent spec (built by ``build_subagents``).  ``create_deep_agent``
        automatically appends ``SkillsMiddleware(backend=backend,
        sources=spec["skills"])`` to the sub-agent's middleware stack.
        Do **not** add ``SkillsMiddleware`` manually; that would create
        duplicates.

        The ``backend`` should be the ``CompositeBackend`` returned by
        ``skills_loader.build_composite_backend()`` so that the
        ``/skills/`` prefix is routed to the read-scoped ``FilesystemBackend``
        while all other paths remain on the default ``StateBackend``.
        """
        try:
            from deepagents import create_deep_agent
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "deepagents is not available. Install project dependencies before "
                "creating the TCMAgent graph."
            ) from exc

        effective_interrupts = dict(self.config.interrupt_on)
        if interrupt_on:
            effective_interrupts.update(interrupt_on)

        agent_subagents = list(subagents) if subagents is not None else self.build_subagents()
        relaxed_subagents = cast(Any, agent_subagents)
        relaxed_interrupts = cast(Any, effective_interrupts or None)

        # Resolve supervisor-level tool set
        resolved_tools = list(tools) if tools is not None else _default_supervisor_tools()

        # Supervisor-level skill sources (currently unused in MVP; reserved for future)
        supervisor_skills = list(skill_paths or self.config.skill_paths) or None

        return create_deep_agent(
            model=self.model_spec,
            tools=resolved_tools,
            system_prompt=system_prompt or self.config.system_prompt,
            middleware=list(middleware or []),
            subagents=relaxed_subagents,
            skills=supervisor_skills,
            memory=list(memory_paths or self.config.memory_paths) or None,
            response_format=response_format,
            context_schema=context_schema,
            checkpointer=checkpointer,
            store=store,
            backend=backend,
            interrupt_on=relaxed_interrupts,
            debug=self.config.debug if debug is None else debug,
            name=name or self.config.name,
            cache=cache,
        )

    def create_default_consultation_graph(
        self,
        *,
        supervisor_tools: Sequence[Any] | None = None,
        subagent_tools: SubagentTools | None = None,
        memory_paths: Sequence[str] | None = None,
        skill_paths: Sequence[str] | None = None,
        interrupt_on: Mapping[str, bool | dict[str, Any]] | None = None,
        checkpointer: Any | None = None,
        store: Any | None = None,
        backend: Any | None = None,
        middleware: Sequence[Any] | None = None,
        enable_skills: bool | None = None,
    ) -> Any:
        """Create the first-stage default consultation graph.

        This is the recommended entry point for the MVP.  It wires:

        * A ``clinical-supervisor`` with default tool set
        * Three sub-agents (triage / intake / safety) each with role-specific
          tools and, when available, domain skill source paths
        * A ``CompositeBackend`` that routes ``/skills/`` to a read-scoped
          ``FilesystemBackend`` (if the skills directory exists on disk)

        Parameters
        ----------
        supervisor_tools:
            Override the supervisor's tool list.  ``None`` uses defaults from
            ``_default_supervisor_tools()``.
        subagent_tools:
            Grouped tool overrides for individual sub-agents.
        memory_paths:
            Optional AGENTS.md memory file paths for the supervisor.
        skill_paths:
            Optional supervisor-level skill source paths.
        interrupt_on:
            Human-in-the-loop interrupt configuration.
        checkpointer:
            Optional LangGraph checkpointer for persistence.
        store:
            Optional LangGraph store.
        backend:
            Explicit backend override.  When ``None`` and ``enable_skills`` is
            ``True``, the factory builds a ``CompositeBackend`` automatically.
        middleware:
            Additional supervisor-level middleware.
        enable_skills:
            Override ``config.enable_skills``.  ``None`` inherits from config.
        """
        use_skills = self.config.enable_skills if enable_skills is None else enable_skills

        # Build the CompositeBackend when skills are enabled and no backend was supplied.
        # The CompositeBackend routes /skills/ to a read-scoped FilesystemBackend
        # so that SkillsMiddleware (wired automatically by create_deep_agent via the
        # SubAgent "skills" key) can load SKILL.md files from disk.
        resolved_backend = backend
        if resolved_backend is None and use_skills:
            try:
                from tcm_agent.agents.skills_loader import build_composite_backend

                resolved_backend = build_composite_backend()
            except ImportError:
                pass

        subagents = self.build_subagents(
            tools=subagent_tools,
            interrupt_on=interrupt_on,
            enable_skills=use_skills,
        )

        return self.create_supervisor(
            tools=supervisor_tools,
            subagents=subagents,
            memory_paths=memory_paths,
            skill_paths=skill_paths,
            interrupt_on=interrupt_on,
            checkpointer=checkpointer,
            store=store,
            backend=resolved_backend,
            middleware=middleware,
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def create_default_agent_factory(
    settings: Settings | None = None,
    config: AgentFactoryConfig | None = None,
) -> AgentFactory:
    """Convenience helper for app bootstrap code."""
    return AgentFactory(settings=settings, config=config)


def create_supervisor_agent(
    *,
    settings: Settings | None = None,
    config: AgentFactoryConfig | None = None,
    supervisor_tools: Sequence[Any] | None = None,
    subagent_tools: SubagentTools | None = None,
    memory_paths: Sequence[str] | None = None,
    skill_paths: Sequence[str] | None = None,
    interrupt_on: Mapping[str, bool | dict[str, Any]] | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
    backend: Any | None = None,
    middleware: Sequence[Any] | None = None,
    enable_skills: bool = True,
) -> Any:
    """Convenience helper that returns the default first-stage supervisor graph."""
    factory = create_default_agent_factory(settings=settings, config=config)
    return factory.create_default_consultation_graph(
        supervisor_tools=supervisor_tools,
        subagent_tools=subagent_tools,
        memory_paths=memory_paths,
        skill_paths=skill_paths,
        interrupt_on=interrupt_on,
        checkpointer=checkpointer,
        store=store,
        backend=backend,
        middleware=middleware,
        enable_skills=enable_skills,
    )


__all__ = [
    "DEFAULT_INTAKE_PROMPT",
    "DEFAULT_SAFETY_PROMPT",
    "DEFAULT_SUPERVISOR_NAME",
    "DEFAULT_SUPERVISOR_PROMPT",
    "DEFAULT_TRIAGE_PROMPT",
    "AgentFactory",
    "AgentFactoryConfig",
    "SubagentTools",
    "build_default_subagents",
    "create_default_agent_factory",
    "create_supervisor_agent",
]
