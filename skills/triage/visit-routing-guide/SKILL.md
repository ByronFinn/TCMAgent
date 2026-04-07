---
name: visit-routing-guide
description: "Visit route decision guide defining four paths: online_continue, offline_referral, emergency, human_review. Includes trigger conditions, priority order (emergency > human_review > offline_referral > online_continue), and decision flowchart. Use to determine the recommended_route after initial triage assessment."
---

# 就诊路径决策指南（Visit Routing Guide）

> **Skill 用途**：本文件定义 `triage-agent` 在完成红旗筛查和特殊人群识别后，用于决定患者最终就诊路径的判断规则。就诊路径决策是导诊阶段的最终输出，决定后续流程走向。

---

## 1. 核心原则

1. **路径决策保守优先**：当两条路径均可选时，选择更保守（更安全）的那条。
2. **路径一旦确定立即通知患者**：不应在内部记录了路径后还继续普通问诊，患者应及时知晓。
3. **路径可以升级，不可降级**：如后续信息使风险升高，路径应升级；已确定高风险路径后，不因新信息良好而降回低级路径。
4. **路径决策必须工具化**：使用 `classify_visit_route` 工具输出路径，不应由 Agent 在自然语言中隐含决策。
5. **路径与风险等级一一对应**：每次 `issue_risk_decision` 必须同时包含 `recommended_route` 字段。

---

## 2. 四条就诊路径定义

### 2.1 路径概览

| `recommended_route` 值 | 中文名称 | 触发条件 | 对应风险等级 |
|------------------------|---------|---------|------------|
| `online_continue` | 继续线上问诊 | 无红旗，无高危特殊人群，症状适合线上 | `none` / `low` |
| `offline_referral` | 建议转线下就诊 | 中度风险，或症状超出线上评估能力 | `medium` / `high` |
| `emergency` | 建议立即急诊 | 严重红旗命中，`safe_to_continue=false` | `critical` |
| `human_review` | 建议转人工审核 | 信息复杂/矛盾/超出系统能力边界 | `low` ~ `high` |

---

## 3. `online_continue`（继续线上问诊）

### 3.1 适用条件

以下**全部**条件满足，方可选择 `online_continue`：

- [ ] 无任何 Level 1 严重红旗
- [ ] 无任何 Level 2 中度风险标志
- [ ] `risk_level` 为 `none` 或 `low`
- [ ] `safe_to_continue` 为 `true` 或尚未评估（`null`）
- [ ] 非新生儿（`neonate`）、非婴儿（`infant`）
- [ ] 非确认孕妇（`pregnant_confirmed`）——孕妇至少需要 `offline_referral`
- [ ] 非 CKD 4–5 期患者
- [ ] 非器官移植患者
- [ ] 患者描述症状持续时间在合理范围内（无慢性病史时 < 4 周）
- [ ] 症状性质属于常见中医门诊范畴（见 3.2 节）

### 3.2 适合线上中医问诊的症状范畴

以下类型症状适合继续线上问诊：

| 症状类别 | 示例 |
|---------|------|
| 普通外感 | 轻中度感冒、鼻炎发作、咽炎（无呼吸困难） |
| 消化系统（非急腹症） | 慢性胃炎调理、消化不良、功能性腹泻 |
| 睡眠情志 | 失眠、焦虑状态（无自伤倾向） |
| 痛证（非急性剧痛） | 慢性头痛调理、颈肩腰背酸痛、痛经调理 |
| 月经调理 | 非孕期的月经不调、痛经、更年期综合征 |
| 皮肤 | 慢性湿疹、荨麻疹（非急性过敏反应） |
| 体质调理 | 气虚、阳虚、阴虚体质的日常调理咨询 |
| 慢病辅助调理 | 高血压、糖尿病已控制稳定的辅助调理（明确不替代西医主治） |

### 3.3 继续线上时的标准提示（向患者）

```
我们可以继续在线上为您收集更多信息，帮助了解您的身体状况。

请放心，如果在问诊过程中发现需要特别关注的情况，
我们会及时告知您。
```

