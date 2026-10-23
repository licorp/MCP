# -*- coding: utf-8 -*-
"""
label_column_finder.py - Cột theo NHÃN + BẢNG CỘT (có tag mới có cấu kiện).

1. read_column_schedule(doc): đọc 'COLUMN SCHEDULE' (vd S150) trong cả bộ PDF -> {mark: {shape, b, h | d}}.
2. size_matches(col, sched): kích thước cột bóc tách có khớp bảng cột không (loại hình nhận nhầm, vd vòng
   tròn ghi chiều dày sàn "250" bị nhận thành cột Ø800).
3. find_shape_for_label(...): nhãn có hậu tố (o) mà chưa có cột -> tìm ĐÚNG hình vector (tròn / chữ nhật,
   có thể xoay) cùng kích thước bảng cột, nằm sát nhãn. Tọa độ lấy từ vector, không ước lượng.
"""
import math
import re
from typing import Dict, List, Optional

_MARK = re.compile(r"^C{1,2}\d+[A-Z]?$")
_DIA = re.compile(r"^(\d{3,4})\s*DIA$", re.I)
_RECT = re.compile(r"^(\d{3,4})\s*[xX]\s*(\d{3,4})$")

_CACHE: Dict[str, Dict] = {}


def read_column_schedule(doc) -> Dict[str, Dict]:
    """{'CC1B': {'shape': 'round', 'd': 400}, 'CC6': {'shape': 'rect', 'b': 500, 'h': 200}, ...}"""
    key = getattr(doc, "name", "") or str(id(doc))
    if key in _CACHE:
        return _CACHE[key]
    out: Dict[str, Dict] = {}
    for page in doc:
        text = page.get_text()
        if "COLUMN SCHEDULE" not in text.upper():
            continue
        toks = [t.strip() for t in text.splitlines() if t.strip()]
        for i, t in enumerate(toks[:-1]):
            if not _MARK.match(t) or t in out:
                continue
            nxt = toks[i + 1].replace(" ", "")
            m = _DIA.match(nxt)
            if m:
                out[t] = {"shape": "round", "d": int(m.group(1))}
                continue
            m = _RECT.match(nxt)
            if m:
                out[t] = {"shape": "rect", "b": int(m.group(1)), "h": int(m.group(2))}
    _CACHE[key] = out
    return out


def size_matches(col: Dict, sched: Dict[str, Dict], tol: float = 0.2) -> Optional[bool]:
    """True/False theo bảng cột; None nếu mã không có trong bảng."""
    s = sched.get((col.get("mark") or "").upper())
    if not s:
        return None
    if s["shape"] == "round":
        d = col.get("diameter_mm") or (col.get("b_mm") if col.get("shape") == "round" else None)
        return bool(d) and col.get("shape") == "round" and abs(d - s["d"]) <= tol * s["d"]
    if col.get("shape") == "round":
        return False
    a, b = sorted([col.get("b_mm", 0), col.get("h_mm", 0)])
    x, y = sorted([s["b"], s["h"]])
    return abs(a - x) <= tol * x and abs(b - y) <= tol * y


