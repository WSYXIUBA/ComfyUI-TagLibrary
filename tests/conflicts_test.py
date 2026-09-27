"""反冲突规则引擎测试 (沙箱临时目录, 不碰真实数据)。

1.14.0 起规则内嵌词库文件: 沙箱改为劫持 library 的三个路径。
用法: "D:/aiv5/python_embeded/python.exe" tests/conflicts_test.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library
import tagconflicts

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


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _set_rules(rules=None, groups=None):
    """直接改写沙箱默认库的 rules 段 (模拟外部编辑), 再清缓存。"""
    lib = json.load(open(library.DEFAULT_PATH, encoding="utf-8"))
    rd = dict(lib.get("rules") or {})
    if rules is not None:
        rd["conflicts"] = rules
    if groups is not None:
        rd["groups"] = groups
    if rd.get("conflicts") or rd.get("groups"):
        lib["rules"] = rd
    else:
        lib.pop("rules", None)
    _write_json(library.DEFAULT_PATH, lib)
    library.invalidate_cache()
    tagconflicts.invalidate()


def main():
    tmp = tempfile.mkdtemp(prefix="taglib_conf_")
    # 沙箱: 库文件指到临时目录 (规则真源 = 库文件)
    orig = (library.DEFAULT_PATH, library.EXT_PATH, library.USER_PATH)
    library.DEFAULT_PATH = os.path.join(tmp, "tag_library.json")
    library.EXT_PATH = os.path.join(tmp, "tag_library.ext.json")
    library.USER_PATH = os.path.join(tmp, "tag_library.user.json")
    _write_json(library.DEFAULT_PATH, {"version": 1, "categories": []})
    library.invalidate_cache()
    tagconflicts.invalidate()

    try:
        print("== 1. 库中无 rules 段 → 默认规则 (内存回退, 不落盘) ==")
        rules = tagconflicts.load_rules()
        ids = [r["id"] for r in rules]
        check("默认规则 6 条", len(rules) == 6, str(ids))
        check("默认含套装/画风互斥", {"suit-vs-tops", "realism-vs-anime"} <= set(ids))
        check("nude-vs-clothes 存在", "nude-vs-clothes" in ids)
        raw = json.load(open(library.DEFAULT_PATH, encoding="utf-8"))
        check("回退不写盘 (库文件无 rules 键)", "rules" not in raw)

        print("== 2. 旧独立文件并入库文件 (conflicts.json + grouprules.json) ==")
        tldir = os.path.join(tmp, "taglib")
        os.makedirs(tldir, exist_ok=True)
        _write_json(os.path.join(tldir, "conflicts.json"), {"version": 1, "rules": [
            {"id": "old1", "left": {"kind": "tags", "value": ["a b", "c d"]},
             "right": [{"kind": "tag", "value": "a b"}, {"kind": "tag", "value": "c d"}]}]})
        _write_json(os.path.join(tldir, "grouprules.json"), {"version": 1, "groups": [
            {"id": "legacy.mouth", "members": ["open mouth", "closed mouth", "smirk"]}]})
        library._migrate_rules_files()
        lib = json.load(open(library.DEFAULT_PATH, encoding="utf-8"))
        rr = lib.get("rules") or {}
        check("conflicts 并入库文件", [x["id"] for x in rr.get("conflicts", [])] == ["old1"],
              str(rr)[:120])
        check("groups 并入库文件", (rr.get("groups") or [{}])[0].get("id") == "legacy.mouth")
        check("旧文件已归档", not os.path.isfile(os.path.join(tldir, "conflicts.json"))
              and os.path.isfile(os.path.join(tmp, "backups", "legacy-rules", "conflicts.json")))
        library.invalidate_cache()
        tagconflicts.invalidate()
        ids2 = [r["id"] for r in tagconflicts.load_rules()]
        check("并入后 load_rules 读到旧规则", ids2 == ["old1"], str(ids2))

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
        _set_rules(rules=[
            {"id": "nude-vs-clothes",
             "left": {"kind": "tags", "value": ["nude", "topless"]},
             "right": [{"kind": "sub", "value": "服装系统/上装"}]},
        ])
        ex = tagconflicts.ExclusionIndex(lib)
        banned = ex.banned_for({"nude"})
        check("nude → corset/jacket 被禁", {"corset", "jacket"} <= banned, str(banned))
        check("nude → necklace 不被禁 (配饰可保留)", "necklace" not in banned, str(banned))
        check("topless → corset 被禁 (tags 组任一成员触发)", "corset" in ex.banned_for({"topless"}))
        check("反向: corset → nude 被禁 (对称)", "nude" in ex.banned_for({"corset"}))
        check("无关标签不受影响", not (ex.banned_for({"collarbone"}) & {"corset", "necklace"}))

        print("== 5. 保存规则: id 去重 + 形状校验 (写回库文件) ==")
        _set_rules(rules=[])
        res = tagconflicts.save_rules([
            {"id": "a", "left": {"kind": "tag", "value": "x"}, "right": [{"kind": "tag", "value": "y"}]},
            {"id": "a", "left": {"kind": "tag", "value": "p"}, "right": [{"kind": "tag", "value": "q"}]},
            {"id": "bad", "left": {"kind": "nope", "value": "x"}, "right": [{"kind": "tag", "value": "y"}]},
        ])
        check("保存成功且 id 去重", res["ok"] and res["count"] == 2, str(res))
        saved = json.load(open(library.DEFAULT_PATH, encoding="utf-8"))
        saved_ids = [x["id"] for x in (saved.get("rules") or {}).get("conflicts", [])]
        check("落盘于库文件 rules 段", saved_ids == ["a", "a-2"], str(saved_ids))
        rules3 = tagconflicts.load_rules()
        check("读回为已保存规则", {r["id"] for r in rules3} == {"a", "a-2"}, str([r["id"] for r in rules3]))

        print("== 6. ext 层规则: 合并且不写回默认库 (影子防护) ==")
        _write_json(library.EXT_PATH, {"version": 1, "categories": [], "rules": {"conflicts": [
            {"id": "ext.shadow", "left": {"kind": "tag", "value": "x"},
             "right": [{"kind": "tag", "value": "y"}]}]}})
        library.invalidate_cache()
        tagconflicts.invalidate()
        merged = tagconflicts.load_rules()
        check("ext 规则出现在合并视图", "ext.shadow" in {r["id"] for r in merged},
              str([r["id"] for r in merged]))
        tagconflicts.save_rules(merged)   # 整表回写 (模拟管理页整表保存)
        saved2 = json.load(open(library.DEFAULT_PATH, encoding="utf-8"))
        ids_saved = {x["id"] for x in (saved2.get("rules") or {}).get("conflicts", [])}
        check("ext 规则不落回默认库", "ext.shadow" not in ids_saved, str(sorted(ids_saved)))
        merged2 = tagconflicts.load_rules()
        check("保存后合并视图仍含 ext (45→35 回归)", "ext.shadow" in {r["id"] for r in merged2},
              str([r["id"] for r in merged2]))
        check("保存后默认库规则仍在", {"a", "a-2"} <= {r["id"] for r in merged2})

        print("== 7. check_selection 体检 ==")
        _set_rules(rules=[{"id": "nude-vs-clothes",
                           "left": {"kind": "tags", "value": ["nude", "topless"]},
                           "right": [{"kind": "sub", "value": "服装系统/上装"}]}])
        sel = tagconflicts.check_selection(["nude", "corset"], lib)
        check("check_selection 体检", "nude" in sel and "corset" in sel["nude"], str(sel))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        library.DEFAULT_PATH, library.EXT_PATH, library.USER_PATH = orig
        library.invalidate_cache()
        tagconflicts.invalidate()

    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
