"""反冲突规则引擎测试 (沙箱临时目录, 不碰真实数据)。

用法: "D:/aiv4/python_embeded/python.exe" tests/conflicts_test.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tagconflicts
import tagfiles

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{extra}]" if extra else ""))


def make_lib():
    return {"version": 1, "categories": [
        {"id": "subject", "name": "人物主体", "subcategories": [
            {"id": "subject.body", "name": "身体特征", "tags": [
                {"id": "t1", "en": "nude", "zh": "裸体"},
                {"id": "t2", "en": "topless", "zh": "上身裸露"},
                {"id": "t3", "en": "collarbone", "zh": "锁骨"},
            ]},
        ]},
        {"id": "outfit", "name": "服装系统", "subcategories": [
            {"id": "outfit.top", "name": "上装", "tags": [
                {"id": "t4", "en": "corset", "zh": "束腰"},
                {"id": "t5", "en": "jacket", "zh": "夹克"},
            ]},
            {"id": "outfit.acc", "name": "配饰", "tags": [
                {"id": "t6", "en": "necklace", "zh": "项链"},
            ]},
        ]},
    ]}


def main():
    tmp = tempfile.mkdtemp(prefix="taglib_conf_")
    # 沙箱: 指到临时目录
    tagfiles.LIBRARY_DIR = tmp
    tagconflicts.CONFLICTS_PATH = os.path.join(tmp, "conflicts.json")
    tagconflicts.LEGACY_GROUPS_PATH = os.path.join(tmp, "legacy_groups.json")  # 沙箱, 不碰真实旧文件
    tagconflicts.invalidate()

    try:
        print("== 1. 缺文件 → 默认规则自动生成 ==")
        rules = tagconflicts.load_rules()
        ids = [r["id"] for r in rules]
        check("默认规则 6 条", len(rules) == 6, str(ids))
        check("默认含套装/画风互斥", {"suit-vs-tops", "realism-vs-anime"} <= set(ids))
        check("无真实旧文件泄漏进沙箱", not any(i.startswith("legacy.") for i in ids))
        check("nude-vs-clothes 存在", "nude-vs-clothes" in ids)
        check("conflicts.json 落盘", os.path.isfile(tagconflicts.CONFLICTS_PATH))
        raw = json.load(open(tagconflicts.CONFLICTS_PATH, encoding="utf-8"))
        check("文件带 _说明 (AI 可读)", "_说明" in raw and "kind" in raw["_说明"])

        print("== 2. 旧互斥组自动迁移 ==")
        with open(os.path.join(os.path.dirname(tmp), "x"), "w") as f:
            pass  # noop
        old_path = tagconflicts.LEGACY_GROUPS_PATH
        with open(old_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "groups": [
                {"id": "mouth", "name": "嘴部", "tags": ["open mouth", "closed mouth", "smirk"]}]},
                f, ensure_ascii=False)
        rules2 = tagconflicts.load_rules()
        tagconflicts.invalidate()
        rules2 = tagconflicts.load_rules()
        # 迁移只在 _fresh_payload (文件不存在) 时发生 → 这里手动触发
        merged = tagconflicts._migrate_legacy_groups()
        check("旧组转规则", len(merged) == 1 and merged[0]["left"]["kind"] == "tags"
              and len(merged[0]["right"]) == 3, str(merged)[:120])

        print("== 3. 解析 + 失效校验 ==")
        lib = make_lib()
        idx = tagconflicts._lib_index(lib)
        s, ok = tagconflicts.resolve_ref({"kind": "sub", "value": "服装系统/上装"}, idx)
        check("sub 引用解析", ok and s == {"corset", "jacket"}, str(s))
        s, ok = tagconflicts.resolve_ref({"kind": "cat", "value": "人物主体"}, idx)
        check("cat 引用解析", ok and "nude" in s)
        s, ok = tagconflicts.resolve_ref({"kind": "sub", "value": "不存在/子类"}, idx)
        check("失效引用识别", ok is False and s == set())

        print("== 4. 互斥索引: 裸体 ↔ 上装, 配饰不冲突 ==")
        ex = tagconflicts.ExclusionIndex(lib)
        banned = ex.banned_for({"nude"})
        check("nude → corset/jacket 被禁", {"corset", "jacket"} <= banned, str(banned))
        check("nude → necklace 不被禁 (配饰可保留)", "necklace" not in banned, str(banned))
        check("topless → corset 被禁 (tags 组任一成员触发)", "corset" in ex.banned_for({"topless"}))
        check("反向: corset → nude 被禁 (对称)", "nude" in ex.banned_for({"corset"}))
        check("无关标签不受影响", not (ex.banned_for({"collarbone"}) & {"corset", "necklace"}))

        print("== 5. 保存规则: id 去重 + 形状校验 ==")
        res = tagconflicts.save_rules([
            {"id": "a", "left": {"kind": "tag", "value": "x"}, "right": [{"kind": "tag", "value": "y"}]},
            {"id": "a", "left": {"kind": "tag", "value": "p"}, "right": [{"kind": "tag", "value": "q"}]},
            {"id": "bad", "left": {"kind": "nope", "value": "x"}, "right": [{"kind": "tag", "value": "y"}]},
        ])
        check("保存成功且 id 去重", res["ok"] and res["count"] == 2, str(res))
        rules3 = tagconflicts.load_rules()
        check("非法形状被剔除", {r["id"] for r in rules3} == {"a", "a-2"}, str([r['id'] for r in rules3]))

        print("== 6. 旧接口兼容 ==")
        # 第5节覆盖过规则文件, 放回裸露↔上装规则供本节使用
        tagconflicts.save_rules([
            {"id": "nude-vs-clothes",
             "left": {"kind": "tags", "value": ["nude", "topless"]},
             "right": [{"kind": "sub", "value": "服装系统/上装"}]},
            {"id": "g1", "note": "旧互斥组形态",
             "left": {"kind": "tags", "value": ["open mouth", "closed mouth"]},
             "right": [{"kind": "tag", "value": "open mouth"},
                       {"kind": "tag", "value": "closed mouth"}]},
        ])
        groups = tagconflicts.get_groups()
        check("get_groups 只还原组形态规则", len(groups) == 1 and groups[0]["id"] == "g1"
              and groups[0]["tags"] == ["open mouth", "closed mouth"], str(groups))
        out, blocked = tagconflicts.filter_conflicts(
            [{"en": "corset"}, {"en": "necklace"}], ["nude"], lib)
        names = [c["en"] for c in out]
        check("filter_conflicts 静态过滤", names == ["necklace"], f"{names}, blocked={blocked}")
        sel = tagconflicts.check_selection(["nude", "corset"], lib)
        check("check_selection 体检", "nude" in sel and "corset" in sel["nude"], str(sel))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(tagconflicts.LEGACY_GROUPS_PATH)
        except OSError:
            pass

    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
