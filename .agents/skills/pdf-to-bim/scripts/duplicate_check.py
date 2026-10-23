# -*- coding: utf-8 -*-
"""
duplicate_check.py - Kiểm tra cấu kiện TRÙNG LẶP (bắt buộc sau mỗi lần dựng).

Phần tử = {"id", "cat", "type", "tag", "bb": [xmin, ymin, xmax, ymax, zmin, zmax]} (mm).
  * TRÙNG (duplicate): cùng category, mặt bằng chồng >= min_ratio diện tích phần tử nhỏ hơn, cao độ
    chồng nhau, và kích thước tương đương (diện tích nhỏ/lớn >= size_ratio) -> 2 cấu kiện cho 1 vị trí.
    Cột tầng trên đứng trên cột tầng dưới KHÔNG trùng (cao độ không chồng).
  * CHỒNG LẤN (overlap): chồng lớn nhưng khác loại/khác kích thước (vd móng đơn cắt móng băng, móng gộp)
    -> chỉ để tham khảo, thường đúng theo bản vẽ.
"""

import math
from itertools import combinations
from typing import Dict, List, Optional


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _plan_inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _z_overlap(a, b):
    if len(a) < 6 or len(b) < 6:
        return True
    return min(a[5], b[5]) - max(a[4], b[4]) > z_min_overlap_mm


z_min_overlap_mm = 50.0


_KIND_ALIAS = {"PF": "PAD", "SF": "STRIP"}


def _kind(e) -> Optional[str]:
    """Loại cấu kiện: 'kind' (sắp dựng), field 3 của tag PDF2BIM, hoặc chữ đầu tên loại (PF -> PAD, SF -> STRIP)."""
    if e.get("kind"):
        return e["kind"]
    tag = e.get("tag") or ""
    if tag.startswith("PDF2BIM|") and len(tag.split("|")) > 2:
        return tag.split("|")[2]
    t = (e.get("type") or "").strip().upper()
    lead = "".join(ch for ch in t[:3] if ch.isalpha())
    return _KIND_ALIAS.get(lead)


def collinear_cover(la, lb, tol_mm: float, max_deg: float = 2.0) -> Optional[float]:
    """
    2 đường tim [x0, y0, x1, y1] (mm): song song (< max_deg), đoạn ngắn nằm trên tuyến đoạn dài (cách < tol_mm)
    -> tỉ lệ chiều dài đoạn ngắn bị phủ; không cùng tuyến -> None.
    """
    def ln(l):
        return math.hypot(l[2] - l[0], l[3] - l[1])
    s, g = (la, lb) if ln(la) <= ln(lb) else (lb, la)
    Ls, Lg = ln(s), ln(g)
    if Ls < 1 or Lg < 1:
        return None
    ux, uy = (g[2] - g[0]) / Lg, (g[3] - g[1]) / Lg
    vx, vy = (s[2] - s[0]) / Ls, (s[3] - s[1]) / Ls
    if abs(ux * vy - uy * vx) > math.sin(math.radians(max_deg)):
        return None
    for px, py in ((s[0], s[1]), (s[2], s[3])):
        if abs((px - g[0]) * uy - (py - g[1]) * ux) > tol_mm:
            return None
    t0 = (s[0] - g[0]) * ux + (s[1] - g[1]) * uy
    t1 = (s[2] - g[0]) * ux + (s[3] - g[1]) * uy
    a0, a1 = min(t0, t1), max(t0, t1)
    return max(0.0, min(a1, Lg) - max(a0, 0.0)) / Ls


