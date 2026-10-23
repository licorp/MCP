"""PC1/PC2 (tuong duc san 180) lap khe giua 2 dau PBS1 tren mep san, khi gan khe co nhan PC1/PC2 tren ban ve.
cwd = extension root. out: cache/pc1_gaps.json"""
import json, math, os, sys
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts"); sys.path.insert(0, ".agents/skills/cad-clean-import/scripts")
import pymupdf as fitz
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring, unary_union
import slab_edge_smoother as sm
from pdf_struct_parser import AffineTransformer
from workdir import work_path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finishing_config as FC  # noqa: E402
D = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
SH = {k: (v["page"], FC.cal(k), v["level"]) for k, v in FC.SHEETS.items() if "LEVEL 01" not in v["level"]}
SL = json.load(open(os.path.join(D, "slabs_export_arcs.json")))
WP = json.load(open(os.path.join(D, "walls_pts.json")))
TH = 180.0
doc = fitz.open(FC.PDF)


def fit(pts):
    """polyline -> danh sach line/arc (3 diem), sai so < 8 mm."""
    if len(pts) < 3 or LineString(pts).length < 1:
        return [{"kind": "line", "start": list(pts[0]), "end": list(pts[-1])}]
    a, b = pts[0], pts[-1]
    ln = LineString([a, b])
    if max(ln.distance(Point(p)) for p in pts) < 8:
        return [{"kind": "line", "start": list(a), "end": list(b)}]
    m = pts[len(pts) // 2]
    (ax, ay), (bx, by), (cx, cy) = a, m, b
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) > 1e-6:
        ux = ((ax*ax+ay*ay)*(by-cy) + (bx*bx+by*by)*(cy-ay) + (cx*cx+cy*cy)*(ay-by)) / d
        uy = ((ax*ax+ay*ay)*(cx-bx) + (bx*bx+by*by)*(ax-cx) + (cx*cx+cy*cy)*(bx-ax)) / d
        r = math.hypot(ax - ux, ay - uy)
        if max(abs(math.hypot(p[0] - ux, p[1] - uy) - r) for p in pts) < 8 and r < 30000:
            return [{"kind": "arc", "start": list(a), "mid": list(m), "end": list(b)}]
    k = len(pts) // 2
    return fit(pts[:k + 1]) + fit(pts[k:])


out = []
for sh, (pno, cal, lvl) in SH.items():
    page = doc[pno - 1]
    T = AffineTransformer(*cal)
    labels = []
    for w in page.get_text("words"):
        if w[4].startswith("PC1") or w[4].startswith("PC2"):
            r = T.to_revit_mm((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            labels.append(Point(r["x"], r["y"]))
    slabs = [s for s in SL if s["level"] == lvl]
    U = unary_union([Polygon(sm.ring_points(max(s["loops"], key=len), 5)).buffer(3) for s in slabs]).buffer(-3)
    pbs = [w for w in WP if w["level"] == lvl and "PBS1" in w["type"]]
    other = unary_union([LineString(w["pts"]).buffer(160) for w in WP if (w["level"] == lvl or abs(w["zmax"] - max([0] + [x["zmin"] for x in pbs])) < 400) and "PBS1" not in w["type"]] or [Point(0, 0).buffer(1)])
    covered = unary_union([LineString(w["pts"]).buffer(120) for w in pbs])
    for g in getattr(U, "geoms", [U]):
        ring = LineString(g.exterior.coords)
        Lr = ring.length
        ends = []
        for w in pbs:
            for e in (w["pts"][0], w["pts"][-1]):
                p = Point(e)
                if ring.distance(p) < 150:
                    ends.append(ring.project(p))
        ends = sorted(set(round(x) for x in ends))
        for i in range(len(ends)):
            s0, s1 = ends[i], ends[(i + 1) % len(ends)]
            if s1 <= s0:
                s1 += Lr
            gap_len = s1 - s0
            if gap_len < 150 or gap_len > 9000:
                continue
            sub = substring(ring, s0, s1) if s1 <= Lr else LineString(list(substring(ring, s0, Lr).coords) + list(substring(ring, 0, s1 - Lr).coords)[1:])
            if sub.length < 150 or sub.intersection(covered).length > 0.5 * sub.length:
                continue
            mid = sub.interpolate(0.5, normalized=True)
            if not any(l.distance(sub) < 1500 for l in labels):
                continue
            off = None
            for side in ("left", "right"):
                o = sub.parallel_offset(TH / 2, side, join_style=1)
                if not o.is_empty and g.contains(o.interpolate(0.5, normalized=True)):
                    off = o if o.geom_type == "LineString" else max(o.geoms, key=lambda z: z.length)
                    break
            if off is None or off.intersection(other).length > 0.5 * off.length:
                continue
            pts = list(off.simplify(2).coords)
            # parallel_offset 'right' dao chieu -> giu thu tu bat ky; Revit khong can chieu
            host = max(slabs, key=lambda s: Polygon(sm.ring_points(max(s["loops"], key=len), 20)).buffer(0).buffer(150).intersection(off).length)
            for seg in fit(pts):
                seg.update({"sheet": sh, "level": lvl, "slab_offset": host["offset_mm"], "cls": 180,
                            "len": round(math.dist(seg["start"], seg["end"]) if seg["kind"] == "line" else LineString([seg["start"], seg["mid"], seg["end"]]).length)})
                out.append(seg)
    print(sh, lvl, "PC1 doan", len([s for s in out if s["sheet"] == sh]), "%.1f m" % (sum(s["len"] for s in out if s["sheet"] == sh) / 1000))
json.dump(out, open(work_path("pc1_gaps.json"), "w"))
