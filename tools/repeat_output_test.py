"""连续 100 次最小工作流输出测试 —— 找"越跑越慢"的积攒。

    python tools/repeat_output_test.py [次数]

图只有两个节点 (用户指定的方案):
    TagLibraryNode (auto 模式, 每次换 seed)  →  PreviewAny

逐次记录日志里的 `Prompt executed in X seconds`, 最后给出序列与趋势判断。
**不做任何猜测** —— 只看数字有没有单调上升。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

LOG = r"D:\aiv5\ComfyUI\user\comfyui_8188.log"
HOST = "http://127.0.0.1:8188"
_RE = re.compile(r"Prompt executed in ([\d.]+) seconds")


def post_prompt(seed: int) -> tuple[int, str]:
    state = json.dumps({"tags": [], "fill_master": True, "fill_master_min": 2,
                        "fill_master_max": 3, "nl_tail": True})
    payload = {
        "prompt": {
            "1": {"class_type": "TagLibraryNode",
                  "inputs": {"selection_state": state, "mode": "auto", "seed": seed}},
            "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 1]}},
        },
        "client_id": "repeat_test",
    }
    req = urllib.request.Request(HOST + "/prompt",
                                data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return 200, "queued"
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:200]


def read_durations() -> list[float]:
    try:
        txt = open(LOG, encoding="utf-8", errors="ignore").read()
    except OSError:
        return []
    return [float(m) for m in _RE.findall(txt)]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    base = read_durations()
    print(f"起点: 日志里已有 {len(base)} 条执行记录\n")

    series: list[float] = []
    t_start = time.perf_counter()
    for i in range(1, n + 1):
        code, msg = post_prompt(1000 + i)
        if code != 200:
            print(f"  第 {i} 次提交失败: {code} {msg}")
            break
        # 等这一条跑完 (日志多出一条 Prompt executed)
        deadline = time.time() + 30
        while time.time() < deadline:
            cur = read_durations()
            if len(cur) > len(base) + len(series):
                series.append(cur[-1])
                break
            time.sleep(0.05)
        else:
            print(f"  第 {i} 次超时未完成")
            break
        if i % 10 == 0:
            recent = series[-10:]
            print(f"  已跑 {i:3d} 次 | 最近 10 次均值 {sum(recent)/len(recent):7.3f}s"
                  f" | 总墙钟 {time.perf_counter()-t_start:6.1f}s")

    if not series:
        print("没有采到数据")
        return 1

    print(f"\n== 共采到 {len(series)} 次执行 ==")
    print("  前 10 次:", " ".join(f"{x:.3f}" for x in series[:10]))
    print("  后 10 次:", " ".join(f"{x:.3f}" for x in series[-10:]))
    head = sum(series[:10]) / min(10, len(series))
    tail = sum(series[-10:]) / min(10, len(series))
    print(f"\n  前 10 均值 {head:.3f}s   后 10 均值 {tail:.3f}s   倍率 {tail/head if head else 0:.2f}x")
    print(f"  最小 {min(series):.3f}s  最大 {max(series):.3f}s  中位 {sorted(series)[len(series)//2]:.3f}s")

    # 单调性: 后 50% 的平均 / 前 50% 的平均
    half = len(series) // 2
    a = sum(series[:half]) / max(1, half)
    b = sum(series[half:]) / max(1, len(series) - half)
    print(f"\n  前半 {a:.3f}s  后半 {b:.3f}s  →  {'⚠ 越跑越慢 (积攒)' if b > a * 1.3 else '✓ 无积攒趋势'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
