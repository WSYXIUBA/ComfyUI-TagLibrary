"""真机 HTTP queue 验收: TagLibraryNode 经 ComfyUI 执行引擎出词, 读 history。

python tests/real_http_test.py
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8188"


def req(path, method="GET", data=None):
    r = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())


# 0) 节点注册检查
info = req("/object_info/TagLibraryNode")
node = info.get("TagLibraryNode") or {}
required = list(((node.get("input") or {}).get("required") or {}).keys())
print("节点已注册, required =", required)
assert "selection_state" in required, "节点签名异常"

# 1) queue 组合: tag 节点 → ShowText 落 history
def build_wf(state, mode, seed):
    return {
        "1": {"class_type": "TagLibraryNode",
              "inputs": {"selection_state": json.dumps(state, ensure_ascii=False),
                         "mode": mode, "seed": seed}},
        "2": {"class_type": "ShowText|pysssss",
              "inputs": {"text": ["1", 0]}},
    }


def run_one(name, state, mode, seed):
    pid = req("/prompt", "POST", {"prompt": build_wf(state, mode, seed),
                                  "client_id": "hermes-real-test"})["prompt_id"]
    for _ in range(60):
        time.sleep(0.5)
        h = req(f"/history/{pid}")
        if pid in h:
            entry = h[pid]
            st = entry["status"]
            assert st.get("completed"), f"{name} 未完成: {st}"
            outs = entry["outputs"]["2"]["text"][0]
            return outs
    raise TimeoutError(name)


PIN_KAT = {"tags": [{"en": "1girl", "pinned": True},
                    {"en": "katana", "pinned": True},
                    {"en": "rain", "pinned": True},
                    {"en": "night", "pinned": True},
                    {"en": "looking at viewer", "pinned": True}],
           "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}
PIN_GIRL_GUN = {"tags": [{"en": "1girl", "pinned": True},
                         {"en": "rifle", "pinned": True}],
                "fill_master": True, "fill_master_min": 1, "fill_master_max": 2}
RAND = {"fill_master": True, "fill_master_min": 2, "fill_master_max": 3}
NAIL = {"fill_master": False,
        "fill_sub_ranges": {},
        "tags": [], "nsfw": False}

cases = [
    ("钉刀雨夜×3", PIN_KAT, "auto", 11),
    ("钉刀雨夜seedB", PIN_KAT, "auto", 87),
    ("钉枪少女×2", PIN_GIRL_GUN, "auto", 5),
    ("钉枪少女seedB", PIN_GIRL_GUN, "auto", 999),
    ("纯随机A", RAND, "auto", 42),
    ("纯随机B", RAND, "auto", 4242),
    ("纯随机C", RAND, "auto", 77),
    ("手动拼", {"tags": [{"en": e, "enabled": True} for e in
             ("1girl", "katana", "holding sword", "school uniform", "rooftop", "sunset")],
               "nsfw": True}, "manual", 1),
]

print("\n" + "=" * 90)
fails = []
for name, st, mode, seed in cases:
    t0 = time.perf_counter()
    text = run_one(name, st, mode, seed)
    ms = (time.perf_counter() - t0) * 1000
    print(f"### {name} ({ms:.0f}ms 含排队)")
    print(text)
    print()
    # 断言
    if mode == "auto" and st.get("tags"):
        if "katana" in str(st) and "sword" not in text and "katana" not in text:
            fails.append((name, "钉选丢失"))
        if "girl" in text and any(w in text.lower() for w in
                                  (" teenage boy", " old man", " mature male", " shota")):
            fails.append((name, "性别混出"))
        if "1girl" in text and "." not in text:
            fails.append((name, "NL 尾段缺失"))

print("=" * 90)
# 复现性: 同参数跑两次
a = run_one("dupA", PIN_KAT, "auto", 11)
b = run_one("dupB", PIN_KAT, "auto", 11)
if a != b:
    fails.append(("复现性", "同参不同输出"))

# NSFW 排除 + 性别锁长测 (20 个 seed 服务端跑)
# ⚠ 断言必须整词: 子串会把 "witch's hut"/"witching hour" 误判成人物词 "witch"
FEMALE_WORDS = {"1girl", "milf", "catgirl", "schoolgirl", "witch", "elf girl",
                "mermaid", "valkyrie", "princess", "queen", "waitress"}
for seed in range(20):
    t = run_one(f"g{seed}", {"tags": [{"en": "1boy", "pinned": True}],
                             "fill_master": True, "fill_master_min": 2,
                             "fill_master_max": 3}, "auto", seed)
    parts = {p.strip().lower() for p in t.split(",")}
    leak = parts & FEMALE_WORDS
    if leak:
        fails.append((f"male锁seed{seed}", "女词漏出", sorted(leak)))

if fails:
    print("❌", fails)
    sys.exit(1)
print("✅ 真机 HTTP queue 全部通过 (9 用例 + 复现 + 20 seed 性别锁)")
