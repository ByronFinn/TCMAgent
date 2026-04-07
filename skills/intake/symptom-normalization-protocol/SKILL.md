---
name: symptom-normalization-protocol
description: "Protocol for converting patient natural language symptom descriptions into structured NormalizedFact objects. Includes a 200+ entry mapping table (Chinese patient expressions to normalized_key/value), six-level confidence scoring (0.0-1.0), and handling of ambiguous expressions. Use when parsing any patient response into structured facts."
---

# 症状归一化协议（Symptom Normalization Protocol）

> **Skill 用途**：本文件定义 `intake-agent` 将患者自然语言描述转化为结构化 `NormalizedFact` 的完整操作规程，包括归一化步骤、对照表、置信度评分和边界处理规则。归一化质量直接决定图谱推理的可靠性。

---

## 1. 核心原则

1. **忠实于患者原始表述**：归一化是"提取+映射"，不是"重新解释"，不得修改患者意图。
2. **保留原始文本**：`source_text` 字段必须保存患者原话，不得用归一化结果替换。
3. **不确定就标低置信度**：宁可标注 `confidence: 0.4` 并保留，也不要主观猜测并标高。
4. **一条描述可产生多条 Fact**：患者说"头痛而且口渴"应拆分为两条独立的 `NormalizedFact`。
5. **不做临床推断**：归一化层只管"患者说了什么"，不管"这说明什么证型"——证型推断由图谱推理服务负责。

---

## 2. 归一化四步骤

### Step 1：识别（Recognition）

从患者回答中识别所有有效的症状、体征、观察项描述片段。

**识别规则**：
- 识别所有与健康状态相关的表述
- 包括肯定性表述（"我头痛"）和否定性表述（"我不怕冷"）
- 包括程度修饰（"有点""很""非常""轻微"）
- 包括时间修饰（"最近""以前""偶尔""一直"）
- **忽略**：纯情感表达（"我很担心"不是症状）、背景叙述（"我上周去旅行了"）

**识别示例**：

```
患者输入："我最近有点怕冷，晚上出汗，吃东西胃口不太好，大便有点稀"

识别结果：
- "有点怕冷" → 症状片段 1
- "晚上出汗" → 症状片段 2
- "胃口不太好" → 症状片段 3
- "大便有点稀" → 症状片段 4
```

---

### Step 2：特征化（Characterization）

对每个识别到的症状片段，提取其特征维度（详见 `tcm-clinical-basics` skill 第 5 节）。

**特征化维度**：
- `quality`：性质（胀/刺/隐/灼/冷/酸/麻等）
- `location`：部位
- `severity`：程度（轻/中/重，或 1–10 分）
- `temporal_pattern`：时间节律（晨起/夜间/持续/间歇等）
- `aggravating_factors`：加重因素
- `relieving_factors`：缓解因素
- `duration`：持续时间
- `onset`：起病方式（急性/渐进）

**特征化规则**：
- 患者明确描述的特征：直接提取
- 患者未描述的特征：不推断，留空（`null`）
- 程度修饰词转换：

| 患者用词 | severity 映射 |
|---------|--------------|
| 有点、轻微、不太、稍微 | `"mild"` |
| 比较、蛮、挺 | `"moderate"` |
| 很、非常、特别、剧烈、严重 | `"severe"` |
| 还好、一般 | `"mild"` ~ `"moderate"` |

---

### Step 3：映射标准术语（Normalization Mapping）

将特征化后的描述映射到标准 `normalized_key` 和 `normalized_value`。

**映射原则**：
- 使用本文件第 3 节对照表作为首选映射依据
- 对照表未覆盖的情况，参考 `tcm-clinical-basics` skill 第 4 节术语表
- 仍无法确定时，使用最接近的上位概念键名，降低置信度
- 永远不创造未在规范中定义的新键名（需通过正式渠道扩展）

**命名规范回顾**：
- snake_case 小写英文
- 语义自解释，不超过 5 个单词
- 详见 `case-state-protocol` skill 第 3 节

---

### Step 4：置信度评估（Confidence Assessment）

为每条 `NormalizedFact` 评定置信度分数（详见第 4 节）。

**评估输出**：
```
NormalizedFact {
    fact_id: "fact_abc123",
    fact_type: "symptom",
    normalized_key: "aversion_to_cold",
    normalized_value: true,
    source_text: "有点怕冷",
    confidence: 0.85,
    source_turn_id: "turn_002"
}
```

