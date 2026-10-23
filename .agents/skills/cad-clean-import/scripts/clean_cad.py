# -*- coding: utf-8 -*-
"""
Deep-clean architectural DWG files for linking into Revit (HPCE "LINK CAD" standard).

Runs AutoCAD Core Console (accoreconsole.exe) headlessly with an AutoLISP script that:
  1. Thaws / unlocks / turns ON all layers
  2. Detaches all Xrefs
  3. Deletes ALL HATCH / SOLID / WIPEOUT / TRACE entities (entdel, NOT the ERASE command)
  4. Deletes entities on non-structural layers (landscape, furniture, sanitary, annotations...)
  5. Purges (3 passes) + AUDIT
  6. SAVEAS a new DWG (AutoCAD 2018 format) - the source file is never modified

Usage:
  # single file
  python clean_cad.py --src "A111.dwg" --out "LINK CAD/BUILDING A - LEVEL 1.dwg" --verify

  # batch via JSON map: [{"src": "...", "out": "..."}, ...]
  python clean_cad.py --map cad_map.json --verify

  # customise layer filters (AutoCAD wildcard, comma separated)
  python clean_cad.py --map cad_map.json --extra-remove-layers "*ROOF*,*SITE*"
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter

ACCORE_CANDIDATES = [
    r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2023\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2022\accoreconsole.exe",
]

# Layers removed by default (AutoCAD wildcard syntax). Structural-relevant layers such as
# A-WALL*, A-FLOR*, S-COLS*, A-COLS*, S-STRS*, A-DOOR*, A-GLAZ*, GRID are kept.
DEFAULT_REMOVE_LAYERS = [
    # landscape / site / topo
    "*LNDSCP*", "*LAND*", "*PLANT*", "*TOPO*", "C-TOPO*",
    # furniture, sanitary, joinery, electrical
    "*FURN*", "*SANR*", "*PLUMB*", "*CASE*", "*ELEC*",
    # patterns / hatches stored on own layers
    "*PATT*", "*HATCH*",
    # annotation, text, dims, room / area tags
    "*ANNO*", "*TEXT*", "*NOTE*", "*IDEN*", "*DIM*", "*AREA*",
    # misc architectural clutter
    "*MBND*", "*GENM*", "*SPCQ*", "*GENF*",
]

REMOVE_ENTITY_TYPES = ["HATCH", "WIPEOUT,SOLID,TRACE"]

LISP_TEMPLATE = r"""
(vl-load-com)
(setvar "CMDECHO" 0)
(setvar "FILEDIA" 0)

;; NOTE: (command "ERASE" ss "") silently does nothing in accoreconsole -> use entdel.
(defun mcp-delete (flt / ss i n)
  (setq n 0)
  (setq ss (ssget "X" flt))
  (if ss
    (repeat (setq i (sslength ss))
      (entdel (ssname ss (setq i (1- i))))
      (setq n (1+ n))
    )
  )
  n
)

;; Standardize all remaining layers to grey (Color 8) & entities to ByLayer
(defun mcp-standardize-grey (/ ss i ent ed)
  (command "-LAYER" "C" "8" "*" "")
  (setq ss (ssget "X"))
  (if ss
    (repeat (setq i (sslength ss))
      (setq ent (ssname ss (setq i (1- i))))
      (setq ed (entget ent))
      (if (assoc 62 ed)
        (progn
          (setq ed (vl-remove (assoc 62 ed) ed))
          (entmod ed)
        )
      )
    )
  )
)

(command "-LAYER" "T" "*" "U" "*" "ON" "*" "")
(command "-XREF" "D" "*")

{entity_deletes}
{layer_deletes}
{grey_step}

