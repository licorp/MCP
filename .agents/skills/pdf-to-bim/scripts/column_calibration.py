# -*- coding: utf-8 -*-
"""
column_calibration.py - Khớp hệ tọa độ PDF <-> Revit KHÔNG cần lưới trục
Dùng cho các Marking Plan không vẽ Grid (vd: "Refer to architectural drawings for column setout"):
  1. extract_pdf_column_features: lấy hình chữ nhật / hình tròn có mã cột ở gần (CC3, CC4A, C1...)
     từ dữ liệu vector của trang PDF (đơn vị point, hệ trục PyMuPDF).
  2. calibrate_from_columns: ghép với các cột CÙNG MÃ đã có trong Revit (mm), tìm phép biến đổi
     đồng dạng (tỉ lệ + xoay + tịnh tiến) được nhiều cột đồng ý nhất (RANSAC theo cặp cột),
     tinh chỉnh bình phương tối thiểu trên các cặp khớp, báo sai số.
Kết quả có cùng dạng với grid_detector.calibrate_from_grids (pdf_grid_pt1/pt2, revit_grid_pt1/pt2_mm)
để dùng thẳng cho AffineTransformer.
"""

import math
import re
from typing import Dict, List, Optional

try:
    from pdf_struct_parser import AffineTransformer
    from grid_detector import _iter_circles
except ImportError:
    from .pdf_struct_parser import AffineTransformer
    from .grid_detector import _iter_circles

PT_TO_MM = 25.4 / 72.0
# Mã cột: CC3, CC4A, C1, SC2... (chữ cái đầu là C), bỏ hậu tố như '(o)'
_COL_MARK_RE = re.compile(r"^(C[A-Z]{0,3}\d{1,3}[A-Z]?)\b")
_TYPE_MARK_RE = re.compile(r"^([A-Z]{1,4}\d{1,3}[A-Z]?)\b")


def drawing_scale_from_text(page) -> Optional[int]:
    """Đọc 'SCALE 1 : 100' trên trang (lấy tỉ lệ xuất hiện nhiều nhất)."""
    found = re.findall(r"SCALE\s*:?\s*1\s*:\s*(\d{1,4})", page.get_text().upper())
    if not found:
        return None
    return int(max(set(found), key=found.count))


def column_mark_from_text(text: str) -> str:
    m = _COL_MARK_RE.match((text or "").strip().upper())
    return m.group(1) if m else ""


def revit_column_mark(type_name: str, mark_param: str = "") -> str:
    """Mã cột của cột Revit: tiền tố tên loại ('CC3 - 800x300' -> 'CC3'), fallback tham số Mark."""
    for s in (type_name, mark_param):
        m = _TYPE_MARK_RE.match((s or "").strip().upper())
        if m and any(ch.isdigit() for ch in m.group(1)):
            return m.group(1)
    return ""


def section_signature(b_mm: float, h_mm: float, step: float = 50.0):
    """Khóa tiết diện không phụ thuộc hướng: (cạnh nhỏ, cạnh lớn) làm tròn 50 mm."""
    if not b_mm or not h_mm:
        return None
    return (int(round(min(b_mm, h_mm) / step)), int(round(max(b_mm, h_mm) / step)))


def revit_type_signature(type_name: str):
    """'CC3 - 800x300' -> (6, 16); 'CC5 - 300DIA' -> (6, 6)."""
    t = (type_name or "").upper()
    m = re.search(r"(\d{2,4})\s*[X\*×]\s*(\d{2,4})", t)
    if m:
        return section_signature(float(m.group(1)), float(m.group(2)))
    m = re.search(r"(\d{2,4})\s*(?:DIA\b|D\b|Ø)", t) or re.search(r"[ØΦ]\s*(\d{2,4})", t)
    if m:
        d = float(m.group(1))
        return section_signature(d, d)
    return None


def _in_area(x, y, area):
    return area is None or (area[0] <= x <= area[2] and area[1] <= y <= area[3])