---

## 3. 常见症状归一化对照表

### 3.1 寒热类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 怕冷、很冷、畏寒、手脚冰、全身发冷 | `aversion_to_cold` | `true` | 0.9 | - |
| 怕冷不明显、不怎么怕冷 | `aversion_to_cold` | `false` | 0.8 | - |
| 有点怕冷、轻微怕冷 | `aversion_to_cold` | `true` | 0.75 | severity: mild |
| 发热、发烧、体温高、身上热 | `fever` | `true` | 0.9 | 需追问体温 |
| 低烧、微热 | `fever` | `true` | 0.85 | severity: mild |
| 高烧、高热 | `fever` | `true` | 0.9 | severity: severe |
| 量了体温 X 度 | `temperature` | X（浮点数） | 0.95 | 有明确数值时 |
| 恶寒发热、先冷后热 | `aversion_to_cold` + `fever` | 均为 `true` | 0.85 | 表证特征，两条 fact |
| 手脚心热、心烦热、五心烦热 | `heat_in_palms_and_soles` | `true` | 0.85 | 阴虚特征 |
| 潮热、午后热、下午热 | `tidal_fever` | `true` | 0.85 | 时间节律热 |
| 忽冷忽热、一会儿冷一会儿热 | `alternating_chills_fever` | `true` | 0.8 | 少阳证特征 |

---

### 3.2 汗出类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 平时容易出汗、没动也出汗、白天汗多 | `spontaneous_sweating` | `true` | 0.85 | 气虚/阳虚特征 |
| 晚上睡觉出汗、半夜出汗、醒来衣服湿了 | `night_sweating` | `true` | 0.9 | 阴虚特征 |
| 出汗后怕冷加重 | `spontaneous_sweating` + `aversion_to_cold` | 均为 `true` | 0.8 | 两条 fact |
| 感冒了有汗 | `sweating_with_cold` | `true` | 0.85 | 表虚证 |
| 感冒了没有汗 | `sweating_with_cold` | `false` | 0.85 | 表实证 |
| 不怎么出汗、出汗少 | `reduced_sweating` | `true` | 0.75 | - |

---

### 3.3 头面类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 头痛、头疼 | `headache` | `true` | 0.9 | 需追问部位和性质 |
| 头顶痛 | `headache` + `headache_location` | `true` + `"vertex"` | 0.9 | 两条 fact |
| 两侧痛、太阳穴痛 | `headache` + `headache_location` | `true` + `"temporal"` | 0.9 | 少阳经 |
| 后脑勺痛 | `headache` + `headache_location` | `true` + `"occipital"` | 0.9 | 太阳经 |
| 前额痛 | `headache` + `headache_location` | `true` + `"frontal"` | 0.9 | 阳明经 |
| 胀痛（头）| `headache` + `headache_quality` | `true` + `"distending"` | 0.85 | - |
| 跳痛、抽痛（头）| `headache_quality` | `"throbbing"` | 0.85 | - |
| 头晕、头昏、晕 | `dizziness` | `true` | 0.85 | - |
| 天旋地转、感觉房间在转 | `vertigo` | `true` | 0.9 | 眩晕 |
| 耳鸣、耳朵嗡嗡响 | `tinnitus` | `true` | 0.9 | 需追问音调 |
| 眼睛干涩 | `dry_eyes` | `true` | 0.9 | 肝阴虚常见 |
| 眼睛红、结膜充血 | `red_eyes` | `true` | 0.9 | - |
| 嘴巴干、喉咙干、口干 | `dry_mouth` | `true` | 0.9 | - |
| 口渴、想喝水 | `thirst` | `true` | 0.9 | 需追问喜冷喜热 |
| 喜欢喝热水、要喝热的 | `thirst_preference_hot` | `true` | 0.9 | 寒证特征 |
| 喜欢喝冷水、要喝冷的、口渴喜冷饮 | `thirst_preference_cold` | `true` | 0.9 | 热证特征 |
| 不怎么喝水、不想喝水 | `thirst` | `false` | 0.8 | - |
| 嘴里发苦、口苦 | `bitter_taste` | `true` | 0.9 | 少阳/肝胆热 |
| 嘴里甜腻 | `sweet_sticky_taste` | `true` | 0.85 | 脾虚湿盛 |
| 嘴里淡、没味道 | `bland_taste` | `true` | 0.85 | 脾虚 |
| 喉咙痛、嗓子痛、咽痛 | `sore_throat` | `true` | 0.9 | 需追问红肿程度 |

