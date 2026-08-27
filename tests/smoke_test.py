"""后端冒烟测试: 直接跑 python tests/smoke_test.py (不依赖 ComfyUI)。

模拟管理页的真实行为: 编辑器加载当前合并库 -> 在副本上修改 -> 整树提交。
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library
from nodes import TagLibraryNode


def clean_user_lib() -> None:
    """测试前后都清理用户库, 保证可重复运行。"""
    try:
        os.remove(library.USER_PATH)
        library.invalidate_cache()
    except OSError:
        pass


def full_tree_from_merged() -> dict:
    """拿一份干净的可提交树 (去掉运行时字段)。"""
    tree = copy.deepcopy(library.get_merged())
    tree.pop("_meta", None)
    tree.pop("_tombstones", None)
    return tree


def find_cat(tree: dict, cid: str) -> dict:
    return next(c for c in tree["categories"] if c["id"] == cid)


def find_sub(cat: dict, sid: str) -> dict:
    return next(s for s in cat["subcategories"] if s["id"] == sid)


def find_tag(sub: dict, tid: str) -> dict | None:
    return next((t for t in sub["tags"] if t["id"] == tid), None)


def main() -> None:
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not cond else ""))

    clean_user_lib()

    # ---- 默认库与首次合并
    lib = library.load_default()
    check("默认库加载", len(lib["categories"]) == 6)
    n_tags = sum(len(s["tags"]) for c in lib["categories"] for s in c["subcategories"])
    check("默认库标签数>60", n_tags >= 60, str(n_tags))

    merged = library.get_merged()
    check("无用户库时合并=默认", len(merged["categories"]) == 6)

    # ---- 模拟管理页编辑: 整树修改后保存
    tree = full_tree_from_merged()
    char = find_cat(tree, "character")
    char["name"] = "人物(改)"
    slim = find_tag(find_sub(char, "character.body"), "character.body.slim")
    slim["zh"] = "超纤细"
    slim["weight"] = 1.5
    hair_sub = find_sub(char, "character.hair")
    hair_sub["tags"] = [t for t in hair_sub["tags"] if t["id"] != "character.hair.blue"]
    new_tag = {"en": "test_tag_xyz", "zh": "测试新增", "weight": 1.0}
    hair_sub["tags"].append(new_tag)

    r = library.save_user_library(tree)
    check("保存成功", r.get("ok") is True)

    merged = library.get_merged()
    check("合并不丢分类", len(merged["categories"]) == 6,
          ",".join(c["id"] for c in merged["categories"]))
    char_m = next(c for c in merged["categories"] if c["id"] == "character")
    check("用户改名生效", char_m["name"] == "人物(改)", char_m["name"])
    slim_m = find_tag(find_sub(char_m, "character.body"), "character.body.slim")
    check("用户覆盖 zh", slim_m["zh"] == "超纤细", slim_m["zh"])
    check("用户覆盖 weight", abs(slim_m["weight"] - 1.5) < 1e-9, str(slim_m["weight"]))
    hair_m = find_sub(char_m, "character.hair")
    check("删除标签生效(蓝发消失)", find_tag(hair_m, "character.hair.blue") is None)
    check("新增标签自动补id", any(t["en"] == "test_tag_xyz" and t.get("id")
                                  for t in hair_m["tags"]))
    bg_m = next(c for c in merged["categories"] if c["id"] == "background")
    check("未触及分类保留", bg_m["name"] == "背景场景")

    # ---- 墓碑: 新插件版本把蓝发加回默认库也该保持删除
    save_json_back = library.load_user_raw()
    check("墓碑已记录", "character.hair.blue" in set(save_json_back.get("_tombstones", [])))

    # ---- 乐观锁
    try:
        library.save_user_library(full_tree_from_merged(),
                                  client_mtime=r["mtime"] - 9999)
        check("旧mtime被拒绝", False, "竟然成功了")
    except library.LibraryError:
        check("旧mtime被拒绝", True)

    # ---- 校验器
    try:
        library.validate({"categories": [{"id": "a"}, {"id": "a"}]})
        check("重复分类id报错", False)
    except library.LibraryError:
        check("重复分类id报错", True)
    try:
        library.validate({"categories": [{"id": "x", "subcategories": [
            {"id": "x.s", "tags": [{"en": "", "zh": "没英文"}]}]}]})
        check("缺英文标签报错", False)
    except library.LibraryError:
        check("缺英文标签报错", True)

    # ================= 节点三模式 =================
    node = TagLibraryNode()

    def rebuild_lib():
        clean_user_lib()
        return library.get_merged()

    lib2 = rebuild_lib()

    def ids_of(kw: str):
        return [t["id"] for t, _ in TagLibraryNode._flat(lib2) if kw in t["en"]]

    # manual
    state_manual = {"selected": ids_of("smile"), "pinned": []}
    out = node.build(json.dumps(state_manual), "manual", 42)
    check("manual 输出 smile", out[0] == "smile", out[0])

    # random_by_category 同 seed 复现 / 数量正确
    rand_state = {"category_random": {
        "lighting": {"enabled": True, "count": 2, "empty_chance": 0},
        "style": {"enabled": True, "count": 3, "empty_chance": 0}}}
    o1 = node.build(json.dumps(rand_state), "random_by_category", 7)
    o2 = node.build(json.dumps(rand_state), "random_by_category", 7)
    print(f"      sample(by_cat seed7): {o1[0]}")
    check("by_category 同seed复现", o1[0] == o2[0])
    check("by_category 数量=2+3", len(o1[0].split(", ")) == 5, o1[0])

    # 空抽 100% = 输出空
    e = node.build('{"category_random":{"lighting":{"enabled":true,"count":2,"empty_chance":100}}}',
                   "random_by_category", 5)
    check("空抽100%输出空", e[0] == "", repr(e[0]))

    # random_mix
    mixA = node.build("{}", "random_mix", 123, min_tags=4, max_tags=6)
    mixB = node.build("{}", "random_mix", 123, min_tags=4, max_tags=6)
    print(f"      sample(mix seed123): {mixA[0]}")
    check("mix 同seed复现", mixA[0] == mixB[0])
    cnt = len([p for p in mixA[0].split(", ") if p])
    check("mix 数量在4~6", 4 <= cnt <= 6, str(cnt))

    # pinned 必含
    pin_state = {"selected": [], "pinned": ids_of("masterpiece")}
    pinout = node.build(json.dumps(pin_state), "random_mix", 999, min_tags=2, max_tags=2)
    check("pinned 必含", "masterpiece" in pinout[0], pinout[0])

    # 权重语法
    swout = node.build('{"selected":["style.quality.masterpiece"],"pinned":[]}',
                       "manual", 42, use_weights_syntax=True)
    check("(tag:w) 语法", swout[0] == "(masterpiece:1.2)", swout[0])

    # prefix/suffix
    pfx = node.build("{}", "manual", 1, prefix="1girl", suffix="roxy migurdia")
    check("prefix/suffix 拼接", pfx[0] == "1girl, roxy migurdia", pfx[0])

    # dedupe
    dup = node.build('{"selected":["style.quality.masterpiece","style.quality.masterpiece","character.expression.smile"]}',
                     "manual", 1)
    check("去重保序", dup[0] == "masterpiece, smile", dup[0])

    # 中文搜索命中别名
    sf = node.build("{}", "random_mix", 11, search_text="月光", min_tags=1, max_tags=3)
    check("中文搜索命中", "dappled moonlight" in sf[0], sf[0])

    # 幽灵 id 跳过不炸
    ghost = node.build('{"selected":["no.such.tag","character.expression.smile"]}', "manual", 1)
    check("幽灵id跳过", ghost[0] == "smile", ghost[0])

    clean_user_lib()
    print("\n== RESULT:", "ALL PASS ✅" if ok else "HAS FAILURES ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
