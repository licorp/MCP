# -*- coding: utf-8 -*-
"""
Kiem thu method 'cad': file CAD link trong view la chuan vi tri, uu tien hon cot da co trong model
(tinh huong that: cot model lech ~200 mm so voi ban ve, khop theo cot model se lech theo).
"""
import asyncio
import json
import math
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import test_grid_detector as g  # noqa: E402
from test_structural_pipeline import make_structural_pdf  # noqa: E402
from tools.structural_tools import auto_calibrate, cad_shapes_as_columns  # noqa: E402

OFFSET = (50000.0, 230000.0)  # vi tri ban ve trong model (giong g.revit_grids)


def fake_revit(cad=True, model_shift_mm=200.0):
    cols_true = [(x + OFFSET[0], y + OFFSET[1]) for x in g.X_MM for y in g.Y_MM]

    async def post(endpoint, data, ctx=None, **kw):
        out = {
            "grids": [],  # ban ve khong co luoi truc trong model
            "columns": [{"type": "C1 - 600x600", "mark_param": "", "x": x, "y": y + model_shift_mm}
                        for x, y in cols_true],
            "cad_shapes": [["rect", x, y, 600.0, 600.0] for x, y in cols_true] if cad else [],
            "cad_links": ["S204"] if cad else [],
            "doc_title": "t", "active_view": "v", "level": "L", "active_level": "L",
        }
        return {"status": "success", "output": json.dumps(out)}
    return post


def _pdf():
    path = os.path.join(tempfile.mkdtemp(), "struct.pdf")
    make_structural_pdf(path)
    return path


def test_cad_shapes_as_columns():
    cols = cad_shapes_as_columns([["rect", 0, 0, 800.4, 300.2], ["rect", 10, 5, 800, 300],
                                  ["circle", 5000, 0, 400.0, 400.0]])
    assert [c["type"] for c in cols] == ["800x300", "400DIA"], cols


def test_auto_prefers_cad_over_shifted_model_columns():
    cal = asyncio.run(auto_calibrate(fake_revit(cad=True), _pdf(), 1, method="auto"))
    assert cal["status"] == "success" and cal["method"] == "cad", cal
    assert cal["residual_max_mm"] < 10, cal
    # Diem moc phai trung vi tri cot THAT (khong lech 200 mm theo cot model)
    true_cols = [(x + OFFSET[0], y + OFFSET[1]) for x in g.X_MM for y in g.Y_MM]
    for key in ("revit_grid_pt1_mm", "revit_grid_pt2_mm"):
        px, py = cal[key]
        assert min(math.hypot(px - x, py - y) for x, y in true_cols) < 10, (key, cal[key])
    assert [a["method"] for a in cal["attempts"]] == ["grids", "cad"], cal["attempts"]


def test_falls_back_to_model_columns_with_warning():
    cal = asyncio.run(auto_calibrate(fake_revit(cad=False), _pdf(), 1, method="auto"))
    assert cal["status"] == "success" and cal["method"] == "columns", cal
    assert "warning" in cal, cal


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
