"""v11 验证: 三级侧栏树 + 排除页三级勾选 (resilient CDP runner)。"""

import json
import time
import urllib.request

from websocket import create_connection


def find_tab(sub):
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and sub in t["url"]]
    return tabs[0] if tabs else None


def fresh_ws(sub):
    tab = find_tab(sub)
    if not tab:
        return None
    try:
        return create_connection(tab["webSocketDebuggerUrl"], timeout=8, suppress_origin=True)
    except Exception:
        return None


mid = [8000]


def run(expr, to=20):
    for attempt in range(3):
        ws = fresh_ws("v11fresh")
        if ws is None:
            time.sleep(3)
            continue
        try:
            mid[0] += 1
            ws.settimeout(to)
            ws.send(json.dumps({"id": mid[0], "method": "Runtime.evaluate",
                                "params": {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True}}))
            deadline = time.time() + to
            while time.time() < deadline:
                try:
                    x = json.loads(ws.recv())
                    if x.get("id") == mid[0]:
                        rr = x.get("result", {})
                        if "exceptionDetails" in rr:
                            return "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:150]
                        return rr["result"].get("value")
                except Exception:
                    continue
            return "TIMEOUT"
        finally:
            try:
                ws.close()
            except Exception:
                pass
    return "ws-failed"


# step1: 初始化页面 + 节点
print("init:", run("""
(async () => {
  if (document.body.innerText.includes('拒绝访问')) { location.reload(); return '403'; }
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{})) {
    try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
  }
  if (!window.app?.graph) return 'noapp';
  await window.app.graph.clear();
  const node = LiteGraph.createNode('TagLibraryNode');
  if (!node) return 'ext-not-ready';
  node.pos=[80,80]; node.size=[470,760];
  window.app.graph.add(node);
  await new Promise(r=>setTimeout(r,2200));
  return 'ok';
})()
""", to=25))

time.sleep(1)

# step2: 打开挑选器 + 展开人物主体树
print("tree:", run("""
(async () => {
  const btn = document.querySelector('[data-act=addtags]');
  if (!btn) return 'no btn';
  btn.click();
  await new Promise(r=>setTimeout(r,1600));
  const dlg = document.querySelector('#taglib-picker-dialog');
  if (!dlg) return 'no dialog';
  const rows = dlg.querySelectorAll('.tp-cat');
  const subjRow = [...rows].find(r2 => r2.textContent.includes('人物主体'));
  if (!subjRow) return 'no subj row, rows=' + rows.length;
  const chev = subjRow.querySelector('.tp-chev');
  if (chev) chev.click();
  await new Promise(r=>setTimeout(r,350));
  return JSON.stringify({
    level1: [...dlg.querySelectorAll('.tp-cat-l1')].map(e=>e.querySelector('.nm')?.textContent).slice(0,8),
    level2: [...dlg.querySelectorAll('.tp-cat-l2')].map(e=>e.querySelector('.nm')?.textContent).slice(0,8)});
})()
""", to=22))

# step3: 切到排除页, 验证三级勾选
print("exclude:", run("""
(async () => {
  const dlg = document.querySelector('#taglib-picker-dialog');
  if (!dlg) return 'dialog closed';
  dlg.querySelector('.tp-excludetab').click();
  await new Promise(r=>setTimeout(r,400));
  // 展开人物主体
  const cards = [...dlg.querySelectorAll('.tp-exc-card')];
  const subjCard = cards.find(c => c.textContent.includes('人物主体'));
  if (!subjCard) return 'no subj card';
  subjCard.querySelector('.tp-exc-toggle').click();
  await new Promise(r=>setTimeout(r,350));
  // 现在应有子分类卡片; 找 外貌 并展开
  const subCards = [...dlg.querySelectorAll('.tp-exc-card')];
  const wgCard = subCards.find(c => c.textContent.includes('外貌'));
  if (!wgCard) return JSON.stringify({subCards: subCards.map(c=>c.textContent.slice(0,12)).slice(0,8)});
  const t2 = wgCard.querySelector('.tp-exc-toggle2');
  if (t2) t2.click();
  await new Promise(r=>setTimeout(r,350));
  const all = [...dlg.querySelectorAll('.tp-exc-card')];
  const gCards = all.filter(c => c.style.marginLeft.includes('52px'));
  return JSON.stringify({
    topLevel: cards.length,
    subVisible: subCards.length - cards.length,
    groupVisible: gCards.map(c=>c.textContent.slice(0,10))});
})()
""", to=22))

# step4: 勾选排除一个孙分类 (五官), 确认保存
print("save:", run("""
(async () => {
  const dlg = document.querySelector('#taglib-picker-dialog');
  const gCards = [...dlg.querySelectorAll('.tp-exc-card')].filter(c => c.style.marginLeft.includes('52px'));
  const wuGuan = gCards.find(c => c.textContent.includes('五官'));
  if (!wuGuan) return 'no 五官 card';
  wuGuan.querySelector('input').click();
  await new Promise(r=>setTimeout(r,350));
  wuGuan.querySelector('input').click();  // 再点取消, 不留状态
  await new Promise(r=>setTimeout(r,350));
  // 关闭
  dlg.querySelector('.tp-cancel').click();
  return 'toggled ok';
})()
""", to=18))

print("DONE")