---

### 3.4 呼吸与胸部

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 胸口痛、胸痛 | `chest_pain` | `true` | 0.9 | ⚠️ 红旗相关，需立即评估 |
| 胸闷、憋气、喘不过气 | `chest_tightness` | `true` | 0.9 | ⚠️ 红旗相关 |
| 心跳快、心慌、心悸 | `palpitations` | `true` | 0.9 | ⚠️ 需评估 |
| 气短、气不够、呼吸费力 | `shortness_of_breath` | `true` | 0.9 | ⚠️ 红旗相关 |
| 咳嗽 | `cough` | `true` | 0.95 | 需追问有无痰 |
| 干咳、咳嗽没有痰 | `cough` + `cough_with_phlegm` | `true` + `false` | 0.9 | 两条 fact |
| 有痰咳出来 | `cough_with_phlegm` | `true` | 0.9 | 需追问痰色 |
| 白痰、清痰 | `phlegm_color` | `"white"` | 0.85 | 寒痰 |
| 黄痰、绿痰 | `phlegm_color` | `"yellow"` | 0.9 | 热痰 |
| 痰多、痰很多 | `phlegm_quantity` | `"excessive"` | 0.85 | - |
| 鼻塞 | `nasal_congestion` | `true` | 0.9 | - |
| 流鼻涕（清的） | `runny_nose` + `nasal_discharge_color` | `true` + `"clear"` | 0.9 | 寒证 |
| 流黄鼻涕 | `runny_nose` + `nasal_discharge_color` | `true` + `"yellow"` | 0.9 | 热证 |

---

### 3.5 消化类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 不想吃东西、胃口不好、纳差 | `poor_appetite` | `true` | 0.9 | - |
| 吃得少 | `poor_appetite` | `true` | 0.8 | 置信度略低，可能饮食习惯 |
| 肚子胀、腹胀、饭后胀 | `abdominal_distension` | `true` | 0.9 | 需追问饭前/饭后 |
| 肚子痛、腹痛 | `abdominal_pain` | `true` | 0.9 | ⚠️ 需评估是否急腹症 |
| 隐隐作痛（肚子）、隐痛 | `abdominal_pain` + `abdominal_pain_quality` | `true` + `"dull"` | 0.85 | 两条 fact |
| 绞痛（肚子）、痉挛痛 | `abdominal_pain` + `abdominal_pain_quality` | `true` + `"cramping"` | 0.85 | - |
| 喝热水/热敷好一点（肚子）| `abdominal_pain_relieving` | `"warmth"` | 0.9 | 寒证特征 |
| 按压舒服（肚子）| `abdominal_pain_response_to_pressure` | `"relieved_by_pressure"` | 0.9 | 虚证特征 |
| 按压更痛、不让按 | `abdominal_pain_response_to_pressure` | `"aggravated_by_pressure"` | 0.9 | 实证特征 |
| 恶心、想吐、感觉恶心 | `nausea` | `true` | 0.9 | - |
| 吐了、呕吐 | `vomiting` | `true` | 0.95 | 需追问呕吐物 |
| 打嗝、嗳气 | `belching` | `true` | 0.9 | - |
| 反酸、胃酸反上来、烧心 | `acid_reflux` | `true` | 0.9 | - |
| 两侧肋下痛、胁痛 | `hypochondriac_pain` | `true` | 0.85 | 肝胆病常见 |

---

### 3.6 大便类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 大便稀、大便不成形、拉肚子、腹泻 | `loose_stool` | `true` | 0.9 | - |
| 大便水样 | `watery_stool` | `true` | 0.9 | 程度更重 |
| 大便烂、糊状 | `loose_stool` | `true` | 0.85 | - |
| 大便正常成形 | `loose_stool` | `false` | 0.85 | - |
| 大便干、大便干结、好几天没拉 | `constipation` | `true` | 0.9 | 需追问天数 |
| 大便羊粪状（一粒一粒）| `constipation` + `stool_consistency` | `true` + `"pellet_like"` | 0.85 | 津亏 |
| 大便粘、不爽快、擦不干净 | `sticky_stool` | `true` | 0.85 | 湿热特征 |
| 大便臭、大便特别臭 | `foul_smelling_stool` | `true` | 0.8 | 热证/食积 |
| 大便不臭、大便腥冷 | `foul_smelling_stool` | `false` | 0.8 | 寒证 |
| 大便有血、便血（鲜红）| `blood_in_stool` | `true` | 0.9 | ⚠️ 需评估 |
| 大便黑色、像沥青颜色 | `melena` | `true` | 0.9 | ⚠️ Level 1 红旗 |
| 一天好几次（大便）| `stool_frequency` | `"increased"` | 0.8 | 需追问次数 |
| 好几天一次（大便）| `stool_frequency` | `"decreased"` | 0.8 | 便秘倾向 |

