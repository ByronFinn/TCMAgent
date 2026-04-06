# 工程骨架设计方案 v1

## 1. 文档目标

本文档定义项目第一阶段的工程骨架与实施方案，目标是把当前项目从“架构讨论”推进到“可初始化、可扩展、可运行”的工程状态。

本方案重点解决以下问题：

1. 如何使用 `uv` 管理 Python 项目
2. 如何围绕 `deepagents` 组织主代理、子代理、工具与状态
3. 如何为 `Neo4j` 图谱推理预留稳定的模块边界
4. 如何为 `deep-agents-ui` 提供后端承载结构
5. 如何让项目从 MVP 平滑演进到后续扩展阶段

---

## 2. 工程目标

第一阶段工程目标不是“做全”，而是“做稳”。

### 2.1 第一阶段必须实现
- 用 `uv` 初始化并管理 Python 项目
- 建立清晰的目录结构
- 建立 `deepagents` 主编排入口
- 建立 `Neo4j` 图谱访问层
- 建立 `case_state` 数据结构
- 建立问诊、风控、图谱推理三类核心工具
- 为 `deep-agents-ui` 提供后端接口基础
- 建立最小测试与配置体系

### 2.2 第一阶段不追求
- 复杂处方生成
- 完整长期随访闭环
- 多模态复杂推理
- 复杂工作流可视化平台
- 一次性做完所有知识图谱建模

---

## 3. 技术栈原则

## 3.1 Python 项目管理
使用 `uv` 负责：
- 虚拟环境
- 依赖安装
- 锁定依赖
- 开发脚本运行

## 3.2 Agent 编排
使用 `deepagents` 负责：
- 主代理组织
- 子代理拆分
- 工具调用治理
- 上下文管理
- 中断与人工确认节点

## 3.3 图谱与医学知识
使用 `Neo4j` 负责：
- 医学节点与关系存储
- 候选空间检索
- 区分性问题选择支持
- 证据路径追踪

## 3.4 前端交互
使用 `deep-agents-ui` 负责：
- 患者问诊界面
- 内部状态展示
- 审核与中断反馈
- 推理结果与证据辅助展示

## 3.5 数据建模
使用 `pydantic` 负责：
- 输入输出 schema
- `case_state` 模型
- 工具参数校验
- 结构化结果标准化

---

## 4. 推荐目录结构

建议第一版目录结构如下：

```text
TCMAgent/
├─ README.md
├─ pyproject.toml
├─ uv.lock
├─ .env.example
├─ .gitignore
├─ docs/
│  ├─ neo4j-schema.md
│  ├─ architecture-plan.md
│  ├─ workflow-design.md
│  └─ tool-contracts.md
├─ src/
│  └─ tcm_agent/
│     ├─ __init__.py
│     ├─ config/
│     │  ├─ __init__.py
│     │  ├─ settings.py
│     │  └─ logging.py
│     ├─ schemas/
│     │  ├─ __init__.py
│     │  ├─ case.py
│     │  ├─ triage.py
│     │  ├─ intake.py
│     │  ├─ safety.py
│     │  ├─ graph_reasoning.py
│     │  └─ response.py
│     ├─ state/
│     │  ├─ __init__.py
│     │  ├─ case_store.py
│     │  ├─ case_transitions.py
│     │  └─ audit.py
│     ├─ graph/
│     │  ├─ __init__.py
│     │  ├─ neo4j_client.py
│     │  ├─ repository.py
│     │  ├─ candidate_query.py
│     │  ├─ question_selector.py
│     │  └─ evidence_builder.py
│     ├─ tools/
│     │  ├─ __init__.py
│     │  ├─ case_tools.py
│     │  ├─ triage_tools.py
│     │  ├─ safety_tools.py
│     │  ├─ graph_tools.py
│     │  └─ summary_tools.py
│     ├─ services/
│     │  ├─ __init__.py
│     │  ├─ triage_service.py
│     │  ├─ intake_service.py
│     │  ├─ graph_reasoning_service.py
│     │  ├─ safety_service.py
│     │  └─ summary_service.py
│     ├─ prompts/
│     │  ├─ __init__.py
│     │  ├─ supervisor.py
│     │  ├─ triage_agent.py
│     │  ├─ intake_agent.py
│     │  └─ safety_agent.py
│     ├─ agents/
│     │  ├─ __init__.py
│     │  ├─ supervisor.py
│     │  ├─ subagents.py
│     │  └─ factory.py
│     ├─ api/
│     │  ├─ __init__.py
│     │  ├─ app.py
│     │  ├─ routes/
│     │  │  ├─ __init__.py
│     │  │  ├─ health.py
│     │  │  ├─ cases.py
│     │  │  └─ chat.py
│     │  └─ deps.py
│     └─ runtime/
│        ├─ __init__.py
│        ├─ bootstrap.py
│        └─ registry.py
├─ tests/
│  ├─ unit/
│  │  ├─ test_case_state.py
│  │  ├─ test_graph_reasoning.py
│  │  ├─ test_question_selector.py
│  │  └─ test_safety_rules.py
│  ├─ integration/
│  │  ├─ test_agent_flow.py
│  │  ├─ test_neo4j_repository.py
│  │  └─ test_api_chat.py
│  └─ fixtures/
│     ├─ sample_cases.json
│     └─ sample_graph.json
└─ scripts/
   ├─ bootstrap.ps1
   ├─ bootstrap.sh
   ├─ seed_neo4j.py
   └─ run_dev.py
```