def _round_outline_count(cx, cy, r, buckets, cell):
    """Số đoạn thẳng nằm trên đường tròn tâm (cx, cy) bán kính r (cột tròn vẽ bằng nhiều đoạn rời)."""
    n = 0
    gx, gy = int(cx // cell), int(cy // cell)
    for i in (gx - 1, gx, gx + 1):
        for j in (gy - 1, gy, gy + 1):
            for x1, y1, x2, y2 in buckets.get((i, j), ()):
                d1 = math.hypot(x1 - cx, y1 - cy)
                d2 = math.hypot(x2 - cx, y2 - cy)
                if 0.85 * r <= d1 <= 1.12 * r and 0.85 * r <= d2 <= 1.12 * r:
                    n += 1
    return n


def _orient_rect(u, buckets, cell, mm_per_pt, min_mm, max_mm, tol_pt=0.6):
    """
    Cột XOAY trên trang (vd cánh nối vẽ nghiêng 30°): PDF vẽ 4 nét xiên + 1 ô nền trắng thẳng trục bao ngoài.
    Ô nền chỉ là hình bao -> tìm các nét xiên nằm trong ô, lấy cạnh thật và góc thật (angle_deg, độ, hệ trang
    Y xuống, theo cạnh b_mm). Không có nét xiên -> giữ nguyên.
    """
    w_pt, h_pt = u["b_mm"] / mm_per_pt, u["h_mm"] / mm_per_pt
    x0, x1 = u["x"] - w_pt / 2 - tol_pt, u["x"] + w_pt / 2 + tol_pt
    y0, y1 = u["y"] - h_pt / 2 - tol_pt, u["y"] + h_pt / 2 + tol_pt
    segs = []
    for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 2):
        for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 2):
            for ax, ay, bx, by in buckets.get((gx, gy), ()):
                if not (x0 <= ax <= x1 and x0 <= bx <= x1 and y0 <= ay <= y1 and y0 <= by <= y1):
                    continue
                L = math.hypot(bx - ax, by - ay)
                if L * mm_per_pt < 0.5 * min_mm:
                    continue
                a = math.degrees(math.atan2(by - ay, bx - ax)) % 180.0
                if min(a % 90.0, 90.0 - a % 90.0) < 3.0:
                    continue  # nét thẳng trục: không phải cạnh cột xoay
                segs.append((L, a))
    if len(segs) < 2:
        return
    segs.sort(reverse=True)
    L1, a1 = segs[0]
    perp = [s for s in segs[1:] if abs(((s[1] - a1) % 180.0) - 90.0) < 3.0]
    if not perp:
        return
    L2 = perp[0][0]
    b, h = L1 * mm_per_pt, L2 * mm_per_pt
    r = math.radians(a1)
    # hình bao của hình chữ nhật xoay phải khớp ô nền
    bw = b * abs(math.cos(r)) + h * abs(math.sin(r))
    bh = b * abs(math.sin(r)) + h * abs(math.cos(r))
    if abs(bw - u["b_mm"]) > 0.08 * u["b_mm"] or abs(bh - u["h_mm"]) > 0.08 * u["h_mm"]:
        return
    if min_mm <= min(b, h) and max(b, h) <= max_mm:
        u.update({"b_mm": round(b), "h_mm": round(h), "angle_deg": round(a1, 3)})