def classify_pair(a: Dict, b: Dict, min_ratio: float = 0.9, size_ratio: float = 0.8,
                  overlap_ratio: float = 0.5) -> Optional[Dict]:
    if not (a.get("bb") and b.get("bb")) or not _z_overlap(a["bb"], b["bb"]):
        return None
    same_cat = a.get("cat") == b.get("cat")
    # Tường / dầm: so theo ĐƯỜNG TIM (hình bao của cấu kiện xiên rất lớn -> dễ báo nhầm). Đoạn ngắn nằm
    # gọn trên tuyến đoạn dài (dù dài ngắn khác nhau) = TRÙNG.
    if same_cat and a.get("line") and b.get("line"):
        tol = max(a.get("width") or 200.0, b.get("width") or 200.0) / 2.0
        cov = collinear_cover(a["line"], b["line"], tol)
        if cov is not None and cov >= min_ratio:
            return {"kind": "duplicate", "overlap": round(cov, 2), "a": _brief(a), "b": _brief(b)}
        if cov is not None and cov >= overlap_ratio:
            return {"kind": "overlap", "overlap": round(cov, 2), "a": _brief(a), "b": _brief(b)}
        return None
    # Sàn có hình chiếu thật (poly): so phần giao THẬT, không so hình bao (dải 370 nằm trong hình bao của tấm 240
    # hình vành khăn bao quanh nó bị báo nhầm 'overlap 1.0' ở 250793 L1).
    if a.get("cat") == "Floors" and b.get("cat") == "Floors" and a.get("poly") and b.get("poly"):
        pa, pb = _poly(a["poly"]), _poly(b["poly"])
        if pa is not None and pb is not None:
            small, big = min(pa.area, pb.area), max(pa.area, pb.area)
            if small <= 0:
                return None
            r = pa.intersection(pb).area / small
            if r < 0.01:
                return None
            kind = "duplicate" if r >= min_ratio else ("overlap" if r >= overlap_ratio else None)
            if kind is None:
                return None
            return {"kind": kind, "overlap": round(r, 2), "a": _brief(a), "b": _brief(b)}
    inter = _plan_inter(a["bb"], b["bb"])
    if not inter:
        return None
    aa, ab = _area(a["bb"]), _area(b["bb"])
    small, big = min(aa, ab), max(aa, ab)
    if small <= 0:
        return None
    r = inter / small
    # Móng băng nằm gọn trong móng băng khác (cùng loại STRIP) = TRÙNG dù kích thước khác (vẽ lại ở 2 trang)
    same_strip = _kind(a) == "STRIP" and _kind(b) == "STRIP"
    # Sàn nằm gọn trong sàn khác cùng cao độ = TRÙNG dù kích thước khác (vd sàn dựng tay nhỏ nằm trong sàn
    # dựng theo bản vẽ) - 2 tấm sàn không thể chiếm cùng chỗ.
    same_slab = a.get("cat") == "Floors" and b.get("cat") == "Floors"
    if same_cat and r >= min_ratio and (small / big >= size_ratio or same_strip or same_slab):
        kind = "duplicate"
    elif r >= overlap_ratio:
        kind = "overlap"
    else:
        return None
    return {"kind": kind, "overlap": round(r, 2), "a": _brief(a), "b": _brief(b)}


def _poly(rings):
    """[[ [x, y], ... ] (vòng ngoài), [lỗ], ...] (mm) -> shapely Polygon hợp lệ; None nếu không dựng được."""
    try:
        from shapely.geometry import Polygon
    except Exception:  # pragma: no cover
        return None
    try:
        rs = [[tuple(p[:2]) for p in r] for r in rings if len(r) >= 3]
        if not rs:
            return None
        rs.sort(key=lambda r: -abs(Polygon(r).area))
        g = Polygon(rs[0], rs[1:])
        return g if g.is_valid else g.buffer(0)
    except Exception:
        return None


def _brief(e):
    return {"id": e.get("id"), "cat": e.get("cat"), "type": e.get("type"), "tag": e.get("tag") or ""}


def find_duplicates(elements: List[Dict], **kw) -> Dict:
    """Quét mọi cặp phần tử (lưới ô 5 m để nhanh). Trả {"duplicates": [...], "overlaps": [...]}."""
    cell = 5000.0
    grid = {}
    for i, e in enumerate(elements):
        b = e.get("bb")
        if not b:
            continue
        for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
            for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    seen, dups, ovs = set(), [], []
    for idxs in grid.values():
        for i, j in combinations(idxs, 2):
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            res = classify_pair(elements[key[0]], elements[key[1]], **kw)
            if res:
                (dups if res["kind"] == "duplicate" else ovs).append(res)
    dups.sort(key=lambda r: -r["overlap"])
    ovs.sort(key=lambda r: -r["overlap"])
    return {"duplicates": dups, "overlaps": ovs}


