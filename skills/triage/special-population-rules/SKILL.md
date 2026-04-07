---
name: special-population-rules
description: "Rules for identifying and handling special patient populations: pregnant women, infants/children, elderly (75+), CKD, liver disease, anticoagulants, immunosuppressants, oncology. Includes risk elevation matrix, population_tag values, and medication prohibition lists. Use when tagging special populations and when evaluating risk level adjustments."
---

# 特殊人群规则（Special Population Rules）

> **Skill 用途**：本文件定义 `triage-agent` 和 `safety-agent` 在识别特殊高风险人群时必须遵守的评估规则、风险提升逻辑和 `population_tag` 标记规范。特殊人群识别必须在红旗筛查的同时或之后立即完成。

---

## 1. 核心原则

1. **主动询问，不被动等待**：特殊人群信息（如是否怀孕、是否儿童）不能依赖患者主动披露，`triage-agent` 必须主动询问。
2. **风险只升不降**：特殊人群标记一旦确认，风险等级只能保持或提升，不能因后续其他信息良好而降低。
3. **标记即生效**：`population_tag` 写入 `case_state` 后，后续所有推理步骤必须考虑该标记的影响。
4. **不确认不代表不存在**：如患者对特殊人群问题（如孕期）给出模糊回答，应按"可能存在"处理，在 `patient_profile.is_pregnant` 字段保持 `null` 并写入 `population_tag: pregnant_unconfirmed`。
5. **特殊人群不等于禁止线上问诊**：特殊人群标记的作用是提高风险敏感度和约束建议范围，不是一律拒绝服务。

---

## 2. 孕妇（Pregnant Women）

### 2.1 识别规则

**必须主动询问的条件**：
- 患者性别为女性（`gender = "female"`）
- 年龄在 12–55 岁之间（育龄期范围）

**询问话术**：
> "请问您目前是否怀孕，或者近期有可能怀孕？"

**字段更新**：
- 确认怀孕：`patient_profile.is_pregnant = true`
- 确认未孕：`patient_profile.is_pregnant = false`
- 不确定/拒绝回答：`patient_profile.is_pregnant = null`，写入 `population_tag: pregnant_unconfirmed`

---

### 2.2 风险提升规则

| 原始风险等级 | 孕妇提升后 | 说明 |
|------------|-----------|------|
| `none` | `low` | 任何症状均需提高基础关注 |
| `low` | `medium` | 自动提升一级 |
| `medium` | `high` | 自动提升一级 |
| `high` | `critical` | 直接进入 critical，`safe_to_continue=false` |
| `critical` | `critical` | 已是最高，维持，立即转急诊 |

> **规则**：对孕妇患者，任何症状的风险等级在最终 `issue_risk_decision` 之前必须自动提升一级。

---

### 2.3 特殊禁忌约束

对已确认或可能怀孕的患者，以下内容必须遵守：

- **禁止给出任何具体中药建议**（无论是否看起来温和）
- **禁止给出任何针灸穴位建议**（部分穴位为妊娠禁忌）
- **任何推测性证型不得输出给患者作为治疗参考**
- **必须建议线下妇产科或中医科联合诊治**

若问诊过程中需要提及症状可能的处理方向，必须加注：
> "⚠️ 您目前处于孕期，任何中药或治疗方案必须在专业医师指导下进行，请勿自行用药。"

---

### 2.4 孕期特殊红旗

以下症状在孕妇中必须直接升级为 Level 1 红旗：

| 症状 | 原因 |
|------|------|
| 孕期阴道出血（任何量） | 先兆流产、前置胎盘、胎盘早剥 |
| 孕期剧烈腹痛 | 异位妊娠破裂、胎盘早剥 |
| 孕期头痛 + 水肿 + 血压高（描述） | 子痫前期 |
| 孕晚期胎动明显减少或消失 | 胎儿宫内窘迫 |
| 孕期高热（>38.5°C） | 感染风险对胎儿影响，不同于非孕期处理 |

---

### 2.5 population_tag 值

| 情况 | population_tag |
|------|----------------|
| 确认怀孕 | `pregnant_confirmed` |
| 可能怀孕（未确认） | `pregnant_unconfirmed` |
| 备孕中 | `trying_to_conceive` |
| 哺乳期 | `breastfeeding` |

---

## 3. 儿童（Children，< 12 岁）

### 3.1 识别规则

**触发条件**：`patient_profile.age < 12`

若患者未提供年龄，但描述中出现"小孩"、"孩子"、"宝宝"、"我家孩子"等词，必须主动询问年龄。

**询问话术**：
> "请问患者（或孩子）目前多大年龄？"

---