---

## 4. `offline_referral`（建议转线下就诊）

### 4.1 触发条件（满足任一即触发）

#### 4.1.1 症状相关

- 发热持续 > 3 天未缓解
- 慢性咳嗽 > 3 周
- 不明原因体重下降 > 5kg / 月
- 腹痛持续 > 48 小时（非红旗级别）
- 关节肿胀伴活动受限（需影像学评估）
- 头痛进行性加重（持续数周）
- 新发肿块发现（需触诊 / 影像）
- 皮肤或黏膜出血点（非外伤）
- 视力下降或视野改变

#### 4.1.2 特殊人群相关

- 确认怀孕（`pregnant_confirmed`）——所有中医问诊均需线下
- 可能怀孕（`pregnant_unconfirmed`）——建议先线下确认孕情
- 婴儿期（`infant`，29天–1岁）——建议儿科门诊
- 幼儿（`toddler`）发热 > 38.5°C 持续超 24 小时
- 高龄（`elderly_high_risk`）且症状模糊或加重
- 慢性肾病 CKD 3–4 期有症状加重
- 多药联用（`polypharmacy`）且涉及潜在中西药相互作用
- 肿瘤患者（`oncology_patient`）——建议整合肿瘤科处理

#### 4.1.3 信息质量相关

- 患者提供的症状信息需体格检查才能判断（如腹部包块触诊）
- 症状需要实验室或影像检查才能鉴别（如黄疸原因、贫血原因）
- 患者既往诊断不明确，当前症状与已知诊断不符

#### 4.1.4 系统能力边界

- 患者明确要求处方或用药方案（线上中医问诊不开具正式处方）
- 患者病情需要中西医协同，但西医情况不明

### 4.2 offline_referral 的时效建议

根据紧迫程度，`offline_referral` 应给出时效建议：

| 紧迫程度 | 建议时效 | 适用情况 |
|---------|---------|---------|
| 紧急（非急诊） | 24 小时内 | 发热 3 天、腹痛持续等 |
| 较急 | 48–72 小时内 | 进行性症状加重、孕妇任何不适 |
| 一般 | 1 周内 | 慢性症状需确诊、处方需求 |
| 建议性 | 方便时 | 调理类问题需线下望闻切完整四诊 |

### 4.3 转线下时的标准提示（向患者）

```
根据您描述的情况，我们建议您[时效建议]前往线下医院
[科室建议，如：中医科 / 全科 / 相关专科]就诊。

原因：[具体说明，如：您的症状持续时间较长，需要结合
面诊和必要的检查才能做出准确判断。]

在此之前，我们已为您整理了本次问诊的基本信息，
您可以将其提供给接诊医生参考。
```

---

## 5. `emergency`（建议立即急诊）

### 5.1 触发条件

`emergency` 路径由**严重红旗命中**自动触发，详见 `skills/triage/red-flags-protocol/SKILL.md` 第 2 节。

触发 `emergency` 时必须：
- `risk_level = "critical"`
- `safe_to_continue = false`
- `case_stage = "handoff_required"`
- 立即停止所有普通问诊逻辑

### 5.2 急诊路径的强制输出

触发 `emergency` 时，系统输出必须包含以下内容，**不得省略**：

1. **明确的紧急提示**（醒目，不可用模糊语言）
2. **建议立即拨打急救电话 120** 或前往最近急诊室
3. **具体说明触发原因**（是什么症状让我们建议急诊）
4. **如有陪同人员，建议陪同就医**
5. **不建议等待观察，不建议自行用药**

### 5.3 急诊时的标准提示（向患者）

```
⚠️ 重要提示：根据您描述的症状，我们建议您立即就医。

您提到的[具体症状描述]可能提示需要紧急处理的情况，
不适合继续线上等待。

请立即：
• 拨打急救电话 120，或
• 前往最近的急诊室就诊

如果身边有人，请让他们陪同您。
请不要等待或自行用药，您的安全是最重要的。
```

