import json, time, urllib.request
from websocket import create_connection

tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read())
        if t.get("type") == "page" and "8188" in t.get("url", "")]
ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
mid = [300000]
def cmd(m, p=None, to=60):
    mid[0] += 1; ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
    dl = time.time() + to
    while time.time() < dl:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]: return x
        except Exception: continue
    return {}
def ev(e, to=60):
    x = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True}, to)
    r = x.get("result", {}).get("result", {})
    return "ERR:" + str(r.get("description", ""))[:400] if r.get("subtype") == "error" else r.get("value")

def disk_tags():
    uj = json.loads(open("data/tag_library.user.json", encoding="utf-8-sig").read())
    return sum(len(s.get("tags", [])) for c in uj.get("categories", []) for s in c.get("subcategories", []))

# 0) 刷新管理页 (加载修复后的 manager.js)
cmd("Page.reload", {"ignoreCache": True})
time.sleep(7)
for i in range(10):
    if ev("!!document.querySelector('#catList')") is True: break
    time.sleep(1)
print("V0 mgr ready, disk:", disk_tags())

# 1) UI 点清空 (直接清空)
print("V1 clear:", ev("""(() => {
  const b = [...document.querySelectorAll('button')].find(x => /清空/.test(x.textContent||''));
  if (!b) return 'NO btn'; b.click(); return 'opened dialog';
})()"""))
time.sleep(1)
print("V1b direct-clear:", ev("""(() => {
  const b = [...document.querySelectorAll('.modal-actions button, .modal-box button')].find(x => /直接清空/.test(x.textContent||''));
  if (!b) return 'NO btn'; b.click(); return 'clicked';
})()"""))
time.sleep(2)
print("V1c after clear disk:", disk_tags())

# 2) 导入全量模板
md = open("data/_repro_full_template.md", encoding="utf-8").read()
ev_js = """
(async () => {
  const md = %s;
  const input = document.querySelector('#mdFileInput');
  const dt = new DataTransfer();
  dt.items.add(new File([md], 'f.md', {type:'text/markdown'}));
  input.files = dt.files;
  input.dispatchEvent(new Event('change', {bubbles: true}));
  return 'ok';
})()
""" % json.dumps(md)
print("V2 inject:", ev(ev_js, 30))
time.sleep(4)
print("V2b preview:", ev("""(() => {
  const d = document.querySelector('#previewDialog');
  return d && !d.classList.contains('hidden') ? 'VISIBLE ' + document.querySelector('#pvCount')?.textContent : 'hidden';
})()"""))
print("V2c confirm:", ev("document.querySelector('#pvOk').click(), 1"))
time.sleep(4)
print("V2d after import disk:", disk_tags())

# 3) 点保存更改 (之前这一步灭词)
print("V3 save:", ev("""(() => {
  [...document.querySelectorAll('button')].find(b => /保存更改/.test(b.textContent||'')).click();
  return 'clicked';
})()"""))
time.sleep(6)
print("V3 FINAL disk after save:", disk_tags())
print("V3 ui stats:", ev("document.body.innerText.match(/合计 \d+ 个标签/)?.[0] || 'n/a'"))

# 4) 再来一轮: 刷新页面再保存 (验证懒加载保存)
cmd("Page.reload", {"ignoreCache": False})
time.sleep(7)
print("V4 reload, disk:", disk_tags())
ev("""(() => { [...document.querySelectorAll('button')].find(b => /保存更改/.test(b.textContent||'')).click(); return 1; })()""")
time.sleep(6)
print("V4 FINAL disk after reload+save:", disk_tags())