### 3.2 年龄分段风险规则

| 年龄段 | population_tag | 特殊规则 |
|--------|----------------|---------|
| 0–28 天（新生儿） | `neonate` | 任何症状直接转线下/急诊，不适合线上问诊 |
| 29 天–1 岁（婴儿） | `infant` | 发热 > 38°C 直接升为 Level 2；任何症状建议线下儿科 |
| 1–6 岁（幼儿） | `toddler` | 发热 > 38.5°C 升为 Level 2；腹泻脱水风险高 |
| 6–12 岁（学龄儿童） | `child` | 正常问诊，但剂量/用药建议需严格儿童标准 |

---

### 3.3 儿童问诊特殊注意

1. **信息来源可靠性**：儿童本人无法准确描述症状，信息来自家长，可靠性需评估。
   - 写入 `audit_log`：`information_source: parent_reported`
   - 对父母描述的主观症状（如"孩子说肚子痛"）置信度适当降低

2. **儿童特有症状模式**：
   - 高热惊厥：体温上升过快时儿童可能发生，需主动询问有无抽搐史
   - 腹泻脱水：儿童脱水进展快，需询问精神状态、尿量、嘴唇是否干
   - 鹅口疮/口腔溃疡：婴幼儿期常见，提示免疫或真菌感染

3. **禁止给出的建议**：
   - 成人剂量中药方
   - 含有儿童禁用药材的任何方案（如附子大剂量、朱砂、雄黄等）
   - 任何需要患儿独立判断的操作建议

---

### 3.4 儿童高热特殊规则

| 年龄 | 体温阈值 | 处置 |
|------|---------|------|
| < 3 个月 | > 38.0°C | 直接 Level 1，转急诊 |
| 3 个月–3 岁 | > 39.0°C | Level 2，建议尽快线下 |
| 3–12 岁 | > 39.5°C | Level 2，建议线下评估 |
| 任何年龄 | > 40.0°C | Level 1，转急诊 |

---

## 4. 老年人（Elderly，> 75 岁）

### 4.1 识别规则

**触发条件**：`patient_profile.age > 75`

**population_tag**：`elderly_high_risk`

---

### 4.2 老年人特殊风险规则

#### 4.2.1 多病共存（Multimorbidity）

老年患者常同时患有多种慢性疾病，以下组合需特别标记：

| 共存组合 | 额外风险 |
|---------|---------|
| 高血压 + 糖尿病 | 心血管事件风险显著升高 |
| 心衰 + 肾功能不全 | 液体管理复杂，不适合线上调药 |
| 糖尿病 + 周围神经病变 | 疼痛感觉减退，症状可能被低报 |
| COPD + 心脏病 | 呼吸困难症状需线下评估 |

#### 4.2.2 多药联用（Polypharmacy）

老年患者服用 ≥ 5 种药物时（Polypharmacy），必须：
- 标记 `population_tag: polypharmacy`
- 在后续任何建议中注明：需由专科医生评估中西药相互作用
- 禁止给出具体中药方剂建议

#### 4.2.3 症状非典型性

老年患者症状表现常与典型描述不符：
- 心肌梗死可仅表现为疲乏、恶心，而非典型胸痛
- 肺炎可仅表现为意识变差，而无明显发热
- 泌尿感染可以意识混乱为首发症状

> **规则**：对 > 75 岁患者，任何"症状模糊但有加重趋势"的情况，必须按 Level 2 处理，而非等待症状明确。

#### 4.2.4 跌倒与骨折风险

老年患者提及头晕、腿软、步态不稳时：
- 写入 `population_tag: fall_risk`
- 建议线下评估，避免给出可能影响平衡感的建议

---

### 4.3 老年人问诊注意事项

1. **认知功能评估**：如患者回答明显不连贯，需在 `audit_log` 中标注，信息可靠性降低
2. **由家属陪同描述时**：写入 `information_source: family_reported`
3. **用药史询问要详细**：重点询问是否服用抗凝药、降糖药、降压药、利尿药

---

## 5. 慢性肾病患者（Chronic Kidney Disease）

### 5.1 识别规则

**触发条件**（满足任一）：
- `known_conditions` 包含：慢性肾病、肾功能不全、肾衰竭、透析、肾移植
- 患者描述中提及相关词汇

**population_tag**：`chronic_kidney_disease`

---

### 5.2 风险规则

| 肾病分期（患者自述） | 风险提升 |
|-------------------|---------|
| CKD 1–2 期 | 中度风险提升，注意肾毒性药物 |
| CKD 3–4 期 | 高风险，任何用药建议需肾科会诊 |
| CKD 5 期 / 透析 / 肾移植 | 不适合线上给出任何中药建议 |

