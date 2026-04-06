# Tool Contracts 设计文档 v1

## 1. 文档目标

本文档定义 TCMAgent 第一阶段的工具接口契约，重点解决以下问题：

1. 哪些能力必须做成工具，而不是只放在 prompt 中
2. 每个工具的职责边界是什么
3. 每个工具的输入输出结构应该如何设计
4. 工具如何与 `case_state`、Neo4j 图谱、风控逻辑协同
5. 哪些工具需要支持人工审核、中断或审计

本文档默认面向第一阶段 MVP，重点覆盖：

- 病例状态工具
- 图谱推理工具
- 风险治理工具
- 总结与归档工具

---

## 2. 总体设计原则

### 2.1 工具负责“可控动作”，Agent 负责“自然交互”
工具适合承载：

- 状态读写
- 结构化推理
- 风险判断
- 图谱查询
- 审计记录
- 输出归档

Agent 适合承载：

- 自然语言理解
- 对患者提问
- 总结解释
- 面向用户的表达优化

---

### 2.2 工具必须结构化输入、结构化输出
不要让工具返回大段模糊自然语言。  
推荐返回：

- 明确字段
- 明确状态
- 明确置信度
- 明确建议动作
- 明确证据链引用

---

### 2.3 工具边界要小而清晰
每个工具应只做一件事，不要把多个职责打包成“大一统工具”。

例如不要设计：

- `do_full_consultation`

而应拆成：

- `create_case`
- `get_case_state`
- `query_graph_candidates`
- `find_discriminative_questions`
- `screen_red_flags`
- `issue_risk_decision`

---

### 2.4 高风险动作必须显式工具化
凡是可能带来安全、合规、审核风险的动作，都不应靠模型直接输出。

例如：

- 风险升级建议
- 转线下建议
- 处方草案
- 归档写入
- 临床审核提交

都必须通过工具触发。

---

### 2.5 工具返回结果必须可审计
每个关键工具的输出，建议都附带：

- `decision_id`
- `trace_id`
- `evidence_refs`
- `timestamp`
- `tool_version`

便于后续复盘与质检。

---

## 3. 工具分层

推荐把工具分成四类：

1. **病例状态工具**
2. **图谱推理工具**
3. **风险治理工具**
4. **总结与归档工具**

---

## 4. 通用契约规范

---

## 4.1 通用输入字段建议

很多工具会共享以下字段：

- `case_id`: 当前病例唯一标识
- `actor`: 调用主体，如 `clinical-supervisor` / `intake-agent`
- `request_id`: 当前请求 ID
- `trace_id`: 当前链路追踪 ID

---

## 4.2 通用输出字段建议

关键工具建议统一包含：

- `success: bool`
- `message: str`
- `trace_id: str`
- `tool_name: str`
- `tool_version: str`
- `timestamp: str`

如涉及决策，还建议包含：

- `decision_id: str | null`
- `evidence_refs: list[str]`
- `warnings: list[str]`

---

## 4.3 时间与 ID 规范

建议：

- 时间统一使用 ISO 8601 / RFC 3339
- 所有主对象使用稳定字符串 ID
- 证据引用使用统一格式，例如：
  - `symptom:fever`
  - `pattern:wind-cold`
  - `question:q-cold-heat-01`
  - `redflag:chest-pain`

---

## 5. 病例状态工具

这类工具负责驱动 `case_state`，是整个系统的流程底盘。

---

## 5.1 `create_case`

### 职责
创建新病例，并初始化基础状态。

### 使用时机
- 患者首次进入问诊流程
- 新建一次独立问诊会话

### 输入 Schema
- `patient_profile: PatientProfileInput | null`
- `visit_type: str`
- `channel: str`
- `chief_complaint: str | null`
- `source: str | null`

### 输出 Schema
- `case_id: str`
- `case_stage: str`
- `created_at: str`
- `initialized_fields: list[str]`

### 注意事项
- 不负责复杂判断
- 不负责图谱推理
- 只做初始化与基础字段落盘

---

## 5.2 `get_case_state`

### 职责
读取当前病例完整结构化状态。

### 使用时机
- supervisor 决策下一步
- 子代理进入前读取上下文
- UI 获取当前状态

### 输入 Schema
- `case_id: str`

### 输出 Schema
- `case_state: CaseState`

### 注意事项
- 这是高频工具
- 输出必须稳定、完整、可直接供后续工具消费

---

## 5.3 `update_case_facts`

### 职责
更新病例中的结构化事实。

