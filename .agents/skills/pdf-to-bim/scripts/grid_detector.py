# -*- coding: utf-8 -*-
"""
grid_detector.py - Tự động dò Lưới trục (Grid) trên PDF Vector & khớp với Grid trong Revit
Phục vụ nguyên tắc "Grid-First Calibration" mà KHÔNG phải ước lượng tọa độ bằng mắt:
  1. detect_pdf_grids: Tìm vòng tròn đầu trục (Grid Bubble) + chữ ký hiệu bên trong (A, B, 1, 2...),
     rồi gom các đoạn thẳng (kể cả nét đứt bị vẽ thành nhiều đoạn) đi xuyên qua tâm bubble
     để dựng lại đường trục.
  2. grid_intersections: Tính giao điểm của các cặp trục không song song.
  3. calibrate_from_grids: Ghép giao điểm trùng tên giữa PDF và Revit, chọn cặp mốc tốt nhất
     (khoảng cách xa + sai số kiểm tra nhỏ nhất) để khởi tạo AffineTransformer.
Toạ độ PDF trả về theo đơn vị point, hệ trục của PyMuPDF (Y hướng xuống).
"""

import math
import re
from itertools import combinations
from typing import Dict, List, Optional, Tuple

try:
    from pdf_struct_parser import AffineTransformer
except ImportError:
    from .pdf_struct_parser import AffineTransformer

# Ký hiệu trục hợp lệ: A, AA, A1, A', 1, 12, 1A, 2'
_LABEL_RE = re.compile(r"^(?:[A-Z]{1,2}'?\d{0,2}'?|\d{1,3}[A-Z]?'?)$")

PT_TO_MM = 25.4 / 72.0


def normalize_grid_label(name: str) -> str:
    """Chuẩn hóa tên trục để so khớp PDF <-> Revit ('Grid A' -> 'A', ' a1 ' -> 'A1')."""
    s = (name or "").upper().strip()
    s = re.sub(r"^(GRID|GL|TRUC|TRỤC)[\s_\-]*", "", s)
    return re.sub(r"[\s_\-]", "", s)


def _circle_from_run(run) -> Optional[Tuple[float, float, float]]:
    """Một chuỗi item liên tiếp, khép kín, mọi điểm cách đều tâm -> hình tròn (cx, cy, r)."""
    pts = [run[0][1]] + [it[-1] for it in run]
    if math.hypot(pts[0].x - pts[-1].x, pts[0].y - pts[-1].y) > 0.05 * max(
            1e-6, max(math.hypot(p.x - pts[0].x, p.y - pts[0].y) for p in pts)):
        return None
    pts = pts[:-1]  # điểm cuối trùng điểm đầu -> bỏ để không lệch tâm
    if run[0][0] == "c":
        # Với Bezier lấy thêm điểm giữa cung để tâm chính xác hơn
        pts += [fitz_mid_bezier(it) for it in run]
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    dists = [math.hypot(p.x - cx, p.y - cy) for p in pts]
    r = sum(dists) / len(dists)
    if r <= 0 or max(abs(d - r) for d in dists) > 0.08 * r:
        return None
    return cx, cy, r


def fitz_mid_bezier(it):
    """Điểm t=0.5 của đường cong Bezier bậc 3 ('c', p0, c1, c2, p3)."""
    _, p0, c1, c2, p3 = it[:5]

    class _P:
        pass
    m = _P()
    m.x = 0.125 * (p0.x + 3 * c1.x + 3 * c2.x + p3.x)
    m.y = 0.125 * (p0.y + 3 * c1.y + 3 * c2.y + p3.y)
    return m


