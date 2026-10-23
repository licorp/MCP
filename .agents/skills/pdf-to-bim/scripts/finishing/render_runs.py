"""Ve danh sach tuong (json) len cac to ban ve; ghep thanh 1 anh. usage: python render_runs.py <json in cache> <out png>"""
import json, math, sys
sys.path.insert(0, ".agents/skills/pdf-to-bim/scripts"); sys.path.insert(0, ".agents/skills/cad-clean-import/scripts")
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont
from pdf_struct_parser import AffineTransformer
from workdir import work_path

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finishing_config as FC  # noqa: E402
SH = {k: (v["page"], FC.cal(k), fitz.Rect(*v["clip"]) if v.get("clip") else None) for k, v in FC.SHEETS.items()}
W = json.load(open(work_path(sys.argv[1])))
doc = fitz.open(FC.PDF)


def pts_of(s):
    if s["kind"] != "arc":
        return [s["start"], s["end"]]
    (ax, ay), (bx, by), (cx, cy) = s["start"], s["mid"], s["end"]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax*ax+ay*ay)*(by-cy) + (bx*bx+by*by)*(cy-ay) + (cx*cx+cy*cy)*(ay-by)) / d
    uy = ((ax*ax+ay*ay)*(cx-bx) + (bx*bx+by*by)*(ax-cx) + (cx*cx+cy*cy)*(bx-ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux); am = math.atan2(by - uy, bx - ux); a1 = math.atan2(cy - uy, cx - ux)
    n = lambda x: (x - a0) % (2 * math.pi)
    sw = n(a1) if n(am) < n(a1) else n(a1) - 2 * math.pi
    return [(ux + r * math.cos(a0 + sw * i / 24), uy + r * math.sin(a0 + sw * i / 24)) for i in range(25)]


tiles = []
SH = {k: v for k, v in SH.items() if any(x["sheet"] == k for x in W)}
font = ImageFont.truetype("arial.ttf", 22)
for sh, (pno, cal, clip) in SH.items():
    mine = [s for s in W if s["sheet"] == sh]
    page = doc[pno - 1]; T = AffineTransformer(*cal)
    shp = page.new_shape()
    for s in mine:
        q = [T.to_pdf_pt(x, y) for x, y in pts_of(s)]
        shp.draw_polyline([fitz.Point(v["x"], v["y"]) for v in q])
    shp.finish(color=(1, 0, 0), width=3.0, closePath=False)
    shp.commit()
    pix = page.get_pixmap(dpi=45, clip=(clip * page.rotation_matrix if page.rotation else clip) if clip else None)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    tile = Image.new("RGB", (im.width, im.height + 32), "white"); tile.paste(im, (0, 32))
    ImageDraw.Draw(tile).text((6, 4), "%s: %d doan, %.1f m" % (sh, len(mine), sum(s["len"] for s in mine) / 1000), fill=(200, 0, 0), font=font)
    tiles.append(tile)
cols = min(3, len(tiles)); rows = (len(tiles) + cols - 1) // cols
cw = max(t.width for t in tiles); ch = max(t.height for t in tiles)
cv = Image.new("RGB", (cw * cols, ch * rows), "white")
for k, t in enumerate(tiles):
    cv.paste(t, ((k % cols) * cw, (k // cols) * ch))
cv.save(work_path(sys.argv[2])); print(cv.size)
