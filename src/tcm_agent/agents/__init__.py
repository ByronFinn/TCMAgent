"""Agent package for TCMAgent.

Exports the factory layer (supervisor graph assembly) and the skills loader
(CompositeBackend wiring and skill-path helpers) as a unified public API.
"""

from .factory import (
    DEFAULT_INTAKE_PROMPT,
    DEFAULT_SAFETY_PROMPT,
    DEFAULT_SUPERVISOR_NAME,
    DEFAULT_SUPERVISOR_PROMPT,
    DEFAULT_TRIAGE_PROMPT,
    AgentFactory,
    AgentFactoryConfig,
    SubagentTools,
    build_default_subagents,
    create_default_agent_factory,
    create_supervisor_agent,
)
from .skills_loader import (
    INTAKE_SOURCE,
    SAFETY_SOURCE,
    SHARED_SOURCE,
    SKILLS_PREFIX,
    SKILLS_ROOT,
    TRIAGE_SOURCE,
    build_composite_backend,
    describe_skills_layout,
    intake_skill_sources,
    safety_skill_sources,
    skills_available,
    triage_skill_sources,
)

__all__ = [
    "DEFAULT_INTAKE_PROMPT",
    "DEFAULT_SAFETY_PROMPT",
    "DEFAULT_SUPERVISOR_NAME",
    "DEFAULT_SUPERVISOR_PROMPT",
    "DEFAULT_TRIAGE_PROMPT",
    "INTAKE_SOURCE",
    "SAFETY_SOURCE",
    "SHARED_SOURCE",
    "SKILLS_PREFIX",
    "SKILLS_ROOT",
    "TRIAGE_SOURCE",
    "AgentFactory",
    "AgentFactoryConfig",
    "SubagentTools",
    "build_composite_backend",
    "build_default_subagents",
    "create_default_agent_factory",
    "create_supervisor_agent",
    "describe_skills_layout",
    "intake_skill_sources",
    "safety_skill_sources",
    "skills_available",
    "triage_skill_sources",
]