**禁止给出的建议**：
- 任何已知肾毒性中药（马兜铃酸类、雷公藤、关木通等）
- 高钾食物相关建议（肾病患者需限钾）
- 任何影响水液代谢的方剂建议

**必须提示**：
> "您患有慢性肾病，任何中药方案的使用都需要在肾科医生的参与下进行，部分中药成分可能对肾功能造成额外负担。"

---

### 5.3 肾病急性加重红旗

以下情况在慢性肾病患者中直接升为 Level 1：

| 症状 | 说明 |
|------|------|
| 突然少尿或无尿 | 急性肾损伤 |
| 严重浮肿伴呼吸困难 | 液体超负荷 |
| 血钾高相关症状（肌无力、心悸） | 高钾血症，可致心律失常 |
| 意识模糊 | 尿毒症脑病 |

---

## 6. 慢性肝病患者（Chronic Liver Disease）

### 6.1 识别规则

**触发条件**（满足任一）：
- `known_conditions` 包含：肝硬化、肝炎（乙肝/丙肝）、脂肪肝（中重度）、肝癌、肝功能不全

**population_tag**：`chronic_liver_disease`

---

### 6.2 风险规则

**禁止给出的建议**：
- 任何已知肝毒性中药（首乌、川楝子、千里光、雷公藤等大剂量使用）
- 酒精相关的任何药酒建议
- 需要肝脏大量代谢的复杂配伍方案

**必须提示**：
> "您患有肝脏疾病，部分中药成分需经肝脏代谢，可能加重肝脏负担，请务必在专业医师指导下用药。"

---

### 6.3 肝病急性加重红旗

| 症状 | 说明 |
|------|------|
| 呕血或黑便 | 食管静脉曲张破裂出血，Level 1 |
| 腹部迅速增大（腹水） | 病情进展 |
| 意识混乱（肝性脑病前期） | Level 1，立即急诊 |
| 皮肤巩膜黄染急性加重 | 肝功能急剧恶化 |
| 发热 + 腹痛（腹水患者） | 自发性腹膜炎，Level 1 |

---

## 7. 抗凝药使用者（Anticoagulant Users）

### 7.1 识别规则

**触发条件**：`current_medications` 包含以下任一：
- 华法林（Warfarin）
- 利伐沙班（Rivaroxaban / 拜瑞妥）
- 达比加群（Dabigatran）
- 阿哌沙班（Apixaban）
- 氯吡格雷（Clopidogrel / 波立维）
- 阿司匹林（长期大剂量，>100mg/日）
- 肝素 / 低分子肝素

**population_tag**：`anticoagulant_user`

---

### 7.2 风险规则

1. **任何出血症状**（即使轻微）直接升为 Level 2
2. **严重出血症状**（呕血、黑便、大量皮下出血）升为 Level 1
3. **禁止给出活血化瘀类中药建议**（可能增强抗凝效果，导致出血风险）
4. **禁止给出可能影响凝血的中药建议**（丹参、三七、桃仁、红花等大剂量时有影响）

**必须提示**：
> "您正在使用抗凝/抗血小板药物，部分中药可能影响药物的凝血效果，用药前必须告知开具中药的医师您正在服用的抗凝药。"

---

## 8. 免疫抑制剂使用者（Immunosuppressant Users）

### 8.1 识别规则

**触发条件**：`current_medications` 包含以下任一：
- 泼尼松 / 甲泼尼龙（长期使用）
- 他克莫司（Tacrolimus）
- 环孢素（Cyclosporin）
- 吗替麦考酚酯（MMF）
- 甲氨蝶呤（MTX，长期低剂量）
- 肿瘤靶向免疫治疗药物
- 生物制剂（如阿达木单抗、英夫利昔单抗等）

**population_tag**：`immunosuppressant_user`

---

### 8.2 风险规则

1. **任何发热症状**（>37.5°C）直接升为 Level 2，免疫抑制患者感染进展快
2. **无明显感染症状也需警惕**：免疫抑制可掩盖感染症状
3. **禁止给出可能影响免疫功能的中药建议**（某些补益药可能与免疫抑制剂产生拮抗）
4. **禁止给出未经清洗处理的生食建议**（机会性感染风险）

**必须提示**：
> "您正在使用免疫抑制剂，免疫功能受到影响，感染风险较高。出现发热等感染症状时应及时就医，同时需告知医师您正在使用的免疫抑制剂。"

---

## 9. 其他需标记的特殊人群