(repeat 3 (command "-PURGE" "ALL" "*" "N"))
(command "AUDIT" "Y")
;; Phong ngua: dua UCS ve WORLD truoc khi luu (in UCS truoc/sau de truy vet). Luu y: A101/A121 du an 250793
;; da o UCS World ma Revit van dat link xoay -30.717 do -> kiem tra link sau khi dat (khop cung voi link dung).
(princ (strcat "\nMCP_UCS_BEFORE: " (vl-princ-to-string (getvar "UCSXDIR")) " WORLD=" (itoa (getvar "WORLDUCS"))))
(command "UCS" "W")
(command "PLAN" "W")
(princ (strcat "\nMCP_UCS_AFTER: " (vl-princ-to-string (getvar "UCSXDIR")) " WORLD=" (itoa (getvar "WORLDUCS"))))
(command "ZOOM" "E")
(command "SAVEAS" "2018" "{target}")
"""


def find_accoreconsole():
    for c in ACCORE_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def _lisp_str(s):
    return s.replace("\\", "/").replace('"', '\\"')


def build_lisp(target, remove_layers, standardize_grey=True):
    ent = "\n".join(
        '(princ (strcat "\\nMCP_DELETED {0}: " (itoa (mcp-delete \'((0 . "{0}"))))))'.format(t)
        for t in REMOVE_ENTITY_TYPES
    )
    lay = ""
    if remove_layers:
        lay = '(princ (strcat "\\nMCP_DELETED LAYERS: " (itoa (mcp-delete (list (cons 8 "{0}"))))))'.format(
            _lisp_str(",".join(remove_layers))
        )
    grey_code = "(mcp-standardize-grey)" if standardize_grey else ""
    return LISP_TEMPLATE.format(entity_deletes=ent, layer_deletes=lay, grey_step=grey_code, target=_lisp_str(target))


def run_accore(accore, dwg, lisp_code, timeout):
    tmp = tempfile.gettempdir()
    uid = uuid.uuid4().hex[:8]
    lsp = os.path.join(tmp, "_cadclean_{0}.lsp".format(uid))
    scr = os.path.join(tmp, "_cadclean_{0}.scr".format(uid))
    try:
        with open(lsp, "w", encoding="utf-8") as f:
            f.write(lisp_code)
        with open(scr, "w", encoding="utf-8") as f:
            f.write('(load "{0}")\nQUIT\nY\n'.format(lsp.replace("\\", "/")))
        proc = subprocess.run([accore, "/i", dwg, "/s", scr],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        # accoreconsole writes UTF-16LE to stdout
        out = proc.stdout.decode("utf-16le", errors="ignore").replace("\x00", "")
        return proc.returncode, out
    finally:
        for p in (lsp, scr):
            try:
                os.remove(p)
            except OSError:
                pass


def verify_layers(accore, dwg, timeout):
    """Export DWG -> DXF headlessly and count remaining entities per layer (needs ezdxf)."""
    try:
        import ezdxf
    except ImportError:
        return {"error": "ezdxf not installed - skip verify"}
    dxf = os.path.join(tempfile.gettempdir(), "_cadverify_{0}.dxf".format(uuid.uuid4().hex[:6]))
    run_accore(accore, dwg, '(command "DXFOUT" "{0}" "16")'.format(_lisp_str(dxf)), timeout)
    if not os.path.exists(dxf):
        return {"error": "DXFOUT failed"}
    try:
        doc = ezdxf.readfile(dxf)
        msp = doc.modelspace()
        layers = Counter(e.dxf.layer for e in msp)
        types = Counter(e.dxftype() for e in msp)
        return {"layers": dict(layers.most_common()), "entity_types": dict(types)}
    finally:
        try:
            os.remove(dxf)
        except OSError:
            pass


def clean_one(accore, src, out, remove_layers, timeout, verify, standardize_grey=True):
    res = {"src": src, "out": out, "success": False}
    if not os.path.exists(src):
        res["error"] = "source not found"
        return res
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)  # SAVEAS must never hit the "replace?" prompt
    t0 = time.time()
    rc, stdout = run_accore(accore, src, build_lisp(os.path.abspath(out), remove_layers, standardize_grey), timeout)
    res["seconds"] = round(time.time() - t0, 1)
    res["deleted"] = [l.strip() for l in stdout.splitlines() if l.strip().startswith(("MCP_DELETED", "MCP_UCS"))]
    if os.path.exists(out):
        res["success"] = True
        res["size_kb_before"] = round(os.path.getsize(src) / 1024.0, 1)
        res["size_kb_after"] = round(os.path.getsize(out) / 1024.0, 1)
        if verify:
            res["verify"] = verify_layers(accore, out, timeout)
    else:
        res["error"] = "output not created (rc={0})".format(rc)
        res["stdout_tail"] = stdout[-800:]
    return res


def main():
    ap = argparse.ArgumentParser(description="Deep-clean DWG files for Revit linking")
    ap.add_argument("--src", help="source DWG")
    ap.add_argument("--out", help="output clean DWG")
    ap.add_argument("--map", help='JSON file: [{"src": "...", "out": "..."}]')
    ap.add_argument("--remove-layers", help="override default layer filter (comma separated wildcards)")
    ap.add_argument("--extra-remove-layers", help="append to default layer filter")
    ap.add_argument("--no-grey", action="store_true", help="do not convert remaining layers to Color 8 (grey)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--verify", action="store_true", help="list remaining layers via DXF + ezdxf")
    args = ap.parse_args()

    accore = find_accoreconsole()
    if not accore:
        sys.exit("accoreconsole.exe not found")

    jobs = []
    if args.map:
        with open(args.map, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    elif args.src and args.out:
        jobs = [{"src": args.src, "out": args.out}]
    else:
        sys.exit("Provide --src/--out or --map")

    layers = DEFAULT_REMOVE_LAYERS
    if args.remove_layers is not None:
        layers = [s.strip() for s in args.remove_layers.split(",") if s.strip()]
    if args.extra_remove_layers:
        layers = layers + [s.strip() for s in args.extra_remove_layers.split(",") if s.strip()]

    standardize_grey = not args.no_grey
    results = [clean_one(accore, j["src"], j["out"], layers, args.timeout, args.verify, standardize_grey) for j in jobs]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    sys.exit(0 if all(r["success"] for r in results) else 1)


if __name__ == "__main__":
    main()
