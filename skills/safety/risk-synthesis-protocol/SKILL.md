---
name: risk-synthesis-protocol
description: "Protocol for synthesizing overall risk level (none/low/medium/high/critical) from red flags, special population risk adjustments, and contraindication flags. Includes 10-step logic flow, stacking rules (3+ medium factors → high), and mandatory actions when safe_to_continue=false. Use to produce the final RiskDecision after collecting all safety signals."
---

# 风险综合判断协议（Risk Synthesis Protocol）

> **Skill 用途**：本文件定义 `safety-agent` 在执行风险综合判断时必须遵守的完整操作规范，包括风险等级定义、综合逻辑、`RiskDecision` 输出规范以及 `safe_to_continue=false` 时的处置流程。风险综合判断是问诊流程中的"最终安全守门人"。

---

## 1. 核心原则

1. **偏保守原则**：当风险信号模糊、信息不足或存在不确定性时，**宁可高估风险**，选择更保守的处置路径，不可为追求流程顺畅而低估风险。
2. **综合判断，不单一依赖**：风险等级由多个维度综合决定（红旗征象 + 特殊人群 + 矛盾质量 + 症状持续时间 + 用药史），不能只看单一维度。
3. **安全决策不可逆**：`safe_to_continue=false` 一旦设置，在本次会话内不可被普通问诊信息逆转（除非有明确的人工干预记录）。
4. **每个关键节点都要复核**：风险评估不只在导诊阶段执行一次，在动态追问循环中的关键节点、以及生成总结之前，都必须执行风险复核。
5. **风险决策必须工具化输出**：所有风险等级变更必须通过 `issue_risk_decision` 工具执行，不允许 Agent 只在自然语言中隐含风险判断而不更新 `case_state`。

---

## 2. 风险等级定义

TCMAgent 使用五级风险等级体系：

### 2.1 等级总览

| 等级 | 英文值 | 中文含义 | `safe_to_continue` | 默认 `recommended_route` |
|------|--------|---------|-------------------|------------------------|
| 无风险 | `none` | 无明显风险信号 | `true` | `online_continue` |
| 低风险 | `low` | 轻微风险因素，整体可控 | `true` | `online_continue` |
| 中度风险 | `medium` | 存在中度风险因素，需关注 | `true`（有条件）| `online_continue` 或 `offline_referral` |
| 高风险 | `high` | 明显高风险，不适合继续普通线上问诊 | `false` | `offline_referral` 或 `human_review` |
| 危急 | `critical` | 严重红旗或立即危及生命安全的情况 | `false` | `emergency` |

---

### 2.2 各等级详细定义

#### 风险等级：`none`

**定义**：当前收集到的全部信息中，无任何风险信号，患者情况适合完整的线上中医问诊。

**满足条件（全部满足）**：
- 无任何红旗征象（Level 1、2、3 均无）
- 无特殊人群标签（或仅有 `diabetic`、`hypertensive` 且病情稳定）
- 无矛盾信息或仅有 P3 级矛盾
- 症状持续时间合理（< 2 周，或慢性病稳定期）
- 无已知危险用药史（无抗凝药、免疫抑制剂等）
- `intake_completeness_score ≥ 0.4`（信息已足够基础评估）

**对应处置**：继续正常问诊，无需任何特殊提示。

---

#### 风险等级：`low`

**定义**：存在轻微风险因素，但整体上适合继续线上问诊，需在问诊中保持关注。

**典型触发情况**：
- 存在 Level 3 风险标志（低风险需标记追踪的情况）
- 年龄 > 65 岁但 < 75 岁，症状非特异性
- 存在单一慢性病（如稳定期高血压），当前症状与慢性病无关
- 存在 P3 级矛盾，信息质量有轻微不确定性
- 症状持续 2–4 周，但无进行性加重趋势