def _path_points(d) -> List[tuple]:
    pts = []
    for it in d.get("items", []):
        if it[0] == "l":
            pts += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif it[0] == "re":
            r = it[1]
            pts += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
        elif it[0] == "qu":
            q = it[1]
            pts += [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
        elif it[0] == "c":
            pts += [(it[1].x, it[1].y), (it[4].x, it[4].y)]
    return pts


def _min_area_rect(pts):
    """Hình chữ nhật bao nhỏ nhất (thử theo hướng từng cạnh): (cx, cy, w, h, angle_deg) - hệ trang Y xuống."""
    best = None
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if math.hypot(x1 - x0, y1 - y0) < 1e-6:
            continue
        a = math.atan2(y1 - y0, x1 - x0)
        c, s = math.cos(a), math.sin(a)
        us = [x * c + y * s for x, y in pts]
        vs = [-x * s + y * c for x, y in pts]
        w, h = max(us) - min(us), max(vs) - min(vs)
        if best is None or w * h < best[0]:
            u0, v0 = (max(us) + min(us)) / 2.0, (max(vs) + min(vs)) / 2.0
            best = (w * h, u0 * c - v0 * s, u0 * s + v0 * c, w, h, math.degrees(a))
    if best is None:
        return None
    _, cx, cy, w, h, ang = best
    k = int(round(ang / 90.0))
    if k % 2:                                    # cạnh đo nằm theo phương dọc trang -> đổi w/h
        w, h = h, w
    ang = ang - 90.0 * k                         # góc lẻ trong [-45, 45]: w theo phương ngang trang
    return cx, cy, w, h, ang


def find_shape_for_label(page, label: Dict, sched_item: Dict, mm_per_pt: float,
                         max_dist_mm: float = 1500.0, tol: float = 0.12, drawings=None,
                         taken_pt: Optional[List[tuple]] = None) -> Optional[Dict]:
    """
    Hình cột gần nhãn nhất có kích thước khớp bảng cột (±tol). Trả feat cho column_to_revit:
    {x, y, b_mm, h_mm, kind: 'circle'|'rect', angle_deg, mark, dist_mm} hoặc None.
    taken_pt: tâm (pt) các cột đã có -> không lấy lại hình đó.
    """
    lx, ly = label["x"], label["y"]
    rad = max_dist_mm / mm_per_pt
    best = None
    for d in (drawings if drawings is not None else page.get_drawings()):
        r = d.get("rect")
        if r is None or r.x1 < lx - rad or r.x0 > lx + rad or r.y1 < ly - rad or r.y0 > ly + rad:
            continue
        pts = _path_points(d)
        if len(pts) < 3:
            continue
        has_curve = any(it[0] == "c" for it in d.get("items", []))
        if sched_item["shape"] == "round":
            if not has_curve:
                continue
            w, h = (r.x1 - r.x0) * mm_per_pt, (r.y1 - r.y0) * mm_per_pt
            dia = (w + h) / 2.0
            if abs(w - h) > 0.1 * dia or abs(dia - sched_item["d"]) > tol * sched_item["d"]:
                continue
            cx, cy, ang = (r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0, None
            feat = {"kind": "circle", "b_mm": float(sched_item["d"]), "h_mm": float(sched_item["d"])}
        else:
            if has_curve:
                continue
            mr = _min_area_rect(pts)
            if not mr:
                continue
            cx, cy, w, h, ang = mr
            a, b = sorted([w * mm_per_pt, h * mm_per_pt])
            x, y = sorted([sched_item["b"], sched_item["h"]])
            if abs(a - x) > tol * x or abs(b - y) > tol * y:
                continue
            # b_mm theo phương 'ngang' của hình (sau khi bỏ góc lẻ), h_mm theo phương 'dọc'
            feat = {"kind": "rect", "b_mm": float(w * mm_per_pt), "h_mm": float(h * mm_per_pt)}
            # làm tròn về kích thước bảng cột theo đúng hướng
            if abs(feat["b_mm"] - sched_item["b"]) <= abs(feat["b_mm"] - sched_item["h"]):
                feat["b_mm"], feat["h_mm"] = float(sched_item["b"]), float(sched_item["h"])
            else:
                feat["b_mm"], feat["h_mm"] = float(sched_item["h"]), float(sched_item["b"])
        if taken_pt and any(math.hypot(cx - tx, cy - ty) * mm_per_pt < 60.0 for tx, ty in taken_pt):
            continue
        dist = math.hypot(cx - lx, cy - ly) * mm_per_pt
        if dist > max_dist_mm:
            continue
        if best is None or dist < best["dist_mm"]:
            feat.update({"x": cx, "y": cy, "mark": label["mark"], "dist_mm": round(dist, 1),
                         "angle_deg": round(ang, 3) if ang is not None else None})
            best = feat
    if best is None:
        # Hình vẽ bằng nhiều đoạn thẳng RỜI (mỗi đoạn 1 path) -> dò theo kích thước đã biết
        segs = _segments_near(drawings if drawings is not None else page.get_drawings(), lx, ly, rad)
        if sched_item["shape"] == "round":
            best = _circle_from_segments(segs, sched_item["d"] / 2.0 / mm_per_pt, lx, ly, rad)
            if best:
                best.update({"kind": "circle", "b_mm": float(sched_item["d"]), "h_mm": float(sched_item["d"])})
        else:
            best = _rect_from_segments(segs, sched_item["b"] / mm_per_pt, sched_item["h"] / mm_per_pt, tol, lx, ly, rad)
        if best and best.get("kind") == "rect":
            bw = best.pop("_w_pt") * mm_per_pt
            best.pop("_h_pt", None)
            # b_mm theo phương ngang trang: gán đúng cạnh bảng cột gần với cạnh đo được
            if abs(bw - sched_item["b"]) <= abs(bw - sched_item["h"]):
                best["b_mm"], best["h_mm"] = float(sched_item["b"]), float(sched_item["h"])
            else:
                best["b_mm"], best["h_mm"] = float(sched_item["h"]), float(sched_item["b"])
        if best:
            if taken_pt and any(math.hypot(best["x"] - tx, best["y"] - ty) * mm_per_pt < 60.0 for tx, ty in taken_pt):
                return None
            best.update({"mark": label["mark"],
                         "dist_mm": round(math.hypot(best["x"] - lx, best["y"] - ly) * mm_per_pt, 1)})
    return best


def _segments_near(drawings, lx, ly, rad, min_len: float = 0.3):
    """Đoạn thẳng nét LIỀN (không nét đứt) trong cửa sổ quanh nhãn: [((x0,y0),(x1,y1))] (pt)."""
    out = []
    for d in drawings:
        r = d.get("rect")
        if r is None or r.x1 < lx - rad or r.x0 > lx + rad or r.y1 < ly - rad or r.y0 > ly + rad:
            continue
        dash = d.get("dashes")
        if dash and dash.strip() not in ("[] 0", "[]0", ""):
            continue
        for it in d.get("items", []):
            if it[0] == "l":
                a, b = (it[1].x, it[1].y), (it[2].x, it[2].y)
                if math.hypot(b[0] - a[0], b[1] - a[1]) >= min_len:
                    out.append((a, b))
            elif it[0] == "re":
                q = it[1]
                c = [(q.x0, q.y0), (q.x1, q.y0), (q.x1, q.y1), (q.x0, q.y1)]
                out += [(c[i], c[(i + 1) % 4]) for i in range(4)]
    return out


def _circle_from_segments(segs, R, lx, ly, rad, step: float = 0.1, tol: float = 0.35,
                          min_pts: int = 12, min_cover_deg: float = 270.0):
    """Tâm đường tròn bán kính R (pt) khớp nhiều đầu đoạn thẳng nhất (đoạn ngắn hơn R)."""
    pts = []
    for a, b in segs:
        if math.hypot(b[0] - a[0], b[1] - a[1]) <= 1.2 * R:
            pts += [a, b]
    if len(pts) < min_pts:
        return None
    # ứng viên tâm: chiếu vuông góc từ trung điểm mỗi đoạn ngắn một khoảng R (2 phía)
    cands = []
    for a, b in segs:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-6 or L > 1.2 * R:
            continue
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        h = math.sqrt(max(0.0, R * R - (L / 2.0) ** 2))
        cands += [(mx + nx * h, my + ny * h), (mx - nx * h, my - ny * h)]
    best = None
    seen = set()
    for cx, cy in cands:
        key = (round(cx / step), round(cy / step))
        if key in seen or math.hypot(cx - lx, cy - ly) > rad:
            continue
        seen.add(key)
        on = [math.atan2(y - cy, x - cx) for x, y in pts if abs(math.hypot(x - cx, y - cy) - R) <= tol]
        if len(on) < min_pts:
            continue
        angs = sorted(math.degrees(a) % 360.0 for a in on)
        gaps = [angs[i + 1] - angs[i] for i in range(len(angs) - 1)] + [360.0 - angs[-1] + angs[0]]
        cover = 360.0 - max(gaps)
        if cover < min_cover_deg:
            continue
        score = (len(on), cover)
        if best is None or score > best[0]:
            best = (score, cx, cy)
    if not best:
        return None
    # tinh chỉnh tâm: trung bình các tâm ứng viên gần tâm tốt nhất
    _, cx, cy = best
    near = [(x, y) for x, y in cands if math.hypot(x - cx, y - cy) <= 2 * tol]
    cx, cy = sum(x for x, _ in near) / len(near), sum(y for _, y in near) / len(near)
    return {"x": cx, "y": cy, "angle_deg": None, "support_pts": best[0][0], "cover_deg": round(best[0][1])}


def _merge_collinear(segs, ang_tol: float = 0.5, off_tol: float = 0.15, gap: float = 0.4):
    """Nối các đoạn thẳng hàng (góc < ang_tol°, lệch < off_tol pt, hở < gap pt)."""
    items = []
    for a, b in segs:
        ang = math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi
        items.append([ang, a, b])
    used = [False] * len(items)
    out = []
    for i, (ang, a, b) in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        ux, uy = math.cos(ang), math.sin(ang)
        off = -a[0] * uy + a[1] * ux
        t = sorted([a[0] * ux + a[1] * uy, b[0] * ux + b[1] * uy])
        lo, hi = t
        changed = True
        while changed:
            changed = False
            for j, (ang2, a2, b2) in enumerate(items):
                if used[j]:
                    continue
                da = abs(ang2 - ang)
                if min(da, math.pi - da) > math.radians(ang_tol):
                    continue
                if abs(-a2[0] * uy + a2[1] * ux - off) > off_tol:
                    continue
                t2 = sorted([a2[0] * ux + a2[1] * uy, b2[0] * ux + b2[1] * uy])
                if t2[0] <= hi + gap and t2[1] >= lo - gap:
                    lo, hi = min(lo, t2[0]), max(hi, t2[1])
                    used[j] = True
                    changed = True
        out.append((ang, off, lo, hi))
    return out


def _rect_from_segments(segs, B, H, tol, lx, ly, rad):
    """Cặp cạnh song song dài ~B, cách nhau ~H (hoặc ngược lại) -> hình chữ nhật (pt). Gần nhãn nhất."""
    lines = _merge_collinear(segs)
    best = None
    for side, other in ((B, H), (H, B)):
        long_ = [l for l in lines if abs((l[3] - l[2]) - side) <= tol * side]
        for i in range(len(long_)):
            for j in range(i + 1, len(long_)):
                a1, o1, lo1, hi1 = long_[i]
                a2, o2, lo2, hi2 = long_[j]
                da = abs(a1 - a2)
                if min(da, math.pi - da) > math.radians(0.5):
                    continue
                if abs(abs(o1 - o2) - other) > tol * other:
                    continue
                ov = min(hi1, hi2) - max(lo1, lo2)
                if ov < 0.85 * side:
                    continue
                ux, uy = math.cos(a1), math.sin(a1)
                tm = (max(lo1, lo2) + min(hi1, hi2)) / 2.0
                om = (o1 + o2) / 2.0
                cx, cy = tm * ux - om * uy, tm * uy + om * ux
                d = math.hypot(cx - lx, cy - ly)
                if d > rad:
                    continue
                deg = math.degrees(a1)
                k = int(round(deg / 90.0))
                rest = deg - 90.0 * k
                # cạnh dài theo phương ngang trang (k chẵn) -> b_mm = side
                if k % 2 == 0:
                    bw, hh = side, other
                else:
                    bw, hh = other, side
                if best is None or d < best[0]:
                    best = (d, {"x": cx, "y": cy, "kind": "rect", "angle_deg": round(rest, 3),
                                "_w_pt": bw, "_h_pt": hh})
    if not best:
        return None
    f = best[1]
    return f
