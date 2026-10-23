"""
Extract PT tendons and CGS height annotations from DWG using AutoCAD Core Console (accoreconsole.exe).
"""
import os
import sys
import subprocess
import json
import re

def find_accoreconsole():
    candidates = [
        r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2023\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2022\accoreconsole.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def extract_dwg_data(dwg_path, cable_layers=("CABLES", "CABLES1"), profile_layers=("PROFILE", "PROFILE1"), bbox=None, output_json=None):
    accore = find_accoreconsole()
    if not accore:
        raise FileNotFoundError("AutoCAD Core Console (accoreconsole.exe) not found in standard paths.")
    
    if not os.path.exists(dwg_path):
        raise FileNotFoundError(f"DWG file not found: {dwg_path}")

    work_dir = os.path.dirname(os.path.abspath(output_json or dwg_path))
    os.makedirs(work_dir, exist_ok=True)
    
    cables_txt = os.path.join(work_dir, "_temp_cables.txt").replace("\\", "/")
    cgs_txt = os.path.join(work_dir, "_temp_cgs.txt").replace("\\", "/")
    lsp_path = os.path.join(work_dir, "_temp_extract.lsp")
    scr_path = os.path.join(work_dir, "_temp_run.scr")

    cable_layers_lisp = " ".join(cable_layers)
    profile_layers_lisp = " ".join(profile_layers)

    bbox_check = ""
    if bbox:
        min_x, min_y, max_x, max_y = bbox
        bbox_check = f"""
        (and (>= (car pt) {min_x}) (<= (car pt) {max_x})
             (>= (cadr pt) {min_y}) (<= (cadr pt) {max_y}))
        """
    else:
        bbox_check = "T"

    lisp_code = f"""
(defun c:EXTRACTDATA ( / f ss i ent data pts str)
  ;; 1. Extract Cables
  (setq f (open "{cables_txt}" "w"))
  (setq ss (ssget "X" '((0 . "*POLYLINE") (8 . "{cable_layers_lisp}"))))
  (if ss
    (repeat (setq i (sslength ss))
      (setq ent (ssname ss (setq i (1- i))))
      (setq data (entget ent))
      (setq pts nil)
      (foreach x data
        (if (= (car x) 10)
          (setq pts (cons (cdr x) pts))
        )
      )
      (setq pts (reverse pts))
      ;; Check bbox with first point
      (if (and pts (let ((pt (car pts))) {bbox_check}))
        (progn
          (write-line "---CABLE---" f)
          (foreach pt pts
            (write-line (strcat (rtos (car pt) 2 3) "," (rtos (cadr pt) 2 3)) f)
          )
        )
      )
    )
  )
  (close f)

  ;; 2. Extract CGS Text
  (setq f (open "{cgs_txt}" "w"))
  (setq ss (ssget "X" '((0 . "*TEXT") (8 . "{profile_layers_lisp}"))))
  (if ss
    (repeat (setq i (sslength ss))
      (setq ent (ssname ss (setq i (1- i))))
      (setq data (entget ent))
      (setq str (cdr (assoc 1 data)))
      (setq pt (cdr (assoc 10 data)))
      (if (and pt {bbox_check})
        (write-line (strcat str "|" (rtos (car pt) 2 3) "|" (rtos (cadr pt) 2 3)) f)
      )
    )
  )
  (close f)
  (princ "\\nEXTRACTION_DONE\\n")
  (command "_.QUIT" "_Y")
)
(c:EXTRACTDATA)
"""
    with open(lsp_path, "w", encoding="utf-8") as f:
        f.write(lisp_code)

    with open(scr_path, "w", encoding="utf-8") as f:
        f.write(f'(load "{lsp_path.replace(chr(92), "/")}")\n')

    cmd = [accore, "/i", dwg_path, "/s", scr_path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)

    # Parse cables
    cables = []
    current_cable = []
    if os.path.exists(cables_txt):
        with open(cables_txt, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line == "---CABLE---":
                    if current_cable:
                        cables.append(current_cable)
                        current_cable = []
                elif "," in line:
                    parts = line.split(",")
                    current_cable.append([float(parts[0]), float(parts[1])])
            if current_cable:
                cables.append(current_cable)

    # Parse CGS texts
    cgs_items = []
    if os.path.exists(cgs_txt):
        with open(cgs_txt, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 3:
                    text_val = parts[0].strip()
                    # Clean digits
                    num_match = re.search(r"(\d+(\.\d+)?)", text_val)
                    if num_match:
                        val = float(num_match.group(1))
                        x = float(parts[1])
                        y = float(parts[2])
                        cgs_items.append({"val": val, "x": x, "y": y, "text": text_val})

    result = {
        "cables_count": len(cables),
        "cgs_count": len(cgs_items),
        "cables": cables,
        "cgs": cgs_items
    }

    if output_json:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    return result

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python extract_cad_pt.py <dwg_path> <output_json> [min_x min_y max_x max_y]")
        sys.exit(1)
    dwg = sys.argv[1]
    out = sys.argv[2]
    bbox = None
    if len(sys.argv) >= 7:
        bbox = [float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])]
    data = extract_dwg_data(dwg, output_json=out, bbox=bbox)
    print(f"Extracted {data['cables_count']} cables and {data['cgs_count']} CGS annotations.")
