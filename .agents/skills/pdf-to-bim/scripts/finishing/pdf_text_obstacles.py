"""Chu tren to PDF -> hop chu nhat toa do model (ft) lam VAT CAN cho tag/dim.

Dung khi nen CAD trong Revit la DWG xuat tu chinh to PDF: chu trong DWG la TEXT that, Revit API khong doc duoc,
nen lay vi tri chu tu PDF (cung nguon). Hieu chuan bang cot: column_calibration (RANSAC theo tiet dien cot).

usage: python pdf_text_obstacles.py <trang PDF 0-based> "<level chan cot>" <out.json> [pdf]
  can chay truoc: run_code.py revit/export_columns.py "xuat cot" notx 'DOC_TITLE="..."'
  ket qua: {"rects": [[x0,y0,x1,y1] ft], "calib": {...}} -> annotate_footing.py doc qua TEXT_JSON
"""
import json
import os
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from column_calibration import calibrate_from_columns, drawing_scale_from_text, extract_pdf_column_features  # noqa: E402
from pdf_struct_parser import AffineTransformer  # noqa: E402
from finishing_config import PDF  # noqa: E402

FT = 304.8


def sheet_transform(page, level):
    """hieu chuan to PDF -> model (mm) bang cot o level chan `level` (columns.json tu revit/export_columns.py)."""
    scale = drawing_scale_from_text(page) or 100
    cols = json.load(open(os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "columns.json")))
    cols = [c for c in cols if c["level"] == level]
    feats = extract_pdf_column_features(page, scale, include_unlabeled=True)
    cal = calibrate_from_columns(feats, cols, scale)
    if not cal.get("pdf_grid_pt1"):
        print("KHONG HIEU CHUAN DUOC", {k: v for k, v in cal.items() if k != "pairs"})
        sys.exit(1)
    tf = AffineTransformer(cal["pdf_grid_pt1"], cal["pdf_grid_pt2"], cal["revit_grid_pt1_mm"], cal["revit_grid_pt2_mm"])
    return tf, cal, scale


def main():
    page_no, level, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    pdf = sys.argv[4] if len(sys.argv) > 4 else PDF
    page = fitz.open(pdf)[page_no]
    tf, cal, _ = sheet_transform(page, level)
    rects = []
    for w in page.get_text("words"):
        x0, y0, x1, y1 = w[:4]
        P = [tf.to_revit_mm(x, y) for x in (x0, x1) for y in (y0, y1)]
        xs = [p["x"] / FT for p in P]; ys = [p["y"] / FT for p in P]
        rects.append([min(xs), min(ys), max(xs), max(ys)])
    info = {k: v for k, v in cal.items() if k not in ("pairs", "inliers")}
    json.dump({"rects": rects, "calib": info}, open(out, "w"))
    print(len(rects), "chu ->", out)
    print(json.dumps(info, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
