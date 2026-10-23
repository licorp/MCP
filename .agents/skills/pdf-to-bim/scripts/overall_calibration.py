# -*- coding: utf-8 -*-
"""
Khớp tọa độ qua TRANG TỔNG (overall plan) - vd S200 bao cả Zone A và Zone B.

    trang zone (S202, 1:100) --cột--> trang tổng (S200, 1:150) --cột--> Revit (mm)

- Trang zone -> trang tổng: ghép TÂM hình cột (có mã) của trang zone với tâm các hình chữ nhật cột
  trên trang tổng, tỉ lệ cố định theo tỉ lệ ghi trên 2 bản vẽ, góc xoay tự do (Zone B vẽ xoay).
- Trang tổng -> Revit: ghép tâm hình cột trang tổng với cột ĐÃ DỰNG trong Revit (ưu tiên cột có tag
  PDF2BIM - dựng theo bản vẽ kết cấu), tỉ lệ cố định, góc làm tròn bội số 90° khi lệch nhỏ.
Mọi zone đi qua CÙNG một phép trang tổng -> Revit nên khớp nhau ở chỗ nối, không lệch theo file link
kiến trúc (thực tế dự án 250793: link kiến trúc lệch hệ thống ~80-105 mm so với bản kết cấu).
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from column_calibration import PT_TO_MM
except Exception:  # pragma: no cover
    PT_TO_MM = 25.4 / 72.0

# Trang zone -> số hiệu trang tổng (bộ bản vẽ HPCE 250793). Không có trong bảng -> tìm theo tiêu đề.
OVERALL_SHEETS = {
    "S201": "S200", "S202": "S200",
    "S204": "S203", "S205": "S203",
    "S207": "S206", "S208": "S206",
    "S210": "S209", "S211": "S209",
    "S213": "S212", "S214": "S212",
    "S216": "S215", "S217": "S215",
}

Pt = Tuple[float, float]


def rect_centres(page, scale: float, lo_mm: float = 150.0, hi_mm: float = 2500.0,
                 drawings=None) -> List[Pt]:
    """Tâm các hình chữ nhật cỡ cột (150-2500 mm) trên trang, đơn vị point PDF (Y xuống), đã gộp trùng."""
    mm = PT_TO_MM * scale
    out: List[Pt] = []
    for p in (drawings if drawings is not None else page.get_drawings()):
        for it in p.get("items", []):
            if it[0] == "re":
                r = it[1]
                w, h = abs(r.width) * mm, abs(r.height) * mm
                if lo_mm <= w <= hi_mm and lo_mm <= h <= hi_mm:
                    c = ((r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0)
                    if not any(math.hypot(c[0] - o[0], c[1] - o[1]) * mm < 30 for o in out):
                        out.append(c)
    return out


def _sim(a1: Pt, a2: Pt, b1: Pt, b2: Pt):
    k = complex(b2[0] - b1[0], b2[1] - b1[1]) / complex(a2[0] - a1[0], a2[1] - a1[1])
    return k, complex(*b1) - k * complex(*a1)


def _apply(k: complex, t: complex, p: Pt) -> Pt:
    z = k * complex(*p) + t
    return (z.real, z.imag)


def ransac_similarity(src: Sequence[Pt], dst: Sequence[Pt], tol: float = 120.0, min_d: float = 3000.0,
                      max_pairs: int = 600, fixed_scale: Optional[float] = 1.0, snap_deg: float = 0.1,
                      outlier_min_mm: float = 25.0):
    """
    Phép đồng dạng (không lật) src -> dst theo vị trí; src nên là tập NHỎ/đủ (mọi điểm src đều có
    điểm tương ứng trong dst). Trả (k, t, inliers[(i_src, j_dst, err)]) hoặc None.
    """
    if len(src) < 2 or len(dst) < 2:
        return None
    pairs = sorted(((math.hypot(src[i][0] - src[j][0], src[i][1] - src[j][1]), i, j)
                    for i in range(len(src)) for j in range(i + 1, len(src))), reverse=True)
    pairs = [p for p in pairs if p[0] >= min_d][:max_pairs]
    buckets: Dict[int, list] = {}
    for a in range(len(dst)):
        for b in range(len(dst)):
            if a != b:
                d = math.hypot(dst[a][0] - dst[b][0], dst[a][1] - dst[b][1])
                buckets.setdefault(int(d // 200), []).append((a, b, d))

    def inliers(k, t):
        res = []
        for si, p in enumerate(src):
            q = _apply(k, t, p)
            bj = min(range(len(dst)), key=lambda x: (dst[x][0] - q[0]) ** 2 + (dst[x][1] - q[1]) ** 2)
            e = math.hypot(dst[bj][0] - q[0], dst[bj][1] - q[1])
            if e <= tol:
                res.append((si, bj, e))
        return res

    best = None
    for d, i, j in pairs:
        for key in (int(d // 200) - 1, int(d // 200), int(d // 200) + 1):
            for a, b, dd in buckets.get(key, []):
                if abs(dd - d) > max(150.0, 0.01 * d):
                    continue
                k, t = _sim(src[i], src[j], dst[a], dst[b])
                if fixed_scale and abs(abs(k) - fixed_scale) > 0.01 * fixed_scale:
                    continue
                inl = inliers(k, t)
                if best is None or len(inl) > len(best[2]) or \
                        (len(inl) == len(best[2]) and sum(x[2] for x in inl) < sum(x[2] for x in best[2])):
                    best = (k, t, inl)
        if best and len(best[2]) >= 0.95 * len(src):
            break
    if best is None or len(best[2]) < 3:
        return None
    def refit(inl):
        """Bình phương tối thiểu trên các cặp khớp (tỉ lệ cố định, góc làm tròn bội số 90° khi lệch nhỏ)."""
        S = [complex(*src[i]) for i, _, _ in inl]
        D = [complex(*dst[j]) for _, j, _ in inl]
        ms, md = sum(S) / len(S), sum(D) / len(D)
        k = sum((d - md) * (s - ms).conjugate() for s, d in zip(S, D)) / sum(abs(s - ms) ** 2 for s in S)
        ang = math.degrees(math.atan2(k.imag, k.real))
        k90 = round(ang / 90.0) * 90.0
        sc = fixed_scale if fixed_scale else abs(k)
        if abs(ang - k90) < snap_deg:
            ang = k90
        k = complex(sc * math.cos(math.radians(ang)), sc * math.sin(math.radians(ang)))
        t = md - k * ms
        return k, t, [(i, j, math.hypot(*(lambda q: (dst[j][0] - q[0], dst[j][1] - q[1]))(_apply(k, t, src[i]))))
                      for i, j, _ in inl]

    k, t, inl = refit(best[2])
    # Loại điểm lệch bất thường (vd nhãn cột ghép nhầm sang ô chữ nhật bên cạnh) rồi khớp lại
    errs = sorted(e for _, _, e in inl)
    med = errs[len(errs) // 2]
    cut = max(outlier_min_mm, 4.0 * med)
    keep = [x for x in inl if x[2] <= cut]
    if len(keep) < len(inl) and len(keep) >= 3:
        k, t, inl = refit(keep)
    return k, t, inl


def _stats(inl) -> Dict:
    e = [x[2] for x in inl]
    return {"n": len(e), "rms_mm": round(math.sqrt(sum(v * v for v in e) / len(e)), 1), "max_mm": round(max(e), 1)}


def calibrate_via_overall(page_feats: List[Dict], page_scale: float,
                          overall_rects_pt: List[Pt], overall_scale: float,
                          revit_cols_mm: List[Pt], tol_mm: float = 120.0,
                          area_margin_mm: float = 5000.0) -> Dict:
    """
    page_feats: extract_pdf_column_features(trang zone) - point, Y xuống.
    overall_rects_pt: rect_centres(trang tổng).
    revit_cols_mm: tâm cột đã dựng trong Revit (mm, Y lên).
    Trả dict cùng dạng calibrate_from_columns (pdf_grid_pt1/2, revit_grid_pt1/2_mm, drawing_area_pt...).
    """
    mm_p, mm_o = PT_TO_MM * page_scale, PT_TO_MM * overall_scale
    base = {"method": "overall", "pdf_column_marks": len(page_feats), "overall_columns": len(overall_rects_pt),
            "revit_columns": len(revit_cols_mm)}
    src_p = [(f["x"] * mm_p, -f["y"] * mm_p) for f in page_feats]
    ov = [(x * mm_o, -y * mm_o) for x, y in overall_rects_pt]
    f1 = ransac_similarity(src_p, ov, tol=tol_mm, fixed_scale=1.0, snap_deg=0.0)
    if not f1 or len(f1[2]) < max(4, 0.6 * len(src_p)):
        base.update({"status": "error", "message": "Khong khop duoc cot trang zone voi trang tong ({}/{})."
                     .format(len(f1[2]) if f1 else 0, len(src_p))})
        return base
    # Revit -> trang tổng (Revit là tập nhỏ, đầy đủ tương ứng), rồi đảo ngược
    f2 = ransac_similarity(revit_cols_mm, ov, tol=tol_mm, fixed_scale=1.0)
    if not f2 or len(f2[2]) < max(4, 0.6 * len(revit_cols_mm)):
        base.update({"status": "error", "message": "Khong khop duoc cot da dung trong Revit voi trang tong ({}/{})."
                     .format(len(f2[2]) if f2 else 0, len(revit_cols_mm)), "page_to_overall": _stats(f1[2])})
        return base
    k1, t1, in1 = f1
    k2, t2, in2 = f2

    def to_revit(px, py):
        a = k1 * complex(px * mm_p, -py * mm_p) + t1        # -> trang tổng (mm)
        z = (a - t2) / k2                                   # -> Revit
        return [round(z.real, 1), round(z.imag, 1)]

    ids = [i for i, _, _ in in1]
    ia, ib = max(((a, b) for a in ids for b in ids if a < b),
                 key=lambda ab: math.hypot(src_p[ab[0]][0] - src_p[ab[1]][0], src_p[ab[0]][1] - src_p[ab[1]][1]))
    p1 = [round(page_feats[ia]["x"], 3), round(page_feats[ia]["y"], 3)]
    p2 = [round(page_feats[ib]["x"], 3), round(page_feats[ib]["y"], 3)]
    s1, s2 = _stats(in1), _stats(in2)
    kk = k1 / k2
    margin = area_margin_mm / mm_p
    xs = [page_feats[i]["x"] for i in ids]
    ys = [page_feats[i]["y"] for i in ids]
    ratio = len(in1) / float(len(src_p))
    base.update({
        "status": "success",
        "matched_columns": len(in1),
        "pdf_columns_with_common_mark": len(src_p),
        "match_ratio": round(ratio, 2),
        "pdf_grid_pt1": p1, "pdf_grid_pt2": p2,
        "revit_grid_pt1_mm": to_revit(*p1), "revit_grid_pt2_mm": to_revit(*p2),
        "rotation_deg": round(math.degrees(math.atan2(kk.imag, kk.real)), 3),
        "drawing_scale": "1:{}".format(int(round(page_scale))),
        "page_to_overall": s1, "overall_to_revit": s2,
        # cột trên trang zone KHÔNG khớp trang tổng (sai hình/nhãn, hoặc bản vẽ 2 trang khác nhau) -> báo kiểm tra
        "columns_not_on_overall": [{"mark": page_feats[i].get("mark"), "kind": page_feats[i].get("kind"),
                                    "b_mm": page_feats[i].get("b_mm"), "h_mm": page_feats[i].get("h_mm"),
                                    "pdf_pt": [round(page_feats[i]["x"], 1), round(page_feats[i]["y"], 1)]}
                                   for i in range(len(page_feats)) if i not in set(ids)],
        # sai số tổng ước lượng (2 bước độc lập)
        "residual_rms_mm": round(math.hypot(s1["rms_mm"], s2["rms_mm"]), 1),
        "residual_max_mm": round(s1["max_mm"] + s2["max_mm"], 1),
        "drawing_area_pt": [round(min(xs) - margin, 1), round(min(ys) - margin, 1),
                            round(max(xs) + margin, 1), round(max(ys) + margin, 1)],
    })
    return base


def find_overall_page(doc, sheet_number: str, title_reader) -> Optional[int]:
    """Số trang (1-based) của trang tổng ứng với sheet_number; None nếu không có."""
    target = OVERALL_SHEETS.get((sheet_number or "").upper())
    if not target:
        return None
    for i in range(len(doc)):
        tb = title_reader(doc[i]) or {}
        if (tb.get("sheet_number") or "").upper() == target:
            return i + 1
    return None
