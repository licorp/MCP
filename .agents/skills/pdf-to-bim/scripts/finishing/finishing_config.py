"""Cau hinh du an cho bo script hoan thien (finishing): duong dan PDF + cac to ban ve (trang, 2 diem hieu chuan, level, khung cat anh).

Tim file theo thu tu: bien moi truong FINISH_CONFIG -> .agents/projects/<FINISH_PROJECT>/finishing_config.json
(FINISH_PROJECT mac dinh = 250793). Mau JSON:
{
  "pdf": "C:/.../Combined set_1.pdf",
  "sheets": {"S210": {"page": 28, "cal": [[x,y],[x,y],[X,Y],[X,Y]], "level": "BUILDING A-LEVEL 02", "clip": [x0,y0,x1,y1]}},
  "mirror_x": {"A": 76958.5}          # tuy chon: truc doi xung de sinh lan can ban cong doi xung (rail_template)
}
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_HERE, *[".."] * 5))
PATH = os.environ.get("FINISH_CONFIG") or os.path.join(ROOT, ".agents", "projects", os.environ.get("FINISH_PROJECT", "250793"),
                                                       "finishing_config.json")
CFG = json.load(open(PATH, encoding="utf-8"))
PDF = CFG["pdf"]
SHEETS = CFG["sheets"]
MIRROR_X = CFG.get("mirror_x", {})


def cal(sheet):
    return tuple(tuple(p) for p in SHEETS[sheet]["cal"])


def sheet_for_level(level):
    return next((k for k, v in SHEETS.items() if v["level"] == level), None)
