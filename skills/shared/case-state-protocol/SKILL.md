---
name: case-state-protocol
description: "CaseState data structure protocol defining all fields (normalized_facts, candidate_diseases, convergence_score, etc.), normalized_key naming conventions (snake_case English), case_stage transition rules, and read/write constraints. Use when reading from or writing to case state, or when deciding how to update case fields after a patient response."
---

# CaseState 数据结构协议（Case State Protocol）

> **Skill 用途**：本文件定义 `CaseState` 的完整字段规范、命名约定、阶段流转规则及最佳实践，所有 Sub-agent 在读取或更新病例状态时必须遵守本协议。

---

## 1. CaseState 总体定位

`CaseState` 是整个 TCMAgent 问诊流程的**核心驱动对象**，而不仅仅是聊天记录的附属品。

- **每一轮对话**都必须产生对 `CaseState` 的结构化更新
- **所有 Agent 的决策**都应基于当前 `CaseState` 而非重新推断聊天历史
- **`CaseState` 是审计的最终依据**，而不是自然语言对话流

> 原则：宁可多写一个字段，不要让关键信息只存在于聊天上下文中。

---

## 2. 完整字段说明

### 2.1 身份与基础信息

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `case_id` | `str` | ✅ | 全局唯一病例 ID，由 `create_case` 工具生成，格式建议：`case_{uuid4_short}` |
| `visit_type` | `str` | ✅ | 就诊类型：`initial`（初诊）/ `follow_up`（复诊） |
| `channel` | `str` | ✅ | 来源渠道，如 `web`、`app`、`api_internal` |
| `created_at` | `str` | ✅ | ISO 8601 格式时间戳，病例创建时间 |
| `updated_at` | `str` | ✅ | 最近一次更新时间，每次写入时更新 |

---

### 2.2 患者档案（patient_profile）

`patient_profile` 是一个嵌套对象，包含：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `name` | `str \| null` | 患者姓名，可匿名 |
| `age` | `int \| null` | 年龄（岁），用于特殊人群判断 |
| `gender` | `str \| null` | 性别：`male` / `female` / `other` |
| `is_pregnant` | `bool \| null` | 是否妊娠，`null` 表示未确认 |
| `known_conditions` | `list[str]` | 已知慢性病列表，如 `["高血压", "糖尿病"]` |
| `current_medications` | `list[str]` | 当前用药列表 |
| `allergies` | `list[str]` | 过敏史列表 |

> **注意**：`is_pregnant` 字段对女性患者必须主动询问，不可默认为 `false`，未询问时保持 `null`。

---

### 2.3 主诉

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `chief_complaint` | `str \| null` | 患者主诉，尽量保留原始表述，不做过度改写 |

> 主诉应在建档初始化阶段（`created` 阶段）完成填写。后续问诊过程中不应覆盖主诉，而是通过 `normalized_facts` 补充细节。

---

### 2.4 归一化症状事实（normalized_facts）

`normalized_facts` 是 `list[NormalizedFact]`，每条记录代表从患者描述中提取的一个结构化事实。

**NormalizedFact 字段说明：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `fact_id` | `str` | 唯一标识，格式：`fact_{uuid4_short}` |
| `fact_type` | `str` | 事实类型（见下方枚举） |
| `normalized_key` | `str` | 标准化键名（见第 3 节规范） |
| `normalized_value` | `str \| bool \| int \| float \| list[str]` | 标准化取值 |
| `source_text` | `str \| null` | 患者原始描述文本 |
| `confidence` | `float` | 置信度 0.0–1.0 |
| `source_turn_id` | `str \| null` | 来源对话轮次 ID |

**fact_type 枚举：**

| 取值 | 说明 |
|------|------|
| `symptom` | 症状，如发热、头痛 |
| `tongue_observation` | 舌象观察，如舌红苔黄 |
| `pulse_observation` | 脉象（线上问诊慎用） |
| `history` | 病史信息，如曾患某病 |
| `medication` | 用药信息 |
| `lifestyle` | 生活习惯，如饮食偏好、睡眠情况 |
| `lab_result` | 检查结果（患者自述） |
| `demographic` | 人口学信息补充，如体型、职业 |

