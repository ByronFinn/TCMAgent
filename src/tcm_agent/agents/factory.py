"""Factory helpers for building TCMAgent deepagents graphs.

This module centralizes how the project assembles its main supervisor agent and
its first-stage subagents. The goal is to keep orchestration code in one place
so later application layers can ask for a configured agent graph without needing
to know the details of prompt wiring, model resolution, interrupt configuration,
or subagent registration.

The first MVP intentionally keeps the factory conservative:

- one top-level `clinical-supervisor`
- three first-stage subagents:
  - `triage-agent`
  - `intake-agent`
  - `safety-agent`
- caller-supplied tools
- lazy imports for optional runtime dependencies

This makes the module usable both in local development and in partially built
project states where not every downstream component exists yet.
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
1. 读取当前病例状态与阶段
2. 选择合适的子代理或工具推进流程
3. 优先执行安全必问与风险检查
4. 让问诊按照“安全优先 + 图谱驱动收敛”的原则推进
5. 汇总对子患者可见的阶段性回复

核心规则：
- 永远先看风险，再看收敛效率
- 红旗征象或高风险特殊人群优先进入安全判断
- “下一问”的选择应优先依赖图谱推理与结构化工具结果
- 不要把候选证型表达成确定性的最终诊断
- 不要直接给出处方或高风险治疗建议
- 需要时触发人工审核或建议线下就医

用户可见回复应当：
- 简洁
- 清楚
- 保守
- 不暴露内部调度细节
""".strip()

DEFAULT_TRIAGE_PROMPT = """
你是 TCMAgent 的导诊代理 triage-agent。

你的职责是：
- 识别是否适合继续线上问诊
- 快速识别红旗征象
- 标记特殊人群
- 给出推荐问诊路径

工作原则：
- 优先识别急重症信号
- 风险不明确时应更保守
- 不做深度辨证分析
- 输出尽量结构化，供 supervisor 与 safety-agent 使用
""".strip()

DEFAULT_INTAKE_PROMPT = """
你是 TCMAgent 的问诊采集代理 intake-agent。

你的职责是：
- 将系统选出的“下一问”转化为自然、简洁、患者易懂的话术
- 解析患者回答并帮助结构化
- 维护问诊节奏，避免一次性追问过多
- 标记不确定信息与潜在冲突信息

工作原则：
- 你负责“怎么问”和“怎么整理回答”
- 你不负责自由决定问诊方向
- 你不应直接做最终诊断或高风险建议
- 当信息不足时，应继续帮助补充关键事实
""".strip()

DEFAULT_SAFETY_PROMPT = """
你是 TCMAgent 的安全代理 safety-agent。

你的职责是：
- 复核红旗征象
- 识别特殊人群风险
- 检查是否存在不适合继续线上问诊的情况
- 给出是否应转人工或建议线下就医的结论

工作原则：
- 安全优先于收敛效率
- 不可忽略红旗征象
- 在不确定风险时应采用更保守策略
- 输出必须足以让 supervisor 做出明确分支决策
""".strip()


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

    def resolved_model(self, settings: Settings) -> str:
        """Resolve the active model spec for deepagents."""
        if self.model:
            return self.model
        return f"{settings.model_provider}:{settings.model_name}"


@dataclass(slots=True)
class SubagentTools:
    """Tool grouping for first-stage subagent assembly."""

    shared: list[Any] = field(default_factory=list)
    triage: list[Any] = field(default_factory=list)
    intake: list[Any] = field(default_factory=list)
    safety: list[Any] = field(default_factory=list)


def _merge_tools(*groups: Sequence[Any]) -> list[Any]:
    """Merge tool groups while preserving order and removing duplicate objects."""
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


def build_default_subagents(
    *,
    model: str | None = None,
    tools: SubagentTools | None = None,
    interrupt_on: Mapping[str, bool | dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the default first-stage subagent specifications.

    Parameters
    ----------
    model:
        Optional model override applied to each declarative subagent.
    tools:
        Structured tool groups to attach to each subagent.
    interrupt_on:
        Optional interrupt configuration inherited by subagents.

    Returns
    -------
    list[dict[str, Any]]
        A list of declarative subagent specs suitable for `create_deep_agent`.
    """
    grouped_tools = tools or SubagentTools()
    inherited_interrupts = dict(interrupt_on or {})

    triage_tools = _merge_tools(grouped_tools.shared, grouped_tools.triage)
    intake_tools = _merge_tools(grouped_tools.shared, grouped_tools.intake)
    safety_tools = _merge_tools(grouped_tools.shared, grouped_tools.safety)

    base: dict[str, Any] = {}
    if model:
        base["model"] = model
    if inherited_interrupts:
        base["interrupt_on"] = inherited_interrupts

    return [
        {
            **base,
            "name": "triage-agent",
            "description": (
                "用于导诊、接诊前风险初筛和特殊人群标记。"
                "适合在问诊开始前快速判断是否适合继续线上流程。"
            ),
            "system_prompt": DEFAULT_TRIAGE_PROMPT,
            "tools": triage_tools,
        },
        {
            **base,
            "name": "intake-agent",
            "description": (
                "用于将图谱推荐问题转成自然问法，并将患者回答整理为结构化事实。"
                "适合执行动态追问，不负责最终判断。"
            ),
            "system_prompt": DEFAULT_INTAKE_PROMPT,
            "tools": intake_tools,
        },
        {
            **base,
            "name": "safety-agent",
            "description": (
                "用于红旗复核、特殊人群风险检查与转人工/转线下决策支持。适合在关键节点做安全兜底。"
            ),
            "system_prompt": DEFAULT_SAFETY_PROMPT,
            "tools": safety_tools,
        },
    ]


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
    ) -> list[dict[str, Any]]:
        """Build the default first-stage subagent set."""
        merged_interrupts = dict(self.config.interrupt_on)
        if interrupt_on:
            merged_interrupts.update(interrupt_on)

        return build_default_subagents(
            model=self.model_spec,
            tools=tools,
            interrupt_on=merged_interrupts,
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

        Most parameters are passed through to `deepagents.create_deep_agent`.
        The caller can supply fully custom tools and subagents, or rely on the
        factory's first-stage defaults.
        """
        try:
            from deepagents import create_deep_agent
        except Exception as exc:  # pragma: no cover - import path depends on env
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

        return create_deep_agent(
            model=self.model_spec,
            tools=list(tools or []),
            system_prompt=system_prompt or self.config.system_prompt,
            middleware=list(middleware or []),
            subagents=relaxed_subagents,
            skills=list(skill_paths or self.config.skill_paths),
            memory=list(memory_paths or self.config.memory_paths),
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
    ) -> Any:
        """Create the first-stage default consultation graph.

        This is the recommended entry point for the MVP:
        - default supervisor prompt
        - default triage / intake / safety subagents
        - caller-provided tools grouped by responsibility
        """
        subagents = self.build_subagents(
            tools=subagent_tools,
            interrupt_on=interrupt_on,
        )
        return self.create_supervisor(
            tools=supervisor_tools,
            subagents=subagents,
            memory_paths=memory_paths,
            skill_paths=skill_paths,
            interrupt_on=interrupt_on,
            checkpointer=checkpointer,
            store=store,
            backend=backend,
            middleware=middleware,
        )


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
