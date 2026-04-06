# Neo4j 医学知识图谱 Schema 草案 v1

## 1. 文档目标

本文档定义“收敛式中医问诊系统”的 `Neo4j` 图谱建模方案，用于支持以下核心能力：

- 基于主诉生成初始候选集合
- 基于医学关系选择“下一问”
- 基于回答更新候选证据与收敛状态
- 对风险路径进行优先拦截
- 对问诊过程提供可解释的证据链
- 为 `deepagents` 编排层提供稳定、结构化的图谱查询接口

本文档重点不是“把所有医学知识都塞进图数据库”，而是设计一套适合 **问诊收敛、风险治理、证据追踪** 的知识图谱骨架。

---

## 2. 设计原则

### 2.1 以“问诊决策支持”为目标，而不是百科式知识存储
图谱中的节点与关系，应该优先服务于：

- 候选疾病/证型/病机生成
- 问题区分度计算
- 红旗识别
- 证据支持与冲突判断

而不是简单堆砌概念定义。

### 2.2 区分“医学实体”与“问诊控制实体”
本图谱既包含医学知识，也包含问诊流程要素：

- 医学实体：疾病、证型、病机、症状、体征、观察项
- 控制实体：问题、风险规则、问诊阶段、转诊路径

### 2.3 支持不确定性与多候选并存
问诊过程中往往不是单一结论，而是多个候选并存。图谱必须允许：

- 一个症状支持多个候选
- 一个问题区分多个候选
- 一个事实同时支持 A、削弱 B
- 候选之间存在层级与并列关系

### 2.4 风险链路必须独立建模
红旗症状、特殊人群、禁忌项、升级路径不能只作为普通标签存在，应形成独立图谱结构，便于：

- 快速命中
- 高优先级查询
- 可审计的风险判定

### 2.5 问题节点要可计算“区分价值”
问题不是普通文案，而应带有结构化属性，支持：

- 区分哪些候选
- 适用哪个阶段
- 是否安全必问
- 预期回答类型
- 对候选收敛的影响

---

## 3. 图谱总体分层

建议将图谱逻辑分为五个子域：

### 3.1 医学知识域
- `Disease`
- `Pattern`
- `Pathogenesis`
- `Symptom`
- `Sign`
- `Observation`

### 3.2 问诊控制域
- `Question`
- `QuestionGroup`
- `VisitRoute`
- `ConsultStage`

### 3.3 风险治理域
- `RedFlag`
- `PopulationTag`
- `Contraindication`
- `RiskDecision`

### 3.4 证据解释域
- `EvidenceRule`
- `EvidenceEdge`
- `ConflictRule`
- `UncertaintyMarker`

### 3.5 数据映射域
- `Synonym`
- `NormalizationRule`
- `ExtractionPattern`

---

## 4. 核心节点设计

---

## 4.1 `Disease`

### 定位
西医疾病或临床问题空间中的疾病候选，用于导诊、风险识别、转诊与病种归类。

### 关键属性
- `id`: 全局唯一 ID
- `name`: 标准名称
- `alias`: 别名列表
- `category`: 疾病分类
- `severity_level`: 严重程度分级
- `description`: 简述
- `is_high_risk`: 是否高风险
- `online_consultable`: 是否适合线上初步问诊
- `source_refs`: 来源文献/指南引用
- `status`: `active` / `draft` / `deprecated`

### 示例
- 感冒
- 偏头痛
- 月经不调
- 急性腹痛
- 胸痹相关疾病候选

---

## 4.2 `Pattern`

### 定位
中医证型节点，是问诊收敛中的核心候选之一。

### 关键属性
- `id`
- `name`
- `alias`
- `category`: 证型类别
- `description`
- `typicality_score`: 典型性基础权重
- `applicable_population`
- `source_refs`
- `status`

### 示例
- 风寒束表
- 风热犯表
- 肝郁气滞
- 脾胃虚寒
- 痰湿内阻
- 肝火上炎