---

### 2.5 已问问题记录（asked_questions）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `asked_questions` | `list[str]` | 已问过的 `question_id` 列表，用于防止重复提问 |

> 每次 `intake-agent` 完成一轮提问后，必须将 `question_id` 追加到此列表。图谱推理服务在选择下一问时必须排除已在此列表中的问题。

---

### 2.6 候选集合

以下三个字段均为 `list[CandidateItem]`，代表图谱推理的当前候选空间：

| 字段名 | 说明 |
|--------|------|
| `candidate_diseases` | 候选疾病列表（西医或中医病名） |
| `candidate_patterns` | 候选证型列表（如风寒束表、肝郁气滞） |
| `candidate_pathogenesis` | 候选病机列表（如气滞血瘀、湿热蕴结） |

**CandidateItem 字段说明：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `candidate_id` | `str` | 图谱节点 ID |
| `name` | `str` | 候选名称（中文） |
| `score` | `float` | 综合评分 0.0–1.0 |
| `confidence` | `float` | 当前置信度 0.0–1.0 |
| `category` | `str \| null` | 分类标签 |
| `evidence_refs` | `list[str]` | 支持该候选的事实 ID 列表 |

> 候选集合在每轮问答后由 `rank_candidate_hypotheses` 工具更新，不应由 Agent 直接手动修改候选排序。

---

### 2.7 红旗与风险字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `red_flags` | `list[MatchedRedFlag]` | 已识别的红旗征象列表 |
| `risk_level` | `str \| null` | 当前风险等级（见第 5 节） |
| `safe_to_continue` | `bool \| null` | 是否可继续线上问诊，`null` 表示尚未评估 |
| `recommend_offline_visit` | `bool` | 是否建议线下就诊，默认 `false` |
| `recommend_human_review` | `bool` | 是否建议人工审核，默认 `false` |
| `recommended_route` | `str \| null` | 推荐就诊路径（见 visit_routing_guide.md） |
| `special_population_tags` | `list[str]` | 特殊人群标签列表（见 special_population_rules.md） |
| `contraindication_flags` | `list[ContraindicationFlag]` | 禁忌标记列表 |

---

### 2.8 推荐问题字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `recommended_next_question` | `QuestionRecommendation \| null` | 当前最推荐的下一个问题 |
| `question_rationale` | `str \| null` | 为什么推荐该问题的理由（供内部审查） |

**QuestionRecommendation 字段说明：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `question_id` | `str` | 问题唯一 ID |
| `question_text` | `str` | 结构化问题描述（非自然语言） |
| `goal` | `str` | 该问题的目标，如 `distinguish_cold_heat` |
| `discriminates_between` | `list[str]` | 该问题能区分的候选 ID 列表 |
| `target_domain` | `str \| null` | 目标维度，如 `tongue`、`sleep`、`stool` |
| `priority` | `float` | 优先级 0.0–1.0 |
| `safety_related` | `bool` | 是否与安全/红旗相关 |
| `fatigue_cost` | `float` | 患者疲劳成本估计 0.0–1.0 |

---

### 2.9 进度评分字段

| 字段名 | 类型 | 初始值 | 说明 |
|--------|------|--------|------|
| `intake_completeness_score` | `float` | `0.0` | 问诊完整度得分（详见第 4 节） |
| `convergence_score` | `float` | `0.0` | 候选收敛度得分（详见第 4 节） |

---

### 2.10 阶段与审计字段

| 字段名 | 类型 | 初始值 | 说明 |
|--------|------|--------|------|
| `case_stage` | `str` | `created` | 当前病例阶段（详见第 5 节） |
| `contradictions` | `list[ContradictionItem]` | `[]` | 已检测到的矛盾记录列表 |
| `audit_log` | `list[AuditEntry]` | `[]` | 完整审计轨迹，只追加不删除 |

**ContradictionItem 字段说明：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `field` | `str` | 涉及的 `normalized_key` |
| `previous_value` | `str \| null` | 早期记录值 |
| `new_value` | `str \| null` | 新提供的矛盾值 |
| `reason` | `str` | 矛盾描述 |

