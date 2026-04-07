# TCMAgent Skills 架构设计文档 v2

## 1. 文档目标

本文档回答三个核心问题：

1. **为什么之前没有 Skill 层？** — 分析当前方案的设计缺口
2. **Tool、Skill、Sub-Agent 如何区分？** — 第一性原理论证
3. **TCMAgent 如何正确落地 Skill 层？** — 基于 deepagents 真实机制的实现方案

---

## 2. 当前设计缺口分析

### 2.1 为什么之前没有 Skill？

**事实一：代码层面**

`AgentFactoryConfig` 中存在 `skill_paths: list[str] = field(default_factory=list)`，但始终为空列表。`build_default_subagents` 从未向任何子代理传递 `skills`。`skills/` 目录也不存在。

**事实二：deepagents 的 Skill 是特定格式的文件系统结构**

deepagents 的 `SkillsMiddleware` 遵循 [Agent Skills 规范](https://agentskills.io/specification)。每个 skill **必须**是一个独立子目录，目录内有且仅有一个 `SKILL.md` 文件，该文件须包含 YAML frontmatter：

```
skills/
└── triage/
    └── red-flags-protocol/      ← 目录名即 skill name
        └── SKILL.md             ← 必须包含 YAML frontmatter
```

`SKILL.md` 格式：

```markdown
---
name: red-flags-protocol        ← 必须与父目录名完全一致
description: What this skill does and when to use it (max 1024 chars)
---

# 正文内容（progressive disclosure 时按需加载）
```

平铺的 `.md` 文件（如 `red_flags_protocol.md`）**不会被 SkillsMiddleware 识别**。

**事实三：`skills` 字段的集成方式**

在 SubAgent spec 中使用 `skills` 字段时，`create_deep_agent` 内部自动处理：

```python
# 来自 deepagents/graph.py（真实源码）
subagent_skills = spec.get("skills")
if subagent_skills:
    subagent_middleware.append(
        SkillsMiddleware(backend=backend, sources=subagent_skills)
    )
```

关键点：`SkillsMiddleware` 使用的 `backend` 与主 agent 的 `backend` **完全相同**。

**事实四：Backend 选择影响 Skills 的加载方式**

| Backend | Skills 如何加载 |
|---------|---------------|
| `StateBackend`（默认） | Skills 文件内容须在 `invoke(files={...})` 时注入，无法从磁盘自动加载 |
| `FilesystemBackend` | Skills 从磁盘自动加载，但给 agent 暴露了 read/write 文件工具（不适合 Web API） |
| `CompositeBackend` | **推荐**：`/skills/` 路由到只读 `FilesystemBackend`，其余路径走 `StateBackend` |

**结论**

Skill 层缺失的根本原因：
1. **文件格式不对**：没有按 Agent Skills 规范使用 `skill-name/SKILL.md` 子目录结构
2. **集成方式不对**：试图手动创建 `SkillsMiddleware` 并加入 `middleware`，但 deepagents 会自动处理（造成重复）
3. **Backend 未配置**：未设置 `CompositeBackend`，导致 `SkillsMiddleware` 读取 skills 时无可用后端

---

## 3. Tool / Skill / Sub-Agent 的原则性区分

### 3.1 第一性原理框架

完成一项临床任务需要三个维度的能力：

```
任务 = 知道做什么（角色边界）
     + 知道怎么做（过程知识）
     + 能做到（原子操作能力）
```

对应：

| 层 | 解决的问题 | 在 deepagents 中的表现 |
|----|------------|----------------------|
| Sub-Agent | "做什么"（角色边界） | 有 `name`/`system_prompt`/`description` 的推理主体 |
| Skill | "怎么做"（过程知识） | `skill-name/SKILL.md`，通过 `SkillsMiddleware` 注入上下文 |
| Tool | "能做到"（原子操作） | Python 函数，结构化输入→结构化输出，无 LLM |

### 3.2 三者的完整对比

| 维度 | Tool（工具） | Skill（技能） | Sub-Agent（子代理） |
|------|------------|-------------|-----------------|
| **本质** | 原子操作单元 | 结构化过程知识 | 有角色的推理主体 |
| **实现形式** | Python 函数 | `skill-name/SKILL.md`（YAML frontmatter + Markdown） | deepagents SubAgent spec |
| **LLM 参与** | 无（纯确定性） | 被动（内容注入上下文，渐进式披露） | 主动（自主推理决策） |
| **状态** | 无状态 | 无状态 | 有对话上下文 |
| **触发方式** | Agent 显式调用 | `before_agent` 钩子自动注入系统提示 | Supervisor 委托 `task` 工具 |
| **可复用性** | 高，任意 Agent 可用 | 高，跨 Agent 按需挂载 | 低，角色专属 |
| **更新成本** | 代码变更，需测试 | 修改 Markdown，无需重部署 | 代码+提示词变更 |

### 3.3 边界判断准则

**用 Tool 当：**
> 操作是确定性的、结构化的、不需要语言理解。

- `query_graph_candidates(chief_complaint, ...)` — Neo4j 查询
- `screen_red_flags(facts)` — 规则匹配
- `update_case_facts(case_id, facts)` — 状态写入

**用 Skill 当：**
> 需要告诉 LLM "怎么做某件事"的过程知识，且这种知识 LLM 遵循即可，不需要独立决策流程。

- 症状归一化的对照表和步骤（`symptom-normalization-protocol`）
- 红旗筛查的清单和等级判断（`red-flags-protocol`）
- 风险综合的决策逻辑（`risk-synthesis-protocol`）

**用 Sub-Agent 当：**
> 需要一个具有独立角色边界，能在任务范围内自主推进、作出决策的推理主体。

- `triage-agent` — 独立完成导诊全流程
- `intake-agent` — 独立执行问诊采集
- `safety-agent` — 独立完成安全复核，可阻断其他代理

### 3.4 常见错误

| 错误 | 正确做法 |
|------|---------|
| 把过程知识写进 `system_prompt`（提示词过长） | `system_prompt` 只写角色定位，过程知识放 Skill |
| 把过程知识放进 Tool 的 if-else 逻辑里 | Tool 只做原子操作，规则/协议放 Skill |
| 在 SubAgent spec 的 `middleware` 里手动加 `SkillsMiddleware` | 使用 SubAgent 的 `skills` 字段，由 deepagents 自动添加 |
| 用平铺 `.md` 文件作为 skills | 每个 skill 必须是独立子目录 + `SKILL.md`（含 YAML frontmatter） |

---

## 4. deepagents Skills 真实机制

### 4.1 Skill 文件格式（Agent Skills 规范）

```
skills/
├── shared/                              ← source 目录（传给 SkillsMiddleware）
│   ├── tcm-clinical-basics/             ← skill 子目录（名称 = skill name）
│   │   └── SKILL.md                     ← 必须存在，须有 YAML frontmatter
│   └── case-state-protocol/
│       └── SKILL.md
└── triage/
    ├── red-flags-protocol/
    │   └── SKILL.md
    └── ...
```

`SKILL.md` 的 YAML frontmatter 约束（来自 `deepagents/middleware/skills.py`）：

| 字段 | 要求 |
|------|------|
| `name` | **必须**，1-64 字符，全小写字母+数字+连字符，**必须与目录名完全一致** |
| `description` | **必须**，1-1024 字符，描述 what it does + when to use it |
| `license` | 可选 |
| `compatibility` | 可选，≤500 字符 |
| `allowed-tools` | 可选，空格分隔的工具名列表 |
| `metadata` | 可选，`dict[str, str]` |

示例：

```markdown
---
name: red-flags-protocol
description: "Red flag symptom screening protocol with three severity levels:
  Level 1 (immediate emergency referral), Level 2 (high-risk, recommend offline),
  Level 3 (monitor). Use at triage stage and whenever a new symptom is reported."
---

# Red Flags Protocol

## Level 1 - Immediate Emergency
- Chest pain with dyspnea
- Loss of consciousness
...
```

### 4.2 SkillsMiddleware 的工作原理

```python
# deepagents/middleware/skills.py（简化）
def before_agent(self, state, runtime, config):
    # 只在 state 中没有 skills_metadata 时加载（每 session 只加一次）
    if "skills_metadata" in state:
        return None

    all_skills = {}
    for source_path in self.sources:
        # 扫描 source_path 下的所有子目录
        # 找到含 SKILL.md 的子目录，解析 YAML frontmatter
        for skill in _list_skills(backend, source_path):
            all_skills[skill["name"]] = skill  # 后面的 source 覆盖前面的

    return SkillsStateUpdate(skills_metadata=list(all_skills.values()))

def wrap_model_call(self, request, handler):
    # 每次 LLM 调用前，把技能元数据（名称+描述+路径）注入系统提示
    # 渐进式披露：LLM 先看技能列表，需要时 read_file(skill_path) 获取全文
    modified_request = self.modify_request(request)
    return handler(modified_request)
```

**渐进式披露（Progressive Disclosure）的价值**：

1. LLM 先收到技能**目录**（名称 + 描述 + 文件路径）
2. 当 LLM 判断某技能与当前任务相关时，调用 `read_file(path)` 获取完整内容
3. 技能文档可以很长，但不会每次都占满上下文窗口

### 4.3 create_deep_agent 内部如何处理 SubAgent 的 skills

```python
# deepagents/graph.py（真实源码，关键片段）

backend = backend if backend is not None else StateBackend()

for spec in subagents or []:
    # 构建 sub-agent 的中间件栈
    subagent_middleware = [
        TodoListMiddleware(),
        FilesystemMiddleware(backend=backend),    # 文件工具，用主 backend
        create_summarization_middleware(...),
        PatchToolCallsMiddleware(),
    ]

    # 关键：从 spec 取 skills，用主 backend 自动创建 SkillsMiddleware
    subagent_skills = spec.get("skills")
    if subagent_skills:
        subagent_middleware.append(
            SkillsMiddleware(backend=backend, sources=subagent_skills)
        )

    # spec.get("middleware", []) 中的自定义中间件追加在后面
    subagent_middleware.extend(spec.get("middleware", []))
```

**结论**：
- SubAgent spec 的 `skills` 字段 → deepagents 自动创建 `SkillsMiddleware`，使用**主 backend**
- SubAgent spec 的 `middleware` 字段 → **追加**在 deepagents 自动中间件**之后**
- **不要**在 `middleware` 里手动添加 `SkillsMiddleware`（会重复）

---

## 5. TCMAgent 的 Backend 设计

### 5.1 为什么需要 CompositeBackend

| 方案 | 问题 |
|------|------|
| `StateBackend`（默认） | Skills 无法从磁盘自动加载；每次 invoke 需注入文件内容 |
| `FilesystemBackend(root_dir=project/)` | Agent 的 `read_file`/`write_file` 工具可访问整个项目目录，包括 `.env`、密钥等 |
| `FilesystemBackend(root_dir=skills/)` | Skills 可加载；但 `read_file` 工具也被限制在 skills 目录，agent 无法正常使用文件工具 |
| **`CompositeBackend`（采用）** | `/skills/` 路由到只读范围的 `FilesystemBackend`；其余路径走 `StateBackend`（安全） |

### 5.2 CompositeBackend 路由规则

```python
# TCMAgent 采用的配置（skills_loader.py）
from deepagents.backends import FilesystemBackend, StateBackend
from deepagents.backends.composite import CompositeBackend

backend = CompositeBackend(
    default=StateBackend(),                       # 其他路径：安全的内存存储
    routes={
        "/skills/": FilesystemBackend(
            root_dir=str(SKILLS_ROOT),
            virtual_mode=True,              # 阻止路径穿越（..、~）
        )
    },
)
```

路由示意：

```
请求路径                    →  实际 Backend              →  磁盘路径
/skills/triage/            →  FilesystemBackend          →  SKILLS_ROOT/triage/
/skills/triage/red-.../    →  FilesystemBackend          →  SKILLS_ROOT/triage/red-.../
/todos/list.txt            →  StateBackend（内存）        →  （不访问磁盘）
/workspace/output.txt      →  StateBackend（内存）        →  （不访问磁盘）
```

`virtual_mode=True` 的作用（来自 `FilesystemBackend` 源码）：
- 将所有路径视为相对于 `root_dir` 的虚拟路径
- 阻止 `..`、`~`、绝对路径穿越 `root_dir`
- 适合与 `CompositeBackend` 配合，提供路径级别的隔离

### 5.3 Skills 目录结构

```
SKILLS_ROOT（project-root/skills/）
├── shared/                                  ← 所有子代理共享
│   ├── tcm-clinical-basics/
│   │   └── SKILL.md
│   └── case-state-protocol/
│       └── SKILL.md
├── triage/                                  ← 仅 triage-agent
│   ├── red-flags-protocol/
│   │   └── SKILL.md
│   ├── special-population-rules/
│   │   └── SKILL.md
│   └── visit-routing-guide/
│       └── SKILL.md
├── intake/                                  ← 仅 intake-agent
│   ├── symptom-normalization-protocol/
│   │   └── SKILL.md
│   ├── question-phrasing-guide/
│   │   └── SKILL.md
│   └── contradiction-detection-rules/
│       └── SKILL.md
└── safety/                                  ← 仅 safety-agent
    ├── risk-synthesis-protocol/
    │   └── SKILL.md
    └── contraindication-reference/
        └── SKILL.md
```

### 5.4 各子代理的 Skill Sources

| 子代理 | `skills` 字段 | 加载的 skill 数量 |
|--------|-------------|-----------------|
| `triage-agent` | `["/skills/shared/", "/skills/triage/"]` | 5（2 共享 + 3 专属） |
| `intake-agent` | `["/skills/shared/", "/skills/intake/"]` | 5（2 共享 + 3 专属） |
| `safety-agent` | `["/skills/shared/", "/skills/safety/"]` | 4（2 共享 + 2 专属） |

---

## 6. 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      clinical-supervisor                             │
│  system_prompt: 流程编排规则                                          │
│  tools: create_case, get_case_state, set_case_stage,                │
│         query_graph_candidates, find_discriminative_questions,       │
│         issue_risk_decision, generate_patient_summary_template       │
│  backend: CompositeBackend                                           │
│    ├── /skills/ → FilesystemBackend(root_dir=skills/, virtual=True) │
│    └── default  → StateBackend()                                     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ task(name=...)
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  triage-agent    │ │  intake-agent    │ │  safety-agent    │
│                  │ │                  │ │                  │
│ skills:          │ │ skills:          │ │ skills:          │
│  /skills/shared/ │ │  /skills/shared/ │ │  /skills/shared/ │
│  /skills/triage/ │ │  /skills/intake/ │ │  /skills/safety/ │
│                  │ │                  │ │                  │
│ ← SkillsMiddleware 由 create_deep_agent 根据 skills 字段自动创建 →   │
│ ← SkillsMiddleware 使用主 agent 的 CompositeBackend 读取 SKILL.md → │
│                  │ │                  │ │                  │
│ tools:           │ │ tools:           │ │ tools:           │
│  run_triage      │ │  update_case_    │ │  screen_red_     │
│  classify_visit_ │ │  facts           │ │  flags           │
│  route           │ │  record_question │ │  check_popul_    │
│  tag_special_    │ │  _asked          │ │  ation_risks     │
│  population      │ │  find_discrim_   │ │  check_contra_   │
│  screen_red_     │ │  questions       │ │  indications     │
│  flags           │ │  explain_ration_ │ │  run_full_safety │
│  set_case_stage  │ │  ale             │ │  _check          │
│                  │ │                  │ │  issue_risk_     │
│                  │ │                  │ │  decision        │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

---

## 7. 代码实现要点

### 7.1 skills_loader.py 的职责

`skills_loader.py` 只做两件事：

1. **构建 `CompositeBackend`**（`build_composite_backend()`）
2. **暴露各角色的 skill source 路径**（`triage_skill_sources()` 等）

它**不**创建 `SkillsMiddleware`——那是 deepagents 的工作。

```python
# skills_loader.py 的核心逻辑
SKILLS_PREFIX = "/skills/"

def build_composite_backend():
    skills_backend = FilesystemBackend(root_dir=str(SKILLS_ROOT), virtual_mode=True)
    return CompositeBackend(
        default=StateBackend(),
        routes={SKILLS_PREFIX: skills_backend},
    )

def triage_skill_sources() -> list[str]:
    return ["/skills/shared/", "/skills/triage/"]
```

### 7.2 factory.py 中 SubAgent spec 的正确写法

```python
# ✅ 正确：使用 skills 字段，deepagents 自动创建 SkillsMiddleware
{
    "name": "triage-agent",
    "description": "导诊代理...",
    "system_prompt": DEFAULT_TRIAGE_PROMPT,
    "tools": triage_tools,
    "skills": ["/skills/shared/", "/skills/triage/"],  # ← 正确
}

# ❌ 错误：手动在 middleware 中添加 SkillsMiddleware（会重复）
{
    "name": "triage-agent",
    "middleware": [SkillsMiddleware(backend=..., sources=[...])],  # ← 错误
}
```

### 7.3 create_default_consultation_graph 的 Backend 传递

```python
# factory.py 中 create_default_consultation_graph 的关键逻辑
resolved_backend = backend
if resolved_backend is None and use_skills:
    from tcm_agent.agents.skills_loader import build_composite_backend
    resolved_backend = build_composite_backend()

# 这个 backend 被传给 create_deep_agent，
# create_deep_agent 把它传给 SkillsMiddleware(backend=resolved_backend, ...)
return self.create_supervisor(..., backend=resolved_backend)
```

---

## 8. 优化前后对比

### 8.1 Skills 文件格式

| | 之前（错误） | 之后（正确） |
|--|------------|------------|
| 目录结构 | `skills/triage/red_flags_protocol.md` | `skills/triage/red-flags-protocol/SKILL.md` |
| 前置要求 | 无 | YAML frontmatter（`name` + `description`） |
| 识别方式 | 不被 SkillsMiddleware 识别 | 被 `_list_skills()` 自动扫描 |

### 8.2 SkillsMiddleware 集成方式

| | 之前（错误） | 之后（正确） |
|--|------------|------------|
| 如何添加 | 手动在 `middleware` 字段中 | 通过 SubAgent spec 的 `skills` 字段，deepagents 自动处理 |
| 使用的 backend | 独立的 `FilesystemBackend`（与主 agent 分离） | 主 agent 的 `CompositeBackend`（正确） |
| 是否重复 | 可能重复 | 不重复 |

### 8.3 Backend 配置

| | 之前 | 之后 |
|--|------|------|
| 主 backend | 未配置（默认 StateBackend） | `CompositeBackend` |
| Skills 加载 | 无法从磁盘加载 | `/skills/` 路由到 `FilesystemBackend(virtual_mode=True)` |
| Web API 安全 | N/A | 其余路径走 `StateBackend`，不暴露文件系统 |

### 8.4 工具集完善

| 工具文件 | 优化前 | 优化后 |
|---------|--------|--------|
| `case_tools.py` | ✅ 已实现 | ✅ 保持 |
| `graph_tools.py` | ✅ 已实现 | ✅ 保持 |
| `safety_tools.py` | ✅ 已实现 | ✅ 保持 |
| `triage_tools.py` | ❌ 缺失 | ✅ 新增（3 个工具） |
| `summary_tools.py` | ❌ 缺失 | ✅ 新增（3 个工具） |

---

## 9. Skill 文件编写规范

每个 `SKILL.md` 的结构：

```markdown
---
name: skill-name           # 全小写，只含字母/数字/连字符，与目录名一致
description: "English description, max 1024 chars. Describe WHAT it does
  and WHEN to use it. Include domain keywords."
---

# 技能标题

## 适用范围
什么情况下使用；什么情况下不适用。

## 核心协议 / 规则
具体步骤、规则、对照表。

## 输出格式
当此技能被调用时，期望的输出结构（如对应的 Schema 字段）。

## 注意事项
边缘情况、禁止事项。
```

**约束**：
- `name` 必须与目录名完全一致（来自 `_validate_skill_name`）
- `description` 必须是英文（供 LLM 理解 when to use）
- 正文可以是中文（供中医场景的具体内容）
- 不要在 Skill 文件中放 Python 代码（Skill 是知识，不是实现）
- 更新 Skill 文件不需要重启服务

---

## 10. 数据流：skills 在一次问诊中的作用

```
1. API 请求到达
       │
       ▼
2. create_default_consultation_graph() 构建 graph
   ├── build_composite_backend()
   │   └── CompositeBackend(/skills/ → FilesystemBackend, default → StateBackend)
   └── build_default_subagents(enable_skills=True)
       └── 每个 SubAgent spec 含 skills=["/skills/shared/", "/skills/xxx/"]

       │
       ▼
3. supervisor 调用 task("triage-agent", ...)
       │
       ▼
4. triage-agent 启动时，SkillsMiddleware.before_agent() 执行
   ├── 调用 CompositeBackend.ls("/skills/shared/")
   │   → 路由到 FilesystemBackend，返回 [tcm-clinical-basics/, case-state-protocol/]
   ├── 调用 CompositeBackend.ls("/skills/triage/")
   │   → 路由到 FilesystemBackend，返回 [red-flags-protocol/, ...]
   ├── 下载并解析所有 SKILL.md（读取 YAML frontmatter）
   └── 写入 state["skills_metadata"]（每 session 只加载一次）

       │
       ▼
5. triage-agent 推理时，SkillsMiddleware.wrap_model_call() 执行
   └── 在系统提示末尾注入技能目录（名称 + 描述 + 路径）

       │
       ▼
6. triage-agent LLM 决策
   ├── 看到技能列表，判断 "red-flags-protocol" 与当前任务相关
   ├── 调用 read_file("/skills/triage/red-flags-protocol/SKILL.md") 获取完整内容
   │   → CompositeBackend 路由到 FilesystemBackend，从磁盘读取
   └── 按协议执行红旗筛查，调用 run_triage() 工具

       │
       ▼
7. 结果返回 supervisor，继续下一阶段
```

---

## 11. 后续扩展路径

### 11.1 第二阶段新增 Skills

| Skill 目录 | 挂载代理 | 用途 |
|-----------|---------|------|
| `intake/pulse-diagnosis-guide/` | intake-agent | 脉诊描述归一化 |
| `intake/tongue-diagnosis-guide/` | intake-agent | 舌诊描述归一化 |
| `triage/chronic-disease-intake/` | triage-agent | 慢病初诊特殊协议 |
| `safety/elderly-care-protocol/` | safety-agent | 老年患者专项安全规则 |

### 11.2 Graph-Reasoner 升级为 Sub-Agent 的时机

当满足以下条件时，可考虑将 `graph_reasoning_service` 升级为独立的 `graph-reasoner` Sub-Agent：

- 图谱推理需要多步骤 LLM 辅助推理（当前纯规则计分无法满足）
- 候选评分需要 LLM 语义理解
- 证据路径解释需要自然语言生成能力

在此之前，保持 service + tool 的架构（确定性、可追踪、无 LLM 成本）。

### 11.3 允许工具的声明

`SKILL.md` 支持 `allowed-tools` 字段，可限制技能推荐使用的工具：

```yaml
---
name: red-flags-protocol
description: "..."
allowed-tools: screen_red_flags run_triage issue_risk_decision
---
```

这是 Agent Skills 规范的实验性特性，未来可用于约束子代理的工具调用行为。

---

## 12. 一句话总结

> TCMAgent 的 Skill 层通过 **`skill-name/SKILL.md`** 格式定义过程知识，
> 在 SubAgent spec 的 **`skills` 字段**声明来源路径，
> 由 `create_deep_agent` 自动创建 `SkillsMiddleware`，
> 通过 **`CompositeBackend`** 将 `/skills/` 路由到只读 `FilesystemBackend`（`virtual_mode=True`），
> 实现对 Web API 安全的、始终可用的、渐进式披露的技能知识注入。