**对应处置**：
- `safe_to_continue = true`
- 问诊中标记相关风险因素，适时追问风险相关维度
- 在总结阶段提示患者"如有加重建议及时就医"

---

#### 风险等级：`medium`

**定义**：存在中度风险因素，问诊可在有限条件下继续，但推荐路径应向 `offline_referral` 倾斜。

**典型触发情况**：
- 存在 1 条 Level 2 中度风险标志
- 特殊人群（如孕妇、婴儿期儿童、`elderly_high_risk`）但无急性加重
- 症状持续 > 3 周且有轻微进行性加重
- 存在 P2 级矛盾 ≥ 2 条，信息质量中等
- `polypharmacy` 标签 + 当前症状涉及用药相关风险
- 单一 P1 级矛盾已记录但尚未澄清（暂时维持 medium，追问澄清）
- 多个 `low` 风险因素叠加（见第 3.4 节升级规则）

**`safe_to_continue` 的设置（条件性）**：

| 子情况 | `safe_to_continue` |
|-------|-------------------|
| 仅有特殊人群标签，症状轻微，无红旗 | `true`（但收集信息时保守） |
| Level 2 红旗已记录，继续采集基础信息 | `true`（短暂，下一步转 offline） |
| 孕妇任何症状 | `false`（孕妇不给中药建议） |
| 信息矛盾严重影响推理质量 | `false` |

**对应处置**：
- 明确告知患者中等程度风险提示
- 设置 `recommended_route = "offline_referral"`（或根据具体子情况选择）
- 继续收集基础信息但不深入收敛推理

---

#### 风险等级：`high`

**定义**：存在明显高风险因素，线上问诊不适合继续，需要线下评估或人工干预。

**典型触发情况**：
- 存在 ≥ 2 条 Level 2 中度风险标志（叠加升级）
- Level 2 红旗 + 高风险特殊人群标签（双重叠加）
- 确认怀孕（`pregnant_confirmed`）+ 任何需要进一步评估的症状
- 儿童（`toddler` 或 `child`）+ 持续高热 > 24 小时
- 老年（`elderly_high_risk`）+ 症状模糊加重趋势
- CKD 3–4 期 + 任何急性加重症状
- 存在 P1 级矛盾 ≥ 2 条，信息质量严重不可靠
- `convergence_score` 长期 < 0.3 且已超过 8 轮追问（推理失败）
- 抗凝药使用者 + 任何出血症状

**对应处置**：
- `safe_to_continue = false`
- `recommend_offline_visit = true`
- 根据具体情况选择 `offline_referral` 或 `human_review`
- 设置 `case_stage = "handoff_required"`
- 立即停止动态追问，输出移交提示

---

#### 风险等级：`critical`

**定义**：存在严重红旗征象或立即危及生命安全的情况，需要立即急诊处置。

**触发条件**：
- 任何 Level 1 严重红旗命中（详见 `red-flags-protocol` skill 第 2 节）
- 特殊人群 + 症状风险等级提升到 `critical`（见 `special-population-rules` skill 第 2.2 节）
- `high` 风险等级 + 新出现严重症状加重
- 患者表达自杀/自伤意念

**对应处置**：
- `safe_to_continue = false`（绝对，不可逆）
- `recommend_offline_visit = true`
- `recommended_route = "emergency"`
- `case_stage = "handoff_required"`
- **立即停止所有普通问诊逻辑**
- 输出急诊强制提示（详见第 5 节）

---

## 3. 风险综合逻辑

### 3.1 综合逻辑总流程