---

## 3. normalized_key 命名规范

所有 `normalized_key` 必须遵守以下规范，确保跨 Agent 一致性。

### 3.1 格式规则

- **全部小写英文**，单词之间用下划线 `_` 连接（snake_case）
- **不使用中文、拼音、缩写**
- **不超过 5 个单词**，保持简洁
- **语义自解释**：读到键名即能理解含义

### 3.2 命名示例

| ✅ 正确 | ❌ 错误 | 说明 |
|---------|---------|------|
| `aversion_to_cold` | `怕冷` | 不使用中文 |
| `loose_stool` | `diarrhea_loose_watery_stool` | 不过度冗长 |
| `night_sweating` | `nightSweat` | 不使用驼峰 |
| `tongue_red` | `舌红` | 不使用中文 |
| `chest_pain` | `cp` | 不使用缩写 |
| `low_back_pain` | `low_back_ache_pain_soreness` | 不过度描述 |

### 3.3 取值规范

| 症状类型 | normalized_value 建议 | 示例 |
|---------|----------------------|------|
| 存在/不存在 | `true` / `false` | `fever: true` |
| 程度 | `"mild"` / `"moderate"` / `"severe"` | `headache_severity: "moderate"` |
| 描述性 | 标准英文短语 | `headache_quality: "throbbing"` |
| 数值 | 浮点或整数 | `temperature: 38.5` |
| 枚举 | 预定义字符串 | `stool_consistency: "loose"` |
| 列表 | 字符串数组 | `tongue_features: ["red", "yellow_coating"]` |

### 3.4 常用 normalized_key 速查

```
# 全身
aversion_to_cold, fever, temperature, spontaneous_sweating, night_sweating,
fatigue, weight_loss, edema

# 头面
headache, headache_location, headache_quality, dizziness, tinnitus,
dry_eyes, red_eyes, dry_mouth, thirst, thirst_preference, bitter_taste, sore_throat

# 胸腹
chest_pain, chest_tightness, palpitations, shortness_of_breath,
cough, cough_with_phlegm, phlegm_color, abdominal_pain, abdominal_distension,
nausea, vomiting, poor_appetite, acid_reflux, hypochondriac_pain

# 腰背四肢
low_back_pain, knee_pain, joint_pain, cold_limbs, numbness_limbs

# 二便
loose_stool, constipation, stool_frequency, dark_urine, clear_urine,
frequent_urination, nocturia, blood_in_urine

# 睡眠情志
insomnia, difficulty_falling_asleep, early_waking, vivid_dreams,
irritability, anxiety, depression_mood

# 舌象
tongue_pale, tongue_red, tongue_deep_red, tongue_purple, tongue_swollen,
tongue_teeth_marks, coating_white, coating_yellow, coating_thick_greasy,
coating_thin, coating_absent, coating_moist, coating_dry

# 女性相关
menstrual_irregular, menstrual_pain, menstrual_flow_heavy, menstrual_flow_light,
menstrual_color_dark, is_pregnant
```

---

## 4. 进度评分字段详解

### 4.1 intake_completeness_score（问诊完整度）

**含义**：当前已收集到的问诊信息相对于"理想最小问诊集"的完整程度。

**取值范围**：`0.0`（完全空白）→ `1.0`（达到最小完整要求）

**评分维度（各维度满分权重）：**

| 维度 | 权重 | 达标条件 |
|------|------|---------|
| 主诉确认 | 15% | `chief_complaint` 非空 |
| 寒热确认 | 15% | `aversion_to_cold` 或 `fever` 已知 |
| 二便情况 | 10% | `loose_stool` 或 `constipation` 已知 |
| 睡眠情况 | 10% | `insomnia` 相关已知 |
| 饮食口味 | 10% | `poor_appetite` 或 `thirst` 已知 |
| 病程时长 | 10% | 相关 `duration` 信息已知 |
| 舌象 | 15% | 至少一条舌象 fact 已采集 |
| 特殊人群筛查 | 15% | 孕妇/儿童/老年相关问题已询问 |

