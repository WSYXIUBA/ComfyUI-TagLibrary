"""UI 门禁的浏览器层 —— 走 huashu-chrome 桥驱动**用户自己的 Edge**。

为什么换掉原来的做法: 三个 UI 门禁原本用裸 CDP 连 `127.0.0.1:9222`, 端口没人监听时
自己 `Popen` 拉一个 Edge (`--user-data-dir=C:\\EdgeForHermes`) —— 那是**另一个浏览器**:
没有用户登录态、窗口尺寸不同, 还会在用户屏幕上多弹一个窗口。用户明确禁止。

现在统一走 huashu-chrome 的本地桥 (`ws://127.0.0.1:8899`) + 浏览器扩展。

⚠ 安全铁律: 驱动的是**用户的真实浏览器**。所以这里只开自己的标签页、只关自己的,
绝不碰用户已有的页 —— 旧脚本会"关掉所有旧页签", 那是给一次性调试浏览器写的,
在真浏览器里等于把用户的页面全关了。

用法:
    ui = ensure_bridge()                    # 桥没起就拉起来, 握手 + 确认扩展在线
    tab = ui.new_tab("about:blank", label="TagLib UI 门禁")
    try:
        ui.navigate("http://127.0.0.1:8188/", tab)
        print(ui.ev("document.title", tab))
    finally:
        ui.close_tab(tab)
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_INFO = os.path.join(os.path.expanduser("~"), ".huashu-chrome", "bridge.json")
HUASHU_DIR = os.environ.get("HUASHU_CHROME_DIR", r"D:\code开发共享\huashu-chrome")
# node 路径写死系统 node —— 带版本号的运行时路径会随升级消失 (见 huashu-chrome-ops 技能)
NODE_CANDIDATES = [r"C:\Program Files\nodejs\node.exe", shutil.which("node") or ""]

HANDSHAKE_TIMEOUT = 8
CMD_TIMEOUT = 120


class UiError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


def _node() -> str | None:
    return next((p for p in NODE_CANDIDATES if p and os.path.isfile(p)), None)


def _bridge_token() -> tuple[str, int] | None:
    try:
        with open(BRIDGE_INFO, encoding="utf-8") as f:
            info = json.load(f)
        return str(info["token"]), int(info.get("port") or 8899)
    except Exception:  # noqa: BLE001  文件不存在 / 桥没起过
        return None


class UiBridge:
    """huashu-chrome 桥的极简 Python 客户端 (只要 UI 门禁用得到的那几条命令)。"""

    def __init__(self, session_id: str = "taglib-gates", client: str = "hermes",
                 label: str = "TagLib UI 门禁"):
        self.session_id = session_id
        self.client = client
        self.label = label
        self.ws = None
        self.mid = 0
        self.tabs_opened: list[int] = []

    # ---------------------------------------------------------------- 连接
    def connect(self) -> None:
        from websocket import create_connection

        info = _bridge_token()
        if not info:
            raise UiError("NO_BRIDGE", f"读不到 {BRIDGE_INFO} —— 桥从没起过。"
                                       f"先跑: node {HUASHU_DIR}\\src\\cli.js bridge")
        token, port = info
        # ⚠ 必须 suppress_origin: 桥按 Origin 区分角色, 带 Origin 的 Node 客户端会被拒
        self.ws = create_connection(f"ws://127.0.0.1:{port}", timeout=CMD_TIMEOUT,
                                    suppress_origin=True)
        self.ws.send(json.dumps({"type": "hello", "role": "agent", "token": token,
                                 "client": self.client, "label": self.label,
                                 "sessionId": self.session_id, "v": 1}))
        self.ws.settimeout(HANDSHAKE_TIMEOUT)
        deadline = time.time() + HANDSHAKE_TIMEOUT
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("type") == "welcome":
                self.ws.settimeout(CMD_TIMEOUT)
                if not msg.get("extensionOnline"):
                    raise UiError("NO_EXTENSION",
                                  "扩展没连上桥 —— 让用户点浏览器工具栏的 huashu-chrome "
                                  "图标 → 「重连」, 几秒后重跑")
                return
        raise UiError("NO_BRIDGE", "桥没回 welcome (握手超时)")

    def close(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass
            self.ws = None

    # ---------------------------------------------------------------- 命令
    def cmd(self, name: str, params: dict | None = None, tab_id: int | None = None) -> dict:
        if not self.ws:
            self.connect()
        self.mid += 1
        cid = f"g{self.mid}"
        msg = {"type": "cmd", "id": cid, "cmd": name, "params": params or {}}
        if tab_id is not None:
            msg["tabId"] = tab_id
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv()
            if not raw:
                raise UiError("NO_BRIDGE", "桥断开 (recv 空)")
            m = json.loads(raw)
            if m.get("type") != "res" or m.get("id") != cid:
                continue                      # event / 别的会话的 res
            if not m.get("ok"):
                e = m.get("error") or {}
                raise UiError(str(e.get("code") or "INTERNAL"),
                              str(e.get("message") or e))
            return m.get("data") or {}

    # ---------------------------------------------------------------- 门禁要用的
    def ev(self, expr: str, tab_id: int | None = None):
        """求值。返回 Python 值 —— 语义对齐原来的 CDP Runtime.evaluate(returnByValue)。

        扩展把结果 JSON.stringify 成字符串回传, 所以这里反解一层:
        表达式返回 JS 字符串 → Python str; 返回对象 → dict; `!!x` → bool。

        ⚠ 桥的 eval 是把源文本包进 `(...)` 求值的, 所以**带顶层分号的多语句**会语法错
        (`x = 1; 1`)。这里遇到语法错就自动改包成 IIFE 重试一次 —— 语法错不会产生副作用,
        重试是安全的, 门禁里那些老式多语句探针也就还能直接跑。
        """
        src = expr.strip()
        # MV3 的 service worker 会被浏览器随时回收 → 偶发 "Detached while handling command"。
        # **纯读探针**重试是安全的 (门禁里的断言绝大多数是读); 带 click/set/赋值的一律不重试,
        # 否则可能点两次。
        read_only = not any(k in src for k in ("click(", ".set(", "= ", "focus(", "remove("))
        attempts = 2 if read_only else 1
        last = None
        for _ in range(attempts):
            try:
                data = self.cmd("eval", {"expr": src}, tab_id)
                break
            except UiError as e:
                last = e
                if "Detached" in str(e) or "TIMEOUT" in str(e):
                    if attempts == 1:
                        raise
                    time.sleep(1.5)
                    continue
                if "Unexpected token" not in str(e) and "SyntaxError" not in str(e):
                    raise
                data = self.cmd("eval", {"expr": f"(() => {{ {src} }})()"}, tab_id)
                break
        else:
            raise last
        text = data.get("text")
        if text is None:
            return None
        # 扩展在"命令没带 tabId"时会把一条提醒**追加在返回值末尾** —— 值本身没问题,
        # 但下游(比如读配色 id)会连提醒一起吃进去, 所以这里剥掉。
        _ADV = chr(10) + chr(10) + chr(0x26A0)      # "\n\n⚠"
        if isinstance(text, str) and _ADV in text:
            text = text.split(_ADV)[0]
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return text

    def shot(self, name: str, tab_id: int | None = None) -> str:
        """截图存到 tests/<name> (和旧脚本一致)。

        ⚠ 扩展是 MV3 service worker, 会被浏览器随时回收 —— 长跑门禁里偶发
        "Detached while handling command"。截图是纯读操作, 重试安全。
        """
        last = None
        for attempt in range(3):
            try:
                data = self.cmd("screenshot", {"full": True}, tab_id)
                break
            except UiError as e:
                last = e
                if "Detached" not in str(e) and "TIMEOUT" not in str(e):
                    raise
                time.sleep(1.5)
        else:
            raise last
        url = data.get("dataUrl") or ""
        if "," not in url:
            raise UiError("INTERNAL", f"截图没拿到 dataUrl: {str(data)[:120]}")
        path = name if os.path.isabs(name) else os.path.join(HERE, name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(url.split(",", 1)[1]))
        return name

    def navigate(self, url: str, tab_id: int | None = None) -> None:
        self.cmd("navigate", {"url": url}, tab_id)

    def new_tab(self, url: str = "about:blank", label: str = "") -> int:
        data = self.cmd("tabs", {"action": "new", "url": url, "label": label})
        tab_id = int(data.get("tabId") or 0)
        if tab_id:
            self.tabs_opened.append(tab_id)
        return tab_id

    def close_tab(self, tab_id: int) -> None:
        """关掉自己的标签页 —— 收尾动作, 失败不该拖垮整轮门禁。"""
        try:
            self.cmd("tabs", {"action": "close"}, tab_id)
        except UiError as e:
            print(f"    (收尾提示: 关闭标签页 {tab_id} 失败: {e})", file=sys.stderr)
        finally:
            self.tabs_opened = [t for t in self.tabs_opened if t != tab_id]


def ensure_bridge(session_id: str = "taglib-gates") -> UiBridge:
    """拿到一个连好的 UiBridge; 桥没起就自己拉起来 (最多等 ~20s)。"""
    ui = UiBridge(session_id=session_id)
    try:
        ui.connect()
        return ui
    except UiError as e:
        if e.code != "NO_BRIDGE" or "welcome" in str(e):
            raise
    node = _node()
    if not node:
        raise UiError("NO_BRIDGE", "找不到 node, 也没连上桥")
    cli = os.path.join(HUASHU_DIR, "src", "cli.js")
    if not os.path.isfile(cli):
        raise UiError("NO_BRIDGE", f"找不到 {cli}")
    subprocess.Popen([node, cli, "bridge"], cwd=HUASHU_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    deadline = time.time() + 20
    last = None
    while time.time() < deadline:
        time.sleep(1.5)
        ui = UiBridge(session_id=session_id)
        try:
            ui.connect()
            return ui
        except UiError as e:  # noqa: PERF203
            last = e
    raise UiError("NO_BRIDGE", f"桥起不来: {last}")


def wait_app(ui: UiBridge, tab_id: int, timeout: float = 60) -> bool:
    """等 ComfyUI 前端就绪 (window.app.graph 出来)。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if ui.ev("!!(window.app && window.app.graph)", tab_id):
                return True
        except UiError:
            pass
        time.sleep(2)
    return False


if __name__ == "__main__":       # 手动自检: python tests/_ui_bridge.py
    b = ensure_bridge("taglib-gates-selftest")
    tab = b.new_tab("http://127.0.0.1:8188/", label="bridge 自检")
    try:
        print("tab:", tab)
        print("app ready:", wait_app(b, tab))
        print("title:", b.ev("document.title", tab))
        print("app type:", b.ev("typeof window.app", tab))
        print("shot:", b.shot("_bridge_selftest.png", tab))
    finally:
        b.close_tab(tab)
        b.close()
    sys.exit(0)
