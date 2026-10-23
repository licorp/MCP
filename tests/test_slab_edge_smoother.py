# -*- coding: utf-8 -*-
"""Răng lược do vạch precast dọc mép ban công tròn phải được làm trơn thành cung, không chồng tấm kề, không mất sàn."""
import math
import os
import sys

from shapely.geometry import Polygon, box

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, ".agents", "skills", "pdf-to-bim", "scripts"))
import slab_edge_smoother as sm  # noqa: E402

R = 4000.0


def comb_disc(r=R, ticks=120, depth=130.0, width=40.0):
    """Nửa đĩa có khấc hẹp (width x depth) cách đều trên mép cung - giống viền bóc tách từ hatch PBS1."""
    pts = []
    for k in range(ticks):
        a0 = math.pi * k / ticks
        a1 = math.pi * (k + 1) / ticks
        da = width / r
        am = (a0 + a1) / 2
        for a, rr in ((a0, r), (am - da / 2, r), (am - da / 2, r - depth), (am + da / 2, r - depth), (am + da / 2, r)):
            pts.append((rr * math.cos(a), rr * math.sin(a)))
    pts.append((-r, 0.0))
    return Polygon(pts).buffer(0)


def test_comb_balcony_becomes_arc():
    disc = comb_disc()
    out = sm.smooth_level([disc])[0]
    assert out is not None
    ideal = math.pi * R * R / 2
    assert abs(out.area - ideal) / ideal < 0.01, (out.area, ideal)
    ring = sm.ring_with_arcs(list(out.exterior.coords))
    assert any("mid" in it for it in ring), "the curved edge must become true arcs"
    assert len(ring) < 20, len(ring)


def test_interlocked_ring_goes_to_neighbour_without_overlap():
    disc = comb_disc()
    band = box(-R, -1200, R, 0)                       # dải 1200 kề mép thẳng của ban công
    ring = Polygon([(R * math.cos(a), R * math.sin(a)) for a in [math.pi * i / 90 for i in range(91)]] +
                   [((R - 150) * math.cos(a), (R - 150) * math.sin(a)) for a in [math.pi * (90 - i) / 90 for i in range(91)]])
    thin = ring.difference(disc).buffer(0)            # vành 150 mm xen kẽ răng, gán nhầm cho tấm khác
    out = sm.smooth_level([disc, band, thin])
    assert out[2] is None or out[2].area < 0.5e6      # vành mỏng nhập vào ban công
    assert out[0].area > math.pi * R * R / 2 * 0.99
    assert out[0].intersection(out[1]).area < 1.0
