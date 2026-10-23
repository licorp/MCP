# -*- coding: utf-8 -*-
"""View-related tools for capturing and listing Revit views"""

from typing import Optional
from mcp.server.fastmcp import Context
from .utils import format_response


def register_view_tools(mcp, revit_get, revit_post, revit_image):
    """Register view-related tools"""

    @mcp.tool()
    async def get_revit_view(view_name: str, ctx: Context = None):
        """Export a specific Revit view as an image"""
        return await revit_image(f"/get_view/{view_name}", ctx)

    @mcp.tool()
    async def list_revit_views(ctx: Context = None) -> str:
        """Get a list of all exportable views in the current Revit model"""
        response = await revit_get("/list_views/", ctx)
        return format_response(response)

    @mcp.tool()
    async def get_current_view_info(ctx: Context = None) -> str:
        """
        Get detailed information about the currently active view in Revit.

        Returns comprehensive information including:
        - View name, type, and ID
        - Scale and detail level
        - Crop box status
        - View family type
        - View discipline
        - Template status
        """
        if ctx:
            await ctx.info("Getting current view information...")
        response = await revit_get("/current_view_info/", ctx)
        return format_response(response)

    @mcp.tool()
    async def get_current_view_elements(
        limit: int = 5000,
        include_levels: bool = False,
        include_location: bool = False,
        ctx: Context = None,
    ) -> str:
        """
        Get elements visible in the currently active view in Revit.

        Returns per element: element_id, name, category, category_id.
        Also returns category_counts (always for ALL elements, even if truncated).

        If the response contains truncated=true, not all elements were returned.
        Check total_elements vs returned_elements and increase limit if needed.

        Args:
            limit: Maximum number of elements to return (default 5000).
            include_levels: Include level name and level_id per element. Default false.
            include_location: Include location geometry (point or curve). Default false.
        """
        if ctx:
            await ctx.info("Getting elements in current view...")
        data = {
            "limit": limit,
            "include_levels": include_levels,
            "include_location": include_location,
        }
        response = await revit_post("/current_view_elements/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def align_viewports_across_sheets(
        main_sheet_number: str,
        target_sheet_numbers: Optional[list[str]] = None,
        apply_crop_scope_box: bool = True,
        align_titleblock: bool = True,
        align_legend: bool = True,
        ctx: Context = None,
    ) -> str:
        """
        Align Viewports across sheets using the proven Erik Frits Temporary-Hide algorithm.
        Eliminates viewport bounding-box offset caused by grid extensions, dimensions, and annotations.

        Args:
            main_sheet_number: Sheet number of the reference sheet (e.g. 'A101' or 'S-101').
            target_sheet_numbers: List of sheet numbers to align to the reference sheet. If None or empty, aligns all other sheets.
            apply_crop_scope_box: Whether to apply the same Scope Box or Crop Shape from the reference view to target views.
            align_titleblock: Whether to align TitleBlock origin to XYZ(0,0,0).
            align_legend: Whether to align matching Legend viewports on target sheets.
        """
        if ctx:
            await ctx.info(f"Aligning viewports relative to sheet {main_sheet_number}...")
        payload = {
            "main_sheet_number": main_sheet_number,
            "target_sheet_numbers": target_sheet_numbers or [],
            "apply_crop_scope_box": apply_crop_scope_box,
            "align_titleblock": align_titleblock,
            "align_legend": align_legend,
        }
        response = await revit_post("/align_viewports/", payload, ctx)
        return format_response(response)
