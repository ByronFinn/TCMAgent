---
name: contradiction-detection-rules
description: "Rules for detecting four types of contradictions in patient-reported facts: logical (same fact stated twice differently), clinical (TCM-incompatible symptom combinations), temporal (timeline inconsistencies), and severity (extreme conflicting intensity claims). Includes P1/P2/P3 priority levels and ContradictionItem recording format. Use after updating normalized_facts with any new patient response."
---

# 矛盾检测规则（Contradiction Detection Rules）

> **Skill 用途**：本文件定义 `intake-agent` 在问诊过程中检测、记录和处理患者信息矛盾的完整操作规范。矛盾检测是保证 `case_state` 数据质量的关键环节，也是保护后续图谱推理不被错误信息污染的安全阀。

---

## 1. 核心原则

1. **检测，不裁判**：矛盾检测的职责是发现和记录矛盾，而不是判断哪条信息"正确"——两条矛盾信息都应保留，交由后续追问澄清。
2. **不删除早期记录**：一旦某条 `NormalizedFact` 已写入 `case_state`，即使后续出现与之矛盾的信息，也不得删除或覆盖旧记录。应在 `contradictions` 中追加矛盾记录。
3. **矛盾本身也是信息**：在中医临床中，"寒热错杂"、"虚实夹杂"等复杂证型本身就会产生看似矛盾的症状组合。矛盾不一定意味着患者在说谎，也可能反映真实的复杂证候。
4. **持续监测，全程检测**：矛盾检测不是只在固定节点执行，而是在每次新 `NormalizedFact` 写入后都需要扫描一遍与已有 facts 的关系。
5. **矛盾不阻断问诊**：除非矛盾严重到无法推进，否则不因矛盾中止问诊。标记矛盾，继续推进，并在合适时机自然追问澄清。
6. **不向患者指出矛盾的语气不得对抗**：追问澄清时使用温和、非对抗性话术（见第 6 节）。

---

## 2. 矛盾类型定义

### 2.1 逻辑矛盾（Logical Contradiction）

**定义**：同一 `normalized_key` 在不同轮次中被赋予了直接对立的 `normalized_value`（尤其是 `true` vs `false` 的直接翻转）。

**特征**：
- 语义上完全对立，无法同时为真
- 通常是患者前后表述不一致，而非中医复杂证候
- 置信度通常都较高（患者对两次都很确定）

**触发条件**：

```
同一 normalized_key 存在两条 fact，且：
  fact_1.normalized_value = true  AND  fact_2.normalized_value = false
  （或者反过来）
  AND
  两条 fact 均来自不同的 source_turn_id
```

**常见示例**：

| 早期记录 | 后续矛盾记录 | 说明 |
|---------|-----------|------|
| `fever: true`（第 1 轮）| `fever: false`（第 3 轮，"我没有发烧"）| 直接否定 |
| `loose_stool: true`（第 2 轮）| `loose_stool: false`（第 5 轮，"我大便是正常的"）| 直接否定 |
| `insomnia: true`（第 1 轮）| `insomnia: false`（第 4 轮，"我睡眠挺好的"）| 直接否定 |
| `headache: true`（主诉）| `headache: false`（第 3 轮，"其实我没有头痛"）| 主诉被否定 |

---

### 2.2 临床矛盾（Clinical Contradiction）

**定义**：两条 `NormalizedFact` 的组合，在中医临床语境下极少共存，且无合理的证型能解释其同时出现。

**特征**：
- 单独每条 fact 都可能是可信的（置信度高）
- 但组合在一起与已知中医证候规律严重不符
- 可能提示：患者对症状描述不准确、症状来自不同病程阶段、或确实存在复杂证型

**重要**：临床矛盾比逻辑矛盾更难判断，需要更谨慎处理。很多看似矛盾的组合在中医复杂证型中是可能的（如"上热下寒"）。只有在极端明显、无合理解释的情况下，才标记为临床矛盾。

**常见触发规则**：

