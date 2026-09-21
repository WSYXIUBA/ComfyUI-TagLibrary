"""一键门禁 —— 跑全部验收测试并汇总结果。

用法:
    python tools/run_gates.py              # 全部离线门禁
    python tools/run_gates.py --with-online  # 加上需要 ComfyUI 实例的在线门禁
    python tools/run_gates.py m1 m3        # 只跑名字匹配这些关键字的门禁
    python tools/run_gates.py --list       # 列出所有门禁

为什么要经过这个脚本而不是逐个 python tests/xxx.py:
  1. 自动快照/还原 data/default/taglib/ —— 门禁会写该目录下的规则 .json
     (互斥域 / 档案等), 直接跑会污染工作区, 让 git status 出现与代码无关的改动。
  2. 统一汇总 + 失败时打印尾部日志, 退出码可直接用于 CI。

1.12.0 起该目录只有规则 .json (没有 .md 镜像、没有热同步), 上面第 1 条仍防的是
规则文件被测试改写这种真实污染。

返回码: 0 = 全部通过; 1 = 有失败。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")

# 离线门禁: 不依赖运行中的 ComfyUI
OFFLINE = [
    ("m1_engine_test", "新引擎骨架 (轴/组/跨池/确定性)"),
    ("m2_weapon_slice_test", "武器束 + 旧 repro 缺陷翻案"),
    ("m3_nl_test", "NL 编译 + 反拼接断言"),
    ("m4_objects_test", "物品档案 (+ --long 万 seed 长跑)"),
    ("quality_audit", "30 条完整提示词人工级审计"),
    ("smoke_test", "后端全链路 (沙箱)"),
    ("conflicts_test", "反冲突引擎"),
    ("perf_build_test", "性能门禁 (10k 库 p50<3ms)"),
    ("quality_gate_test", "输出质量门禁 (词数/配额/互斥/人数/畸形词/确定性)"),
    ("prompt_quality_test", "完整提示词重度测试 (文本层语义/段位/性别/负向词)"),
    ("api_security_test", "API 安全门禁 (CSRF 中间件/导入 .json 载荷防呆)"),
    ("tag_edit_test", "标签就地编辑 (推导/新增/改字段/校验拒绝/首页分段/待完善)"),
    ("lint_check", "死代码门禁 (ruff: 死导入 / 重复定义 / 死变量)"),
    ("nsfw_pack_test", "1.8.0 NSFW 扩展门禁 (扩展包/互斥域/未成年锁/手账本/重摇/吸收/negative/NL)"),
    ("heavy_prompt_test", "重度提示词矩阵 (708 条 × 模式/NSFW档/性别/场景/排除 + 3000 次压力)"),
]

# 需要 ComfyUI 在跑的在线门禁 (--with-online 才跑)
ONLINE = [
    ("real_http_test", "真机 ComfyUI HTTP queue 验收 (接口/端口/性别锁)"),
    ("node_output_test", "真机节点输出测试 (60 次生成 × 文本层断言)"),
    ("ui_v13_check", "CDP 浏览器 UI 巡检 (面板/页签/可编辑/开关)"),
    ("ui_theme_check", "CDP 浏览器主题一致性巡检 (深色/浅色/管理页)"),
    ("ui_dialog_close_test", "弹层开关巡检 (⋯菜单/挑选器/面板弹层/管理页弹窗 能否关掉)"),
    ("feature_e2e_test", "全功能真机端到端 (预设/场景条/强度/重摇/批量/吸收/未成年锁/negative)"),
]

# 会被测试写到的目录 (跑前快照、跑后还原)
SNAPSHOT_DIRS = [os.path.join(ROOT, "data", "default", "taglib")]


def _snapshot(dst_root: str) -> list[tuple[str, str]]:
    """逐个文件快照 (不做整目录拷贝/删除 —— 逐文件还原更稳, 也不触发批量删除保护)。"""
    out: list[tuple[str, str]] = []
    for src in SNAPSHOT_DIRS:
        if not os.path.isdir(src):
            continue
        for root, _dirs, files in os.walk(src):
            for fn in files:
                p = os.path.join(root, fn)
                rel = os.path.relpath(p, src)
                dst = os.path.join(dst_root, str(len(SNAPSHOT_DIRS)), rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.copy2(p, dst)
                except OSError:
                    continue
                out.append((p, dst))
    return out


def _restore(snaps: list[tuple[str, str]]) -> None:
    """把快照写回原位 (只写不删)。"""
    for orig, copy in snaps:
        try:
            os.makedirs(os.path.dirname(orig), exist_ok=True)
            shutil.copy2(copy, orig)
        except OSError:
            pass


def _run(name: str) -> tuple[int, str]:
    path = os.path.join(TESTS, name + ".py")
    if not os.path.isfile(path):
        return 2, f"未找到 {path}"
    p = subprocess.run([sys.executable, path], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# 环境性抖动 (跟被测代码无关, 重跑一次就好) —— 命中就在门禁层重试一轮:
#   · 扩展的 MV3 service worker 被浏览器回收: "Detached while handling command"
#   · 桥/扩展忙不过来: "桥无响应" / "[TIMEOUT]"
# 只重试一次, 且重试结果会打印出来, 不让它掩盖真问题。
FLAKY_MARKERS = ("Detached while handling command", "桥无响应", "[TIMEOUT]",
                 "还没有受控标签页")


def _run_with_flake_retry(name: str) -> tuple[int, str, bool]:
    rc, out = _run(name)
    if rc == 0 or not any(m in out for m in FLAKY_MARKERS):
        return rc, out, False
    time.sleep(3)
    rc2, out2 = _run(name)
    if rc2 == 0:
        return 0, out2 + "\n(注: 首轮命中环境性抖动, 重试后通过)", True
    return rc2, out2, True


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("filters", nargs="*", help="只跑名字含这些关键字的门禁")
    ap.add_argument("--with-online", action="store_true", help="包含在线门禁")
    ap.add_argument("--list", action="store_true", help="只列出可跑的门禁")
    args = ap.parse_args()

    gates = list(OFFLINE) + (list(ONLINE) if args.with_online else [])
    if args.filters:
        gates = [(n, d) for n, d in gates
                 if any(f in n for f in args.filters)]
    if not gates:
        print("没有匹配的门禁")
        return 1
    if args.list:
        for n, d in gates:
            print(f"  {n:<26} {d}")
        return 0

    print(f"运行 {len(gates)} 项门禁 (python: {sys.executable})\n")
    tmp = tempfile.mkdtemp(prefix="taglib-gates-")
    snaps = _snapshot(tmp)
    results: list[tuple[str, bool, str]] = []
    try:
        for name, desc in gates:
            code, out, retried = _run_with_flake_retry(name)
            ok = code == 0
            results.append((name, ok, out))
            note = " (首轮抖动, 重试通过)" if (ok and retried) else ""
            print(f"{'PASS' if ok else 'FAIL'}  {name:<24} {desc}{note}")
            if not ok:
                tail = "\n".join(out.strip().splitlines()[-12:])
                print("      " + tail.replace("\n", "\n      "))
    finally:
        _restore(snaps)
        shutil.rmtree(tmp, ignore_errors=True)

    npass = sum(1 for _, ok, _ in results if ok)
    nfail = len(results) - npass
    print(f"\n结果: {npass} 通过 / {nfail} 失败 (数据目录已还原)")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
