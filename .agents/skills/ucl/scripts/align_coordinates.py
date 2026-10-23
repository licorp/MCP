"""
Calculate 2D Rigid / Helmert transformation between CAD coordinates and Revit coordinates.
Supports 2 or more control points (e.g. Grid intersections or column centers).
"""
import math
import sys
import json

def calculate_transform(cad_pts, revit_pts, fixed_scale=1.0):
    """
    cad_pts: list of (x, y) in mm
    revit_pts: list of (x, y) in mm or feet
    Returns: angle_rad, angle_deg, tx, ty, scale
    """
    n = len(cad_pts)
    if n < 2 or len(revit_pts) < 2:
        raise ValueError("At least 2 control points are required.")

    # Centroids
    cx_cad = sum(p[0] for p in cad_pts) / n
    cy_cad = sum(p[1] for p in cad_pts) / n
    cx_rev = sum(p[0] for p in revit_pts) / n
    cy_rev = sum(p[1] for p in revit_pts) / n

    # Relative vectors
    num = 0.0
    den = 0.0
    for (xc, yc), (xr, yr) in zip(cad_pts, revit_pts):
        dxc = xc - cx_cad
        dyc = yc - cy_cad
        dxr = xr - cx_rev
        dyr = yr - cy_rev
        num += dxc * dyr - dyc * dxr
        den += dxc * dxr + dyc * dyr

    theta = math.atan2(num, den)

    # Translation
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    tx = cx_rev - (cx_cad * cos_t - cy_cad * sin_t)
    ty = cy_rev - (cx_cad * sin_t + cy_cad * cos_t)

    return {
        "theta_rad": theta,
        "theta_deg": math.degrees(theta),
        "tx": tx,
        "ty": ty,
        "scale": fixed_scale
    }

def apply_transform(cad_x, cad_y, transform):
    theta = transform["theta_rad"]
    tx = transform["tx"]
    ty = transform["ty"]
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    rx = (cad_x * cos_t - cad_y * sin_t) + tx
    ry = (cad_x * sin_t + cad_y * cos_t) + ty
    return rx, ry

if __name__ == "__main__":
    print("Helper module for coordinate alignment.")