---

## 5. 为什么这样分层

## 5.1 `schemas/`
这一层负责定义所有“结构化事实”。

不要把结构化字段散落在工具和 agent 中。  
所有核心对象都应先建模，再进入流程。

重点包括：
- `CaseState`
- `PatientProfile`
- `TriageDecision`
- `GraphCandidate`
- `QuestionRecommendation`
- `RiskDecision`
- `PatientSummary`
- `ClinicianSummary`

## 5.2 `state/`
这一层负责病例状态管理，而不是聊天缓存。

职责包括：
- 案例创建
- 状态更新
- 阶段流转
- 审计日志
- 决策留痕

这一层应该尽量不依赖 LLM。

## 5.3 `graph/`
这是 Neo4j 的隔离层。

不要让上层模块直接拼接 Cypher。  
所有图谱查询都应该通过统一仓储或服务接口完成。

建议拆成：
- `neo4j_client.py`：连接管理
- `repository.py`：底层读写
- `candidate_query.py`：候选检索
- `question_selector.py`：区分性问题选择
- `evidence_builder.py`：证据路径构建

## 5.4 `tools/`
这一层是 deepagents 可调用能力的出口层。

工具不应包含太多业务拼装逻辑，而应：
- 参数清晰
- 输出结构化
- 调用 service / graph / state 层
- 便于测试与审计

## 5.5 `services/`
这一层承载核心业务逻辑。

这样做的好处是：
- 工具更薄
- Agent 更轻
- 逻辑更容易复用
- 后续 API / batch / CLI 都能共用

## 5.6 `prompts/`
只放提示词与角色边界，不放核心规则。

尤其不要把：
- 状态转移规则
- 风控规则
- 图谱推理规则

藏在提示词里。

## 5.7 `agents/`
负责组合 `deepagents` 的主代理与子代理。

这里应该包含：
- supervisor 创建
- subagent 注册
- 工具装配
- 中断策略配置

## 5.8 `api/`
即使前期 UI 还没完全接上，也建议尽早把 API 层独立出来。

因为后续无论你用：
- deep-agents-ui
- 自己的前端
- 内部运营后台

都需要一个稳定的服务接口层。

---

## 6. 推荐模块职责

## 6.1 `config/settings.py`
负责统一配置来源。

建议管理：
- 模型提供商与模型名
- Neo4j 连接信息
- API 服务端口
- 日志级别
- 风险阈值
- 收敛阈值
- 是否开启调试输出

建议使用环境变量驱动。

---

## 6.2 `schemas/case.py`
定义核心病例对象。

建议至少包含：
- `case_id`
- `patient_profile`
- `chief_complaint`
- `normalized_facts`
- `candidate_diseases`
- `candidate_patterns`
- `candidate_pathogenesis`
- `asked_questions`
- `question_rationale`
- `red_flags`
- `risk_level`
- `safe_to_continue`
- `case_stage`
- `intake_completeness_score`
- `convergence_score`
- `audit_log`

