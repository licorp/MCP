"""Tag + dim tranh va cham cho nhieu view, LUU sau moi view, roi xuat anh PNG da cat vien.

usage: python annotate_views.py <DOC_TITLE> "<view 1>" "<view 2>" ... [--prep] [--no-export]
  view co "FOOTING" trong ten -> revit/annotate_footing.py, con lai -> revit/annotate_marking.py
  --prep      : chay revit/prep_marking_views.py truoc (bat Floors, view range kieu Yarralumla, nong crop)
  --no-export : khong xuat anh
  --text=<json> : hop chu to PDF (pdf_text_obstacles.py) lam vat can cho view mong
Anh ra: .agents/cache/marking/<ten view>.png
Moi view lon mat ~1-10 phut; khong thao tac trong Revit khi dang chay (lenh MCP phai xep hang).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REVIT = os.path.join(HERE, "revit")
OUT = os.path.abspath(os.path.join(HERE, *[".."] * 4, "cache", "marking"))   # .agents/cache/marking


def run(script, desc, *extra, timeout="2400"):
    env = dict(os.environ, RUN_TIMEOUT=timeout)
    r = subprocess.run([sys.executable, os.path.join(HERE, "run_code.py"), os.path.join(REVIT, script), desc, "notx", *extra],
                       capture_output=True, text=True, env=env)
    print((r.stdout or r.stderr).strip()[-1500:])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    title, views = args[0], args[1:]
    doc_arg = "DOC_TITLE=" + json.dumps(title)
    if "--prep" in flags:
        run("prep_marking_views.py", "chuan bi view", doc_arg, "VIEW_NAMES=" + json.dumps(views))
    for v in views:
        script = "annotate_footing.py" if "FOOTING" in v.upper() else "annotate_marking.py"
        print("==", v)
        extra = [a.split("=", 1)[1] for a in flags if a.startswith("--text=")]
        extra = ["TEXT_JSON=" + json.dumps(extra[0])] if extra and script == "annotate_footing.py" else []
        run(script, "tag+dim " + v, doc_arg, "VIEW_NAMES=" + json.dumps([v]), *extra)
        run("save_doc.py", "luu", doc_arg, timeout="600")
    if "--no-export" not in flags:
        run("export_view_png.py", "xuat anh", doc_arg, "VIEW_NAMES=" + json.dumps(views), timeout="1200")
        from crop_png import crop_all
        crop_all(views, OUT)


if __name__ == "__main__":
    main()
