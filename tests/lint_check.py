"""lint 门禁: 死导入 / 重复定义 / 死变量 (ruff F401 F811 F841)。

为什么上闸: 全仓曾积下 53 处死导入, 成因全是"复制粘贴后忘了删"
(四个路由模块互相抄导入头), 人眼审查成本高且必然再犯。

ruff 是外部二进制, 找不到就**判失败** —— 宁可红也不静默跳过, 否则门禁等于没有。

用法: python tests/lint_check.py
"""

from __future__ import annotations

import ast
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELECT = "F401,F811,F841"
EXCLUDE = ["tests/_scratch"]  # 历史归档脚本, 不属门禁范围

# ---------------------------------------------------------------- _common 导入白名单
# api/_common.py 是"路由公共层", 只允许放**常量**与**无业务依赖的工具** (路径 / 响应
# 封装 / 中间件)。它一度 import 了 8 个业务模块却一个都没用到 —— 那样一旦有人从这里删
# 东西, 会在完全无关的路由模块里炸出 ImportError, 报错位置和真实原因还对不上。
COMMON_ALLOWED_ABS = {"__future__", "os", "re", "json", "time", "typing",
                      "collections", "hashlib", "shutil", "urllib", "aiohttp"}
COMMON_ALLOWED_REL = {"jsonio"}  # 纯工具, 无业务依赖


def check_common_imports() -> list[str]:
    path = os.path.join(ROOT, "api", "_common.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in COMMON_ALLOWED_ABS:
                    bad.append(f"import {a.name}  (第 {node.lineno} 行)")
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入 = 插件包内模块 (业务模块从这儿进来)
                mod = (node.module or "").split(".")[0]
                if mod not in COMMON_ALLOWED_REL:
                    bad.append(f"from .{node.module or ''} import ...  (第 {node.lineno} 行)")
            elif (node.module or "").split(".")[0] not in COMMON_ALLOWED_ABS:
                bad.append(f"from {node.module} import ...  (第 {node.lineno} 行)")
    return bad


def find_ruff() -> str | None:
    """按优先级找 ruff: PATH → 系统 Python 的 Scripts → 常见用户目录。"""
    cands = [shutil.which("ruff")]
    local = os.environ.get("LOCALAPPDATA") or ""
    cands += glob.glob(os.path.join(local, "Programs", "Python", "Python*", "Scripts", "ruff.exe"))
    cands += [
        os.path.join(os.path.expanduser("~"), ".local", "bin", "ruff.exe"),
        os.path.join(os.path.dirname(sys.executable), "Scripts", "ruff.exe"),
        os.path.join(os.path.dirname(sys.executable), "ruff.exe"),
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def main() -> int:
    ruff = find_ruff()
    if not ruff:
        print("未找到 ruff —— lint 门禁无法运行, 判失败。")
        print("安装: pip install ruff   (或 uv tool install ruff)")
        return 1

    cmd = [ruff, "check", "--select", SELECT, "--output-format", "concise"]
    for e in EXCLUDE:
        cmd += ["--exclude", e]
    cmd.append(".")
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print((p.stdout or "").strip() or "(无输出)")
    if p.returncode != 0:
        print(f"\n❌ 死代码门禁失败 (ruff {SELECT}) —— 删掉未使用的导入/变量; "
              f"有意的对外 re-export 加 `# noqa: F401`。")
        return 1

    bad = check_common_imports()
    if bad:
        print("\n❌ api/_common.py 引入了业务依赖 (路由公共层约束):")
        for b in bad:
            print(f"   - {b}")
        print("   业务函数请放到它自己的模块 (如 library/tagfiles), 路由模块直接调那个模块。")
        return 1

    print(f"\n✅ 死代码门禁通过 (ruff {SELECT}, 排除 {', '.join(EXCLUDE)})")
    print("✅ _common 导入白名单通过 (只有常量与无业务工具)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
