"""Cat vien trang anh view xuat tu revit/export_view_png.py (FitToPage de lai le rat rong).

usage: python crop_png.py <thu muc ra> "<view 1>" ...   (hoac goi crop_all tu annotate_views.py)
"""
import glob
import os
import sys

from PIL import Image, ImageOps

SRC = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RevitMCPPython")


def crop_all(views, out, pad=40):
    os.makedirs(out, exist_ok=True)
    for v in views:
        for f in glob.glob(os.path.join(SRC, "viewimg - * - %s.png" % v)):
            im = Image.open(f).convert("RGB")
            bb = ImageOps.invert(im).getbbox()
            if bb:
                im = im.crop((max(bb[0] - pad, 0), max(bb[1] - pad, 0), min(bb[2] + pad, im.width), min(bb[3] + pad, im.height)))
            p = os.path.join(out, v + ".png")
            im.save(p)
            print(p, im.size)


if __name__ == "__main__":
    crop_all(sys.argv[2:], sys.argv[1])
