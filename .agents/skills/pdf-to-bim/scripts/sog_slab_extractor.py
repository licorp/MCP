# -*- coding: utf-8 -*-
"""
sog_slab_extractor.py - Biên SÀN TRÊN NỀN (S.O.G) từ vector PDF trang TỔNG (S203...).

Sàn S.O.G không có dầm -> không đa giác hóa theo lưới dầm được. Biên sàn = MẶT TRONG vòng tường bao,
lấy trên TRANG TỔNG (cả 2 zone chung 1 hệ tọa độ, quy tắc "trang tổng là chuẩn"):

  1. overall_transform: trang tổng -> Revit, ghép tâm hình cột trang tổng với cột ĐÃ DỰNG (tag PDF2BIM),
     tỉ lệ cố định theo tỉ lệ ghi trên bản vẽ (không ước lượng bằng mắt).
  2. interior_from_page: thử từng NHÓM NÉT (màu + nét dày); nhóm nào khép được vùng kín lớn nhất là nét
     mặt tường. Nét được nở tol mm rồi hợp -> lỗ lớn nhất = vùng trong vòng tường, nở ngược tol -> mặt trong.
  3. x_openings: lỗ mở chữ X (giếng thang, hộp gen) trên trang tổng, diện tích >= min_area_m2, nằm trong sàn.
  4. match_line: đường "FOR CONTINUATION ... ZONE B" của trang zone -> đường chia zone.
  5. split_zones: cắt vùng sàn theo đường chia, mỗi zone lấy phía chứa cột đã dựng của zone đó.
  6. sog_thickness: số ghi ngay trước 'S.O.G' (vòng tròn chiều dày) trên trang zone.

Tọa độ đầu ra: mm Revit, làm tròn 0.1 mm, dạng dùng thẳng cho batch_create_structural_slabs.
"""
import math
import re
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

try:
    import overall_calibration as oc
except Exception:  # pragma: no cover
    oc = None

Pt = Tuple[float, float]
ToRevit = Callable[[float, float], Pt]


# ----------------------------------------------------------------------------- 1. hệ tọa độ
def overall_transform(page, scale: float, revit_cols_mm: Sequence[Pt], tol_mm: float = 120.0):
    """(to_revit(px, py) -> (x, y) mm, stats) cho TRANG TỔNG; None nếu không khớp được >= 60% cột."""
    mm = oc.PT_TO_MM * scale
    ov = [(x * mm, -y * mm) for x, y in oc.rect_centres(page, scale)]
    fit = oc.ransac_similarity(list(revit_cols_mm), ov, tol=tol_mm, fixed_scale=1.0)
    if not fit or len(fit[2]) < max(4, 0.6 * len(revit_cols_mm)):
        return None, {"matched": len(fit[2]) if fit else 0, "revit_columns": len(revit_cols_mm)}
    k, t, inl = fit

    def to_revit(px: float, py: float) -> Pt:
        z = (complex(px * mm, -py * mm) - t) / k
        return (z.real, z.imag)

    st = oc._stats(inl)
    st.update({"matched": len(inl), "revit_columns": len(revit_cols_mm),
               "rotation_deg": round(math.degrees(math.atan2(k.imag, k.real)), 3)})
    return to_revit, st


def similarity_from_pts(pdf_pt1, pdf_pt2, rvt_pt1, rvt_pt2) -> ToRevit:
    """Phép đồng dạng trang zone -> Revit từ 2 cặp điểm mốc (kết quả auto_calibrate_grids)."""
    a1, a2 = complex(pdf_pt1[0], -pdf_pt1[1]), complex(pdf_pt2[0], -pdf_pt2[1])
    k = (complex(*rvt_pt2) - complex(*rvt_pt1)) / (a2 - a1)
    t = complex(*rvt_pt1) - k * a1

    def to_revit(px: float, py: float) -> Pt:
        z = k * complex(px, -py) + t
        return (z.real, z.imag)
    return to_revit


# ----------------------------------------------------------------------------- 2. vùng trong vòng tường
def _bezier(p0, p1, p2, p3, n: int = 12) -> List[Pt]:
    out = []
    for i in range(n + 1):
        t = i / float(n)
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0.x + b * p1.x + c * p2.x + d * p3.x, a * p0.y + b * p1.y + c * p2.y + d * p3.y))
    return out


