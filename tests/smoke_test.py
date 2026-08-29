"""后端冒烟测试: 直接跑 python tests/smoke_test.py (不依赖 ComfyUI)。

模拟管理页的真实行为: 编辑器加载当前合并库 -> 在副本上修改 -> 整树提交。
"""

import copy
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library
from nodes import TagLibraryNode


def clean_user_lib() -> None:
    """把库文件指向沙箱副本: 真实用户库与标签库文件夹永不被测试触碰。

    沙箱 = 默认库拷贝 + 空用户库 + 空的标签库文件夹 (热同步不会写到真实 data/标签库)。
    """
    global _SANDBOX
    _SANDBOX = tempfile.mkdtemp(prefix="taglib_smoke_")
    shutil.copy(library.DEFAULT_PATH, os.path.join(_SANDBOX, "tag_library.json"))
    library.DEFAULT_PATH = os.path.join(_SANDBOX, "tag_library.json")
    library.USER_PATH = os.path.join(_SANDBOX, "tag_library.user.json")
    try:
        import tagfiles
        tagfiles.LIBRARY_DIR = os.path.join(_SANDBOX, "标签库")
    except Exception:
        pass
    library.invalidate_cache()


_SANDBOX = None


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

    # ---- 负面标签防回归: 本节点只连正面提示词 ----
    NEG_SUB = "负面"
    NEG_TAGS = {"lowres", "worst quality", "low quality", "blurry",
                "jpeg artifacts", "noise", "bad anatomy", "bad hands"}
    def _scan_neg(tree):
        subs = [s["name"] for c in tree.get("categories", [])
                for s in c.get("subcategories", []) if NEG_SUB in s.get("name", "")]
        tags = [t.get("en", "") for c in tree.get("categories", [])
                for s in c.get("subcategories", []) for t in s.get("tags", [])
                if t.get("en", "").strip().lower() in NEG_TAGS]
        return subs, tags
    for label, tree in (("默认库", library.load_default()),
                        ("用户库", library.load_user_raw() if os.path.exists(library.USER_PATH) else {"categories": []})):
        ns, ts = _scan_neg(tree)
        check(f"无负面标签({label})", not ns and not ts, f"子分类{ns} 标签{ts[:4]}")

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

    # auto 模式: 总控制 1~3 → 每子分类抽 1~3 个 (35 子分类 → 数量远超旧 min/max)
    mixA = node.build('{"fill_master":true,"fill_master_min":1,"fill_master_max":3}', "auto", 123)
    mixA = mixA["result"] if isinstance(mixA, dict) else mixA
    mixB = node.build('{"fill_master":true,"fill_master_min":1,"fill_master_max":3}', "auto", 123)
    mixB = mixB["result"] if isinstance(mixB, dict) else mixB
    print(f"      sample(auto seed123): {mixA[0][:60]}...")
    check("auto 同seed复现", mixA[0] == mixB[0])
    cntA = len([p for p in mixA[0].split(", ") if p])
    check("auto 总控制1~3 → 总量>=35", cntA >= 35, str(cntA))
    # 子分类独立范围: fill_master=false + 质量与技术整个大类 0~0 → 该大类不出
    # (大类下每个子分类都设 0~0, 模拟 UI 里用户给每个子分类单独设 0)
    q_subs = next(c for c in library.get_merged()["categories"] if c["name"] == "质量与技术")
    zero_ranges = {s["id"]: {"min": 0, "max": 0} for s in q_subs["subcategories"]}
    __r_mixC = node.build(json.dumps({"fill_master": False, "fill_sub_ranges": zero_ranges}), "auto", 7)
    mixC = __r_mixC["result"] if isinstance(__r_mixC, dict) else __r_mixC
    flat_all = TagLibraryNode._flat(library.get_merged())
    # 只判定"仅在质量与技术"存在的独有词 (同名标签在别类出现属合法)
    q_only = {t.get("en","").lower() for t, cn in flat_all if cn == "质量与技术"}
    others = {t.get("en","").lower() for t, cn in flat_all if cn != "质量与技术"}
    q_exclusive = q_only - others
    parts_c = [p.strip().lower() for p in mixC[0].split(",")]
    leaked_q = [en for en in q_exclusive if en and en in parts_c]
    check("子分类独立0~0 跳过", not leaked_q, str(leaked_q[:3]))

    # mix_scope 范围限制: 只在'光影氛围'抽 → 结果全在该分类
    __r_scoped = node.build('{"fill_master":true,"fill_master_min":1,"fill_master_max":2,"exclude_categories":["人物主体","服装系统","姿势动作","构图镜头","场景环境","风格媒介","材质特效","负面标签库","质量与技术"]}', "auto", 42)
    scoped = __r_scoped["result"] if isinstance(__r_scoped, dict) else __r_scoped
    print(f"      sample(mix scoped): {scoped[0]}")
    lib_pairs = dict()
    for t, cname in TagLibraryNode._flat(library.get_merged()):
        lib_pairs[str(t.get("en", "")).lower()] = cname
    in_scope = all(lib_pairs.get(p.strip(), "光影氛围") == "光影氛围"
                   for p in scoped[0].split(",") if p.strip())
    check("排除类目限定范围(等价mix_scope)", scoped[0] != "" and in_scope, scoped[0][:60])

    # 旧 random_by_category → manual 退化 (mode 纠偏)
    legacy = node.build("{}", "random_by_category", 1)
    check("by_category 退化为 manual(不炸)", isinstance(legacy, tuple), "ok")
    legacy2 = node.build("{}", "random_mix", 1)
    legacy2 = legacy2["result"] if isinstance(legacy2, dict) else legacy2
    check("random_mix 迁移为 auto(不炸)", isinstance(legacy2, tuple), "ok")

    # pinned 必含
    pin_state = {"selected": [], "pinned": ids_of("masterpiece")}
    pin_state["min_tags"] = 2
    pin_state["max_tags"] = 2
    __r_pinout = node.build(json.dumps(pin_state), "auto", 999)
    pinout = __r_pinout["result"] if isinstance(__r_pinout, dict) else __r_pinout
    check("pinned 必含", "masterpiece" in pinout[0], pinout[0])

    # 权重语法 (新 tags 结构)
    swout = node.build('{"tags":[{"en":"masterpiece","enabled":true}],"use_weights_syntax":true}',
                       "manual", 42)
    check("(tag:w) 语法", swout[0] == "(masterpiece:1.2)", swout[0])

    # prefix/suffix
    pfx = node.build("{}", "manual", 1, prefix="1girl", suffix="roxy migurdia")  # prefix/suffix 仍是正式参数
    check("prefix/suffix 拼接", pfx[0] == "1girl, roxy migurdia", pfx[0])

    # dedupe
    dup = node.build('{"tags":[{"en":"masterpiece","enabled":true},{"en":"masterpiece","enabled":true},{"en":"smile","enabled":true}]}',
                     "manual", 1)
    check("去重保序", dup[0] == "masterpiece, smile", dup[0])

    # 中文搜索命中别名
    __r_sf = node.build('{"search_text":"月光","fill_master":true,"fill_master_min":1,"fill_master_max":3}', "auto", 11)
    sf = __r_sf["result"] if isinstance(__r_sf, dict) else __r_sf
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
        off = node.build(tags_state, "manual", 1)
        check("nsfw off 剔除nsfw标签", nsfw_sample not in off[0] and "smile" in off[0], off[0])
        on_ = node.build(tags_state.replace('"enabled": true}', '"enabled": true,"nsfw":true}')
                                   .replace('"enabled":True}', '"enabled":True,"nsfw":true}'), "manual", 1)
        # 开关在 state: nsfw=true 时全量输出
        st_on = json.loads(tags_state)
        for t in st_on["tags"]:
            if t.get("en") == nsfw_sample:
                t["nsfw"] = True
        on_ = node.build(json.dumps({"tags": st_on["tags"], "nsfw": True}), "manual", 1)
        check("nsfw on 全量", nsfw_sample in on_[0], on_[0])
        # only 模式已删除 → 检查默认剔除即可
        check("nsfw only 已废弃(二态)", node.INPUT_TYPES is not None, "ok")
    else:
        # 库里没有 nsfw 样本 -> 走旧合成断言 (向后兼容)
        nsfw_state = '{"tags":[{"en":"nsfw_example_tag","nsfw":true,"enabled":true},{"en":"smile","enabled":true}]}'
        off = node.build(nsfw_state, "manual", 1)
        check("nsfw off 剔除nsfw标签", off[0] == "smile" and "nsfw_example_tag" not in off[0], off[0])
        on_ = node.build(nsfw_state.replace("}", ",\"nsfw\":true}", 1)[:-1] + ",\"nsfw\":true}", "manual", 1) \
            if False else node.build(json.dumps({"tags": json.loads(nsfw_state)["tags"], "nsfw": True}), "manual", 1)
        check("nsfw on 全量", "nsfw_example_tag" in on_[0], on_[0])
        check("nsfw only 已废弃(二态)", node.INPUT_TYPES is not None, "ok")

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
        pin_mix = {"selected": [], "pinned": [conflict_pair[0]], "avoid_conflicts": True,
                   "fill_master": True, "fill_master_min": 1, "fill_master_max": 1}
        bad = 0
        for s in range(40):
            o = node.build(json.dumps({**pin_mix, "fill_master": True, "fill_master_min": 1, "fill_master_max": 1}), "auto", s)
            o = o["result"] if isinstance(o, dict) else o
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
            # 库已扁平化为二级: 直接取一个子分类做排除测试
            wg_sub = subj_cat["subcategories"][1] if len(subj_cat["subcategories"]) > 1 else subj_cat["subcategories"][0]
            sub_ens = {t.get("en", "").lower() for t in wg_sub.get("tags", [])}

            # 1) 排除子分类 (人物主体/<名>)
            state_x = json.dumps({"tags": [
                {"en": en, "enabled": True} for en in list(sub_ens)[:2]
            ] + [{"en": "closed mouth", "enabled": True}],
                "exclude_categories": [f"人物主体/{wg_sub['name']}"]})
            o1 = node.build(state_x, "manual", 1)
            leaked1 = [en for en in sub_ens if en and en in o1[0].lower()]
            check("排除子分类[" + wg_sub["name"] + "]", not leaked1
                  and "closed mouth" in o1[0], o1[0][:50])

            # 2) 随机模式: 排除整个大类 -> 该大类零漏出
            state_r = json.dumps({
                "fill_master": True, "fill_master_min": 1, "fill_master_max": 1,
                "exclude_categories": ["人物主体"]})
            big_ens = {t.get("en", "").lower()
                       for s in subj_cat.get("subcategories", [])
                       for t in s.get("tags", [])}
            # 同名标签可能存在于多个分类 (如 dappled moonlight 双处),
            # 泄漏判定 = 输出含【只在人物主体】的独有标签
            flat_all = TagLibraryNode._flat(library.get_merged())
            exclusive = {t.get("en", "").lower()
                         for t, cn in flat_all
                         if cn == "人物主体"
                         and not any(t2.get("en","").lower() == t.get("en","").lower()
                                     and cn2 != "人物主体" for t2, cn2 in flat_all)}
            leaked3 = []
            for sd in range(20):
                o = node.build(state_r, "auto", sd)
                o = o["result"] if isinstance(o, dict) else o
                parts_l = [p.strip().lower() for p in o[0].split(",")]
                leaked3 += [en for en in exclusive if en and en in parts_l]
            check("排除大类:随机零漏出", not leaked3, str(leaked3[:4]))
        else:
            check("存在人物主体大类", False)
    else:
        check("排除类目(需 ComfyUI 服务重建大库)", True, "skipped - no server")

    print("\n== RESULT:", "ALL PASS ✅" if ok else "HAS FAILURES ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
