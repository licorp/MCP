# -*- coding: UTF-8 -*-
"""
Views Module for Revit MCP
Handles view export and image generation functionality
"""

from pyrevit import routes, revit, DB
import tempfile
import shutil
import os
import base64
import json
import logging
import traceback
from System.Collections.Generic import List

try:
    from urllib.parse import unquote
except ImportError:
    from urllib import unquote

from .utils import normalize_string, get_element_name, element_id_value
from .security import authorize_request

logger = logging.getLogger(__name__)


def register_views_routes(api):
    """Register all view-related routes with the API"""

    @api.route("/get_view/<view_name>", methods=["GET"])
    def get_view(doc, view_name, request):
        """
        Export a named Revit view as a PNG image and return the image data

        Args:
            doc: Revit document (provided by MCP context)
            view_name: Name of the view to export

        Returns:
            dict: Contains base64 encoded image data and content type, or error message
        """
        denial = authorize_request(request, action=None)
        if denial is not None:
            return denial
        output_folder = None
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )

            # Decode URL-encoded characters (e.g. %20 -> space)
            # httpx encodes the path but pyRevit's router doesn't decode params
            view_name = unquote(view_name)
            # Normalize the view name
            view_name = normalize_string(view_name)
            logger.info("Exporting view: {}".format(view_name))

            output_folder = tempfile.mkdtemp(prefix="RevitMCPExports-")

            # Create filename prefix
            file_path_prefix = os.path.join(output_folder, "export")

            # Find the view by name
            target_view = None
            all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()

            for view in all_views:
                try:
                    # Use safe name access
                    current_view_name = normalize_string(get_element_name(view))
                    if current_view_name == view_name:
                        target_view = view
                        break
                except Exception as e:
                    logger.warning("Could not get name for view: {}".format(str(e)))
                    continue

            if not target_view:
                # Get list of available views for better error message
                available_views = []
                for view in all_views:
                    try:
                        view_name_safe = normalize_string(get_element_name(view))
                        # Filter out system views and templates
                        if (
                            hasattr(view, "IsTemplate")
                            and not view.IsTemplate
                            and view.ViewType != DB.ViewType.Internal
                            and view.ViewType != DB.ViewType.ProjectBrowser
                        ):
                            available_views.append(view_name_safe)
                    except:
                        continue

                return routes.make_response(
                    data={
                        "error": "View '{}' not found".format(view_name),
                        "available_views": available_views[
                            :20
                        ],  # Limit to first 20 for readability
                    },
                    status=404,
                )

            # Check if view can be exported
            try:
                if hasattr(target_view, "IsTemplate") and target_view.IsTemplate:
                    return routes.make_response(
                        data={"error": "Cannot export view templates"}, status=400
                    )

                if target_view.ViewType == DB.ViewType.Internal:
                    return routes.make_response(
                        data={"error": "Cannot export internal views"}, status=400
                    )
            except Exception as e:
                logger.warning("Could not check view properties: {}".format(str(e)))

            # Set up export options
            ieo = DB.ImageExportOptions()
            ieo.ExportRange = DB.ExportRange.SetOfViews

            # Create list of view IDs to export
            viewIds = List[DB.ElementId]()
            viewIds.Add(target_view.Id)
            ieo.SetViewsAndSheets(viewIds)

            ieo.FilePath = file_path_prefix
            ieo.HLRandWFViewsFileType = DB.ImageFileType.PNG
            ieo.ShadowViewsFileType = DB.ImageFileType.PNG
            ieo.ImageResolution = DB.ImageResolution.DPI_150
            ieo.ZoomType = DB.ZoomFitType.FitToPage
            ieo.PixelSize = 1024  # Set a reasonable default size

            # Export the image
            logger.info("Starting image export for view: {}".format(view_name))
            doc.ExportImage(ieo)

            # Find the exported file (most recent PNG in folder)
            matching_files = []
            try:
                matching_files = [
                    os.path.join(output_folder, f)
                    for f in os.listdir(output_folder)
                    if f.endswith(".png")
                ]
                matching_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
            except Exception as e:
                logger.error("Could not list exported files: {}".format(str(e)))
                return routes.make_response(
                    data={"error": "Could not access export folder"}, status=500
                )

            if not matching_files:
                return routes.make_response(
                    data={"error": "Export failed - no image file was created"},
                    status=500,
                )

            exported_file = matching_files[0]
            logger.info("Image exported successfully: {}".format(exported_file))

            # Read and encode the image
            try:
                with open(exported_file, "rb") as img_file:
                    img_data = img_file.read()

                encoded_data = base64.b64encode(img_data).decode("utf-8")

                # Get file size for logging
                file_size = len(img_data)
                logger.info(
                    "Image encoded successfully. Size: {} bytes".format(file_size)
                )

            except Exception as e:
                logger.error("Could not read/encode image file: {}".format(str(e)))
                return routes.make_response(
                    data={"error": "Could not read exported image file"}, status=500
                )
            finally:
                # Clean up the file
                try:
                    if os.path.exists(exported_file):
                        os.remove(exported_file)
                        logger.info("Temporary export file cleaned up")
                except Exception as e:
                    logger.warning(
                        "Could not clean up temporary file: {}".format(str(e))
                    )

            return routes.make_response(
                data={
                    "image_data": encoded_data,
                    "content_type": "image/png",
                    "view_name": view_name,
                    "file_size_bytes": len(img_data),
                    "export_success": True,
                }
            )

        except Exception as e:
            logger.error("Failed to export view '{}': {}".format(view_name, str(e)))
            return routes.make_response(
                data={"error": "Failed to export view: {}".format(str(e))}, status=500
            )
        finally:
            if output_folder:
                try:
                    shutil.rmtree(output_folder)
                except OSError:
                    logger.warning("Could not remove this request's temporary export directory.")

    @api.route("/list_views/", methods=["GET"])
    def list_views(doc, request):
        """
        Get a list of all exportable views in the current Revit model

        Returns:
            dict: List of view names organized by type
        """
        denial = authorize_request(request, action=None)
        if denial is not None:
            return denial

        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )

            # Get all views
            all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()

            views_by_type = {
                "floor_plans": [],
                "ceiling_plans": [],
                "elevations": [],
                "sections": [],
                "3d_views": [],
                "drafting_views": [],
                "schedules": [],
                "other": [],
            }

            for view in all_views:
                try:
                    # Skip templates and internal views
                    if hasattr(view, "IsTemplate") and view.IsTemplate:
                        continue

                    if (
                        view.ViewType == DB.ViewType.Internal
                        or view.ViewType == DB.ViewType.ProjectBrowser
                    ):
                        continue

                    view_name = normalize_string(get_element_name(view))
                    view_type = view.ViewType

                    # Categorize views
                    if view_type == DB.ViewType.FloorPlan:
                        views_by_type["floor_plans"].append(view_name)
                    elif view_type == DB.ViewType.CeilingPlan:
                        views_by_type["ceiling_plans"].append(view_name)
                    elif view_type == DB.ViewType.Elevation:
                        views_by_type["elevations"].append(view_name)
                    elif view_type == DB.ViewType.Section:
                        views_by_type["sections"].append(view_name)
                    elif view_type == DB.ViewType.ThreeD:
                        views_by_type["3d_views"].append(view_name)
                    elif view_type == DB.ViewType.DraftingView:
                        views_by_type["drafting_views"].append(view_name)
                    elif view_type == DB.ViewType.Schedule:
                        views_by_type["schedules"].append(view_name)
                    else:
                        views_by_type["other"].append(view_name)

                except Exception as e:
                    logger.warning("Could not process view: {}".format(str(e)))
                    continue

            # Sort all lists alphabetically
            for view_list in views_by_type.values():
                view_list.sort()

            # Count total exportable views
            total_views = sum(len(view_list) for view_list in views_by_type.values())

            return routes.make_response(
                data={
                    "views_by_type": views_by_type,
                    "total_exportable_views": total_views,
                    "status": "success",
                }
            )

        except Exception as e:
            logger.error("Failed to list views: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Failed to list views: {}".format(str(e))}, status=500
            )

    @api.route("/current_view_info/", methods=["GET"])
    def get_current_view_info(uidoc, request):
        """
        Get detailed information about the currently active view.

        Args:
            uidoc: UIDocument (provided by MCP context)

        Returns:
            dict: Detailed information about the current view
        """
        denial = authorize_request(request, action=None)
        if denial is not None:
            return denial

        try:
            if not uidoc or not uidoc.Document:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )

            current_view = uidoc.ActiveView
            if not current_view:
                return routes.make_response(
                    data={"error": "No active view found"}, status=404
                )

            logger.info("Getting current view info")

            # Get basic view information
            view_info = {
                "view_name": normalize_string(get_element_name(current_view)),
                "view_type": str(current_view.ViewType),
                "view_id": element_id_value(current_view.Id),
                "is_template": (
                    current_view.IsTemplate
                    if hasattr(current_view, "IsTemplate")
                    else False
                ),
            }

            # Add scale information if available
            try:
                view_info["scale"] = current_view.Scale
            except Exception:
                view_info["scale"] = None

            # Add crop box information if available
            try:
                view_info["crop_box_active"] = current_view.CropBoxActive
            except Exception:
                view_info["crop_box_active"] = False

            # Add view family type if available
            try:
                view_family_type = current_view.Document.GetElement(
                    current_view.GetTypeId()
                )
                if view_family_type:
                    view_info["view_family_type"] = normalize_string(get_element_name(view_family_type))
                else:
                    view_info["view_family_type"] = "Unknown"
            except Exception:
                view_info["view_family_type"] = "Unknown"

            # Add detail level if available
            try:
                view_info["detail_level"] = str(current_view.DetailLevel)
            except Exception:
                view_info["detail_level"] = "Unknown"

            # Add view discipline if available
            try:
                view_info["discipline"] = str(current_view.Discipline)
            except Exception:
                view_info["discipline"] = "Unknown"

            return routes.make_response(
                data={"status": "success", "view_info": view_info}
            )

        except Exception as e:
            logger.error("Get current view info failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Failed to get current view info: {}".format(str(e))},
                status=500,
            )

    @api.route("/current_view_elements/", methods=["POST"])
    def get_current_view_elements(doc, uidoc, request):
        """
        Get all elements visible in the current view.

        Expected JSON payload (all fields optional):
        {
            "limit": 5000,
            "include_levels": false,
            "include_location": false
        }
        """
        denial = authorize_request(request, action=None)
        if denial is not None:
            return denial

        try:
            if not doc or not uidoc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )

            current_view = uidoc.ActiveView
            if not current_view:
                return routes.make_response(
                    data={"error": "No active view found"}, status=404
                )

            # Parse optional parameters from request body
            limit = 5000
            include_levels = False
            include_location = False
            try:
                if request and request.data:
                    data = (
                        json.loads(request.data)
                        if isinstance(request.data, str)
                        else request.data
                    )
                    limit = int(data.get("limit", 5000))
                    include_levels = bool(data.get("include_levels", False))
                    include_location = bool(data.get("include_location", False))
            except Exception:
                pass  # Use defaults if parsing fails

            # Get all elements in the current view
            collector = DB.FilteredElementCollector(doc, current_view.Id)
            elements = collector.WhereElementIsNotElementType().ToElements()

            # Level cache to avoid redundant doc.GetElement() calls
            level_cache = {}  # {int(level_id): {"name": str, "id": int}}

            # Process elements, tracking category counts for ALL elements
            elements_info = []
            category_counts = {}
            total_elements = 0

            for elem in elements:
                try:
                    # Get category name for counting (always counted, even beyond limit)
                    cat = elem.Category
                    if cat:
                        cat_name = cat.Name
                    else:
                        cat_name = "Unknown"

                    if cat_name in category_counts:
                        category_counts[cat_name] = category_counts[cat_name] + 1
                    else:
                        category_counts[cat_name] = 1
                    total_elements = total_elements + 1

                    # Only build full element info up to the limit
                    if len(elements_info) >= limit:
                        continue

                    element_info = {
                        "element_id": element_id_value(elem.Id),
                        "name": normalize_string(get_element_name(elem)),
                        "category": cat_name,
                    }

                    if cat:
                        element_info["category_id"] = element_id_value(cat.Id)
                    else:
                        element_info["category_id"] = None

                    # Add level information only if requested (opt-in)
                    if include_levels:
                        try:
                            level_param = elem.get_Parameter(
                                DB.BuiltInParameter.FAMILY_LEVEL_PARAM
                            )
                            if level_param:
                                level_id = level_param.AsElementId()
                                if level_id != DB.ElementId.InvalidElementId:
                                    lid = element_id_value(level_id)
                                    if lid in level_cache:
                                        cached = level_cache[lid]
                                        element_info["level"] = cached["name"]
                                        element_info["level_id"] = cached["id"]
                                    else:
                                        level_elem = doc.GetElement(level_id)
                                        lname = normalize_string(get_element_name(level_elem))
                                        level_cache[lid] = {"name": lname, "id": lid}
                                        element_info["level"] = lname
                                        element_info["level_id"] = lid
                                else:
                                    element_info["level"] = None
                                    element_info["level_id"] = None
                            else:
                                element_info["level"] = None
                                element_info["level_id"] = None
                        except Exception:
                            element_info["level"] = None
                            element_info["level_id"] = None

                    # Add location information only if requested (opt-in)
                    if include_location:
                        try:
                            location = elem.Location
                            if hasattr(location, "Point"):
                                pt = location.Point
                                element_info["location"] = {
                                    "type": "point",
                                    "x": pt.X,
                                    "y": pt.Y,
                                    "z": pt.Z,
                                }
                            elif hasattr(location, "Curve"):
                                curve = location.Curve
                                start = curve.GetEndPoint(0)
                                end = curve.GetEndPoint(1)
                                element_info["location"] = {
                                    "type": "curve",
                                    "start": {"x": start.X, "y": start.Y, "z": start.Z},
                                    "end": {"x": end.X, "y": end.Y, "z": end.Z},
                                }
                            else:
                                element_info["location"] = {"type": "unknown"}
                        except Exception:
                            element_info["location"] = {"type": "unknown"}

                    elements_info.append(element_info)

                except Exception as elem_error:
                    logger.warning(
                        "Could not process element: {}".format(str(elem_error))
                    )
                    continue

            truncated = total_elements > len(elements_info)

            result = {
                "status": "success",
                "view_name": normalize_string(get_element_name(current_view)),
                "view_id": element_id_value(current_view.Id),
                "total_elements": total_elements,
                "returned_elements": len(elements_info),
                "limit": limit,
                "truncated": truncated,
                "elements": elements_info,
                "category_counts": category_counts,
            }

            if truncated:
                result["message"] = "Results truncated: showing {} of {} elements. Use limit parameter to retrieve more.".format(
                    len(elements_info), total_elements
                )

            return routes.make_response(data=result)

        except Exception as e:
            logger.error("Get current view elements failed: {}".format(str(e)))
            return routes.make_response(
                data={
                    "error": "Failed to get current view elements: {}".format(str(e))
                },
                status=500,
            )

    @api.route("/align_viewports/", methods=["POST"])
    def align_viewports_route(doc, request):
        """
        Align Viewports across sheets using the Erik Frits Temporary-Hide algorithm.
        Eliminates viewport bounding-box offset caused by grid extensions, dimensions, and annotations.

        Payload:
        {
            "main_sheet_number": "A101",
            "target_sheet_numbers": ["A102", "A103"],
            "apply_crop_scope_box": true,
            "align_titleblock": true,
            "align_legend": true
        }
        """
        denial = authorize_request(request, action='Align viewports across sheets')
        if denial is not None:
            return denial

        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )

            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else (request.data or {})
            )
            main_sheet_num = str(data.get("main_sheet_number", "")).strip()
            target_sheet_nums = data.get("target_sheet_numbers", [])
            apply_crop = data.get("apply_crop_scope_box", True)
            align_tb = data.get("align_titleblock", True)
            align_lg = data.get("align_legend", True)

            if not main_sheet_num:
                return routes.make_response(
                    data={"error": "main_sheet_number is required"}, status=400
                )

            all_sheets = (
                DB.FilteredElementCollector(doc)
                .OfClass(DB.ViewSheet)
                .WhereElementIsNotElementType()
                .ToElements()
            )
            sheet_map = {s.SheetNumber: s for s in all_sheets}

            main_sheet = sheet_map.get(main_sheet_num)
            if not main_sheet:
                return routes.make_response(
                    data={"error": "Main sheet '{}' not found".format(main_sheet_num)},
                    status=404,
                )

            def get_viewplans_on_sheet(sheet):
                vps = []
                for vp_id in sheet.GetAllViewports():
                    vp = doc.GetElement(vp_id)
                    v = doc.GetElement(vp.ViewId)
                    if isinstance(v, DB.ViewPlan):
                        vps.append((vp, v))
                return vps

            main_vps = get_viewplans_on_sheet(main_sheet)
            if not main_vps:
                return routes.make_response(
                    data={"error": "No ViewPlan found on main sheet '{}'".format(main_sheet_num)},
                    status=400,
                )

            main_vp, main_view = main_vps[0]

            # Get ScopeBox / CropShape from main view
            param_sb = main_view.get_Parameter(
                DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP
            )
            main_scopebox_id = (
                param_sb.AsElementId()
                if param_sb
                else DB.ElementId.InvalidElementId
            )

            crop_mgr = main_view.GetCropRegionShapeManager()
            main_cropbox = None
            if crop_mgr:
                try:
                    c_shapes = crop_mgr.GetCropShape()
                    if c_shapes and c_shapes.Count > 0:
                        main_cropbox = c_shapes[0]
                except Exception:
                    pass

            # Determine target sheets
            if target_sheet_nums and len(target_sheet_nums) > 0:
                target_sheets = [
                    sheet_map[num] for num in target_sheet_nums if num in sheet_map
                ]
            else:
                target_sheets = [
                    s for s in all_sheets if s.SheetNumber != main_sheet_num
                ]

            if not target_sheets:
                return routes.make_response(
                    data={"error": "No valid target sheets found to align"},
                    status=400,
                )

            def get_tb(sheet):
                tbs = (
                    DB.FilteredElementCollector(doc, sheet.Id)
                    .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                    .WhereElementIsNotElementType()
                    .ToElements()
                )
                return tbs[0] if tbs.Count > 0 else None

            def get_legend_vp(sheet):
                for vp_id in sheet.GetAllViewports():
                    vp = doc.GetElement(vp_id)
                    v = doc.GetElement(vp.ViewId)
                    if v and v.ViewType == DB.ViewType.Legend:
                        return vp, v
                return None, None

            results = []
            aligned_count = 0

            with DB.Transaction(doc, "MCP: Align Viewports Across Sheets") as t:
                t.Start()

                # Align TitleBlock origin to (0,0,0) if requested
                zero_pt = DB.XYZ(0, 0, 0)
                if align_tb:
                    main_tb = get_tb(main_sheet)
                    if main_tb and str(main_tb.Location.Point) != str(zero_pt):
                        try:
                            main_tb.Location.Point = zero_pt
                        except Exception:
                            pass

                main_legend_vp, main_legend_view = (
                    get_legend_vp(main_sheet) if align_lg else (None, None)
                )

                for tgt_sheet in target_sheets:
                    sheet_res = {
                        "sheet_number": tgt_sheet.SheetNumber,
                        "status": "skipped",
                        "viewports_aligned": 0,
                    }
                    tgt_vps = get_viewplans_on_sheet(tgt_sheet)

                    if not tgt_vps:
                        sheet_res["message"] = "No ViewPlan on target sheet"
                        results.append(sheet_res)
                        continue

                    if align_tb:
                        other_tb = get_tb(tgt_sheet)
                        if other_tb and str(other_tb.Location.Point) != str(zero_pt):
                            try:
                                other_tb.Location.Point = zero_pt
                            except Exception:
                                pass

                    for other_vp, other_view in tgt_vps:
                        # Apply Crop / Scope Box
                        if apply_crop:
                            if (
                                main_scopebox_id
                                and main_scopebox_id != DB.ElementId.InvalidElementId
                            ):
                                try:
                                    sb_param = other_view.get_Parameter(
                                        DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP
                                    )
                                    if sb_param and not sb_param.IsReadOnly:
                                        sb_param.Set(main_scopebox_id)
                                except Exception:
                                    pass
                            elif main_cropbox:
                                try:
                                    cr_param = other_view.get_Parameter(
                                        DB.BuiltInParameter.VIEWER_CROP_REGION
                                    )
                                    if cr_param and not cr_param.AsInteger():
                                        cr_param.Set(1)
                                    other_crop_mgr = other_view.GetCropRegionShapeManager()
                                    if other_crop_mgr:
                                        other_crop_mgr.SetCropShape(main_cropbox)
                                except Exception:
                                    pass

                        # Core Algorithm: Temporary Hide Isolate
                        main_elems = (
                            DB.FilteredElementCollector(doc, main_view.Id)
                            .WhereElementIsNotElementType()
                            .ToElementIds()
                        )
                        other_elems = (
                            DB.FilteredElementCollector(doc, other_view.Id)
                            .WhereElementIsNotElementType()
                            .ToElementIds()
                        )

                        main_view.HideElementsTemporary(main_elems)
                        other_view.HideElementsTemporary(other_elems)
                        doc.Regenerate()  # viewport boxes only shrink after regen

                        try:
                            # Read the reference centre WHILE its annotations are hidden,
                            # otherwise grid bubbles / dims skew the viewport box.
                            other_vp.SetBoxCenter(main_vp.GetBoxCenter())
                            sheet_res["viewports_aligned"] += 1
                        except Exception as align_err:
                            sheet_res["error"] = str(align_err)
                        finally:
                            other_view.DisableTemporaryViewMode(
                                DB.TemporaryViewMode.TemporaryHideIsolate
                            )
                            main_view.DisableTemporaryViewMode(
                                DB.TemporaryViewMode.TemporaryHideIsolate
                            )

                    # Legend alignment
                    if align_lg and main_legend_vp and main_legend_view:
                        other_lg_vp, other_lg_v = get_legend_vp(tgt_sheet)
                        if (
                            other_lg_vp
                            and other_lg_v
                            and other_lg_v.Name == main_legend_view.Name
                        ):
                            try:
                                other_lg_vp.SetBoxCenter(main_legend_vp.GetBoxCenter())
                                sheet_res["legend_aligned"] = True
                            except Exception:
                                pass

                    sheet_res["status"] = "success"
                    aligned_count += 1
                    results.append(sheet_res)

                t.Commit()

            return routes.make_response(
                data={
                    "status": "success",
                    "main_sheet": main_sheet_num,
                    "aligned_sheets_count": aligned_count,
                    "details": results,
                }
            )
        except Exception as e:
            logger.error("Align viewports failed: {}".format(str(e)))
            return routes.make_response(
                data={
                    "error": "Failed to align viewports: {}".format(str(e)),
                    "traceback": traceback.format_exc(),
                },
                status=500,
            )

    logger.info("Views routes registered successfully")
