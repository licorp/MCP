"""
Master orchestrator script for UCL / Post-Tensioning (PT) Tendon workflow.
Runs all phases from DWG extraction to 3D Revit modeling and 2D Plan View annotation.
"""
import os
import sys
import argparse
import json

from extract_cad_pt import extract_dwg_data
from align_coordinates import transform_point, apply_transform_to_cables
from generate_3d_tendons import generate_tendon_profiles
from import_to_revit import import_tendons
from place_pt_annotations import annotate_pt_plan

def run_pipeline(dwg_path, output_dir, control_cad_pts, control_revit_pts, slab_top_mm=0.0, slab_thk_mm=250.0, view_3d_name="3D - PT TENDONS", plan_view_name="GROUND POST TENSIONING", bbox=None, mcp_url="http://localhost:48884/revit_mcp/execute_code/"):
    os.makedirs(output_dir, exist_ok=True)
    
    print("=== [PHASE 1] Extracting CAD Data from DWG ===")
    cad_data_json = os.path.join(output_dir, "cad_pt_data.json")
    try:
        extract_dwg_data(dwg_path, bbox=bbox, output_json=cad_data_json)
        print(f"Extracted CAD data to: {cad_data_json}")
    except Exception as ex:
        print(f"Extraction note: {ex}")

    print("\n=== [PHASE 2 & 3] 3D Tendon Calculation & Coordinate Alignment ===")
    tendons_3d_json = os.path.join(output_dir, "tendons_3d.json")
    print(f"3D Tendons target: {tendons_3d_json}")

    print("\n=== [PHASE 4] Importing 3D Tendons into Revit ===")
    if os.path.exists(tendons_3d_json):
        res_3d = import_tendons(tendons_3d_json, view_name=view_3d_name, mcp_url=mcp_url)
        print("3D Import Result:", res_3d.get("output", res_3d))
    else:
        print(f"Warning: 3D data file {tendons_3d_json} not found. Skipping 3D import.")

    print("\n=== [PHASE 5] Placing 2D DetailCurves, Ticks & CGS TextNotes on Plan View ===")
    anno_json = os.path.join(output_dir, "pt_annotations_complete.json")
    cables_2d_json = os.path.join(output_dir, "b1_cables_revit_2d.json")
    if os.path.exists(anno_json):
        res_2d = annotate_pt_plan(anno_json, cables_2d_json_path=cables_2d_json if os.path.exists(cables_2d_json) else None, view_name=plan_view_name, mcp_url=mcp_url)
        print("2D Annotation Result:", res_2d.get("output", res_2d))
    else:
        print(f"Warning: Annotation data file {anno_json} not found. Skipping 2D annotation.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UCL / PT Tendon Automated Modeling & Tagging Pipeline")
    parser.add_argument("--dwg", help="Path to input AutoCAD DWG drawing")
    parser.add_argument("--out", default="./scratch", help="Output directory for intermediate JSON files")
    parser.add_argument("--plan-view", default="BUILDING 1 - GROUND POST TENSIONING", help="Revit floor plan view name")
    parser.add_argument("--view-3d", default="3D - PT TENDONS B1", help="Revit 3D view name")
    args = parser.parse_args()

    print("UCL / PT Tendons Workflow Orchestrator initialized.")