**使用规则**：
- `intake_completeness_score < 0.4`：问诊严重不足，不应进入总结阶段
- `0.4 ≤ score < 0.7`：基础信息已有，但仍需补充关键维度
- `score ≥ 0.7`：可进入收敛判断，考虑是否结束动态追问

### 4.2 convergence_score（候选收敛度）

**含义**：当前候选集合的"收敛程度"，反映系统对主要证型/病机的确信度。

**取值范围**：`0.0`（完全发散）→ `1.0`（高度收敛）

**计算逻辑（概念层面）：**

```
convergence_score = f(
    top_candidate_confidence,        # 最高候选置信度
    gap_to_second_candidate,         # 第一与第二候选的差距
    total_supported_evidence_count,  # 有效支持证据数量
    unresolved_contradiction_count   # 未消解矛盾数量（负向）
)
```

**使用规则**：
- `convergence_score < 0.3`：候选严重发散，需继续追问区分性问题
- `0.3 ≤ score < 0.6`：有初步倾向，继续收敛
- `0.6 ≤ score < 0.8`：候选基本明确，可开始准备阶段性总结
- `score ≥ 0.8`：高度收敛，优先进入总结阶段（前提：`safe_to_continue=true`）

> **重要**：`convergence_score` 高并不意味着可以停止问诊。如果仍有未完成的安全必问（红旗筛查、特殊人群），必须先完成安全轨，再评估收敛。

---

## 5. case_stage 阶段定义与流转规则

### 5.1 阶段枚举

| 阶段值 | 含义 | 进入条件 |
|--------|------|---------|
| `created` | 病例已建档，尚未开始任何分析 | `create_case` 工具执行成功 |
| `triaged` | 导诊与红旗初筛完成 | `triage-agent` 完成评估并调用 `set_case_stage` |
| `initial_candidates_generated` | 初始候选集合已生成 | 图谱推理服务完成首次候选生成 |
| `intake_in_progress` | 动态追问进行中 | 第一轮动态问题已发出 |
| `intake_paused_for_risk` | 问诊因风险复核暂停 | `safety-agent` 触发风险评估暂停 |
| `intake_converged` | 问诊达到收敛条件 | `convergence_score ≥ 阈值` 且 `intake_completeness_score ≥ 阈值` |
| `safety_reviewed` | 安全复核完成 | `safety-agent` 完成最终复核 |
| `summary_generated` | 阶段性总结已生成 | 总结工具执行完毕 |
| `handoff_required` | 需要移交（人工审核或线下） | `safe_to_continue=false` 或触发移交条件 |
| `closed` | 本次问诊会话已关闭 | 显式关闭操作或超时 |

### 5.2 合法流转路径

```
created
  └─→ triaged
        ├─→ handoff_required          # 红旗命中或不适合线上
        └─→ initial_candidates_generated
              └─→ intake_in_progress
                    ├─→ intake_paused_for_risk
                    │     ├─→ handoff_required
                    │     └─→ intake_in_progress   # 风险消解后继续
                    └─→ intake_converged
                          └─→ safety_reviewed
                                ├─→ handoff_required
                                └─→ summary_generated
                                      └─→ closed
```

### 5.3 阶段流转规则

1. **只能向前推进**，不允许回退到更早阶段（除 `intake_paused_for_risk → intake_in_progress`）
2. **跳过阶段需记录原因**到 `audit_log`
3. **`handoff_required` 是终态之一**，进入后不应再推进普通问诊流程
4. **阶段变更必须通过 `set_case_stage` 工具**，不应直接修改字段

---

## 6. 读取 case_state 的最佳实践

### 6.1 使用 get_case_state 工具

任何 Sub-agent 需要读取病例状态时，必须调用 `get_case_state` 工具，而不是依赖上下文记忆。

```
# 正确做法
state = get_case_state(case_id=case_id)

# 错误做法
# 从聊天历史中推断 risk_level
```

### 6.2 读取时必须检查的字段

Agent 收到 `CaseState` 后，必须优先检查：

