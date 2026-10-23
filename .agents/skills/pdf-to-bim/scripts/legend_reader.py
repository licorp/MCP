# -*- coding: utf-8 -*-
"""
legend_reader.py - Đọc LEGEND của trang PDF (ký hiệu hatch/nền/nét -> ý nghĩa) và phân loại vùng trên mặt bằng
theo đúng legend đó (thay vì đoán theo hình học).

Mỗi bản vẽ đều có legend giải thích hatch. Bộ HPCE 250793 (marking plans):
    nền xám + viền nét đứt            -> WALL/COLUMN UNDER          (cấu kiện TẦNG DƯỚI, chỉ thể hiện)
    nền trắng + hatch chấm bê tông   -> CONCRETE WALL/COLUMN OVER   (bắt đầu từ tầng này đi lên)
    nền xám + hatch chấm bê tông     -> CONCRETE WALL/COLUMN UNDER AND OVER
    vòng tròn có số                   -> SLAB THICKNESS
    S.O.G                             -> SLAB ON GROUND
    ký hiệu STEP                      -> STEP IN TOP OF SLAB
Làm việc trong hệ toạ độ "nhìn thấy" của trang (đã xoay theo page.rotation) để chữ legend nằm ngang.
"""
import math
from typing import Dict, List, Optional, Tuple

GREY_MIN, GREY_MAX = 0.5, 0.92      # nền xám (0.75 trên bộ HPCE)


def _is_grey(rgb) -> bool:
    if not rgb:
        return False
    return all(GREY_MIN <= c <= GREY_MAX for c in rgb) and max(rgb) - min(rgb) < 0.05


def _is_white(rgb) -> bool:
    return bool(rgb) and min(rgb) >= 0.97


def _meaning(text: str) -> Optional[str]:
    t = text.upper()
    if "PRECAST" in t:
        return "PRECAST_UNDER_AND_OVER" if "UNDER AND OVER" in t else ("PRECAST_OVER" if "OVER" in t else "PRECAST")
    if "UNDER AND OVER" in t:
        return "UNDER_AND_OVER"
    if "WALL" in t and "OVER" in t:
        return "OVER"
    if "WALL" in t and "UNDER" in t:
        return "UNDER"
    if "SLAB THICKNESS" in t:
        return "SLAB_THICKNESS"
    if "SLAB ON GROUND" in t:
        return "SOG"
    if "STEP" in t:
        return "STEP"
    return None


def read_legend(page, drawings=None, search_pt: float = 450.0) -> Dict:
    """
    Trả {"found": bool, "rows": [{"text", "meaning", "grey_fill", "white_fill", "hatch_strokes", "dashed"}],
         "styles": {meaning: {...}}}.
    """
    drawings = drawings if drawings is not None else page.get_drawings()
    M = page.rotation_matrix
    hits = page.search_for("LEGEND")
    if not hits:
        return {"found": False, "rows": [], "styles": {}}
    head = hits[0] * M
    rows = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = " ".join(s["text"] for s in ln["spans"]).strip()
            if not t.upper().startswith("DENOTES"):
                continue
            r = fitz_rect(ln["bbox"]) * M
            if abs(r.x0 - head.x0) > search_pt or not (head.y0 - 20 <= r.y0 <= head.y0 + search_pt):
                continue
            rows.append((r, t))
    rows.sort(key=lambda x: x[0].y0)
    vis = [(d, d["rect"] * M) for d in drawings if d["rect"].width < 150 and d["rect"].height < 150]
    out = []
    for i, (r, t) in enumerate(rows):
        # ô ký hiệu: bên trái dòng chữ, cùng dải ngang (không lấn sang dòng trên/dưới)
        top = (rows[i - 1][0].y1 + r.y0) / 2.0 if i > 0 else r.y0 - 15
        bot = (r.y1 + rows[i + 1][0].y0) / 2.0 if i + 1 < len(rows) else r.y1 + 15
        x0 = head.x0 - 15
        grey = white = dashed = False
        strokes = 0
        for d, vr in vis:
            cx, cy = (vr.x0 + vr.x1) / 2.0, (vr.y0 + vr.y1) / 2.0
            if not (x0 <= cx <= r.x0 - 1 and top <= cy <= bot):
                continue
            if d.get("fill") is not None:
                grey = grey or _is_grey(d["fill"])
                white = white or _is_white(d["fill"])
            if d.get("type") in ("s", "fs"):
                da = str(d.get("dashes") or "")
                if da and da not in ("[] 0", "[] 0.0", "None"):
                    dashed = True
                for it in d["items"]:
                    if it[0] == "l":
                        L = math.hypot(it[2].x - it[1].x, it[2].y - it[1].y)
                        if L < 1.5:                          # chấm/tam giác hatch rất ngắn
                            strokes += 1
        out.append({"text": t, "meaning": _meaning(t), "grey_fill": grey, "white_fill": white,
                    "hatch_strokes": strokes, "dashed": dashed})
    styles = {o["meaning"]: o for o in out if o["meaning"]}
    return {"found": True, "rows": out, "styles": styles}


