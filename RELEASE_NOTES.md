# ComfyUI-TagLibrary v1.7.1 Release

输出质量真审：未成年锁定 / 人数词分类补全 / 人称一致（2026-09-12）

用户问"完整提示词质量到底如何、你真验证过吗"。回答：门禁全过 ≠ 没毛病 ——
把真机输出**当人读**后抓到 4 类门禁管不到的语义缺陷，全部修复并固化为新断言。

### 真审抓到什么（真实输出实例）

| 缺陷 | 实测输出 | 根因 |
|---|---|---|
| **未成年 × 成人内容** | `toddler` + `side-tie panties` | 年龄词与成人词散布 9 个槽位，配额/互斥槽位组/跨池规则全管不到 |
| **群像配单数人称** | `large group` + "She has asymmetric bangs..." | 人数轴 30 词里 9 个没进 MULTI 表；`_pronouns` 按 `_INTRO_KEYS` 扫描，扫不到回落 "She" |
| **摄影 × 手绘媒介** | `product photography` + `shin-hanga` | style_base 互斥只盖 写实摄影⊥二次元向 |
| (连带发现) | `4girls/5girls/6+girls/1other/0others` 缺人称行 | 同上，Q10 建好后由门禁自己抓出来 |

### 修了什么

- **未成年锁定 (slotpolicy + engine)**：`MINOR_AGE_WORDS` (toddler/infant/child/
  preteen/loli/shota/teen/…) 一经出生（抽取或钉选），`MINOR_BLOCK_WORDS`
  (~55 个成人向词：裸露/内衣/泳装/体型/表情/氛围情绪的成人子集) 在候选级
  全池屏蔽。**词级**而非槽位级 —— 裸露槽的 "bare shoulders"、腿袜槽的
  "thighhighs" 等日常词保持可用。
- **人数词分类补全 (slotpolicy + nl)**：group of girls/boys、trio、quartet、
  ensemble、pair、large/small group、crowd 进 MULTI 表；全部 30 个人数轴词
  进 `_PRONOUN` + `_INTRO_KEYS`（缺了任何一张表都会回落 She）。
- **NL 群像开箱句 (nl_flavors.json)**：给 23 个复数/中性人数词补 intro 句
  （此前只有 1girl/1boy/solo 有，群像从来不出引入句）。
- **摄影⊥艺术媒介 (slotpolicy.EXCLUSIVE)**：新增 style_photo_art 互斥组；
  二次元向不参与（anime style + oil painting 是合法组合）。
  题材风格的 art nouveau 等流派词不锁（摄影配流派语义成立）。

### 新断言

- `quality_gate_test` **Q10 人数词分类完备**：人数轴每词必须进三张分类表 +
  `_PRONOUN`/`_INTRO_KEYS`（建好后立即抓出 crowd/4girls/5girls/6+girls/1other/
  0others 六个漏网，全部补齐）。
- `quality_gate_test` **Q11 未成年锁定**：钉选 toddler + NSFW 全开，30 seed 内
  成人向词必须零出现。
- `prompt_quality_test` **P4 新增 4 对未成年矛盾**、**P9 NL 人称与人数词一致**
  （人数词为复数时尾段出现 She/He/her/his 即违规）。

### 修复后实测

```
[seed2]  count='group of girls' → The group of girls fills the scene. They have swept bangs and wolf cut, ...
[seed6]  count='5girls'         → They hold katana between their teeth, both hands free. ...
[seed8]  count='large group'    → A large group fills the frame to its edges. They hold sword ...
```

### 验证

离线门禁 14/14；在线 node_output_test（真机 60 次生成 × 文本层断言）通过。
