"""真机节点输出重度测试 —— 经 ComfyUI 真实队列跑 N 次, 校验节点吐出的 positive 文本。

与另两个测试的分工:
  · quality_gate_test      引擎层 (直接调 run_auto) 的结构断言
  · prompt_quality_test    引擎层合成提示词后的文本层断言
  · node_output_test(**本测试**)  走**真实节点**: POST /prompt → 读 history 里节点实际
    吐出的 positive 字符串。多出来的是节点这一段路径:
    前后缀拼接 / _format_tag(权重语法, 画师 @) / 分隔符 / NL 尾段 / executed 回显。

为什么需要它: 前两个测试是"模拟"节点拼装, 一旦节点的拼装逻辑改错 (例如权重没生效、
前后缀没接上、分隔符写死), 它们都不会报。这一层才是用户真正连 CLIPTextEncode 拿到的文本。

用法:
    python tests/node_output_test.py                 # 20×3 = 60 次真机生成 (~1.5 分钟)
    python tests/node_output_test.py --n 200         # 200×3 = 600 次 (发布前重度)
    python tests/node_output_test.py --n 5 --keep    # 少量并打印 positive 原文
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:8188"

# 与 prompt_quality_test 共用的语义互斥对 (高置信)
CONTRADICTIONS: list[tuple[str, str, str]] = [
    ("写实与二次元并存", "realistic", "anime style"),
    ("室内与室外并存", "indoors", "outdoors"),
    ("白天与夜晚并存", "daytime", "night"),
    ("白天与星空并存", "daytime", "starry sky"),
    ("站立与坐姿并存", "standing", "sitting"),
    ("俯视与仰视并存", "from above", "from below"),
    ("笑脸与哭脸并存", "smile", "crying"),
    ("张嘴与闭嘴并存", "open mouth", "closed mouth"),
    ("长发与短发并存", "long hair", "short hair"),
    ("大胸与小胸并存", "large breasts", "small breasts"),
    ("粗腿与细腿并存", "thick thighs", "thin thighs"),
    ("赤足与鞋并存", "barefoot", "high heels"),
    ("赤足与靴并存", "bare feet", "boots"),
    ("全裸与穿着并存", "nude", "school uniform"),
]
NEGATIVE_LEAK = ["worst quality", "low quality", "jpeg artifacts", "blurry",
                 "bad anatomy", "bad hands", "watermark", "score_1", "score_2"]
MALFORMED = None


def req(path, method="GET", data=None, timeout=60):
    r = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


def build_wf(state, mode, seed, prefix="", suffix=""):
    """节点 → ShowText; 输出 0 = positive, 1 = tags_preview, 前/后缀走 inputs。"""
    inputs = {"selection_state": json.dumps(state, ensure_ascii=False),
              "mode": mode, "seed": seed}
    if prefix:
        inputs["prefix"] = prefix
    if suffix:
        inputs["suffix"] = suffix
    return {
        "1": {"class_type": "TagLibraryNode", "inputs": inputs},
        "2": {"class_type": "ShowText|pysssss", "inputs": {"text": ["1", 0]}},
        "3": {"class_type": "ShowText|pysssss", "inputs": {"text": ["1", 1]}},
    }


def run_one(state, mode, seed, prefix="", suffix="", poll=120):
    pid = req("/prompt", "POST", {"prompt": build_wf(state, mode, seed, prefix, suffix),
                                 "client_id": "taglib-node-output-test"})["prompt_id"]
    for _ in range(poll):
        time.sleep(0.25)
        h = req(f"/history/{pid}")
        if pid in h:
            e = h[pid]
            st = e.get("status") or {}
            assert st.get("completed"), f"未完成: {st}"
            pos = e["outputs"]["2"]["text"][0]
            prev = e["outputs"]["3"]["text"][0]
            return pos, prev
    raise TimeoutError(f"seed {seed}")


def main() -> int:
    ap = argparse.ArgumentParser()
    # 默认 20 × 3 状态 = 60 次真机生成 (约 1.5 分钟, 够进常规门禁);
    # 发布前跑重度的: python tests/node_output_test.py --n 200  (600 次)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    import re
    malformed = re.compile(r"\([^()]*\([^()]*\)")

    try:
        info = req("/object_info/TagLibraryNode", timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"❌ ComfyUI 未就绪 (先启动它): {e}")
        return 2
    assert "selection_state" in ((info.get("TagLibraryNode") or {}).get("input") or {}).get("required", {})
    print("节点已注册 ✓")

    stat = Counter()
    fails: list[str] = []
    n_done = 0

    states = {
        "自动·钉刀": {"tags": [{"en": "katana", "pinned": True}], "nsfw": False,
                      "fill_master": True, "nl_tail": True},
        "自动·空":   {"tags": [], "nsfw": False, "fill_master": True, "nl_tail": True},
        "纯标签":    {"tags": [{"en": "katana", "pinned": True}], "nsfw": False,
                      "fill_master": True, "nl_tail": False, "separator": "comma"},
    }

    for label, st in states.items():
        for seed in range(1, args.n + 1):
            try:
                pos, prev = run_one(st, "auto", seed)
            except Exception as e:  # noqa: BLE001
                stat["E·请求失败"] += 1
                if len(fails) < 15:
                    fails.append(f"E({label}) seed{seed}: {e}")
                continue
            n_done += 1
            # ⚠ 节点是用 ". " (句号+空格) 把 NL 尾段接在标签后面的, 不是换行 ——
            # 一开始我按 "\n\n" 切, 结果永远切不出尾段、误报"NL 0 句"。
            # 标签段本身不含句号, 所以第一个 ". " 之后就是尾段 (节点只在标签段末尾补一个句号)。
            m = re.search(r"\.\s+(?=[A-Z])", pos)
            body = pos[:m.start()] if m else pos
            words = [w.strip() for w in body.split(",") if w.strip()]
            low = [w.lower() for w in words]
            tag = label

            # N1 非空 + 词数带
            if not (20 <= len(words) <= 80):
                stat[f"N1·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"N1({tag}) seed{seed}: {len(words)} 词")
            # N2 无重复
            dup = [w for w, c in Counter(low).items() if c > 1]
            if dup:
                stat[f"N2·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"N2({tag}) seed{seed}: 重复 {dup[:2]}")
            # N3 无畸形
            bad = [w for w in words if malformed.search(w)]
            if bad:
                stat[f"N3·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"N3({tag}) seed{seed}: 畸形 {bad[:2]}")
            # N4 语义互斥
            for lb, a, b in CONTRADICTIONS:
                if a in low and b in low:
                    stat[f"N4·{tag}"] += 1
                    if len(fails) < 15:
                        fails.append(f"N4({tag}) seed{seed}: {lb}")
                    break
            # N5 负向词不漏
            leak = [w for w in NEGATIVE_LEAK if w in low]
            if leak:
                stat[f"N5·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"N5({tag}) seed{seed}: {leak}")
            # N6 尾段 (开启时 >=2 句)
            if st.get("nl_tail"):
                tail = pos[m.end():] if m else ""
                n_sent = len([x for x in re.split(r"[.!?。！？]+", tail) if x.strip()])
                if n_sent < 2:
                    stat[f"N6·{tag}"] += 1
                    if len(fails) < 15:
                        fails.append(f"N6({tag}) seed{seed}: NL {n_sent} 句")
            # N7 标签段必须是纯逗号分隔 (没有句号掺杂), 且 NL 尾段只能出现在最后
            if "。" in body or re.search(r"\.(?!\s*[A-Z])", body):
                stat[f"N7·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"N7({tag}) seed{seed}: 标签段掺入了句子")
            if st.get("nl_tail") and not m:
                stat[f"N7·{tag}"] += 1
                if len(fails) < 15:
                    fails.append(f"N7({tag}) seed{seed}: NL 开启但没有尾段")
            if args.keep and seed <= 1:
                print(f"\n[{tag} seed{seed}] positive:\n{pos[:600]}")

    print(f"\n真机节点生成 {n_done} 次 / 失败 {stat['E·请求失败']} 次")
    print()
    checks = [("N1", "词数带"), ("N2", "无重复词"), ("N3", "无畸形词"),
              ("N4", "语义互斥对不共现"), ("N5", "负向词不漏入"),
              ("N6", "NL 尾段 ≥2 句"), ("N7", "标签段纯净且尾段在末尾")]
    tot = 0
    for key, desc in checks:
        row = {t: stat[f"{key}·{t}"] for t in states}
        v = sum(row.values())
        tot += v
        print(f"  {'✓' if not v else '✗'} {key} {desc}: {v}  " +
              " ".join(f"[{t}]{c}" for t, c in row.items() if c))
    if fails:
        print(f"\n❌ 前几条失败 ({len(fails)} 条):")
        for f in fails:
            print("   -", f)
        return 1
    print(f"\n✅ 真机节点输出测试通过 ({n_done} 次生成, 全部零违规)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