### 5.4 急诊路径不可被患者否定

若患者表示"我没那么严重"或"我不想去急诊"，系统不可撤销 `emergency` 路径，应回应：

```
我们理解您可能感觉还好，但您描述的[症状]是我们必须
认真对待的信号。

我们无法替您做最终决定，但强烈建议您至少拨打
120 咨询，由专业急救人员帮您判断是否需要处理。

系统记录显示当前状态需要线下评估，
线上问诊暂时无法继续。
```

---

## 6. `human_review`（建议转人工审核）

### 6.1 触发条件（满足任一即触发）

#### 6.1.1 信息可靠性问题

- 患者描述前后严重矛盾，`contradictions` 中存在多条未消解矛盾
- 患者表达极度混乱，无法提取有效结构化信息
- 患者不配合关键安全问题的回答
- 强烈怀疑信息失真（如代替他人问诊但信息严重缺失）

#### 6.1.2 系统判断边界问题

- `convergence_score` 长期 < 0.3 且已超过 8 轮追问
- 候选集合发散，多个高置信度候选持续并列，图谱无法区分
- 症状组合极为罕见，图谱候选不足
- 患者主动要求人工医生介入

#### 6.1.3 医学复杂度超限

- 多个系统同时出现复杂症状，超出常见中医门诊范畴
- 症状高度提示需要多学科会诊的情况
- 患者有复杂手术史、化疗史，当前症状难以归因
- 存在高风险特殊人群标记，但症状又无法明确分类

#### 6.1.4 伦理与安全边界

- 患者提及强烈自杀/自伤意念（此时同时触发 Level 1 红旗，`emergency` 优先）
- 患者要求系统给出超越平台能力的诊断或处方承诺
- 疑似涉及未成年人的监护问题

### 6.2 human_review 与其他路径的优先级

```
emergency > human_review > offline_referral > online_continue
```

当多个路径同时满足触发条件时，取优先级最高的路径。

**特例**：`human_review` + `emergency` 同时触发时，输出 `emergency`，
并在 `audit_log` 中标注"同时满足 human_review 条件"。

### 6.3 转人工时的标准提示（向患者）

```
您的情况需要由我们的专业人员进行进一步评估。

[原因说明，如：您描述的症状比较复杂，需要更专业的
判断才能为您提供准确的建议。]

我们已为您保存了本次问诊的所有信息，
专业人员将在[时效，如：工作日 24 小时内]与您联系。

如果在等待期间症状明显加重，请立即前往医院就诊。
```

---

## 7. 路径决策执行逻辑

### 7.1 完整决策流程

```
Step 1：读取 case_state（risk_level、red_flags、special_population_tags、contradictions）
    ↓
Step 2：检查是否有 Level 1 红旗或 risk_level=critical
    ├─ 是 → recommended_route = "emergency"，流程结束
    └─ 否 → 继续
    ↓
Step 3：检查 human_review 触发条件
    ├─ 满足任一 → 记录 human_review 候选路径，继续评估
    └─ 否 → 继续
    ↓
Step 4：检查 offline_referral 触发条件
    ├─ 满足任一 → recommended_route = "offline_referral"，
    │             若同时满足 human_review，叠加标记
    └─ 否 → 继续
    ↓
Step 5：检查是否满足 online_continue 全部条件
    ├─ 全部满足 → recommended_route = "online_continue"
    └─ 存在任何疑虑 → 默认 "offline_referral"（保守原则）
    ↓
Step 6：若第 3 步记录了 human_review 候选，且当前路径为 offline_referral：
    └─ 升级为 recommended_route = "human_review"
    ↓
Step 7：调用 classify_visit_route 工具，写入 case_state
Step 8：调用 issue_risk_decision 工具，包含 recommended_route 字段
Step 9：向患者输出对应路径提示
```

### 7.2 决策结果写入规范

路径决策完成后，以下字段必须同步更新到 `case_state`：