---

### 3.7 小便类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 尿黄、尿色深、尿少 | `dark_urine` | `true` | 0.85 | 热证/津亏 |
| 尿多、尿色淡 | `clear_urine` | `true` | 0.85 | 寒证/阳虚 |
| 经常上厕所、尿频 | `frequent_urination` | `true` | 0.9 | 需追问夜间/白天 |
| 晚上起来上厕所、夜尿多 | `nocturia` | `true` | 0.9 | 肾虚特征 |
| 尿急、憋不住尿 | `urinary_urgency` | `true` | 0.9 | - |
| 小便时痛、尿痛 | `dysuria` | `true` | 0.9 | 下焦湿热 |
| 尿里有血、尿血 | `blood_in_urine` | `true` | 0.9 | ⚠️ 需评估 |

---

### 3.8 睡眠类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 睡不着、失眠 | `insomnia` | `true` | 0.9 | 需细分类型 |
| 很久才睡着、入睡困难 | `difficulty_falling_asleep` | `true` | 0.9 | 心神不宁 |
| 睡着了但容易醒、早醒 | `early_waking` | `true` | 0.9 | 心脾两虚常见 |
| 梦多、总做梦、整夜做梦 | `vivid_dreams` | `true` | 0.9 | - |
| 噩梦、梦境恐怖 | `nightmares` | `true` | 0.9 | - |
| 睡眠浅、睡不深 | `light_sleep` | `true` | 0.85 | - |
| 白天犯困、嗜睡 | `excessive_daytime_sleepiness` | `true` | 0.85 | 脾虚湿盛 |
| 睡眠好、睡得很好 | `insomnia` | `false` | 0.85 | - |

---

### 3.9 情志类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 烦躁、容易发火、脾气大 | `irritability` | `true` | 0.85 | 肝郁化火 |
| 焦虑、担心很多、心慌乱 | `anxiety` | `true` | 0.8 | - |
| 心情不好、郁闷、抑郁 | `depression_mood` | `true` | 0.8 | 肝郁 |
| 喜欢叹气、爱叹气 | `frequent_sighing` | `true` | 0.85 | 肝郁气滞 |
| 情绪波动大 | `emotional_lability` | `true` | 0.8 | - |
| 心烦、坐立不安 | `restlessness` | `true` | 0.85 | 热证/阴虚 |

---

### 3.10 舌象类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 舌头颜色淡、舌淡 | `tongue_pale` | `true` | 0.8 | 患者自述置信度适中 |
| 舌头颜色红、舌红 | `tongue_red` | `true` | 0.8 | - |
| 舌头很红、舌深红 | `tongue_deep_red` | `true` | 0.75 | 患者区分有限 |
| 舌头紫色、发紫发暗 | `tongue_purple` | `true` | 0.8 | - |
| 舌头胖大、比较大 | `tongue_swollen` | `true` | 0.8 | - |
| 舌头边上有牙印 | `tongue_teeth_marks` | `true` | 0.9 | 患者描述较明确 |
| 舌苔白、苔是白的 | `coating_white` | `true` | 0.85 | - |
| 舌苔黄、苔是黄的 | `coating_yellow` | `true` | 0.85 | - |
| 舌苔厚腻、苔厚、油腻感 | `coating_thick_greasy` | `true` | 0.8 | - |
| 舌苔薄 | `coating_thin` | `true` | 0.8 | - |
| 舌苔少、几乎没有苔、镜面舌 | `coating_absent` | `true` | 0.85 | 阴虚典型 |
| 舌苔湿润 | `coating_moist` | `true` | 0.8 | - |
| 舌苔干燥 | `coating_dry` | `true` | 0.8 | - |
| 白腻苔 | `coating_white` + `coating_thick_greasy` | 均为 `true` | 0.8 | 两条 fact，寒湿 |
| 黄腻苔 | `coating_yellow` + `coating_thick_greasy` | 均为 `true` | 0.8 | 两条 fact，湿热 |

