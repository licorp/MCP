# -*- coding: utf-8 -*-
"""
suspended_slab_extractor.py - Sàn tầng (sàn PT) từ marking plan PDF: chia vùng chiều dày, dải dày 1200 (370),
sàn hạ cốt ngoài đường bậc (ban công / podium "250 MIN", "70mm STEP + 50 FALLS").

Kiểm chứng 250793 L1 (S207/S208):
  - Vòng tròn có số = chiều dày sàn tổng U.N.O (legend). "MIN" cạnh vòng tròn = sàn ngoài đường bậc (hạ cốt).
  - Sàn chính = vùng kín (nét đen 0.6) chứa vòng tròn không MIN; vùng chứa "MIN" = sàn hạ cốt (z_offset).
  - Đường nét đứt (gạch rời 60-700 mm) chia sàn chính; dải rộng ~1200 có kích thước '1200' gần đó
    hoặc thẳng hàng với dải đã có vòng tròn -> dải dày (band_thickness, vd 370). Ô không có vòng tròn
    và không phải dải -> báo 'unresolved', KHÔNG đoán.
  - Các vùng nối khít (ưu tiên dải > ô sàn chính > sàn hạ cốt), không chồng bê tông; lỗ mở = dấu X.
Toạ độ: mm Revit (to_revit từ sog_slab_extractor.similarity_from_pts).
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union

import sog_slab_extractor as sx

Pt = Tuple[float, float]


def _parts(g) -> List[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [x for x in getattr(g, "geoms", []) if isinstance(x, Polygon)]


def bubbles(page, to_revit, area_pt=None, d_min_pt: float = 8.0, d_max_pt: float = 32.0) -> List[Dict]:
    """Vòng tròn chiều dày: số 100-600 nằm giữa 1 đường tròn (curve) -> [{thk, min, x, y}] (mm Revit)."""
    circles = []
    for d in page.get_drawings():
        r = d["rect"]
        if any(it[0] == "c" for it in d["items"]) and d_min_pt < r.width < d_max_pt and abs(r.width - r.height) < 1.5:
            circles.append(((r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0, r.width / 2.0))
    words = page.get_text("words")
    out = []
    for w in words:
        t = w[4].strip()
        if not t.isdigit() or not 100 <= int(t) <= 600:
            continue
        cx, cy = (w[0] + w[2]) / 2.0, (w[1] + w[3]) / 2.0
        if area_pt and not (area_pt[0] <= cx <= area_pt[2] and area_pt[1] <= cy <= area_pt[3]):
            continue
        c = min(circles, key=lambda c: math.hypot(c[0] - cx, c[1] - cy), default=None)
        if not c or math.hypot(c[0] - cx, c[1] - cy) > c[2] * 0.6:
            continue
        if any(abs(o["_pt"][0] - c[0]) < 1 and abs(o["_pt"][1] - c[1]) < 1 for o in out):
            continue
        mn = any(x[4].strip().upper() == "MIN" and math.hypot((x[0] + x[2]) / 2 - c[0], (x[1] + x[3]) / 2 - c[1]) < c[2] * 2.6
                 for x in words)
        X, Y = to_revit(c[0], c[1])
        out.append({"thk": int(t), "min": mn, "x": X, "y": Y, "_pt": (c[0], c[1])})
    return out


def dashed_lines(drawings, to_revit, color=(0.0, 0.0, 0.0), width: float = 0.6, dash_mm=(60.0, 700.0),
                 gap_mm: float = 450.0, min_dashes: int = 3, min_len_mm: float = 1000.0, extend_mm: float = 700.0):
    """Gạch rời cùng kiểu nét -> đường liền (gom theo góc 0.5° + offset 40 mm, hở <= gap_mm), nối dài 2 đầu."""
    short = []
    for d in drawings:
        if (d.get("color") or (9,)) != color or abs((d.get("width") or 0) - width) > 0.01:
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            A, B = to_revit(it[1].x, it[1].y), to_revit(it[2].x, it[2].y)
            if dash_mm[0] <= math.hypot(B[0] - A[0], B[1] - A[1]) <= dash_mm[1]:
                short.append((A, B))
    runs: Dict[tuple, list] = {}
    for A, B in short:
        ang = math.atan2(B[1] - A[1], B[0] - A[0]) % math.pi
        nx, ny = -math.sin(ang), math.cos(ang)
        off = A[0] * nx + A[1] * ny
        runs.setdefault((round(math.degrees(ang) * 2) / 2 % 180, round(off / 40)), []).append((A, B, ang, off))
    out = []
    for segs in runs.values():
        ang = segs[0][2]
        off = sum(s[3] for s in segs) / len(segs)
        ux, uy, nx, ny = math.cos(ang), math.sin(ang), -math.sin(ang), math.cos(ang)
        iv = sorted((min(s[0][0] * ux + s[0][1] * uy, s[1][0] * ux + s[1][1] * uy),
                     max(s[0][0] * ux + s[0][1] * uy, s[1][0] * ux + s[1][1] * uy)) for s in segs)
        cur = [iv[0][0], iv[0][1], 1]
        groups = []
        for lo, hi in iv[1:]:
            if lo - cur[1] <= gap_mm:
                cur[1] = max(cur[1], hi)
                cur[2] += 1
            else:
                groups.append(cur)
                cur = [lo, hi, 1]
        groups.append(cur)
        for lo, hi, n in groups:
            if n >= min_dashes and hi - lo >= min_len_mm:
                lo, hi = lo - extend_mm, hi + extend_mm
                out.append(LineString([(lo * ux + off * nx, lo * uy + off * ny), (hi * ux + off * nx, hi * uy + off * ny)]))
    return out


def dash_points(drawings, to_revit, color=(0.0, 0.0, 0.0), width: float = 0.6, dash_mm=(60.0, 700.0)) -> List[Pt]:
    """Trung điểm các gạch rời (kể cả gạch trên đường cong) - dùng dò dải dày bám mép."""
    pts = []
    for d in drawings:
        if (d.get("color") or (9,)) != color or abs((d.get("width") or 0) - width) > 0.01:
            continue
        for it in d["items"]:
            if it[0] in ("l", "c"):
                a, b = (it[1], it[2]) if it[0] == "l" else (it[1], it[4])
                A, B = to_revit(a.x, a.y), to_revit(b.x, b.y)
                if dash_mm[0] <= math.hypot(B[0] - A[0], B[1] - A[1]) <= dash_mm[1]:
                    pts.append(((A[0] + B[0]) / 2.0, (A[1] + B[1]) / 2.0))
    return pts


def band_strips(main: Polygon, dpts: Sequence[Pt], width_mm: float = 1200.0, tol_mm: float = 150.0,
                piece_mm: float = 600.0, min_hits: int = 1) -> Tuple[Polygon, int]:
    """
    Dải dày bám mép: đi dọc từng đoạn biên sàn chính (chia nhỏ <= piece_mm); nếu PHÍA TRONG cách mép width_mm
    (±tol_mm) có gạch nét đứt -> đoạn đó thuộc dải: tứ giác (mép, mép + width*pháp tuyến trong). Chạy được cả với
    mép cong / góc bậc mà nét đứt không liền. Trả (vùng dải ∩ sàn chính, số đoạn dải).
    """
    from shapely.strtree import STRtree
    tree_pts = [Point(p) for p in dpts]
    tree = STRtree(tree_pts) if tree_pts else None
    quads, n = [], 0
    for ring in [main.exterior] + list(main.interiors):
        cs = list(ring.coords)
        for i in range(len(cs) - 1):
            (x0, y0), (x1, y1) = cs[i], cs[i + 1]
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 50:
                continue
            k = max(1, int(math.ceil(L / piece_mm)))
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            nx, ny = -uy, ux
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            if not main.contains(Point(mx + nx * 300, my + ny * 300)):
                nx, ny = -nx, -ny
                if not main.contains(Point(mx + nx * 300, my + ny * 300)):
                    continue
            for j in range(k):
                ax, ay = x0 + ux * L * j / k, y0 + uy * L * j / k
                bx, by = x0 + ux * L * (j + 1) / k, y0 + uy * L * (j + 1) / k
                off = LineString([(ax + nx * width_mm, ay + ny * width_mm), (bx + nx * width_mm, by + ny * width_mm)])
                hits = 0
                if tree is not None:
                    for q in tree.query(off.buffer(tol_mm)):
                        g = tree_pts[q] if isinstance(q, (int,)) or hasattr(q, "__index__") else q
                        if off.distance(g) <= tol_mm:
                            hits += 1
                if hits >= min_hits:
                    quads.append(Polygon([(ax, ay), (bx, by), (bx + nx * width_mm, by + ny * width_mm), (ax + nx * width_mm, ay + ny * width_mm)]).buffer(1))
                    n += 1
    if not quads:
        return Polygon(), 0
    bands = unary_union(quads).intersection(main)
    bands = bands.buffer(60, join_style=2).buffer(-60, join_style=2).intersection(main)
    return bands, n


def faces_from_lines(lines: Sequence[LineString], tol_mm: float = 25.0, min_area_mm2: float = 2e5) -> List[Polygon]:
    U = unary_union([l.buffer(tol_mm, cap_style=2, join_style=2) for l in lines])
    return [Polygon(r) for g in _parts(U) for r in g.interiors if Polygon(r).area >= min_area_mm2]


def _strip_width(g: Polygon) -> Tuple[float, float]:
    mrr = g.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    e = sorted(Point(c[i]).distance(Point(c[i + 1])) for i in range(2))
    return g.area / max(e[1], 1.0), e[1]


def _band_thk(g, B: List[Dict], band_set, default: int) -> int:
    """Chiều dày dải = vòng tròn (thuộc band_set, không MIN) trong/sát dải; nhiều giá trị -> gần nhất; không có -> default."""
    c = [b for b in B if not b["min"] and b["thk"] in band_set and g.buffer(300).contains(Point(b["x"], b["y"]))]
    if not c:
        return default
    return min(c, key=lambda b: g.distance(Point(b["x"], b["y"])))["thk"]


def _split_by_edge_bands(main: Polygon, B: List[Dict], dpts: Sequence[Pt], band_thickness: int,
                         dashed: Sequence[LineString], band_set=None) -> List[Dict]:
    """Dải bám mép (band_strips) + phần còn lại chia theo vòng tròn; mảnh lẫn nhiều chiều dày chia thêm bằng nét đứt."""
    band_set = set(band_set or (band_thickness,))
    bands, _ = band_strips(main, dpts)
    info = [{"g": g, "thk": _band_thk(g, B, band_set, band_thickness), "band": True, "multi": False, "why": "edge band"}
            for g in _parts(bands) if g.area > 1e4]
    rest = main.difference(bands)
    for comp in _parts(rest):
        if comp.area < 1e4:
            continue
        # vòng tròn 370 nằm NGOÀI dải bám mép (dải lệch vào trong) cũng tính -> buộc chia tiếp bằng nét đứt
        th = sorted(set(b["thk"] for b in B if not b["min"] and comp.contains(Point(b["x"], b["y"]))
                        and not (b["thk"] in band_set and bands.buffer(200).contains(Point(b["x"], b["y"])))))
        if len(th) == 1:
            info.append({"g": comp, "thk": th[0], "band": th[0] in band_set, "multi": False, "why": "bubble"})
            continue
        if len(th) > 1:
            U = unary_union([comp.boundary] + [l.intersection(comp.buffer(1)) for l in dashed if l.intersects(comp)])
            for g in polygonize(U):
                if g.area < 1e4 or not comp.buffer(5).contains(g.representative_point()):
                    continue
                t2 = sorted(set(b["thk"] for b in B if not b["min"] and g.contains(Point(b["x"], b["y"]))))
                isb = False
                if not t2:      # ô con không vòng tròn: dải hẹp ~1200 kề dải dày -> dải (chiều dày dải kề); ô lớn -> chưa rõ
                    w, _ = _strip_width(g)
                    if w <= 2000 and g.buffer(30).intersection(bands).area > 0:
                        nb = max((o for o in info if o.get("band")), key=lambda o: g.buffer(30).intersection(o["g"]).area)
                        t2, isb = [nb["thk"]], True
                info.append({"g": g, "thk": t2[0] if len(t2) == 1 else None, "band": isb or (len(t2) == 1 and t2[0] in band_set),
                             "multi": len(t2) > 1,
                             "why": "bubble+dashed"})
            continue
        # không vòng tròn: mảnh nhỏ sát dải -> dải; còn lại -> chưa xác định
        touch = comp.buffer(30).intersection(bands).area > 0
        nb = max((o for o in info if o.get("band")), key=lambda o: comp.buffer(30).intersection(o["g"]).area, default=None)
        ok = touch and comp.area < 3e6 and nb is not None
        info.append({"g": comp, "thk": nb["thk"] if ok else None, "band": ok, "multi": False,
                     "why": "residual next to band" if ok else "no bubble"})
    for it in info:                       # mảnh vụn < 0.5 m2 -> gộp ô kề lớn nhất
        if it["thk"] is None and it["g"].area < 5e5:
            nb = max((o for o in info if o is not it and o["thk"] is not None),
                     key=lambda o: it["g"].buffer(30).intersection(o["g"]).area, default=None)
            if nb is not None:
                it["thk"], it["why"] = nb["thk"], "sliver merged"
    return info


def extract(page, to_revit, zone_side, split_line: LineString, band_thickness: int = 370,
            step_mm: float = 70.0, band_width_mm=(900.0, 2000.0), dim_text: str = "1200",
            fill_hole_m2: float = 15.0, tol_mm: float = 25.0, bbox_mm=None, band_thicknesses=None,
            close_step_dashes: bool = False) -> Dict:
    """
    zone_side: điểm (mm) nằm phía zone cần lấy so với split_line. Trả {slabs_by_kind, report}.
    slabs: [{"thickness_mm", "z_offset_mm", "region": Polygon/MultiPolygon, "label"}].
    band_thicknesses: các chiều dày dải 1200 trên trang (vd L2 250793: 300/330/340); mỗi dải lấy theo vòng tròn
    trong dải, dải không có vòng tròn lấy theo dải thẳng hàng / kề bên, cuối cùng mới dùng band_thickness.
    Sàn hạ cốt (MIN) chia theo từng mảnh: chiều dày = vòng tròn MIN trong mảnh.
    close_step_dashes: đường bậc / mép sàn hạ cốt vẽ gạch đứt (L2 250793) -> nối gạch (không kéo dài) để khép ô MIN;
    ô MIN chỉ nhận khi gần như không chồng sàn chính.
    """
    band_set = set(band_thicknesses or ()) | {band_thickness}
    drw = page.get_drawings()
    B = bubbles(page, to_revit)
    side = sx.half_plane(split_line.coords[0], split_line.coords[-1], zone_side)
    B = [b for b in B if side.contains(Point(b["x"], b["y"]))]
    groups = sx.stroke_groups(drw, to_revit, bbox_mm)
    key = next(k for k in groups if k[0] == (0.0, 0.0, 0.0) and abs(k[1] - 0.6) < 0.01)
    holes = faces_from_lines(list(groups[key]) + [split_line], tol_mm, 1e6 * 0.3)
    holes = [h for h in holes if side.contains(h.representative_point())]
    def has(h, pred):
        return [b for b in B if pred(b) and h.contains(Point(b["x"], b["y"]))]
    mains = [h for h in holes if has(h, lambda b: not b["min"])]
    main = unary_union(mains) if mains else None
    podium_faces = [h for h in holes if h not in mains and has(h, lambda b: b["min"])]
    if close_step_dashes and main is not None:
        dlp = dashed_lines(drw, to_revit, dash_mm=(20.0, 700.0), extend_mm=0.0, min_len_mm=500.0)
        holes2 = faces_from_lines(list(groups[key]) + dlp + [split_line], tol_mm, 1e6 * 0.3)
        got = unary_union(podium_faces) if podium_faces else Polygon()
        for h in holes2:
            if not side.contains(h.representative_point()) or not has(h, lambda b: b["min"]):
                continue
            if h.intersection(main).area > 0.05 * h.area or (not got.is_empty and h.intersection(got).area > 0.05 * h.area):
                continue
            podium_faces.append(h)
            got = unary_union([got, h])
    slab_core = unary_union([main] + podium_faces) if main is not None else unary_union(podium_faces)
    # ô nhỏ (lòng tường / cột) nằm trong sàn -> lấp; ô lớn không vòng tròn -> báo
    # dấu X trong ô LỖ giữa sàn (giếng thang máy, giếng trời) / ô nhỏ sắp lấp cạnh sàn cũng là lỗ mở
    small = [h for h in holes if h not in mains and h not in podium_faces and h.area <= fill_hole_m2 * 1e6
             and h.buffer(3 * tol_mm).intersection(slab_core).area > 0]
    core_full = unary_union([Polygon(g.exterior) for g in _parts(slab_core)] + small)
    xs = sx.x_openings(drw, to_revit, core_full.buffer(3 * tol_mm), min_area_m2=1.0)
    op_polys = [o[0] if isinstance(o, tuple) else o for o in (xs[0] if isinstance(xs, tuple) else xs)]
    report = {"bubbles": len(B), "unbuilt_regions": [], "unresolved_main_faces": [], "openings": len(op_polys)}
    fills = []
    for h in holes:
        if h in mains or h in podium_faces:
            continue
        a = h.area / 1e6
        touching = h.buffer(3 * tol_mm).intersection(slab_core).area > 0
        if a <= fill_hole_m2 and touching and not any(h.intersects(o) for o in op_polys):
            fills.append(h)
        elif a > 1.0 and not slab_core.buffer(tol_mm).contains(h.representative_point()):
            report["unbuilt_regions"].append({"area_m2": round(a, 1), "at_mm": [round(h.centroid.x), round(h.centroid.y)]})
    # chia sàn chính theo nét đứt
    dl = [l for l in dashed_lines(drw, to_revit) if l.intersects(main.buffer(-50))]
    U = unary_union([main.boundary] + [l.intersection(main.buffer(1)) for l in dl])
    mfaces = [g for g in polygonize(U) if g.area > 1e4 and main.buffer(5).contains(g.representative_point())]
    dims = [to_revit((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) for w in page.get_text("words") if w[4].strip() == dim_text]
    info = []
    for g in mfaces:
        th = sorted(set(b["thk"] for b in B if not b["min"] and g.contains(Point(b["x"], b["y"]))))
        w, L = _strip_width(g)
        info.append({"g": g, "thk": th[0] if len(th) == 1 else None, "multi": len(th) > 1, "w": w, "len": L,
                     "band": bool(len(th) == 1 and th[0] in band_set),
                     "dim": sum(1 for d in dims if g.buffer(700).contains(Point(d)))})
    for it in info:                       # dải 1200 có kích thước '1200' -> dải dày (chiều dày xác định sau)
        if it["thk"] is None and not it["multi"] and band_width_mm[0] <= it["w"] <= band_width_mm[1] and it["dim"]:
            it["band"], it["why"] = True, "band (dim %s)" % dim_text

    def _collinear(a, b):
        # thẳng hàng: bao lồi của 2 đoạn vẫn chỉ rộng ~1 dải (đoạn bị tường cắt ngang, khe ~250 mm)
        if abs(a["w"] - b["w"]) >= 150 or a["g"].distance(b["g"]) > 400:
            return False
        return _strip_width(unary_union([a["g"], b["g"]]).convex_hull)[0] <= max(a["w"], b["w"]) + 150

    changed = True
    while changed:                        # dải thẳng hàng / kề dải đã biết chiều dày -> cùng chiều dày
        changed = False
        for it in info:
            if it["thk"] is not None or not band_width_mm[0] <= it["w"] <= band_width_mm[1]:
                continue
            known = [o for o in info if o.get("band") and o["thk"] is not None and o is not it]
            o = next((o for o in known if _collinear(it, o)), None)
            why = "band (collinear)"
            if o is None and it.get("band"):
                o = max((o for o in known if it["g"].distance(o["g"]) <= 400),
                        key=lambda o: it["g"].buffer(400).intersection(o["g"]).area, default=None)
                why = "band (dim %s, adjacent band)" % dim_text
            if o is not None:
                it["thk"], it["band"], it["why"] = o["thk"], True, why
                changed = True
    for it in info:                       # dải có kích thước 1200 nhưng không dải nào kề có số -> chiều dày mặc định
        if it.get("band") and it["thk"] is None:
            it["thk"], it["why"] = band_thickness, "band (dim %s, default)" % dim_text
    for it in info:                       # mảnh vụn < 0.5 m2 -> gộp ô kề lớn nhất
        if it["thk"] is None and it["g"].area < 5e5:
            nb = max((o for o in info if o is not it and o["thk"] is not None),
                     key=lambda o: it["g"].buffer(5).intersection(o["g"]).area, default=None)
            if nb is not None:
                it["thk"], it["why"] = nb["thk"], "sliver merged"
    report["split_method"] = "dashed_lines"
    if any(it["thk"] is None and it["multi"] for it in info):
        # nét đứt không khép được dải (mép cong / góc bậc) -> dò dải bám mép theo gạch nét đứt cách mép 1200
        info = _split_by_edge_bands(main, B, dash_points(drw, to_revit), band_thickness, dl, band_set)
        report["split_method"] = "edge_bands"
    in_band = unary_union([it["g"] for it in info if it.get("band")]) if info else Polygon()
    report["band_bubbles_outside_bands"] = [[round(b["x"]), round(b["y"])] for b in B
                                            if b["thk"] in band_set and not b["min"] and main.contains(Point(b["x"], b["y"]))
                                            and not in_band.buffer(200).contains(Point(b["x"], b["y"]))]
    # ô lấp (lòng tường / ô khu ướt) chạm sàn chính -> thuộc ô sàn chính kề nhiều nhất (cùng chiều dày)
    for h in fills:
        if not h.buffer(3 * tol_mm).intersects(main):
            continue
        nb = max((it for it in info if it["thk"] is not None),
                 key=lambda it: h.buffer(3 * tol_mm).intersection(it["g"]).area, default=None)
        if nb is not None and h.buffer(3 * tol_mm).intersection(nb["g"]).area > 0:
            nb["g"] = unary_union([nb["g"], h])
    for it in info:
        if it["thk"] is None:
            report["unresolved_main_faces"].append({"area_m2": round(it["g"].area / 1e6, 2),
                                                    "at_mm": [round(it["g"].centroid.x), round(it["g"].centroid.y)],
                                                    "bubbles_multi": it["multi"]})
    # lắp ráp vùng nối khít: tổng thể khép khe nét, ưu tiên dải > ô chính > hạ cốt
    total = unary_union([main] + podium_faces + fills).buffer(tol_mm * 1.2, join_style=2).buffer(-tol_mm * 0.2, join_style=2)
    for o in op_polys:
        total = total.difference(o)
    used = None
    out = []
    order = sorted([it for it in info if it["thk"] is not None], key=lambda it: (0 if it.get("band") else 1, -it["g"].area))
    by_thk: Dict[tuple, list] = {}
    for it in order:
        by_thk.setdefault((bool(it.get("band")), it["thk"]), []).append(it["g"])
    main_closed = unary_union([main] + [f for f in fills if f.buffer(3 * tol_mm).intersects(main)]).buffer(tol_mm * 1.2, join_style=2)
    for key in sorted(by_thk, key=lambda k: (0 if k[0] else 1, k[1])):
        isb, thk = key
        reg = unary_union([g.buffer(tol_mm * 1.2, join_style=2) for g in by_thk[key]]).intersection(main_closed).intersection(total)
        if used is not None:
            reg = reg.difference(used)
        used = reg if used is None else used.union(reg)
        out.append({"thickness_mm": thk, "z_offset_mm": 0.0, "region": reg, "label": ("%d band" if isb and len(band_set) > 1 else "%d") % thk})
    pod_thk = sorted(set(b["thk"] for b in B if b["min"]))
    # sàn hạ cốt CHỈ là phần ngoài sàn chính; ô chính chưa xác định chiều dày -> để trống + báo (không thành -70)
    podium = total.difference(main_closed)
    if used is not None:
        podium = podium.difference(used)
    # mảnh hạ cốt < 1 m2 = phần thừa khi khép khe nét (giữa ô chính và đường bậc) -> trả về ô chính kề nhất
    keep = []
    for p in _parts(podium):
        if p.area >= 1e6:
            keep.append(p)
            continue
        nb = max(out, key=lambda o: p.buffer(tol_mm * 2).intersection(o["region"]).area, default=None)
        if nb is not None and p.buffer(tol_mm * 2).intersection(nb["region"]).area > 0:
            nb["region"] = unary_union([nb["region"], p])
    # mỗi mảnh hạ cốt lấy chiều dày vòng tròn MIN trong mảnh; trang chỉ có 1 giá trị MIN -> dùng cho mọi mảnh (L1);
    # mảnh có nhiều giá trị / không có vòng tròn khi trang có nhiều giá trị -> báo, KHÔNG đoán
    report["unresolved_podium"] = []
    pods: Dict[int, list] = {}
    for p in keep:
        t = sorted(set(b["thk"] for b in B if b["min"] and p.contains(Point(b["x"], b["y"]))))
        if len(t) != 1 and len(pod_thk) == 1:
            t = pod_thk
        if len(t) == 1:
            pods.setdefault(t[0], []).append(p)
        else:
            report["unresolved_podium"].append({"area_m2": round(p.area / 1e6, 2), "at_mm": [round(p.centroid.x), round(p.centroid.y)],
                                                "min_values": t})
    for t in sorted(pods):
        out.append({"thickness_mm": t, "z_offset_mm": -step_mm, "region": unary_union(pods[t]), "label": "%d MIN (-%d)" % (t, step_mm)})
    report["areas_m2"] = {o["label"]: round(o["region"].area / 1e6, 2) for o in out}
    report["total_m2"] = round(total.area / 1e6, 2)
    report["podium_thickness_values"] = pod_thk
    return {"slabs": out, "openings": op_polys, "report": report}


def _clean(poly: Polygon) -> Optional[Polygon]:
    """Biên hợp lệ cho Floor.Create: sửa tự cắt, khử đỉnh thừa nhưng giữ topology."""
    g = poly.buffer(0)
    if g.is_empty:
        return None
    g = max(_parts(g), key=lambda p: p.area)
    s = g.simplify(2.0, preserve_topology=True)
    s = s if s.is_valid else s.buffer(0)
    if isinstance(s, MultiPolygon):
        s = max(s.geoms, key=lambda p: p.area)
    return s if isinstance(s, Polygon) and s.is_valid else (g if g.is_valid else None)


def to_payload(res: Dict, mark_prefix: str = "L1", min_part_m2: float = 0.3, hole_fill_m2: float = 2.0) -> List[Dict]:
    """
    Vùng -> slabs cho batch_create_structural_slabs. Lỗ trong < hole_fill_m2 (dấu vết nét tường / cột / hatch) được
    lấp nếu không trùng sàn khác (sàn chạy liền dưới tường, cột); lỗ lớn giữ làm opening. Kiểm tra hợp lệ + không chồng.
    """
    regions = [(s, _parts(s["region"].buffer(0))) for s in res["slabs"]]
    allu = unary_union([p for _, ps in regions for p in ps])
    out, kept = [], []
    for s, parts in regions:
        others = unary_union([p for s2, ps in regions if s2 is not s for p in ps])
        for part in parts:
            holes = []
            for r in part.interiors:
                h = Polygon(r)
                if h.area >= hole_fill_m2 * 1e6 or (not others.is_empty and h.intersection(others).area > 0.01 * h.area):
                    holes.append(r)
            g = _clean(Polygon(part.exterior, holes))
            if g is None or g.area < min_part_m2 * 1e6:
                continue
            if kept:                          # chống chồng tuyệt đối với các tấm đã nhận
                ov = g.intersection(unary_union(kept)).area
                if ov > 1e4:
                    g = _clean(g.difference(unary_union(kept)))
                    if g is None or g.area < min_part_m2 * 1e6:
                        continue
            kept.append(g)
            for gg in _rounded_valid(g):
                if gg.area < min_part_m2 * 1e6:
                    continue
                out.append({"mark": "%s %s" % (mark_prefix, s["label"]), "thickness_mm": s["thickness_mm"],
                            "z_offset_mm": s["z_offset_mm"], "outer_loop_mm": sx._ring(gg.exterior.coords),
                            "opening_loops_mm": [sx._ring(r.coords) for r in gg.interiors], "area_m2": round(gg.area / 1e6, 2)})
    return out


INSET_MM = 2.5          # lùi biên mỗi tấm: > sai số làm gọn biên (2 mm) -> 2 tấm kề nhau KHÔNG BAO GIỜ chồng (Revit 'floors overlap')
MIN_EDGE_MM = 5.0       # cạnh ngắn nhất cho Floor.Create (Revit short-curve tolerance ~0.8 mm)


def _ring_clean(cs, min_edge: float):
    pts = [(round(x, 1), round(y, 1)) for x, y in cs[:-1]] if cs[0] == cs[-1] else [(round(x, 1), round(y, 1)) for x, y in cs]
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_edge:
            out.append(p)
    while len(out) > 3 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < min_edge:
        out.pop()
    return out


def _round_poly(g: Polygon, min_edge: float = MIN_EDGE_MM) -> Optional[Polygon]:
    ext = _ring_clean(list(g.exterior.coords), min_edge)
    if len(ext) < 3:
        return None
    holes = [h for h in (_ring_clean(list(r.coords), min_edge) for r in g.interiors) if len(h) >= 3]
    return Polygon(ext, holes)


def _rounded_valid(g: Polygon) -> List[Polygon]:
    """Lùi biên INSET_MM, toạ độ 0.1 mm, cạnh >= MIN_EDGE_MM, vẫn hợp lệ: chỗ thắt / tự chạm -> tách mảnh."""
    out = []
    for p in _parts(g.buffer(-INSET_MM, join_style=2)):
        q = _round_poly(p)
        if q is None:
            continue
        if not q.is_valid:
            q2 = q.buffer(0)
            cand = [_round_poly(x) for x in _parts(q2)]
            out += [c for c in cand if c is not None and c.is_valid]
            continue
        out.append(q)
    return out