---

## 4.3 `Pathogenesis`

### 定位
病机节点，用于解释证型形成机制，也可用于提升可解释性和追问方向。

### 关键属性
- `id`
- `name`
- `alias`
- `description`
- `level`: 病机层级
- `source_refs`
- `status`

### 示例
- 外感风寒
- 气滞
- 血瘀
- 痰湿阻滞
- 阴虚火旺
- 脾失健运

---

## 4.4 `Symptom`

### 定位
患者主观症状节点，是问诊中最常见的输入事实类型。

### 关键属性
- `id`
- `name`
- `alias`
- `body_system`
- `symptom_type`
- `polarity`: 正向/反向症状
- `severity_scale_supported`: 是否支持严重程度刻画
- `duration_supported`: 是否支持病程刻画
- `source_refs`
- `status`

### 示例
- 发热
- 恶寒
- 头痛
- 胸闷
- 咳嗽
- 腹痛
- 口渴
- 失眠

---

## 4.5 `Sign`

### 定位
偏客观体征，通常来自医生观察、患者测量结果或可视化输入。

### 关键属性
- `id`
- `name`
- `alias`
- `measurement_type`
- `normal_range`
- `status`

### 示例
- 体温升高
- 脉弦
- 面色萎黄
- 舌质红
- 舌苔白腻

---

## 4.6 `Observation`

### 定位
中医四诊或结构化观察维度的抽象节点，用于连接问题、症状、证型和病机。

### 关键属性
- `id`
- `name`
- `domain`: `tongue` / `pulse` / `sleep` / `stool` / `urine` / `cold_heat` 等
- `data_type`: `enum` / `boolean` / `text` / `number`
- `allowed_values`
- `status`

### 示例
- 寒热
- 出汗
- 饮水偏好
- 食欲
- 睡眠质量
- 大便性状
- 小便颜色
- 舌苔厚薄
- 舌质颜色

---

## 4.7 `Question`

### 定位
问诊问题节点，是“下一问”机制的核心实体。

### 关键属性
- `id`
- `title`: 问题标准标题
- `prompt_template`: 推荐提问模板
- `question_type`: `boolean` / `single_choice` / `multi_choice` / `scale` / `free_text`
- `stage`: 适用阶段
- `priority`: 默认优先级
- `is_required_safety`: 是否安全必问
- `is_dynamic`: 是否动态问题
- `target_domain`: 目标观察域或症状域
- `expected_answer_schema`
- `stop_condition_impact`: 对停止追问判断的影响
- `source_refs`
- `status`

### 示例
- “有没有胸痛或呼吸困难？”
- “发热时更怕冷还是更怕热？”
- “口渴明显吗？更想喝热水还是冷水？”
- “大便偏稀、偏干还是正常？”

---

## 4.8 `QuestionGroup`

### 定位
问题组节点，用于按主题或场景组织问题。

### 关键属性
- `id`
- `name`
- `group_type`
- `description`
- `stage`
- `status`

### 示例
- 红旗筛查
- 头痛问诊组
- 咳嗽问诊组
- 寒热汗问诊组
- 舌象采集组
- 妇科专项组

---

## 4.9 `RedFlag`

### 定位
高风险信号节点，用于触发中断、转人工、转线下。

### 关键属性
- `id`
- `name`
- `description`
- `urgency_level`: `high` / `critical`
- `recommended_action`
- `source_refs`
- `status`

### 示例
- 持续胸痛
- 呼吸困难
- 神志异常
- 抽搐
- 黑便/呕血
- 高热不退
- 突发剧烈头痛

---

## 4.10 `PopulationTag`

### 定位
特殊人群标签，用于风险调整和分流。

### 关键属性
- `id`
- `name`
- `description`
- `risk_multiplier`
- `status`

### 示例
- 孕妇
- 儿童
- 高龄
- 慢病患者
- 免疫低下
- 多药联用人群

---

## 4.11 `Contraindication`