```
Step 1：读取 case_state 全量信息
    - red_flags（已命中的红旗，含 level）
    - special_population_tags（特殊人群标签）
    - contradictions（矛盾列表及状态）
    - normalized_facts（已收集症状）
    - patient_profile（年龄、用药、慢性病）
    - current risk_level（当前已有的风险等级）
    ↓
Step 2：严重红旗检查（最优先）
    任何 Level 1 红旗 → risk_level = "critical"，停止其他检查
    ↓
Step 3：特殊人群风险调整
    读取 special_population_tags，应用各标签的风险提升规则
    得到"特殊人群调整后的基础风险等级"
    ↓
Step 4：Level 2 红旗评估
    计算 Level 2 红旗数量：
    0 条 → 无额外影响
    1 条 → 至少 medium
    ≥ 2 条 → 至少 high（叠加升级）
    ↓
Step 5：信息质量评估
    P1 unresolved 矛盾数量：
    0 条 → 无影响
    1 条 → 如当前 < medium，升至 medium
    ≥ 2 条 → 升至 high
    ↓
Step 6：其他风险因子评估（见 3.5 节）
    ↓
Step 7：取所有评估结果中的最高等级
    ↓
Step 8：应用特殊人群自动升级规则（二次确认）
    ↓
Step 9：生成最终 risk_level 和 safe_to_continue
    ↓
Step 10：调用 issue_risk_decision 工具，写入 case_state
```

---

### 3.2 严重红旗 → `critical`

**规则**：`case_state.red_flags` 中存在任何 `level = 1` 的 `MatchedRedFlag`。

```
IF any(flag.level == 1 for flag in case_state.red_flags):
    risk_level = "critical"
    safe_to_continue = false
    recommended_route = "emergency"
    → 停止其他所有检查，直接进入 critical 处置
```

**此规则优先级高于所有其他规则，不可被其他因素抵消。**

---

### 3.3 高风险特殊人群 + 症状不明 → `high`

**规则**：存在高风险特殊人群标签，且当前症状信息不足以排除高风险情况。

```
高风险特殊人群标签定义（任一满足）：
  - pregnant_confirmed 或 pregnant_unconfirmed
  - neonate
  - infant
  - chronic_kidney_disease（CKD 3–5 期）
  - chronic_liver_disease（肝硬化/肝功能不全）
  - anticoagulant_user + 任何出血症状
  - immunosuppressant_user + 发热
  - organ_transplant

症状不明的判断条件（任一满足）：
  - intake_completeness_score < 0.5
  - 存在 P1 级 unresolved 矛盾
  - chief_complaint 为空或极度模糊

→ 满足高风险人群 + 症状不明 → risk_level = "high"
```

---

### 3.4 多个中度风险叠加 → 升级规则

**规则**：单个中度风险因素 = `medium`；多个中度风险因素叠加 = `high`。

```
中度风险因子清单（每项计 1 分）：
  1. Level 2 红旗命中（每条计 1 分）
  2. elderly_high_risk 标签（计 1 分）
  3. polypharmacy 标签（计 1 分）
  4. 症状持续 > 3 周且有加重趋势（计 1 分）
  5. P2 级 unresolved 矛盾 ≥ 3 条（计 1 分）
  6. 已知慢性病 ≥ 2 种（计 1 分）
  7. 当前推理收敛失败（convergence_score < 0.3 且已超 8 轮）（计 1 分）

叠加规则：
  总分 = 0 → none/low（按其他规则决定）
  总分 = 1 → medium
  总分 = 2 → medium（但 safe_to_continue 需评估）
  总分 ≥ 3 → high
```

---

### 3.5 其他独立风险因子

以下情况单独触发对应风险等级，不需要叠加：

| 触发条件 | 直接设置 risk_level | 说明 |
|---------|-------------------|------|
| `convergence_score < 0.3` 且追问 > 12 轮 | `high` | 推理长期无法收敛，线上已无法有效推进 |
| `intake_completeness_score < 0.3` 且已超过 10 轮问诊 | `medium` | 信息采集严重不足，需线下或人工 |
| P1 unresolved 矛盾 ≥ 3 条 | `high` | 信息质量极差，无法可靠推理 |
| 患者明确拒绝回答所有安全必问（> 3 次） | `medium` | 无法排除风险 |
| 患者自述用药 ≥ 10 种（高度复杂多药）| `medium` | 中西药相互作用风险极高 |