1. `safe_to_continue`：如果为 `false`，立即停止普通问诊逻辑
2. `case_stage`：确认当前阶段合法，不执行不属于本阶段的操作
3. `red_flags`：是否有未处理的红旗
4. `special_population_tags`：是否有高风险特殊人群标记

### 6.3 只读字段（不应被覆盖）

| 字段 | 原因 |
|------|------|
| `case_id` | 唯一标识，不可变 |
| `created_at` | 创建时间，不可变 |
| `chief_complaint` | 主诉一旦确认不应覆盖，追加到 `normalized_facts` |
| `audit_log` | 只能追加，不能修改历史记录 |
| `contradictions` | 只能追加新矛盾，不能删除历史矛盾 |

---

## 7. 更新 case_state 的最佳实践

### 7.1 使用对应工具更新，不直接 patch 整个对象

| 更新目标 | 使用工具 |
|---------|---------|
| 添加归一化事实 | `update_case_facts` |
| 记录已问问题 | `record_question_asked` |
| 追加证据 | `append_case_evidence` |
| 变更阶段 | `set_case_stage` |
| 发布风险决策 | `issue_risk_decision` |
| 追加审计日志 | `append_audit_log` |

### 7.2 每轮问答必须更新的最小字段集

每轮 `intake-agent` 完成问答后，**必须**更新：

- [ ] `normalized_facts`：新归一化事实追加
- [ ] `asked_questions`：已问问题 ID 追加
- [ ] `updated_at`：时间戳更新

**应当**更新（若有变化）：

- [ ] `candidate_patterns` / `candidate_diseases`：候选重排序
- [ ] `convergence_score`：重新计算
- [ ] `intake_completeness_score`：重新计算
- [ ] `contradictions`：若检测到矛盾则追加
- [ ] `recommended_next_question`：更新为最新推荐

### 7.3 置信度管理原则

- 同一 `normalized_key` 被多次提及时，**不要删除旧记录**，而是追加新记录，保留 `confidence` 差异
- 系统使用**最新高置信度记录**作为当前有效值
- 低置信度记录（`confidence < 0.4`）不应影响候选排序，但应保留供矛盾检测

### 7.4 并发更新注意事项

- 同一 `case_id` 不应由多个 Agent 同时写入
- `clinical-supervisor` 负责串行调度各 Sub-agent 的写操作
- 写入前应检查 `updated_at` 确认当前读取的是最新状态

---

## 8. audit_log 写入规范

`audit_log` 是每个操作的留痕，不可删除或篡改。

**AuditEntry 建议字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `entry_id` | `str` | 唯一 ID |
| `timestamp` | `str` | ISO 8601 |
| `actor` | `str` | 执行者，如 `triage-agent`、`safety-agent`、`system` |
| `action` | `str` | 操作类型，如 `stage_changed`、`risk_issued`、`fact_added` |
| `summary` | `str` | 操作摘要（人类可读） |
| `detail` | `dict \| null` | 操作详细数据（可选，用于调试） |

**必须记录到 audit_log 的操作：**

1. 病例创建
2. 阶段变更
3. 红旗命中
4. 风险决策发布（每次 `issue_risk_decision`）
5. 问诊中断或移交
6. `safe_to_continue` 值变更
7. 矛盾检测记录
8. 总结生成

---

## 9. 常见错误模式

| 错误模式 | 正确做法 |
|---------|---------|
| 直接从聊天历史推断 `risk_level` | 调用 `get_case_state` 读取最新状态 |
| 用新事实覆盖旧事实（相同 `normalized_key`） | 追加新记录，保留旧记录 |
| 跳过 `safe_to_continue` 检查直接继续问诊 | 任何轮次开始前先检查该字段 |
| 修改 `audit_log` 历史条目 | `audit_log` 是追加专用，禁止修改 |
| 在 `handoff_required` 阶段继续发送问诊问题 | 检查阶段后，该阶段只能输出移交提示 |
| 自行计算 `convergence_score` 而不调用工具 | 通过图谱推理服务的 `rank_candidate_hypotheses` 工具更新 |
| 将证型候选直接表述为诊断结论 | 候选必须标注为"候选"，不得作为确定性诊断输出给患者 |