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
import importlib.util
import os
import sys
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
taglib_csrf_middleware = api_pkg.taglib_csrf_middleware  # noqa: E402


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


class _FakeReq:
    """最小 web.Request 替身: 只喂 json() 给导入端点。"""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


async def _import_checks() -> list[str]:
    """📥 导入 .json 的防呆 (1.12.0 新端点)。

    老的两组检查 (导出目录确认 / 双向删除精确匹配) 随 .md 镜像层一起下线:
    新导出是纯 JSON 下载 (不落任意路径), 新导入只写库本身 (无外部路径参数),
    于是真正要守住的是「垃圾载荷必须被拒」。
    """
    errs: list[str] = []
    resp = await api_pkg.import_library(_FakeReq({"library": {"nope": 1}}))
    if resp.status != 400:
        errs.append(f"S4 非库文件载荷: 期望 400, 实际 {resp.status}")
    resp = await api_pkg.import_library(_FakeReq({"library": {"categories": "不是数组"}}))
    if resp.status != 400:
        errs.append(f"S4 categories 非数组: 期望 400, 实际 {resp.status}")
    return errs


def main() -> int:
    errs = asyncio.run(_csrf_checks())
    errs += asyncio.run(_import_checks())
    if errs:
        print(f"❌ API 安全门禁失败 ({len(errs)} 项):")
        for e in errs:
            print("   -", e)
        return 1
    print("✅ API 安全门禁通过 (CSRF 中间件 / 导入 .json 载荷防呆)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