---

### 3.6 特殊人群自动升级（二次确认）

在所有风险因子评估完成后，对特殊人群再执行一次自动升级检查：

```python
# 特殊人群自动升级规则（二次确认）
if "pregnant_confirmed" in special_population_tags:
    risk_level = upgrade_one_level(risk_level)
    # none→low, low→medium, medium→high, high→critical

if "neonate" in special_population_tags:
    risk_level = max(risk_level, "high")

if "infant" in special_population_tags and fever_present:
    risk_level = max(risk_level, "high")

if "elderly_high_risk" in special_population_tags:
    if risk_level in ("none", "low") and symptoms_vague:
        risk_level = "medium"

# upgrade_one_level 函数：none→low→medium→high→critical
# max 函数按等级严重程度取最大值
```

---

## 4. RiskDecision 输出规范

### 4.1 完整字段定义

每次调用 `issue_risk_decision` 工具，必须填写以下所有字段：

```python
class RiskDecisionOutput:
    decision_id: str               # 唯一 ID，格式：risk_{uuid4_short}
    risk_level: str                # 五级枚举：none/low/medium/high/critical
    safe_to_continue: bool         # 是否可继续线上问诊
    recommend_offline_visit: bool  # 是否建议线下就诊
    recommend_human_review: bool   # 是否建议人工审核
    recommended_route: str         # 路径枚举：online_continue/offline_referral/emergency/human_review
    decision_reason: str           # 决策理由（人类可读，需具体，不可泛泛）
    evidence_refs: list[str]       # 触发该决策的 fact_id 或 flag_id 列表
    triggering_factors: list[str]  # 触发因素摘要列表（结构化）
    population_adjustments: list[PopulationRiskAdjustment]  # 特殊人群风险调整记录
    timestamp: str                 # ISO 8601 时间戳
    issuing_agent: str             # 发出决策的 agent，通常为 "safety-agent"
    is_final: bool                 # 是否为本次会话的终态风险决策
```

---

### 4.2 字段填写规范

#### `decision_reason` 填写要求

**必须具体说明**：
- 触发的风险因素是什么
- 为什么选择当前风险等级（而非更高或更低）
- 如有特殊人群调整，说明调整逻辑

**❌ 错误示例（过于泛泛）**：
> "患者存在一些风险因素，建议线下就诊。"

**✅ 正确示例（具体说明）**：
> "患者确认怀孕（pregnant_confirmed），当前症状为发热 37.8°C 持续 2 天。根据特殊人群规则，孕妇风险等级自动从 low 提升为 medium。孕妇线上中医问诊不适合给出任何中药建议，建议 48 小时内妇产科或中医科（有孕期资质）线下就诊。"

---

#### `triggering_factors` 填写要求

使用结构化字符串列表，每条描述一个触发因素：

```json
"triggering_factors": [
  "red_flag_level2: 发热持续3天未缓解",
  "special_population: pregnant_confirmed（风险升级一级）",
  "symptom: fever=true, temperature=37.8, duration=2days",
  "intake_completeness_score: 0.65（已达基础要求）"
]
```

---

#### `evidence_refs` 填写要求

列出触发该风险决策的具体证据来源：
- 红旗记录：`flag_xxx`（来自 `case_state.red_flags`）
- 症状事实：`fact_xxx`（来自 `case_state.normalized_facts`）
- 矛盾记录：`contr_xxx`（来自 `case_state.contradictions`）

```json
"evidence_refs": ["flag_a3b2c1", "fact_003", "fact_007", "contr_x7k2m1"]
```

---

#### `is_final` 的使用规则

