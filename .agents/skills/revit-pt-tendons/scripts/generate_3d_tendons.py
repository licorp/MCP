"""
Generate 3D tendon points by combining 2D CAD trajectory, CGS height annotations,
and slab soffit elevation.
"""
import math
import json
import sys
import os

def dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def process_3d_tendons(extracted_json_path, transform, soffit_elev_mm, default_cgs=115.0, search_radius=1200.0, output_json=None):
    with open(extracted_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cables = data.get("cables", [])
    cgs_items = data.get("cgs", [])

    theta = transform["theta_rad"]
    tx = transform["tx"]
    ty = transform["ty"]
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    tendons_3d = []

    for cable in cables:
        if len(cable) < 2:
            continue

        # For each vertex, find closest CGS annotation
        cable_pts_3d = []
        for v in cable:
            best_cgs = None
            min_d = search_radius
            for item in cgs_items:
                d = dist(v, [item["x"], item["y"]])
                if d < min_d:
                    min_d = d
                    best_cgs = item["val"]

            cgs_val = best_cgs if best_cgs is not None else default_cgs

            # Convert (x, y) to Revit mm
            revit_x_mm = (v[0] * cos_t - v[1] * sin_t) + tx
            revit_y_mm = (v[0] * sin_t + v[1] * cos_t) + ty
            revit_z_mm = soffit_elev_mm + cgs_val

            # Convert to Revit internal units (feet: 1 ft = 304.8 mm)
            x_ft = revit_x_mm / 304.8
            y_ft = revit_y_mm / 304.8
            z_ft = revit_z_mm / 304.8

            cable_pts_3d.append([x_ft, y_ft, z_ft])

        tendons_3d.append(cable_pts_3d)

    if output_json:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(tendons_3d, f, indent=2)

    return tendons_3d

if __name__ == "__main__":
    print("3D Tendon reconstruction module.")