### 使用时机
- 用户回答被归一化后
- 工具从图谱/风控中得到新的结构化事实后

### 输入 Schema
- `case_id: str`
- `facts: list[NormalizedFactInput]`
- `source: str`
- `overwrite_strategy: str`

### 输出 Schema
- `updated_fields: list[str]`
- `contradictions: list[ContradictionItem]`
- `case_stage: str`

### 注意事项
- 不应直接接受原始自然语言
- 应接受已经归一化后的事实对象
- 应能够标记冲突而不是粗暴覆盖

---

## 5.4 `record_question_asked`

### 职责
记录某个问题已被提问，用于避免重复追问，并支持审计。

### 使用时机
- `intake-agent` 正式向患者发问后

### 输入 Schema
- `case_id: str`
- `question_id: str`
- `question_text: str`
- `rationale: str | null`
- `question_type: str`

### 输出 Schema
- `question_record_id: str`
- `asked_count: int`

---

## 5.5 `append_case_evidence`

### 职责
向病例中追加结构化证据条目。

### 使用时机
- 图谱推理后
- 风险判定后
- 归纳总结前

### 输入 Schema
- `case_id: str`
- `evidence_items: list[EvidenceItemInput]`

### 输出 Schema
- `appended_count: int`

---

## 5.6 `set_case_stage`

### 职责
更新病例流程阶段。

### 使用时机
- 导诊结束
- 进入动态追问
- 命中高风险中断
- 问诊总结完成

### 输入 Schema
- `case_id: str`
- `new_stage: str`
- `reason: str`

### 输出 Schema
- `previous_stage: str`
- `current_stage: str`

### 注意事项
- 应校验状态是否合法流转
- 不允许任意跳跃式更新

---

## 5.7 `lock_case_stage`

### 职责
锁定某阶段，防止后续错误覆盖或越权推进。

### 使用时机
- 高风险命中后
- 提交人工审核后
- 某阶段已完成且必须冻结时

### 输入 Schema
- `case_id: str`
- `stage: str`
- `reason: str`

### 输出 Schema
- `locked: bool`

---

## 6. 图谱推理工具

这是 TCMAgent 的核心工具域，用于实现“图谱驱动动态追问”。

---

## 6.1 `query_graph_candidates`

### 职责
根据当前病例事实生成候选疾病、证型、病机集合。

### 使用时机
- 主诉首次进入系统后
- 新事实更新后需要重新评估候选时

### 输入 Schema
- `case_id: str`
- `facts: list[NormalizedFactInput]`
- `population_tags: list[str]`
- `limit: int`

### 输出 Schema
- `candidate_diseases: list[CandidateItem]`
- `candidate_patterns: list[CandidateItem]`
- `candidate_pathogenesis: list[CandidateItem]`
- `matched_facts: list[str]`
- `missing_high_value_facts: list[str]`

### 注意事项
- 不生成患者可见结论
- 只做候选空间生成
- 输出要支持后续排序和解释

---

## 6.2 `find_discriminative_questions`

### 职责
在当前候选空间下，选择最有区分价值的下一问。

### 使用时机
- 动态追问循环中每一轮
- 候选变化后需要重新选题时

### 输入 Schema
- `case_id: str`
- `candidate_patterns: list[CandidateItem]`
- `candidate_diseases: list[CandidateItem]`
- `already_asked_question_ids: list[str]`
- `population_tags: list[str]`
- `max_questions: int`

### 输出 Schema
- `recommended_questions: list[QuestionRecommendation]`
- `selection_reason: str`
- `question_strategy: str`

### `QuestionRecommendation` 建议字段
- `question_id: str`
- `question_text: str`
- `goal: str`
- `discriminates_between: list[str]`
- `target_domain: str | null`
- `priority: float`
- `safety_related: bool`
- `fatigue_cost: float`

### 注意事项
- 必须过滤已问问题
- 必须考虑特殊人群与风险优先级
- 输出不能只是字符串数组

---

## 6.3 `explain_question_rationale`

### 职责
解释某个问题为什么会被选中。

### 使用时机
- 内部审核视图
- 医生端查看
- 调试与审计

### 输入 Schema
- `question_id: str`
- `candidate_context: CandidateContextInput`

### 输出 Schema
- `rationale: str`
- `supports_targets: list[str]`
- `conflicts_targets: list[str]`
- `evidence_refs: list[str]`

---

## 6.4 `build_evidence_path`

### 职责
构建从“已知事实”到“候选判断/风险结论”的证据路径。