def _iter_circles(drawings):
    """
    Duyệt mọi path, tách thành các chuỗi item liền mạch cùng loại ('c' hoặc 'l') rồi kiểm tra
    chuỗi nào là hình tròn. PDF xuất từ CAD thường gộp nhiều hình vào chung 1 path nên KHÔNG
    dựa vào bbox của cả path.
    """
    for path in drawings:
        items = path.get("items", [])
        run = []

        def _flush(r):
            n = len(r)
            if not n:
                return None
            if (r[0][0] == "c" and 4 <= n <= 8) or (r[0][0] == "l" and 12 <= n <= 72):
                return _circle_from_run(r)
            return None

        for it in items:
            kind = it[0]
            connected = run and run[-1][0] == kind and \
                math.hypot(run[-1][-1].x - it[1].x, run[-1][-1].y - it[1].y) < 1e-3
            if kind in ("c", "l") and (not run or connected):
                run.append(it)
                continue
            c = _flush(run)
            if c:
                yield c
            run = [it] if kind in ("c", "l") else []
        c = _flush(run)
        if c:
            yield c


def detect_pdf_grids(page, min_bubble_pt: float = 5.0, max_bubble_pt: float = 60.0,
                     min_length_ratio: float = 8.0) -> List[Dict]:
    """
    Trả về danh sách trục: [{"label", "p1": {x,y}, "p2": {x,y}, "angle_deg", "bubble_r_pt"}]
    (đơn vị point PDF). min_length_ratio: chiều dài trục tối thiểu = ratio * bán kính bubble.
    """
    drawings = page.get_drawings()

    # 1. Text spans
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip().upper()
                if txt and _LABEL_RE.match(txt):
                    b = span["bbox"]
                    spans.append((txt, (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0))

    # 2. Bubble = vòng tròn có chữ ký hiệu trục nằm bên trong
    bubbles = []
    for cx, cy, r in _iter_circles(drawings):
        if not (min_bubble_pt <= 2 * r <= max_bubble_pt):
            continue
        best = None
        for txt, tx, ty in spans:
            d = math.hypot(tx - cx, ty - cy)
            if d <= 0.8 * r and (best is None or d < best[1]):
                best = (txt, d)
        if best and not any(abs(b[1] - cx) < 0.5 and abs(b[2] - cy) < 0.5 for b in bubbles):
            bubbles.append((best[0], cx, cy, r))

    # 3. Toàn bộ đoạn thẳng trên trang
    segs = []
    for path in drawings:
        for it in path.get("items", []):
            if it[0] == "l":
                p, q = it[1], it[2]
                L = math.hypot(q.x - p.x, q.y - p.y)
                if L >= 0.5:
                    segs.append((p.x, p.y, q.x, q.y, L))

    # 4. Với mỗi bubble: gom các đoạn nằm trên đường thẳng đi qua tâm bubble
    found = {}
    for label, cx, cy, r in bubbles:
        tol = max(0.15 * r, 0.4)
        groups = {}
        for x1, y1, x2, y2, L in segs:
            # Bỏ các nét nằm trọn trong bubble (vd: gạch ngang trong ký hiệu)
            if math.hypot(x1 - cx, y1 - cy) <= 1.05 * r and math.hypot(x2 - cx, y2 - cy) <= 1.05 * r:
                continue
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            if abs((cx - x1) * uy - (cy - y1) * ux) > tol:
                continue
            ang = math.degrees(math.atan2(uy, ux)) % 180.0
            key = int(round(ang)) % 180
            groups.setdefault(key, []).append((x1, y1, x2, y2, L))
        if not groups:
            continue
        # Gộp các bin góc kề nhau (vd 89° và 90°)
        best_key = max(groups, key=lambda k: sum(s[4] for kk in (k - 1, k, (k + 1) % 180)
                                                 for s in groups.get(kk % 180, [])))
        members = [s for kk in (best_key - 1, best_key, best_key + 1) for s in groups.get(kk % 180, [])]
        total = sum(s[4] for s in members)
        if total < min_length_ratio * r:
            continue

        ang = math.radians(best_key)
        ux, uy = math.cos(ang), math.sin(ang)
        ts = []
        for x1, y1, x2, y2, _ in members:
            ts.append((x1 - cx) * ux + (y1 - cy) * uy)
            ts.append((x2 - cx) * ux + (y2 - cy) * uy)
        # Đầu trục bắt đầu từ tâm bubble
        tmin, tmax = min(ts + [0.0]), max(ts + [0.0])
        grid = {
            "label": label,
            "p1": {"x": round(cx + tmin * ux, 2), "y": round(cy + tmin * uy, 2)},
            "p2": {"x": round(cx + tmax * ux, 2), "y": round(cy + tmax * uy, 2)},
            "angle_deg": float(best_key),
            "bubble_r_pt": round(r, 2),
            "_len": tmax - tmin,
        }
        # Cùng ký hiệu xuất hiện ở 2 đầu trục -> giữ đường dài nhất
        if label not in found or grid["_len"] > found[label]["_len"]:
            found[label] = grid

    result = []
    for g in found.values():
        g.pop("_len", None)
        result.append(g)
    return sorted(result, key=lambda g: g["label"])


def _intersect(a1, a2, b1, b2, min_sin: float = 0.2):
    """Giao điểm 2 đường thẳng vô hạn (a1-a2) và (b1-b2); None nếu gần song song."""
    dax, day = a2[0] - a1[0], a2[1] - a1[1]
    dbx, dby = b2[0] - b1[0], b2[1] - b1[1]
    la, lb = math.hypot(dax, day), math.hypot(dbx, dby)
    if la == 0 or lb == 0:
        return None
    cross = dax * dby - day * dbx
    if abs(cross) / (la * lb) < min_sin:
        return None
    t = ((b1[0] - a1[0]) * dby - (b1[1] - a1[1]) * dbx) / cross
    return (a1[0] + t * dax, a1[1] + t * day)


def grid_intersections(grids: List[Dict], start_key: str = "p1", end_key: str = "p2") -> Dict[str, Tuple[float, float]]:
    """{'A-1': (x, y), ...} cho mọi cặp trục không song song. Key được sắp xếp theo tên chuẩn hóa."""
    norm = [(normalize_grid_label(g["label"]), g) for g in grids]
    out = {}
    for (na, ga), (nb, gb) in combinations(norm, 2):
        if not na or not nb or na == nb:
            continue
        p = _intersect((ga[start_key]["x"], ga[start_key]["y"]), (ga[end_key]["x"], ga[end_key]["y"]),
                       (gb[start_key]["x"], gb[start_key]["y"]), (gb[end_key]["x"], gb[end_key]["y"]))
        if p:
            key = "-".join(sorted([na, nb]))
            out[key] = p
    return out


def calibrate_from_grids(pdf_grids: List[Dict], revit_grids: List[Dict],
                         max_candidates: int = 40) -> Dict:
    """
    pdf_grids: kết quả detect_pdf_grids (point, Y xuống).
    revit_grids: [{"name", "start_mm": {x,y}, "end_mm": {x,y}}] lấy từ Revit (mm, Y lên).
    Trả về 4 toạ độ mốc cho AffineTransformer + sai số kiểm tra trên mọi giao điểm chung.
    """
    rvt = [{"label": g["name"], "p1": g["start_mm"], "p2": g["end_mm"]} for g in revit_grids]
    pdf_x = grid_intersections(pdf_grids)
    rvt_x = grid_intersections(rvt)

    pdf_labels = {normalize_grid_label(g["label"]) for g in pdf_grids}
    rvt_labels = {normalize_grid_label(g["label"]) for g in rvt}
    common = sorted(set(pdf_x) & set(rvt_x))

    base = {
        "pdf_grid_labels": sorted(pdf_labels),
        "revit_grid_labels": sorted(rvt_labels),
        "only_in_pdf": sorted(pdf_labels - rvt_labels),
        "only_in_revit": sorted(rvt_labels - pdf_labels),
        "common_intersections": len(common),
    }
    if len(common) < 2:
        base.update({"status": "error",
                     "message": "Can it nhat 2 giao diem truc trung ten giua PDF va Revit."})
        return base

    # Ưu tiên các giao điểm nằm xa nhau (ổn định hình học tốt hơn)
    cand = sorted(combinations(common, 2),
                  key=lambda ab: -math.hypot(pdf_x[ab[0]][0] - pdf_x[ab[1]][0],
                                             pdf_x[ab[0]][1] - pdf_x[ab[1]][1]))[:max_candidates]

    best = None
    for a, b in cand:
        try:
            tr = AffineTransformer(pdf_x[a], pdf_x[b], rvt_x[a], rvt_x[b])
        except Exception:
            continue
        errs = []
        for k in common:
            p = tr.to_revit_mm(*pdf_x[k])
            errs.append((math.hypot(p["x"] - rvt_x[k][0], p["y"] - rvt_x[k][1]), k))
        errs.sort()
        median = errs[len(errs) // 2][0]
        if best is None or median < best["median"]:
            best = {"a": a, "b": b, "tr": tr, "errs": errs, "median": median}

    if best is None:
        base.update({"status": "error", "message": "Khong dung duoc AffineTransformer tu cac giao diem chung."})
        return base

    errs = best["errs"]
    rms = math.sqrt(sum(e * e for e, _ in errs) / len(errs))
    tr = best["tr"]
    scale_ratio = tr.scale / PT_TO_MM  # mm thuc / mm giay -> ti le ban ve 1:N
    a, b = best["a"], best["b"]
    base.update({
        "status": "success",
        "anchors": [a, b],
        "pdf_grid_pt1": [round(pdf_x[a][0], 3), round(pdf_x[a][1], 3)],
        "pdf_grid_pt2": [round(pdf_x[b][0], 3), round(pdf_x[b][1], 3)],
        "revit_grid_pt1_mm": [round(rvt_x[a][0], 1), round(rvt_x[a][1], 1)],
        "revit_grid_pt2_mm": [round(rvt_x[b][0], 1), round(rvt_x[b][1], 1)],
        "drawing_scale": "1:{}".format(int(round(scale_ratio))),
        "rotation_deg": round(math.degrees(tr.theta), 3),
        "residual_rms_mm": round(rms, 1),
        "residual_max_mm": round(errs[-1][0], 1),
        "worst_intersections": [{"grid": k, "error_mm": round(e, 1)} for e, k in errs[-5:][::-1]],
        # Khung mặt bằng = vùng bao các đường trục (bubble nằm ngoài mặt bằng)
        "drawing_area_pt": [round(min(g[k]["x"] for g in pdf_grids for k in ("p1", "p2")), 1),
                            round(min(g[k]["y"] for g in pdf_grids for k in ("p1", "p2")), 1),
                            round(max(g[k]["x"] for g in pdf_grids for k in ("p1", "p2")), 1),
                            round(max(g[k]["y"] for g in pdf_grids for k in ("p1", "p2")), 1)],
    })
    return base


def get_title_block_info(page) -> Dict:
    """
    Đọc Số hiệu bản vẽ, Zone và Tên bản vẽ từ khung tên:
      - Số hiệu: span 'S###' gần nhãn 'Drawing No' đứng riêng nhất (không lấy số trong câu ghi chú
        'refer ... on drawing no S203'); không có nhãn thì lấy 'S###' cỡ chữ lớn nhất.
      - Tên bản vẽ: dòng chứa 'PLAN' có cỡ chữ lớn nhất, bỏ các câu dẫn 'FOR CONTINUATION/REFER'.
    """
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"].strip()
                if t:
                    b = span["bbox"]
                    spans.append((t, span["size"], (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0))

    sheets = [sp for sp in spans if re.fullmatch(r"S\d{3}", sp[0].upper())]
    labels = [sp for sp in spans if re.fullmatch(r"DRAWING\s*(NO|NUMBER)\.?:?", sp[0].upper())]
    sheet = None
    if sheets and labels:
        sheet = min(sheets, key=lambda sp: min(math.hypot(sp[2] - l[2], sp[3] - l[3]) for l in labels))[0]
    elif sheets:
        sheet = max(sheets, key=lambda sp: sp[1])[0]

    titles = [sp for sp in spans if "PLAN" in sp[0].upper()
              and not re.match(r"^(FOR CONTINUATION|REFER|SEE )", sp[0].upper())]
    title = max(titles, key=lambda sp: sp[1])[0].strip() if titles else None
    zone = re.search(r"ZONE\s+([A-Z])\b", (title or "").upper())
    return {
        "sheet_number": sheet.upper() if sheet else None,
        "zone": zone.group(1) if zone else None,
        "title": title,
    }
