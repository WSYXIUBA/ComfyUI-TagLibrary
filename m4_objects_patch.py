# -*- coding: utf-8 -*-
"""M4: 日常物品档案 + NL 句式扩充 (AI 起草, 词表只用 Danbooru 真实 tag)。幂等。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

P_PATH = os.path.join(ROOT, "data", "default", "taglib", "profiles.json")
N_PATH = os.path.join(ROOT, "data", "default", "taglib", "nl_flavors.json")

OBJ = [
 {"id": "obj.phone", "zh": "手机", "mount_sub": "人物主体/日用道具",
  "tags": ["smartphone"],
  "poses": [
   {"id": "hold", "zh": "单手持机", "tags": ["holding phone"], "hands": 1, "gaze": 0,
    "state_slot": {}, "conflicts_with": [], "implies": []},
   {"id": "look", "zh": "看手机", "tags": ["looking at phone"], "hands": 1, "gaze": 1,
    "state_slot": {},
    "conflicts_with": ["looking at viewer", "looking away", "looking back", "looking afar",
                       "sideways glance", "closed eyes", "wink"],
    "implies": []},
   {"id": "call", "zh": "贴耳通话", "tags": ["phone to ear", "holding phone"], "hands": 1, "gaze": 0,
    "state_slot": {"phone_state": "call"}, "conflicts_with": ["looking at phone"], "implies": []}],
  "extras": []},
 {"id": "obj.book", "zh": "书本", "mount_sub": "人物主体/日用道具",
  "tags": ["book"],
  "poses": [
   {"id": "read", "zh": "阅读", "tags": ["holding book", "open book"], "hands": 2, "gaze": 1,
    "state_slot": {"book_state": "open"},
    "conflicts_with": ["looking at viewer", "looking away", "looking up", "closed eyes", "wink"],
    "implies": []},
   {"id": "hold", "zh": "抱书", "tags": ["holding book"], "hands": 1, "gaze": 0,
    "state_slot": {}, "conflicts_with": [], "implies": []}],
  "extras": [
   {"id": "closed", "zh": "合拢的书", "tags": ["book closed", "holding book"], "hands": 1, "gaze": 0,
    "state_slot": {"book_state": "closed"},
    "conflicts_with": ["open book"], "implies": []}]},
 {"id": "obj.umbrella", "zh": "伞", "mount_sub": "人物主体/日用道具",
  "tags": ["umbrella", "paper umbrella"],
  "poses": [
   {"id": "open", "zh": "撑伞", "tags": ["holding umbrella"], "hands": 1, "gaze": 0,
    "state_slot": {"umbrella_state": "open"}, "conflicts_with": [], "implies": []},
   {"id": "closed", "zh": "收伞持握", "tags": ["holding umbrella closed"], "hands": 1, "gaze": 0,
    "state_slot": {"umbrella_state": "closed"}, "conflicts_with": [], "implies": []}],
  "extras": []},
 {"id": "obj.guitar", "zh": "吉他", "mount_sub": "人物主体/乐器与运动",
  "tags": ["guitar", "acoustic guitar", "electric guitar"],
  "poses": [
   {"id": "play", "zh": "弹奏", "tags": ["playing instrument", "holding guitar"], "hands": 2, "gaze": 0,
    "state_slot": {"guitar_state": "played"}, "conflicts_with": ["holding phone"], "implies": []},
   {"id": "hold", "zh": "抱琴", "tags": ["holding guitar"], "hands": 1, "gaze": 0,
    "state_slot": {"guitar_state": "played"}, "conflicts_with": [], "implies": []}],
  "extras": []},
 {"id": "obj.cup", "zh": "杯子", "mount_sub": "人物主体/食物饮品",
  "tags": ["teacup", "coffee cup"],
  "poses": [
   {"id": "hold", "zh": "端杯", "tags": ["holding cup"], "hands": 1, "gaze": 0,
    "state_slot": {}, "conflicts_with": [], "implies": []},
   {"id": "both", "zh": "双手捧杯", "tags": ["holding cup with both hands"], "hands": 2, "gaze": 0,
    "state_slot": {}, "conflicts_with": ["holding food in mouth", "biting food", "sucking object", "holding lollipop"], "implies": []},
   {"id": "sip", "zh": "啜饮", "tags": ["drinking"], "hands": 1, "gaze": 0,
    "state_slot": {},
    "conflicts_with": ["food in mouth", "sword out of mouth", "cigarette in mouth", "straw in mouth", "whistling", "singing"],
    "implies": []}],
  "extras": []},
 {"id": "obj.camera", "zh": "相机", "mount_sub": "人物主体/日用道具",
  "tags": ["camera"],
  "poses": [
   {"id": "shoot", "zh": "举起拍照", "tags": ["camera up", "taking picture", "holding camera"], "hands": 2, "gaze": 1,
    "state_slot": {}, "conflicts_with": ["closed eyes", "looking down"], "implies": []},
   {"id": "hold", "zh": "持机", "tags": ["holding camera"], "hands": 1, "gaze": 0,
    "state_slot": {}, "conflicts_with": [], "implies": []},
   {"id": "selfie", "zh": "自拍", "tags": ["selfie", "holding phone"], "hands": 1, "gaze": 1,
    "state_slot": {}, "conflicts_with": ["closed eyes", "looking at phone"], "implies": []}],
  "extras": [
   {"id": "neck", "zh": "挂脖相机", "tags": ["camera on neck strap"], "hands": 0, "gaze": 0,
    "state_slot": {}, "conflicts_with": ["taking picture", "holding camera", "camera up"], "implies": []}]},
 {"id": "obj.mic", "zh": "麦克风", "mount_sub": "人物主体/乐器与运动",
  "tags": ["microphone"],
  "poses": [
   {"id": "sing", "zh": "握麦演唱", "tags": ["holding microphone"], "hands": 1, "gaze": 0,
    "state_slot": {},
    "conflicts_with": ["cigarette in mouth", "food in mouth", "sword out of mouth", "biting food", "sucking object", "holding lollipop"],
    "implies": ["singing"]}],
  "extras": []},
 {"id": "obj.flower", "zh": "花", "mount_sub": "人物主体/日用道具",
  "tags": ["rose"],
  "poses": [
   {"id": "hold", "zh": "持花", "tags": ["holding flower"], "hands": 1, "gaze": 0,
    "state_slot": {}, "conflicts_with": [], "implies": []},
   {"id": "bouquet", "zh": "捧花", "tags": ["holding bouquet"], "hands": 2, "gaze": 0,
    "state_slot": {}, "conflicts_with": ["holding cup with both hands", "two-handed sword", "aiming gun", "aiming at viewer", "drawing bow"], "implies": []}],
  "extras": []},
 {"id": "obj.optics", "zh": "望远镜", "mount_sub": "人物主体/日用道具",
  "tags": ["binoculars", "telescope"],
  "poses": [
   {"id": "peer", "zh": "举镜眺望", "tags": ["holding binoculars", "binoculars over eyes"], "hands": 2, "gaze": 1,
    "state_slot": {},
    "conflicts_with": ["looking at viewer", "closed eyes", "wink", "sideways glance", "heterochromia"], "implies": []},
   {"id": "hang", "zh": "挂颈", "tags": ["binoculars"], "hands": 0, "gaze": 0,
    "state_slot": {}, "conflicts_with": ["holding binoculars"], "implies": []}],
  "extras": []},
 {"id": "obj.snack", "zh": "点心", "mount_sub": "人物主体/食物饮品",
  "tags": ["apple", "cookie", "onigiri", "ice cream"],
  "poses": [
   {"id": "hold", "zh": "拿食物", "tags": ["holding food"], "hands": 1, "gaze": 0,
    "state_slot": {}, "conflicts_with": [], "implies": []},
   {"id": "bite", "zh": "咬一口", "tags": ["biting food"], "hands": 1, "gaze": 0,
    "state_slot": {},
    "conflicts_with": ["sword out of mouth", "cigarette in mouth", "straw in mouth", "whistling", "singing", "holding microphone"],
    "implies": ["eating"]}],
  "extras": []},
 {"id": "obj.pen", "zh": "笔", "mount_sub": "人物主体/日用道具",
  "tags": ["pen", "paintbrush"],
  "poses": [
   {"id": "write", "zh": "执笔书写", "tags": ["holding pen"], "hands": 1, "gaze": 1,
    "state_slot": {}, "conflicts_with": ["looking at viewer", "closed eyes"], "implies": ["writing"]}],
  "extras": []},
]

FAM_NEW = {
 "phone_look": ["{S} stare into {POS} phone, the world on mute.",
                "Thumbs hover over the glowing screen.",
                "Nothing exists but the phone and whatever is on it."],
 "phone_call": ["{O} pressed to {POS} ear, a call in progress.",
                "Mid-sentence on the phone, {POS} free hand idles.",
                "Listening to whoever is on the other end, {S} forget to blink."],
 "read": ["{S} read {O}, eyes tracking the lines.",
          "Pages wait under {POS} fingers, spine soft from use.",
          "{O} open in both hands, everything else forgotten."],
 "hold_book": ["{O} held against {POS} chest like a small shield."],
 "umbrella": ["{O} blooms above {POS} shoulder, keeping the rain honest.",
              "{S} hold {O} tilted just enough against the drizzle.",
              "Under {O}, the weather stays somebody else's problem."],
 "guitar_play": ["{S} work the strings like {POS} hands have done it a thousand times.",
                 "A chord hangs half-formed in the air as {POS} fingers settle.",
                 "Strummed lazy and low, the guitar keeping time with {POS} breathing."],
 "guitar_hold": ["The guitar rests at the neck, casual as a walking stick."],
 "cup_hold": ["{O} raised in a small, thoughtful toast to nowhere.",
              "Both hands wrap around {O}, stealing its warmth."],
 "sip": ["{S} take a careful sip, eyes half-closed at the taste.",
         "The cup tips just enough for one more sip."],
 "photo": ["{S} raise {O} to one eye and frame the shot.",
           "A click hangs in the air — the camera still leveled.",
           "Selfie arm extended, catching the angle on the first try."],
 "mic_sing": ["{O} close to {POS} lips, a note caught mid-air.",
              "Singing into the microphone like nobody volunteered to listen."],
 "flower": ["{O} twirled loosely in {POS} fingers.",
            "Held out toward us, the rose offering itself.",
            "Petals brushed against {POS} cheek as {S} admire them."],
 "peer": ["{O} pressed to {POS} eyes, scanning far off.",
          "Watching the distance through the binoculars, unblinking."],
 "bite": ["{S} bite into {O}, cheeks puffing mid-chew.",
          "A first bite, eyes closing in quiet approval."],
 "write": ["{O} scratching lines across whatever {S} can reach.",
           "Head down, the pen moving in small quick strokes."],
}

WORDS_NEW = {
 "phone": ["phone", "the smartphone"],
 "book": ["book", "the open book"],
 "umbrella": ["umbrella", "the paper umbrella"],
 "guitar": ["guitar", "acoustic guitar"],
 "cup": ["cup", "the teacup"],
 "camera": ["camera", "the camera"],
 "mic": ["microphone", "the mic"],
 "flower": ["rose", "flower"],
 "binoculars": ["binoculars", "brass binoculars"],
 "food": ["apple", "cookie", "onigiri"],
 "pen": ["pen", "brush"],
}

SUB_FAM_NEW = {
 "obj.phone": {"hold": "hold_one", "look": "phone_look", "call": "phone_call"},
 "obj.book": {"read": "read", "hold": "hold_book", "closed": "hold_book"},
 "obj.umbrella": {"open": "umbrella", "closed": "hold_one"},
 "obj.guitar": {"play": "guitar_play", "hold": "guitar_hold"},
 "obj.cup": {"hold": "cup_hold", "both": "cup_hold", "sip": "sip"},
 "obj.camera": {"shoot": "photo", "hold": "hold_one", "selfie": "photo", "neck": None},
 "obj.mic": {"sing": "mic_sing"},
 "obj.flower": {"hold": "flower", "bouquet": "flower"},
 "obj.optics": {"peer": "peer", "hang": None},
 "obj.snack": {"hold": "hold_one", "bite": "bite"},
 "obj.pen": {"write": "write"},
}

OBJ_KIND_NEW = {
 "obj.phone": "phone", "obj.book": "book", "obj.umbrella": "umbrella",
 "obj.guitar": "guitar", "obj.cup": "cup", "obj.camera": "camera",
 "obj.mic": "mic", "obj.flower": "flower", "obj.optics": "binoculars",
 "obj.snack": "food", "obj.pen": "pen",
}

# pose_map 兜底 (无 sub_family 表命中时按成员词查)
POSE_MAP_NEW = {
 "holding guitar": "guitar_hold", "holding book": "hold_book", "open book": "read",
 "book closed": "hold_book", "holding phone": "hold_one", "looking at phone": "phone_look",
 "phone to ear": "phone_call", "camera up": "photo", "holding camera": "hold_one",
 "taking picture": "photo", "selfie": "photo", "camera on neck strap": None,
 "holding microphone": "mic_sing", "holding binoculars": "peer",
 "binoculars over eyes": "peer", "biting food": "bite", "holding food": "hold_one",
 "sipping": "sip", "drinking": "sip", "weapon drag": "hold_one",
}


def main():
    p = json.load(open(P_PATH, encoding="utf-8"))
    have = {x["id"] for x in p["profiles"]}
    added = [x for x in OBJ if x["id"] not in have]
    p["profiles"].extend(added)
    json.dump(p, open(P_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"profiles +{len(added)} -> {len(p['profiles'])}")

    n = json.load(open(N_PATH, encoding="utf-8"))
    n.setdefault("families", {}).update({k: v for k, v in FAM_NEW.items() if v})
    n.setdefault("words", {}).update(WORDS_NEW)
    n.setdefault("sub_family", {}).update(SUB_FAM_NEW)
    n.setdefault("obj_kind", {}).update(OBJ_KIND_NEW)
    pm = n.setdefault("pose_map", {})
    for k, v in POSE_MAP_NEW.items():
        if v and k not in pm:
            pm[k] = v
    json.dump(n, open(N_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"nl_flavors: families={len(n['families'])} words={len(n['words'])}")

    import profiles as prof
    data = prof.load_profiles()
    valid, errs = prof.validate_profiles(data)
    print("validate:", len(valid), "errs:", errs[:3])
    import library, runtime_snapshot
    snap = runtime_snapshot.build_snapshot(library.get_merged())
    print("snapshot profiles:", len(snap.profiles), "bundled:", len(snap.bundled_only))


if __name__ == "__main__":
    main()
