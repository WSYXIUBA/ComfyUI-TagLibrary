# 复现用户报告: ①自动模式会不会出双武器 ②手动模式武器+姿势混乱 ③姿势池贫乏导致的乱配
import sys, collections
sys.path.insert(0, '.')
import library, runtime_snapshot, random_engine
from nodes import TagLibraryNode

lib = library.get_merged()
snap = runtime_snapshot.get_snapshot(lib)
st = snap.slots
wi = st.slot_index['weapon']

# --- ① 自动模式 2000 seed: 每次抽出的武器数分布
cfg = random_engine.resolve_config({'fill_master': True, 'fill_master_min': 2, 'fill_master_max': 3}, {})
state = {'tags': [], 'fill_master': True, 'fill_master_min': 2, 'fill_master_max': 3}
dist = collections.Counter()
for seed in range(2000):
    r = random_engine.run_auto(snap, state, seed, nsfw_on=False, config=cfg)
    dist[sum(1 for i in r.fixed_ids + r.rest_ids if st.slot_of[i] == wi)] += 1
print('① 自动模式 2000 seed 武器数分布:', dict(dist))

# --- ② 手动模式: 挑两把武器+一个姿势 → 输出什么样
node = TagLibraryNode()
mstate = {'tags': [{'en': 'katana', 'enabled': True}, {'en': 'crossbow', 'enabled': True},
                   {'en': 'holding sword', 'enabled': True}, {'en': 'aiming gun', 'enabled': True}],
          'nsfw': True}
out = node.build(__import__('json').dumps(mstate), 'manual', 1)
print('② 手动模式输出:', out[0])

# --- ③ 姿势贫乏/乱配: 每组能绑的姿势 + 可疑成员
for g, gm in __import__('json').load(open('data/default/slots.json', encoding='utf-8'))['weapon_groups'].items():
    print(f'   {g}: 武器{len(gm["weapons"])} ←→ 姿势 {gm["poses"]}')
# grimoire(魔导书) 会绑 holding staff 吗?
gid = snap.en_to_id['grimoire']
print('③ grimoire 可绑姿势:', [snap.tag_text[p] for p in st.weapon_to_poses.get(gid, ())])
bid = snap.en_to_id['bow and arrow']
print('   bow and arrow 可绑姿势:', [snap.tag_text[p] for p in st.weapon_to_poses.get(bid, ())])
# 非手持物被当武器?
susp = [w for w in ('sniper scope', 'quiver', 'katana sheath', 'shield bash', 'sheathed sword', 'katana on back')
        if w in snap.en_to_id and st.slot_of[snap.en_to_id[w]] == wi]
print('   槽=weapon 的非手持物:', susp)
