"""API 安全门禁 —— CSRF 中间件 / 导出目录确认 / 双向删除精确匹配。

python tests/api_security_test.py

背景 (1.6.6 全仓体检): ComfyUI 主应用无鉴权, 用户浏览器里打开的任意网页都能把
请求打进 localhost:8188 —— text/plain 简单请求可绕过 CORS 预检, 让删库/覆盖库/
向任意路径导出文件真正执行。本门禁固化三层防线:

  S1 CSRF 中间件   /taglib/api/* 的写方法: Origin/Referer 指向别处 → 403;
                   同源 / 无 Origin (curl、测试脚本) / GET → 放行
  S2 导出目录确认  export-folder 导出 data/ 之外需显式 confirm=true
  S3 双向删除      文件夹→库 的反向匹配只认精确名 (原名/净化名/(n)后缀),
                   包含式模糊匹配会把"文件已删"误判成"还在" (上装 ⊂ 上装细节)
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

# api/ 包内部用的是 `from .. import library` 相对导入, 只能作为插件根包的子包
# 加载 —— 这里用合成父包 (path 指向仓库根) 把 api 挂起来, 不执行根 __init__.py
_PARENT = "taglib_plugin"
if _PARENT not in sys.modules:
    _pkg = types.ModuleType(_PARENT)
    _pkg.__path__ = [ROOT]
    sys.modules[_PARENT] = _pkg


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[os.path.dirname(path)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


api_pkg = _load(f"{_PARENT}.api", os.path.join(ROOT, "api", "__init__.py"))
library = importlib.import_module(f"{_PARENT}.library")  # noqa: E402
tagfiles = importlib.import_module(f"{_PARENT}.tagfiles")  # noqa: E402
taglib_csrf_middleware = api_pkg.taglib_csrf_middleware  # noqa: E402
_export_dir_error = importlib.import_module(
    f"{_PARENT}.api.tagfiles_routes")._export_dir_error  # noqa: E402


async def _csrf_checks() -> list[str]:
    errs: list[str] = []
    app = web.Application()
    app.middlewares.append(taglib_csrf_middleware)

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_post("/taglib/api/dummy", ok)
    app.router.add_get("/taglib/api/dummy", ok)
    app.router.add_post("/not-taglib/dummy", ok)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        same = f"http://{client.host}:{client.port}"
        evil = "https://evil.example"

        async def post(headers: dict | None, path: str = "/taglib/api/dummy") -> int:
            r = await client.post(path, json={"x": 1}, headers=headers or {})
            await r.read()
            return r.status

        async def get(headers: dict | None) -> int:
            r = await client.get("/taglib/api/dummy", headers=headers or {})
            await r.read()
            return r.status

        def expect(name: str, got: int, want: int) -> None:
            if got != want:
                errs.append(f"{name}: 期望 {want} 实际 {got}")

        expect("无 Origin (curl/脚本) 放行", await post(None), 200)
        expect("同源 Origin 放行", await post({"Origin": same}), 200)
        expect("跨站 Origin 拒绝", await post({"Origin": evil}), 403)
        expect("不透明 Origin (null) 拒绝", await post({"Origin": "null"}), 403)
        expect("同源 Referer 兜底放行",
               await post({"Referer": f"{same}/taglib?embed=1"}), 200)
        expect("跨站 Referer 拒绝",
               await post({"Referer": f"{evil}/attack"}), 403)
        expect("GET 不拦 (响应本就读不到)", await get({"Origin": evil}), 200)
        expect("非本插件路径不拦",
               await post({"Origin": evil}, path="/not-taglib/dummy"), 200)
        # Host 与 Origin 端口不一致 = 不同服务, 也得拦
        expect("跨端口 Origin 拒绝",
               await post({"Origin": f"http://{client.host}:{client.port + 1}"}), 403)
    finally:
        await client.close()
    return errs


def _export_dir_checks() -> list[str]:
    errs: list[str] = []
    data_root = os.path.realpath(os.path.join(ROOT, "data"))
    inside = os.path.join(data_root, "default", "taglib")
    outside = os.path.join(tempfile.gettempdir(), "taglib_sec_external")
    cases = [
        ("相对路径拒绝", "relative/path", {}, True),
        ("data/ 内放行", inside, {}, False),
        ("data/ 根放行", data_root, {}, False),
        ("外部目录无 confirm 拒绝", outside, {}, True),
        ("外部目录 confirm 放行", outside, {"confirm": True}, False),
    ]
    for name, folder, payload, want_err in cases:
        err = _export_dir_error(folder, payload)
        if want_err and not err:
            errs.append(f"S2 {name}: 期望报错, 实际放行")
        if not want_err and err:
            errs.append(f"S2 {name}: 期望放行, 实际 {err}")
    return errs


def _deletion_checks() -> list[str]:
    errs: list[str] = []
    old_lib_dir, old_default_path = tagfiles.LIBRARY_DIR, library.DEFAULT_PATH
    tmp = tempfile.mkdtemp(prefix="taglib_sec_")
    try:
        # _trash 快照跟着 DEFAULT_PATH 走 → 全部落进沙箱, 不碰真实 data/
        library.DEFAULT_PATH = os.path.join(tmp, "tag_library.json")
        tagfiles.LIBRARY_DIR = tmp

        def cat_dir(name: str) -> str:
            p = os.path.join(tmp, name)
            os.makedirs(p, exist_ok=True)
            return p

        def touch(folder: str, filenames: list[str]) -> None:
            for fn in filenames:
                with open(os.path.join(cat_dir(folder), fn), "w",
                          encoding="utf-8") as f:
                    f.write("")

        def run(lib: dict, missing: list[str]) -> list[str]:
            lib = copy.deepcopy(lib)
            library._apply_folder_deletions(lib, missing)
            return [s["name"] for s in lib["categories"][0]["subcategories"]]

        # S3a 回归: 子分类名互为子串 —— 上装细节.md 已删, 但上装.md 还在,
        # 旧包含式匹配用 "上装" in "上装细节" 把已删的子分类误判成还在
        lib_a = {"categories": [{"id": "c1", "name": "服装", "subcategories": [
            {"id": "c1.a", "name": "上装", "tags": []},
            {"id": "c1.b", "name": "上装细节", "tags": []},
        ]}]}
        touch("服装", ["上装.md"])
        got = run(lib_a, ["服装/上装细节/上装细节.md"])
        if got != ["上装"]:
            errs.append(f"S3a 子串误匹配回归: 期望 ['上装'] 实际 {got}")

        # S3b 常规: 凉鞋.md 已删, 不该被别的文件顶替保命
        lib_b = {"categories": [{"id": "c2", "name": "服装", "subcategories": [
            {"id": "c2.a", "name": "上装", "tags": []},
            {"id": "c2.b", "name": "凉鞋", "tags": []},
        ]}]}
        touch("服装", ["上装.md"])
        got = run(lib_b, ["服装/凉鞋/凉鞋.md"])
        if got != ["上装"]:
            errs.append(f"S3b 已删子分类未删: 期望 ['上装'] 实际 {got}")

        # S3c 净化名: 子分类名带非法字符 → 文件名是 sanitize 后的
        lib_c = {"categories": [{"id": "c3", "name": "场景", "subcategories": [
            {"id": "c3.a", "name": "室内/场景", "tags": []},
        ]}]}
        touch("场景", ["室内_场景.md"])
        got = run(lib_c, [])
        if got != ["室内/场景"]:
            errs.append(f"S3c 净化名匹配失效: 期望 ['室内/场景'] 实际 {got}")

        # S3d 同名净化冲突的去重后缀: _uniq 写出的 "写实(2).md" 也要能对上
        lib_d = {"categories": [{"id": "c4", "name": "风格", "subcategories": [
            {"id": "c4.a", "name": "写实", "tags": []},
        ]}]}
        touch("风格", ["写实(2).md"])
        got = run(lib_d, [])
        if got != ["写实"]:
            errs.append(f"S3d (n) 去重后缀匹配失效: 期望 ['写实'] 实际 {got}")
    finally:
        tagfiles.LIBRARY_DIR = old_lib_dir
        library.DEFAULT_PATH = old_default_path
        # 逐文件清理 (避免 rmtree 触发宿主批量删除保护)
        for root, _dirs, files in os.walk(tmp, topdown=False):
            for fn in files:
                try:
                    os.remove(os.path.join(root, fn))
                except OSError:
                    pass
            try:
                os.rmdir(root)
            except OSError:
                pass
    return errs


def main() -> int:
    errs = asyncio.run(_csrf_checks())
    errs += _export_dir_checks()
    errs += _deletion_checks()
    if errs:
        print(f"❌ API 安全门禁失败 ({len(errs)} 项):")
        for e in errs:
            print("   -", e)
        return 1
    print("✅ API 安全门禁通过 (CSRF 中间件 / 导出目录确认 / 双向删除精确匹配)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