### 定位
禁忌或需要额外警惕的条件节点。

### 关键属性
- `id`
- `name`
- `description`
- `contra_type`: `drug` / `procedure` / `advice` / `route`
- `severity`
- `status`

### 示例
- 妊娠禁忌
- 特定病情禁针灸
- 出血倾向禁某些方案
- 高危症状不适宜继续线上观察

---

## 4.12 `VisitRoute`

### 定位
就诊路径/流程路由节点。

### 关键属性
- `id`
- `name`
- `description`
- `route_type`: `online_intake` / `offline_visit` / `er` / `human_review`
- `status`

### 示例
- 普通线上问诊
- 妇儿专线
- 立即线下就医
- 急诊建议
- 人工审核

---

## 4.13 `ConsultStage`

### 定位
问诊阶段节点，用于流程控制和问题可用性约束。

### 关键属性
- `id`
- `name`
- `description`
- `order`
- `status`

### 示例
- 建档
- 导诊
- 红旗筛查
- 初始收敛
- 动态追问
- 风险复核
- 总结输出

---

## 4.14 `EvidenceRule`

### 定位
结构化证据规则节点，用于表达“某事实如何影响某候选”。

### 关键属性
- `id`
- `name`
- `description`
- `rule_type`: `support` / `conflict` / `exclude` / `requires_more_info`
- `weight`
- `confidence`
- `source_refs`
- `status`

---

## 4.15 `Synonym`

### 定位
同义词/别称/口语映射节点，用于自然语言归一化。

### 关键属性
- `id`
- `text`
- `normalized_to`
- `lang`
- `source`
- `status`

### 示例
- “怕冷” -> 恶寒
- “肚子胀痛” -> 腹胀 / 腹痛
- “上火” -> 热象候选
- “睡不实” -> 睡眠不安稳

---

## 5. 核心关系设计

---

## 5.1 医学实体关系

### `(:Symptom)-[:SUGGESTS_DISEASE {weight, confidence}]->(:Disease)`
表示某症状提示某疾病候选。

### `(:Symptom)-[:SUPPORTS_PATTERN {weight, confidence}]->(:Pattern)`
表示某症状支持某证型。

### `(:Observation)-[:SUPPORTS_PATTERN {weight, confidence}]->(:Pattern)`
表示某观察项支持某证型。

### `(:Pattern)-[:RELATED_TO_PATHOGENESIS {weight}]->(:Pathogenesis)`
表示证型与病机之间的关联。

### `(:Disease)-[:MAY_PRESENT_AS]->(:Pattern)`
表示某疾病可能在中医辨证上呈现为某证型。

### `(:Pattern)-[:ASSOCIATED_WITH_SYMPTOM]->(:Symptom)`
表示某证型常见关联症状。

### `(:Pattern)-[:ASSOCIATED_WITH_SIGN]->(:Sign)`
表示某证型常见关联体征。

---

## 5.2 问题驱动关系

### `(:Question)-[:TARGETS_DOMAIN]->(:Observation)`
问题关注某观察维度。

### `(:Question)-[:ASKS_ABOUT]->(:Symptom)`
问题用于确认某症状。

### `(:Question)-[:DISCRIMINATES_BETWEEN {gain_hint}]->(:Pattern)`
问题对区分某证型有帮助。

### `(:Question)-[:DISCRIMINATES_DISEASE]->(:Disease)`
问题对区分某疾病候选有帮助。

### `(:Question)-[:BELONGS_TO]->(:QuestionGroup)`
问题属于某问题组。

### `(:Question)-[:AVAILABLE_IN_STAGE]->(:ConsultStage)`
问题在哪个阶段可用。

### `(:QuestionGroup)-[:PRIORITIZED_FOR]->(:VisitRoute)`
某问题组在特定问诊路径中优先使用。

---

## 5.3 风险治理关系

### `(:Symptom)-[:INDICATES_RED_FLAG {severity}]->(:RedFlag)`
某症状可触发红旗。

