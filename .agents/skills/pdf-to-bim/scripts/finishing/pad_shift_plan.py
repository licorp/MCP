"""De xuat DOI MONG DON theo to mat bang mong PDF (mong lech tam cot).

Mong tren to ve bang NET DON (khong phai hinh chu nhat khep kin), mong chong nhau chi con 1 phan canh.
Cach lam (tung truc Hand / Facing cua mong):
  - net den day (~0,48) dai >= 500 mm, song song mot canh mong, nam trong vung +-3 m quanh mong, phu qua hang cot;
  - tim cap net cach nhau DUNG kich thuoc danh dinh cua loai mong (+-30 mm) ma cot nam giua;
  - chon cap gan vi tri hien tai nhat (doi it nhat). Khong co cap -> giu nguyen truc do.
Kich thuoc danh dinh doc tu ten loai "PF3 - 4300x4300x750D" (So 1 theo Facing? -> thu ca 2 chieu).

usage: python pad_shift_plan.py <trang PDF 0-based> "<level chan cot>" [pdf]
  can truoc: revit/export_columns.py, revit/export_pads.py (VIEW_NAMES = view mong)
  ra: %LOCALAPPDATA%/RevitMCPPython/pad_shift.json  ({id, dx, dy (mm)}) va .agents/cache/pad_shift_<trang>.png
"""
import json
import math
import os
import re
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pdf_text_obstacles import sheet_transform  # noqa: E402
from finishing_config import PDF  # noqa: E402

LOC = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython")
CACHE = os.path.abspath(os.path.join(HERE, *[".."] * 4, "cache"))
TOL = 30.0          # mm, sai lech cho phep giua khoang cach 2 net va kich thuoc mong
MAXSHIFT = 2500.0   # mm


def nominal(type_name):
    m = re.search(r"(\d{3,5})\s*x\s*(\d{3,5})", type_name)
    return (float(m.group(1)), float(m.group(2))) if m else None