---

### 3.11 全身与体力类

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 累、很累、疲劳、没力气 | `fatigue` | `true` | 0.9 | 需追问诱因 |
| 活动以后更累 | `fatigue` + `fatigue_aggravating` | `true` + `"exertion"` | 0.9 | 气虚特征 |
| 体重下降、瘦了 | `weight_loss` | `true` | 0.9 | ⚠️ 需评估原因 |
| 浮肿、肿、按下去有坑 | `edema` | `true` | 0.9 | 需追问部位 |
| 腿肿 | `edema` + `edema_location` | `true` + `"lower_limbs"` | 0.9 | 两条 fact |
| 手脚冰凉、四肢冷 | `cold_limbs` | `true` | 0.9 | 阳虚特征 |
| 麻木、没感觉、麻 | `numbness_limbs` | `true` | 0.85 | 需追问部位 |
| 关节痛 | `joint_pain` | `true` | 0.9 | 需追问部位 |
| 腰酸、腰痛 | `low_back_pain` | `true` | 0.9 | 肾虚或湿邪 |
| 膝盖痛 | `knee_pain` | `true` | 0.9 | - |

---

### 3.12 女性相关

| 患者描述（中文） | normalized_key | normalized_value | 置信度参考 | 备注 |
|----------------|----------------|-----------------|----------|------|
| 月经不规律、月经乱 | `menstrual_irregular` | `true` | 0.9 | 需追问周期 |
| 月经提前、经早 | `menstrual_early` | `true` | 0.9 | 热证/气虚 |
| 月经推迟、经迟 | `menstrual_late` | `true` | 0.9 | 寒证/血虚 |
| 月经量多 | `menstrual_flow_heavy` | `true` | 0.9 | - |
| 月经量少 | `menstrual_flow_light` | `true` | 0.9 | 血虚/血瘀 |
| 痛经、来月经肚子痛 | `menstrual_pain` | `true` | 0.95 | - |
| 经血颜色深、发暗、有血块 | `menstrual_color_dark` | `true` | 0.85 | 血瘀特征 |
| 经血颜色淡 | `menstrual_color_pale` | `true` | 0.85 | 血虚特征 |
| 白带多、白带异常 | `abnormal_vaginal_discharge` | `true` | 0.85 | 需追问颜色性状 |
| 更年期症状（烘热汗出等）| `menopausal_symptoms` | `true` | 0.8 | - |

---

## 4. 置信度评分规则（Confidence Scoring）

### 4.1 评分量表

| 置信度范围 | 等级 | 适用情况 |
|----------|------|---------|
| `0.9 – 1.0` | 高置信 | 患者描述清晰、直接、无歧义，与标准术语高度匹配 |
| `0.75 – 0.89` | 中高置信 | 患者描述较清晰，轻微歧义，需少量推断 |
| `0.5 – 0.74` | 中等置信 | 患者描述模糊，存在多种可能解释，选择了最可能的一种 |
| `0.3 – 0.49` | 低置信 | 患者描述高度模糊，归一化结果存在明显不确定性 |
| `0.1 – 0.29` | 极低置信 | 主要依赖推测，几乎无明确依据 |
| `< 0.1` | 不建议记录 | 不确定到无实际价值，可跳过不记录 |

---

### 4.2 影响置信度的因素

**提高置信度的因素**：

| 因素 | 示例 | 提升幅度 |
|------|------|---------|
| 患者使用了与标准术语完全匹配的词汇 | "畏寒" vs "怕冷" | +0.05–0.10 |
| 患者在多轮对话中反复确认同一症状 | 两次提到"怕冷" | +0.05 |
| 患者提供了精确的程度描述 | "体温 38.5°C" | +0.10–0.20 |
| 患者否认与该症状矛盾的内容 | 确认"喜冷饮"后否认"喜热饮" | +0.05 |

**降低置信度的因素**：

| 因素 | 示例 | 降低幅度 |
|------|------|---------|
| 使用模糊程度词 | "有点"、"可能"、"感觉好像" | -0.10–0.20 |
| 患者表述自我否定 | "我有时候有点冷，但有时候又不冷" | -0.20–0.30 |
| 患者信息来自第三方（家属代述）| 父母描述儿童症状 | -0.10 |
| 该症状与其他已知症状存在临床不一致 | 同时描述寒热极端矛盾 | -0.10–0.20 |
| 患者年龄/语言理解局限（儿童、认知下降老人）| - | -0.10–0.15 |
| 症状描述受患者主观情绪影响 | "感觉哪里都不舒服" | -0.20 |