| 场景 | `is_final` |
|------|-----------|
| 导诊阶段的初次风险评估 | `false`（后续还可能更新） |
| 动态追问中的中间风险复核 | `false` |
| 进入 `safety_reviewed` 阶段的最终复核 | `true` |
| 触发 `handoff_required` 的风险决策 | `true` |
| `safe_to_continue=false` 时发出的决策 | `true` |

---

### 4.3 完整输出示例

**场景**：患者确认怀孕，报告发热持续 3 天，37.8°C。

```json
{
  "decision_id": "risk_p8q3r2",
  "risk_level": "high",
  "safe_to_continue": false,
  "recommend_offline_visit": true,
  "recommend_human_review": false,
  "recommended_route": "offline_referral",
  "decision_reason": "患者确认怀孕（pregnant_confirmed），发热持续3天（Level 2红旗）。根据特殊人群规则，孕妇风险等级在medium基础上再提升一级至high。孕妇发热需排除感染性因素对胎儿的影响，线上无法充分评估，建议48小时内妇产科就诊。线上问诊不提供任何中药建议。",
  "evidence_refs": ["flag_b5c2d1", "fact_012", "fact_015"],
  "triggering_factors": [
    "red_flag_level2: 发热持续3天",
    "special_population: pregnant_confirmed（风险从medium升至high）",
    "symptom: fever=true, temperature=37.8, duration=3days"
  ],
  "population_adjustments": [
    {
      "population_tag": "pregnant_confirmed",
      "risk_delta": 1.0,
      "reason": "孕妇自动升一级：medium → high",
      "evidence_refs": ["fact_005"]
    }
  ],
  "timestamp": "2024-01-15T11:45:30Z",
  "issuing_agent": "safety-agent",
  "is_final": true
}
```

---

## 5. `safe_to_continue=false` 时的处置规程

### 5.1 触发后立即执行的动作序列

```
safe_to_continue 被设置为 false
    ↓
Step 1：调用 issue_risk_decision（含 is_final=true）
    ↓
Step 2：调用 set_case_stage，设置为 "handoff_required"
    ↓
Step 3：根据 recommended_route 选择输出路径：
    emergency    → 执行急诊提示（5.2节）
    offline_referral → 执行线下转诊提示（5.3节）
    human_review → 执行人工审核提示（5.4节）
    ↓
Step 4：停止所有以下操作：
    ✗ 不再调用 find_discriminative_questions
    ✗ 不再调用 rank_candidate_hypotheses（不再做收敛推理）
    ✗ 不再向患者发送新的问诊问题
    ✗ 不再更新 candidate_patterns / candidate_diseases
    ↓
Step 5：写入 audit_log（见5.5节）
    ↓
Step 6：可以执行的操作（仅以下）：
    ✓ 输出已收集信息的简要摘要
    ✓ 提供患者可见的安全提示
    ✓ 保存本次问诊记录供后续参考
    ✓ 响应患者的后续提问（仅做安全引导，不做新的问诊推进）
```

---

### 5.2 `emergency` 路径输出规范

输出给患者的急诊提示**必须包含以下所有要素**，缺一不可：

```
⚠️ 重要提示：请立即就医

根据您描述的情况，我们检测到以下需要紧急关注的信号：
• [具体红旗症状描述，如：您提到的胸痛伴随呼吸困难]

这类情况可能提示需要立即处理的紧急状况，
线上问诊无法为您提供足够的帮助。

请立即采取以下行动：
1. 拨打急救电话 120
2. 或立即前往最近的急诊室
3. 如身边有人，请让他们陪同您

请不要等待，也不要自行用药。
线上问诊已暂停，您的安全是最重要的。
```

**禁止**：
- ❌ 使用模糊语言（"可能需要注意一下"）
- ❌ 给患者选择余地（"您也可以先观察看看"）
- ❌ 继续接受问诊问题
- ❌ 给出任何中医建议

---

### 5.3 `offline_referral` 路径输出规范