def _item_points(it) -> List[Pt]:
    if it[0] == "l":
        return [(it[1].x, it[1].y), (it[2].x, it[2].y)]
    if it[0] == "c":
        return _bezier(*it[1:5])
    if it[0] == "re":
        r = it[1]
        return [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
    if it[0] == "qu":
        q = it[1]
        return [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)]
    return []


def stroke_groups(drawings, to_revit: ToRevit, bbox_mm=None, min_items: int = 50) -> Dict[tuple, List[LineString]]:
    """Nét vẽ (stroke) gom theo (màu, nét dày), đã đổi sang mm Revit; bỏ nét ngoài bbox_mm."""
    groups: Dict[tuple, List[LineString]] = defaultdict(list)
    for p in drawings:
        col = p.get("color")
        if p.get("type") not in ("s", "fs") or not col:
            continue
        key = (tuple(round(c, 2) for c in col), round(p.get("width") or 0.0, 2))
        for it in p.get("items", []):
            pts = [to_revit(x, y) for x, y in _item_points(it)]
            if len(pts) < 2:
                continue
            if bbox_mm and not all(bbox_mm[0] <= x <= bbox_mm[2] and bbox_mm[1] <= y <= bbox_mm[3] for x, y in pts):
                continue
            ls = LineString(pts)
            if ls.length > 1.0:
                groups[key].append(ls)
    return {k: v for k, v in groups.items() if len(v) >= min_items}


def enclosed_region(lines: List[LineString], tol_mm: float = 25.0) -> Optional[Polygon]:
    """Vùng kín lớn nhất do các nét bao quanh (đã nở ngược về đúng mặt nét)."""
    if not lines:
        return None
    U = unary_union([l.buffer(tol_mm, cap_style=2, join_style=2) for l in lines])
    parts = list(U.geoms) if isinstance(U, MultiPolygon) else [U]
    holes = [Polygon(r) for g in parts for r in g.interiors]
    if not holes:
        return None
    big = max(holes, key=lambda h: h.area)
    return big.buffer(tol_mm, join_style=2, mitre_limit=3.0).simplify(2.0)


def interior_from_page(drawings, to_revit: ToRevit, bbox_mm=None, tol_mm: float = 25.0,
                       min_area_m2: float = 50.0) -> Dict:
    """Thử từng nhóm nét; nhóm khép vùng kín lớn nhất = nét mặt tường. Trả {polygon, style, area_m2, candidates}."""
    best, cands = None, []
    for key, lines in stroke_groups(drawings, to_revit, bbox_mm).items():
        poly = enclosed_region(lines, tol_mm)
        a = poly.area / 1e6 if poly is not None else 0.0
        cands.append({"style": {"color": key[0], "width": key[1]}, "segments": len(lines), "area_m2": round(a, 1)})
        if a >= min_area_m2 and (best is None or a > best[1]):
            best = (poly, a, key)
    cands.sort(key=lambda c: -c["area_m2"])
    if best is None:
        return {"polygon": None, "candidates": cands}
    return {"polygon": best[0], "area_m2": round(best[1], 1),
            "style": {"color": best[2][0], "width": best[2][1]}, "candidates": cands}


def clean_outline(poly, notch_fill_mm: float = 900.0, smooth_mm: float = 200.0):
    """
    Làm sạch biên (nở mitre nên giữ góc vuông):
      - ĐÓNG (nở rồi co) notch_fill_mm/2: lấp khấc lõm hẹp hơn notch_fill_mm - khấc cột biên lồi khỏi mặt
        tường (300x800) -> sàn chạy liền dưới cột (chân cột ở cao độ level, không chồng khối với sàn).
      - MỞ (co rồi nở) smooth_mm/2: bỏ răng cưa / gai nhỏ (tường cong vẽ bằng nhiều đoạn ngắn, đầu nét).
    Trả (polygon, {"area_before_m2", "area_after_m2"}).
    """
    a0 = poly.area
    p = poly
    if notch_fill_mm > 0:
        r = notch_fill_mm / 2.0
        p = p.buffer(r, join_style=2, mitre_limit=10.0).buffer(-r, join_style=2, mitre_limit=10.0)
    if smooth_mm > 0:
        r = smooth_mm / 2.0
        p = p.buffer(-r, join_style=2, mitre_limit=10.0).buffer(r, join_style=2, mitre_limit=10.0)
    if isinstance(p, MultiPolygon):
        p = max(p.geoms, key=lambda g: g.area)
    p = p.simplify(5.0)
    return p, {"area_before_m2": round(a0 / 1e6, 2), "area_after_m2": round(p.area / 1e6, 2)}


