"""Lan can / tuong mep san: lay mau mep san moi 50 mm, phan loai 150 (PBS1) / 180 (PC1) theo 2 net song song tren ban ve,
gom thanh cac doan lien tuc (giu cung tron), noi goc. cwd = extension root. out: cache/edge_runs.json + edge_runs_<sheet>.png"""
import json, math, os, sys
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts"); sys.path.insert(0, ".agents/skills/cad-clean-import/scripts")
import pymupdf as fitz
from PIL import Image
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
import slab_edge_smoother as sm
from pdf_struct_parser import AffineTransformer
from workdir import work_path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finishing_config as FC  # noqa: E402
D = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
SH = {k: (v["page"], FC.cal(k), v["level"]) for k, v in FC.SHEETS.items()}
SL = json.load(open(os.path.join(D, "slabs_export_arcs.json")))
WP = json.load(open(os.path.join(D, "walls_pts.json")))
CLS = (150.0, 180.0)
TOL = 20.0
STEP = 50.0
doc = fitz.open(FC.PDF)


def arc_cmr(a, m, b):
    (ax, ay), (bx, by), (cx, cy) = a, m, b
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def item(a, b, mid):
    if mid is None:
        L = math.dist(a, b)
        return {"kind": "line", "len": L, "at": lambda t: (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)}
    (cx, cy), r = arc_cmr(a, mid, b)
    a0 = math.atan2(a[1] - cy, a[0] - cx)
    am = math.atan2(mid[1] - cy, mid[0] - cx)
    a1 = math.atan2(b[1] - cy, b[0] - cx)
    n = lambda x: (x - a0) % (2 * math.pi)
    sw = n(a1) if n(am) < n(a1) else n(a1) - 2 * math.pi
    return {"kind": "arc", "c": (cx, cy), "r": r, "a0": a0, "sw": sw, "len": abs(sw) * r,
            "at": lambda t: (cx + r * math.cos(a0 + sw * t), cy + r * math.sin(a0 + sw * t))}


def inter(s1, s2):
    (x1, y1), (x2, y2) = s1["start"], s1["end"]
    (x3, y3), (x4, y4) = s2["start"], s2["end"]
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-6:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
    return [x1 + t * (x2 - x1), y1 + t * (y2 - y1)]