---

### 4.3 置信度评分示例

```
患者说："我昨晚睡觉出了很多汗，衣服都湿了。"
→ normalized_key: night_sweating
→ normalized_value: true
→ 分析：描述清晰，时间明确（昨晚），程度明确（很多，衣服湿了）
→ confidence: 0.95

---

患者说："我有时候睡觉好像有点汗，也不确定，可能是被子太厚了。"
→ normalized_key: night_sweating
→ normalized_value: true
→ 分析："有时候"、"好像"、"有点"、"可能"、"不确定"——多个模糊修饰词
→ confidence: 0.45
→ 建议：标记并追问澄清

---

患者说："我很冷，非常怕冷。"
→ normalized_key: aversion_to_cold
→ normalized_value: true
→ 分析：明确肯定，有程度加强词"非常"
→ confidence: 0.92
→ 附加 severity: "severe"
```

---

## 5. 不确定描述的处理策略

### 5.1 分类处理框架

```
患者描述
    ↓
是否能明确识别为某个 normalized_key？
    ├─ 是，且表述清晰 → 直接归一化，置信度 0.75–0.95
    ├─ 是，但表述模糊 → 归一化 + 低置信度 + 追问标记
    ├─ 可能是某个键，但不确定 → 记录最可能的，置信度 0.3–0.5
    └─ 完全无法识别 → 不归一化，原文保存到 audit_log
```

### 5.2 五类不确定情况及处理

#### 情况 1：程度模糊

**场景**：患者说"好像有点不舒服"、"感觉有什么地方不对"

**处理**：
- 不强行归一化为具体症状
- 在 `audit_log` 中记录原始描述
- 在下一轮追问中引导明确："您说的不舒服，是哪个部位，什么样的感觉？"

---

#### 情况 2：是否存在不确定

**场景**：患者说"我不知道算不算怕冷"、"感觉可能有点口渴吧"

**处理**：
- 归一化记录，置信度设为 0.4–0.55
- 在 `QuestionRecommendation` 中标记该键需要澄清
- 不用于高置信度候选排序，用于"待确认"追问队列

```
NormalizedFact {
    normalized_key: "thirst",
    normalized_value: true,
    confidence: 0.45,
    source_text: "感觉可能有点口渴吧",
    needs_clarification: true
}
```

---

#### 情况 3：描述在两个键之间摇摆

**场景**：患者说"有时候怕冷有时候怕热"（可能是寒热错杂，也可能是正常体温调节）

**处理**：
- 两条 fact 都记录，置信度均下调
- 写入 `contradictions` 待追问
- 不用单一症状推断证型

```
NormalizedFact 1: aversion_to_cold = true, confidence: 0.55
NormalizedFact 2: heat_sensation = true, confidence: 0.55
ContradictionItem: field="temperature_sensation", reason="患者描述同时出现怕冷和怕热，需澄清是否交替出现（少阳）或同时存在（寒热错杂）"
```

---

#### 情况 4：描述指向不同的舌象特征

**场景**：患者说"舌头感觉有点黄又有点白，不太确定"

**处理**：
- 两条 fact 都记录，均置信度 0.5
- 优先追问澄清
- 提供引导话术："您能拍一张舌头的照片发给我们吗？" 或 "是苔的颜色整体偏黄，还是部分白部分黄？"

---

#### 情况 5：患者否认但描述与否认矛盾

**场景**：患者一开始说"我不怕冷"，但后面描述"我喜欢喝热水，冷饮喝了就不舒服"

**处理**：
- 保留两条 fact（`aversion_to_cold: false` 和 `thirst_preference_hot: true`）
- 写入 `contradictions`，记录矛盾
- 不删除早期记录
- 在追问中自然澄清："您之前说不太怕冷，但您喜欢喝热水，可以再说说您对冷的感觉吗？"

---

### 5.3 追问触发规则

以下情况应生成追问 flag，交由 `intake-agent` 在合适时机追问：

| 触发条件 | 追问目标 |
|---------|---------|
| `confidence < 0.5` 的 fact | 澄清该症状是否存在及程度 |
| 存在未填充的关键特征维度 | 追问部位、性质、程度 |
| 记录了矛盾 | 澄清矛盾来源 |
| 高价值症状（图谱推理需要）描述不清 | 优先追问 |

