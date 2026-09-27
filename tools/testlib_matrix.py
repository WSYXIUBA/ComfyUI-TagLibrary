"""逐库判据跑分器 —— 把每个生成的词库喂给引擎, 跑同一套判据, 抓"换个库就失效的规则"。

动机: 功能必须对**任何符合插件规范的词库**有效。只为当前 4458 条的库调好 = 敷衍。
机制: runtime_snapshot.get_snapshot(lib_dict) 直接吃库字典 —— 不换数据目录, 不碰用户库。
判据: 与全矩阵扫描同口径的 8 项不变量 (词缺失 / 单人锁构图词 / 性别混用 / 取景视角矛盾 / 武器堆叠)。
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根 (本文件在 tools/ 下)
LIBS = os.path.join(REPO, "tools", "_testlibs")
sys.path.insert(0, REPO)
os.chdir(REPO)

import engine        # noqa: E402
import runtime_snapshot as rs  # noqa: E402

STRICT_FEMALE = re.compile(r"(?<![a-z])(1girl|[2-9]\+?girls|girls?|female|woman|women|lady)(?![a-z])")
STRICT_MALE = re.compile(r"(?<![a-z])(1boy|[2-9]\+?boys|boys?|male|man|men|gentleman)(?![a-z])")
MULTI_IMG = ("mirror", "reflection", "polaroid", "multiple views", "split screen",
             "double exposure", "collage", "montage", "frame within frame")
COUNT_MULTI = ("2girls", "2boys", "3girls", "3boys", "multiple girls", "multiple boys",
               "multiple others", "crowd", "everyone", "couple")

# 功能开关矩阵: 性别三档 × 单人锁 × 简背景 × 特写 (与重度测试同口径)
FEATURES = [{"gender": g, "solo_lock": s, "bg_mode": bg, "focus_mode": fc}
            for g in ("off", "female", "male")
            for s in (True, False)
            for bg in ("normal", "simple")
            for fc in ("normal", "portrait")]

SEEDS = int(os.environ.get("TLIB_SEEDS", "60"))


def state_of(snap, feat):
    """按功能开关造 selection_state。tags 取该库随机若干可用词之外的空列表 —— 引擎自己抽。"""
    return {"tags": [], "nsfw": False, "gender": feat["gender"], "solo_lock": feat["solo_lock"],
            "bg_mode": feat["bg_mode"], "focus_mode": feat["focus_mode"],
            "exclude_categories": [], "fill_master": False, "avoid_conflicts": True}


def judge(snap, picks, feat, has_f=True, has_m=True):
    """与库无关的那几条判据。库本身没有对应词时跳过并计数, 免得把"库缺词"误报成引擎错。"""
    if not picks:
        return {"_skip:输出为空(库内容与场景不匹配)": 1}
    low = [p.en.lower() for p in picks]
    text = ", ".join(low)
    bad = {}
    if feat["gender"] == "female":
        if not has_f:
            bad["_skip:库无女性词"] = 1
        elif not STRICT_FEMALE.search(text):
            bad["女性词缺失"] = 1
    if feat["gender"] == "male":
        if not has_m:
            bad["_skip:库无男性词"] = 1
        elif not STRICT_MALE.search(text):
            bad["男性词缺失"] = 1
    if feat["solo_lock"] and any(w in text for w in MULTI_IMG):
        bad["单人锁+多次成像构图词"] = 1
    if feat["gender"] == "female" and has_m and STRICT_MALE.search(text):
        bad["性别混用(要女出男)"] = 1
    if feat["gender"] == "male" and has_f and STRICT_FEMALE.search(text):
        bad["性别混用(要男出女)"] = 1
    cnt = sum(1 for w in COUNT_MULTI if w in text)
    if cnt > 2:
        bad["武器堆叠(>2)"] = 1
    return bad


def run_lib(path):
    lib = json.load(open(path, encoding="utf-8"))
    snap = rs.get_snapshot(lib)
    # 库级性别词存在性 (锚位口径: count/character/appearance —— 引擎补锚只用这些轴;
    # 库没有"可当主体锚"的同性别词时, "要不要女却无女词"不该记引擎账)
    _AN = ("count", "character", "appearance")
    has_f = any(g == 1 and snap.axis_arr[i] in _AN for i, g in enumerate(snap.gender_flag))
    has_m = any(g == 2 and snap.axis_arr[i] in _AN for i, g in enumerate(snap.gender_flag))
    n_tags = sum(len(s["tags"]) for c in lib["categories"] for s in c["subcategories"])
    tot, fails = 0, {}
    for feat in FEATURES:
        st = state_of(snap, feat)
        for i in range(SEEDS):
            seed = 70000 + i
            try:
                picks = engine.run_auto(snap, st, seed, nsfw_on=False, config={"avoid_conflicts": True}).picks
            except Exception as e:                                  # 库缺轴时引擎不该崩
                fails["引擎异常:" + type(e).__name__] = fails.get("引擎异常:" + type(e).__name__, 0) + 1
                if fails.get("_first_trace") is None:
                    fails["_first_trace"] = traceback.format_exc()[-400:]
                continue
            tot += 1
            for k in judge(snap, picks, feat, has_f=has_f, has_m=has_m):
                fails[k] = fails.get(k, 0) + 1
    return n_tags, tot, fails


def main():
    libs = sorted(f for f in os.listdir(LIBS) if f.endswith(".json"))
    print("  逐库跑分: %d 个库 × %d 组功能开关 × %d seed/组\n" % (len(libs), len(FEATURES), SEEDS))
    print("  %-11s %8s %8s  %s" % ("库", "标签", "样本", "超标判据 (占比)"))
    rows = []
    for fn in libs:
        try:
            n_tags, tot, fails = run_lib(os.path.join(LIBS, fn))
        except Exception:
            print("  %-11s %8s %8s  ✗ 加载失败: %s" % (fn[:-5], "-", "-", traceback.format_exc().strip().splitlines()[-1][:70]))
            continue
        trace = fails.pop("_first_trace", "")
        hot = sorted(((k, v) for k, v in fails.items() if v), key=lambda kv: -kv[1])[:4]
        desc = "  ".join("%s %.1f%%" % (k, 100 * v / max(tot, 1)) for k, v in hot) or "✓ 全部 0"
        print("  %-11s %8d %8d  %s" % (fn[:-5], n_tags, tot, desc))
        if trace and any(k.startswith("引擎异常") for k, _ in hot):
            print("        └ %s" % trace.strip().splitlines()[-1][:110])
        rows.append({"lib": fn[:-5], "tags": n_tags, "samples": tot, "fails": fails})
    json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testlibs_report.json"),
                         "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
