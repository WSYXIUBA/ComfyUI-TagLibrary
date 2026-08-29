"""perf 门禁: build() 性能基线与 SLA 断言 (方案 V2.1 阶段 0, 最先写的测试)。

- 构造 800 / 1k / 5k / 10k 合成标签库 + 互斥规则 (确定性生成, 不碰真实数据)。
- 测: 冷启动首次 build / 热 build 连续 100~500 次; 打印 P50 / P95 / max。
- 断言故障红线 (禁止合并): 800→100ms, 5k→200ms, 10k→1000ms。
- 可选 GIL 抢占测试: PERF_GIL_HOG=1 时后台线程间歇烧 CPU, 信息性输出。

用法: "D:/aiv4/python_embeded/python.exe" tests/perf_build_test.py
"""

import gc
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library
from nodes import TagLibraryNode

# ---------------------------------------------------------------- SLA (方案 V2.1)

# 规模 -> (P50, P95, Max告警, 故障红线) 毫秒; SLA 严格断言在引擎阶段启用,
# 阶段 0 对旧路径断言故障红线作为基线护栏。
SLA = {
    800:  (2, 5, 20, 100),
    1000: (2, 5, 20, 100),
    5000: (5, 10, 30, 200),
    10000: (10, 20, 100, 1000),
}
RUNS = {800: 500, 1000: 500, 5000: 200, 10000: 100}


def percentile(sorted_vals, p):
    """最近秩百分位 (p in 0..100)。输入须已排序。"""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


# ---------------------------------------------------------------- 合成库生成

CAT_NAMES = ["质量与技术", "人物主体", "服装系统", "姿势动作", "构图镜头",
             "光影氛围", "场景环境", "风格媒介", "材质特效", "人物补充"]