| 人群 | 识别条件 | population_tag | 处理要点 |
|------|---------|----------------|---------|
| 糖尿病患者 | `known_conditions` 含糖尿病 | `diabetic` | 高血糖/低血糖症状需快速识别；禁忌高糖食疗建议 |
| 高血压患者 | `known_conditions` 含高血压 | `hypertensive` | 头痛+恶心+视力模糊需警惕高血压危象 |
| 肿瘤患者（治疗中） | `known_conditions` 含肿瘤/化疗/放疗 | `oncology_patient` | 不适合线上给出任何中药建议，建议整合肿瘤科 |
| 器官移植患者 | `known_conditions` 含移植 | `organ_transplant` | 免疫抑制 + 多药联用，只采集信息，不给建议 |
| 精神疾病患者（服药中） | `current_medications` 含精神类药物 | `psychiatric_medication_user` | 注意药物相互作用；情志变化需谨慎判断 |
| 哺乳期妇女 | 患者描述或主动告知 | `breastfeeding` | 用药风险通过母乳传递，禁止给出中药建议 |

---

## 10. population_tag 写入规范

### 10.1 写入时机

`population_tag` 应在以下时机写入 `case_state.special_population_tags`：

1. **建档阶段**：从 `patient_profile` 自动推断（年龄、性别、已知病史）
2. **导诊阶段**：`triage-agent` 主动询问后确认
3. **问诊过程中**：患者在回答中披露新信息时即时添加

### 10.2 写入方式

使用 `update_case_facts` 工具更新 `special_population_tags` 字段，采用**追加**方式，不覆盖已有标签：

```
# 示例：追加孕妇标签
special_population_tags: ["pregnant_confirmed"]

# 后续发现同时服用抗凝药，继续追加：
special_population_tags: ["pregnant_confirmed", "anticoagulant_user"]
```

### 10.3 标签命名规范

所有 `population_tag` 值遵循 `snake_case` 小写英文格式：

| 标准标签值 | 含义 |
|-----------|------|
| `pregnant_confirmed` | 确认怀孕 |
| `pregnant_unconfirmed` | 可能怀孕（未确认） |
| `trying_to_conceive` | 备孕中 |
| `breastfeeding` | 哺乳期 |
| `neonate` | 新生儿（0–28天） |
| `infant` | 婴儿（29天–1岁） |
| `toddler` | 幼儿（1–6岁） |
| `child` | 学龄儿童（6–12岁） |
| `elderly_high_risk` | 高龄（>75岁） |
| `fall_risk` | 跌倒风险 |
| `polypharmacy` | 多药联用（≥5种） |
| `chronic_kidney_disease` | 慢性肾病 |
| `chronic_liver_disease` | 慢性肝病 |
| `anticoagulant_user` | 抗凝药使用者 |
| `immunosuppressant_user` | 免疫抑制剂使用者 |
| `diabetic` | 糖尿病患者 |
| `hypertensive` | 高血压患者 |
| `oncology_patient` | 肿瘤患者（治疗中） |
| `organ_transplant` | 器官移植患者 |
| `psychiatric_medication_user` | 精神类药物使用者 |

### 10.4 标签对风险决策的影响

`safety-agent` 在调用 `check_special_population_risks` 工具时，必须：
1. 读取 `special_population_tags` 全部标签
2. 对每个标签应用对应风险调整规则（见各节 2.2、3.2 等）
3. 取所有标签中**最高风险等级**作为综合特殊人群风险
4. 将 `PopulationRiskAdjustment` 列表写入风险决策输出

---

## 11. 特殊人群信息采集话术

### 11.1 标准问询顺序（triage 阶段）

```
1. "请问患者（或您）目前多大年龄？" → 确认是否儿童/老年
2. "请问您是否正在怀孕，或有可能怀孕？"（仅适用育龄女性）
3. "您目前是否有慢性病，比如高血压、糖尿病、肾病、肝病等？"
4. "您目前是否在服用任何长期药物？能说说大概是哪些吗？"
```

### 11.2 用药询问技巧

患者常不知道药物名称，可使用以下辅助话术：
- "是否有稀血的药（抗凝药）？"
- "是否有压制免疫的药，比如器官移植后服用的？"
- "是否长期服用激素类药物？"
- "是否有精神类或安眠药？"

---

## 12. 特殊人群规则与其他 Skill 的联动

| 联动 Skill | 联动规则 |
|-----------|---------|
| `red-flags-protocol` | 特殊人群相同症状风险等级自动提升，详见各节风险提升表 |
| `contraindication-reference` | 特殊人群禁忌药物的具体列表由该文件定义 |
| `risk-synthesis-protocol` | 综合风险决策必须将特殊人群风险调整纳入计算 |
| `case-state-protocol` | `population_tag` 写入规范、`patient_profile` 字段使用规范 |