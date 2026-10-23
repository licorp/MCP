"""Merge FILL| floors into the touching PDF2BIM slab (same type + offset) -> rebuild plan (true arcs) + filler ids to delete."""
import json, os, sys, collections
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts"); sys.path.insert(0, ".agents/skills/cad-clean-import/scripts")
from shapely.geometry import Polygon
from shapely.ops import unary_union
import slab_edge_smoother as sm
D = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
S = json.load(open(os.path.join(D, "slabs_export_fill.json")))
def poly(s):
    rings = sorted([Polygon(sm.ring_points(l, 2)).buffer(0) for l in s["loops"]], key=lambda g: -g.area)
    return Polygon(rings[0].exterior.coords, [r.exterior.coords for r in rings[1:] if rings[0].contains(r.representative_point())]).buffer(0)
F = [s for s in S if s["comments"].startswith("FILL|")]
P = {s["id"]: s for s in S if s["comments"].startswith("PDF2BIM|")}
PG = {i: poly(s) for i, s in P.items()}
host = collections.defaultdict(list); orphan = []
for f in F:
    g = poly(f)
    cand = [i for i, s in P.items() if s["level_id"] == f["level_id"] and s["offset_mm"] == f["offset_mm"] and s["type_id"] == f["type_id"]
            and PG[i].buffer(20).intersects(g)]
    if not cand: orphan.append(f["id"]); continue
    i = max(cand, key=lambda i: PG[i].buffer(20).intersection(g).area)
    host[i].append((f["id"], g))
plan, fills = [], []
for i, lst in host.items():
    s = P[i]
    u = unary_union([PG[i]] + [g.buffer(3, join_style=2) for _, g in lst]).buffer(-3, join_style=2).buffer(0)
    if u.geom_type != "Polygon":
        parts = sorted(u.geoms, key=lambda g: -g.area); u = parts[0]
        keep = [fid for fid, g in lst if u.buffer(5).contains(g.representative_point())]
    else:
        keep = [fid for fid, _ in lst]
    u = u.simplify(2, preserve_topology=True)
    def clean(items):
        out = []
        for it in items:
            if out and ((it["x"] - out[-1]["x"]) ** 2 + (it["y"] - out[-1]["y"]) ** 2) ** 0.5 < 6: continue
            out.append(it)
        if len(out) > 1 and ((out[0]["x"] - out[-1]["x"]) ** 2 + (out[0]["y"] - out[-1]["y"]) ** 2) ** 0.5 < 6: out.pop()
        return out
    outer = clean(sm.ring_with_arcs(list(u.exterior.coords)))
    holes = [clean(sm.ring_with_arcs(list(r.coords))) for r in u.interiors if Polygon(r).area > 1e5]
    plan.append({**{k: s[k] for k in ("id", "comments", "type_id", "level_id", "offset_mm", "structural")}, "outer": outer, "holes": holes, "fills": keep})
    fills += keep
json.dump(plan, open(os.path.join(D, "merge_plan.json"), "w"))
print("fillers", len(F), "merged into", len(plan), "slabs; fillers merged", len(fills), "orphans (kept)", len(orphan))
