# -*- coding: utf-8 -*-
"""
slab_edge_smoother.py - Làm trơn viền sàn bóc tách từ PDF trước khi dựng Revit.

Lỗi gặp ở 250793 (L1/L2): mép ban công tròn có vạch ký hiệu precast (PBS1) vẽ cách đều dọc cung -> viền sàn
đi theo từng vạch thành "răng lược" (khấc ~40 x 130 mm mỗi 150 mm), và mọi cung là chuỗi đoạn thẳng.

  smooth_partition(polys)  -> lấp khấc hẹp (closing, mối nối mitre giữ góc vuông), bỏ gai mảnh, không chồng tấm kề.
  ring_with_arcs(ring)     -> [{"x","y"(,"mid":{"x","y"})}]: đỉnh có "mid" = cạnh tới đỉnh kế là CUNG qua mid.
Toạ độ mm Revit.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Polygon
from shapely.ops import unary_union

Pt = Tuple[float, float]
MITRE = dict(join_style=2, mitre_limit=10.0)


def _parts(g) -> List[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [x for x in getattr(g, "geoms", []) if isinstance(x, Polygon)]


def close_notches(g: Polygon, notch_mm: float = 120.0, spike_mm: float = 20.0) -> Polygon:
    """Lấp khấc lõm hẹp hơn notch_mm và bỏ gai mảnh hơn spike_mm, giữ góc vuông (mitre)."""
    d = notch_mm / 2.0
    c = g.buffer(d, **MITRE).buffer(-d, **MITRE)
    s = spike_mm / 2.0
    if s > 0:
        c = c.buffer(-s, **MITRE).buffer(s, **MITRE)
    parts = [p for p in _parts(c.buffer(0)) if p.area > 1e4]
    if not parts:
        return g
    return parts[0] if len(parts) == 1 else unary_union(parts)


def smooth_partition(polys: Sequence[Polygon], notch_mm: float = 120.0, spike_mm: float = 20.0,
                     gap_mm: float = 2.5, simplify_mm: float = 1.5) -> List[Optional[Polygon]]:
    """Làm trơn từng tấm của 1 tầng; phần nở lấn sang tấm khác bị cắt (cách >= gap_mm) -> không bao giờ chồng."""
    closed = [close_notches(p, notch_mm, spike_mm) for p in polys]
    out: List[Optional[Polygon]] = []
    for i, c in enumerate(closed):
        others = [polys[j] for j in range(len(polys)) if j != i] + [o for o in out if o is not None]
        if others:
            c = c.difference(unary_union(others).buffer(gap_mm, **MITRE))
        # không cho nở ra ngoài vùng gốc đã đóng khấc (tránh phình mép thật)
        c = c.intersection(closed[i]).buffer(0)
        parts = sorted(_parts(c), key=lambda p: -p.area)
        g = parts[0].simplify(simplify_mm, preserve_topology=True) if parts else None
        out.append(g if g is not None and g.is_valid and g.area > 0.2e6 else None)
    return out


def smooth_level(polys: Sequence[Polygon], thin_mm: float = 300.0, grow_mm: float = 300.0, notch_mm: float = 120.0,
                 gap_mm: float = 2.5, simplify_mm: float = 1.5, min_m2: float = 0.2,
                 spike_mm: float = 60.0) -> List[Optional[Polygon]]:
    """
    Làm trơn cả tầng khi viền "răng lược" bị chia xen kẽ giữa 2 tấm (vành precast mỏng dọc mép ban công):
      1. thân mỗi tấm = opening(thin_mm): bỏ phần mảnh hơn thin_mm (vành ~150 mm, răng);
      2. viền ngoài chung = union các tấm, lấp khấc < notch_mm;
      3. tấm lớn trước: nở grow_mm trong viền chung, không lấn thân tấm khác -> nhận lại vành/răng kề bên;
    Tấm chỉ gồm phần mảnh (vd dải 330 mỏng 150 mm dọc ban công) -> None (phần đó nhập vào tấm kề).
    """
    h = thin_mm / 2.0
    cores = []
    for p in polys:
        c = p.buffer(-h, **MITRE).buffer(h, **MITRE).intersection(p).buffer(0)
        cores.append(unary_union([q for q in _parts(c) if q.area >= min_m2 * 1e6]) if _parts(c) else Polygon())
    footprint = close_notches(unary_union(list(polys)).buffer(0), notch_mm, 0.0) if len(polys) > 1 else \
        close_notches(polys[0], notch_mm, 0.0)
    footprint = unary_union([footprint] + [close_notches(p, notch_mm, 0.0) for p in polys]).buffer(0)
    order = sorted(range(len(polys)), key=lambda i: -cores[i].area)
    out: List[Optional[Polygon]] = [None] * len(polys)
    taken = []
    for i in order:
        if cores[i].is_empty:
            continue
        others = [cores[j] for j in range(len(polys)) if j != i and not cores[j].is_empty] + taken
        g = cores[i].buffer(grow_mm, **MITRE).intersection(footprint)
        if others:
            g = g.difference(unary_union(others).buffer(gap_mm, **MITRE))
        # spike_mm: tai/gai nhô ra hẹp hơn 60 mm (vạch precast còn sót, vd 36 x 144 mm ở đỉnh cung) -> cắt
        g = close_notches(g.buffer(0), notch_mm, spike_mm)
        if others:
            g = g.difference(unary_union(others).buffer(gap_mm, **MITRE))
        parts = [p for p in _parts(g.buffer(0)) if p.area >= min_m2 * 1e6]
        if not parts:
            continue
        parts = [q if q.is_valid else p for p, q in ((p, p.simplify(simplify_mm, preserve_topology=True)) for p in parts)]
        out[i] = unary_union(parts) if len(parts) > 1 else parts[0]     # nhiều mảnh -> dựng thành nhiều tấm
        taken.append(out[i])
    # tấm chỉ gồm phần mảnh mà không tấm kề nào nhận lại -> giữ hình gốc (chỉ lấp khấc), không làm mất sàn
    for i, p in enumerate(polys):
        if out[i] is not None:
            continue
        g = close_notches(p, notch_mm, 0.0)
        if taken:
            g = g.difference(unary_union(taken).buffer(gap_mm, **MITRE))
        parts = [q for q in _parts(g.buffer(0)) if q.area >= min_m2 * 1e6]
        if parts:
            out[i] = unary_union(parts) if len(parts) > 1 else parts[0]
            taken.append(out[i])
    return out


def _circle(a: Pt, b: Pt, c: Pt) -> Optional[Tuple[float, float, float]]:
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def _turn(a: Pt, b: Pt, c: Pt) -> float:
    """Góc rẽ có dấu tại b (độ)."""
    a1 = math.atan2(b[1] - a[1], b[0] - a[0])
    a2 = math.atan2(c[1] - b[1], c[0] - b[0])
    return math.degrees((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)


def _fits(pts: Sequence[Pt], tol: float, rmin: float, rmax: float):
    if len(pts) < 4:
        return None
    circ = _circle(pts[0], pts[len(pts) // 2], pts[-1])
    if circ is None or not (rmin <= circ[2] <= rmax):
        return None
    ux, uy, r = circ
    if max(abs(math.hypot(x - ux, y - uy) - r) for x, y in pts) > tol:
        return None
    # cạnh cũng phải bám cung (trung điểm mỗi cạnh)
    for p, q in zip(pts, pts[1:]):
        mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        if abs(math.hypot(mx - ux, my - uy) - r) > tol:
            return None
    turns = [_turn(pts[i - 1], pts[i], pts[i + 1]) for i in range(1, len(pts) - 1)]
    if any(abs(t) > 25 for t in turns) or (min(turns) < -0.5 and max(turns) > 0.5):
        return None
    sweep = abs(sum(turns))
    return circ if sweep >= 10 else None


def ring_with_arcs(ring: Sequence[Pt], tol_mm: float = 20.0, rmin: float = 300.0, rmax: float = 60000.0,
                   min_pts: int = 4) -> List[Dict]:
    """Thay chuỗi đỉnh nằm trên cùng 1 đường tròn bằng cung (đỉnh đầu mang 'mid')."""
    pts = [tuple(p) for p in ring]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < min_pts + 2:
        return [{"x": round(x, 1), "y": round(y, 1)} for x, y in pts]
    # bắt đầu tại đỉnh góc gắt nhất (không nằm giữa cung)
    k = max(range(n), key=lambda i: abs(_turn(pts[i - 1], pts[i], pts[(i + 1) % n])))
    pts = pts[k:] + pts[:k]
    out, i = [], 0
    while i < n:
        best = None
        j = i + min_pts - 1
        while j < n + (0 if i else 0):
            seg = [pts[t % n] for t in range(i, j + 1)]
            if j - i + 1 > n:
                break
            c = _fits(seg, tol_mm, rmin, rmax)
            if c is None:
                if best is not None:
                    break
            else:
                best = (j, c)
            j += 1
        if best is None:
            out.append({"x": round(pts[i][0], 1), "y": round(pts[i][1], 1)})
            i += 1
            continue
        j, (ux, uy, r) = best
        a, b = pts[i], pts[j % n]
        a0 = math.atan2(a[1] - uy, a[0] - ux)
        sgn = 1 if sum(_turn(pts[t - 1], pts[t], pts[(t + 1) % n]) for t in range(i + 1, j)) > 0 else -1
        a1 = math.atan2(b[1] - uy, b[0] - ux)
        sweep = (a1 - a0) % (2 * math.pi) if sgn > 0 else -((a0 - a1) % (2 * math.pi))
        am = a0 + sweep / 2
        out.append({"x": round(a[0], 1), "y": round(a[1], 1),
                    "mid": {"x": round(ux + r * math.cos(am), 1), "y": round(uy + r * math.sin(am), 1)}})
        i = j
    return _merge_arcs(out, tol_mm * 1.5)


def _arc_mid_through(a: Pt, b: Pt, via: Pt, c: Tuple[float, float, float]) -> Pt:
    """Trung điểm cung a->b trên đường tròn c, đi qua phía có điểm via."""
    ux, uy, r = c
    a0 = math.atan2(a[1] - uy, a[0] - ux)
    av = math.atan2(via[1] - uy, via[0] - ux)
    a1 = math.atan2(b[1] - uy, b[0] - ux)
    ccw = (av - a0) % (2 * math.pi) < (a1 - a0) % (2 * math.pi)
    sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
    am = a0 + sweep / 2
    return ux + r * math.cos(am), uy + r * math.sin(am)


def _merge_arcs(items: List[Dict], tol: float, max_between: int = 6, max_gap_mm: float = 1500.0) -> List[Dict]:
    """
    Gộp cung bị chẻ: cung k ... cung m (liền nhau, hoặc kẹp tối đa max_between đoạn thẳng ngắn tổng < max_gap_mm)
    nằm trên cùng 1 đường tròn (mọi đỉnh và trung điểm cung lệch <= tol) -> 1 cung.
    """
    changed = True
    while changed and len(items) > 3:
        changed = False
        n = len(items)
        for k in range(n):
            p = items[k]
            if "mid" not in p:
                continue
            gap = 0.0
            for s in range(1, max_between + 2):
                m = (k + s) % n
                if m == k:
                    break
                q = items[m]
                if "mid" in q:
                    end = items[(m + 1) % n]
                    a, b = (p["x"], p["y"]), (end["x"], end["y"])
                    via = (q["x"], q["y"])
                    c = _circle(a, via, b)
                    chk = [(items[(k + t) % n]["x"], items[(k + t) % n]["y"]) for t in range(1, s + 1)]
                    chk += [(it["mid"]["x"], it["mid"]["y"]) for it in (p, q)]
                    if c is not None and all(abs(math.hypot(x - c[0], y - c[1]) - c[2]) <= tol for x, y in chk):
                        mx, my = _arc_mid_through(a, b, via, c)
                        items[k] = {"x": p["x"], "y": p["y"], "mid": {"x": round(mx, 1), "y": round(my, 1)}}
                        for idx in sorted([(k + t) % n for t in range(1, s + 1)], reverse=True):
                            del items[idx]
                        changed = True
                    break
                nxt = items[(m + 1) % n]
                gap += math.hypot(nxt["x"] - q["x"], nxt["y"] - q["y"])
                if gap > max_gap_mm:
                    break
            if changed:
                break
    return items


def ring_points(ring_items: Sequence[Dict], step_deg: float = 5.0) -> List[Pt]:
    """Rời rạc hoá vòng có cung (để kiểm tra hình học / diện tích)."""
    pts: List[Pt] = []
    n = len(ring_items)
    for k, it in enumerate(ring_items):
        a = (it["x"], it["y"])
        pts.append(a)
        if "mid" in it:
            b = ring_items[(k + 1) % n]
            c = _circle(a, (it["mid"]["x"], it["mid"]["y"]), (b["x"], b["y"]))
            if c is None:
                continue
            ux, uy, r = c
            a0 = math.atan2(a[1] - uy, a[0] - ux)
            am = math.atan2(it["mid"]["y"] - uy, it["mid"]["x"] - ux)
            a1 = math.atan2(b["y"] - uy, b["x"] - ux)
            ccw = (am - a0) % (2 * math.pi) < (a1 - a0) % (2 * math.pi)
            sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
            steps = max(2, int(abs(math.degrees(sweep)) / step_deg))
            for s in range(1, steps):
                t = a0 + sweep * s / steps
                pts.append((ux + r * math.cos(t), uy + r * math.sin(t)))
    return pts