# ----------------------------------------------------------------------------- 3. lỗ mở chữ X
def x_openings(drawings, to_revit: ToRevit, region: Polygon, min_area_m2: float = 1.0,
               mid_tol_mm: float = 40.0, len_tol: float = 0.08) -> Tuple[List[Polygon], List[Dict]]:
    """
    Cặp nét thẳng cắt nhau tại trung điểm, dài tương đương -> hình chữ nhật 4 đầu mút. Giữ lỗ có diện tích
    >= min_area_m2 và nằm trong sàn; lỗ nhỏ hơn (ký hiệu X cạnh cột, ...) liệt kê trong 'skipped'.
    """
    segs = []
    for p in drawings:
        for it in p.get("items", []):
            if it[0] != "l":
                continue
            a, b = to_revit(it[1].x, it[1].y), to_revit(it[2].x, it[2].y)
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if 200.0 <= L <= 8000.0:
                m = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                if region.buffer(1000).contains(Point(m)):
                    segs.append((a, b, m, L))
    keep, skipped, used = [], [], set()
    for i in range(len(segs)):
        if i in used:
            continue
        a1, b1, m1, L1 = segs[i]
        for j in range(i + 1, len(segs)):
            if j in used:
                continue
            a2, b2, m2, L2 = segs[j]
            if abs(L1 - L2) / max(L1, L2) > len_tol or math.hypot(m1[0] - m2[0], m1[1] - m2[1]) > mid_tol_mm:
                continue
            u = ((b1[0] - a1[0]) / L1, (b1[1] - a1[1]) / L1)
            v = ((b2[0] - a2[0]) / L2, (b2[1] - a2[1]) / L2)
            if abs(u[0] * v[1] - u[1] * v[0]) < 0.2:      # gần song song -> không phải chữ X
                continue
            c = ((m1[0] + m2[0]) / 2.0, (m1[1] + m2[1]) / 2.0)
            pts = sorted([a1, b1, a2, b2], key=lambda q: math.atan2(q[1] - c[1], q[0] - c[0]))
            poly = Polygon(pts)
            if not poly.is_valid or poly.area < 40000:
                continue
            used.update((i, j))
            info = {"center_mm": [round(c[0], 1), round(c[1], 1)], "area_m2": round(poly.area / 1e6, 2)}
            if poly.area / 1e6 >= min_area_m2 and region.contains(poly.centroid):
                keep.append(poly)
            else:
                info["reason"] = "nho hon %.1f m2" % min_area_m2 if poly.area / 1e6 < min_area_m2 else "ngoai san"
                skipped.append(info)
            break
    return keep, skipped


# ----------------------------------------------------------------------------- 4-5. chia zone
def match_line(page, to_revit: ToRevit, keyword: str = "CONTINUATION", max_dist_mm: float = 6000.0,
               min_len_mm: float = 15000.0) -> Optional[Dict]:
    """
    Đường chia zone trên trang zone: nhóm nét thẳng đồng tuyến (gom theo góc + khoảng cách tới gốc, ô 50 mm)
    dài nhất, song song và gần dòng chữ 'FOR CONTINUATION REFER ...'. Trả {p1, p2, length_mm, text}.
    """
    blk = next((b for b in page.get_text("blocks") if keyword in b[4].upper()), None)
    if blk is None:
        return None
    t0, t1 = to_revit(blk[0], blk[1]), to_revit(blk[2], blk[3])
    tc = ((t0[0] + t1[0]) / 2.0, (t0[1] + t1[1]) / 2.0)
    runs: Dict[tuple, List] = defaultdict(lambda: [0.0, None, []])
    for p in page.get_drawings():
        for it in p.get("items", []):
            if it[0] != "l":
                continue
            a, b = to_revit(it[1].x, it[1].y), to_revit(it[2].x, it[2].y)
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 300:
                continue
            ang = math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi
            nx, ny = -math.sin(ang), math.cos(ang)
            off = a[0] * nx + a[1] * ny
            key = (round(math.degrees(ang) * 2) / 2.0 % 180.0, round(off / 50.0))
            r = runs[key]
            r[0] += L
            r[1] = (ang, off)
            r[2] += [a, b]
    best = None
    for key, (L, (ang, off), pts) in runs.items():
        if L < min_len_mm:
            continue
        nx, ny = -math.sin(ang), math.cos(ang)
        dist = abs(tc[0] * nx + tc[1] * ny - off)
        if dist > max_dist_mm:
            continue
        ux, uy = math.cos(ang), math.sin(ang)
        ts = [q[0] * ux + q[1] * uy for q in pts]
        span = max(ts) - min(ts)
        if best is None or span > best[0]:
            q0 = pts[ts.index(min(ts))]
            q1 = pts[ts.index(max(ts))]
            best = (span, q0, q1, dist)
    if best is None:
        return None
    return {"p1": [round(best[1][0], 1), round(best[1][1], 1)], "p2": [round(best[2][0], 1), round(best[2][1], 1)],
            "length_mm": round(best[0], 1), "text_distance_mm": round(best[3], 1), "text": blk[4].replace("\n", " ")[:120]}