### `(:RedFlag)-[:REQUIRES_ROUTE]->(:VisitRoute)`
命中红旗后需要走某路径。

### `(:PopulationTag)-[:INCREASES_RISK_OF]->(:RedFlag)`
特殊人群增加某风险信号的重要性。

### `(:PopulationTag)-[:CONTRAINDICATED_FOR]->(:Contraindication)`
某类人群与某禁忌相关。

### `(:Contraindication)-[:REQUIRES_ROUTE]->(:VisitRoute)`
命中禁忌后建议对应路径。

### `(:Question)-[:REQUIRED_FOR_SAFETY]->(:RedFlag)`
某问题是识别该红旗的关键问题。

---

## 5.4 证据解释关系

### `(:EvidenceRule)-[:SUPPORTS]->(:Pattern|:Disease|:Pathogenesis)`
某规则支持某候选。

### `(:EvidenceRule)-[:TRIGGERED_BY]->(:Symptom|:Observation|:Sign)`
某规则由某事实触发。

### `(:EvidenceRule)-[:CONFLICTS_WITH]->(:Pattern|:Disease)`
某规则与候选冲突。

### `(:EvidenceRule)-[:NEEDS_QUESTION]->(:Question)`
要验证该规则需要问哪个问题。

---

## 5.5 归一化与映射关系

### `(:Synonym)-[:NORMALIZES_TO]->(:Symptom|:Observation|:PopulationTag)`
口语词汇映射到标准概念。

### `(:ExtractionPattern)-[:MAPS_TO]->(:Symptom|:Observation)`
抽取模板映射到结构化节点。

---

## 6. 关系属性建议

多数关系应支持以下属性：

- `weight`: 关联强度
- `confidence`: 证据置信度
- `evidence_level`: 证据等级
- `population_scope`: 适用人群
- `source_refs`: 来源引用
- `source_type`: 指南/教材/专家共识/内部规则
- `status`: 启用状态
- `notes`: 补充说明

---

## 7. “下一问”选择相关建模

这是本图谱最关键的设计部分。

---

## 7.1 问题为什么必须建成一等节点
如果问题只是字符串模板，就无法支持：

- 计算问题对候选区分的价值
- 管理问题在不同阶段的可用性
- 将问题与风险、候选、观察域建立稳定连接
- 为 UI 展示“为什么问这个问题”提供依据

因此 `Question` 必须是核心节点。

---

## 7.2 问题的最小结构

每个问题至少应表达：

- 问什么
- 适合哪个阶段问
- 是安全必问还是动态候选问题
- 主要区分哪些候选
- 对应哪个观察域
- 预期答案类型
- 关联哪些风险或证据规则

---

## 7.3 建议新增问题相关属性
- `information_gain_hint`: 理论区分度提示
- `fatigue_cost`: 用户认知负担估计
- `safety_priority`: 安全优先级
- `clinical_priority`: 临床优先级
- `repeatable`: 是否可重复确认
- `requires_context`: 是否需要前置条件
- `requires_population_scope`: 是否仅在某类人群下启用

---

## 7.4 下一问选择建议逻辑
系统选择问题时，不应只看一个维度，而应综合：

- 风险优先级
- 当前候选分歧度
- 问题区分度
- 用户疲劳成本
- 阶段合法性
- 特殊人群适用性
- 是否已问过
- 是否能直接影响停止追问判断

可抽象成一个综合评分：

`question_score = safety_priority + discrimination_gain + convergence_gain - fatigue_cost - repetition_penalty`

具体算法可在服务层实现，图谱负责提供结构化依据。

---

## 8. 证据链建模建议

---

## 8.1 为什么要显式建证据链
问诊系统必须能够回答：

- 为什么现在怀疑 A 而不是 B？
- 为什么问了这道题？
- 用户的哪个回答改变了候选排序？
- 为什么现在建议线下？

这要求图谱支持从“事实”走到“候选”和“决策”的可追踪路径。

---