> **追问原则**：一次只追问一个方向，不要在一句话里追问多个症状的多个维度。详见 `question-phrasing-guide` skill。

---

## 6. NormalizedFact 输出格式规范

### 6.1 完整字段定义

```python
class NormalizedFact:
    fact_id: str                    # 格式：fact_{uuid4_short}，如 fact_a3f2b1
    fact_type: str                  # 枚举：symptom / tongue_observation / history /
                                    #       medication / lifestyle / lab_result / demographic
    normalized_key: str             # snake_case 英文，见第 3 节及 case-state-protocol
    normalized_value: bool | str | int | float | list[str]  # 见第 3 节对照表
    source_text: str | None         # 患者原始描述片段，尽量保留原话
    confidence: float               # 0.0–1.0，见第 4 节
    source_turn_id: str | None      # 来源对话轮次 ID，格式：turn_001
```

### 6.2 输出示例（多症状一次输入）

**患者输入**（turn_003）：
> "我最近有点怕冷，晚上出汗，吃东西胃口不太好，大便有点稀，舌苔看起来白白的"

**归一化输出（5 条 fact）**：

```json
[
  {
    "fact_id": "fact_001",
    "fact_type": "symptom",
    "normalized_key": "aversion_to_cold",
    "normalized_value": true,
    "source_text": "有点怕冷",
    "confidence": 0.80,
    "source_turn_id": "turn_003"
  },
  {
    "fact_id": "fact_002",
    "fact_type": "symptom",
    "normalized_key": "night_sweating",
    "normalized_value": true,
    "source_text": "晚上出汗",
    "confidence": 0.85,
    "source_turn_id": "turn_003"
  },
  {
    "fact_id": "fact_003",
    "fact_type": "symptom",
    "normalized_key": "poor_appetite",
    "normalized_value": true,
    "source_text": "吃东西胃口不太好",
    "confidence": 0.82,
    "source_turn_id": "turn_003"
  },
  {
    "fact_id": "fact_004",
    "fact_type": "symptom",
    "normalized_key": "loose_stool",
    "normalized_value": true,
    "source_text": "大便有点稀",
    "confidence": 0.85,
    "source_turn_id": "turn_003"
  },
  {
    "fact_id": "fact_005",
    "fact_type": "tongue_observation",
    "normalized_key": "coating_white",
    "normalized_value": true,
    "source_text": "舌苔看起来白白的",
    "confidence": 0.80,
    "source_turn_id": "turn_003"
  }
]
```

### 6.3 输出注意事项

1. **同一 normalized_key 重复出现时**：追加新记录，不覆盖旧记录，保留两条
2. **否定症状也要记录**：如"我没有头痛" → `headache: false, confidence: 0.9`
3. **fact_id 必须全局唯一**：在整个 case 生命周期内不重复
4. **source_text 不得截断关键修饰词**："有点怕冷" 不能记录为 "怕冷"
5. **批量输出顺序**：建议按患者描述顺序输出，便于审计追溯

---

## 7. 归一化质量检查清单

每批归一化完成后，执行以下检查：

- [ ] 所有识别到的症状片段都已处理（无遗漏）
- [ ] `source_text` 字段保留了患者原话（未被改写）
- [ ] `normalized_key` 符合 snake_case 规范
- [ ] `confidence` 已根据第 4 节规则评定（无全部标 1.0 的情况）
- [ ] 模糊描述已标记低置信度，非强行设高
- [ ] 矛盾信息已写入 `contradictions`，未被单方面删除
- [ ] 否定性表述（"我没有 X"）已记录为 `value: false`，未被忽略
- [ ] 所有 `fact_id` 在本批次中唯一
- [ ] `source_turn_id` 已正确填写

---

## 8. 与其他 Skill 的联动

| 联动 Skill | 联动关系 |
|-----------|---------|
| `tcm-clinical-basics` | 提供标准术语映射基础；特征维度定义来自该 skill 第 5 节 |
| `case-state-protocol` | `NormalizedFact` 结构定义；`normalized_key` 命名规范 |
| `question-phrasing-guide` | 低置信度和追问 flag 触发后，由该 skill 指导追问话术 |
| `contradiction-detection-rules` | 矛盾检测与记录规范，归一化完成后由该规则检查矛盾 |