### 使用时机
- 输出内部总结前
- 风险决策后
- 审计导出时

### 输入 Schema
- `case_id: str`
- `target_ids: list[str]`
- `target_type: str`

### 输出 Schema
- `paths: list[EvidencePath]`

### `EvidencePath` 建议字段
- `target_id: str`
- `path_nodes: list[EvidenceNodeRef]`
- `path_edges: list[EvidenceEdgeRef]`
- `summary: str`

---

## 6.5 `rank_candidate_hypotheses`

### 职责
对候选进行重新排序，并输出支持证据、冲突证据和不确定性。

### 使用时机
- 用户新回答进入后
- 追问阶段每轮迭代后

### 输入 Schema
- `case_id: str`
- `facts: list[NormalizedFactInput]`
- `candidate_ids: list[str]`
- `candidate_type: str`

### 输出 Schema
- `ranked_candidates: list[CandidateAssessment]`
- `convergence_score: float`
- `uncertainty_notes: list[str]`

### `CandidateAssessment` 建议字段
- `candidate_id: str`
- `score: float`
- `supporting_evidence: list[str]`
- `conflicting_evidence: list[str]`
- `confidence: float`

---

## 6.6 `update_graph_evidence_projection`

### 职责
将病例中的最新事实映射为图谱视角下的证据投影结果。

### 使用时机
- 更新病例事实后
- 为下一轮图谱推理做准备时

### 输入 Schema
- `case_id: str`
- `facts: list[NormalizedFactInput]`

### 输出 Schema
- `projection_refs: list[str]`
- `updated_domains: list[str]`

---

## 7. 风险治理工具

风险工具必须独立存在，不能散落在 prompt 中。

---

## 7.1 `screen_red_flags`

### 职责
检查当前病例是否命中红旗征象。

### 使用时机
- 初次导诊
- 动态追问中关键节点
- 输出总结前

### 输入 Schema
- `case_id: str`
- `facts: list[NormalizedFactInput]`
- `population_tags: list[str]`

### 输出 Schema
- `matched_red_flags: list[MatchedRedFlag]`
- `risk_level: str`
- `requires_immediate_action: bool`

### `MatchedRedFlag` 建议字段
- `red_flag_id: str`
- `name: str`
- `severity: str`
- `evidence_refs: list[str]`
- `recommended_route: str`

---

## 7.2 `check_special_population_risks`

### 职责
对孕妇、儿童、高龄、慢病、多药联用等特殊人群做风险增强判断。

### 使用时机
- 导诊后
- 风险复核前
- 高风险建议前

### 输入 Schema
- `case_id: str`
- `population_tags: list[str]`
- `facts: list[NormalizedFactInput]`

### 输出 Schema
- `risk_adjustments: list[PopulationRiskAdjustment]`
- `warnings: list[str]`

---

## 7.3 `check_contraindications`

### 职责
检查当前状态下是否存在禁忌或不宜继续线上处理的情形。

### 使用时机
- 风险复核时
- 后续如果涉及建议/方案生成前

### 输入 Schema
- `case_id: str`
- `facts: list[NormalizedFactInput]`
- `population_tags: list[str]`
- `candidate_ids: list[str]`

### 输出 Schema
- `contraindication_flags: list[ContraindicationFlag]`
- `requires_human_review: bool`
- `requires_offline_visit: bool`

---

## 7.4 `issue_risk_decision`

### 职责
综合红旗、特殊人群、禁忌与阶段状态，输出正式风险决策。

### 使用时机
- 导诊结束后
- 动态追问循环的关键节点
- 问诊总结前

### 输入 Schema
- `case_id: str`
- `red_flags: list[MatchedRedFlag]`
- `contraindication_flags: list[ContraindicationFlag]`
- `population_risks: list[PopulationRiskAdjustment]`
- `current_stage: str`

### 输出 Schema
- `decision_id: str`
- `risk_level: str`
- `safe_to_continue: bool`
- `recommend_offline_visit: bool`
- `recommend_human_review: bool`
- `recommended_route: str | null`
- `decision_reason: str`
- `evidence_refs: list[str]`

### 注意事项
- 这是关键决策工具
- 输出结果应能直接驱动 supervisor 分支
- 建议支持人工审核挂钩

---

## 8. 总结与归档工具

这类工具负责输出面向不同对象的结果，并保留结构化轨迹。

---

## 8.1 `summarize_case_for_patient`

### 职责
生成患者可见的阶段性总结。

### 使用时机
- 一轮问诊结束后
- 需要对患者解释当前情况时
- 停止追问时