def fitz_rect(b):
    import pymupdf as fitz  # noqa
    return fitz.Rect(b)


class RegionClassifier(object):
    """
    Phân loại 1 điểm/1 đoạn trên mặt bằng theo legend: có nền xám? có hatch chấm bê tông? (toạ độ PDF gốc).
    """

    def __init__(self, page, drawings=None, cell: float = 20.0, hatch_max_pt: float = 1.5):
        drawings = drawings if drawings is not None else page.get_drawings()
        self.cell = cell
        self.grey = []                    # đa giác/ hình chữ nhật nền xám
        self.hatch = {}
        for d in drawings:
            if d.get("fill") is not None and _is_grey(d["fill"]):
                pts = []
                for it in d["items"]:
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
                if len(pts) >= 3:
                    self.grey.append((d["rect"], _dedupe(pts)))
            if d.get("type") in ("s", "fs"):
                for it in d["items"]:
                    if it[0] == "l":
                        a, b = it[1], it[2]
                        if math.hypot(b.x - a.x, b.y - a.y) < hatch_max_pt:
                            k = (int(a.x // cell), int(a.y // cell))
                            self.hatch.setdefault(k, []).append(((a.x + b.x) / 2.0, (a.y + b.y) / 2.0))

    def grey_at(self, x, y) -> bool:
        for r, poly in self.grey:
            if r.x0 - 0.5 <= x <= r.x1 + 0.5 and r.y0 - 0.5 <= y <= r.y1 + 0.5 and _in_poly(x, y, poly):
                return True
        return False

    def hatch_near(self, x, y, rad: float) -> int:
        n = 0
        for i in range(int((x - rad) // self.cell), int((x + rad) // self.cell) + 1):
            for j in range(int((y - rad) // self.cell), int((y + rad) // self.cell) + 1):
                for hx, hy in self.hatch.get((i, j), ()):
                    if (hx - x) ** 2 + (hy - y) ** 2 <= rad * rad:
                        n += 1
        return n

    def classify_samples(self, samples_pt: List[Tuple[float, float]], hatch_rad_pt: float) -> Dict:
        """Mẫu điểm dọc tim cấu kiện -> tỉ lệ nền xám, tỉ lệ có hatch -> ý nghĩa theo legend."""
        g = sum(1 for x, y in samples_pt if self.grey_at(x, y))
        h = sum(1 for x, y in samples_pt if self.hatch_near(x, y, hatch_rad_pt) > 0)
        n = max(1, len(samples_pt))
        gr, hr = g / float(n), h / float(n)
        if gr >= 0.5 and hr >= 0.5:
            m = "UNDER_AND_OVER"
        elif hr >= 0.5:
            m = "OVER"
        elif gr >= 0.5:
            m = "UNDER"
        else:
            m = "NONE"
        return {"meaning": m, "grey_ratio": round(gr, 2), "hatch_ratio": round(hr, 2)}


def _wall_samples(w, n=19):
    s, e = w["start_mm"], w["end_mm"]
    if w.get("mid_mm") and w.get("center_mm"):
        cx, cy, r = w["center_mm"]["x"], w["center_mm"]["y"], w["radius_mm"]
        a0 = math.atan2(s["y"] - cy, s["x"] - cx)
        am = math.atan2(w["mid_mm"]["y"] - cy, w["mid_mm"]["x"] - cx)
        d = (am - a0 + math.pi) % (2 * math.pi) - math.pi
        return [(cx + r * math.cos(a0 + 2 * d * k / (n + 1.0)), cy + r * math.sin(a0 + 2 * d * k / (n + 1.0)))
                for k in range(1, n + 1)]
    return [(s["x"] + (e["x"] - s["x"]) * k / (n + 1.0), s["y"] + (e["y"] - s["y"]) * k / (n + 1.0)) for k in range(1, n + 1)]


def classify_by_legend(page, transformer, columns=(), walls=(), scale: float = 100.0) -> Dict:
    """
    Gắn 'legend' (OVER | UNDER_AND_OVER | UNDER | NONE) cho từng cột/tường (toạ độ mm Revit) theo legend trang.
    Trả {"legend_found", "legend_rows", "keep_columns", "keep_walls", "under_only": [...], "summary": {...}}.
    Cấu kiện CHỈ là UNDER (nền xám, không hatch bê tông) thuộc tầng DƯỚI -> không dựng từ tầng này.
    Trang không có legend kiểu UNDER/OVER -> giữ nguyên, không lọc.
    """
    from column_calibration import PT_TO_MM
    leg = read_legend(page)
    has_style = leg["found"] and ("OVER" in leg["styles"] or "UNDER_AND_OVER" in leg["styles"])
    out = {"legend_found": leg["found"], "legend_rows": [(r["meaning"], r["text"]) for r in leg["rows"]],
           "keep_columns": list(columns), "keep_walls": list(walls), "under_only": [], "summary": {}}
    if not has_style:
        return out
    rc = RegionClassifier(page)
    mm = PT_TO_MM * scale
    summary = {}
    keep_c, keep_w, under = [], [], []
    for c in columns:
        p = transformer.to_pdf_pt(c["center"]["x"], c["center"]["y"])
        r = max(30.0, min(c.get("b_mm", 300), c.get("h_mm", 300)) / 2.0 - 20.0) / mm
        sm = [(p["x"] + 0.6 * r * math.cos(a), p["y"] + 0.6 * r * math.sin(a)) for a in [i * 0.785 for i in range(8)]]
        sm.append((p["x"], p["y"]))
        cl = rc.classify_samples(sm, r)
        c["legend"] = cl["meaning"]
        summary[("COL", cl["meaning"])] = summary.get(("COL", cl["meaning"]), 0) + 1
        (under if cl["meaning"] == "UNDER" else keep_c).append(c)
    for w in walls:
        sm = []
        for x, y in _wall_samples(w):
            p = transformer.to_pdf_pt(x, y)
            sm.append((p["x"], p["y"]))
        cl = rc.classify_samples(sm, (w.get("thickness_mm", 200) / 2.0 - 5.0) / mm)
        w["legend"] = cl["meaning"]
        summary[("WALL", cl["meaning"])] = summary.get(("WALL", cl["meaning"]), 0) + 1
        (under if cl["meaning"] == "UNDER" else keep_w).append(w)
    # Bảng cột (vd S150): hình có mã nhưng sai kích thước bảng -> nhận nhầm hình (vd vòng tròn chiều dày sàn)
    sched = {}
    try:
        import label_column_finder as lcf
        sched = lcf.read_column_schedule(page.parent) if columns else {}
    except Exception:  # pragma: no cover
        lcf = None
    if sched:
        bad = [c for c in keep_c + under if "center" in c and lcf.size_matches(c, sched) is False]
        if bad:
            out["size_mismatch"] = [{"mark": c.get("mark"), "shape": c.get("shape"), "b_mm": c.get("b_mm"),
                                     "h_mm": c.get("h_mm"), "schedule": sched.get((c.get("mark") or "").upper()),
                                     "at_mm": c.get("center")} for c in bad]
            keep_c = [c for c in keep_c if c not in bad]
            under = [u for u in under if u not in bad]
    # Nhãn ghi rõ hậu tố (u)/(o) -> ưu tiên hơn hatch (hatch chấm có thể bị nét sàn/ký hiệu khác che)
    label_info = apply_label_suffixes(page, transformer, keep_c + [c for c in under if "center" in c],
                                      keep_w + [w for w in under if "center" not in w], scale=scale,
                                      sched=sched)
    if label_info["labels"]:
        allc = keep_c + [c for c in under if "center" in c]
        allw = keep_w + [w for w in under if "center" not in w]
        # Nhãn (o) chưa có cột -> tìm đúng hình vector theo kích thước bảng cột, sát nhãn
        if sched and lcf is not None:
            from pdf_struct_parser import column_to_revit
            mmpt = PT_TO_MM * scale
            drawings = page.get_drawings()
            cpt = [transformer.to_pdf_pt(c["center"]["x"], c["center"]["y"]) for c in allc]
            # cột chỉ UNDER không chặn hình: cùng 1 hình có thể là 'CC4A (u)' dưới + 'CC4B (o)' trên
            taken = [(p["x"], p["y"]) for p, c in zip(cpt, allc) if c.get("legend") != "UNDER"]
            still = []
            for lb in label_info["unassigned"]:
                si = sched.get(lb["mark"])
                if lb["kind"] not in ("o", "uo") or not si:
                    still.append(lb)
                    continue
                feat = lcf.find_shape_for_label(page, {"x": lb["pdf_pt"][0], "y": lb["pdf_pt"][1], "mark": lb["mark"]},
                                                si, mmpt, drawings=drawings, taken_pt=taken)
                if not feat:
                    lb["note"] = "khong tim thay hinh vector dung kich thuoc bang cot gan nhan"
                    still.append(lb)
                    continue
                under_same = [c for p, c in zip(cpt, allc) if c.get("legend") == "UNDER"
                              and math.hypot(p["x"] - feat["x"], p["y"] - feat["y"]) * mmpt < 60.0
                              and sched.get((c.get("mark") or "").upper()) == si]
                if under_same:
                    c = under_same[0]
                    c["mark_below"], c["mark"] = c.get("mark"), lb["mark"]
                    c["legend"], c["legend_source"] = "UNDER_AND_OVER", "label+vector"
                    c["labels"] = (c.get("labels") or []) + ["%s(%s)" % (lb["mark"], lb["kind"])]
                    taken.append((feat["x"], feat["y"]))
                    label_info["found_by_label"] = label_info.get("found_by_label", 0) + 1
                    continue
                col = column_to_revit(feat, transformer)
                col.update({"legend": "OVER" if lb["kind"] == "o" else "UNDER_AND_OVER",
                            "legend_source": "label+vector", "labels": ["%s(%s)" % (lb["mark"], lb["kind"])],
                            "label_dist_mm": feat["dist_mm"]})
                allc.append(col)
                taken.append((feat["x"], feat["y"]))
                label_info["found_by_label"] = label_info.get("found_by_label", 0) + 1
            label_info["unassigned"] = still
        summary = {}
        keep_c = [c for c in allc if c["legend"] != "UNDER"]
        keep_w = [w for w in allw if w["legend"] != "UNDER"]
        under = [c for c in allc if c["legend"] == "UNDER"] + [w for w in allw if w["legend"] == "UNDER"]
        for c in allc:
            summary[("COL", c["legend"])] = summary.get(("COL", c["legend"]), 0) + 1
        for w in allw:
            summary[("WALL", w["legend"])] = summary.get(("WALL", w["legend"]), 0) + 1
        out["label_suffixes"] = label_info
    out.update({"keep_columns": keep_c, "keep_walls": keep_w,
                "under_only": [{"kind": "COL" if "center" in u else "WALL", "mark": u.get("mark"),
                                "at_mm": u.get("center") or u.get("start_mm")} for u in under],
                "summary": {"%s:%s" % k: v for k, v in summary.items()}})
    return out


import re as _re

_SUFFIX_RE = _re.compile(r"^([A-Z]{1,3}\d+[A-Z]?(?:\s?NLB)?)\s*\((U|O|U&O|UO|U/O)\)$", _re.I)
_COL_MARK_RE = _re.compile(r"^C{1,2}\d", _re.I)


def read_label_suffixes(page) -> List[Dict]:
    """
    Nhãn cấu kiện có hậu tố trên mặt bằng: 'CC3(u)', 'CC4B (o)', 'W1(o)'... -> [{mark, kind, x, y}] (toạ độ PDF).
    kind: 'u' (UNDER), 'o' (OVER), 'uo' (UNDER AND OVER). Hậu tố tách thành từ riêng ('CC3' '(u)') cũng nhận.
    """
    words = page.get_text("words")
    out = []
    for i, w in enumerate(words):
        t = w[4].strip()
        m = _SUFFIX_RE.match(t)
        if not m and i + 1 < len(words):
            nxt = words[i + 1]
            if abs((nxt[1] + nxt[3]) / 2.0 - (w[1] + w[3]) / 2.0) < 3 and 0 <= nxt[0] - w[2] < 8:
                m = _SUFFIX_RE.match(t + nxt[4].strip())
                if m:
                    w = (w[0], w[1], nxt[2], nxt[3])
        if not m:
            continue
        k = m.group(2).upper().replace("&", "").replace("/", "")
        out.append({"mark": m.group(1).upper().replace(" ", ""), "kind": {"U": "u", "O": "o"}.get(k, "uo"),
                    "x": (w[0] + w[2]) / 2.0, "y": (w[1] + w[3]) / 2.0})
    _attach_text_dirs(page, out)
    return out


def _attach_text_dirs(page, labels):
    """Hướng dòng chữ (dir) của từng nhãn từ get_text('dict') - mã tường viết DỌC theo tường."""
    try:
        d = page.get_text("dict")
    except Exception:
        return
    if not isinstance(d, dict):
        return
    lines = []
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            bb = ln.get("bbox")
            if bb and ln.get("dir"):
                lines.append(((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0, bb, tuple(ln["dir"])))
    for lb in labels:
        cands = [l for l in lines if l[2][0] - 1 <= lb["x"] <= l[2][2] + 1 and l[2][1] - 1 <= lb["y"] <= l[2][3] + 1]
        if cands:
            lb["dir"] = min(cands, key=lambda l: math.hypot(l[0] - lb["x"], l[1] - lb["y"]))[3]


def _seg_dist(px, py, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L2))
    return math.hypot(px - a[0] - t * dx, py - a[1] - t * dy)


def apply_label_suffixes(page, transformer, columns=(), walls=(), scale: float = 100.0,
                         max_col_mm: float = 2500.0, max_wall_mm: float = 1500.0,
                         stack_mm: float = 900.0, sched: Optional[Dict] = None,
                         arc_band_mm: float = 800.0, arc_dir_min: float = 0.9) -> Dict:
    """
    Gán mỗi nhãn có hậu tố cho cấu kiện GẦN NHẤT (cột: tâm; tường: đoạn tim), rồi quyết định legend theo nhãn:
      chỉ (u) -> UNDER; chỉ (o) -> OVER; có cả (u) và (o) / (u&o) -> UNDER_AND_OVER.
    Cột đổi mã qua sàn (vd 'CC4A (u)' + 'CC4B (o)' cùng vị trí) -> mark = mã của nhãn (o), giữ 'mark_below'.
    Cấu kiện không có nhãn hậu tố giữ kết quả hatch. Sửa trực tiếp các dict, trả thống kê.
    """
    from column_calibration import PT_TO_MM
    labels = read_label_suffixes(page)
    info = {"labels": len(labels), "applied_columns": 0, "applied_walls": 0, "unassigned": []}
    if not labels:
        return info
    mm = PT_TO_MM * scale
    cpts = [transformer.to_pdf_pt(c["center"]["x"], c["center"]["y"]) for c in columns]
    wsegs = []
    for w in walls:
        a = transformer.to_pdf_pt(w["start_mm"]["x"], w["start_mm"]["y"])
        b = transformer.to_pdf_pt(w["end_mm"]["x"], w["end_mm"]["y"])
        wsegs.append(((a["x"], a["y"]), (b["x"], b["y"])))
    got_c = [[] for _ in columns]
    got_w = [[] for _ in walls]
    # TƯỜNG CONG: mã lấy từ chữ gần nhất có thể là tường thẳng bên cạnh ('RW1 (u)' phía trên cung 'W1 (o)').
    # Nhãn có hậu tố nằm TRONG dải cung (|d - R| <= arc_band_mm, góc trong phạm vi cung) quyết định mã cung.
    for w in walls:
        if not (w.get("mid_mm") and w.get("center_mm") and w.get("radius_mm")):
            continue
        cpt = transformer.to_pdf_pt(w["center_mm"]["x"], w["center_mm"]["y"])
        R = w["radius_mm"] / mm
        angs = [math.atan2(p["y"] - cpt["y"], p["x"] - cpt["x"]) for p in
                (transformer.to_pdf_pt(w[k]["x"], w[k]["y"]) for k in ("start_mm", "mid_mm", "end_mm"))]
        a0, am, a1 = angs
        span = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        if (am - a0 + math.pi) % (2 * math.pi) - math.pi < 0 < span or \
                (am - a0 + math.pi) % (2 * math.pi) - math.pi > 0 > span:
            span = span - math.copysign(2 * math.pi, span)
        best = None
        for lb in labels:
            if _COL_MARK_RE.match(lb["mark"]):
                continue
            d = math.hypot(lb["x"] - cpt["x"], lb["y"] - cpt["y"])
            if abs(d - R) * mm > arc_band_mm:
                continue
            t = ((math.atan2(lb["y"] - cpt["y"], lb["x"] - cpt["x"]) - a0) + 2 * math.pi) % (2 * math.pi)
            t = t if span >= 0 else (2 * math.pi - t) % (2 * math.pi)
            if t > abs(span):
                continue
            if lb.get("dir"):
                # chữ phải song song tiếp tuyến cung tại vị trí nhãn (không nhận nhãn của tường thẳng bên cạnh)
                a = math.atan2(lb["y"] - cpt["y"], lb["x"] - cpt["x"])
                if abs(lb["dir"][0] * -math.sin(a) + lb["dir"][1] * math.cos(a)) < arc_dir_min:
                    continue
            # nhãn ở ĐẦU cung có thể thuộc tường thẳng nối tiếp -> ưu tiên nhãn xa 2 đầu cung nhất
            score = (-min(t, abs(span) - t), abs(d - R))
            if best is None or score < best[0]:
                best = (score, lb)
        info.setdefault("arcs", []).append({
            "mark_in": w.get("mark"), "radius_mm": w.get("radius_mm"), "span_deg": round(math.degrees(span), 1),
            "label": best and "%s(%s)" % (best[1]["mark"], best[1]["kind"]),
            "near": sorted([("%s(%s)" % (lb["mark"], lb["kind"]),
                             round((math.hypot(lb["x"] - cpt["x"], lb["y"] - cpt["y"]) - R) * mm))
                            for lb in labels if not _COL_MARK_RE.match(lb["mark"])
                            and abs(math.hypot(lb["x"] - cpt["x"], lb["y"] - cpt["y"]) - R) * mm < 3000],
                           key=lambda x: abs(x[1]))[:5]})
        if best and best[1]["mark"] != (w.get("mark") or "").upper():
            w["mark_from_text"] = w.get("mark")
            w["mark"] = best[1]["mark"]
    col_labels = [lb for lb in labels if _COL_MARK_RE.match(lb["mark"])]
    pending = []
    # 1) nhãn cột chỉ gán cho cột CÙNG MÃ gần nhất
    for lb in col_labels:
        cands = [i for i, c in enumerate(columns) if (c.get("mark") or "").upper() == lb["mark"]]
        best = min(cands, key=lambda i: math.hypot(cpts[i]["x"] - lb["x"], cpts[i]["y"] - lb["y"]), default=None)
        if best is not None and math.hypot(cpts[best]["x"] - lb["x"], cpts[best]["y"] - lb["y"]) * mm <= max_col_mm:
            got_c[best].append(lb)
            lb["_col"] = best
        else:
            pending.append(lb)
    # 2) nhãn đổi mã qua sàn ('CC4A (u)' / 'CC4B (o)' xếp chồng): bám theo nhãn đã gán nằm sát nó
    stack_pt = stack_mm / mm
    for lb in pending:
        near = [o for o in col_labels if "_col" in o and o is not lb
                and math.hypot(o["x"] - lb["x"], o["y"] - lb["y"]) <= stack_pt]
        if near and sched:
            # mã mới phải CÙNG kích thước bảng cột với hình đang có (CC4A -> CC4B 800x300); khác -> tìm hình riêng
            def _same(o):
                a, b = sched.get(o["mark"]), sched.get(lb["mark"])
                return bool(a and b) and a == b
            near = [o for o in near if _same(o)]
        if near:
            o = min(near, key=lambda o: math.hypot(o["x"] - lb["x"], o["y"] - lb["y"]))
            got_c[o["_col"]].append(lb)
        else:
            info["unassigned"].append({"mark": lb["mark"], "kind": lb["kind"],
                                       "pdf_pt": [round(lb["x"], 1), round(lb["y"], 1)],
                                       "note": "khong co cot cung ma duoc boc tach gan nhan"})
    for lb in labels:
        if _COL_MARK_RE.match(lb["mark"]) or not wsegs:   # không truyền tường -> nhãn tường không xét ở đây
            continue
        else:
            # nhãn tường chỉ gán cho tường CÙNG MÃ (RW1 (u) cạnh US1 (o) không được làm RW1 thành OVER)
            same = [i for i, w in enumerate(walls) if (w.get("mark") or "").upper().replace(" ", "") == lb["mark"]]
            best = min(same, key=lambda i: _seg_dist(lb["x"], lb["y"], *wsegs[i]), default=None)
            if best is not None and _seg_dist(lb["x"], lb["y"], *wsegs[best]) * mm <= max_wall_mm:
                got_w[best].append(lb)
                continue
        info["unassigned"].append({"mark": lb["mark"], "kind": lb["kind"], "pdf_pt": [round(lb["x"], 1), round(lb["y"], 1)]})

    def decide(el, lbs, is_col):
        kinds = set(l["kind"] for l in lbs)
        el["legend_hatch"] = el.get("legend")
        el["legend_source"] = "label"
        el["labels"] = ["%s(%s)" % (l["mark"], l["kind"]) for l in lbs]
        if "uo" in kinds or ("u" in kinds and "o" in kinds):
            el["legend"] = "UNDER_AND_OVER"
        elif "o" in kinds:
            el["legend"] = "OVER"
        else:
            el["legend"] = "UNDER"
        over = [l for l in lbs if l["kind"] in ("o", "uo")]
        if is_col and over and over[0]["mark"] != el.get("mark"):
            el["mark_below"] = el.get("mark")
            el["mark"] = over[0]["mark"]

    for c, lbs in zip(columns, got_c):
        if lbs:
            decide(c, lbs, True)
            info["applied_columns"] += 1
        else:
            c.setdefault("legend_source", "hatch")
    for w, lbs in zip(walls, got_w):
        if lbs:
            decide(w, lbs, False)
            info["applied_walls"] += 1
        else:
            w.setdefault("legend_source", "hatch")
    return info


def _dedupe(pts):
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-3 or abs(p[1] - out[-1][1]) > 1e-3:
            out.append(p)
    return out


def _in_poly(x, y, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if xi > x:
                inside = not inside
    return inside