| 矛盾组合 | 说明 | 可能的合理解释 |
|---------|------|-------------|
| `aversion_to_cold: true, severe` + `thirst_preference_cold: true, severe` + `fever: false` | 极度怕冷但喜冷饮，无发热 | 需区分：寒热错杂？描述不准？ |
| `spontaneous_sweating: true` + `night_sweating: true` + `aversion_to_cold: true, severe` + 无虚证特征 | 自汗盗汗并重且畏寒，无虚证背景 | 可能：阳虚兼阴虚（虚劳），但需确认 |
| `coating_absent: true`（阴虚）+ `aversion_to_cold: true, severe`（阳虚）+ `tongue_red: true`（热证）同时出现 | 舌象与全身症状极度矛盾 | 可能：患者对舌象描述不准确 |
| `constipation: true`（大便干）+ `watery_stool: true`（大便水样）在同一时段 | 同时便秘和腹泻在同一时段不可能 | 可能：不同时段的症状被混淆 |
| `poor_appetite: true` + `excessive_hunger: true` 同时极度表现 | 同时完全不想吃但又特别饿 | 消渴？还是描述混乱？ |

---

### 2.3 时序矛盾（Temporal Contradiction）

**定义**：患者提供的时间信息相互不一致，使得症状的先后顺序或病程时间无法自洽。

**示例**：

| 情况 | 说明 |
|------|------|
| "感冒 3 天" vs 后来说"已经好几周了" | 病程时间严重不符 |
| "昨天突然发烧" vs "我一直都有发烧，很久了" | 起病方式描述矛盾 |
| "这个症状是最近新出现的" vs 后来提到"这个毛病好几年了" | 新旧时间矛盾 |
| 月经"刚来完" vs 同时说"还没来" | 月经状态描述直接矛盾 |

---

### 2.4 程度矛盾（Severity Contradiction）

**定义**：同一症状的严重程度在不同描述中出现显著差异，且差异超出合理的描述误差范围。

**示例**：

| 早期描述 | 后期描述 | 判断 |
|---------|---------|------|
| "头痛非常严重，严重到影响工作" | "头痛有点轻微，不怎么影响" | 矛盾（程度极端不一致） |
| "发热有点低烧，37.5°C" | "高烧 39.5°C，很严重" | 矛盾（需确认是否同一次发热） |
| "大便稀有点严重，一天十几次" | "大便稍微有点稀，不影响" | 矛盾（程度极端不一致） |

**注意**：同一症状在不同时段的自然变化（如"之前严重，现在好了"）**不是**矛盾，但需要写入时序信息。

---

## 3. 矛盾严重程度分级

并非所有矛盾都需要同等对待，根据矛盾对推理影响程度分为三级：

### 3.1 P1 级矛盾（高影响，需优先追问）

**定义**：矛盾涉及的 `normalized_key` 直接影响当前最高优先级候选的区分，或涉及安全相关字段。

**触发条件（任一满足）**：

- 矛盾涉及红旗相关 key（如 `fever`、`chest_pain`、`hematemesis`）
- 矛盾涉及当前 `convergence_score` 最高候选的核心区分维度
- 矛盾涉及的两条 fact 都是 `confidence ≥ 0.8`（双方都很确定）
- 矛盾导致 `convergence_score` 显著下降（超过 0.15）

**处理**：在当前轮或下一轮优先追问澄清，不推迟。

---

### 3.2 P2 级矛盾（中影响，尽快追问）

**定义**：矛盾影响候选推理，但不是最关键的区分维度；或涉及的 fact 有至少一条置信度 < 0.8。

**处理**：在 3 轮以内安排追问，或在图谱推理指定追问时追问。

---

### 3.3 P3 级矛盾（低影响，记录追踪）

**定义**：矛盾对当前候选推理影响有限；涉及的 key 在当前阶段优先级低；或矛盾来自时序（前后不同时段）。

**处理**：写入 `contradictions` 记录，但不主动安排追问，仅在患者自然提及相关话题时顺带澄清。

---

## 4. 矛盾检测执行逻辑

### 4.1 检测时机

矛盾检测在以下时机**自动触发**：

| 时机 | 说明 |
|------|------|
| 每次新 `NormalizedFact` 写入 `case_state` 后 | 检查新 fact 与已有所有 facts 的关系 |
| `update_case_facts` 工具调用完成后 | 系统层面的自动检查 |
| 图谱推理服务重算候选后 | 检查是否新增矛盾导致候选异常分布 |
| `safety-agent` 风险复核阶段 | 全量扫描，确保无漏检矛盾 |

