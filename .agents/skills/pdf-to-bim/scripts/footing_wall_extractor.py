# -*- coding: utf-8 -*-
"""
footing_wall_extractor.py - Trích xuất Móng đơn (PF), Móng băng (SF) và Tường 200 mm từ
Footing Marking Plan dạng PDF vector (nét vẽ thường là các đoạn thẳng rời, không phải hình khép kín).

Nguyên tắc chống nhận nhầm (học từ S201 thực tế - parser cũ ra 186 móng đơn thay vì ~39):
  * Móng đơn: hình chữ nhật ghép từ đoạn ngang/dọc, >= 80% chu vi có nét, KÍCH THƯỚC ĐÚNG bảng
    thống kê của mã PF ghi trong/gần hình đó.
  * Tường: cặp nét song song cách nhau đúng bề dày (200 mm), nối các đoạn thẳng hàng, PHẢI có mã
    tường (W1, LW1, SW1, RW1...) trong bán kính cho phép.
  * Móng băng: cặp nét cách nhau đúng bề rộng SF trong bảng thống kê, có mã SF gần đó.
Toạ độ đầu ra: mm Revit (qua AffineTransformer đã khớp).
"""

import math
import re
from typing import Dict, List, Optional, Tuple

PF_RE = re.compile(r"^(PF\d{1,2}[A-Z]?)\b")
SF_RE = re.compile(r"^(SF\d{1,2}[A-Z]?)\b")
WALL_RE = re.compile(r"^((?:RW|SW|LW|US|W)\d{1,2}[A-Z]?)\b")


class SegIndex(object):
    """Chỉ mục đoạn thẳng ngang/dọc theo toạ độ (bước 50 mm) để tra độ phủ nét nhanh."""

    def __init__(self, segs: List[Tuple[float, float, float, float]], step: float = 50.0):
        self.step = step
        self.h, self.v = {}, {}
        for x1, y1, x2, y2 in segs:
            if abs(y2 - y1) < 2 and abs(x2 - x1) >= 2:
                self.h.setdefault(int(round(y1 / step)), []).append((min(x1, x2), max(x1, x2), y1))
            elif abs(x2 - x1) < 2 and abs(y2 - y1) >= 2:
                self.v.setdefault(int(round(x1 / step)), []).append((min(y1, y2), max(y1, y2), x1))

    def _cov(self, table, key_val, a0, a1, tol, bridge=0.0):
        """
        Tỉ lệ chiều dài [a0, a1] có nét. bridge: khe hở <= bridge mm giữa 2 đoạn liền kề được tính là
        có nét (nét đứt vẽ bằng nhiều đoạn rời - vd phần móng nằm dưới sàn).
        """
        k = int(round(key_val / self.step))
        got = []
        for kk in (k - 1, k, k + 1):
            for s0, s1, c in table.get(kk, ()):
                if abs(c - key_val) <= tol:
                    g0, g1 = max(a0, s0), min(a1, s1)
                    if g1 > g0:
                        got.append((g0, g1))
        got.sort()
        m = 0.0
        end = None
        for g0, g1 in got:
            if end is not None and g1 <= end:
                continue
            if end is not None and g0 > end and g0 - end <= bridge:
                g0 = end  # nối khe nét đứt
            start = g0 if end is None else max(g0, end)
            m += g1 - start
            end = g1
        return m / (a1 - a0) if a1 > a0 else 0.0

    def h_cov(self, y, x0, x1, tol=25.0, bridge=0.0):
        return self._cov(self.h, y, x0, x1, tol, bridge)

    def v_cov(self, x, y0, y1, tol=25.0, bridge=0.0):
        return self._cov(self.v, x, y0, y1, tol, bridge)

    def rect_cov(self, x0, y0, x1, y1, tol=25.0):
        return min(self.h_cov(y0, x0, x1, tol), self.h_cov(y1, x0, x1, tol),
                   self.v_cov(x0, y0, y1, tol), self.v_cov(x1, y0, y1, tol))


def collect_segments(page, transformer, area_pt=None, min_len_mm: float = 20.0) -> List[Tuple[float, float, float, float]]:
    """Mọi đoạn thẳng (kể cả cạnh 're') của trang, quy đổi sang mm Revit, trong khung mặt bằng."""
    def inside(x, y):
        return area_pt is None or (area_pt[0] <= x <= area_pt[2] and area_pt[1] <= y <= area_pt[3])

    segs = []
    for path in page.get_drawings():
        for it in path.get("items", []):
            pts = []
            if it[0] == "l":
                pts = [(it[1], it[2])]
            elif it[0] == "re":
                r = it[1]
                cs = [fitz_pt(r.x0, r.y0), fitz_pt(r.x1, r.y0), fitz_pt(r.x1, r.y1), fitz_pt(r.x0, r.y1)]
                pts = [(cs[i], cs[(i + 1) % 4]) for i in range(4)]
            for a, b in pts:
                if not (inside(a.x, a.y) and inside(b.x, b.y)):
                    continue
                pa, pb = transformer.to_revit_mm(a.x, a.y), transformer.to_revit_mm(b.x, b.y)
                if math.hypot(pb["x"] - pa["x"], pb["y"] - pa["y"]) >= min_len_mm:
                    segs.append((pa["x"], pa["y"], pb["x"], pb["y"]))
    return segs


class _P(object):
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x, self.y = x, y


def fitz_pt(x, y):
    return _P(x, y)


def collect_labels(page, transformer, regex, area_pt=None) -> List[Dict]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                m = regex.match(span["text"].strip().upper())
                if not m:
                    continue
                b = span["bbox"]
                cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
                if area_pt is not None and not (area_pt[0] <= cx <= area_pt[2] and area_pt[1] <= cy <= area_pt[3]):
                    continue
                p = transformer.to_revit_mm(cx, cy)
                out.append({"mark": m.group(1), "x": p["x"], "y": p["y"]})
    return out


def _rect_dist(px, py, x0, y0, x1, y1):
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


