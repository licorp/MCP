"""Gop san lien ke cung (tang, loai, cao do) thanh 1 tam + nan net gan truc (< 0.6 do) ve dung truc.
out: %LOCALAPPDATA%/RevitMCPPython/merge_snap_plan.json  (moi muc: ids cu, outer/holes moi dang items line/arc)"""
import json, math, os, sys, collections
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts")
from shapely.geometry import Polygon
from shapely.ops import unary_union
import slab_edge_smoother as sm

D = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
S = json.load(open(os.path.join(D, "slabs_export_fill.json")))
ONLY = set(json.load(open(os.path.join(D, "offaxis_ids.json")))) if len(sys.argv) > 1 and sys.argv[1] == "offaxis" else None
if ONLY is not None:
    S = [s for s in S if s["id"] in ONLY]
SNAP_DEG = 0.6


def poly(s):
    rings = sorted([Polygon(sm.ring_points(l, 2)).buffer(0) for l in s["loops"]], key=lambda g: -g.area)
    return Polygon(rings[0].exterior.coords, [r.exterior.coords for r in rings[1:] if rings[0].contains(r.representative_point())]).buffer(0)


def snap(items):
    """nhom dinh noi bang canh gan ngang -> chung Y; gan dung -> chung X (union-find), lap den on dinh."""
    n = len(items)
    for _ in range(4):
        for axis, test in (("y", lambda dx, dy: abs(dy) < abs(dx)), ("x", lambda dx, dy: abs(dx) <= abs(dy))):
            parent = list(range(n))
            def f(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]; i = parent[i]
                return i
            for k in range(n):
                a, b = items[k], items[(k + 1) % n]
                if "mid" in a: continue
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                if math.hypot(dx, dy) < 1: continue
                ang = abs(math.degrees(math.atan2(dy, dx))) % 90
                if min(ang, 90 - ang) < SNAP_DEG and test(dx, dy):
                    parent[f(k)] = f((k + 1) % n)
            grp = collections.defaultdict(list)
            for k in range(n): grp[f(k)].append(k)
            for g in grp.values():
                if len(g) > 1:
                    v = round(sum(items[k][axis] for k in g) / len(g), 1)
                    for k in g: items[k][axis] = v
    return _clean(items)


def _clean(items):
    out = []
    for it in items:
        if out and math.hypot(it["x"] - out[-1]["x"], it["y"] - out[-1]["y"]) < 6:
            continue
        out.append(it)
    if len(out) > 1 and math.hypot(out[0]["x"] - out[-1]["x"], out[0]["y"] - out[-1]["y"]) < 6:
        out.pop()
    return out


def snap_old(items):
    """nan canh thang gan truc: lap toi da 3 vong, dat toa do chung = trung binh."""
    n = len(items)
    for _ in range(3):
        for k in range(n):
            a, b = items[k], items[(k + 1) % n]
            if "mid" in a:
                continue
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            L = math.hypot(dx, dy)
            if L < 1:
                continue
            ang = abs(math.degrees(math.atan2(dy, dx))) % 90
            dev = min(ang, 90 - ang)
            if 0 < dev < SNAP_DEG:
                if abs(dx) > abs(dy):
                    y = (a["y"] + b["y"]) / 2; a["y"] = b["y"] = round(y, 2)
                else:
                    x = (a["x"] + b["x"]) / 2; a["x"] = b["x"] = round(x, 2)
    # bo canh qua ngan sau khi nan
    out = []
    for it in items:
        if out and math.hypot(it["x"] - out[-1]["x"], it["y"] - out[-1]["y"]) < 6:
            continue
        out.append(it)
    if len(out) > 1 and math.hypot(out[0]["x"] - out[-1]["x"], out[0]["y"] - out[-1]["y"]) < 6:
        out.pop()
    return out


groups = collections.defaultdict(list)
for s in S:
    if "GROUND" in s["level"]:
        continue
    groups[(s["level_id"], s["type_id"], round(s["offset_mm"]))].append(s)
plan, n_merge, n_old = [], 0, 0
for key, ss in groups.items():
    P = [(s, poly(s)) for s in ss]
    # cum lien ke (cham nhau trong 15 mm)
    left = list(range(len(P))); clusters = []
    while left:
        c = [left.pop(0)]; grow = True
        while grow:
            grow = False
            for j in list(left):
                if any(P[i][1].buffer(15).intersects(P[j][1]) for i in c):
                    c.append(j); left.remove(j); grow = True
        clusters.append(c)
    for c in clusters:
        ss_c = [P[i][0] for i in c]
        if len(c) == 1:
            u = P[c[0]][1]
        else:
            u = unary_union([P[i][1].buffer(4, join_style=2) for i in c]).buffer(-4, join_style=2).buffer(0)
            n_merge += 1
        parts = [u] if u.geom_type == "Polygon" else sorted(u.geoms, key=lambda g: -g.area)
        for k, part in enumerate(parts):
            if part.area < 1e5:
                continue
            outer = snap(sm.ring_with_arcs(list(part.simplify(1.5).exterior.coords)))
            holes = [snap(sm.ring_with_arcs(list(r.coords))) for r in part.interiors if Polygon(r).area > 1e5]
            base = max(ss_c, key=lambda s: poly(s).area)
            plan.append({"old": [s["id"] for s in ss_c] if k == 0 else [], "comments": base["comments"].replace("FILL|", "PDF2BIM|merged|") if base["comments"].startswith("FILL|") else base["comments"],
                         "type_id": base["type_id"], "level_id": base["level_id"], "offset_mm": base["offset_mm"], "structural": base["structural"],
                         "outer": outer, "holes": holes})
        n_old += len(ss_c)
json.dump(plan, open(os.path.join(D, "merge_snap_plan.json"), "w"))
print("san cu", n_old, "-> san moi", len(plan), "| cum gop", n_merge)
