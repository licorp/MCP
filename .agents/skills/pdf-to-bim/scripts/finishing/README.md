# Bo script hoan thien (Phase 7 cua skill pdf-to-bim)

Chay tu goc repo. CPython: `python <file>.py`. Revit (IronPython): `python run_code.py revit/<file>.py "<mo ta>" notx [dry]`.
Cau hinh du an: `.agents/projects/<ma>/finishing_config.json` (bien moi truong `FINISH_PROJECT` hoac `FINISH_CONFIG`).
Du lieu trung gian: `%LOCALAPPDATA%/RevitMCPPython/*.json` (xuat tu Revit) va `.agents/cache/*.json|png`.

| Buoc | CPython | Revit |
|---|---|---|
| Xuat du lieu | | export_slabs_arcs, export_slabs_fill, export_walls_pts, export_walls_full, export_rails |
| Lan can mep san | edge_runs, pc1_gaps, render_runs | |
| Dong bo tang | rail_template | (dung lai bang script sinh tu rail_plan.json) dedupe_rails, snap_warn, keep_stacked_walls |
| Lo / khe san | slab_gaps, slab_gaps2 | |
| Gop san + nan truc | merge_fillers, merge_snap_plan [offaxis] | merge_fillers_apply, merge_snap_apply, offaxis_floors |
| Dinh/chan tuong-cot | | fix_tops_bases, tops_to_soffit [dry] |
| Join | | join_overlaps, join_floor_hosts_safe, join_floors_safe, unjoin_noint |
| Kiem tra | render_runs | warn_summary, export3d, save_doc |
| Tag + dim (Phase 8) | annotate_views (dieu phoi, --text=), crop_png, pdf_text_obstacles | prep_marking_views, annotate_marking, annotate_footing, export_view_png, export_columns |

Truoc moi buoc dung lai hang loat: `revit/save_doc.py`.

Tham so cho script Revit: `run_code.py x.py "mo ta" notx 'DOC_TITLE="Project1"' 'VIEW_NAMES=["..."]'`; script lau: `RUN_TIMEOUT=2400`.
