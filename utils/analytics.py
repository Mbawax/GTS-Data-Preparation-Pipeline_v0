"""
analytics.py
============
Grid-level statistics for Module 2 (GPS Analytics).
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np


@dataclass
class GridStats:
    """Summary statistics computed over a grid's ``Point_Count`` column."""

    total_grids: int
    visited_grids: int
    unvisited_grids: int
    total_gps_points: int
    avg_points_per_visited_grid: float
    max_points: int
    min_points: int
    median_points: float
    std_points: float
    pct_visited: float


def compute_grid_statistics(grid: gpd.GeoDataFrame) -> GridStats:
    """Compute summary statistics from a grid GeoDataFrame with ``Point_Count``.

    Args:
        grid: Grid GeoDataFrame containing a ``Point_Count`` integer column.

    Returns:
        A :class:`GridStats` instance with all dashboard metrics.

    Raises:
        ValueError: If ``Point_Count`` column is missing.
    """
    if "Point_Count" not in grid.columns:
        raise ValueError("Grid GeoDataFrame is missing a 'Point_Count' column.")

    counts = grid["Point_Count"].astype(int)
    visited_mask = counts > 0
    visited_counts = counts[visited_mask]

    total_grids = len(grid)
    visited_grids = int(visited_mask.sum())
    unvisited_grids = total_grids - visited_grids

    return GridStats(
        total_grids=total_grids,
        visited_grids=visited_grids,
        unvisited_grids=unvisited_grids,
        total_gps_points=int(counts.sum()),
        avg_points_per_visited_grid=float(visited_counts.mean()) if visited_grids else 0.0,
        max_points=int(counts.max()) if total_grids else 0,
        min_points=int(counts.min()) if total_grids else 0,
        median_points=float(counts.median()) if total_grids else 0.0,
        std_points=float(counts.std()) if total_grids > 1 else 0.0,
        pct_visited=float(100 * visited_grids / total_grids) if total_grids else 0.0,
    )


def compute_grid_areas(grid: gpd.GeoDataFrame, area_unit: str = "sq_km") -> gpd.GeoDataFrame:
    """Compute polygon area in a metric CRS and attach it as an ``Area`` column.

    Args:
        grid: Grid GeoDataFrame (any CRS).
        area_unit: Either ``"sq_km"`` or ``"hectares"``.

    Returns:
        A copy of ``grid`` with an added ``Area`` column (rounded to 4 dp),
        computed after projecting to an equal-area CRS (EPSG:6933).
    """
    grid = grid.copy()
    projected = grid.to_crs("EPSG:6933")
    areas_m2 = projected.geometry.area

    if area_unit == "hectares":
        grid["Area"] = (areas_m2 / 10_000).round(4)
    else:
        grid["Area"] = (areas_m2 / 1_000_000).round(4)

    return grid
