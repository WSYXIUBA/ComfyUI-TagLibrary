"""一键门禁 —— 跑全部验收测试并汇总结果。

用法:
    python tools/run_gates.py              # 全部离线门禁
    python tools/run_gates.py --with-online  # 加上需要 ComfyUI 实例的在线门禁
    python tools/run_gates.py m1 m3        # 只跑名字匹配这些关键字的门禁
    python tools/run_gates.py --list       # 列出所有门禁

为什么要经过这个脚本而不是逐个 python tests/xxx.py:
  1. 自动快照/还原 data/default/taglib/ —— 部分门禁 (folder_template_test 等) 会
     真实写入文件夹镜像与 _sync_state.json, 直接跑会污染工作区, 让 git status
     出现与代码无关的改动。
  2. 统一汇总 + 失败时打印尾部日志, 退出码可直接用于 CI。

⚠ 若 ComfyUI 正在运行, 它的热同步会在还原之后再次触碰 _sync_state.json
   (插件在 get_merged 里做文件夹双向同步)。提交前请先停掉 ComfyUI, 或再
   执行一次 `git checkout -- data/`。

返回码: 0 = 全部通过; 1 = 有失败。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

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
    ("folder_template_test", "文件夹热同步"),
    ("parser_conflict_test", ".md 解析器"),
    ("perf_build_test", "性能门禁 (10k 库 p50<3ms)"),
    ("quality_gate_test", "输出质量门禁 (词数/配额/互斥/人数/畸形词/确定性)"),
    ("prompt_quality_test", "完整提示词重度测试 (文本层语义/段位/性别/负向词)"),
]

# 需要 ComfyUI 在跑的在线门禁 (--with-online 才跑)
ONLINE = [
    ("real_http_test", "真机 ComfyUI HTTP queue 验收 (接口/端口/性别锁)"),
    ("node_output_test", "真机节点输出测试 (60 次生成 × 文本层断言)"),
    ("ui_v13_check", "CDP 浏览器 UI 巡检 (面板/页签/可编辑/开关)"),
    ("ui_theme_check", "CDP 浏览器主题一致性巡检 (深色/浅色/管理页)"),
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
            code, out = _run(name)
            ok = code == 0
            results.append((name, ok, out))
            print(f"{'PASS' if ok else 'FAIL'}  {name:<24} {desc}")
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