| 字段 | 更新内容 |
|------|---------|
| `recommended_route` | 路径取值（见第 2 节枚举） |
| `risk_level` | 对应风险等级 |
| `safe_to_continue` | `true` 仅适用于 `online_continue`；其余路径需评估 |
| `recommend_offline_visit` | `offline_referral` 和 `emergency` 时为 `true` |
| `recommend_human_review` | `human_review` 时为 `true` |
| `case_stage` | `triaged`（正常导诊完成）或 `handoff_required`（emergency/human_review） |

---

## 8. 路径决策的审计要求

每次路径决策必须写入 `audit_log`，包含：

```json
{
  "actor": "triage-agent",
  "action": "route_decision",
  "summary": "就诊路径决策：[recommended_route]",
  "detail": {
    "recommended_route": "offline_referral",
    "risk_level": "medium",
    "triggering_conditions": ["发热持续3天", "pregnant_confirmed"],
    "safe_to_continue": false,
    "decision_rationale": "患者已确认怀孕，且发热持续超过3天，风险等级自动提升，建议尽快线下妇产科或中医科联合评估"
  }
}
```

---

## 9. 路径决策常见场景示例

### 场景 A：普通外感，无特殊情况

```
主诉：感冒两天，有点怕冷，鼻塞，没发烧
红旗：无
特殊人群：无
→ recommended_route = "online_continue"
→ risk_level = "low"
→ safe_to_continue = true
```

### 场景 B：孕妇外感

```
主诉：感冒三天，轻微发热 37.8°C，鼻塞
红旗：无 Level 1
特殊人群：pregnant_confirmed
→ 孕妇风险自动提升：low → medium
→ recommended_route = "offline_referral"
→ 建议 48 小时内妇产科或中医科（有孕期问诊资质）就诊
→ safe_to_continue = false（孕期不给中药建议）
```

### 场景 C：突发剧烈头痛

```
主诉：刚才突然头痛得很厉害，从没这么痛过
红旗：Level 1（thunderclap_headache）
→ recommended_route = "emergency"
→ risk_level = "critical"
→ safe_to_continue = false
→ 立即停止问诊，输出急诊提示
```

### 场景 D：慢性症状，信息矛盾多

```
主诉：各种症状，反复描述不一致
红旗：无
特殊人群：elderly_high_risk
矛盾记录：5条未消解矛盾
→ human_review 触发（信息矛盾 + 老年模糊症状）
→ recommended_route = "human_review"
→ risk_level = "medium"
→ safe_to_continue = false
```

### 场景 E：发热 3 天，老年患者

```
主诉：发烧三天了，37.8–38.2°C，没什么其他症状
红旗：Level 2（发热持续 3 天）
特殊人群：elderly_high_risk（age=78）
→ offline_referral 触发（发热持续 + 老年）
→ recommended_route = "offline_referral"
→ 建议 24 小时内线下就诊
→ risk_level = "high"
→ safe_to_continue = false
```

---

## 10. 路径决策与其他 Skill 的联动

| 联动 Skill | 联动关系 |
|-----------|---------|
| `red-flags-protocol` | Level 1 红旗直接触发 `emergency`；Level 2 触发 `offline_referral` |
| `special-population-rules` | 特殊人群标签影响风险等级，进而影响路径选择 |
| `risk-synthesis-protocol` | 综合风险判断的最终输出包含 `recommended_route` |
| `case-state-protocol` | 路径决策结果写入 `case_state` 的规范字段 |

---

## 11. 路径取值速查表

| `recommended_route` | 含义 | `safe_to_continue` | `case_stage` 结果 |
|--------------------|------|--------------------|------------------|
| `online_continue` | 继续线上问诊 | `true` | `triaged` → 进入 `initial_candidates_generated` |
| `offline_referral` | 建议线下就诊 | `false`（通常）| `triaged` 或 `handoff_required` |
| `emergency` | 立即急诊 | `false` | `handoff_required` |
| `human_review` | 转人工审核 | `false` | `handoff_required` |