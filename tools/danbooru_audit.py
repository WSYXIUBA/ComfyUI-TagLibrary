# -*- coding: utf-8 -*-
"""低频词审计 (1.8.0 主线 1a) —— 库内词对照 danbooru post_count。

母数据集口径: Anima 在 danbooru 系数据上训练, post_count 是「模型认识程度」
的最好代理。本工具把合并库每个词查一遍 counts 缓存 (data/packs/danbooru_counts.json,
由 build_ext_pack 前的数据抓取生成), 输出:

  A. 不在 danbooru 高频 35k 词表内的词 —— 自造复合词/极低频词 (最优先处理;
     --verify N 可抽样查线上 API 校准: 区分"存在但低频"与"确认不存在")
  B. post_count < LOW 的低频词 —— 权重上不去, 建议换成高频同义词
  C. 库词 vs danbooru top-N 的覆盖率

报告写 data/packs/audit_report.md。只读, 不改库。

用法: python tools/danbooru_audit.py [--low 1000]
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import library  # noqa: E402

COUNTS_PATH = os.path.join(ROOT, "data", "packs", "danbooru_counts.json")
REPORT_PATH = os.path.join(ROOT, "data", "packs", "audit_report.md")
LOW_DEFAULT = 1000


def main() -> None:
    low = LOW_DEFAULT
    if "--low" in sys.argv:
        low = int(sys.argv[sys.argv.index("--low") + 1])

    try:
        counts = json.load(open(COUNTS_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        print("❌ 找不到 counts 缓存 (data/packs/danbooru_counts.json) — 先跑 build_ext_pack 或抓取脚本")
        sys.exit(1)
    # danbooru 名是下划线形态, 库词是空格形态 → 双向索引
    by_space = {k.replace("_", " "): v for k, v in counts.items()}

    lib = library.get_merged()
    rows: list[tuple[str, str, str, int | None]] = []  # (词, 槽位, nsfw, count)
    for c in lib.get("categories", []):
        for s in c.get("subcategories", []):
            for t in s.get("tags", []):
                en = str(t.get("en") or "").strip()
                if not en:
                    continue
                rows.append((en, f"{c.get('name')}/{s.get('name')}",
                             "NSFW" if t.get("nsfw") else "", by_space.get(en.lower())))

    missing = [r for r in rows if r[3] is None]

    # --verify N: 抽样 N 个未命中词查线上 API, 区分"存在但低频"与"确认不存在"
    verified_live: dict[str, int | None] = {}
    if "--verify" in sys.argv:
        try:
            n_verify = int(sys.argv[sys.argv.index("--verify") + 1])
        except (ValueError, IndexError):
            n_verify = 30
        import random as _rnd
        import urllib.request
        import urllib.parse
        proxy = os.environ.get("TL_PROXY") or "http://192.168.31.181:7890"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy}))
        sample = _rnd.sample(missing, min(n_verify, len(missing))) if missing else []
        for r in sample:
            name = r[0].lower().replace(" ", "_")
            try:
                url = ("https://danbooru.donmai.us/tags.json?" +
                       urllib.parse.urlencode({"search[name_matches]": name, "limit": 1}))
                with opener.open(url, timeout=15) as resp:
                    data = json.load(resp)
                verified_live[r[0]] = int(data[0]["post_count"]) if data else 0
            except Exception:  # noqa: BLE001 — 网络失败不挡报告
                verified_live[r[0]] = None
            time.sleep(0.8)
        hits = {k: v for k, v in verified_live.items() if v}
        print(f"线上抽样 {len(sample)}: 真实存在 {len(hits)}, 确认不存在 "
              f"{sum(1 for v in verified_live.values() if v == 0)}, 网络失败 "
              f"{sum(1 for v in verified_live.values() if v is None)}")
    lowfreq = [r for r in rows if r[3] is not None and r[3] < low]
    nsfw_missing = [r for r in missing if r[2]]
    nsfw_low = [r for r in lowfreq if r[2]]
    covered = sum(1 for r in rows if r[3] is not None and r[3] >= 5000)

    lines = [
        "# 低频词审计报告",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 库内词: {len(rows)} | counts 缓存: {len(counts)} 词",
        f"- danbooru 未命中 (模型基本没见过): **{len(missing)}**",
        f"- 低频 (<{low}): **{len(lowfreq)}**",
        f"- 高频覆盖 (≥5000 posts): {covered} ({covered * 100 // max(len(rows), 1)}%)",
        "",
        "## A. danbooru 未命中 (优先处理: 改词 / 加别名 / 停用)",
        "",
    ]
    for en, slot, flag, _ in sorted(missing, key=lambda r: r[1]):
        lines.append(f"- `{en}` {flag} — {slot}")
    lines += ["", f"## B. 低频词 (<{low} posts, 建议换高频同义词)", ""]
    for en, slot, flag, cnt in sorted(lowfreq, key=lambda r: r[3] or 0):
        lines.append(f"- `{en}` {flag} — {slot} — {cnt} posts")
    if verified_live:
        lines += ["", "## A2. 线上抽样校准 (--verify)", "",
                  "| 词 | danbooru 实际 post_count |", "|---|---|"]
        for k, v in verified_live.items():
            lines.append(f"| `{k}` | {'不存在' if v == 0 else ('网络失败' if v is None else v)} |")
    lines += ["", "## C. 处理建议", "",
              "- 未命中词若确属必要 (角色名/新梗), 在管理页给它加别名; 否则停用或替换。",
              "- 低频词的替换词可直接在吸收器里粘贴候选 prompt 对照。",
              "- 本报告只读不改库; 批量停用走管理页「🧰 批量工具」。"]

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"库内词 {len(rows)} | 不在35k词表 {len(missing)} (NSFW {len(nsfw_missing)}) | "
          f"低频<{low} {len(lowfreq)} (NSFW {len(nsfw_low)}) | 高频覆盖 {covered * 100 // max(len(rows), 1)}%")
    print(f"报告: {REPORT_PATH}")


if __name__ == "__main__":
    main()