---

## 6.3 `graph/question_selector.py`
这是第一阶段的关键模块之一。

它的职责不是生成自然语言，而是：
- 比较当前候选集合
- 找出区分度最高的问题
- 标记该问题的目标
- 输出结构化推荐

建议输出结构：
- `question_id`
- `question_type`
- `goal`
- `targets`
- `candidate_split_reason`
- `priority`
- `safety_related`

---

## 6.4 `services/graph_reasoning_service.py`
负责图谱推理的组合逻辑。

建议封装以下能力：
- 从主诉生成初始候选
- 根据新事实更新候选
- 生成下一问建议
- 构建支持证据与冲突证据
- 计算收敛分数

---

## 6.5 `tools/graph_tools.py`
建议暴露给 agent 的工具接口包括：
- `query_graph_candidates`
- `find_discriminative_questions`
- `build_evidence_path`
- `update_graph_evidence_projection`

工具层只负责：
- 接收结构化参数
- 调服务层
- 返回结构化结果

---

## 6.6 `agents/supervisor.py`
这里负责创建主 supervisor。

主职责：
- 读取当前病例状态
- 识别当前阶段
- 判断先调谁
- 保证安全检查先执行
- 控制问诊推进节奏

---

## 7. deepagents 组织策略

## 7.1 主代理
第一阶段建议只有一个主控：
- `clinical-supervisor`

它的工作不是做全部推理，而是：
- 编排流程
- 调用子代理
- 调用工具
- 汇总用户可见输出

## 7.2 子代理
第一阶段建议只启用：
- `triage-agent`
- `intake-agent`
- `safety-agent`

说明如下：

### `triage-agent`
负责：
- 导诊
- 初筛红旗
- 线上问诊可行性判断

### `intake-agent`
负责：
- 执行当前推荐问题
- 理解患者自然语言回答
- 归一化症状表述
- 更新问诊事实

### `safety-agent`
负责：
- 复核风险
- 特殊人群禁忌判断
- 停止继续问诊的建议
- 触发线下或人工审核建议

## 7.3 图谱推理为什么先不做成独立 agent
第一阶段建议把 `graph-reasoner` 作为：
- service
- repository
- tool 组合能力

而不是直接做成 prompt 型 agent。

原因是它更适合：
- 结构化输入输出
- 稳定逻辑
- 可追踪结果
- 明确规则治理

后续若复杂度上升，再考虑升级成独立子代理。

---

## 8. API 层设计建议

第一阶段建议至少有以下接口：

## 8.1 健康检查
- `GET /health`

## 8.2 创建病例
- `POST /cases`

## 8.3 获取病例详情
- `GET /cases/{case_id}`

## 8.4 发送用户消息
- `POST /cases/{case_id}/messages`

这个接口应触发：
- supervisor 调度
- triage/intake/safety 流程
- 图谱推理
- 结构化状态更新

## 8.5 获取问诊轨迹
- `GET /cases/{case_id}/trace`

用于内部调试与审计查看。

## 8.6 获取候选与证据
- `GET /cases/{case_id}/reasoning`

用于医生端或后台查看。

---

## 9. `uv` 初始化方案

## 9.1 初始化原则
整个项目以 `pyproject.toml` 为中心。

建议采用 `src` 布局，原因：
- 避免导入混乱
- 更适合包化管理
- 便于测试和部署

## 9.2 依赖分组建议

### 核心依赖
- `deepagents`
- `pydantic`
- `neo4j`
- `fastapi`
- `uvicorn`

### 模型与图谱周边
- `langchain`
- `langgraph`
- 可能需要的 provider SDK

### 开发依赖
- `pytest`
- `pytest-asyncio`
- `ruff`
- `mypy`
- `httpx`

### 可选依赖
- `python-dotenv`
- `orjson`
- `tenacity`

## 9.3 运行脚本建议
建议在 `pyproject.toml` 中定义常用脚本，例如：
- 启动 API
- 运行测试
- 初始化图谱数据
- 本地开发启动

---

## 10. 配置管理建议

建议维护 `.env.example`，至少包含：

