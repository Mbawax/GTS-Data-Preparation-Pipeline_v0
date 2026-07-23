"""
preprocessing.py
=================
Cleaning and standardisation helpers used by Module 1 (Data Preparation).

Functions here are intentionally free of any Streamlit UI code so they can
be unit tested and reused independently.
"""

from __future__ import annotations

from typing import Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

DEFAULT_CRS = "EPSG:4326"


# --------------------------------------------------------------------------- #
# Geometry repair / reprojection
# --------------------------------------------------------------------------- #

def repair_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fix invalid geometries using a zero-width buffer and drop empties.

    Args:
        gdf: Input GeoDataFrame, possibly containing invalid or empty
            geometries.

    Returns:
        A new GeoDataFrame with only valid, non-empty geometries.
    """
    gdf = gdf.copy()
    gdf["geometry"] = gdf["geometry"].apply(
        lambda geom: geom.buffer(0) if geom is not None and not geom.is_valid else geom
    )
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty]
    return gdf


def ensure_crs_4326(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ensure a GeoDataFrame is in EPSG:4326, reprojecting if necessary.

    Args:
        gdf: Input GeoDataFrame. If it has no CRS defined, EPSG:4326 is
            assumed and simply assigned (no reprojection performed).

    Returns:
        The GeoDataFrame in EPSG:4326.
    """
    if gdf.crs is None:
        gdf = gdf.set_crs(DEFAULT_CRS)
    elif gdf.crs.to_string() != DEFAULT_CRS:
        gdf = gdf.to_crs(DEFAULT_CRS)
    return gdf


def reproject_to_match(gdf: gpd.GeoDataFrame, reference: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject ``gdf`` to match the CRS of ``reference``.

    Args:
        gdf: GeoDataFrame to reproject.
        reference: GeoDataFrame whose CRS should be matched.

    Returns:
        A reprojected copy of ``gdf``.
    """
    if reference.crs is None:
        reference = reference.set_crs(DEFAULT_CRS)
    if gdf.crs is None:
        gdf = gdf.set_crs(DEFAULT_CRS)
    if gdf.crs != reference.crs:
        gdf = gdf.to_crs(reference.crs)
    return gdf


# --------------------------------------------------------------------------- #
# Coordinate cleaning (Module 1, Step 3)
# --------------------------------------------------------------------------- #

def clean_coordinates(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
) -> Tuple[pd.DataFrame, dict]:
    """Clean latitude/longitude columns: coerce to numeric, drop bad rows.

    Removes:
        * Non-numeric / null coordinates
        * Coordinates outside the valid range (-90..90 lat, -180..180 lon)
        * Exact duplicate rows (all columns identical)

    Args:
        df: Input DataFrame containing lat/lon columns.
        lat_col: Name of the latitude column.
        lon_col: Name of the longitude column.

    Returns:
        Tuple of (cleaned DataFrame, stats dict with counts at each stage).
    """
    stats = {"initial": len(df)}

    df = df.copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

    df = df.dropna(subset=[lat_col, lon_col])
    stats["after_null_removal"] = len(df)

    valid_mask = (
        df[lat_col].between(-90, 90, inclusive="both")
        & df[lon_col].between(-180, 180, inclusive="both")
        & ~((df[lat_col] == 0) & (df[lon_col] == 0))
    )
    df = df[valid_mask]
    stats["after_range_filter"] = len(df)

    df = df.drop_duplicates()
    stats["after_dedup"] = len(df)

    return df.reset_index(drop=True), stats


def build_point_geodataframe(df: pd.DataFrame, lat_col: str, lon_col: str) -> gpd.GeoDataFrame:
    """Convert a DataFrame with lat/lon columns into a point GeoDataFrame.

    Args:
        df: Cleaned DataFrame.
        lat_col: Name of the latitude column.
        lon_col: Name of the longitude column.

    Returns:
        A GeoDataFrame with Point geometries in EPSG:4326.
    """
    geometry = gpd.points_from_xy(df[lon_col], df[lat_col])
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=DEFAULT_CRS)
    return gdf


# --------------------------------------------------------------------------- #
# Speed filtering (Module 1, Step 6)
# --------------------------------------------------------------------------- #

def detect_speed_column(df: pd.DataFrame) -> Optional[str]:
    """Guess which column holds speed-in-metres-per-second values.

    Args:
        df: Input DataFrame.

    Returns:
        The matched column name, or ``None`` if no candidate is found.
    """
    candidates = (
        "Speed_mps", "speed_mps", "Speed mps", "speed mps",
        "Speed", "speed", "SPEED", "speed_ms", "Speed_ms",
    )
    return next((c for c in candidates if c in df.columns), None)


def filter_by_speed(
    gdf: gpd.GeoDataFrame,
    speed_col: str,
    threshold: float = 1.0,
) -> gpd.GeoDataFrame:
    """Keep only records whose speed is strictly below the given threshold.

    Args:
        gdf: Input GeoDataFrame.
        speed_col: Name of the speed column (metres per second).
        threshold: Maximum allowed speed (exclusive). Defaults to 1.0.

    Returns:
        The filtered GeoDataFrame.
    """
    speed_numeric = pd.to_numeric(gdf[speed_col], errors="coerce")
    mask = speed_numeric < threshold
    return gdf[mask].reset_index(drop=True)
