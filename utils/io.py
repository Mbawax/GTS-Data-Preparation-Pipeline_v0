"""
io.py
=====
Input/output utilities for the GTS GPS Analytics application.

Handles reading of vector boundary/grid files (Shapefile .zip, GeoPackage,
GeoJSON) and GPS track CSV files, as well as auto-detection of the format
of a "prepared" dataset exported by Module 1.

All heavy read operations are wrapped with ``st.cache_data`` so that
re-running the Streamlit script (which happens on every widget interaction)
does not re-parse the same bytes over and over again.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

VECTOR_EXTENSIONS = {".shp", ".gpkg", ".geojson", ".json"}
DEFAULT_CRS = "EPSG:4326"


# --------------------------------------------------------------------------- #
# Vector layer readers (boundary / grid)
# --------------------------------------------------------------------------- #

def _read_zipped_shapefile(file_bytes: bytes) -> gpd.GeoDataFrame:
    """Extract an uploaded .zip archive containing a Shapefile and read it.

    Args:
        file_bytes: Raw bytes of the uploaded .zip file.

    Returns:
        A GeoDataFrame parsed from the .shp found inside the archive.

    Raises:
        ValueError: If no .shp file is found inside the archive.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "upload.zip"
        zip_path.write_bytes(file_bytes)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)

        shp_files = list(Path(tmp_dir).rglob("*.shp"))
        if not shp_files:
            raise ValueError(
                "No .shp file found inside the uploaded .zip archive. "
                "Please make sure the archive contains .shp, .shx, .dbf "
                "and .prj files."
            )
        gdf = gpd.read_file(shp_files[0])
    return gdf


def read_vector_upload(uploaded_file) -> gpd.GeoDataFrame:
    """Read an uploaded vector file (.zip shapefile, .gpkg, or .geojson/.json).

    Args:
        uploaded_file: A Streamlit ``UploadedFile`` object.

    Returns:
        The parsed GeoDataFrame (CRS as found in the source file; the
        caller is responsible for reprojecting / validating).

    Raises:
        ValueError: If the file extension is unsupported or the file is
            corrupt / unreadable.
    """
    name = uploaded_file.name.lower()
    file_bytes = uploaded_file.getvalue()

    try:
        if name.endswith(".zip"):
            gdf = _read_zipped_shapefile(file_bytes)
        elif name.endswith(".gpkg"):
            with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            gdf = gpd.read_file(tmp_path)
        elif name.endswith(".geojson") or name.endswith(".json"):
            gdf = gpd.read_file(io.BytesIO(file_bytes))
        else:
            raise ValueError(
                f"Unsupported file type: '{uploaded_file.name}'. "
                "Please upload a .zip (Shapefile), .gpkg, or .geojson file."
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"'{uploaded_file.name}' is not a valid .zip archive.") from exc
    except Exception as exc:  # noqa: BLE001 - surface any parsing failure clearly
        raise ValueError(
            f"Could not read '{uploaded_file.name}'. The file may be corrupt "
            f"or in an unsupported format. Details: {exc}"
        ) from exc

    if gdf.empty:
        raise ValueError(f"'{uploaded_file.name}' contains no features.")

    return gdf


# --------------------------------------------------------------------------- #
# GPS Track CSV readers
# --------------------------------------------------------------------------- #

