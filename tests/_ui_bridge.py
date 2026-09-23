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

import atexit
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
        self._storage_backup: dict | None = None   # 用户草稿/上次工作流的原始快照

    # ---------------------------------------------------------------- 连接
    def connect(self) -> None:
        from websocket import create_connection

        info = _bridge_token()
        if not info:
            raise UiError("NO_BRIDGE", f"读不到 {BRIDGE_INFO} —— 桥从没起过。"
                                       f"先跑: node {HUASHU_DIR}\\src\\cli.js bridge")
        token, port = info
        # ⚠ 必须 suppress_origin: 桥按 Origin 区分角色, 带 Origin 的 Node 客户端会被拒
        # ⚠ 桥进程不在时 create_connection 抛的是原生 ConnectionRefusedError —— 不包成
        #   UiError 的话, ensure_bridge 的"没起就拉起来"分支根本走不到 (实测)。
        try:
            self.ws = create_connection(f"ws://127.0.0.1:{port}", timeout=CMD_TIMEOUT,
                                        suppress_origin=True)
        except OSError as e:
            self.ws = None
            raise UiError("NO_BRIDGE", f"连不上 ws://127.0.0.1:{port} ({e})") from e
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
        worker 被回收后要几秒才醒, 所以退避必须够长, 且每次重试前先发一个廉价命令
        把它叫起来 —— 1.5s × 3 的老参数在真机连跑里仍被打穿 (2026-09-21:
        两轮在线门禁各命中一次, 分别挂在 ui_theme_dark.png / ui_prof.png)。
        """
        last = None
        data = None
        for attempt in range(5):
            try:
                data = self.cmd("screenshot", {"full": True}, tab_id)
                break
            except UiError as e:
                last = e
                if "Detached" not in str(e) and "TIMEOUT" not in str(e):
                    raise
                time.sleep((1.5, 3.0, 6.0, 10.0)[min(attempt, 3)])
                try:                      # 唤醒被回收的 worker; 它自己失败也无所谓
                    self.cmd("tabs", {"action": "list"})
                except UiError:
                    pass
        if data is None:
            # 5 次都没救回来 → **重建会话**再试一次 (L2 调试会话卡死时只有重连能治)
            try:
                self.close()
                self.connect()
                time.sleep(2)
                data = self.cmd("screenshot", {"full": True}, tab_id)
            except Exception as e:  # noqa: BLE001 — 重连本身也可能失败
                last = e
        if data is None:
            # 截图只作留证, 门禁断言不靠它 —— 桥真掉线时给显眼告警后继续,
            # 别让一次截图失败把整轮门禁判红 (2026-09-21: 两次假红都出在这一步)。
            print(f"⚠ 截图失败 (桥 L2 掉线, 重连后仍不行): {name} — {last}")
            return ""
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
            self.backup_storage(tab_id)
        return tab_id

    # ------------------------------------------------- 用户浏览器存储的防污染
    # 门禁会在 ComfyUI 页面上建 __tl_gate__ 测试节点, 而 ComfyUI 会把画布状态
    # **自动存成草稿** (Comfy.Workflow.Draft.v2:personal:<id>) —— 于是用户的工作流
    # 草稿里被塞进一堆测试节点 (2026-09-21 实测: 一份草稿里 15 个), 下次打开
    # 工作流就带出来。收尾时把草稿/上次工作流原样还原, 才是真"不留垃圾"。
    #
    # ⚠ 快照**存在页面 localStorage 里**, 不走 eval 回传: 扩展的 evaluate 有
    #   20000 字符上限, 草稿动辄 75KB, 回传必然被截断 (实测 JSONDecodeError)。
    #   这里只回传键名与长度。
    _DRAFT_KEYS = ("Comfy.Workflow.Draft", "workflow")
    _BACKUP_KEY = "__tl_gate_draft_backup__"

    def _draft_js(self, mode: str) -> str:
        keys, bk = json.dumps(list(self._DRAFT_KEYS)), json.dumps(self._BACKUP_KEY)
        match = f"const K={keys}; const hit=(k)=>K.some(p=>k.startsWith(p));"
        if mode == "backup":
            return ("(() => { %s"
                    " if (localStorage.getItem(%s)) return JSON.stringify({kept:true});"
                    " const o={}; for (const k of Object.keys(localStorage))"
                    " { if (hit(k)) o[k]=localStorage.getItem(k); }"
                    " localStorage.setItem(%s, JSON.stringify(o));"
                    " return JSON.stringify({n:Object.keys(o).length,"
                    " bytes:JSON.stringify(o).length, keys:Object.keys(o)}); })()"
                    % (match, bk, bk))
        return ("(() => { %s"
                " const raw=localStorage.getItem(%s);"
                " if (!raw) return JSON.stringify({restored:false});"
                " const s=JSON.parse(raw);"
                " for (const k of Object.keys(localStorage))"
                " { if (hit(k) && !(k in s)) localStorage.removeItem(k); }"
                " for (const k of Object.keys(s)) localStorage.setItem(k, s[k]);"
                " localStorage.removeItem(%s);"
                " return JSON.stringify({restored:true, n:Object.keys(s).length}); })()"
                % (match, bk, bk))

    def backup_storage(self, tab_id: int) -> None:
        """备份 ComfyUI 草稿/上次工作流 (快照留在页面里, 只回传元信息)。"""
        if self._storage_backup:
            return
        # 新标签页刚建出来时可能还没落到目标 origin, 这时读到的 localStorage 是空的
        # (甚至会读到 about:blank) —— 空结果重试几次, 别把"没备份"当成"没草稿"。
        for attempt in range(3):
            try:
                raw = self.ev(self._draft_js("backup"), tab_id)
                info = json.loads(raw) if isinstance(raw, str) else {}
                if info.get("n") or info.get("kept"):
                    self._storage_backup = info or {}
                    print(f"    (草稿快照: {info.get('n', 0)} 项 / {info.get('bytes', 0)} 字节"
                          f"{', 沿用本轮已有快照' if info.get('kept') else ''})")
                    return
            except UiError as e:
                if attempt == 2:
                    print(f"    (提示: 草稿备份失败, 本轮不做还原: {e})", file=sys.stderr)
                    return
            time.sleep(1.5)
        print("    (提示: 没读到可备份的草稿, 本轮不做还原)")

    def restore_storage(self, tab_id: int) -> None:
        """还原草稿 —— 收尾动作, 失败不该拖垮整轮门禁。"""
        if not self._storage_backup:
            return
        try:
            self.ev(self._draft_js("restore"), tab_id)
        except UiError as e:
            print(f"    (收尾提示: 草稿还原失败: {e})", file=sys.stderr)

    def cleanup_tabs(self) -> None:
        """异常退出兜底: 把本轮开过、还没关的标签页关掉。

        正常路径每条都调了 close_tab, 但门禁失败时可能直接 sys.exit / 抛异常,
        标签页就留给用户了 (2026-09-21 实测: 一轮在线门禁留下 2 个
        「TagLib 弹层门禁」标签页)。注册到 atexit, 崩了也收干净。
        """
        for t in list(self.tabs_opened):
            try:
                self.close_tab(t)
            except Exception:  # noqa: BLE001  收尾不许再抛
                pass

    def close_tab(self, tab_id: int) -> None:
        """关掉自己的标签页 —— 收尾动作, 失败不该拖垮整轮门禁。

        ⚠ tabId 必须放进 **params**: 扩展的 tabs 处理器读的是 `p.tabId`, 信封里的
        tabId 只有 ask 之类用。放错位置 → `resolveTab` 回落到会话的缺省槽 → 报
        `NO_TAB 还没有受控标签页` 并且**真的不关** (2026-09-21 实测: 在线门禁
        每轮都给用户留 2 个标签页, 就是这里)。
        """
        self.restore_storage(tab_id)          # 先还原用户的草稿, 再关
        try:
            self.cmd("tabs", {"action": "close", "tabId": tab_id}, tab_id)
        except UiError as e:
            print(f"    (收尾提示: 关闭标签页 {tab_id} 失败: {e})", file=sys.stderr)
        finally:
            self.tabs_opened = [t for t in self.tabs_opened if t != tab_id]


def ensure_bridge(session_id: str = "taglib-gates") -> UiBridge:
    """拿到一个连好的 UiBridge; 桥没起就自己拉起来 (最多等 ~20s)。"""
    ui = UiBridge(session_id=session_id)
    atexit.register(ui.cleanup_tabs)      # 崩了也别把标签页/草稿垃圾留给用户
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
    """等 ComfyUI 前端就绪 (window.app.graph 出来)。

    ⚠ 只查一次不够 (2026-09-21 假红): 服务端刚重启后首次打开页面时, 前端可能
    在资产指纹比对后**再自动 reload 一次** —— 那一瞬间 `window.app` 已经存在过、
    随后又被清空, 于是紧随其后的 `ev()` 报 `Cannot read properties of undefined`。
    所以要求「app 在 + 文档加载完」连续两次都成立 (间隔 2s) 才算就绪。
    """
    deadline = time.time() + timeout
    stable = 0
    while time.time() < deadline:
        try:
            if ui.ev("!!(window.app && window.app.graph && document.readyState === 'complete')", tab_id):
                stable += 1
                if stable >= 2:
                    return True
            else:
                stable = 0
        except UiError:
            stable = 0
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