```
根据您描述的情况，我们建议您[时效建议]前往线下医院就诊。

需要关注的情况：
• [具体风险因素描述，如：您的症状已持续超过3天，同时您正处于孕期]

建议就诊科室：[科室建议，如：妇产科 / 中医科 / 全科 / 相关专科]

原因说明：
[具体说明为什么线上无法充分处理，如：孕期用药安全需要面诊评估]

我们已整理了本次问诊的基本信息，您可以将其提供给接诊医生参考。

如果症状突然加重，请立即前往急诊。
```

**时效建议填写规范**：

| 风险程度 | 时效建议 |
|---------|---------|
| `risk_level=critical`（降级到 offline） | 立即（今天）|
| `risk_level=high` | 24 小时内 |
| `risk_level=medium`，症状有加重 | 48–72 小时内 |
| `risk_level=medium`，症状稳定 | 1 周内方便时 |

---

### 5.4 `human_review` 路径输出规范

```
您的情况需要我们的专业人员进一步评估。

[原因说明，选择适用的：]
• 您描述的情况比较复杂，需要更专业的判断
• 我们收集到的信息存在一些需要进一步澄清的地方
• 您的整体情况需要人工医生参与评估

我们已保存了本次问诊的全部信息。
专业人员将在[时效，如：工作日 24 小时内]与您联系。

在等待期间：
• 如症状明显加重，请立即前往医院就诊
• 如有紧急情况，请拨打 120

感谢您的配合。
```

---

### 5.5 `audit_log` 写入规范（`safe_to_continue=false` 时）

```json
{
  "entry_id": "audit_s9t6u4",
  "timestamp": "2024-01-15T11:45:30Z",
  "actor": "safety-agent",
  "action": "safe_to_continue_set_false",
  "summary": "风险决策：safe_to_continue 设置为 false，问诊已中止",
  "detail": {
    "risk_decision_id": "risk_p8q3r2",
    "risk_level": "high",
    "recommended_route": "offline_referral",
    "triggering_summary": "孕妇 + 发热3天（Level 2红旗）",
    "previous_risk_level": "low",
    "previous_safe_to_continue": true,
    "case_stage_before": "intake_in_progress",
    "case_stage_after": "handoff_required"
  }
}
```

---

## 6. 风险复核触发时机

`safety-agent` 的风险复核不只在固定阶段执行，以下时机都应触发：

### 6.1 必须触发风险复核的时机

| 时机 | 说明 |
|------|------|
| 导诊阶段完成后 | 首次完整风险评估 |
| 新的 Level 2 红旗写入 `red_flags` | 立即重新评估 |
| 新的特殊人群标签写入 `special_population_tags` | 立即重新评估 |
| 新的 P1 级矛盾写入 `contradictions` | 立即重新评估 |
| 每 5 轮动态追问后 | 定期复核，防止风险信号被忽略 |
| `intake_converged` 阶段进入时 | 生成总结前必须完整复核 |
| 患者主动提及新症状（且含高风险关键词）| 立即触发 |

### 6.2 轻量复核 vs. 完整复核

| 复核类型 | 触发场景 | 执行内容 |
|---------|---------|---------|
| **轻量复核** | 每轮追问后的例行检查 | 仅扫描新增 facts 是否触发 Level 1 红旗；检查当前 risk_level 是否需要升级 |
| **完整复核** | 关键节点（见6.1节）| 执行第 3 节完整综合逻辑；重新生成 RiskDecision；更新 case_state |

---

## 7. 风险评估中的不确定性处理

### 7.1 信息不足时的处理原则

当 `intake_completeness_score < 0.5` 时，风险评估面临信息不足的情况：

```
信息不足处置规则：
  - 不可因"信息不足"而降低已识别的风险等级
  - 不可以"信息太少，无法判断"为由推迟风险评估
  - 应按当前已知信息进行最保守的推断
  - 在 decision_reason 中明确标注"信息不足，按保守原则评估"
  - 风险评估后继续问诊，以补充关键信息
```