results = []
for sh in (sys.argv[1:] or list(SH)):
    pno, cal, lvl = SH[sh]
    page = doc[pno - 1]
    T = AffineTransformer(*cal)
    segs = []
    for d in page.get_drawings():
        col = tuple(round(v, 2) for v in (d.get("color") or (9, 9, 9)))
        grey06 = col[0] == col[1] == col[2] and 0.6 <= col[0] <= 0.7 and abs((d.get("width") or 0) - 0.6) < 0.01
        if col != (0.0, 0.0, 0.0) and not grey06:
            continue
        for it in d["items"]:
            pts = [it[1], it[2]] if it[0] == "l" else ([it[1], it[4]] if it[0] == "c" else [])
            if len(pts) == 2:
                a = T.to_revit_mm(pts[0].x, pts[0].y)
                b = T.to_revit_mm(pts[1].x, pts[1].y)
                if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) > 3:
                    segs.append(LineString([(a["x"], a["y"]), (b["x"], b["y"])]))
    tree = STRtree(segs)

    def near(p, tol=TOL):
        return any(segs[i].distance(p) < tol for i in tree.query(p.buffer(tol)))

    slabs = [s for s in SL if s["level"] == lvl]
    polys = [Polygon(sm.ring_points(max(s["loops"], key=lambda l: Polygon(sm.ring_points(l, 20)).area), 5)).buffer(0) for s in slabs]
    U = unary_union([p.buffer(3) for p in polys]).buffer(-3)
    edge = U.boundary
    Ub = U.buffer(1)
    keep_walls = [LineString(w["pts"]) for w in WP if w["level"] == lvl and "PBS1" not in w["type"] and "Precast" not in w["type"]]
    WALL = unary_union([w.buffer(100) for w in keep_walls]) if keep_walls else None
    pieces = []
    for s in slabs:
        for loop in s["loops"]:
            n = len(loop)
            for k in range(n):
                a = (loop[k]["x"], loop[k]["y"])
                b = (loop[(k + 1) % n]["x"], loop[(k + 1) % n]["y"])
                mid = (loop[k]["mid"]["x"], loop[k]["mid"]["y"]) if "mid" in loop[k] else None
                g = item(a, b, mid)
                if g["len"] < 5 or edge.distance(Point(*g["at"](0.5))) > 5:
                    continue
                ns = max(2, int(g["len"] // STEP))
                lab = []
                for i in range(ns):
                    t = (i + 0.5) / ns
                    p = g["at"](t)
                    q = g["at"](min(1, t + 0.002))
                    r0 = g["at"](max(0, t - 0.002))
                    dx, dy = q[0] - r0[0], q[1] - r0[1]
                    L = math.hypot(dx, dy) or 1
                    nx, ny = -dy / L, dx / L
                    if not Ub.contains(Point(p[0] + nx * 30, p[1] + ny * 30)):
                        nx, ny = -nx, -ny
                    c = None
                    if near(Point(*p)):
                        for th in CLS:
                            if near(Point(p[0] + nx * th, p[1] + ny * th)) and not near(Point(p[0] + nx * th / 2, p[1] + ny * th / 2), 25):
                                c = th
                                break
                    if c and WALL is not None and WALL.contains(Point(p[0] + nx * c / 2, p[1] + ny * c / 2)):
                        c = None
                    lab.append((t, c, (nx, ny)))
                labs = [x[1] for x in lab]
                i = 0
                while i < len(labs):          # lam muot: khoang ngan < 350 mm giua 2 khoang cung nhan
                    j = i
                    while j < len(labs) and labs[j] == labs[i]:
                        j += 1
                    if (j - i) * g["len"] / ns < 350 and i > 0 and j < len(labs) and labs[i - 1] == labs[j]:
                        for k2 in range(i, j):
                            labs[k2] = labs[i - 1]
                    i = j
                i = 0
                while i < len(labs):
                    j = i
                    while j < len(labs) and labs[j] == labs[i]:
                        j += 1
                    if labs[i]:
                        pieces.append({"slab": s, "cls": labs[i], "g": g, "t0": i / ns, "t1": j / ns, "n": lab[(i + j) // 2][2]})
                    i = j
    out = []
    for p in pieces:
        g, h = p["g"], p["cls"] / 2
        if (p["t1"] - p["t0"]) * g["len"] < 120:
            continue
        if g["kind"] == "line":
            a = g["at"](p["t0"])
            b = g["at"](p["t1"])
            nx, ny = p["n"]
            seg = {"kind": "line", "start": [a[0] + nx * h, a[1] + ny * h], "end": [b[0] + nx * h, b[1] + ny * h]}
        else:
            cx, cy = g["c"]
            pm = g["at"]((p["t0"] + p["t1"]) / 2)
            inward_to_c = (pm[0] - cx) * p["n"][0] + (pm[1] - cy) * p["n"][1] < 0
            r2 = g["r"] - h if inward_to_c else g["r"] + h
            P = lambda t, g=g, r2=r2, cx=cx, cy=cy: [cx + r2 * math.cos(g["a0"] + g["sw"] * t), cy + r2 * math.sin(g["a0"] + g["sw"] * t)]
            seg = {"kind": "arc", "start": P(p["t0"]), "mid": P((p["t0"] + p["t1"]) / 2), "end": P(p["t1"])}
        seg.update({"sheet": sh, "level": lvl, "cls": p["cls"], "slab_offset": p["slab"]["offset_mm"], "slab_id": p["slab"]["id"]})
        out.append(seg)
    # noi goc: 2 doan thang co dau mut gan nhau -> giao diem; doan cong: dua dau mut ve trung nhau
    for i, s1 in enumerate(out):
        for j, s2 in enumerate(out):
            if j <= i or s1["cls"] != s2["cls"]:
                continue
            for e1 in ("start", "end"):
                for e2 in ("start", "end"):
                    dd = math.dist(s1[e1], s2[e2])
                    if 0.5 < dd < 260:
                        if s1["kind"] == "line" and s2["kind"] == "line":
                            x = inter(s1, s2)
                            if x and math.dist(x, s1[e1]) < 400:
                                s1[e1] = list(x)
                                s2[e2] = list(x)
                        elif dd < 60:
                            if s1["kind"] == "arc":
                                s2[e2] = list(s1[e1])
                            else:
                                s1[e1] = list(s2[e2])
    for s in out:
        s["len"] = round(math.dist(s["start"], s["end"]) if s["kind"] == "line" else LineString([s["start"], s["mid"], s["end"]]).length)
    out = [s for s in out if s["len"] >= 100]
    results += out
    n150 = sum(s["len"] for s in out if s["cls"] == 150) / 1000
    n180 = sum(s["len"] for s in out if s["cls"] == 180) / 1000
    print(sh, lvl, "doan", len(out), "PBS1 %.1f m" % n150, "PC1 %.1f m" % n180)
    for col, cl in (((1, 0, 0), 150), ((0, 0.3, 1), 180)):
        shp = page.new_shape()
        for s in [x for x in out if x["cls"] == cl]:
            if s["kind"] == "arc":
                it2 = item(tuple(s["start"]), tuple(s["end"]), tuple(s["mid"]))
                pts = [it2["at"](k / 24) for k in range(25)]
            else:
                pts = [s["start"], s["end"]]
            q = [T.to_pdf_pt(x, y) for x, y in pts]
            shp.draw_polyline([fitz.Point(v["x"], v["y"]) for v in q])
        shp.finish(color=col, width=2.6, closePath=False)
        shp.commit()
    pix = page.get_pixmap(dpi=55)
    Image.frombytes("RGB", (pix.width, pix.height), pix.samples).save(work_path("edge_runs_%s.png" % sh))
json.dump(results, open(work_path("edge_runs.json"), "w"))
