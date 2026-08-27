"""tagfiles 解析器 + 冲突引擎 测试。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tagfiles
import tagconflicts

ok = True


def check(name, cond, detail=""):
    global ok
    if not cond:
        ok = False
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


SAMPLE = """
<!-- comment 忽略 -->
# 人物·测试

## 表情

smile(微笑), open mouth(张嘴), smirk{1.1}, crying(哭) [nsfw],
nsfw_tag(某描述) {1.2} [nsfw], plain

## 表情

laughing(笑) [nsfw]

# 场景

sunset(日落), indoors
"""

tree = tagfiles.parse_tagfile(SAMPLE)
cats = {c["name"]: c for c in tree["categories"]}
check("分类数=2", len(cats) == 2, str(list(cats)))
char = cats["人物·测试"]
subs = {s["name"]: s for s in char["subcategories"]}
check("同名子分类合并", set(subs) == {"表情"}, str(list(subs)))
tags = {t["en"]: t for t in subs["表情"]["tags"]}
check("标签数=7(含合并的laughing)", len(tags) == 7, str(list(tags)))
check("中文提取", tags["smile"]["zh"] == "微笑")
check("权重提取", abs(tags["smirk"]["weight"] - 1.1) < 1e-9)
check("nsfw 标记 A", tags["crying"].get("nsfw") is True)
check("nsfw 标记 B(乱序修饰)", tags["nsfw_tag"].get("nsfw") is True and abs(tags["nsfw_tag"]["weight"] - 1.2) < 1e-9)
check("纯英文无 zh 键", "zh" not in tags["plain"])
scene = cats["场景"]
check("未指定子分类归未分类", scene["subcategories"][0]["name"] == "未分类")

# 去重: 已有 smile -> 应剔除; laughing 是新的应保留
existing = {"categories": [{"id": "x", "name": "X", "subcategories": [
    {"id": "x.s", "name": "S", "tags": [{"id": "x.s.smile", "en": "SMILE", "zh": "已有"}]}]}]}
clean_tree, stats = tagfiles.dedupe_against(tagfiles.parse_tagfile(SAMPLE), existing)
kept = [t for c in clean_tree["categories"] for s in c["subcategories"] for t in s["tags"]]
check("去重剔除大小写重复", not any(t["en"].lower() == "smile" for t in kept), str([t['en'] for t in kept]))
check("统计新增=8", stats["total_new"] == 8, str(stats))
check("统计去重=1", stats["duplicates_removed"] == 1, str(stats))

# ---- 冲突引擎
groups = tagconflicts.get_groups()
check("默认冲突组已加载", len(groups) >= 15, str(len(groups)))
mouth = next((g for g in groups if g["id"] == "mouth"), None)
check("嘴部组存在", mouth is not None)

res = tagconflicts.check_selection(["open mouth", "closed eyes", "pout"])
check("体检发现嘴部冲突", "嘴部" in res and set(res["嘴部"]) == {"open mouth", "pout"}, str(res))

pool = [{"en": "open mouth"}, {"en": "closed mouth"}, {"en": "smile"}]
filtered, blocked = tagconflicts.filter_conflicts(pool, ["open mouth"])
check("随机避让过滤同组", blocked == 2 and [p["en"] for p in filtered] == ["smile"],
      f"blocked={blocked} left={[p['en'] for p in filtered]}")

# 配置热加载: 改 mtime 后新组生效
tagconflicts.save_groups(groups + [{"id": "test_g", "name": "测试组", "strict": True,
                                    "tags": ["aaa", "bbb"]}])
after = tagconflicts.get_groups()
check("保存后热加载", any(g["id"] == "test_g" for g in after))
r2 = tagconflicts.check_selection(["AAA", "bbb"])
check("大小写不敏感", "测试组" in r2)
# 还原 (去掉测试组)
tagconflicts.save_groups([g for g in after if g["id"] != "test_g"])

print("\n== RESULT:", "ALL PASS ✅" if ok else "HAS FAILURES ❌")
sys.exit(0 if ok else 1)