### 输入 Schema
- `case_id: str`
- `case_state: CaseState`
- `risk_decision: RiskDecisionOutput | null`

### 输出 Schema
- `summary_text: str`
- `next_step_hint: str | null`
- `safety_notice: str | null`

### 注意事项
- 输出必须保守
- 不应直接暴露内部候选排序细节
- 不应输出强诊断结论

---

## 8.2 `summarize_case_for_clinician`

### 职责
生成内部可见的结构化问诊总结。

### 使用时机
- 阶段结束
- 医生复核
- 人工审核前

### 输入 Schema
- `case_id: str`
- `case_state: CaseState`

### 输出 Schema
- `structured_summary: ClinicianSummary`

### `ClinicianSummary` 建议字段
- `chief_complaint`
- `normalized_facts`
- `candidate_patterns`
- `candidate_diseases`
- `supporting_evidence`
- `conflicting_evidence`
- `red_flags`
- `risk_level`
- `missing_critical_facts`
- `next_recommended_actions`

---

## 8.3 `save_consultation_record`

### 职责
将当前问诊结果写入正式存储。

### 使用时机
- 阶段性归档
- 问诊结束
- 审核完成后

### 输入 Schema
- `case_id: str`
- `record_type: str`
- `payload: dict`
- `operator: str`

### 输出 Schema
- `record_id: str`
- `saved_at: str`

### 注意事项
- 建议作为中断候选工具
- 高风险记录写入前可挂审核

---

## 8.4 `export_reasoning_trace`

### 职责
导出病例的推理轨迹、证据链和工具调用摘要。

### 使用时机
- 审计
- 质检
- 调试
- 模型效果分析

### 输入 Schema
- `case_id: str`
- `include_messages: bool`
- `include_tool_traces: bool`
- `include_evidence_paths: bool`

### 输出 Schema
- `trace_export: ReasoningTraceExport`

---

## 9. 核心 Schema 草案

下面给出推荐的结构化对象草案。

---

## 9.1 `PatientProfileInput`

字段建议：

- `name: str | null`
- `age: int | null`
- `gender: str | null`
- `is_pregnant: bool | null`
- `known_conditions: list[str]`
- `current_medications: list[str]`
- `allergies: list[str]`

---

## 9.2 `NormalizedFactInput`

字段建议：

- `fact_id: str`
- `fact_type: str`
- `normalized_key: str`
- `normalized_value: str | bool | int | float | list[str]`
- `source_text: str | null`
- `confidence: float`
- `source_turn_id: str | null`

示例：

- `fact_type = symptom`
- `normalized_key = fever`
- `normalized_value = true`

---

## 9.3 `CandidateItem`

字段建议：

- `candidate_id: str`
- `name: str`
- `score: float`
- `confidence: float`
- `category: str | null`
- `evidence_refs: list[str]`

---

## 9.4 `ContradictionItem`

字段建议：

- `field: str`
- `previous_value: str | null`
- `new_value: str | null`
- `reason: str`

---

## 9.5 `EvidenceItemInput`

字段建议：

- `target_id: str`
- `target_type: str`
- `evidence_type: str`
- `evidence_refs: list[str]`
- `summary: str`
- `weight: float | null`

---

## 9.6 `PopulationRiskAdjustment`

字段建议：

- `population_tag: str`
- `risk_delta: float`
- `reason: str`
- `evidence_refs: list[str]`

---

## 9.7 `ContraindicationFlag`

字段建议：

- `contraindication_id: str`
- `name: str`
- `severity: str`
- `reason: str`
- `evidence_refs: list[str]`

---

## 9.8 `RiskDecisionOutput`

字段建议：

- `decision_id: str`
- `risk_level: str`
- `safe_to_continue: bool`
- `recommend_offline_visit: bool`
- `recommend_human_review: bool`
- `recommended_route: str | null`
- `decision_reason: str`
- `evidence_refs: list[str]`

---

## 9.9 `QuestionRecommendation`

字段建议：

- `question_id: str`
- `question_text: str`
- `goal: str`
- `discriminates_between: list[str]`
- `target_domain: str | null`
- `priority: float`
- `safety_related: bool`
- `fatigue_cost: float`

---

## 9.10 `CaseState`

字段建议：

