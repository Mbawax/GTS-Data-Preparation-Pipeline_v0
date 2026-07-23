"""
spatial.py
==========
Core spatial operations: bounding-box pre-filtering, polygon clipping,
and spatial joins. Built on GeoPandas' spatial-indexed operations so it
stays performant for datasets with millions of points.
"""

from __future__ import annotations

from typing import Tuple

import geopandas as gpd
import pandas as pd


# --------------------------------------------------------------------------- #
# Fast bbox pre-filter + polygon clip (Module 1, Step 5)
# --------------------------------------------------------------------------- #

def filter_by_bbox(points: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Cheaply discard points outside the bounding box of ``boundary``.

    This is a fast pre-filter meant to be run before the more expensive
    exact polygon clip, dramatically reducing the number of points that
    need to go through the costly intersection test.

    Args:
        points: Point GeoDataFrame (same CRS as ``boundary``).
        boundary: Polygon GeoDataFrame defining the area of interest.

    Returns:
        The subset of ``points`` whose coordinates fall within the total
        bounding box of ``boundary``.
    """
    minx, miny, maxx, maxy = boundary.total_bounds
    x = points.geometry.x
    y = points.geometry.y
    mask = (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy)
    return points[mask].reset_index(drop=True)


def clip_to_polygon(points: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Perform an exact polygon clip of points against a boundary layer.

    Uses ``gpd.sjoin`` with the "within" predicate (which leverages the
    spatial index built into GeoPandas/Shapely-STRtree) rather than
    ``gpd.clip``, since we only need membership, not geometry cutting.

    Args:
        points: Point GeoDataFrame, ideally pre-filtered with
            :func:`filter_by_bbox` for speed.
        boundary: Polygon GeoDataFrame (dissolved or not).

    Returns:
        The subset of ``points`` that fall within any polygon of
        ``boundary``, with join columns removed.
    """
    boundary_dissolved = boundary[["geometry"]].copy()
    boundary_dissolved["_dissolve_key"] = 1
    boundary_dissolved = boundary_dissolved.dissolve(by="_dissolve_key")

    joined = gpd.sjoin(points, boundary_dissolved, how="inner", predicate="within")
    drop_cols = [c for c in joined.columns if c.startswith("index_") or c == "_dissolve_key"]
    joined = joined.drop(columns=drop_cols, errors="ignore")
    return joined.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Spatial join with campaign grid (Module 2, Step 3-4)
# --------------------------------------------------------------------------- #

def join_points_to_grid(
    points: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    grid_id_col: str,
) -> gpd.GeoDataFrame:
    """Spatially join GPS points to a campaign grid using the 'within' predicate.

    Args:
        points: Point GeoDataFrame.
        grid: Polygon grid GeoDataFrame containing ``grid_id_col``.
        grid_id_col: Name of the unique grid-ID column in ``grid``.

    Returns:
        A copy of ``points`` with a new column ``grid_id_col`` inherited
        from the enclosing grid polygon (NaN for points outside all
        polygons).
    """
    grid_subset = grid[[grid_id_col, "geometry"]].copy()

    joined = gpd.sjoin(
        points,
        grid_subset,
        how="left",
        predicate="within",
    )
    joined = joined.drop(columns=[c for c in joined.columns if c.startswith("index_")], errors="ignore")

    # sjoin renames the right-hand grid_id_col if it collides with a column
    # already present in `points`; normalise back to the expected name.
    right_col = f"{grid_id_col}_right" if f"{grid_id_col}_right" in joined.columns else grid_id_col
    if right_col != grid_id_col:
        joined = joined.rename(columns={right_col: grid_id_col})

    return joined.reset_index(drop=True)


def count_points_per_grid(
    joined_points: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    grid_id_col: str,
) -> gpd.GeoDataFrame:
    """Attach a ``Point_Count`` column to every grid cell, including zeros.

    Args:
        joined_points: Output of :func:`join_points_to_grid`.
        grid: Original grid GeoDataFrame (all cells, including those with
            zero points).
        grid_id_col: Name of the unique grid-ID column.

    Returns:
        A copy of ``grid`` with an added integer ``Point_Count`` column.
    """
    counts = (
        joined_points.dropna(subset=[grid_id_col])
        .groupby(grid_id_col)
        .size()
        .rename("Point_Count")
    )

    result = grid.copy()
    result = result.merge(counts, how="left", left_on=grid_id_col, right_index=True)
    result["Point_Count"] = result["Point_Count"].fillna(0).astype(int)
    return result