### 7.2 矛盾信息下的处理原则

当 `contradictions` 中存在未消解矛盾时：

```
矛盾信息处置规则：
  P1 unresolved 矛盾：
    - 涉及的症状按"更高风险"版本参与风险评估
    - 例：fever 矛盾（true vs false）→ 按 fever=true 评估风险

  P2/P3 unresolved 矛盾：
    - 按正常信息处理，但在 decision_reason 中注明不确定性
```

### 7.3 "可能性"vs"确定性"的处理

| 情况 | 处理 |
|------|------|
| 患者"可能"怀孕（`pregnant_unconfirmed`）| 按怀孕处理（使用 `pregnant_unconfirmed` 规则）|
| 患者"好像"有胸痛 | 按有胸痛处理，主动追问澄清 |
| 患者"以前"有抽搐，"不知道现在算不算"| 写入既往史，主动追问当前状态 |
| 患者否认但症状组合高度提示 | 标记临床可疑，不强行断言，但提高风险权重 |

---

## 8. 风险综合判断 vs. 图谱推理的边界

`safety-agent` 的职责是风险综合判断，与图谱推理服务有明确的职责边界：

| 职责 | 负责方 | 说明 |
|------|-------|------|
| 是否存在生命安全风险 | `safety-agent` | 基于红旗、特殊人群、用药 |
| 是否适合继续线上问诊 | `safety-agent` | 综合风险判断输出 |
| 证型/病机候选排序 | 图谱推理服务 | 不属于 safety-agent 职责 |
| 何时停止追问（收敛）| 图谱推理服务 | `convergence_score` 管理 |
| 具体中药禁忌核查 | `safety-agent` | 基于 `contraindication-reference` skill |
| 处方安全性评估 | `safety-agent` | 需要中药禁忌知识 |

> **重要**：`safety-agent` 不做证型推断，不影响候选排序。它只负责"继续是否安全"和"输出是否合规"。

---

## 9. 风险综合与其他 Skill 的联动

| 联动 Skill | 联动关系 |
|-----------|---------|
| `red-flags-protocol` | 红旗级别（Level 1/2/3）直接映射到风险等级；Level 1 → critical |
| `special-population-rules` | 特殊人群标签提供风险提升规则；各标签的 `risk_delta` 参数 |
| `visit-routing-guide` | 风险等级决定 `recommended_route` 取值；路径优先级规则 |
| `case-state-protocol` | `RiskDecision` 输出字段与 `case_state` 更新规范 |
| `contraindication-reference` | `check_contraindications` 工具的输出作为风险因子输入本协议 |
| `contradiction-detection-rules` | 矛盾数量和级别作为信息质量因子参与风险综合计算 |

---

## 10. 常见风险评估错误模式

| 错误模式 | 正确做法 |
|---------|---------|
| 患者否认症状后降低风险等级（已有 Level 1 红旗） | 红旗一旦记录不因否认而撤销，维持风险等级 |
| 因患者"感觉还好"而将 `safe_to_continue` 改回 `true` | `safe_to_continue=false` 不可被患者主观感受逆转 |
| 只看最新信息，忽略早期记录的红旗 | 风险评估必须全量扫描 `red_flags` 列表，不只看最新 |
| 特殊人群标签识别后忘记应用风险升级 | 每次 `issue_risk_decision` 前必须检查 `special_population_tags` |
| `decision_reason` 写"综合评估结果为 high" | 必须写出具体触发因素和推理逻辑 |
| 在 `safe_to_continue=false` 后继续更新候选排序 | 中止后不再执行收敛推理，只允许输出移交提示 |
| 多个中度风险叠加，仍只标记为 medium | 应用叠加升级规则，≥ 3 个中度因子升为 high |
| 信息不足时推迟风险评估 | 按保守原则立即评估，在 reason 中标注信息不足 |