---

### 4.2 检测扫描逻辑

```
新 fact 写入后：

Step 1：【逻辑矛盾扫描】
  对新 fact 的 normalized_key，在已有 facts 中查找：
    - 相同 normalized_key
    - normalized_value 与新 fact 相反（true vs false）
    - source_turn_id 不同（不同轮次的陈述）
  → 发现匹配 → 写入 ContradictionItem（类型：logical）

Step 2：【临床矛盾扫描】
  将新 fact 与已有 facts 组合，检查是否触发第 2 节的临床矛盾规则
  → 发现触发 → 写入 ContradictionItem（类型：clinical）
  注意：只触发有明确规则定义的组合，不做自由推断

Step 3：【时序矛盾扫描】
  如新 fact 包含时间相关信息（duration、onset、temporal_pattern），
  与已有时间信息对比是否自洽
  → 发现冲突 → 写入 ContradictionItem（类型：temporal）

Step 4：【程度矛盾扫描】
  对相同 normalized_key，比较新旧 fact 的 severity 取值：
  若差异 ≥ 2 级（如 mild vs severe）
  → 写入 ContradictionItem（类型：severity）

Step 5：【矛盾分级】
  对每个新检测到的矛盾，评定 P1 / P2 / P3 级别（见第 3 节）

Step 6：【更新追问队列】
  P1 级矛盾 → 插入追问队列最高优先级
  P2 级矛盾 → 插入追问队列普通优先级
  P3 级矛盾 → 仅记录，不加入主动追问队列
```

---

### 4.3 不应标记为矛盾的情况

以下情况**不应触发**矛盾记录：

| 情况 | 原因 |
|------|------|
| 同一 key，新 fact 置信度明显更高，旧 fact 是模糊描述 | 视为信息更新，不是矛盾（但旧记录保留） |
| 两条描述的时段明确不同（"以前怕冷，最近不怕了"）| 是症状变化，不是矛盾；应更新时间标注 |
| 症状在"某条件下存在/不存在"（"运动后出汗，静息不出"）| 是条件性描述，记录条件维度，不标矛盾 |
| 中医复杂证型可解释的寒热虚实并存（如"上热下寒"）| 不是矛盾，写入 `audit_log` 备注复杂证型可能性 |
| 程度差异在 1 级以内（mild vs moderate）| 在描述误差范围内，不标矛盾 |
| 否认不相关症状（"我没有头痛" 不否定其他症状）| 正常否定性表述，非矛盾 |

---

## 5. ContradictionItem 写入规范

### 5.1 数据结构

每条矛盾记录以 `ContradictionItem` 格式写入 `case_state.contradictions`：

```python
class ContradictionItem:
    contradiction_id: str          # 唯一 ID，格式：contr_{uuid4_short}
    contradiction_type: str        # 枚举：logical / clinical / temporal / severity
    priority: str                  # 枚举：P1 / P2 / P3
    field: str                     # 涉及的主 normalized_key
    related_fields: list[str]      # 临床矛盾涉及的多个 key（可为空列表）
    previous_fact_id: str          # 早期 fact 的 fact_id
    previous_value: Any            # 早期 fact 的 normalized_value
    new_fact_id: str               # 新 fact 的 fact_id
    new_value: Any                 # 新 fact 的 normalized_value
    previous_turn_id: str | None   # 早期描述的轮次 ID
    new_turn_id: str | None        # 新描述的轮次 ID
    reason: str                    # 矛盾描述（人类可读）
    status: str                    # 枚举：unresolved / clarified / accepted_complex
    resolution: str | None         # 消解说明（仅 status != unresolved 时填写）
    detected_at_stage: str         # 检测时的 case_stage
    timestamp: str                 # ISO 8601 时间戳
```

### 5.2 status 字段枚举说明

| status 值 | 含义 | 何时设置 |
|----------|------|---------|
| `unresolved` | 矛盾已记录，尚未澄清 | 矛盾初次检测时 |
| `clarified` | 患者已澄清，矛盾已消解 | 追问得到明确答案后 |
| `accepted_complex` | 矛盾被认定为中医复杂证型表现，不需要消解 | 图谱推理判断为合理复杂证候 |

