"""Mau lan can chung moi nha = gop PBS1/PC1 cua L2+L3 (+ doi xung ban cong Dong Bac sang Tay Bac nha A);
ap cho L1/L2/L3 o nhung doan nam tren mep ngoai san tang do. out: cache/rail_plan.json (+ anh rail_plan.png)"""
import json, math, os, sys
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts")
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Polygon, box
from shapely.affinity import scale
from shapely.ops import unary_union
import slab_edge_smoother as sm

D = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
SL = json.load(open(os.path.join(D, "slabs_export_arcs.json")))
RA = json.load(open(os.path.join(D, "rails_export.json")))
LV = ("LEVEL 01", "LEVEL 02", "LEVEL 03")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finishing_config as FC  # noqa: E402
MIRROR = FC.MIRROR_X   # {"A": x}: doi xung ban cong phia +x sang -x (bo trong neu khong can)


def geom(r, n=24):
    if r["kind"] == "line":
        return LineString([r["start"], r["end"]])
    (ax, ay), (bx, by), (cx, cy) = r["start"], r["mid"], r["end"]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax*ax+ay*ay)*(by-cy) + (bx*bx+by*by)*(cy-ay) + (cx*cx+cy*cy)*(ay-by)) / d
    uy = ((ax*ax+ay*ay)*(cx-bx) + (bx*bx+by*by)*(ax-cx) + (cx*cx+cy*cy)*(bx-ax)) / d
    rr = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux); am = math.atan2(by - uy, bx - ux); a1 = math.atan2(cy - uy, cx - ux)
    f = lambda x: (x - a0) % (2 * math.pi)
    sw = f(a1) if f(am) < f(a1) else f(a1) - 2 * math.pi
    return LineString([(ux + rr * math.cos(a0 + sw * i / n), uy + rr * math.sin(a0 + sw * i / n)) for i in range(n + 1)])


def kind_of(t):
    return "PC1" if "PC1" in t else ("US1" if "US1" in t else "PBS1")


plan, tiles = [], []
font = ImageFont.truetype("arial.ttf", 24)
for b in ("A", "B"):
    src = [r for r in RA if r["level"] in ("BUILDING %s-LEVEL 02" % b, "BUILDING %s-LEVEL 03" % b) and kind_of(r["type"]) != "US1"]
    if b in MIRROR:   # vd nha A: ban cong Tay Bac = doi xung ban cong Dong Bac qua truc x = MIRROR[b]
        MIRROR_X = MIRROR[b]
        ne = [r for r in src if min(p[0] for p in geom(r).coords) > 84200 and min(p[1] for p in geom(r).coords) > 269900]
        for r in ne:
            m = {k: ([2 * MIRROR_X - r[k][0], r[k][1]] if k in ("start", "mid", "end") and k in r else r[k]) for k in r}
            m["id"] = None
            src.append(m)
    # khu trung L2/L3: giu 1 ban cho moi hinh hoc
    tmpl = []
    for r in src:
        g = geom(r)
        if not any(g.hausdorff_distance(t[1]) < 80 and kind_of(r["type"]) == kind_of(t[0]["type"]) for t in tmpl):
            tmpl.append((r, g))
    for lv in LV:
        lvl = "BUILDING %s-%s" % (b, lv)
        slabs = [s for s in SL if s["level"] == lvl]
        if not slabs:
            continue
        polys = [(s, Polygon(sm.ring_points(max(s["loops"], key=len), 5)).buffer(0)) for s in slabs]
        U = unary_union([p.buffer(3) for _, p in polys]).buffer(-3)
        outer = unary_union([LineString(g.exterior.coords) for g in getattr(U, "geoms", [U])])
        us1 = unary_union([geom(r).buffer(150) for r in RA if r["level"] == lvl and kind_of(r["type"]) == "US1"] or [box(0, 0, 1, 1)])
        keep = []
        for r, g in tmpl:
            k = kind_of(r["type"]); half = 75 if k == "PBS1" else 90
            on_edge = g.intersection(outer.buffer(half + 60)).length / g.length
            if on_edge < 0.8 or g.intersection(us1).length > 0.5 * g.length:
                continue
            host = max(polys, key=lambda sp: sp[1].buffer(200).intersection(g).length)[0]
            it = {k2: r[k2] for k2 in ("kind", "start", "end") + (("mid",) if r["kind"] == "arc" else ())}
            it.update({"level": lvl, "rail": k, "slab_offset": host["offset_mm"], "len": round(g.length)})
            keep.append(it)
        plan += keep
        # anh
        xs = [c[0] for _, p in polys for c in p.exterior.coords]; ys = [c[1] for _, p in polys for c in p.exterior.coords]
        x0, x1, y0, y1 = min(xs) - 1000, max(xs) + 1000, min(ys) - 1000, max(ys) + 1000
        k_ = 900 / max(x1 - x0, y1 - y0); W, H = int((x1 - x0) * k_), int((y1 - y0) * k_)
        im = Image.new("RGB", (W, H + 36), "white"); d = ImageDraw.Draw(im)
        T = lambda q: ((q[0] - x0) * k_, 36 + (y1 - q[1]) * k_)
        for _, p in polys:
            d.line([T(c) for c in p.exterior.coords], fill=(190, 190, 190), width=1)
        for r in RA:
            if r["level"] == lvl and kind_of(r["type"]) == "US1":
                d.line([T(c) for c in geom(r).coords], fill=(0, 140, 0), width=4)
        for it in keep:
            d.line([T(c) for c in geom(it).coords], fill=(220, 0, 0) if it["rail"] == "PBS1" else (255, 140, 0), width=4)
        d.text((6, 4), "%s %s: PBS1 %.1f m, PC1 %.1f m" % (b, lv, sum(i["len"] for i in keep if i["rail"] == "PBS1") / 1000,
                                                    sum(i["len"] for i in keep if i["rail"] == "PC1") / 1000), fill=(0, 0, 0), font=font)
        tiles.append(im)
        print(lvl, "doan", len(keep))
json.dump(plan, open(".agents/cache/rail_plan.json", "w"))
cw = max(t.width for t in tiles); ch = max(t.height for t in tiles)
cv = Image.new("RGB", (cw * 3, ch * 2), "white")
for i, t in enumerate(tiles):
    cv.paste(t, ((i % 3) * cw, (i // 3) * ch))
cv.save(".agents/cache/rail_plan.png"); print(cv.size)