def half_plane(p1: Sequence[float], p2: Sequence[float], side_pt: Sequence[float], R: float = 1e6) -> Polygon:
    """Nửa mặt phẳng giới hạn bởi đường p1-p2 (kéo dài vô hạn), phía chứa side_pt."""
    ux, uy = p2[0] - p1[0], p2[1] - p1[1]
    L = math.hypot(ux, uy)
    ux, uy = ux / L, uy / L
    nx, ny = -uy, ux
    if (side_pt[0] - p1[0]) * nx + (side_pt[1] - p1[1]) * ny < 0:
        nx, ny = -nx, -ny
    a = (p1[0] - ux * R, p1[1] - uy * R)
    b = (p1[0] + ux * R, p1[1] + uy * R)
    return Polygon([a, b, (b[0] + nx * R, b[1] + ny * R), (a[0] + nx * R, a[1] + ny * R)])


def split_zones(region, zones: List[Dict]) -> List[Dict]:
    """
    zones theo thứ tự trang: [{"zone", "columns": [(x, y)], "line": {p1, p2} | None}]. Zone i lấy phần còn lại
    phía đường chia của nó chứa trọng tâm cột zone đó; zone cuối lấy toàn bộ phần còn lại.
    (Quy tắc dải chồng: phần đã giao cho trang zone trước thì GIỮ ở zone trước.)
    """
    rest, out = region, []
    for i, z in enumerate(zones):
        last = i == len(zones) - 1
        if last or not z.get("line"):
            part = rest
        else:
            cx = sum(c[0] for c in z["columns"]) / len(z["columns"])
            cy = sum(c[1] for c in z["columns"]) / len(z["columns"])
            part = rest.intersection(half_plane(z["line"]["p1"], z["line"]["p2"], (cx, cy)))
        rest = rest.difference(part)
        out.append(dict(z, region=part))
    return out


# ----------------------------------------------------------------------------- 6. chiều dày
def sog_thickness(page) -> Optional[int]:
    """Số (2-3 chữ số) đứng ngay trước 'S.O.G' trên trang (vòng tròn chiều dày); lấy giá trị nhiều nhất."""
    words = page.get_text("words")
    vals = []
    for i, w in enumerate(words):
        if re.fullmatch(r"S\.?O\.?G\.?", w[4].upper()):
            for j in range(max(0, i - 3), i):
                if re.fullmatch(r"\d{2,3}", words[j][4]):
                    vals.append(int(words[j][4]))
    return Counter(vals).most_common(1)[0][0] if vals else None


# ----------------------------------------------------------------------------- đầu ra
def _ring(coords) -> List[Dict]:
    pts = list(coords)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return [{"x": round(x, 1), "y": round(y, 1)} for x, y in pts]


def to_slab_payload(region, thickness_mm: float, mark: str, openings: List[Polygon],
                    z_offset_mm: float = 0.0, min_part_m2: float = 1.0) -> List[Dict]:
    """Vùng (có thể nhiều mảnh) trừ lỗ mở -> danh sách slabs cho batch_create_structural_slabs."""
    geom = region.difference(unary_union(openings)) if openings else region
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    out = []
    for g in parts:
        if not isinstance(g, Polygon) or g.area / 1e6 < min_part_m2:
            continue
        g = g.simplify(2.0)
        out.append({"mark": mark, "thickness_mm": thickness_mm, "z_offset_mm": z_offset_mm,
                    "outer_loop_mm": _ring(g.exterior.coords),
                    "opening_loops_mm": [_ring(r.coords) for r in g.interiors],
                    "area_m2": round(g.area / 1e6, 2)})
    return out
