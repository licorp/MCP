"""Remaining small holes/slits in slab coverage (all floors incl. fillers): fill at the LOWER neighbour's offset."""
import json, os, sys, collections
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts"); sys.path.insert(0, ".agents/skills/cad-clean-import/scripts")
from shapely.geometry import Polygon
from shapely.ops import unary_union
import slab_edge_smoother as sm
from workdir import work_path
S = json.load(open(os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "slabs_export_fill.json")))
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
    gaps = U.buffer(300, join_style=2).buffer(-300, join_style=2).difference(U.buffer(0.5))
    for g in [x for gg in getattr(gaps, "geoms", [gaps]) for x in getattr(gg.buffer(-1).buffer(1), "geoms", [gg.buffer(-1).buffer(1)]) if not x.is_empty]:
        if g.area < 1000 or g.area > 2e6: continue
        if g.boundary.intersection(U.buffer(3)).length / g.length < 0.75: continue
        nbs = [(s, q) for s, q in items if q.buffer(5).intersects(g)]
        if not nbs: continue
        lo = min(nbs, key=lambda x: (x[0]["offset_mm"], -x[1].buffer(5).intersection(g).area))
        out.append({"level": lvl, "level_id": lo[0]["level_id"], "type_id": lo[0]["type_id"], "offset_mm": lo[0]["offset_mm"],
                    "area_mm2": round(g.area), "at": [round(g.centroid.x), round(g.centroid.y)],
                    "outer": [[round(x, 1), round(y, 1)] for x, y in list(g.simplify(1).exterior.coords)[:-1]]})
json.dump(out, open(work_path("slab_gaps2.json"), "w"))
print(len(out), "holes", collections.Counter(o["level"][-12:] for o in out), "m2", round(sum(o["area_mm2"] for o in out) / 1e6, 2))
for o in sorted(out, key=lambda o: -o["area_mm2"])[:10]: print(" ", o["level"][-12:], o["area_mm2"], o["at"], o["offset_mm"])