def extract_pdf_column_features(page, scale: float, drawings=None,
                                 min_mm: float = 190.0, max_mm: float = 2500.0,
                                 label_radius_mm: float = 2000.0,
                                 area_pt=None) -> List[Dict]:
    """
    Trả về [{"mark", "x", "y" (point PDF), "kind": rect|circle, "b_mm" (phương X của trang),
    "h_mm" (phương Y của trang)}] cho các hình cột có mã cột trong bán kính label_radius_mm.
    Mỗi hình chỉ gán 1 mã (gần nhất trước). Cột tròn: hình tròn khép kín, hoặc ô gần vuông có
    >= 12 đoạn thẳng rời nằm trên đường tròn nội tiếp. area_pt (x0, y0, x1, y1): chỉ xét trong vùng.
    """
    mm_per_pt = PT_TO_MM * scale
    drawings = drawings if drawings is not None else page.get_drawings()

    shapes = []
    for path in drawings:
        for it in path.get("items", []):
            if it[0] == "re":
                r = it[1]
                w, h = abs(r.width) * mm_per_pt, abs(r.height) * mm_per_pt
                if min_mm <= w <= max_mm and min_mm <= h <= max_mm:
                    shapes.append({"x": (r.x0 + r.x1) / 2.0, "y": (r.y0 + r.y1) / 2.0,
                                   "kind": "rect", "b_mm": round(w), "h_mm": round(h)})
            elif it[0] == "qu":
                q = it[1]
                xs = [q.ul.x, q.ur.x, q.ll.x, q.lr.x]
                ys = [q.ul.y, q.ur.y, q.ll.y, q.lr.y]
                w = math.hypot(q.ur.x - q.ul.x, q.ur.y - q.ul.y) * mm_per_pt
                h = math.hypot(q.ll.x - q.ul.x, q.ll.y - q.ul.y) * mm_per_pt
                if min_mm <= w <= max_mm and min_mm <= h <= max_mm:
                    shapes.append({"x": sum(xs) / 4.0, "y": sum(ys) / 4.0,
                                   "kind": "rect", "b_mm": round(w), "h_mm": round(h)})
    for cx, cy, r in _iter_circles(drawings):
        d = 2 * r * mm_per_pt
        if min_mm <= d <= max_mm:
            shapes.append({"x": cx, "y": cy, "kind": "circle", "b_mm": round(d), "h_mm": round(d)})

    shapes = [s for s in shapes if _in_area(s["x"], s["y"], area_pt)]
    # Hình tròn khép kín ưu tiên trước để giữ lại khi gộp với ô vuông nền trắng cùng tâm
    shapes.sort(key=lambda s: 0 if s["kind"] == "circle" else 1)

    # Gộp hình trùng tâm (nét đôi / hatch vẽ chồng)
    uniq = []
    for s in shapes:
        if not any(math.hypot(s["x"] - u["x"], s["y"] - u["y"]) * mm_per_pt < 30 for u in uniq):
            uniq.append(s)

    # Cột tròn vẽ bằng nhiều đoạn thẳng rời quanh 1 ô vuông
    cell = 20.0
    buckets = {}
    for path in drawings:
        for it in path.get("items", []):
            if it[0] == "l":
                a, b = it[1], it[2]
                buckets.setdefault((int(a.x // cell), int(a.y // cell)), []).append((a.x, a.y, b.x, b.y))
    for u in uniq:
        if u["kind"] == "rect" and abs(u["b_mm"] - u["h_mm"]) <= 0.05 * max(u["b_mm"], u["h_mm"]):
            r_pt = (u["b_mm"] + u["h_mm"]) / 4.0 / mm_per_pt
            if r_pt < cell and _round_outline_count(u["x"], u["y"], r_pt, buckets, cell) >= 12:
                d = int(round((u["b_mm"] + u["h_mm"]) / 2.0))
                u.update({"kind": "circle", "b_mm": d, "h_mm": d})
                continue
        if u["kind"] == "rect":
            _orient_rect(u, buckets, cell, mm_per_pt, min_mm, max_mm)

    labels = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                mk = column_mark_from_text(span["text"])
                if mk:
                    b = span["bbox"]
                    lx, ly = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
                    if _in_area(lx, ly, area_pt):
                        labels.append((mk, lx, ly))

    # Ghép nhãn <-> hình theo khoảng cách tăng dần, mỗi bên dùng 1 lần
    radius_pt = label_radius_mm / mm_per_pt
    pairs = []
    for li, (mk, lx, ly) in enumerate(labels):
        for si, s in enumerate(uniq):
            d = math.hypot(lx - s["x"], ly - s["y"])
            if d <= radius_pt:
                pairs.append((d, li, si))
    pairs.sort()
    used_l, used_s, feats = set(), set(), []
    for d, li, si in pairs:
        if li in used_l or si in used_s:
            continue
        used_l.add(li)
        used_s.add(si)
        f = dict(uniq[si])
        f["mark"] = labels[li][0]
        feats.append(f)
    return feats


def _fit_similarity(src, dst, nominal_scale=None, snap_deg=0.1, snap_scale=0.01):
    """
    Bình phương tối thiểu phép đồng dạng 2D (không lật): dst ~ s*R*src + t.
    Góc gần bội số 90° (< snap_deg) và tỉ lệ gần tỉ lệ ghi trên bản vẽ (< snap_scale) được làm tròn
    về đúng giá trị, rồi tính lại tịnh tiến - tránh cấu kiện bị xiên vài phần trăm độ trong Revit.
    Trả về (hàm biến đổi, thông tin).
    """
    n = len(src)
    mx = sum(p[0] for p in src) / n
    my = sum(p[1] for p in src) / n
    qx = sum(q[0] for q in dst) / n
    qy = sum(q[1] for q in dst) / n
    a = b = norm = 0.0
    for (px, py), (ux, uy) in zip(src, dst):
        px, py, ux, uy = px - mx, py - my, ux - qx, uy - qy
        a += px * ux + py * uy
        b += px * uy - py * ux
        norm += px * px + py * py
    sc, ss = a / norm, b / norm  # s*cos, s*sin
    scale, ang = math.hypot(sc, ss), math.degrees(math.atan2(ss, sc))
    info = {"snapped_rotation": False, "snapped_scale": False}
    k90 = round(ang / 90.0) * 90.0
    if abs(ang - k90) < snap_deg:
        ang = k90
        info["snapped_rotation"] = True
        # tỉ lệ tối ưu khi góc cố định
        c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        num = 0.0
        for (px, py), (ux, uy) in zip(src, dst):
            px, py, ux, uy = px - mx, py - my, ux - qx, uy - qy
            num += (c * px - s_ * py) * ux + (s_ * px + c * py) * uy
        scale = num / norm
    if nominal_scale and abs(scale / nominal_scale - 1.0) < snap_scale:
        scale = nominal_scale
        info["snapped_scale"] = True
    sc = scale * math.cos(math.radians(ang))
    ss = scale * math.sin(math.radians(ang))
    tx = qx - (sc * mx - ss * my)
    ty = qy - (ss * mx + sc * my)
    return (lambda x, y: (sc * x - ss * y + tx, ss * x + sc * y + ty)), info


def calibrate_from_columns(pdf_feats: List[Dict], revit_cols: List[Dict], scale: int,
                           tol_mm: float = 200.0, max_pairs: int = 400,
                           min_inliers: int = 4, area_margin_mm: float = 5000.0) -> Dict:
    """
    pdf_feats: kết quả extract_pdf_column_features (point, Y xuống).
    revit_cols: [{"mark", "type", "x", "y"}] (mm, Y lên) - cột đi qua cao độ tầng đang dựng.
    Ghép theo TIẾT DIỆN (800x300, 300DIA...) khi tên loại Revit có kích thước - bền với nhãn
    PDF bị gán nhầm sang cột bên cạnh; nếu không thì ghép theo MÃ cột.
    """
    mm_per_pt = PT_TO_MM * scale
    sigs = [revit_type_signature(c.get("type", "")) for c in revit_cols]
    match_by = "section" if revit_cols and sum(1 for g in sigs if g) >= 0.8 * len(revit_cols) else "mark"

    def pdf_key(f):
        return section_signature(f["b_mm"], f["h_mm"]) if match_by == "section" else f["mark"]

    by_mark = {}
    for c, g in zip(revit_cols, sigs):
        k = g if match_by == "section" else c.get("mark")
        if k:
            by_mark.setdefault(k, []).append((float(c["x"]), float(c["y"])))
    feats = [dict(f, key=pdf_key(f)) for f in pdf_feats]
    feats = [f for f in feats if f["key"] in by_mark]

    base = {
        "method": "columns",
        "match_by": match_by,
        "pdf_column_marks": len(pdf_feats),
        "revit_columns": len(revit_cols),
        "common_marks": sorted(set(f["mark"] for f in feats)),
        "only_in_pdf": sorted(set(f["mark"] for f in pdf_feats) - set(f["mark"] for f in feats)),
    }
    if len(feats) < min_inliers:
        base.update({"status": "error",
                     "message": "Khong du cot co ma trung nhau giua PDF ({}) va Revit ({}) de khop toa do."
                     .format(len(pdf_feats), len(revit_cols))})
        return base

    pts = [(f["x"], f["y"]) for f in feats]

    def score(tr):
        inl, err = [], 0.0
        for i, f in enumerate(feats):
            p = tr.to_revit_mm(f["x"], f["y"])
            best = None
            for q in by_mark[f["key"]]:
                d = math.hypot(p["x"] - q[0], p["y"] - q[1])
                if d <= tol_mm and (best is None or d < best[0]):
                    best = (d, q)
            if best:
                inl.append((i, best[1]))
                err += best[0]
        return inl, err

    # Cặp cột PDF xa nhau trước (ổn định hình học)
    pairs = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) * mm_per_pt
            if d >= 2000:
                pairs.append((d, i, j))
    pairs.sort(reverse=True)

    best = None
    for d_mm, i, j in pairs[:max_pairs]:
        tol_d = max(150.0, 0.02 * d_mm)
        for r in by_mark[feats[i]["key"]]:
            for s in by_mark[feats[j]["key"]]:
                if r == s or abs(math.hypot(r[0] - s[0], r[1] - s[1]) - d_mm) > tol_d:
                    continue
                tr = AffineTransformer(pts[i], pts[j], r, s)
                inl, err = score(tr)
                if best is None or len(inl) > len(best[0]) or (len(inl) == len(best[0]) and err < best[1]):
                    best = (inl, err)
        if best and len(best[0]) >= 0.9 * len(feats):
            break

    if not best or len(best[0]) < min_inliers:
        base.update({"status": "error",
                     "message": "Khong tim duoc phep bien doi du so cot dong y (toi da {} cot).".format(
                         len(best[0]) if best else 0)})
        return base

    # Tinh chỉnh bình phương tối thiểu trên các cặp khớp (PDF đã đảo Y)
    src = [(pts[i][0], -pts[i][1]) for i, _ in best[0]]
    dst = [q for _, q in best[0]]
    fit, fit_info = _fit_similarity(src, dst, nominal_scale=mm_per_pt)

    # 2 mốc = 2 cột khớp xa nhau nhất -> AffineTransformer tái tạo đúng phép fit
    ia, ib = max(((a, b) for a in range(len(src)) for b in range(a + 1, len(src))),
                 key=lambda ab: math.hypot(src[ab[0]][0] - src[ab[1]][0], src[ab[0]][1] - src[ab[1]][1]))
    pa, pb = (src[ia][0], -src[ia][1]), (src[ib][0], -src[ib][1])
    ra, rb = fit(*src[ia]), fit(*src[ib])
    tr = AffineTransformer(pa, pb, ra, rb)

    errs = []
    for (i, q) in best[0]:
        p = tr.to_revit_mm(*pts[i])
        errs.append((math.hypot(p["x"] - q[0], p["y"] - q[1]), feats[i]["mark"]))
    errs.sort()
    rms = math.sqrt(sum(e * e for e, _ in errs) / len(errs))
    ratio = len(errs) / float(len(feats))
    # Khung mặt bằng = vùng bao các cột đã khớp + lề (loại chú thích/bảng/khung tên)
    margin_pt = area_margin_mm / mm_per_pt
    ipx = [pts[i][0] for i, _ in best[0]]
    ipy = [pts[i][1] for i, _ in best[0]]
    area = [round(min(ipx) - margin_pt, 1), round(min(ipy) - margin_pt, 1),
            round(max(ipx) + margin_pt, 1), round(max(ipy) + margin_pt, 1)]

    base.update({
        "status": "success" if ratio >= 0.5 else "error",
        "matched_columns": len(errs),
        "pdf_columns_with_common_mark": len(feats),
        "match_ratio": round(ratio, 2),
        "pdf_grid_pt1": [round(pa[0], 3), round(pa[1], 3)],
        "pdf_grid_pt2": [round(pb[0], 3), round(pb[1], 3)],
        "revit_grid_pt1_mm": [round(ra[0], 1), round(ra[1], 1)],
        "revit_grid_pt2_mm": [round(rb[0], 1), round(rb[1], 1)],
        "anchors": ["{}@({:.0f},{:.0f})".format(feats[best[0][k][0]]["mark"], *dst[k]) for k in (ia, ib)],
        "drawing_scale": "1:{}".format(int(round(tr.scale / PT_TO_MM))),
        "rotation_deg": round(math.degrees(tr.theta), 3),
        "residual_rms_mm": round(rms, 1),
        "residual_max_mm": round(errs[-1][0], 1),
        "drawing_area_pt": area,
        "snapped_rotation": fit_info["snapped_rotation"],
        "snapped_scale": fit_info["snapped_scale"],
    })
    if ratio < 0.5:
        base["message"] = "Chi {:.0%} cot PDF co ma chung khop duoc - nghi ngo sai tang/sai toa nha.".format(ratio)
    return base
