# -*- coding: utf-8 -*-
"""Kiem thu grid_detector bang PDF gia lap (khong can Revit)."""
import math
import os
import sys
import tempfile

import fitz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".agents", "skills", "pdf-to-bim", "scripts")))
from grid_detector import detect_pdf_grids, calibrate_from_grids, get_title_block_info  # noqa: E402

MM_PER_PT_1_100 = 25.4 / 72.0 * 100  # 1 pt giay = 35.28 mm thuc o ti le 1:100
X_LABELS = ["A", "B", "C", "D"]
Y_LABELS = ["1", "2", "3"]
X_MM = [0, 6000, 12000, 18000]
Y_MM = [0, 7500, 15000]
ORIGIN_PT = (100.0, 700.0)  # vi tri giao diem A-1 tren trang (Y xuong)


def mm_to_pt(x, y):
    return ORIGIN_PT[0] + x / MM_PER_PT_1_100, ORIGIN_PT[1] - y / MM_PER_PT_1_100


def dashed(shape, p, q, dash=6.0, gap=3.0):
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    t = 0.0
    while t < L:
        e = min(t + dash, L)
        shape.draw_line((p[0] + ux * t, p[1] + uy * t), (p[0] + ux * e, p[1] + uy * e))
        t = e + gap


def make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=1190, height=842)
    sh = page.new_shape()
    r = 7.0
    for lab, x in zip(X_LABELS, X_MM):
        top = mm_to_pt(x, 17000)
        bot = mm_to_pt(x, -2000)
        dashed(sh, bot, top)
        c = (top[0], top[1] - r)
        sh.draw_circle(c, r)
        page.insert_text((c[0] - 3, c[1] + 3), lab, fontsize=8)
    for lab, y in zip(Y_LABELS, Y_MM):
        left = mm_to_pt(-2000, y)
        right = mm_to_pt(20000, y)
        dashed(sh, left, right)
        c = (left[0] - r, left[1])
        sh.draw_circle(c, r)
        page.insert_text((c[0] - 2.5, c[1] + 3), lab, fontsize=8)
    sh.finish(color=(0, 0, 0), width=0.3)
    sh.commit()
    page.insert_text((1000, 820), "GROUND FLOOR MARKING PLAN ZONE A", fontsize=8)
    page.insert_text((1100, 835), "S204", fontsize=10)
    doc.save(path)


def revit_grids(offset=(50000.0, 230000.0)):
    out = []
    for lab, x in zip(X_LABELS, X_MM):
        out.append({"name": lab, "start_mm": {"x": x + offset[0], "y": -3000 + offset[1]},
                    "end_mm": {"x": x + offset[0], "y": 18000 + offset[1]}})
    for lab, y in zip(Y_LABELS, Y_MM):
        out.append({"name": "Grid " + lab, "start_mm": {"x": -3000 + offset[0], "y": y + offset[1]},
                    "end_mm": {"x": 21000 + offset[0], "y": y + offset[1]}})
    return out


def test_detect_and_calibrate():
    path = os.path.join(tempfile.mkdtemp(), "grid_test.pdf")
    make_pdf(path)
    page = fitz.open(path)[0]

    grids = detect_pdf_grids(page)
    assert [g["label"] for g in grids] == sorted(X_LABELS + Y_LABELS), grids

    cal = calibrate_from_grids(grids, revit_grids())
    assert cal["status"] == "success", cal
    assert cal["common_intersections"] == 12
    assert cal["drawing_scale"] == "1:100", cal["drawing_scale"]
    assert cal["residual_max_mm"] < 5.0, cal

    info = get_title_block_info(page)
    assert info["sheet_number"] == "S204" and info["zone"] == "A", info
    print("OK", cal["anchors"], cal["drawing_scale"], "rms", cal["residual_rms_mm"], "mm")


if __name__ == "__main__":
    test_detect_and_calibrate()