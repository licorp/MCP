"""Chay 1 file IronPython trong Revit qua route /execute_code/ cua pyRevit MCP.

usage: python run_code.py <script.py> "<mo ta>" [notx] [dry] [TEN=gia_tri_python ...]
  notx : khong boc transaction tu dong (cac script tu mo Transaction rieng)
  dry  : chen "DRY_RUN = True" vao dau script (script nao co DRY se chi bao cao, khong ghi)
  TEN=gia_tri : chen "TEN = gia_tri" vao dau script, vd 'DOC_TITLE="Project1"' 'VIEW_NAMES=["A - LEVEL 01 - MARKING PLAN"]'
bien moi truong RUN_TIMEOUT (giay, mac dinh 600) cho script chay lau (tag/dim ca view).
"""
import json
import os
import sys

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 5))   # goc repo extension
sys.path.insert(0, ROOT)
from revit_mcp.pairing import authorization_headers, authorization_params  # noqa: E402

code = open(sys.argv[1], encoding="utf-8").read()
if "dry" in sys.argv[3:]:
    code = "DRY_RUN = True\n" + code
for a in sys.argv[3:]:
    if "=" in a:
        k, val = a.split("=", 1)
        code = "%s = %s\n" % (k.strip(), val) + code
payload = {"code": code, "description": sys.argv[2], "use_transaction": "notx" not in sys.argv[3:]}
r = httpx.post("http://localhost:48884/revit_mcp/execute_code/", json=payload,
               headers=authorization_headers(), params=authorization_params(), timeout=float(os.environ.get("RUN_TIMEOUT", "600")), trust_env=False)
print(r.status_code)
try:
    d = r.json()
    print(d.get("output") or json.dumps(d, ensure_ascii=False, indent=1)[:4000])
except ValueError:
    print(r.text[:4000])