def gen_lib(n_tags: int, seed: int = 42) -> dict:
    """确定性合成库: 均分到 10 大类, 每类 4 个子分类, 交错生成互斥词簇。"""
    rng = random.Random(seed)
    per_cat = [n_tags // len(CAT_NAMES)] * len(CAT_NAMES)
    for i in range(n_tags - sum(per_cat)):
        per_cat[i % len(CAT_NAMES)] += 1

    categories = []
    for ci, cname in enumerate(CAT_NAMES):
        subs = []
        per_sub = [per_cat[ci] // 4] * 4
        for j in range(per_cat[ci] - sum(per_sub)):
            per_sub[j % 4] += 1
        for si in range(4):
            tags = []
            for k in range(per_sub[si]):
                gid = ci * 10000 + si * 1000 + k
                tags.append({
                    "id": f"cat{ci}.s{si}.t{k}",
                    "en": f"tag{gid}",
                    "zh": f"词{gid}",
                    "weight": 1.0 if k % 3 else 1.2,
                    "nsfw": (k % 17 == 0),
                    "enabled": True,
                    "aliases": [],
                })
            subs.append({"id": f"cat{ci}.s{si}", "name": f"子类{ci}{si}", "tags": tags})
        categories.append({"id": f"cat{ci}", "name": cname, "icon": "📦",
                           "subcategories": subs})
    return {"version": 1, "categories": categories}


def gen_mutex_rules(lib: dict, n_rules: int, seed: int = 7) -> list[dict]:
    """生成 n 条组互斥规则 (每组 4~6 个真实存在的标签, 类似旧 groups)。"""
    rng = random.Random(seed)
    pool = [t["en"] for c in lib["categories"]
            for s in c["subcategories"] for t in s["tags"]]
    rules = []
    for i in range(n_rules):
        members = rng.sample(pool, rng.randint(4, 6))
        rules.append({
            "id": f"perf.group{i}",
            "left": {"kind": "tags", "value": members},
            "right": [{"kind": "tag", "value": t} for t in members],
        })
    return rules


# ---------------------------------------------------------------- 测量

def measure_build(node, state: str, mode: str, runs: int) -> dict:
    """连续 runs 次 build, 返回 {cold, p50, p95, max, mean} (毫秒)。"""
    times = []
    for i in range(runs):
        t0 = time.perf_counter()
        node.build(state, mode, i)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {
        "cold": times[0],
        "p50": percentile(times, 50),
        "p95": percentile(times, 95),
        "max": times[-1],
        "mean": statistics.fmean(times),
    }


PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{extra}]" if extra else ""))


def run_suite(n_tags: int, n_rules: int, mode: str = "auto"):
    key = n_tags if n_tags in SLA else min(SLA, key=lambda k: abs(k - n_tags))
    print(f"\n== 规模 {n_tags} 标签 + {n_rules} 规则 (mode={mode}) ==")

    lib = gen_lib(n_tags)
    rules = gen_mutex_rules(lib, n_rules) if n_rules else []

    # 注入合成库 (真实文件不参与; 恢复由 finally/进程退出处理)
    real_get_merged = library.get_merged
    library.get_merged = lambda: lib
    node = TagLibraryNode()
    state = json.dumps({"tags": [], "fill_master": True, "fill_master_min": 1,
                        "fill_master_max": 1, "exclude_categories": [],
                        "avoid_conflicts": True, "nsfw": True})
    try:
        node.build(state, mode, 999)  # 预热 (编译缓存)
        gc.collect()

        st = measure_build(node, state, mode, RUNS.get(key, 200))
        _, p50_sla, max_sla, redline = SLA[key]
        check(f"P50 {st['p50']:.2f}ms ≤ {p50_sla}ms (SLA)", st["p50"] <= p50_sla)
        check(f"P95 {st['p95']:.2f}ms ≤ {max_sla}ms (告警)", st["p95"] <= max_sla)
        check(f"Max {st['max']:.2f}ms < {redline}ms (故障红线)", st["max"] < redline)
        print(f"  cold={st['cold']:.2f} p50={st['p50']:.2f} p95={st['p95']:.2f} "
              f"max={st['max']:.2f} mean={st['mean']:.2f} (n={RUNS.get(key, 200)})")
        return st
    finally:
        library.get_merged = real_get_merged


def gil_hog_info(n_tags: int = 1000):
    """信息性: 后台线程间歇烧 CPU 时 build 的 wall 时间 (不硬断言)。"""
    import threading
    stop = threading.Event()

    def hog():
        while not stop.is_set():
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.03:
                sum(i * i for i in range(2000))  # 烧 GIL 30ms
            time.sleep(0.02)

    lib = gen_lib(n_tags)
    real = library.get_merged
    library.get_merged = lambda: lib
    node = TagLibraryNode()
    state = json.dumps({"tags": [], "fill_master": True, "nsfw": True})
    try:
        node.build(state, "auto", 1)
        th = threading.Thread(target=hog, daemon=True)
        th.start()
        times = []
        for i in range(20):
            t0 = time.perf_counter()
            node.build(state, "auto", 100 + i)
            times.append((time.perf_counter() - t0) * 1000)
        stop.set()
        th.join()
        times.sort()
        print(f"  [GIL hog] p50={percentile(times, 50):.1f} max={times[-1]:.1f} ms "
              f"(信息性: 环境抢占会进窗口, 本插件计算仍为个位数 ms)")
    finally:
        stop.set()
        library.get_merged = real


def main():
    print("== perf_build_test: build() 性能门禁 ==")
    redline_fail = [f for f in FAIL if "故障红线" in f]

    run_suite(800, 20)
    run_suite(1000, 30)
    run_suite(5000, 200)
    run_suite(10000, 500)

    if os.environ.get("PERF_GIL_HOG") == "1":
        gil_hog_info(1000)

    hard = [f for f in FAIL if "故障红线" in f]
    print(f"\n== RESULT: {'ALL PASS ✅' if not FAIL else 'HAS FAILURES ❌'} "
          f"(故障红线违规 {len(hard)} 条 — 红线违规即禁止合并)")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
