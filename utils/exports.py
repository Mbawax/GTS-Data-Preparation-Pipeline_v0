"""
exports.py
==========
Helpers to serialise GeoDataFrames into downloadable bytes for Streamlit's
``st.download_button`` (GeoPackage, CSV, GeoJSON).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd


def to_geopackage_bytes(gdf: gpd.GeoDataFrame, layer_name: str = "data") -> bytes:
    """Serialise a GeoDataFrame to GeoPackage bytes.

    Args:
        gdf: GeoDataFrame to export.
        layer_name: Name of the layer inside the GeoPackage.

    Returns:
        Raw bytes of the .gpkg file.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "export.gpkg"
        gdf.to_file(path, layer=layer_name, driver="GPKG")
        return path.read_bytes()


def to_geojson_bytes(gdf: gpd.GeoDataFrame) -> bytes:
    """Serialise a GeoDataFrame to GeoJSON bytes.

    Args:
        gdf: GeoDataFrame to export (reprojected to EPSG:4326 if needed).

    Returns:
        Raw UTF-8 encoded GeoJSON bytes.
    """
    if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    return gdf.to_json().encode("utf-8")


def to_csv_bytes(gdf: gpd.GeoDataFrame, include_geometry_wkt: bool = True) -> bytes:
    """Serialise a GeoDataFrame (or DataFrame) to CSV bytes.

    Args:
        gdf: GeoDataFrame to export.
        include_geometry_wkt: If True, geometry is included as a WKT
            string column named ``geometry``; otherwise it is dropped.

    Returns:
        Raw UTF-8 encoded CSV bytes.
    """
    df = pd.DataFrame(gdf.copy())
    if "geometry" in df.columns:
        if include_geometry_wkt:
            df["geometry"] = df["geometry"].apply(lambda g: g.wkt if g is not None else "")
        else:
            df = df.drop(columns=["geometry"])
    return df.to_csv(index=False).encode("utf-8")