**注意**：`status` 只能从 `unresolved` 向前推进，不可从 `clarified` 退回 `unresolved`。

---

### 5.3 写入示例

**场景**：患者第 1 轮说"有发烧"，第 3 轮说"我没有发烧"。

```json
{
  "contradiction_id": "contr_x7k2m1",
  "contradiction_type": "logical",
  "priority": "P1",
  "field": "fever",
  "related_fields": [],
  "previous_fact_id": "fact_001",
  "previous_value": true,
  "new_fact_id": "fact_012",
  "new_value": false,
  "previous_turn_id": "turn_001",
  "new_turn_id": "turn_003",
  "reason": "患者在 turn_001 描述有发烧（fever: true），在 turn_003 明确否认（fever: false），两次陈述直接矛盾",
  "status": "unresolved",
  "resolution": null,
  "detected_at_stage": "intake_in_progress",
  "timestamp": "2024-01-15T10:23:45Z"
}
```

---

**场景**：患者描述同时"极度怕冷（severe）"和"口渴只喝冷水（cold preference, high confidence）"，无合理虚实解释。

```json
{
  "contradiction_id": "contr_y9p3q2",
  "contradiction_type": "clinical",
  "priority": "P2",
  "field": "aversion_to_cold",
  "related_fields": ["thirst_preference_cold"],
  "previous_fact_id": "fact_003",
  "previous_value": true,
  "new_fact_id": "fact_008",
  "new_value": "cold",
  "previous_turn_id": "turn_002",
  "new_turn_id": "turn_004",
  "reason": "极度畏寒（寒证特征）与口渴明显喜冷饮（热证特征）并存，两者均为高置信度，临床上寒热错杂但程度需进一步确认是否为虚实组合导致",
  "status": "unresolved",
  "resolution": null,
  "detected_at_stage": "intake_in_progress",
  "timestamp": "2024-01-15T10:31:22Z"
}
```

---

## 6. 矛盾处理策略

### 6.1 核心策略：标记后继续，追问澄清

矛盾处理的正确流程是：

```
检测到矛盾
    ↓
写入 ContradictionItem（status: unresolved）
    ↓
评定优先级（P1 / P2 / P3）
    ↓
P1 → 尽快安排追问（当前或下一轮）
P2 → 3 轮内安排追问
P3 → 记录，被动等待
    ↓
继续正常问诊（不阻断）
    ↓
得到澄清 → 更新 status 为 clarified，写入 resolution
无法澄清 → 保持 unresolved，交由人工审核
```

### 6.2 不可采取的处理方式

| 禁止行为 | 原因 |
|---------|------|
| 删除早期 fact，用新 fact 替换 | 破坏数据完整性，可能删除正确信息 |
| 不记录矛盾，直接采信新信息 | 丢失矛盾证据，影响后续推理质量 |
| 不记录矛盾，直接采信旧信息 | 同上 |
| 立即停止问诊等待矛盾消解 | 降低问诊效率，大多数矛盾可以边追问边继续 |
| 在候选推理中忽略矛盾（两者都用） | 可能导致候选推理基于互斥的事实 |
| 在患者面前直接说"您前后矛盾" | 对抗性语气，影响患者配合度 |

---

### 6.3 矛盾对候选推理的影响规则

存在未消解矛盾时，候选推理服务应遵循以下规则：

| 矛盾状态 | 对推理的影响 |
|---------|------------|
| P1 级 unresolved | 涉及的 key 不参与候选评分，或显著降低权重；`convergence_score` 不应虚高 |
| P2 级 unresolved | 涉及的 key 以较低权重参与推理，结果需标注不确定性 |
| P3 级 unresolved | 对当前推理影响忽略，正常参与 |
| clarified | 按澄清后的 fact 参与推理，废弃的 fact 权重清零 |
| accepted_complex | 两条 fact 均可参与推理，体现为复杂证型候选权重提升 |

---

### 6.4 矛盾澄清追问话术

矛盾澄清的话术必须温和、非对抗性。参见 `question-phrasing-guide` skill 第 3.2 节场景 E。