## 8.2 建议的证据路径模式

### 症状支持路径
`用户回答 -> Symptom -> SUPPORTS_PATTERN -> Pattern`

### 观察支持路径
`用户回答 -> Observation -> SUPPORTS_PATTERN -> Pattern`

### 风险路径
`用户回答 -> Symptom -> INDICATES_RED_FLAG -> RedFlag -> REQUIRES_ROUTE -> VisitRoute`

### 问题动机路径
`Question -> DISCRIMINATES_BETWEEN -> Pattern`
或
`Question -> REQUIRED_FOR_SAFETY -> RedFlag`

---

## 8.3 冲突证据
建议通过 `EvidenceRule` 或关系属性表达冲突：

- 某事实支持 A 但削弱 B
- 某回答与典型证型不一致
- 某观察与当前主候选冲突

可采用：
- `(:EvidenceRule)-[:CONFLICTS_WITH]->(:Pattern)`
- 关系属性 `polarity = negative`

---

## 9. 风险治理建模建议

---

## 9.1 红旗不是普通症状集合
红旗应作为独立节点组织，原因：

- 一个红旗可能由多个症状组合触发
- 一个症状在不同人群中的风险等级不同
- 红旗最终需要映射到明确动作

### 例如
- 胸痛 + 呼吸困难 + 高龄 -> 高优先级心肺风险路径
- 持续高热 + 儿童 -> 快速升级路径

---

## 9.2 风险动作映射
建议使用 `VisitRoute` 承载动作结果：

- `offline_visit`
- `emergency_visit`
- `human_review`
- `specialist_referral`

这样风控输出不会散落在文本里，而是结构化决策。

---

## 9.3 特殊人群增强
`PopulationTag` 与风险的关系不能只作为标签，建议支持：

- 增加红旗优先级
- 限制某些问题或建议
- 改变停止追问阈值
- 直接强制某些转诊路径

---

## 10. 数据归一化设计

---

## 10.1 为什么必须有归一化层
患者表达通常是口语化、模糊化、组合化的：

- “我有点上火”
- “就是怕冷还没劲”
- “晚上睡不好，心里也烦”
- “肚子不舒服老咕噜”

这些表达不能直接进入核心图谱，需要先归一化。

---

## 10.2 建议映射机制

### 文本层
原始对话文本保留在业务库中，不直接写入图谱主节点。

### 归一化层
将文本抽取为：
- `Symptom`
- `Observation`
- `PopulationTag`
- `RedFlag`
- `UncertaintyMarker`

### 置信度
每次映射都应带：
- `confidence`
- `source_span`
- `normalizer_version`

---

## 11. 是否把患者个案数据存进 Neo4j

建议区分两类数据：

### 11.1 适合放 Neo4j 的
- 医学知识图谱本体
- 标准节点与关系
- 问题节点
- 风险路径
- 同义词与规则
- 轻量级解释性轨迹引用

### 11.2 不建议直接主存 Neo4j 的
- 大量原始聊天消息
- 高频更新的完整个案状态
- 整个长会话上下文
- 大量临时中间态

### 11.3 推荐方式
采用“双存储”：

- `Neo4j`：知识图谱 + 推理依据
- 业务数据库/状态存储：`case_state`、消息、审核记录、结果缓存

必要时仅把个案相关的“证据引用”写入图谱或专用关系表。

---

## 12. 标签与索引建议

---

## 12.1 推荐标签
- `Disease`
- `Pattern`
- `Pathogenesis`
- `Symptom`
- `Sign`
- `Observation`
- `Question`
- `QuestionGroup`
- `RedFlag`
- `PopulationTag`
- `Contraindication`
- `VisitRoute`
- `ConsultStage`
- `EvidenceRule`
- `Synonym`

---

## 12.2 推荐唯一约束
建议为以下节点建立唯一约束：

