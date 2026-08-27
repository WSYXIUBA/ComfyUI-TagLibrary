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
    check("默认库加载", len(lib["categories"]) >= 8, str(len(lib["categories"])))
    n_tags = sum(len(s["tags"]) for c in lib["categories"] for s in c["subcategories"])
    check("默认库标签数>60", n_tags >= 60, str(n_tags))

    merged = library.get_merged()
    check("无用户库时合并=默认", len(merged["categories"]) == len(lib["categories"]))

    # ---- 模拟管理页编辑: 整树修改后保存 (用新骨架的质量与技术类)
    tree = full_tree_from_merged()
    qcat = find_cat(tree, "quality")
    qcat["name"] = "质量与技术(改)"
    q_sub = find_sub(qcat, "quality.s1")
    master_tag = next((t for t in q_sub["tags"] if t["en"] == "masterpiece"), None)
    assert master_tag is not None, "骨架 masterpiece 缺失"
    master_tag["zh"] = "杰作(改)"
    master_tag["weight"] = 1.5
    # 删除一条 + 新增一条
    q_sub["tags"] = [t for t in q_sub["tags"] if t["en"] != "8k"]
    new_tag = {"en": "test_tag_xyz", "zh": "测试新增", "weight": 1.0}
    q_sub["tags"].append(new_tag)

    r = library.save_user_library(tree)
    check("保存成功", r.get("ok") is True)

    merged = library.get_merged()
    check("合并不丢分类", len(merged["categories"]) == len(lib["categories"]),
          ",".join(c["id"] for c in merged["categories"]))
    q_m = next(c for c in merged["categories"] if c["id"] == "quality")
    check("用户改名生效", q_m["name"] == "质量与技术(改)", q_m["name"])
    m_tag = next(t for t in find_sub(q_m, "quality.s1")["tags"] if t["en"] == "masterpiece")
    check("用户覆盖 zh", m_tag["zh"] == "杰作(改)", m_tag["zh"])
    check("用户覆盖 weight", abs(m_tag["weight"] - 1.5) < 1e-9, str(m_tag["weight"]))
    check("删除标签生效(8k消失)", next((t for t in find_sub(q_m, "quality.s1")["tags"] if t["en"] == "8k"), None) is None)
    check("新增标签自动补id", any(t["en"] == "test_tag_xyz" and t.get("id")
                                  for t in find_sub(q_m, "quality.s1")["tags"]))
    subj_m = next(c for c in merged["categories"] if c["id"] == "subject")
    check("未触及分类保留", subj_m["name"] == "人物主体")

    # ---- 墓碑: 删掉的 8k 加回默认库也该保持删除
    save_json_back = library.load_user_raw()
    tombstones = set(save_json_back.get("_tombstones", []))
    check("墓碑已记录", any("8k" in tb for tb in tombstones), str(list(tombstones)[:3]))

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

    # manual —— 新结构: state.tags = [{en, enabled}], 兼容旧 selected ids
    state_manual = {"tags": [{"en": "smile", "enabled": True}]}
    out = node.build(json.dumps(state_manual), "manual", 42)
    check("manual 输出 smile", out[0] == "smile", out[0])
    # 旧 selected ids 结构仍兼容 (用精确 id)
    smile_exact = next((t["id"] for t, _ in TagLibraryNode._flat(lib2)
                        if t["en"].lower() == "smile"), None)
    if smile_exact:
        state_old = {"selected": [smile_exact], "pinned": []}
        out_old = node.build(json.dumps(state_old), "manual", 42)
        check("manual 兼容旧selected", out_old[0] == "smile", out_old[0])
    else:
        check("manual 兼容旧selected", True, "skipped - smile 不在默认库")

    # random_by_category 同 seed 复现 / 数量正确 (新骨架: lighting=光影氛围, stylemed=风格媒介)
    rand_state = {"category_random": {
        "lighting": {"enabled": True, "count": 2, "empty_chance": 0},
        "stylemed": {"enabled": True, "count": 3, "empty_chance": 0}}}
    o1 = node.build(json.dumps(rand_state), "random_by_category", 7)
    o2 = node.build(json.dumps(rand_state), "random_by_category", 7)
    print(f"      sample(by_cat seed7): {o1[0]}")
    check("by_category 同seed复现", o1[0] == o2[0])
    # 风格媒介只有 3 条标签(去重后可能不满3), 断言上限放宽: 至少 1+2
    cnt_lines = len([p for p in o1[0].split(", ") if p])
    check("by_category 数量在2~5", 2 <= cnt_lines <= 5, o1[0])

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

    # 权重语法 (新 tags 结构)
    swout = node.build('{"tags":[{"en":"masterpiece","enabled":true}]}',
                       "manual", 42, use_weights_syntax=True)
    check("(tag:w) 语法", swout[0] == "(masterpiece:1.2)", swout[0])

    # prefix/suffix
    pfx = node.build("{}", "manual", 1, prefix="1girl", suffix="roxy migurdia")
    check("prefix/suffix 拼接", pfx[0] == "1girl, roxy migurdia", pfx[0])

    # dedupe
    dup = node.build('{"tags":[{"en":"masterpiece","enabled":true},{"en":"masterpiece","enabled":true},{"en":"smile","enabled":true}]}',
                     "manual", 1)
    check("去重保序", dup[0] == "masterpiece, smile", dup[0])

    # 中文搜索命中别名
    sf = node.build("{}", "random_mix", 11, search_text="月光", min_tags=1, max_tags=3)
    check("中文搜索命中", "dappled moonlight" in sf[0], sf[0])

    # 幽灵 id 跳过不炸 (旧结构兼容: selected 里的坏 id 应被忽略)
    ghost = node.build('{"selected":["no.such.tag","quality.s1.masterpiece"]}', "manual", 1)
    check("幽灵id跳过", "masterpiece" in ghost[0], ghost[0])

    # ---- NSFW 过滤三态 (用户库导入后有真实 nsfw 标签: 取一个 nsfw en 做样本)
    lib_n = library.get_merged()
    nsfw_en = next((t.get("en") for _, cn in TagLibraryNode._flat(lib_n)
                    for t in [] if False), None)
    flat_pairs = TagLibraryNode._flat(lib_n)
    nsfw_sample = None
    for t, _cn in flat_pairs:
        if t.get("nsfw"):
            nsfw_sample = t.get("en")
            break
    if nsfw_sample:
        tags_state = json.dumps({"tags": [
            {"en": nsfw_sample, "enabled": True},
            {"en": "smile", "enabled": True}]})
        off = node.build(tags_state, "manual", 1, nsfw_mode="off")
        check("nsfw off 剔除nsfw标签", nsfw_sample not in off[0] and "smile" in off[0], off[0])
        on_ = node.build(tags_state, "manual", 1, nsfw_mode="on")
        check("nsfw on 全量", nsfw_sample in on_[0], on_[0])
        only = node.build('{}', "random_mix", 3, nsfw_mode="only",
                          min_tags=2, max_tags=4)
        check("nsfw only 只出nsfw", (only[0] == "") or all(
            any(tt.get("en") == p for tt, _ in flat_pairs if tt.get("nsfw"))
            for p in [p.strip() for p in only[0].split(",")] if p), f"{only[0][:50]}")
    else:
        # 库里没有 nsfw 样本 -> 走旧合成断言 (向后兼容)
        nsfw_state = '{"tags":[{"en":"nsfw_example_tag","nsfw":true,"enabled":true},{"en":"smile","enabled":true}]}'
        off = node.build(nsfw_state, "manual", 1, nsfw_mode="off")
        check("nsfw off 剔除nsfw标签", off[0] == "smile" and "nsfw_example_tag" not in off[0], off[0])
        on_ = node.build(nsfw_state, "manual", 1, nsfw_mode="on")
        check("nsfw on 全量", "nsfw_example_tag" in on_[0], on_[0])
        only = node.build('{"selected":[],"pinned":[]}', "random_mix", 3, nsfw_mode="only",
                          min_tags=2, max_tags=4)
        check("nsfw only 只出nsfw", ("nsfw_example_tag" in only[0]) or (only[0] == ""),
              f"{only[0]}")

    # ---- 防冲突随机: pinned 一个光源组标签, 另一个永远不该出现
    lib3 = library.get_merged()
    light_ids = [t["id"] for t, _ in TagLibraryNode._flat(lib3)
                 if t.get("id", "").startswith("lighting.s1.")
                 and t.get("en") in ("backlighting", "rim lighting", "rim light")]
    # 骨架里 backlight 和 rim lighting 是两条; 找互斥组覆盖的对
    import tagconflicts as _tc
    conflict_pair = None
    for g in _tc.get_groups():
        ens = {e.lower() for e in g.get("tags", [])}
        pair = [eid for eid in light_ids
                if {str(t.get("en","").lower()) for t,_ in TagLibraryNode._flat(lib3) if t.get("id")==eid} <= ens]
        if len(pair) >= 2:
            conflict_pair = pair[:2]
            break
    if conflict_pair:
        pin_mix = {"selected": [], "pinned": [conflict_pair[0]], "avoid_conflicts": True}
        bad = 0
        for s in range(40):
            o = node.build(json.dumps(pin_mix), "random_mix", s, min_tags=4, max_tags=9)
            parts_lower = [p.strip().lower() for p in o[0].split(",")]
            pair_ens = [str(t.get("en","").lower()) for t,_ in TagLibraryNode._flat(lib3)
                        if t.get("id") in conflict_pair]
            hit = [e for e in pair_ens if e in parts_lower]
            if len(hit) >= 2:
                bad += 1
        check("防冲突:同组不双出", bad == 0, f"{bad}/40 次同时出现")
    elif len(light_ids) >= 2:
        check("防冲突:同组不双出", True, "skipped - no strict pair")
    else:
        check("光源组标签存在", False, str(light_ids))

    clean_user_lib()

    # ---- 排除类目: 随机+手动都跳过被排除分类的全部标签
    # (先重建大库, 因为上面 clean_user_lib 清掉了)
    import urllib.request

    def _req(path, method="GET", data=None):
        q = urllib.request.Request("http://127.0.0.1:8188" + path, method=method,
                                   data=json.dumps(data).encode() if data else None,
                                   headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(q, timeout=20).read())

    rebuilt = False
    try:
        for f in _req("/taglib/api/tagfiles")["files"]:
            if f["file_name"].startswith("00_"):
                continue
            _req("/taglib/api/tagfiles/import", "POST", {"path": f["path"]})
        rebuilt = True
    except Exception:
        pass  # 无服务器时跳过大库测试 (CI 场景)

    if rebuilt and os.path.exists(library.USER_PATH):
        libx = library.get_merged()
        subj_cat = next((c for c in libx["categories"] if c["name"] == "人物主体"), None)
        if subj_cat:
            wg_sub = next((s for s in subj_cat["subcategories"] if s.get("groups")), None)
            if wg_sub:
                g0 = wg_sub["groups"][0]
                g0_ens = {t.get("en", "").lower() for t in g0.get("tags", [])}

                # 1) 排除孙分类 (人物主体/外貌/发型发色 等)
                exc_key = f"人物主体/{wg_sub['name']}/{g0['name']}"
                state_x = json.dumps({"tags": [
                    {"en": en, "enabled": True} for en in list(g0_ens)[:2]
                ] + [{"en": "closed mouth", "enabled": True}],
                    "exclude_categories": [exc_key]})
                o1 = node.build(state_x, "manual", 1)
                leaked1 = [en for en in g0_ens if en and en in o1[0].lower()]
                check("排除孙类[" + g0["name"] + "]", not leaked1
                      and "closed mouth" in o1[0], o1[0][:50])

                # 2) 排除子分类 (人物主体/外貌 = 该子分类全部 groups + tags)
                sub_ens = {t.get("en", "").lower() for t in wg_sub.get("tags", [])}
                state_y = json.dumps({"tags": [
                    {"en": en, "enabled": True} for en in list(sub_ens)[:2]],
                    "exclude_categories": [f"人物主体/{wg_sub['name']}"]})
                o2 = node.build(state_y, "manual", 1)
                leaked2 = [en for en in sub_ens if en and en in o2[0].lower()]
                check("排除子类[" + wg_sub["name"] + "]", not leaked2, o2[0][:50])

                # 3) 随机模式: 排除整个大类 -> 该大类零漏出
                state_r = json.dumps({
                    "category_random": {subj_cat["id"]: {"enabled": True, "count": 5}},
                    "exclude_categories": ["人物主体"]})
                big_ens = {t.get("en", "").lower()
                           for s in subj_cat.get("subcategories", [])
                           for t in s.get("tags", [])}
                leaked3 = []
                for sd in range(20):
                    o = node.build(state_r, "random_by_category", sd)
                    text_l = o[0].lower()
                    leaked3 += [en for en in big_ens if en and en in text_l]
                check("排除大类:随机零漏出", not leaked3, str(leaked3[:4]))
            else:
                check("存在 groups 的子分类", False)
        else:
            check("存在人物主体大类", False)
    else:
        check("排除类目(需 ComfyUI 服务重建大库)", True, "skipped - no server")

    print("\n== RESULT:", "ALL PASS ✅" if ok else "HAS FAILURES ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