**通用追问框架**：

```
[软性引入，不指责] + [提到两次不同的描述] + [开放性请患者解释]
```

**场景 1：逻辑矛盾（先说有后说没有）**

```
"我想再确认一下您刚才提到的情况——
您之前提到有发烧，后来又说没有发烧，
我想更准确地了解一下，您现在有没有发烧，
或者这两个情况是发生在不同时间的？"
```

---

**场景 2：临床矛盾（寒热症状并存）**

```
"您提到有时候感觉比较怕冷，
但同时也说口渴的时候更想喝冷的，
这两种感觉都有发生吗？
比如，是身体某些部位觉得冷，同时又觉得口干想喝凉的？"
```

---

**场景 3：时序矛盾（病程时间不一致）**

```
"我想确认一下这个症状的时间——
您之前说是最近两天才出现的，
但后来提到已经好几周了，
这个症状大概是什么时候开始的呢？"
```

---

**场景 4：程度矛盾（轻重描述不一致）**

```
"您对头痛的描述，有时候说得比较严重，
有时候又说还好，影响不大，
我想了解一下现在这个阶段，头痛的程度大概是怎么样的？"
```

---

### 6.5 澄清结果的处理

追问得到明确答案后，按以下规则更新 `ContradictionItem`：

**情况 A：患者明确了哪条是准确的**

```
1. 将 ContradictionItem.status 更新为 "clarified"
2. 写入 ContradictionItem.resolution：
   "患者确认：[准确的那条描述]，
    [另一条] 系 [原因，如：早期描述不准确/不同时段的状态]"
3. 将废弃 fact 的 confidence 降低到 0.1（不删除，降权）
4. 写入 audit_log
```

**情况 B：患者确认两者都存在（复杂证型）**

```
1. 将 ContradictionItem.status 更新为 "accepted_complex"
2. 写入 resolution：
   "患者确认两种情况同时存在，可能为寒热错杂/虚实夹杂等复杂证型，
    待图谱推理进一步分析"
3. 两条 fact 均保持原始 confidence，均参与推理
4. 在 audit_log 中记录复杂证型可能性
```

**情况 C：患者无法澄清（"不知道"、"说不清"）**

```
1. ContradictionItem.status 维持 "unresolved"
2. 不再主动追问该矛盾（避免重复追问增加疲劳）
3. 若为 P1 级且无法消解 → 考虑升级为 human_review
4. 若为 P2/P3 级 → 接受不确定性，两条 fact 以较低权重参与推理
```

---

## 7. 常见矛盾模式速查

### 7.1 高频逻辑矛盾模式

| 矛盾模式 | 检测键 | 触发说明 |
|---------|-------|---------|
| 发热先说有后说没有 | `fever` | 患者可能在描述不同时段，先确认时段 |
| 怕冷先说有后说没有 | `aversion_to_cold` | 同上，常见于轻微症状的描述误差 |
| 失眠先说有后说没有 | `insomnia` | 患者标准不同（"算不算失眠"） |
| 大便稀/干 反转 | `loose_stool`、`constipation` | 可能描述不同时段 |
| 有无痰矛盾 | `cough_with_phlegm` | 咳嗽痰量波动，时段问题 |
| 食欲先说好后说差 | `poor_appetite` | 饮食情况随时间波动 |
| 有无口渴 反转 | `thirst` | 程度感知差异 |

---

### 7.2 高频临床矛盾模式

| 矛盾组合 | 检测 key 对 | 中医解读提示 |
|---------|----------|------------|
| 畏寒（severe）+ 喜冷饮（high conf） | `aversion_to_cold` + `thirst_preference_cold` | 真寒假热？寒热错杂？需深入询问 |
| 盗汗（阴虚典型）+ 畏寒肢冷（阳虚典型）同时极端 | `night_sweating` + `cold_limbs, severe` | 阴阳两虚？描述混淆？ |
| 苔厚腻（湿实）+ 少苔/无苔（阴虚）并报 | `coating_thick_greasy` + `coating_absent` | 患者舌象描述不准确？不同时间？ |
| 大便干结（肠燥）+ 大便水样（脾虚寒湿）同时高信度 | `constipation` + `watery_stool` | 时段混淆，需确认是否交替 |
| 舌红（热）+ 脉迟（寒），患者描述中两者并重 | `tongue_red` + `cold_limbs, severe` | 真热假寒？上热下寒？ |