- `Disease.id`
- `Pattern.id`
- `Pathogenesis.id`
- `Symptom.id`
- `Observation.id`
- `Question.id`
- `RedFlag.id`
- `PopulationTag.id`
- `Contraindication.id`
- `VisitRoute.id`
- `ConsultStage.id`
- `EvidenceRule.id`
- `Synonym.id`

---

## 12.3 推荐索引字段
建议对以下字段建立索引：

- `name`
- `alias`
- `status`
- `stage`
- `question_type`
- `is_required_safety`
- `domain`
- `category`

---

## 13. 初版最小图谱范围建议

为了快速落地 MVP，不建议一开始建全量医学宇宙。

### 13.1 先做一个收敛良好的专题域
例如任选其一作为首批：
- 感冒/咳嗽/发热
- 头痛/失眠
- 月经不调/痛经
- 胃脘不适/腹痛

### 13.2 初版节点范围
每个专题域先控制在：

- `Disease`: 10~20
- `Pattern`: 15~30
- `Pathogenesis`: 10~20
- `Symptom`: 50~120
- `Observation`: 20~40
- `Question`: 40~100
- `RedFlag`: 10~20
- `PopulationTag`: 5~10

### 13.3 初版目标
重点验证三件事：

1. 主诉能否拉出合理候选集合
2. 下一问是否明显比固定问卷更有效
3. 系统是否能输出清晰证据链

---

## 14. 与 `deepagents` 的集成接口建议

图谱层建议不要直接暴露给 LLM 任意 Cypher 查询，而是通过受控工具提供能力。

---

## 14.1 推荐图谱工具接口
- `query_graph_candidates`
- `find_discriminative_questions`
- `expand_related_observations`
- `check_red_flag_paths`
- `build_evidence_path`
- `explain_question_rationale`
- `rank_pattern_candidates`

---

## 14.2 推荐返回结构
所有图谱工具尽量返回结构化对象，而不是自然语言段落。

### 候选查询返回
- `candidate_diseases`
- `candidate_patterns`
- `candidate_pathogenesis`
- `matched_facts`
- `missing_high_value_facts`

### 下一问返回
- `question_id`
- `question_text`
- `why_this_question`
- `discriminates_between`
- `expected_answers`
- `risk_priority`
- `fatigue_cost`

### 风险返回
- `matched_red_flags`
- `risk_level`
- `recommended_route`
- `reasoning_path`

---

## 15. 示例建模片段

以下只是概念示例，不代表完整数据。

### 症状到证型
- `恶寒` 支持 `风寒束表`
- `发热` 可支持 `风寒束表` 或 `风热犯表`
- `口渴喜冷饮` 更支持 `风热犯表`
- `无汗` 更支持 `风寒束表`

### 问题区分
问题：“发热时更怕冷还是更怕热？”
可同时关联：
- `寒热` 观察域
- `风寒束表`
- `风热犯表`

并携带：
- 对两者区分价值较高
- 疲劳成本较低
- 在“动态追问”阶段可用

### 风险路径
- `胸痛` -> `RedFlag(胸痛风险)`
- `RedFlag(胸痛风险)` -> `VisitRoute(立即线下/急诊评估)`

---

## 16. 后续扩展方向

本版 Schema 先支持问诊收敛，后续可逐步扩展：

- 舌诊图像结果节点
- 脉象采集结果节点
- 方药知识图谱
- 随访与疗效变化图谱
- 时间序列症状变化
- 个体化风险评分
- 医生审核反馈反哺图谱权重

---

## 17. 本版结论

本 Schema 的核心不是“医学概念越多越好”，而是让系统具备以下能力：

- 从主诉快速进入候选空间
- 依据图谱关系动态决定下一问
- 将回答映射为可计算的结构化事实
- 对风险优先拦截
- 对候选收敛提供证据链
- 为 `deepagents` 的 Supervisor、`intake-agent`、`safety-agent` 提供稳定的图谱能力底座

一句话总结：

> Neo4j 在本项目中的角色，不是静态医学知识库，而是“收敛式问诊引擎”的结构化推理底盘。