def main():
    page_no, level = int(sys.argv[1]), sys.argv[2]
    pdf = sys.argv[3] if len(sys.argv) > 3 else PDF
    page = fitz.open(pdf)[page_no]
    tf, cal, scale = sheet_transform(page, level)
    to_m = lambda x, y: (lambda d: (d["x"], d["y"]))(tf.to_revit_mm(x, y))
    # nghich dao (model mm -> pdf pt) cho anh de xuat
    o = to_m(0, 0); ex = to_m(1, 0); ey = to_m(0, 1)
    a, b, c, d = ex[0] - o[0], ey[0] - o[0], ex[1] - o[1], ey[1] - o[1]
    det = a * d - b * c
    to_p = lambda X, Y: ((d * (X - o[0]) - b * (Y - o[1])) / det, (-c * (X - o[0]) + a * (Y - o[1])) / det)

    segs = []        # net den day, da quy ve model mm
    for p in page.get_drawings():
        wd = p.get("width") or 0; col = p.get("color") or (1, 1, 1)
        if wd < 0.4 or max(col) > 0.1: continue
        for it in p["items"]:
            if it[0] != "l": continue
            A, B = to_m(it[1].x, it[1].y), to_m(it[2].x, it[2].y)
            if math.hypot(B[0] - A[0], B[1] - A[1]) >= 500: segs.append((A, B))
    pads = json.load(open(os.path.join(LOC, "pads.json")))
    plan, report = [], []
    for pd in pads:
        nom = nominal(pd["type"])
        if not nom or not pd["cols"]:
            continue
        cx, cy = pd["x"], pd["y"]
        u = pd["hand"]; w = pd["facing"]
        # kich thuoc danh dinh theo u/w: lay chieu khop voi hinh hoc hien tai
        su, sw = pd["u1"] - pd["u0"], pd["w1"] - pd["w0"]
        Wu, Ww = (nom if abs(nom[0] - su) + abs(nom[1] - sw) <= abs(nom[1] - su) + abs(nom[0] - sw) else (nom[1], nom[0]))
        pu = lambda P: (P[0] - cx) * u[0] + (P[1] - cy) * u[1]
        pw = lambda P: (P[0] - cx) * w[0] + (P[1] - cy) * w[1]
        colu = [pu((q["x"], q["y"])) for q in pd["cols"]]; colw = [pw((q["x"], q["y"])) for q in pd["cols"]]
        shift = {}
        for ax, ox, size, cpos, cother in (("u", "w", Wu, colu, colw), ("w", "u", Ww, colw, colu)):
            f_ax = pu if ax == "u" else pw
            f_ot = pw if ax == "u" else pu
            pos = []
            for A, B in segs:
                if abs(f_ax(A) - f_ax(B)) > 5: continue             # phai vuong goc truc ax
                t = (f_ax(A) + f_ax(B)) / 2.0
                lo, hi = sorted((f_ot(A), f_ot(B)))
                if abs(t) > 3000 + size / 2: continue
                if hi < min(cother) - 200 or lo > max(cother) + 200: continue   # phu qua hang cot (+-200)
                if hi - lo < 500: continue
                pos.append(t)
            best = None
            for i in range(len(pos)):
                for j in range(len(pos)):
                    p0, p1 = pos[i], pos[j]
                    if p1 <= p0 or abs((p1 - p0) - size) > TOL: continue
                    if not (p0 < min(cpos) - 50 and p1 > max(cpos) + 50): continue
                    s = (p0 + p1) / 2.0
                    if abs(s) > MAXSHIFT: continue
                    if best is None or abs(s) < abs(best): best = s
            shift[ax] = best
        su_, sw_ = shift["u"] or 0.0, shift["w"] or 0.0
        dx = su_ * u[0] + sw_ * w[0]; dy = su_ * u[1] + sw_ * w[1]
        rec = {"id": pd["id"], "type": pd["type"], "du": round(su_), "dw": round(sw_), "dx": round(dx, 1), "dy": round(dy, 1),
               "found_u": shift["u"] is not None, "found_w": shift["w"] is not None,
               "col_to_edge_u": [round(Wu / 2 + su_ + cu) for cu in colu] if True else None}
        report.append(rec)
        if math.hypot(dx, dy) > 50: plan.append(rec)
    json.dump(plan, open(os.path.join(LOC, "pad_shift.json"), "w"), indent=1)
    for r in report:
        print(r["id"], r["type"][:3], "du", r["du"], "dw", r["dw"], "tim thay u/w", r["found_u"], r["found_w"])
    print("de xuat doi:", len(plan), "/", len(report), "->", os.path.join(LOC, "pad_shift.json"))

    # ---- anh de xuat: do = vi tri hien tai, xanh la = vi tri moi ----
    def outline(pd, dx, dy):
        u, w = pd["hand"], pd["facing"]
        nom = nominal(pd["type"]); su, sw = pd["u1"] - pd["u0"], pd["w1"] - pd["w0"]
        Wu, Ww = (nom if abs(nom[0] - su) + abs(nom[1] - sw) <= abs(nom[1] - su) + abs(nom[0] - sw) else (nom[1], nom[0]))
        P = []
        for a_, b_ in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)):
            X = pd["x"] + dx + a_ * Wu / 2 * u[0] + b_ * Ww / 2 * w[0]
            Y = pd["y"] + dy + a_ * Wu / 2 * u[1] + b_ * Ww / 2 * w[1]
            P.append(fitz.Point(*to_p(X, Y)))
        return P
    sh = page.new_shape()
    byid = dict((r["id"], r) for r in plan)
    for pd in pads:
        if not nominal(pd["type"]): continue
        r = byid.get(pd["id"])
        sh.draw_polyline(outline(pd, 0, 0)); sh.finish(color=(1, 0, 0) if r else (0.6, 0.6, 0.6), width=1.2 if r else 0.6, dashes="[4 2]" if r else None)
        if r:
            P = outline(pd, r["dx"], r["dy"])
            sh.draw_polyline(P); sh.finish(color=(0, 0.6, 0), width=1.6)
            mid = fitz.Point(sum(q.x for q in P[:4]) / 4, sum(q.y for q in P[:4]) / 4)
            sh.insert_text(mid, "%d,%d" % (r["du"], r["dw"]), fontsize=7, color=(0, 0.45, 0))
    sh.commit()
    os.makedirs(CACHE, exist_ok=True)
    png = os.path.join(CACHE, "pad_shift_p%d.png" % page_no)
    page.get_pixmap(dpi=110).save(png)
    print(png)


if __name__ == "__main__":
    main()