---

### 7.3 特殊人群常见矛盾模式

| 人群 | 常见矛盾原因 | 处理建议 |
|------|------------|---------|
| 老年患者 | 认知问题导致前后描述不一致 | 降低单条 fact 置信度，增加追问次数 |
| 家属代述的儿童 | 家属描述不准确或混淆不同时段 | 写入 `information_source: parent_reported`，适当降权 |
| 情绪紧张的患者 | 症状被夸大或遗漏 | 温和追问，避免强化极端描述 |
| 有医学背景的患者 | 可能混用专业术语造成理解偏差 | 用白话验证专业术语的理解是否一致 |

---

## 8. 矛盾统计与会话质量指标

### 8.1 矛盾计数的意义

`case_state` 中 `contradictions` 列表的数量和状态，是问诊质量的重要指标：

| 指标 | 说明 | 参考阈值 |
|------|------|---------|
| `unresolved P1` 矛盾数量 | 影响核心推理的未消解矛盾 | > 2 条 → 考虑 `human_review` |
| `unresolved` 矛盾总数 | 整体信息质量 | > 5 条 → 显示在问诊摘要中，提示信息不可靠 |
| `clarified` 比例 | 矛盾消解率 | < 50% 且 P1 矛盾多 → 考虑停止推进 |

### 8.2 对 convergence_score 的影响

图谱推理服务在计算 `convergence_score` 时，未消解矛盾会作为负向因子：

```
convergence_score 计算中：
  - 每条 P1 unresolved 矛盾：-0.10 至 -0.15
  - 每条 P2 unresolved 矛盾：-0.05 至 -0.08
  - P3 矛盾：不影响评分

因此：即使候选集合已高度收敛，若存在多条 P1 未消解矛盾，
convergence_score 也不应显示为"已收敛"状态。
```

---

## 9. 矛盾检测与其他 Skill 的联动

| 联动 Skill | 联动关系 |
|-----------|---------|
| `symptom-normalization-protocol` | 归一化完成后，矛盾检测立即触发；低置信度 fact 产生的矛盾优先级降低 |
| `question-phrasing-guide` | P1/P2 矛盾的追问话术规范，见该 skill 第 3.2 节场景 E |
| `case-state-protocol` | `ContradictionItem` 写入规范；`audit_log` 必须记录矛盾检测事件 |
| `risk-synthesis-protocol` | P1 级大量未消解矛盾可触发 `human_review` 路径 |
| `visit-routing-guide` | 矛盾数量和质量是 `human_review` 路径的触发条件之一 |

---

## 10. audit_log 矛盾相关记录规范

每次矛盾检测事件必须写入 `audit_log`：

```json
{
  "entry_id": "audit_z5w8r3",
  "timestamp": "2024-01-15T10:23:45Z",
  "actor": "intake-agent",
  "action": "contradiction_detected",
  "summary": "检测到逻辑矛盾：fever 字段在 turn_001 和 turn_003 存在直接冲突（P1 级）",
  "detail": {
    "contradiction_id": "contr_x7k2m1",
    "contradiction_type": "logical",
    "priority": "P1",
    "field": "fever",
    "previous_turn": "turn_001",
    "new_turn": "turn_003",
    "action_taken": "矛盾记录已写入，已加入优先追问队列"
  }
}
```

矛盾消解时也需写入 `audit_log`：

```json
{
  "entry_id": "audit_q2p7n6",
  "timestamp": "2024-01-15T10:35:12Z",
  "actor": "intake-agent",
  "action": "contradiction_resolved",
  "summary": "矛盾已消解：fever 字段矛盾，患者确认当前无发烧（早期描述为不同时段）",
  "detail": {
    "contradiction_id": "contr_x7k2m1",
    "resolution_type": "clarified",
    "accepted_fact_id": "fact_012",
    "deprecated_fact_id": "fact_001",
    "deprecated_fact_new_confidence": 0.1
  }
}
```