- `APP_ENV`
- `LOG_LEVEL`
- `OPENAI_API_KEY` 或其他模型密钥
- `MODEL_NAME`
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `API_HOST`
- `API_PORT`

原则：
- 密钥绝不写入仓库
- 所有配置由环境变量注入
- 配置读取集中化，不在业务代码中直接散读

---

## 11. 测试策略

第一阶段不要等到功能写完再补测试。

## 11.1 单元测试优先覆盖
- `CaseState` 状态流转
- 图谱候选生成
- 区分性问题选择
- 风险规则判断
- 工具层输入输出

## 11.2 集成测试优先覆盖
- 创建病例到首次问诊
- 红旗命中后中断流程
- 图谱建议问题与状态更新闭环
- API 调用到结构化结果返回

## 11.3 暂不追求
- 完整端到端大而全自动化
- 复杂 UI 自动化

---

## 12. 日志与审计建议

医疗相关系统必须重视审计。

建议至少记录：
- 用户输入摘要
- agent 调度记录
- 工具调用记录
- 图谱查询摘要
- 风险判断结果
- 问题推荐依据
- 病例状态变更记录

建议日志分层：
- 应用日志
- 审计日志
- 调试日志

---

## 13. 第一阶段开发顺序

建议按下面顺序推进：

### Step 1：初始化项目
- 建立 `uv` 项目
- 建立 `pyproject.toml`
- 建立 `src` 布局
- 建立基础依赖与配置

### Step 2：定义 schema
- `CaseState`
- 问诊输入输出
- 风险输出
- 图谱候选输出
- 问题推荐输出

### Step 3：实现 Neo4j 基础访问层
- 连接管理
- 节点检索
- 候选查询
- 问题推荐最小逻辑

### Step 4：实现核心 services
- triage
- intake normalization
- graph reasoning
- safety

### Step 5：实现 tools
- case tools
- graph tools
- safety tools
- summary tools

### Step 6：组装 deepagents
- supervisor
- subagents
- tools
- interrupt 节点

### Step 7：提供 API
- 建病例
- 发消息
- 获取状态
- 获取推理轨迹

### Step 8：接 UI
- 先接患者视图
- 再接内部视图

---

## 14. 第一阶段最小落地版本

如果只做一个真正能跑起来的 MVP，建议最小闭环如下：

1. 患者输入主诉
2. 创建病例
3. `triage-agent` 做初筛
4. 图谱服务生成候选与下一问
5. `intake-agent` 发问并解析回答
6. 更新病例状态
7. `safety-agent` 复核
8. 返回患者可见问题或阶段性总结
9. 后台可查看候选与证据摘要

这个闭环已经足够验证：
- 工程骨架是否合理
- 图谱是否真的能驱动追问
- `deepagents` 是否适合当前编排模式
- 状态模型是否可持续扩展

---

## 15. 后续扩展位

本骨架设计应当允许第二阶段平滑扩展：

### 第二阶段新增
- `pattern-agent`
- `plan-agent`
- 更细的图谱问题类型
- 更丰富的证据路径
- 医生侧分析视图

### 第三阶段新增
- `prescription-agent`
- 人工审核流
- 随访模块
- 更复杂的特殊人群安全治理

---

## 16. 当前工程结论

一句话总结：

本项目第一阶段应采用“`uv` 管理工程、`deepagents` 负责编排、`Neo4j` 负责医学图谱推理、`deep-agents-ui` 负责交互承载”的模块化骨架；通过 `schemas + state + graph + services + tools + agents + api` 的分层结构，把问诊系统做成一个可扩展、可审计、可解释的收敛式工程系统，而不是一个单一的大模型聊天应用。

---

## 17. 下一步落地建议

在本文件基础上，下一步建议立即推进三项工作：

1. 创建 `pyproject.toml` 并完成 `uv` 初始化
2. 创建 `src/tcm_agent/schemas/` 与 `src/tcm_agent/graph/` 最小模块
3. 基于 `deepagents` 搭出 `clinical-supervisor` + `triage-agent` + `intake-agent` + `safety-agent` 的最小骨架

这样项目就会从“设计阶段”正式进入“可开发阶段”。