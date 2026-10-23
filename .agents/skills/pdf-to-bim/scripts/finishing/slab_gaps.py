"""Gaps/notches in slab coverage that walls or columns pass through -> filler slab payloads (neighbour type/offset)."""
import json, os, sys, collections
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts"); sys.path.insert(0, ".agents/skills/cad-clean-import/scripts")
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union
import slab_edge_smoother as sm
from workdir import work_path
D = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
S = json.load(open(os.path.join(D, "slabs_export_arcs.json"))); WP = json.load(open(os.path.join(D, "walls_pts.json")))
cols = json.load(open(os.path.join(D, "cols.json")))
def poly(s):
    rings = sorted([Polygon(sm.ring_points(l, 5)).buffer(0) for l in s["loops"]], key=lambda g: -g.area)
    g = rings[0]
    for h in rings[1:]: g = g.difference(h)
    return g
by = collections.defaultdict(list)
for s in S:
    if "GROUND" not in s["level"]: by[s["level"]].append((s, poly(s)))
out = []
for lvl, items in by.items():
    U = unary_union([g for _, g in items])
    closed = U.buffer(450, join_style=2).buffer(-450, join_style=2)   # closes notches / gaps narrower than 900
    gaps = closed.difference(U.buffer(1))
    holes_real = [Polygon(r) for g in getattr(U, "geoms", [U]) for r in g.interiors if Polygon(r).area > 3e6]
    pieces = []
    for g in getattr(gaps, "geoms", [gaps]):
        g = g.buffer(-3).buffer(3)
        pieces += [x for x in getattr(g, "geoms", [g]) if not x.is_empty]
    for g in pieces:
        if g.area < float(os.environ.get("GAP_MIN", "2e4")): continue
        if any(h.contains(g.representative_point()) for h in holes_real): continue          # lift/stair openings stay open
        # only gaps something structural passes through (wall top / column below this level or wall above)
        shared = g.boundary.intersection(U.buffer(3)).length / g.length
        if shared < 0.7: continue                                              # open notch at the slab edge: leave
        hit = [w["id"] for w in WP if LineString(w["pts"]).buffer(100).intersects(g.buffer(-2))]
        if not hit: continue
        nb = max(items, key=lambda it: it[1].buffer(5).intersection(g.buffer(5)).area)
        out.append({"level": lvl, "area_m2": round(g.area / 1e6, 3), "shared": round(shared, 2), "at": [round(g.centroid.x), round(g.centroid.y)], "walls": hit[:4],
                    "type": nb[0]["type"], "type_id": nb[0]["type_id"], "level_id": nb[0]["level_id"], "offset_mm": nb[0]["offset_mm"],
                    "outer": [[round(x, 1), round(y, 1)] for x, y in list(g.simplify(2).exterior.coords)[:-1]]})
json.dump(out, open(work_path("slab_gaps.json"), "w"))
c = collections.Counter(o["level"] for o in out)
print(len(out), "gaps", dict(c), "total m2", round(sum(o["area_m2"] for o in out), 2))
for o in sorted(out, key=lambda o: -o["area_m2"])[:15]: print(" ", o["level"][-12:], o["area_m2"], o["at"], o["type"][-6:], o["offset_mm"], o["walls"])
