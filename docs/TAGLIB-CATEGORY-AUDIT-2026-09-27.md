# 词库分类与数据体检 (2026-09-27)

口径：合并库（default ← ext ← user）实测，13 轴 / 73 槽 / 4741 词。
配套材料：`resources/anima二次元角色跑图数据-20260927/`（平台采样 + 分析报告，其第 8/9 节与本单联动）。

## 1. 现状分布

| 轴 | 槽位 | 词数 | | 轴 | 槽位 | 词数 |
|---|---|---|---|---|---|---|
| 外貌特征 | 11 | 1018 | | 场景环境 | 10 | 639 |
| 服装 | 14 | 976 | | 动作姿态 | 11 | 545 |
| 风格媒介 | 5 | 360 | | 道具武器 | 6 | 293 |
| 材质特效 | 2 | 249 | | 光影氛围 | 4 | 235 |
| 构图镜头 | 4 | 200 | | 角色身份 | 2 | 107 |
| 画质规格 | 2 | 98 | | 人数 | 1 | 21 |
| 画师 | 1 | **0** | | | | |

## 2. 问题清单（带证据）

### 2.1 空轴 —— 画师轴 0 词（数据最实锤的一处）
采样中约 32% 的真实 prompt 带 artist name，画师轴却无词可选 → 只能靠手输/外部贴。
（详见数据报告 #1）

### 2.2 近义重复 18 组（同义双抽 → 结构性冲突来源）
- **同槽撞车（直接重复）**：hand on hip ↔ hands on hips；arms crossed ↔ crossed arms；bandage ↔ bandages；
  fist raised ↔ raised fist；hand on own cheek ↔ hands on own cheeks（均在同一槽内）。
- **跨槽撞车（语义叠 + 视觉重复）**：long sleeve（上装）↔ long sleeves（服装细节）；
  hand up / arm up（站走与动态）↔ hands up / arms up（手部动作）；light leak（镜头语言）↔ light leaks（视觉特效）；
  hand holding ↔ holding hands；stretching arm ↔ stretching arms 等。
- 另有 arm outstretched 系列 4 写法同存、reaching toward/towards viewer、dumbbell(s)、finger gun(s)、
  film grain heavy ↔ heavy film grain、lips parted slightly ↔ lips slightly parted、colored inner hair ↔ inner colored hair。
  （完整 18 组见数据报告第 8 节）
- 现状：部分对由防冲突规则兜底（抽到一个会压另一个），但**词表层面的重复本身**未清。

### 2.3 过粗候选（大槽，可考虑拆）
表情 164 / 发型 162 / 手部动作 158 / 室内 155 / 材质 135 / 服装细节 129 / 上装 126 / 非人特征 125。
拆法备选（要拍板）：
- 表情：基础表情（smile/angry/cry…） vs 强化/复合（evil-smile/wide-grin…），或按"情绪/生理反应"分。
- 发型：结构（ponytail/braid…） vs 状态（wet hair/floating hair/messy…）；发色已独立成槽。
- 手部动作：单手 vs 双手/交互（holding hands…） vs 面部相关（covering-face…）。
- 室内：住宅/公共设施/商业场景三分。

### 2.4 过细评估（结论：没有需要合并的）
最小非空槽 17~31 词：节日与季节 17、月与星空 18、束缚道具 19、体位 19、人数 21、情绪与状态 22、
动物伙伴 22、高潮与体液 24、头颈与倚靠 26、身体细节 28、束缚与调教 28、时间时段 30、服装状态 31、躺跪与趴伏 31。
这些槽各自主题独立、17+ 词实际可抽，**不建议合并**；真正的"细"问题只有 2.1 的空轴。

### 2.5 词表面小项
- 画质规格缺：`score_7_up` / `score_8_up` / `safe` / `year 2025` / `no lineart`（数据报告 #2）。
- `bow` 消歧：缎带义（服装细节，正确） vs `bow (weapon)`（道具武器），值得加消歧提示（数据报告 #8 尾）。

## 3. 处理分级

**A 组（低风险，拍板即做）**
- A1 画师轴灌词（来源与规模待定，见 4.1）
- A2 近义 18 组去重（保留形规则待定，见 4.2）
- A3 画质规格补 5 词
- A4 `bow` 消歧提示

**B 组（方案待拍板）**
- B1 大槽拆分（2.3 三选二/全做/暂缓）

**C 组（联动数据报告 #3~#7/#9，各自独立）**
- C1 Anima negative 预设、C2 NL 无标点短语族、C3 武器档案补类、C4 臂挂配件不占手、C5 参数预设、C6 输出格式决策(权重/内联 lora，需对齐)

## 4. 待确认（回复编号）✅ 已全部落地（2026-09-27，见 CHANGELOG v1.15.0）
1. 画师轴灌词：来源=danbooru 高热度画师？规模（30/100/300）？还是只留"常用绑定"预设？
2. 近义 18 组：保留 danbooru 主形、旧形转 aliases（不再单独抽出）？还是直接删旧形？
3. 大槽拆分：拆哪几个、按什么维度？（建议先只拆"手部动作"一个试点，其余暂缓）
4. 画质规格 5 词 + bow 消歧：直接补？

> 落地口径：① 100 词 = 社区实测采样 37 + danbooru 榜前 63（裸名存储、输出补 @）；② 保留 danbooru 活词形、
> 旧形转别名（16 个死/不存在词形退役、2 个升级活词形、单复数双活词 4 组保留）；③ 仅拆「手部动作」为
> 单手 76 / 双手与交互 38 / 面部与头部 38（其余大槽暂缓）；④ 5 词直接补 + bow 双语消歧 desc。

## 5. 执行后新发现（2026-09-27 复核，下一批候选，未动手）

- **跨槽同 en 10 对（会真实双出）**：`bare arms` / `bare back` / `bare feet` / `bare legs` / `bare midriff`
  （外貌特征·体型 ↔ 服装·裸露与暴露，各一对）、`detailed background`（画质规格·细节强化 ↔ 场景环境·背景处理）、
  `fog`（场景环境·天气现象 ↔ 材质特效·视觉特效）、`hair ornament`（服装·头部配饰 ↔ 服装·首饰珠宝）、
  `ribbon`（服装·头部配饰 ↔ 服装·服装细节）、`sweatdrop`（外貌特征·表情 ↔ 材质特效·视觉特效）。
- **手部三槽内近义簇（共 10 组）**：
  - 叉腰系 5 条：`hand on own hip` / `hands on own hips` / `both hands on hips` / `akimbo` / `arms akimbo`
  - 握拳：`fist clench` / `clenched fist`；敬礼：`saluting` / `salute` / `military salute`
  - 打响指：`snap fingers` / `snapping fingers`；嘘：`shushing` / `shushing gesture`
  - 合十：`praying` / `praying hands` / `namaste`；持物：`holding` / `holding object`
  - 手指抵唇：`finger to mouth` / `finger to lips`；V 手势：`peace sign` / `v sign`
  - 抚胸：`hand on own chest` / `hand over heart` / `clutching chest`
- **人数轴历史 12 条"同 en 后位条"**仍在库文件（`0others` / `trio` / `pair` / `group` 等，合并视图由
  同槽去重器隐掉、user_auto 已记 12 墓碑）；可选清理项，对使用无影响。

