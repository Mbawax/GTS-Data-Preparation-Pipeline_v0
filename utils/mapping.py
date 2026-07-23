"""
mapping.py
==========
Interactive Folium map construction for Module 2 (GPS Analytics).
"""

from __future__ import annotations

from typing import Optional

import branca.colormap as cm
import folium
import geopandas as gpd
from folium.plugins import FastMarkerCluster, MiniMap


def _map_center(gdf: gpd.GeoDataFrame) -> tuple:
    """Compute a reasonable [lat, lon] centre for a GeoDataFrame."""
    minx, miny, maxx, maxy = gdf.total_bounds
    return [(miny + maxy) / 2, (minx + maxx) / 2]


def build_analytics_map(
    grid: gpd.GeoDataFrame,
    grid_id_col: str,
    points: Optional[gpd.GeoDataFrame] = None,
    boundary: Optional[gpd.GeoDataFrame] = None,
    max_points_to_render: int = 20_000,
) -> folium.Map:
    """Build an interactive Folium map of grid Point_Count with optional layers.

    Args:
        grid: Grid GeoDataFrame with ``Point_Count`` and ``Area`` columns
            (EPSG:4326).
        grid_id_col: Name of the grid ID column.
        points: Optional GPS point GeoDataFrame (EPSG:4326) to overlay.
            Rendered via a marker cluster to stay performant with very
            large point counts.
        boundary: Optional boundary polygon layer to overlay.
        max_points_to_render: Points are subsampled to this count before
            rendering to keep the browser responsive.

    Returns:
        A ``folium.Map`` instance ready to be embedded with
        ``st_folium`` / ``folium_static``.
    """
    center = _map_center(grid)
    fmap = folium.Map(location=center, zoom_start=11, tiles="cartodbpositron", control_scale=True)

    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)

    # -- Graduated colour scale for Point_Count ----------------------------
    max_count = int(grid["Point_Count"].max()) if len(grid) else 1
    max_count = max(max_count, 1)
    colormap = cm.linear.YlOrRd_09.scale(0, max_count)
    colormap.caption = "GPS Point Count per Grid"

    def style_function(feature):
        count = feature["properties"].get("Point_Count", 0)
        return {
            "fillColor": colormap(count),
            "color": "#555555",
            "weight": 0.6,
            "fillOpacity": 0.75 if count > 0 else 0.15,
        }

    highlight_function = lambda feature: {"weight": 2, "color": "#000000", "fillOpacity": 0.9}

    tooltip_fields = [grid_id_col, "Point_Count"]
    tooltip_aliases = ["Grid ID:", "Point Count:"]
    if "Area" in grid.columns:
        tooltip_fields.append("Area")
        tooltip_aliases.append("Area (sq km):")

    grid_layer = folium.GeoJson(
        grid.to_json(),
        name="Campaign Grid (Point_Count)",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, sticky=True),
        popup=folium.GeoJsonPopup(fields=tooltip_fields, aliases=tooltip_aliases),
    )
    grid_layer.add_to(fmap)
    colormap.add_to(fmap)

    # -- Optional boundary outline ------------------------------------------
    if boundary is not None and not boundary.empty:
        folium.GeoJson(
            boundary.to_json(),
            name="State Boundary",
            style_function=lambda f: {"fillOpacity": 0, "color": "#1f77b4", "weight": 2},
        ).add_to(fmap)

    # -- Optional GPS points (clustered for performance) --------------------
    if points is not None and not points.empty:
        sample = points if len(points) <= max_points_to_render else points.sample(
            max_points_to_render, random_state=42
        )
        coords = list(zip(sample.geometry.y, sample.geometry.x))
        cluster_layer = FastMarkerCluster(coords, name="GPS Points")
        cluster_layer.add_to(fmap)

    MiniMap(toggle_display=True).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    return fmap
