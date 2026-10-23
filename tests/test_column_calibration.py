# -*- coding: utf-8 -*-
"""Kiem thu khop toa do bang cot (ban ve khong co luoi truc) - khong can Revit."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".agents", "skills", "pdf-to-bim", "scripts")))
from column_calibration import (calibrate_from_columns, revit_type_signature,  # noqa: E402
                                revit_column_mark, section_signature)
from pdf_struct_parser import AffineTransformer  # noqa: E402

SCALE = 100
MM_PER_PT = 25.4 / 72.0 * SCALE


def make_case(seed=1):
    """Cot Revit (mm) + cot PDF (point) tren trang xoay 90 do, co lech, nhan nham va nhieu."""
    rnd = random.Random(seed)
    revit, pdf = [], []
    ox, oy = 60000.0, 235000.0
    for i in range(6):
        for j in range(5):
            x, y = ox + i * 7000.0, oy + j * 6500.0
            if (i + j) % 7 == 0:
                typ, b, h = "CC5 - 300DIA", 300, 300
            elif (i + j) % 2:
                typ, b, h = "CC3 - 800x300", 800, 300
            else:
                typ, b, h = "CC4A - 800x300", 800, 300
            revit.append({"type": typ, "mark": revit_column_mark(typ), "x": x, "y": y})
            # Trang PDF xoay 90 do: x_pt = (y - oy)/s + 100 ; y_pt = (x - ox)/s + 200 (Y xuong)
            # cong lech +-100 mm theo canh ngan nhu model that
            dx = rnd.choice([-100.0, 100.0])
            px = (y - oy + dx) / MM_PER_PT + 100.0
            py = (x - ox) / MM_PER_PT + 200.0
            mark = revit_column_mark(typ)
            if rnd.random() < 0.25:  # nhan bi gan nham sang cot ben canh
                mark = "CC3" if mark == "CC4A" else "CC4A"
            pdf.append({"mark": mark, "x": px, "y": py, "kind": "rect", "b_mm": h, "h_mm": b})
    # Nhieu: o bang thong ke / chu thich co ma cot
    for k in range(6):
        pdf.append({"mark": "CC3", "x": 900.0 + k * 3, "y": 50.0 + k * 20, "kind": "rect", "b_mm": 800, "h_mm": 300})
    return revit, pdf


def test_signatures():
    assert revit_type_signature("CC3 - 800x300") == section_signature(300, 800)
    assert revit_type_signature("CC5 - 300DIA") == section_signature(300, 300)
    assert revit_column_mark("CC4A - 800x300") == "CC4A"


def test_calibrate_rotated_noisy_page():
    revit, pdf = make_case()
    cal = calibrate_from_columns(pdf, revit, SCALE)
    assert cal["status"] == "success", cal
    assert cal["match_by"] == "section"
    assert cal["drawing_scale"] == "1:100", cal
    assert cal["snapped_rotation"] and abs(cal["rotation_deg"] % 90) < 1e-9, cal
    assert cal["matched_columns"] >= 25, cal
    assert cal["residual_max_mm"] <= 200, cal

    # Moi cot PDF that phai roi ve dung cot Revit (sai so <= lech da cong + dung sai)
    tr = AffineTransformer(cal["pdf_grid_pt1"], cal["pdf_grid_pt2"], cal["revit_grid_pt1_mm"], cal["revit_grid_pt2_mm"])
    for f, r in zip(pdf[:30], revit):
        p = tr.to_revit_mm(f["x"], f["y"])
        assert math.hypot(p["x"] - r["x"], p["y"] - r["y"]) <= 150, (f, r, p)


def test_rejects_unrelated_floor():
    revit, pdf = make_case()
    shuffled = [dict(r, x=r["x"] + random.Random(i).uniform(-20000, 20000),
                     y=r["y"] + random.Random(i + 99).uniform(-20000, 20000)) for i, r in enumerate(revit)]
    cal = calibrate_from_columns(pdf, shuffled, SCALE)
    assert cal["status"] == "error", cal


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