def extract_pad_footings(idx: SegIndex, labels: List[Dict], schedule: Dict[str, Dict],
                         edge_cov: float = 0.85, missing_edge_min: float = 0.0,
                         label_radius_mm: float = 1500.0) -> List[Dict]:
    """
    Với mỗi nhãn PFx: dò hình chữ nhật đúng kích thước bảng thống kê (cả 2 hướng) chứa/sát nhãn,
    dựa trên các cạnh ngang có thật. Trả về [{"mark","center","x_mm","y_mm","thickness_mm","cov"}].
    """
    sizes = {k: (v["b_mm"], v["h_mm"], v.get("d_mm")) for k, v in schedule.items()
             if k.startswith("PF") and v.get("b_mm") and v.get("h_mm")}
    found = []
    for lb in labels:
        if lb["mark"] not in sizes:
            continue
        b, h, d = sizes[lb["mark"]]
        best = None
        for wx, wy in {(b, h), (h, b)}:
            # Toạ độ cạnh dọc (x) và cạnh ngang (y) có thật quanh nhãn. Cạnh móng có thể nằm trên nét
            # dài của tường/móng băng nên KHÔNG dựa vào đầu mút đoạn thẳng.
            r = label_radius_mm + max(wx, wy)
            xs, ys = set(), set()
            for k in range(int((lb["y"] - r) // idx.step), int((lb["y"] + r) // idx.step) + 2):
                for s0, s1, y in idx.h.get(k, ()):
                    if s1 >= lb["x"] - r and s0 <= lb["x"] + r and min(s1, lb["x"] + r) - max(s0, lb["x"] - r) >= 0.25 * wx:
                        ys.add(round(y / 5) * 5)
            for k in range(int((lb["x"] - r) // idx.step), int((lb["x"] + r) // idx.step) + 2):
                for s0, s1, x in idx.v.get(k, ()):
                    if s1 >= lb["y"] - r and s0 <= lb["y"] + r and min(s1, lb["y"] + r) - max(s0, lb["y"] - r) >= 0.25 * wy:
                        xs.add(round(x / 5) * 5)
            # Mỗi cạnh có thật cho 2 ứng viên (là cạnh trái/dưới hoặc phải/trên) - cạnh còn lại có thể
            # không vẽ vì nhập vào nét móng băng/tường bên cạnh.
            x0s = set(xs) | set(x - wx for x in xs)
            y0s = set(ys) | set(y - wy for y in ys)
            for x0 in x0s:
                for y0 in y0s:
                    x1, y1 = x0 + wx, y0 + wy
                    dist = _rect_dist(lb["x"], lb["y"], x0, y0, x1, y1)
                    if dist > label_radius_mm:
                        continue
                    edges = (idx.h_cov(y0, x0, x1), idx.h_cov(y1, x0, x1), idx.v_cov(x0, y0, y1), idx.v_cov(x1, y0, y1))
                    good = sum(1 for e in edges if e >= edge_cov)
                    # >= 3 cạnh rõ: 2 cạnh song song + 1 cạnh vuông góc đã khóa vị trí theo cả 2 phương
                    if good < 3 or min(edges) < missing_edge_min and good < 4:
                        continue
                    key = (good, round(sum(edges), 2), dist == 0, -dist)
                    if best is None or key > best[0]:
                        best = (key, x0, y0, x1, y1, wx, wy, edges)
        if best:
            _, x0, y0, x1, y1, wx, wy, edges = best
            found.append({"mark": lb["mark"], "center": {"x": round((x0 + x1) / 2, 1), "y": round((y0 + y1) / 2, 1)},
                          "x_mm": int(round(wx)), "y_mm": int(round(wy)), "thickness_mm": d,
                          "cov": round(sum(edges) / 4.0, 2), "edges_found": best[0][0]})
    # Gộp trùng (nhiều nhãn cùng 1 móng)
    uniq = []
    for f in sorted(found, key=lambda f: -f["cov"]):
        if not any(math.hypot(f["center"]["x"] - u["center"]["x"], f["center"]["y"] - u["center"]["y"]) < 100
                   for u in uniq):
            uniq.append(f)
    return uniq


def _parallel_bands(segs, width_mm, tol_mm=15.0, min_overlap_mm=300.0):
    """Cặp nét ngang/dọc song song cách nhau width_mm -> dải [(orient, c, a0, a1)] (c = toạ độ tim)."""
    bands = []
    for orient in ("h", "v"):
        lines = []
        for x1, y1, x2, y2 in segs:
            if orient == "h" and abs(y2 - y1) < 2:
                lines.append((y1, min(x1, x2), max(x1, x2)))
            elif orient == "v" and abs(x2 - x1) < 2:
                lines.append((x1, min(y1, y2), max(y1, y2)))
        lines.sort()
        cs = [l[0] for l in lines]
        import bisect
        for i, (c, a0, a1) in enumerate(lines):
            j0 = bisect.bisect_left(cs, c + width_mm - tol_mm)
            j1 = bisect.bisect_right(cs, c + width_mm + tol_mm)
            for j in range(j0, j1):
                c2, b0, b1 = lines[j]
                o0, o1 = max(a0, b0), min(a1, b1)
                if o1 - o0 >= min_overlap_mm:
                    bands.append((orient, round((c + c2) / 2.0, 1), o0, o1))
    return bands


def _merge_bands(bands, gap_mm=600.0, c_tol=20.0):
    """Nối các dải cùng tim (lệch <= c_tol) và hở <= gap_mm thành đoạn dài."""
    out = []
    for orient in ("h", "v"):
        bs = sorted([b for b in bands if b[0] == orient], key=lambda b: (b[1], b[2]))
        groups = []
        for _, c, a0, a1 in bs:
            for g in groups:
                if abs(g["c"] - c) <= c_tol and a0 <= g["a1"] + gap_mm and a1 >= g["a0"] - gap_mm:
                    g["a0"], g["a1"] = min(g["a0"], a0), max(g["a1"], a1)
                    g["n"] += 1
                    break
            else:
                groups.append({"c": c, "a0": a0, "a1": a1, "n": 1})
        # gộp tiếp các nhóm chồng lên nhau sau khi mở rộng
        changed = True
        while changed:
            changed = False
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    gi, gj = groups[i], groups[j]
                    if abs(gi["c"] - gj["c"]) <= c_tol and gj["a0"] <= gi["a1"] + gap_mm and gj["a1"] >= gi["a0"] - gap_mm:
                        gi["a0"], gi["a1"] = min(gi["a0"], gj["a0"]), max(gi["a1"], gj["a1"])
                        gi["n"] += gj["n"]
                        groups.pop(j)
                        changed = True
                        break
                if changed:
                    break
        for g in groups:
            out.append((orient, g["c"], g["a0"], g["a1"]))
    return out


def _nearest_label(labels, orient, c, a0, a1, radius):
    best = None
    for lb in labels:
        along = lb["x"] if orient == "h" else lb["y"]
        perp = lb["y"] if orient == "h" else lb["x"]
        d_al = max(a0 - along, 0.0, along - a1)
        d = math.hypot(d_al, perp - c)
        if d <= radius and (best is None or d < best[0]):
            best = (d, lb["mark"])
    return best[1] if best else None


def extract_walls(segs, labels: List[Dict], thickness_mm: float = 200.0, min_len_mm: float = 600.0,
                  label_radius_mm: float = 1500.0) -> List[Dict]:
    """Tường dày thickness_mm có mã tường gần đó: [{"mark","start_mm","end_mm","thickness_mm"}]."""
    walls = []
    for orient, c, a0, a1 in _merge_bands(_parallel_bands(segs, thickness_mm)):
        if a1 - a0 < min_len_mm:
            continue
        mark = _nearest_label(labels, orient, c, a0, a1, label_radius_mm)
        if not mark:
            continue
        s = {"x": a0, "y": c} if orient == "h" else {"x": c, "y": a0}
        e = {"x": a1, "y": c} if orient == "h" else {"x": c, "y": a1}
        walls.append({"mark": mark, "start_mm": {k: round(v, 1) for k, v in s.items()},
                      "end_mm": {k: round(v, 1) for k, v in e.items()},
                      "length_mm": round(a1 - a0), "thickness_mm": thickness_mm})
    return walls


def extract_strip_footings(segs, labels: List[Dict], schedule: Dict[str, Dict], min_len_mm: float = 1000.0,
                           label_radius_mm: float = 2500.0) -> List[Dict]:
    """Móng băng: dải rộng đúng bảng thống kê SFx, có nhãn SFx gần đó."""
    out = []
    for mk, v in schedule.items():
        if not mk.startswith("SF") or not v.get("b_mm"):
            continue
        width = float(v["b_mm"])
        mk_labels = [l for l in labels if l["mark"] == mk]
        for orient, c, a0, a1 in _merge_bands(_parallel_bands(segs, width, tol_mm=25.0, min_overlap_mm=500.0),
                                              gap_mm=800.0):
            if a1 - a0 < min_len_mm or not _nearest_label(mk_labels, orient, c, a0, a1, label_radius_mm):
                continue
            s = {"x": a0, "y": c} if orient == "h" else {"x": c, "y": a0}
            e = {"x": a1, "y": c} if orient == "h" else {"x": c, "y": a1}
            out.append({"mark": mk, "start_mm": {k: round(v2, 1) for k, v2 in s.items()},
                        "end_mm": {k: round(v2, 1) for k, v2 in e.items()},
                        "width_mm": int(width), "thickness_mm": v.get("h_mm"), "length_mm": round(a1 - a0)})
    return out


# ---------------------------------------------------------------------------------------------
# Thế hệ 2 (học từ S201 thực tế):
#  - Móng sát tường vẽ nửa nét liền / nửa nét đứt (phần dưới sàn) và các móng chồng nhau được vẽ
#    GỘP 1 đường bao -> không tìm được từng hình chữ nhật. Ghi chú bản vẽ: "Footings to be positioned
#    from the C.L. of columns U.N.O." -> đặt móng TÂM TẠI TIM CỘT, kích thước theo bảng thống kê,
#    kiểm chứng bằng độ phủ nét (nối nét đứt).
#  - Tường: bắt buộc có hatch bê tông (đoạn rất ngắn) giữa 2 nét, nối góc.
#  - Móng băng: dò theo từng tường chắn đất (RW), cặp nét cách nhau đúng bề rộng SF.
# ---------------------------------------------------------------------------------------------

def _pad_edges(idx, x0, y0, x1, y1, bridge):
    return (idx.h_cov(y0, x0, x1, bridge=bridge), idx.h_cov(y1, x0, x1, bridge=bridge),
            idx.v_cov(x0, y0, y1, bridge=bridge), idx.v_cov(x1, y0, y1, bridge=bridge))


def _pad_ok(edges, min_total, min_axis):
    """Đủ bằng chứng: tổng độ phủ >= min_total VÀ có ít nhất 1 cạnh ngang + 1 cạnh dọc rõ."""
    return sum(edges) >= min_total and max(edges[0], edges[1]) >= min_axis and max(edges[2], edges[3]) >= min_axis


def extract_pads_on_columns(idx: SegIndex, columns: List[Dict], labels: List[Dict], schedule: Dict[str, Dict],
                            label_radius_mm: float = 3500.0, bridge_mm: float = 300.0,
                            min_total: float = 2.4, min_axis: float = 0.7) -> List[Dict]:
    """
    columns: [{"center": {x, y}, "mark"}] (mm Revit, lấy từ chính trang móng).
    Mỗi cột: thử các mã PF có nhãn trong bán kính (gần trước), cả 2 hướng, hình đặt tâm tại tim cột.
    Cột không có nhãn PF gần -> không có móng (có tag mới có cấu kiện).
    """
    sizes = {k: (v["b_mm"], v["h_mm"], v.get("d_mm")) for k, v in schedule.items()
             if k.startswith("PF") and v.get("b_mm") and v.get("h_mm")}
    pads = []
    for col in columns:
        cx, cy = col["center"]["x"], col["center"]["y"]
        near = sorted(((math.hypot(l["x"] - cx, l["y"] - cy), l["mark"]) for l in labels
                       if l["mark"] in sizes and math.hypot(l["x"] - cx, l["y"] - cy) <= label_radius_mm))
        marks = []
        for _, mk in near:
            if mk not in marks:
                marks.append(mk)
        if not marks:
            # NGUYÊN TẮC: chỗ nào trên bản vẽ có tag thì chỗ đó mới có cấu kiện -> cột không có nhãn
            # PF gần đó thì KHÔNG đặt móng, dù nét bao rõ đến đâu.
            continue
        best = None
        for rank, mk in enumerate(marks[:3]):
            b, h, d = sizes[mk]
            for wx, wy in {(b, h), (h, b)}:
                x0, y0, x1, y1 = cx - wx / 2.0, cy - wy / 2.0, cx + wx / 2.0, cy + wy / 2.0
                edges = _pad_edges(idx, x0, y0, x1, y1, bridge_mm)
                if not _pad_ok(edges, min_total, min_axis):
                    continue
                key = (round(sum(edges), 2), -rank)
                if best is None or key > best[0]:
                    best = (key, mk, wx, wy, d, edges)
        if best:
            _, mk, wx, wy, d, edges = best
            pads.append({"mark": mk, "center": {"x": round(cx, 1), "y": round(cy, 1)},
                         "x_mm": int(round(wx)), "y_mm": int(round(wy)), "thickness_mm": d,
                         "cov": round(sum(edges) / 4.0, 2), "placement": "column_centre",
                         "column": col.get("mark"), "labeled": True})
    return pads


def extract_pad_footings_v2(idx: SegIndex, columns: List[Dict], labels: List[Dict], schedule: Dict[str, Dict],
                            explain_radius_mm: float = 1500.0, relaxed_radius_mm: float = 3000.0,
                            relaxed_min_total: float = 2.0) -> List[Dict]:
    """Móng theo tim cột + móng lệch tâm (U.N.O) dò theo cạnh cho các nhãn PF chưa được giải thích."""
    pads = extract_pads_on_columns(idx, columns, labels, schedule)

    def explained(lb):
        for f in pads:
            if f["mark"] != lb["mark"]:
                continue  # nhãn chỉ được "giải thích" bởi móng CÙNG mã
            x0 = f["center"]["x"] - f["x_mm"] / 2.0
            y0 = f["center"]["y"] - f["y_mm"] / 2.0
            if _rect_dist(lb["x"], lb["y"], x0, y0, x0 + f["x_mm"], y0 + f["y_mm"]) <= explain_radius_mm:
                return True
        return False

    rest = [l for l in labels if not explained(l)]
    for f in extract_pad_footings(idx, rest, schedule):
        if not any(math.hypot(f["center"]["x"] - p["center"]["x"], f["center"]["y"] - p["center"]["y"]) < 300
                   for p in pads):
            f["placement"] = "edges"
            pads.append(f)
    # Lượt 2: nhãn PF vẫn chưa có móng -> cột gần nhãn nhất CHƯA có móng, đặt theo tim cột với ngưỡng
    # nới (móng bị móng bên cạnh/móng băng che 1 cạnh). Nhãn chưa dùng là bằng chứng bổ sung.
    sizes = {k: (v["b_mm"], v["h_mm"], v.get("d_mm")) for k, v in schedule.items()
             if k.startswith("PF") and v.get("b_mm") and v.get("h_mm")}
    for lb in [l for l in labels if not explained(l) and l["mark"] in sizes]:
        free = [c for c in columns
                if not any(math.hypot(c["center"]["x"] - p["center"]["x"], c["center"]["y"] - p["center"]["y"]) < 300
                           for p in pads)
                and math.hypot(c["center"]["x"] - lb["x"], c["center"]["y"] - lb["y"]) <= relaxed_radius_mm]
        if not free:
            continue
        col = min(free, key=lambda c: math.hypot(c["center"]["x"] - lb["x"], c["center"]["y"] - lb["y"]))
        b, h, d = sizes[lb["mark"]]
        cx, cy = col["center"]["x"], col["center"]["y"]
        best = None
        for wx, wy in {(b, h), (h, b)}:
            e = _pad_edges(idx, cx - wx / 2.0, cy - wy / 2.0, cx + wx / 2.0, cy + wy / 2.0, 300.0)
            if _pad_ok(e, relaxed_min_total, 0.6) and (best is None or sum(e) > sum(best[0])):
                best = (e, wx, wy)
        if best:
            pads.append({"mark": lb["mark"], "center": {"x": round(cx, 1), "y": round(cy, 1)},
                         "x_mm": int(round(best[1])), "y_mm": int(round(best[2])), "thickness_mm": d,
                         "cov": round(sum(best[0]) / 4.0, 2), "placement": "column_centre_relaxed",
                         "column": col.get("mark"), "labeled": True})
    return assign_labels_one_to_one(pads, labels, explain_radius_mm)


def assign_labels_one_to_one(items: List[Dict], labels: List[Dict], radius_mm: float = 1500.0) -> List[Dict]:
    """
    NGUYÊN TẮC "có tag mới có cấu kiện": ghép một-một nhãn <-> cấu kiện CÙNG mã theo khoảng cách
    tăng dần (nhãn trong/sát hình trước). Cấu kiện không có nhãn riêng bị loại; mỗi cấu kiện giữ
    toạ độ nhãn của nó ("label_mm") để truy vết.
    """
    def dist(lb, it):
        x0 = it["center"]["x"] - it["x_mm"] / 2.0
        y0 = it["center"]["y"] - it["y_mm"] / 2.0
        return _rect_dist(lb["x"], lb["y"], x0, y0, x0 + it["x_mm"], y0 + it["y_mm"])

    pairs = sorted((dist(lb, it), li, ii) for li, lb in enumerate(labels) for ii, it in enumerate(items)
                   if lb["mark"] == it["mark"] and dist(lb, it) <= radius_mm)
    used_l, owned = set(), {}
    for d, li, ii in pairs:
        if li in used_l or ii in owned:
            continue
        used_l.add(li)
        owned[ii] = li
    out = []
    for ii, it in enumerate(items):
        if ii in owned:
            lb = labels[owned[ii]]
            it = dict(it, label_mm={"x": round(lb["x"], 1), "y": round(lb["y"], 1)})
            out.append(it)
    return out


class _PointGrid(object):
    def __init__(self, pts, cell=200.0):
        self.cell = cell
        self.g = {}
        for x, y in pts:
            self.g.setdefault((int(x // cell), int(y // cell)), []).append((x, y))

    def points_in_box(self, x0, y0, x1, y1):
        out = []
        for i in range(int(x0 // self.cell), int(x1 // self.cell) + 1):
            for j in range(int(y0 // self.cell), int(y1 // self.cell) + 1):
                for x, y in self.g.get((i, j), ()):
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        out.append((x, y))
        return out

    def count_in_box(self, x0, y0, x1, y1):
        n = 0
        for i in range(int(x0 // self.cell), int(x1 // self.cell) + 1):
            for j in range(int(y0 // self.cell), int(y1 // self.cell) + 1):
                for x, y in self.g.get((i, j), ()):
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        n += 1
        return n


def hatch_points(page, transformer, max_len_mm: float = 150.0, area_pt=None):
    """Trung điểm các đoạn rất ngắn (hatch chấm/tam giác bê tông) - mm Revit."""
    pts = []
    for x1, y1, x2, y2 in collect_segments(page, transformer, area_pt, min_len_mm=1.0):
        if math.hypot(x2 - x1, y2 - y1) <= max_len_mm:
            pts.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    return _PointGrid(pts)


def _snap_corners(walls, tol=350.0):
    """Nối góc tường vuông góc: kéo/cắt đầu tường về giao điểm tim khi hở/chờm <= tol."""
    for w in walls:
        for v in walls:
            if w is v or w["orient"] == v["orient"]:
                continue
            # w: tim c, phạm vi a0..a1 ; v: tim c', phạm vi b0..b1 (phương vuông góc)
            if not (v["a0"] - tol <= w["c"] <= v["a1"] + tol):
                continue
            for end in ("a0", "a1"):
                if abs(w[end] - v["c"]) <= tol:
                    w[end] = v["c"]
    return walls


def extract_walls_v2(segs, labels: List[Dict], hatch: _PointGrid, thickness_mm: float = 200.0,
                     min_len_mm: float = 900.0, label_radius_mm: float = 2000.0,
                     dedupe_mm: float = 60.0, min_face_cov: float = 0.8, min_hatch_per_m: float = 15.0,
                     bin_mm: float = 250.0, min_hatch_per_bin: int = 2, max_gap_bins: int = 2) -> List[Dict]:
    """Tường dày thickness_mm: có hatch bê tông giữa 2 nét + mã tường gần đó, đã nối góc."""
    raw = []
    fidx = SegIndex(segs)
    half = thickness_mm / 2.0 - 15.0
    for orient, c, band0, band1 in _merge_bands(_parallel_bands(segs, thickness_mm), gap_mm=800.0):
        # Chia dải thành các ô bin_mm; tường thật có hatch bê tông LIÊN TỤC -> chỉ giữ các đoạn
        # hatch liên tục (cho phép hở <= max_gap_bins ô). Tránh nối quá tay 2 tường xa nhau qua 1 nét dài.
        nb = max(1, int(math.ceil((band1 - band0) / bin_mm)))
        hot = []
        for i in range(nb):
            b0, b1 = band0 + i * bin_mm, min(band1, band0 + (i + 1) * bin_mm)
            n = hatch.count_in_box(b0, c - half, b1, c + half) if orient == "h" else                 hatch.count_in_box(c - half, b0, c + half, b1)
            hot.append(n >= min_hatch_per_bin)
        runs, i = [], 0
        while i < nb:
            if not hot[i]:
                i += 1
                continue
            j, gap = i, 0
            k = i
            while k + 1 < nb:
                if hot[k + 1]:
                    gap = 0
                    j = k + 1
                elif gap < max_gap_bins:
                    gap += 1
                else:
                    break
                k += 1
            runs.append((band0 + i * bin_mm, min(band1, band0 + (j + 1) * bin_mm)))
            i = j + 1
        cov = fidx.h_cov if orient == "h" else fidx.v_cov
        for a0, a1 in runs:
            if a1 - a0 < min_len_mm:
                continue
            faces = (cov(c - thickness_mm / 2.0, a0, a1, tol=20.0, bridge=60.0),
                     cov(c + thickness_mm / 2.0, a0, a1, tol=20.0, bridge=60.0))
            if min(faces) < min_face_cov:
                continue  # dải "ma": 1 mặt chỉ là nét ngắn/nét đứt
            n = hatch.count_in_box(a0, c - half, a1, c + half) if orient == "h" else                 hatch.count_in_box(c - half, a0, c + half, a1)
            mark = _nearest_label(labels, orient, c, a0, a1, label_radius_mm)
            if not mark:
                continue
            raw.append({"orient": orient, "c": c, "a0": a0, "a1": a1, "mark": mark,
                        "hatch_per_m": round(n / ((a1 - a0) / 1000.0), 1)})
    # Hatch thấp hơn tường thật (>= 20/m trên S201) -> dải giả ghép từ nét móng/thang
    raw = [w for w in raw if w["hatch_per_m"] >= min_hatch_per_m]
    # Gộp tường trùng / dải "kề": 1 dải song song nằm sát (<= bề dày + 60 mm) cạnh tường dài hơn và
    # chồng phạm vi >= 50% là ảo (nét mặt vẽ đôi tạo thêm cặp nét cách 200 mm) -> giữ tường dài hơn
    raw.sort(key=lambda w: -(w["a1"] - w["a0"]))
    kept = []
    for w in raw:
        dup = False
        for k in kept:
            if k["orient"] == w["orient"] and abs(k["c"] - w["c"]) <= thickness_mm + dedupe_mm:
                ov = min(k["a1"], w["a1"]) - max(k["a0"], w["a0"])
                if ov >= 0.5 * (w["a1"] - w["a0"]):
                    dup = True
                    break
        if not dup:
            kept.append(w)
    raw = kept
    _snap_corners(raw)
    walls = []
    for w in raw:
        s = {"x": w["a0"], "y": w["c"]} if w["orient"] == "h" else {"x": w["c"], "y": w["a0"]}
        e = {"x": w["a1"], "y": w["c"]} if w["orient"] == "h" else {"x": w["c"], "y": w["a1"]}
        walls.append({"mark": w["mark"], "start_mm": {k: round(v, 1) for k, v in s.items()},
                      "end_mm": {k: round(v, 1) for k, v in e.items()}, "thickness_mm": thickness_mm,
                      "length_mm": round(w["a1"] - w["a0"]), "hatch_per_m": w["hatch_per_m"]})
    return walls


def extract_strips_along_walls(idx: SegIndex, walls: List[Dict], labels: List[Dict], schedule: Dict[str, Dict],
                               wall_prefix: str = "RW", search_mm: float = 3000.0, size_tol_mm: float = 30.0,
                               min_score: float = 0.5, label_radius_mm: float = 4000.0,
                               band_label_mm: float = 1500.0) -> List[Dict]:
    """
    Móng băng chạy dọc tường chắn đất: với mỗi tường RW, tìm cặp nét song song cách nhau đúng bề rộng
    SF (bảng thống kê) trong +-search_mm quanh tim tường; điểm = tổng độ phủ 2 nét dọc chiều dài tường
    (bị móng đơn che từng đoạn vẫn được). Phạm vi móng băng = phạm vi tường.
    """
    out = []
    sfs = {k: v for k, v in schedule.items() if k.startswith("SF") and v.get("b_mm")}
    for w in walls:
        if not w["mark"].startswith(wall_prefix):
            continue
        sx, sy, ex, ey = w["start_mm"]["x"], w["start_mm"]["y"], w["end_mm"]["x"], w["end_mm"]["y"]
        orient = "h" if abs(ey - sy) < 1 else "v"
        c = sy if orient == "h" else sx
        a0, a1 = (min(sx, ex), max(sx, ex)) if orient == "h" else (min(sy, ey), max(sy, ey))
        table = idx.h if orient == "h" else idx.v
        offs = set()
        for k in range(int((c - search_mm) // idx.step), int((c + search_mm) // idx.step) + 2):
            for s0, s1, cc in table.get(k, ()):
                if abs(cc - c) <= search_mm and min(s1, a1) - max(s0, a0) > 300:
                    offs.add(round((cc - c) / 5.0) * 5.0)
        for mk, v in sfs.items():
            width = float(v["b_mm"])
            mk_labels = [l for l in labels if l["mark"] == mk]
            if not _nearest_label(mk_labels, orient, c, a0, a1, label_radius_mm):
                continue
            best = None
            for o1 in offs:
                for o2 in offs:
                    if not (abs((o2 - o1) - width) <= size_tol_mm):
                        continue
                    cov = idx.h_cov if orient == "h" else idx.v_cov
                    score = cov(c + o1, a0, a1) + cov(c + o2, a0, a1)
                    if best is None or score > best[0]:
                        best = (score, o1, o2)
            if best and best[0] >= min_score:
                cc = c + (best[1] + best[2]) / 2.0
                if not _nearest_label(mk_labels, orient, cc, a0, a1, width / 2.0 + band_label_mm):
                    continue
                s = {"x": a0, "y": cc} if orient == "h" else {"x": cc, "y": a0}
                e = {"x": a1, "y": cc} if orient == "h" else {"x": cc, "y": a1}
                out.append({"mark": mk, "start_mm": {k: round(v2, 1) for k, v2 in s.items()},
                            "end_mm": {k: round(v2, 1) for k, v2 in e.items()}, "width_mm": int(width),
                            "thickness_mm": v.get("h_mm"), "length_mm": round(a1 - a0),
                            "offset_from_wall_mm": round((best[1] + best[2]) / 2.0), "score": round(best[0], 2),
                            "wall_mark": w["mark"], "_orient": orient, "_c": cc, "_a0": a0, "_a1": a1})
    # Mỗi nhãn SF chỉ thuộc về dải GẦN NHẤT (1 nhãn ở góc không được "nuôi" 2 dải vuông góc) ->
    # loại dải giả do các cạnh móng đơn thẳng hàng tạo ra.
    owned = set()
    for lb in labels:
        best = None
        for i, sf in enumerate(out):
            if sf["mark"] != lb["mark"]:
                continue
            along = lb["x"] if sf["_orient"] == "h" else lb["y"]
            perp = lb["y"] if sf["_orient"] == "h" else lb["x"]
            d = math.hypot(max(sf["_a0"] - along, 0.0, along - sf["_a1"]), perp - sf["_c"])
            if d <= sf["width_mm"] / 2.0 + band_label_mm and (best is None or d < best[0]):
                best = (d, i)
        if best:
            owned.add(best[1])
    result = []
    for i, sf in enumerate(out):
        if i in owned:
            result.append({k: v for k, v in sf.items() if not k.startswith("_")})
    return result


def union_strip_footings(strips: List[Dict], min_area_mm2: float = 250000.0) -> List[Dict]:
    """
    Hợp nhất các dải móng băng cùng mã/bề rộng/chiều dày thành đường bao liền (chữ L/U...) -> mỗi tuyến
    1 tấm móng: KHÔNG chồng bê tông ở góc (Revit báo 'floors overlap') và KHÔNG hở góc ngoài.
    Trả [{"mark", "width_mm", "thickness_mm", "outer_loop_mm": [...], "opening_loops_mm": [...],
          "source_strips": n, "length_mm"}].
    """
    from shapely.geometry import box
    from shapely.ops import unary_union
    def band(s, grow=0.0):
        sx, sy, ex, ey = s["start_mm"]["x"], s["start_mm"]["y"], s["end_mm"]["x"], s["end_mm"]["y"]
        hw = s["width_mm"] / 2.0 + grow
        if abs(ey - sy) < 1:
            return min(sx, ex) - grow, sy - hw, max(sx, ex) + grow, sy + hw
        return sx - hw, min(sy, ey) - grow, sx + hw, max(sy, ey) + grow

    def inside(px, py, b):
        return b[0] <= px <= b[2] and b[1] <= py <= b[3]

    groups = {}
    for s in strips:
        key = (s["mark"], s["width_mm"], s.get("thickness_mm"))
        sx, sy, ex, ey = s["start_mm"]["x"], s["start_mm"]["y"], s["end_mm"]["x"], s["end_mm"]["y"]
        hw = s["width_mm"] / 2.0
        # Đầu dải chạm dải khác (góc L / chữ T: tim dừng tại giao điểm tim tường) -> kéo dài thêm nửa bề
        # rộng để phủ kín ô góc ngoài; đầu tự do giữ nguyên.
        L = math.hypot(ex - sx, ey - sy) or 1.0
        ux, uy = (ex - sx) / L, (ey - sy) / L
        others = [band(o, 1.0) for o in strips if o is not s and o["mark"] == s["mark"]]
        if any(inside(sx, sy, b) for b in others):
            sx, sy = sx - ux * hw, sy - uy * hw
        if any(inside(ex, ey, b) for b in others):
            ex, ey = ex + ux * hw, ey + uy * hw
        if abs(ey - sy) < 1:      # ngang
            r = box(min(sx, ex), sy - hw, max(sx, ex), sy + hw)
        else:                     # doc
            r = box(sx - hw, min(sy, ey), sx + hw, max(sy, ey))
        groups.setdefault(key, []).append((r, s.get("length_mm", 0)))
    out = []
    for (mark, width, thick), items in groups.items():
        merged = unary_union([r for r, _ in items])
        polys = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        for poly in polys:
            if poly.area < min_area_mm2:
                continue
            poly = poly.simplify(1.0)  # bo dinh thang hang
            loop = [{"x": round(x, 1), "y": round(y, 1)} for x, y in list(poly.exterior.coords)[:-1]]
            holes = [[{"x": round(x, 1), "y": round(y, 1)} for x, y in list(h.coords)[:-1]] for h in poly.interiors]
            n = sum(1 for r, _ in items if r.intersects(poly))
            out.append({"mark": mark, "width_mm": width, "thickness_mm": thick, "outer_loop_mm": loop,
                        "opening_loops_mm": holes, "source_strips": n,
                        "length_mm": round(poly.area / float(width))})
    return out



# ---------------------------------------------------------------------------------------------
# Toà nhà XOAY so với trang bản vẽ (vd Building B -30.74°): các bộ trích xuất ở trên giả định nét
# thẳng hàng trục X/Y. Trích xuất trong HỆ TRỤC CỤC BỘ (góc làm tròn về bội số 90° -> nét thẳng hàng),
# rồi xoay kết quả về hệ Revit quanh 1 điểm gốc.
# ---------------------------------------------------------------------------------------------

def local_frame(transformer, rest_deg=None):
    """
    Trả (transformer_cuc_bo, goc_le_deg, goc_xoay_quanh). goc_le = góc phép biến đổi trừ bội số 90° gần
    nhất (hoặc rest_deg = hướng trục cục bộ trong hệ Revit, mod 90). |goc_le| < 0.01° -> trả lại chính
    transformer (không cần xoay).
    """
    try:
        from pdf_struct_parser import AffineTransformer
    except ImportError:
        from .pdf_struct_parser import AffineTransformer
    if rest_deg is None:
        deg = math.degrees(transformer.theta)
        rest = deg - 90.0 * round(deg / 90.0)
    else:
        rest = rest_deg - 90.0 * round(rest_deg / 90.0)
    if abs(rest) < 0.01:
        return transformer, 0.0, None
    a = transformer.to_revit_mm(0.0, 0.0)
    b = transformer.to_revit_mm(1000.0, 0.0)
    origin = (a["x"], a["y"])
    bl = rotate_xy((b["x"], b["y"]), origin, -rest)
    return AffineTransformer((0.0, 0.0), (1000.0, 0.0), origin, bl), rest, origin


def rotate_xy(pt, origin, deg):
    r = math.radians(deg)
    dx, dy = pt[0] - origin[0], pt[1] - origin[1]
    return (origin[0] + dx * math.cos(r) - dy * math.sin(r), origin[1] + dx * math.sin(r) + dy * math.cos(r))


def _rot_pt(d, origin, deg):
    x, y = rotate_xy((d["x"], d["y"]), origin, deg)
    return {"x": round(x, 1), "y": round(y, 1)}


def rotate_results(origin, deg, pads=(), walls=(), strips=(), polys=(), columns=()):
    """Xoay kết quả trích xuất từ hệ cục bộ về hệ Revit (tại chỗ). Móng đơn/cột thêm rotation_deg."""
    for p in pads:
        p["center"] = _rot_pt(p["center"], origin, deg)
        if p.get("label_mm"):
            p["label_mm"] = _rot_pt(p["label_mm"], origin, deg)
        p["rotation_deg"] = round(p.get("rotation_deg", 0.0) + deg, 3)
    for c in columns:
        c["center"] = _rot_pt(c["center"], origin, deg)
        c["rotation_deg"] = round(c.get("rotation_deg", 0.0) + deg, 3)
    for w in list(walls) + list(strips):
        w["start_mm"] = _rot_pt(w["start_mm"], origin, deg)
        w["end_mm"] = _rot_pt(w["end_mm"], origin, deg)
    for pl in polys:
        pl["outer_loop_mm"] = [_rot_pt(q, origin, deg) for q in pl["outer_loop_mm"]]
        pl["opening_loops_mm"] = [[_rot_pt(q, origin, deg) for q in h] for h in pl.get("opening_loops_mm", [])]


# ---------------------------------------------------------------------------------------------
# Trang có NHIỀU HƯỚNG TRỤC (vd S202: khối chính Building B xoay -30.7°, cánh nối song song Zone A):
# dò các hướng chính của nét vẽ (hệ Revit, mod 90), trích xuất riêng trong từng hệ trục cục bộ, xoay về
# Revit rồi gộp. Mỗi nhãn PF chỉ sinh 1 móng trên toàn trang (hướng chính được ưu tiên).
# ---------------------------------------------------------------------------------------------

def _ang_dist(a, b):
    d = abs(a - b) % 90.0
    return min(d, 90.0 - d)


def dominant_orientations(segs, min_len_mm: float = 1000.0, bin_deg: float = 0.5,
                          min_share: float = 0.12, min_sep_deg: float = 3.0, max_frames: int = 3) -> List[float]:
    """Các hướng trục chính (độ, trong (-45, 45]) theo tổng chiều dài nét >= min_len_mm, mạnh nhất trước."""
    nb = int(round(90.0 / bin_deg))
    hist = [0.0] * nb
    longs = []
    for x0, y0, x1, y1 in segs:
        L = math.hypot(x1 - x0, y1 - y0)
        if L < min_len_mm:
            continue
        a = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 90.0
        longs.append((a, L))
        hist[int(a / bin_deg) % nb] += L
    sm = [hist[(i - 1) % nb] + hist[i] + hist[(i + 1) % nb] for i in range(nb)]
    top = max(sm) if sm and max(sm) > 0 else 1.0
    peaks = []
    for i in sorted(range(nb), key=lambda k: -sm[k]):
        if sm[i] < min_share * top or len(peaks) >= max_frames:
            break
        a = (i + 0.5) * bin_deg
        if all(_ang_dist(a, p) >= min_sep_deg for p in peaks):
            peaks.append(a)
    out = []
    for a in peaks:
        # tinh chỉnh: trung bình có trọng số các nét trong ±1° quanh đỉnh
        num = den = 0.0
        for b, L in longs:
            d = (b - a + 45.0) % 90.0 - 45.0
            if abs(d) <= 1.0:
                num += d * L
                den += L
        a = a + (num / den if den else 0.0)
        out.append(round(a - 90.0 * round(a / 90.0), 3))
    return out


def _wall_dup(w, acc, tol=250.0):
    """w trùng 1 đoạn đã nhận (trung điểm cách đường tim < tol)."""
    mx, my = (w["start_mm"]["x"] + w["end_mm"]["x"]) / 2.0, (w["start_mm"]["y"] + w["end_mm"]["y"]) / 2.0
    for a in acc:
        ax, ay = a["start_mm"]["x"], a["start_mm"]["y"]
        bx, by = a["end_mm"]["x"], a["end_mm"]["y"]
        L2 = ((bx - ax) ** 2 + (by - ay) ** 2) or 1.0
        t = max(0.0, min(1.0, ((mx - ax) * (bx - ax) + (my - ay) * (by - ay)) / L2))
        if math.hypot(mx - (ax + t * (bx - ax)), my - (ay + t * (by - ay))) <= tol:
            return True
    return False


def extract_foundation_multi_frame(page, transformer, area_pt, schedule, column_scale,
                                   extract_columns, column_to_revit, frames=None) -> Dict:
    """
    Chạy bộ trích xuất thế hệ 2 trong từng hướng trục chính rồi gộp. Trả dict: pads, walls, strips,
    strip_polys, unmatched (nhãn PF chưa có móng ở MỌI hướng), frames (độ, hướng chính trước).
    extract_columns(page, scale, area_pt=...) / column_to_revit(feat, transformer): hàm từ module khác.
    """
    main = math.degrees(transformer.theta)
    main = main - 90.0 * round(main / 90.0)
    found = frames if frames is not None else dominant_orientations(collect_segments(page, transformer, area_pt))
    order = [main]
    for a in found:
        if all(_ang_dist(a, b) >= 3.0 for b in order):
            order.append(a)
    feats = extract_columns(page, column_scale, area_pt=area_pt)
    res = {"pads": [], "walls": [], "strips": [], "strip_polys": [], "frames": [round(a, 3) for a in order]}
    unexplained = None
    for k, ang in enumerate(order):
        ltr, rot_deg, origin = local_frame(transformer, None if k == 0 else ang)
        segs = collect_segments(page, ltr, area_pt)
        idx = SegIndex(segs)
        cols = [column_to_revit(f, ltr) for f in feats]
        pf_labels = collect_labels(page, ltr, PF_RE, area_pt)
        sf_labels = collect_labels(page, ltr, SF_RE, area_pt)
        wall_labels = collect_labels(page, ltr, WALL_RE, area_pt)
        hatch = hatch_points(page, ltr, area_pt=area_pt)
        pads = extract_pad_footings_v2(idx, cols, pf_labels, schedule)
        walls = extract_walls_v2(segs, wall_labels, hatch)
        strips = extract_strips_along_walls(idx, walls, sf_labels, schedule, wall_prefix="")

        def explained(lb, pads=pads):
            return any(p["mark"] == lb["mark"] and abs(lb["x"] - p["center"]["x"]) <= p["x_mm"] / 2 + 1500 and
                       abs(lb["y"] - p["center"]["y"]) <= p["y_mm"] / 2 + 1500 for p in pads)
        unm = [l for l in pf_labels if not explained(l)]
        if origin is not None:
            rotate_results(origin, rot_deg, pads=pads, walls=walls, strips=strips)
            for l in unm:
                l["x"], l["y"] = rotate_xy((l["x"], l["y"]), origin, rot_deg)
        # Gộp: nhãn PF đã sinh móng ở hướng trước thì bỏ; móng trùng tâm (< 500 mm) thì bỏ
        used = [p["label_mm"] for p in res["pads"] if p.get("label_mm")]
        for p in pads:
            p["frame_deg"] = round(ang, 3)
            lm = p.get("label_mm")
            if lm and any(math.hypot(lm["x"] - u["x"], lm["y"] - u["y"]) < 50 for u in used):
                continue
            if any(math.hypot(p["center"]["x"] - q["center"]["x"], p["center"]["y"] - q["center"]["y"]) < 500
                   for q in res["pads"]):
                continue
            res["pads"].append(p)
        for w in walls:
            w["frame_deg"] = round(ang, 3)
            if not _wall_dup(w, res["walls"]):
                res["walls"].append(w)
        new_strips = []
        for s in strips:
            s["frame_deg"] = round(ang, 3)
            if not _wall_dup(s, res["strips"]):
                new_strips.append(s)
        res["strips"] += new_strips
        # Hợp nhất dải trong CÙNG hướng (đầu dải kéo phủ góc); khác hướng -> tấm riêng
        if new_strips:
            if origin is not None:
                rotate_results(origin, -rot_deg, strips=new_strips)
            polys = union_strip_footings(new_strips)
            if origin is not None:
                rotate_results(origin, rot_deg, strips=new_strips, polys=polys)
            for pl in polys:
                pl["frame_deg"] = round(ang, 3)
            res["strip_polys"] += polys
        if unexplained is None:
            unexplained = unm
        else:
            unexplained = [l for l in unexplained if any(
                l["mark"] == u["mark"] and math.hypot(l["x"] - u["x"], l["y"] - u["y"]) < 100 for u in unm)]
    res["unmatched"] = [l for l in (unexplained or []) if not any(
        p["mark"] == l["mark"] and math.hypot(l["x"] - p["center"]["x"], l["y"] - p["center"]["y"]) <=
        max(p["x_mm"], p["y_mm"]) / 2 + 1500 for p in res["pads"])]
    return res


# ---------------------------------------------------------------------------------------------
# TƯỜNG CONG: PDF vẽ cung tròn bằng CHUỖI đoạn thẳng ngắn (không phải đường cong Bezier).
# Nối chuỗi -> khớp đường tròn -> ghép 2 cung ĐỒNG TÂM cách nhau đúng bề dày tường, giữa có hatch
# bê tông liên tục, có mã tường gần đó (không tag -> không dựng). Toạ độ mm Revit.
# ---------------------------------------------------------------------------------------------

def _fit_circle(pts):
    """Khớp đường tròn bình phương tối thiểu. Trả (cx, cy, r, sai_so_max) hoặc None."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    u = [(p[0] - mx, p[1] - my) for p in pts]
    suu = sum(a * a for a, _ in u)
    svv = sum(b * b for _, b in u)
    suv = sum(a * b for a, b in u)
    suuu = sum(a ** 3 for a, _ in u)
    svvv = sum(b ** 3 for _, b in u)
    suvv = sum(a * b * b for a, b in u)
    svuu = sum(b * a * a for a, b in u)
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return None
    r1 = 0.5 * (suuu + suvv)
    r2 = 0.5 * (svvv + svuu)
    uc = (r1 * svv - r2 * suv) / det
    vc = (suu * r2 - suv * r1) / det
    cx, cy = uc + mx, vc + my
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    err = max(abs(math.hypot(p[0] - cx, p[1] - cy) - r) for p in pts)
    return cx, cy, r, err


def _chains(segs, key_mm=2.0, min_pts=5):
    """Nối các đoạn ngắn chung đầu mút thành chuỗi (chỉ nối nơi đúng 2 đoạn gặp nhau)."""
    from collections import defaultdict
    key = lambda x, y: (int(round(x / key_mm)), int(round(y / key_mm)))
    adj = defaultdict(list)
    for i, (x0, y0, x1, y1) in enumerate(segs):
        adj[key(x0, y0)].append(i)
        adj[key(x1, y1)].append(i)
    used, out = set(), []
    for i in range(len(segs)):
        if i in used:
            continue
        used.add(i)
        x0, y0, x1, y1 = segs[i]
        pts = [(x0, y0), (x1, y1)]
        for at_end in (True, False):
            while True:
                tip = pts[-1] if at_end else pts[0]
                nxt = [j for j in adj[key(*tip)] if j not in used]
                if len(nxt) != 1 or len(adj[key(*tip)]) != 2:
                    break
                j = nxt[0]
                used.add(j)
                a0, b0, a1, b1 = segs[j]
                q = (a1, b1) if key(a0, b0) == key(*tip) else (a0, b0)
                if at_end:
                    pts.append(q)
                else:
                    pts.insert(0, q)
        if len(pts) >= min_pts:
            out.append(pts)
    return out


def _arc_interval(pts, cx, cy):
    """Khoảng góc liên tục [a0, a1] (rad, a1 > a0) của chuỗi điểm quanh tâm."""
    angs = [math.atan2(p[1] - cy, p[0] - cx) for p in pts]
    un = [angs[0]]
    for a in angs[1:]:
        d = (a - un[-1] + math.pi) % (2 * math.pi) - math.pi
        un.append(un[-1] + d)
    return min(un), max(un)


def _interval_overlap(i1, i2):
    best = None
    for k in (-1, 0, 1):
        a0, a1 = i2[0] + 2 * math.pi * k, i2[1] + 2 * math.pi * k
        lo, hi = max(i1[0], a0), min(i1[1], a1)
        if hi > lo and (best is None or hi - lo > best[1] - best[0]):
            best = (lo, hi)
    return best


def _merge_angles(ivs, gap):
    """Gộp các khoảng góc [a0, a1] (rad, có thể vượt ±pi) - hở <= gap thì nối."""
    out = []
    for a0, a1 in sorted(ivs):
        if out and a0 <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], a1)
        else:
            out.append([a0, a1])
    return out


def _face_cover(tangent, cx, cy, r, band_mm, gap_mm):
    """Khoảng góc có nét nằm trên đường tròn (cx, cy, r) +- band (nét tiếp tuyến)."""
    ivs = []
    for x0, y0, x1, y1, _ in tangent:
        d0, d1 = math.hypot(x0 - cx, y0 - cy), math.hypot(x1 - cx, y1 - cy)
        if abs(d0 - r) <= band_mm and abs(d1 - r) <= band_mm:
            a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
            d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            lo, hi = (a0, a0 + d) if d >= 0 else (a0 + d, a0)
            ivs.append((lo, hi))
            if lo < -math.pi:
                ivs.append((lo + 2 * math.pi, hi + 2 * math.pi))
            if hi > math.pi:
                ivs.append((lo - 2 * math.pi, hi - 2 * math.pi))
    return _merge_angles(ivs, gap_mm / max(r, 1.0))


def extract_curved_walls_guided(segs, labels: List[Dict], hatch: _PointGrid, hints=(), thickness_mm: float = 200.0,
                                min_len_mm: float = 900.0, label_radius_mm: float = 2000.0,
                                thick_tol_mm: float = 20.0, bin_mm: float = 250.0, min_hatch_per_bin: int = 2,
                                max_gap_bins: int = 2, min_hatch_per_m: float = 15.0,
                                straight_walls=(), cad_hints=(), join_mm: float = 400.0) -> List[Dict]:
    """
    Tường cong dò theo TÂM GỢI Ý (hints: [(cx, cy, r)] mm Revit) - lấy từ cung tường của file CAD kiến trúc
    (A-WALL...: ghi đúng bán kính, tâm lệch ~100 mm so với bản kết cấu) và từ các chuỗi nét PDF khớp tròn tốt.
    Trên PDF kết cấu: chỉ lấy nét TIẾP TUYẾN quanh tâm gợi ý -> khớp lại tâm chính xác -> tìm 2 mặt cách nhau
    đúng bề dày -> đoạn góc có đủ 2 mặt + hatch bê tông liên tục + mã tường gần đó.
    """
    # gom tâm gợi ý gần nhau (< 400 mm). hints = cung PDF + cad_hints (CAD đã dời theo độ lệch)
    cents = []
    for cx, cy, r in list(hints) + list(cad_hints):
        for c in cents:
            if math.hypot(c["x"] - cx, c["y"] - cy) < 400:
                c["r"].append(r)
                break
        else:
            cents.append({"x": cx, "y": cy, "r": [r]})
    pre = []
    for x0, y0, x1, y1 in segs:
        L = math.hypot(x1 - x0, y1 - y0)
        if 10.0 <= L <= 1500.0:
            pre.append((x0, y0, x1, y1, L))
    half = thickness_mm / 2.0 - 15.0
    walls = []
    for c in cents:
        rmin, rmax = max(500.0, min(c["r"]) - 600.0), max(c["r"]) + 600.0

        def tangent_segs(cx, cy, tol_deg=8.0):
            out = []
            s = math.sin(math.radians(tol_deg))
            for x0, y0, x1, y1, L in pre:
                mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                d = math.hypot(mx - cx, my - cy)
                if not (rmin <= d <= rmax) or d < 1:
                    continue
                if abs(((x1 - x0) * (mx - cx) + (y1 - y0) * (my - cy)) / (L * d)) <= s:
                    out.append((x0, y0, x1, y1, L))
            return out
        # Có tâm CAD kiến trúc (đã dời theo độ lệch) gần đó -> dùng luôn (giá trị thiết kế, cung ngắn khớp lại
        # dễ trượt tâm dọc phân giác). Không có -> khớp lại tâm theo TỪNG MẶT trên PDF.
        cx, cy = c["x"], c["y"]
        cad_c = [h for h in cad_hints if math.hypot(h[0] - cx, h[1] - cy) <= 200]
        if cad_c:
            cx, cy = cad_c[0][0], cad_c[0][1]
        for _ in range(0 if cad_c else 3):
            tg = tangent_segs(cx, cy, 12.0)
            h = {}
            for x0, y0, x1, y1, L in tg:
                k = int(math.hypot((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy) // 20)
                h[k] = h.get(k, 0.0) + L
            fits = []
            for k, v in sorted(h.items(), key=lambda kv: -kv[1])[:4]:
                if v < 400:
                    break
                r0 = (k + 0.5) * 20.0
                pts = []
                for x0, y0, x1, y1, L in tg:
                    if abs(math.hypot((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy) - r0) <= 30:
                        pts += [(x0, y0), (x1, y1)]
                if len(pts) >= 8:
                    f = _fit_circle(pts)
                    if f and f[3] < 25 and abs(f[2] - r0) < 150:
                        fits.append((f, len(pts)))
            if not fits:
                break
            w = sum(n for _, n in fits)
            nx = sum(f[0] * n for f, n in fits) / w
            ny = sum(f[1] * n for f, n in fits) / w
            moved = math.hypot(nx - cx, ny - cy)
            cx, cy = nx, ny
            if moved < 2:
                break
        tg = tangent_segs(cx, cy)
        # mặt tường = đỉnh histogram khoảng cách tới tâm (bước 10 mm, trọng số chiều dài)
        hist = {}
        for x0, y0, x1, y1, L in tg:
            d = math.hypot((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy)
            hist[int(d // 10)] = hist.get(int(d // 10), 0.0) + L
        faces = []
        for k, v in sorted(hist.items(), key=lambda kv: -kv[1]):
            tot = v + hist.get(k - 1, 0) + hist.get(k + 1, 0)
            if tot < 500:
                break
            if all(abs(k - f) > 3 for f in faces):
                faces.append(k)
        faces = sorted((k + 0.5) * 10.0 for k in faces)
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                ri, ro = faces[i], faces[j]
                if abs(ro - ri - thickness_mm) > thick_tol_mm:
                    continue
                rc = (ri + ro) / 2.0
                cov_i = _face_cover(tg, cx, cy, ri, 20.0, 400.0)
                cov_o = _face_cover(tg, cx, cy, ro, 20.0, 400.0)
                both = []
                for a in cov_i:
                    for b in cov_o:
                        lo, hi = max(a[0], b[0]), min(a[1], b[1])
                        if hi > lo:
                            both.append((lo, hi))
                for lo, hi in _merge_angles(both, 400.0 / rc):
                    if lo < -math.pi - 1e-9 or (hi - lo) * rc < min_len_mm:
                        continue
                    # hatch bê tông liên tục NẰM TRONG VÀNH KHĂN giữa 2 mặt cong (không đếm hatch tường thẳng kề bên)
                    nb = max(1, int(math.ceil((hi - lo) * rc / bin_mm)))
                    hot = []
                    for k in range(nb):
                        b0 = lo + k / float(nb) * (hi - lo)
                        b1 = lo + (k + 1) / float(nb) * (hi - lo)
                        a = (b0 + b1) / 2.0
                        px, py = cx + rc * math.cos(a), cy + rc * math.sin(a)
                        rr = bin_mm / 2.0 + thickness_mm
                        n_in = 0
                        for hx, hy in hatch.points_in_box(px - rr, py - rr, px + rr, py + rr):
                            d = math.hypot(hx - cx, hy - cy)
                            t = math.atan2(hy - cy, hx - cx)
                            t = b0 + ((t - b0) % (2 * math.pi))
                            if ri + 15 <= d <= ro - 15 and t <= b1:
                                n_in += 1
                        # đoạn cung nằm trong dải 1 tường THẲNG đã có (chỗ tiếp tuyến) -> hatch là của tường thẳng
                        on_straight = False
                        for sw in straight_walls:
                            ax, ay = sw["start_mm"]["x"], sw["start_mm"]["y"]
                            bx, by = sw["end_mm"]["x"], sw["end_mm"]["y"]
                            L2 = ((bx - ax) ** 2 + (by - ay) ** 2) or 1.0
                            u = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L2))
                            if math.hypot(px - ax - u * (bx - ax), py - ay - u * (by - ay)) <= thickness_mm:
                                on_straight = True
                                break
                        hot.append(n_in >= min_hatch_per_bin and not on_straight)
                    best, s = None, 0
                    while s < nb:
                        if not hot[s]:
                            s += 1
                            continue
                        e_, gap, k = s, 0, s
                        while k + 1 < nb:
                            if hot[k + 1]:
                                gap, e_ = 0, k + 1
                            elif gap < max_gap_bins:
                                gap += 1
                            else:
                                break
                            k += 1
                        if best is None or e_ - s > best[1] - best[0]:
                            best = (s, e_)
                        s = e_ + 1
                    if not best:
                        continue
                    a0 = lo + best[0] / float(nb) * (hi - lo)
                    a1 = lo + (best[1] + 1) / float(nb) * (hi - lo)
                    L = (a1 - a0) * rc
                    if L < min_len_mm:
                        continue
                    pts = [(cx + rc * math.cos(a0 + (a1 - a0) * t / 20.0), cy + rc * math.sin(a0 + (a1 - a0) * t / 20.0))
                           for t in range(21)]
                    n = sum(hatch.count_in_box(p[0] - half, p[1] - half, p[0] + half, p[1] + half) for p in pts)
                    per_m = n * (L / 21.0 / (2 * half)) / (L / 1000.0) if L else 0.0
                    mark, dbest, how = None, None, "label"
                    for lb in labels:
                        d = min(math.hypot(lb["x"] - p[0], lb["y"] - p[1]) for p in pts)
                        if d <= label_radius_mm and (dbest is None or d < dbest):
                            dbest, mark = d, lb["mark"]
                    if not mark:
                        # đoạn cong NỐI TIẾP TUYẾN với tường thẳng đã có mã (cùng 1 tường, nhãn ghi ở đoạn thẳng)
                        for sw in straight_walls:
                            for e in (sw["start_mm"], sw["end_mm"]):
                                for p, q in ((pts[0], pts[1]), (pts[-1], pts[-2])):
                                    if math.hypot(e["x"] - p[0], e["y"] - p[1]) > join_mm:
                                        continue
                                    sx, sy = sw["end_mm"]["x"] - sw["start_mm"]["x"], sw["end_mm"]["y"] - sw["start_mm"]["y"]
                                    tx, ty = p[0] - q[0], p[1] - q[1]
                                    nrm = (math.hypot(sx, sy) * math.hypot(tx, ty)) or 1.0
                                    if abs(sx * ty - sy * tx) / nrm <= math.sin(math.radians(10)):
                                        mark, how = sw["mark"], "tangent_to:" + sw["mark"]
                    if not mark:
                        continue
                    # bán kính thiết kế từ CAD kiến trúc (cặp mặt cách nhau bề dày) nếu khớp <= 40 mm
                    cad_radii = sorted(set(h[2] for h in cad_hints if math.hypot(h[0] - cx, h[1] - cy) <= 200))
                    for a, b in ((x, y) for x in cad_radii for y in cad_radii):
                        if abs(b - a - thickness_mm) <= 5 and abs(a - ri) <= 40 and abs(b - ro) <= 40:
                            rc_new = (a + b) / 2.0
                            pts = [(cx + rc_new * math.cos(a0 + (a1 - a0) * t / 20.0),
                                    cy + rc_new * math.sin(a0 + (a1 - a0) * t / 20.0)) for t in range(21)]
                            ri, ro, rc = a, b, rc_new
                            L = (a1 - a0) * rc
                            break
                    rnd = lambda p: {"x": round(p[0], 1), "y": round(p[1], 1)}
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    walls.append({"mark": mark, "curve": "arc", "start_mm": rnd(pts[0]), "mid_mm": rnd(pts[10]),
                                  "end_mm": rnd(pts[-1]), "center_mm": rnd((cx, cy)), "radius_mm": round(rc, 1),
                                  "faces_mm": [round(ri, 1), round(ro, 1)], "thickness_mm": thickness_mm,
                                  "mark_from": how,
                                  "length_mm": round(L), "hatch_per_m": round(per_m, 1),
                                  "bbox_mm": [round(min(xs) - thickness_mm / 2.0), round(min(ys) - thickness_mm / 2.0),
                                              round(max(xs) + thickness_mm / 2.0), round(max(ys) + thickness_mm / 2.0)]})
    # bỏ trùng (cùng tâm/bán kính, chồng góc)
    out = []
    for w in sorted(walls, key=lambda w: -w["length_mm"]):
        if not any(abs(w["radius_mm"] - o["radius_mm"]) < 30 and
                   math.hypot(w["center_mm"]["x"] - o["center_mm"]["x"], w["center_mm"]["y"] - o["center_mm"]["y"]) < 100 and
                   math.hypot(w["mid_mm"]["x"] - o["mid_mm"]["x"], w["mid_mm"]["y"] - o["mid_mm"]["y"]) < o["length_mm"] / 2
                   for o in out):
            out.append(w)
    return [w for w in out if w["hatch_per_m"] >= min_hatch_per_m]


def _arc_set_end(w, which, pt):
    """Đặt lại đầu (which='start'|'end') của tường cong tại điểm pt trên đường tròn; tính lại mid/length/bbox."""
    cx, cy, r = w["center_mm"]["x"], w["center_mm"]["y"], w["radius_mm"]
    ang = lambda p: math.atan2(p["y"] - cy, p["x"] - cx)
    a_s, a_m, a_e = ang(w["start_mm"]), ang(w["mid_mm"]), ang(w["end_mm"])
    sweep = ((a_m - a_s + math.pi) % (2 * math.pi) - math.pi) * 2.0     # có dấu (CCW > 0)
    a_new = math.atan2(pt[1] - cy, pt[0] - cx)
    if which == "start":
        a_s = a_new
        sweep = (a_e - a_s) % (2 * math.pi) if sweep > 0 else -((a_s - a_e) % (2 * math.pi))
    else:
        sweep = (a_new - a_s) % (2 * math.pi) if sweep > 0 else -((a_s - a_new) % (2 * math.pi))
    a_e = a_s + sweep
    rnd = lambda a: {"x": round(cx + r * math.cos(a), 1), "y": round(cy + r * math.sin(a), 1)}
    w["start_mm"], w["mid_mm"], w["end_mm"] = rnd(a_s), rnd(a_s + sweep / 2.0), rnd(a_e)
    w["length_mm"] = round(abs(sweep) * r)
    pts = [(cx + r * math.cos(a_s + sweep * t / 20.0), cy + r * math.sin(a_s + sweep * t / 20.0)) for t in range(21)]
    h = w.get("thickness_mm", 200) / 2.0
    w["bbox_mm"] = [round(min(p[0] for p in pts) - h), round(min(p[1] for p in pts) - h),
                    round(max(p[0] for p in pts) + h), round(max(p[1] for p in pts) + h)]


def tangent_joins(curved, straight, max_gap_mm: float = 600.0, tangent_tol_mm: float = 40.0):
    """
    Nối tường cong với tường thẳng nối tiếp tuyến: điểm tiếp tuyến T = chân đường vuông góc từ tâm cung xuống
    tim tường thẳng (khi |khoảng cách - R| <= tangent_tol). Kéo đầu tường thẳng gần nhất và đầu cung về T.
    Sửa tại chỗ; trả danh sách [(mark cong, mark thang, khe_truoc_mm)].
    """
    out = []
    for w in curved:
        cx, cy, r = w["center_mm"]["x"], w["center_mm"]["y"], w["radius_mm"]
        for which in ("start", "end"):
            e = w[which + "_mm"]
            best = None
            for s in straight:
                ax, ay = s["start_mm"]["x"], s["start_mm"]["y"]
                bx, by = s["end_mm"]["x"], s["end_mm"]["y"]
                L = math.hypot(bx - ax, by - ay)
                if L < 1:
                    continue
                ux, uy = (bx - ax) / L, (by - ay) / L
                t = (cx - ax) * ux + (cy - ay) * uy
                tx, ty = ax + t * ux, ay + t * uy
                if abs(math.hypot(cx - tx, cy - ty) - r) > tangent_tol_mm:
                    continue
                for end in ("start_mm", "end_mm"):
                    gap = math.hypot(s[end]["x"] - e["x"], s[end]["y"] - e["y"])
                    if gap <= max_gap_mm and math.hypot(tx - e["x"], ty - e["y"]) <= max_gap_mm and \
                            (best is None or gap < best[0]):
                        best = (gap, s, end, (tx, ty))
            if best:
                gap, s, end, T = best
                s[end] = {"x": round(T[0], 1), "y": round(T[1], 1)}
                s["length_mm"] = round(math.hypot(s["end_mm"]["x"] - s["start_mm"]["x"], s["end_mm"]["y"] - s["start_mm"]["y"]))
                _arc_set_end(w, which, T)
                out.append((w["mark"], s["mark"], round(gap)))
    return out


def align_cad_hints(cad_hints, pdf_hints, match_mm: float = 400.0):
    """
    Cung CAD kiến trúc lệch hệ thống so với bản kết cấu (~100 mm ở dự án 250793): đo độ lệch = trung vị
    (tâm PDF - tâm CAD) của các cặp cùng bán kính (+-60 mm), tâm gần nhau; dời mọi cung CAD theo độ lệch đó.
    Trả (hints_da_doi, (dx, dy), so_cap).
    """
    dx, dy = [], []
    for px, py, pr in pdf_hints:
        best = None
        for cx, cy, cr in cad_hints:
            d = math.hypot(px - cx, py - cy)
            if d <= match_mm and abs(pr - cr) <= 60 and (best is None or d < best[0]):
                best = (d, px - cx, py - cy)
        if best:
            dx.append(best[1])
            dy.append(best[2])
    if not dx:
        return list(cad_hints), (0.0, 0.0), 0
    dx.sort()
    dy.sort()
    ox, oy = dx[len(dx) // 2], dy[len(dy) // 2]
    return [(cx + ox, cy + oy, cr) for cx, cy, cr in cad_hints], (round(ox, 1), round(oy, 1)), len(dx)


def pdf_circle_hints(segs, r_range_mm=(1000.0, 20000.0), fit_tol_mm: float = 15.0):
    """Tâm/bán kính gợi ý từ các chuỗi nét ngắn khớp tròn tốt trên chính trang PDF."""
    short = [s for s in segs if 20.0 <= math.hypot(s[2] - s[0], s[3] - s[1]) <= 700.0]
    out = []
    for pts in _chains(short):
        f = _fit_circle(pts)
        if f and f[3] <= fit_tol_mm and r_range_mm[0] <= f[2] <= r_range_mm[1]:
            a0, a1 = _arc_interval(pts, f[0], f[1])
            if (a1 - a0) * f[2] >= 600:
                out.append((f[0], f[1], f[2]))
    return out


def extract_curved_walls(segs, labels: List[Dict], hatch: _PointGrid, thickness_mm: float = 200.0,
                         min_len_mm: float = 900.0, label_radius_mm: float = 2000.0,
                         seg_len_mm=(20.0, 700.0), r_range_mm=(1000.0, 40000.0), fit_tol_mm: float = 15.0,
                         centre_tol_mm: float = 40.0, thick_tol_mm: float = 20.0, bin_mm: float = 250.0,
                         min_hatch_per_bin: int = 2, max_gap_bins: int = 2,
                         min_hatch_per_m: float = 15.0) -> List[Dict]:
    """
    (Cách cũ - chỉ ghép chuỗi PDF; dùng extract_curved_walls_guided.) segs: đoạn thẳng mm Revit.
    """
    short = [s for s in segs if seg_len_mm[0] <= math.hypot(s[2] - s[0], s[3] - s[1]) <= seg_len_mm[1]]
    arcs = []
    for pts in _chains(short):
        f = _fit_circle(pts)
        if not f:
            continue
        cx, cy, r, err = f
        if err > fit_tol_mm or not (r_range_mm[0] <= r <= r_range_mm[1]):
            continue
        a0, a1 = _arc_interval(pts, cx, cy)
        if (a1 - a0) * r < 600:
            continue
        arcs.append({"cx": cx, "cy": cy, "r": r, "iv": (a0, a1)})
    # ghép cặp cung đồng tâm cách nhau đúng bề dày
    cands = []
    for A in arcs:
        for B in arcs:
            if B["r"] <= A["r"] or math.hypot(A["cx"] - B["cx"], A["cy"] - B["cy"]) > centre_tol_mm:
                continue
            if abs(B["r"] - A["r"] - thickness_mm) > thick_tol_mm:
                continue
            ov = _interval_overlap(A["iv"], B["iv"])
            if ov:
                cands.append(((A["cx"] + B["cx"]) / 2, (A["cy"] + B["cy"]) / 2, (A["r"] + B["r"]) / 2, ov))
    # gộp các đoạn cùng tâm/bán kính có khoảng góc nối nhau
    groups = []
    for cx, cy, rc, (lo, hi) in sorted(cands, key=lambda c: c[3][0]):
        for g in groups:
            if math.hypot(g["cx"] - cx, g["cy"] - cy) <= centre_tol_mm and abs(g["r"] - rc) <= thick_tol_mm:
                ov = _interval_overlap((g["lo"] - 0.05, g["hi"] + 0.05), (lo, hi))
                if ov:
                    shift = round(((g["lo"] + g["hi"]) - (lo + hi)) / 2 / (2 * math.pi)) * 2 * math.pi
                    g["lo"], g["hi"] = min(g["lo"], lo + shift), max(g["hi"], hi + shift)
                    break
        else:
            groups.append({"cx": cx, "cy": cy, "r": rc, "lo": lo, "hi": hi})
    half = thickness_mm / 2.0 - 15.0
    walls = []
    for g in groups:
        cx, cy, rc = g["cx"], g["cy"], g["r"]
        nb = max(1, int(math.ceil((g["hi"] - g["lo"]) * rc / bin_mm)))
        hot = []
        for k in range(nb):
            a = g["lo"] + (k + 0.5) / nb * (g["hi"] - g["lo"])
            px, py = cx + rc * math.cos(a), cy + rc * math.sin(a)
            hot.append(hatch.count_in_box(px - half, py - half, px + half, py + half) >= min_hatch_per_bin)
        # đoạn hatch liên tục dài nhất (cho phép hở <= max_gap_bins ô)
        best, i = None, 0
        while i < nb:
            if not hot[i]:
                i += 1
                continue
            j, gap, k = i, 0, i
            while k + 1 < nb:
                if hot[k + 1]:
                    gap, j = 0, k + 1
                elif gap < max_gap_bins:
                    gap += 1
                else:
                    break
                k += 1
            if best is None or j - i > best[1] - best[0]:
                best = (i, j)
            i = j + 1
        if not best:
            continue
        lo = g["lo"] + best[0] / float(nb) * (g["hi"] - g["lo"])
        hi = g["lo"] + (best[1] + 1) / float(nb) * (g["hi"] - g["lo"])
        L = (hi - lo) * rc
        if L < min_len_mm:
            continue
        pts = [(cx + rc * math.cos(lo + (hi - lo) * t / 20.0), cy + rc * math.sin(lo + (hi - lo) * t / 20.0))
               for t in range(21)]
        n = sum(hatch.count_in_box(p[0] - half, p[1] - half, p[0] + half, p[1] + half) for p in pts[::2])
        per_m = n * 1000.0 / (11 * 2 * half)
        mark, dbest = None, None
        for lb in labels:
            d = min(math.hypot(lb["x"] - p[0], lb["y"] - p[1]) for p in pts)
            if d <= label_radius_mm and (dbest is None or d < dbest):
                dbest, mark = d, lb["mark"]
        if not mark:
            continue
        rnd = lambda p: {"x": round(p[0], 1), "y": round(p[1], 1)}
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        walls.append({"mark": mark, "curve": "arc", "start_mm": rnd(pts[0]), "mid_mm": rnd(pts[10]),
                      "end_mm": rnd(pts[-1]), "center_mm": rnd((cx, cy)), "radius_mm": round(rc, 1),
                      "thickness_mm": thickness_mm, "length_mm": round(L), "hatch_per_m": round(per_m, 1),
                      "bbox_mm": [round(min(xs) - thickness_mm / 2.0), round(min(ys) - thickness_mm / 2.0),
                                  round(max(xs) + thickness_mm / 2.0), round(max(ys) + thickness_mm / 2.0)]})
    return [w for w in walls if w["hatch_per_m"] >= min_hatch_per_m]