def planned_bbox(kind: str, item: Dict, level_mm: float, top_mm: Optional[float],
                 footing_top_offset_mm: float = -150.0) -> Optional[List[float]]:
    """Hình bao (mm) của cấu kiện SẮP dựng, để so trùng với phần đang có trước khi ghi."""
    top = top_mm if top_mm is not None else level_mm + 3000.0
    if kind == "COL":
        cx, cy = item["center"]["x"], item["center"]["y"]
        b = item.get("diameter_mm") or item.get("b_mm", 0)
        h = item.get("diameter_mm") or item.get("h_mm", 0)
        return [cx - b / 2.0, cy - h / 2.0, cx + b / 2.0, cy + h / 2.0, level_mm, top]
    if kind == "PAD":
        cx, cy = item["center"]["x"], item["center"]["y"]
        z1 = level_mm + footing_top_offset_mm
        hx, hy = item["x_mm"] / 2.0, item["y_mm"] / 2.0
        r = math.radians(item.get("rotation_deg") or 0.0)
        ex = abs(hx * math.cos(r)) + abs(hy * math.sin(r))   # nua hinh bao cua hinh chu nhat xoay
        ey = abs(hx * math.sin(r)) + abs(hy * math.cos(r))
        return [cx - ex, cy - ey, cx + ex, cy + ey, z1 - (item.get("thickness_mm") or 500), z1]
    if kind == "STRIP" and item.get("outer_loop_mm"):
        xs = [q["x"] for q in item["outer_loop_mm"]]
        ys = [q["y"] for q in item["outer_loop_mm"]]
        z1 = level_mm + footing_top_offset_mm
        return [min(xs), min(ys), max(xs), max(ys), z1 - (item.get("thickness_mm") or 500), z1]
    if kind == "SLAB" and item.get("outer_loop_mm"):        # san: hinh bao vien ngoai, day tu dinh xuong
        xs = [q["x"] for q in item["outer_loop_mm"]]
        ys = [q["y"] for q in item["outer_loop_mm"]]
        z1 = level_mm + (item.get("z_offset_mm") or 0.0)
        return [min(xs), min(ys), max(xs), max(ys), z1 - (item.get("thickness_mm") or 150), z1]
    if kind == "WALL" and item.get("bbox_mm"):          # tuong cong: hinh bao tinh san tu cung
        b = item["bbox_mm"]
        return [b[0], b[1], b[2], b[3], level_mm, top]
    if kind in ("WALL", "BEAM", "STRIP"):
        s, e = item["start_mm"], item["end_mm"]
        w = item.get("width_mm") or item.get("thickness_mm") or item.get("b_mm") or 200
        L = math.hypot(e["x"] - s["x"], e["y"] - s["y"]) or 1.0
        nx, ny = abs(e["y"] - s["y"]) / L * w / 2.0, abs(e["x"] - s["x"]) / L * w / 2.0
        if kind == "WALL":
            z0, z1 = level_mm, top
        elif kind == "BEAM":
            z1 = level_mm + (item.get("z_offset_mm") or 0.0)
            z0 = z1 - (item.get("h_mm") or 600)
        else:
            z1 = level_mm + footing_top_offset_mm
            z0 = z1 - (item.get("thickness_mm") or 500)
        return [min(s["x"], e["x"]) - nx, min(s["y"], e["y"]) - ny, max(s["x"], e["x"]) + nx,
                max(s["y"], e["y"]) + ny, z0, z1]
    return None


CAT_OF = {"COL": "Structural Columns", "BEAM": "Structural Framing", "WALL": "Walls",
          "PAD": "Structural Foundations", "STRIP": "Structural Foundations", "SLAB": "Floors"}


def planned_vs_existing(planned: List[Dict], existing: List[Dict], ignore_tag_prefix: str = "",
                        **kw) -> List[Dict]:
    """
    planned: [{"kind": COL|BEAM|WALL|PAD|STRIP, "index", "mark", "bb"}]. Trả các cặp sẽ TRÙNG với phần tử
    đang có (bỏ qua phần tử mang tag ignore_tag_prefix - sẽ bị replace_existing thay thế).
    """
    out = []
    ex = [e for e in existing if not (ignore_tag_prefix and (e.get("tag") or "").startswith(ignore_tag_prefix))]
    for p in planned:
        pe = {"id": "planned:%s#%s" % (p["kind"], p["index"]), "cat": CAT_OF[p["kind"]],
              "type": p.get("mark"), "tag": "(sap dung)", "bb": p["bb"], "kind": p["kind"],
              "line": p.get("line"), "width": p.get("width"), "poly": p.get("poly")}
        for e in ex:
            res = classify_pair(pe, e, **kw)
            if res and res["kind"] == "duplicate":
                out.append({"planned": p["kind"], "index": p["index"], "mark": p.get("mark"),
                            "existing_id": e["id"], "existing_type": e.get("type"),
                            "existing_tag": e.get("tag") or "", "overlap": res["overlap"]})
    return out
