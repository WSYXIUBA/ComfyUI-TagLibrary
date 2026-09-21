"""JSON 原子写 —— 全仓唯一的写盘策略真源。

原先 11 处写盘点各自复制了同一段 `tmp + json.dump(ensure_ascii=False) + os.replace`,
缩进策略散落各处 (改一次格式要改 11 处), 将来要加 fsync / 写前备份也没有统一入口。

    atomic_write_json(path, data)               # indent=1, 人工可编辑的库文件
    atomic_write_json(path, data, indent=None)  # 紧凑, 纯机器读的指纹文件

tmp 与目标同目录: os.replace 只在同一文件系统内保证原子。
"""

from __future__ import annotations

import json
import os


def atomic_write_json(path: str, data, *, indent: int | None = 1) -> None:
    """把 data 以 JSON 原子写入 path (先写 path.tmp, 再 replace)。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)