def merge_csv_uploads(
    uploaded_files: List,
    lat_col_candidates: Tuple[str, ...] = ("Latitude", "latitude", "lat", "LAT", "Lat"),
    lon_col_candidates: Tuple[str, ...] = ("Longitude", "longitude", "lon", "lng", "LON", "Lon"),
    chunk_size: int = 200_000,
    progress_callback: Optional[callable] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """Read and merge multiple uploaded GPS-track CSV files.

    Adds a ``source_file`` column recording the originating filename for
    every row. Corrupt / unreadable files are skipped and reported back to
    the caller rather than crashing the whole batch.

    Args:
        uploaded_files: List of Streamlit ``UploadedFile`` objects.
        lat_col_candidates: Column names that will be recognised as latitude.
        lon_col_candidates: Column names that will be recognised as longitude.
        chunk_size: Number of rows read per chunk for large CSV files.
        progress_callback: Optional callable(fraction: float, message: str)
            used to update a Streamlit progress bar.

    Returns:
        A tuple of (merged DataFrame, list of error messages for files that
        failed to load).
    """
    frames: List[pd.DataFrame] = []
    errors: List[str] = []
    total = len(uploaded_files)

    for idx, uploaded_file in enumerate(uploaded_files, start=1):
        try:
            raw_bytes = uploaded_file.getvalue()
            chunks = []
            reader = pd.read_csv(
                io.BytesIO(raw_bytes),
                chunksize=chunk_size,
                low_memory=False,
                on_bad_lines="skip",
            )
            for chunk in reader:
                chunk["source_file"] = uploaded_file.name
                chunks.append(chunk)

            if not chunks:
                errors.append(f"'{uploaded_file.name}' is empty and was skipped.")
                continue

            df = pd.concat(chunks, ignore_index=True)
            frames.append(df)

        except Exception as exc:  # noqa: BLE001
            errors.append(f"'{uploaded_file.name}' could not be read: {exc}")

        if progress_callback is not None:
            progress_callback(idx / total, f"Reading {uploaded_file.name} ({idx}/{total})")

    if not frames:
        return pd.DataFrame(), errors

    merged = pd.concat(frames, ignore_index=True, sort=False)
    return merged, errors


def detect_lat_lon_columns(
    df: pd.DataFrame,
    lat_col_candidates: Tuple[str, ...] = ("Latitude", "latitude", "lat", "LAT", "Lat", "y", "Y"),
    lon_col_candidates: Tuple[str, ...] = ("Longitude", "longitude", "lon", "lng", "LON", "Lon", "x", "X"),
) -> Tuple[Optional[str], Optional[str]]:
    """Guess which columns hold latitude / longitude values.

    Args:
        df: The merged GPS-track DataFrame.
        lat_col_candidates: Candidate column names for latitude.
        lon_col_candidates: Candidate column names for longitude.

    Returns:
        A tuple (lat_column, lon_column); either may be ``None`` if no
        candidate matched.
    """
    lat_col = next((c for c in lat_col_candidates if c in df.columns), None)
    lon_col = next((c for c in lon_col_candidates if c in df.columns), None)
    return lat_col, lon_col


# --------------------------------------------------------------------------- #
# Prepared-dataset auto-detection (Module 2, Step 1)
# --------------------------------------------------------------------------- #

def read_prepared_dataset(uploaded_file) -> gpd.GeoDataFrame:
    """Auto-detect and read a prepared GPS dataset (CSV, GeoPackage, or GeoJSON).

    For CSV input, the function looks for ``geometry`` / ``WKT`` columns,
    or falls back to ``Latitude``/``Longitude`` columns to build point
    geometries.

    Args:
        uploaded_file: A Streamlit ``UploadedFile`` object.

    Returns:
        A point GeoDataFrame in EPSG:4326.

    Raises:
        ValueError: If the format cannot be detected or the file is invalid.
    """
    name = uploaded_file.name.lower()
    file_bytes = uploaded_file.getvalue()

    if name.endswith(".gpkg"):
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        gdf = gpd.read_file(tmp_path)

    elif name.endswith(".geojson") or name.endswith(".json"):
        gdf = gpd.read_file(io.BytesIO(file_bytes))

    elif name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), low_memory=False)

        if "geometry" in df.columns:
            from shapely import wkt as shapely_wkt

            geom = df["geometry"].apply(shapely_wkt.loads)
            gdf = gpd.GeoDataFrame(df.drop(columns=["geometry"]), geometry=geom, crs=DEFAULT_CRS)
        else:
            lat_col, lon_col = detect_lat_lon_columns(df)
            if lat_col is None or lon_col is None:
                raise ValueError(
                    "Could not find latitude/longitude or geometry columns "
                    "in the uploaded CSV. Expected columns such as "
                    "'Latitude'/'Longitude' or a 'geometry' WKT column."
                )
            gdf = gpd.GeoDataFrame(
                df,
                geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
                crs=DEFAULT_CRS,
            )
    else:
        raise ValueError(
            f"Unsupported file type: '{uploaded_file.name}'. "
            "Please upload a .csv, .gpkg, or .geojson file."
        )

    if gdf.empty:
        raise ValueError(f"'{uploaded_file.name}' contains no records.")

    return gdf