- `case_id: str`
- `patient_profile: dict | null`
- `visit_type: str`
- `channel: str`
- `chief_complaint: str | null`
- `normalized_facts: list[NormalizedFactInput]`
- `asked_questions: list[str]`
- `candidate_diseases: list[CandidateItem]`
- `candidate_patterns: list[CandidateItem]`
- `candidate_pathogenesis: list[CandidateItem]`
- `red_flags: list[MatchedRedFlag]`
- `risk_level: str | null`
- `safe_to_continue: bool | null`
- `recommended_next_question: QuestionRecommendation | null`
- `question_rationale: str | null`
- `intake_completeness_score: float`
- `convergence_score: float`
- `case_stage: str`
- `audit_log: list[dict]`

---

## 10. 推荐工具清单总表

| 工具名 | 类别 | 是否 MVP 必需 | 是否高风险 |
|---|---|---:|---:|
| `create_case` | 病例状态 | 是 | 否 |
| `get_case_state` | 病例状态 | 是 | 否 |
| `update_case_facts` | 病例状态 | 是 | 否 |
| `record_question_asked` | 病例状态 | 是 | 否 |
| `append_case_evidence` | 病例状态 | 是 | 否 |
| `set_case_stage` | 病例状态 | 是 | 否 |
| `lock_case_stage` | 病例状态 | 可选 | 否 |
| `query_graph_candidates` | 图谱推理 | 是 | 否 |
| `find_discriminative_questions` | 图谱推理 | 是 | 否 |
| `explain_question_rationale` | 图谱推理 | 可选 | 否 |
| `build_evidence_path` | 图谱推理 | 是 | 否 |
| `rank_candidate_hypotheses` | 图谱推理 | 是 | 否 |
| `update_graph_evidence_projection` | 图谱推理 | 可选 | 否 |
| `screen_red_flags` | 风险治理 | 是 | 是 |
| `check_special_population_risks` | 风险治理 | 是 | 是 |
| `check_contraindications` | 风险治理 | 是 | 是 |
| `issue_risk_decision` | 风险治理 | 是 | 是 |
| `summarize_case_for_patient` | 总结归档 | 是 | 否 |
| `summarize_case_for_clinician` | 总结归档 | 是 | 否 |
| `save_consultation_record` | 总结归档 | 是 | 是 |
| `export_reasoning_trace` | 总结归档 | 可选 | 否 |

---

## 11. 哪些工具建议接人工审核

第一阶段建议把以下工具设计成可挂中断或人工审核的节点：

- `issue_risk_decision`
- `save_consultation_record`

后续如进入高风险能力，还应扩展到：

- 处方草案相关工具
- 高风险建议相关工具
- 转诊正式下发相关工具

---

## 12. 工具与 Agent 的推荐分配

---

## 12.1 `clinical-supervisor`
建议可调用：

- `get_case_state`
- `set_case_stage`
- `query_graph_candidates`
- `find_discriminative_questions`
- `issue_risk_decision`
- `summarize_case_for_patient`

---

## 12.2 `triage-agent`
建议可调用：

- `get_case_state`
- `update_case_facts`
- `screen_red_flags`
- `check_special_population_risks`
- `issue_risk_decision`

---

## 12.3 `intake-agent`
建议可调用：

- `get_case_state`
- `record_question_asked`
- `update_case_facts`
- `query_graph_candidates`
- `find_discriminative_questions`
- `append_case_evidence`

---

## 12.4 `safety-agent`
建议可调用：

- `get_case_state`
- `screen_red_flags`
- `check_special_population_risks`
- `check_contraindications`
- `issue_risk_decision`
- `build_evidence_path`

---

## 13. 第一阶段最小闭环工具组合

如果只做一个最小可跑通版本，建议先实现这 10 个：

1. `create_case`
2. `get_case_state`
3. `update_case_facts`
4. `record_question_asked`
5. `query_graph_candidates`
6. `find_discriminative_questions`
7. `screen_red_flags`
8. `check_special_population_risks`
9. `issue_risk_decision`
10. `summarize_case_for_patient`

这 10 个工具已经足够支撑：

- 建档
- 初筛
- 动态追问
- 风险判断
- 阶段性输出

---

## 14. 当前结论

TCMAgent 的工具体系应坚持以下原则：

- 用工具管理状态，而不是靠聊天历史硬推
- 用工具承载风险治理，而不是把安全逻辑散在 prompt 里
- 用工具查询图谱与选择下一问，而不是让模型自由发散
- 用工具输出结构化结果，为审计、复盘和医生协作提供基础

一句话总结：

> **TCMAgent 的工具不是“给模型补能力”，而是“把问诊流程、图谱推理与风险治理工程化”的核心基础设施。**