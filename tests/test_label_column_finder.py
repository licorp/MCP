# -*- coding: utf-8 -*-
"""Cot theo nhan (u)/(o) + bang cot: label_column_finder & legend_reader.apply_label_suffixes."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".agents", "skills", "pdf-to-bim", "scripts"))

import label_column_finder as lcf  # noqa: E402
import legend_reader as lgd  # noqa: E402

SCHED = {"CC1B": {"shape": "round", "d": 400}, "CC4A": {"shape": "rect", "b": 800, "h": 300},
         "CC4B": {"shape": "rect", "b": 800, "h": 300}, "CC6": {"shape": "rect", "b": 500, "h": 200}}
MMPT = 25.4 / 72.0 * 100.0          # 1 pt = 35.28 mm o ti le 1:100


def test_size_matches_rejects_slab_bubble_and_merged_rect():
    assert lcf.size_matches({"mark": "CC1B", "shape": "round", "diameter_mm": 800}, SCHED) is False
    assert lcf.size_matches({"mark": "CC1B", "shape": "round", "diameter_mm": 400}, SCHED) is True
    assert lcf.size_matches({"mark": "CC6", "shape": "rect", "b_mm": 300, "h_mm": 650}, SCHED) is False
    assert lcf.size_matches({"mark": "CC4B", "shape": "rect", "b_mm": 300, "h_mm": 800}, SCHED) is True
    assert lcf.size_matches({"mark": "XX9", "shape": "rect", "b_mm": 1, "h_mm": 1}, SCHED) is None


def test_circle_from_loose_segments():
    R = 200.0 / MMPT
    cx, cy = 100.0, 50.0
    n = 24
    pts = [(cx + R * math.cos(2 * math.pi * k / n), cy + R * math.sin(2 * math.pi * k / n)) for k in range(n)]
    segs = [(pts[k], pts[(k + 1) % n]) for k in range(n) if k % 6 != 5]   # hở vài đoạn như nét vẽ thật
    segs += [((90.0, 40.0), (110.0, 40.0))]                                 # nét nhiễu
    f = lcf._circle_from_segments(segs, R, 101.0, 49.0, 60.0)
    assert f and abs(f["x"] - cx) < 0.15 and abs(f["y"] - cy) < 0.15


def test_rect_from_segments_with_edge_merged_into_wall():
    B, H = 500.0 / MMPT, 200.0 / MMPT
    x0, y0 = 10.0, 20.0
    segs = [((x0 - 30.0, y0), (x0 + B + 30.0, y0)),       # cạnh trên trùng mép tường dài
            ((x0, y0 + H), (x0 + B, y0 + H)),
            ((x0, y0), (x0, y0 + H)), ((x0 + B, y0), (x0 + B, y0 + H))]
    f = lcf._rect_from_segments(segs, B, H, 0.12, x0 + B / 2, y0 - 10, 60.0)
    assert f and abs(f["x"] - (x0 + B / 2)) < 0.2 and abs(f["y"] - (y0 + H / 2)) < 0.2


class _T(object):
    """Transformer don gian: mm Revit = pt * MMPT, Y dao dau."""
    scale = MMPT

    def to_pdf_pt(self, x, y):
        return {"x": x / MMPT, "y": -y / MMPT}


class _Page(object):
    def __init__(self, words):
        self._w = words

    def get_text(self, kind="text"):
        return self._w


def _word(x, y, t, w=10.0):
    return (x, y - 2, x + w, y + 2, t, 0, 0, 0)


def test_label_suffix_mark_matched_and_stacked():
    # cot CC4A tai (100,100)pt co nhan 'CC4A(u)' + 'CC4B (o)' xep chong; cot CC4A tai (200,100) chi '(u)'
    cols = [{"mark": "CC4A", "shape": "rect", "b_mm": 300, "h_mm": 800, "legend": "UNDER_AND_OVER",
             "center": {"x": 100 * MMPT, "y": -100 * MMPT}},
            {"mark": "CC4A", "shape": "rect", "b_mm": 300, "h_mm": 800, "legend": "UNDER_AND_OVER",
             "center": {"x": 200 * MMPT, "y": -100 * MMPT}}]
    words = [_word(105, 98, "CC4A(u)"), _word(105, 112, "CC4B"), _word(116, 112, "(o)", 4),
             _word(205, 98, "CC4A(u)"),
             _word(400, 400, "CC5(o)")]           # nhan khong co cot -> unassigned
    info = lgd.apply_label_suffixes(_Page(words), _T(), cols, [], scale=100.0, sched=SCHED)
    assert cols[0]["legend"] == "UNDER_AND_OVER" and cols[0]["mark"] == "CC4B" and cols[0]["mark_below"] == "CC4A"
    assert cols[1]["legend"] == "UNDER" and cols[1]["mark"] == "CC4A"
    assert [u["mark"] for u in info["unassigned"]] == ["CC5"]


def test_wall_labels_only_same_mark():
    walls = [{"mark": "RW1", "legend": "UNDER_AND_OVER", "thickness_mm": 200,
              "start_mm": {"x": 0, "y": -50 * MMPT}, "end_mm": {"x": 100 * MMPT, "y": -50 * MMPT}}]
    words = [_word(40, 47, "US1(o)"), _word(60, 53, "RW1(u)")]
    lgd.apply_label_suffixes(_Page(words), _T(), [], walls, scale=100.0, sched=SCHED)
    assert walls[0]["legend"] == "UNDER"        # US1 (o) ben canh khong duoc lam RW1 thanh OVER


def test_arc_wall_takes_label_along_arc_not_neighbour_end():
    # cung 1/4 tâm (100,100)pt R=45pt từ 90° (trên) đến 180° (trái), mã ban đầu RW1 (chữ gần nhất)
    R = 45.0
    pt = lambda a: {"x": (100 + R * math.cos(a)) * MMPT, "y": -(100 + R * math.sin(a)) * MMPT}
    w = {"mark": "RW1", "legend": "UNDER", "thickness_mm": 200, "radius_mm": R * MMPT,
         "center_mm": {"x": 100 * MMPT, "y": -100 * MMPT},
         "start_mm": pt(math.pi / 2), "mid_mm": pt(3 * math.pi / 4), "end_mm": pt(math.pi)}

    class P(_Page):
        def get_text(self, kind="text"):
            if kind == "dict":
                return {"blocks": [{"lines": [
                    {"bbox": (96, 140, 110, 150), "dir": (1.0, 0.0)},                        # RW1(u) ngang, đầu cung
                    {"bbox": (62, 122, 80, 136), "dir": (0.707, 0.707)}]}]}                  # W1(o) xiên theo tiếp tuyến cung (trang Y xuống)
            return self._w
    words = [_word(98, 146, "RW1(u)"), _word(66, 129, "W1(o)")]
    lgd.apply_label_suffixes(P(words), _T(), [], [w], scale=100.0, sched=SCHED)
    assert w["mark"] == "W1" and w["mark_from_text"] == "RW1" and w["legend"] == "OVER"
