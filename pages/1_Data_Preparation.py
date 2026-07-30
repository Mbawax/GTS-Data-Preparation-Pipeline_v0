"""
1_Data_Preparation.py
======================
Module 1 — Data Preparation.

Cleans and standardises raw GPS tracks against a user-uploaded state
boundary. Produces a prepared dataset (GeoPackage / CSV / GeoJSON) that
feeds directly into Module 2 (GPS Analytics). No analytics happen here.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.exports import to_csv_bytes, to_geojson_bytes, to_geopackage_bytes
from utils.io import detect_lat_lon_columns, merge_csv_uploads, read_vector_upload
from utils.preprocessing import (
    build_point_geodataframe,
    clean_coordinates,
    detect_speed_column,
    ensure_crs_4326,
    filter_by_speed,
    repair_geometries,
)
from utils.spatial import clip_to_polygon, filter_by_bbox

st.set_page_config(page_title="Module 1 — GTS Data Preparation", page_icon="📦", layout="wide")


# --------------------------------------------------------------------------- #
# Cached wrappers
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def _load_boundary(file_bytes: bytes, file_name: str) -> gpd.GeoDataFrame:
    """Cache-friendly boundary loader keyed on raw bytes + name."""
    class _Wrapped:
        name = file_name

        def getvalue(self):
            return file_bytes

    gdf = read_vector_upload(_Wrapped())
    gdf = repair_geometries(gdf)
    gdf = ensure_crs_4326(gdf)
    return gdf


def main() -> None:
    st.title("📦 Module 1 — GTS Data Preparation")
    st.caption("Clean and standardise raw GTS tracks before analysis. No analytics performed here.")

    # ----------------------------------------------------------------- #
    # Step 1 — Boundary upload
    # ----------------------------------------------------------------- #
    st.header("Step 1 — Upload State Boundary")
    boundary_file = st.file_uploader(
        "Upload boundary as Shapefile (.zip), GeoPackage (.gpkg), or GeoJSON (.geojson)",
        type=["zip", "gpkg", "geojson", "json"],
        key="boundary_upload",
    )

    boundary_gdf = None
    if boundary_file is not None:
        try:
            with st.spinner("Reading and repairing boundary geometry..."):
                boundary_gdf = _load_boundary(boundary_file.getvalue(), boundary_file.name)

            area_gdf = boundary_gdf.to_crs("EPSG:6933")
            total_area_km2 = area_gdf.geometry.area.sum() / 1_000_000

            c1, c2, c3 = st.columns(3)
            c1.metric("CRS", str(boundary_gdf.crs))
            c2.metric("Number of Polygons", f"{len(boundary_gdf):,}")
            c3.metric("Total Area (sq km)", f"{total_area_km2:,.2f}")

            with st.expander("Preview boundary attributes"):
                st.dataframe(boundary_gdf.drop(columns="geometry").head(20), use_container_width=True)

        except ValueError as exc:
            st.error(str(exc))
            boundary_gdf = None
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error while reading boundary: {exc}")
            boundary_gdf = None
    else:
        st.info("Upload a boundary file to continue.")

    st.divider()

    # ----------------------------------------------------------------- #
    # Step 2 — GTS Track CSV uploads
    # ----------------------------------------------------------------- #
    st.header("Step 2 — Upload GTS Track CSV Files")
    csv_files = st.file_uploader(
        "Upload one or many GTS-track CSV files",
        type=["csv"],
        accept_multiple_files=True,
        key="csv_upload",
    )

    merged_df = None
    if csv_files:
        st.write(f"**{len(csv_files)} file(s) selected.**")
        progress_bar = st.progress(0.0, text="Starting...")

        def _progress(frac: float, msg: str) -> None:
            progress_bar.progress(min(frac, 1.0), text=msg)

        start = time.time()
        merged_df, load_errors = merge_csv_uploads(csv_files, progress_callback=_progress)
        elapsed = time.time() - start
        progress_bar.empty()

        if load_errors:
            with st.expander(f"⚠️ {len(load_errors)} file(s) had issues", expanded=False):
                for err in load_errors:
                    st.warning(err)

        if merged_df is not None and not merged_df.empty:
            st.success(
                f"Merged {len(csv_files) - len(load_errors)} file(s) into "
                f"{len(merged_df):,} rows in {elapsed:.2f}s."
            )
            with st.expander("Preview merged data"):
                st.dataframe(merged_df.head(20), use_container_width=True)
        else:
            st.error("No valid data could be loaded from the uploaded CSV files.")
            merged_df = None
    else:
        st.info("Upload GPS-track CSV files to continue.")

    st.divider()

    # ----------------------------------------------------------------- #
    # Steps 3-6 — Clean, build geometry, filter, speed clean
    # ----------------------------------------------------------------- #
    if boundary_gdf is not None and merged_df is not None:
        st.header("Step 3-6 — Clean, Filter & Standardise")

        lat_col, lon_col = detect_lat_lon_columns(merged_df)
        col_a, col_b = st.columns(2)
        lat_col = col_a.selectbox(
            "Latitude column",
            options=list(merged_df.columns),
            index=list(merged_df.columns).index(lat_col) if lat_col in merged_df.columns else 0,
        )
        lon_col = col_b.selectbox(
            "Longitude column",
            options=list(merged_df.columns),
            index=list(merged_df.columns).index(lon_col) if lon_col in merged_df.columns else 0,
        )

        speed_col_guess = detect_speed_column(merged_df)
        speed_col = st.selectbox(
            "Speed column (metres/second) — used for Step 6 speed cleaning",
            options=["<none>"] + list(merged_df.columns),
            index=(list(merged_df.columns).index(speed_col_guess) + 1) if speed_col_guess else 0,
        )
        speed_threshold = st.number_input(
            "Keep records where Speed (mps) is less than:",
            min_value=0.0,
            value=1.0,
            step=0.1,
            help="Default threshold is 1.0 mps as specified in the requirements.",
        )

        run_button = st.button("▶️ Run Data Preparation Pipeline", type="primary")

        if run_button:
            log_container = st.expander("📜 Processing Log", expanded=True)
            records_summary = {}
            t0 = time.time()

            with log_container:
                st.write(f"Records loaded: **{len(merged_df):,}**")
                records_summary["Records loaded"] = len(merged_df)

                # Step 3 - clean coordinates
                try:
                    cleaned_df, clean_stats = clean_coordinates(merged_df, lat_col, lon_col)
                except KeyError as exc:
                    st.error(f"Missing expected column: {exc}")
                    st.stop()
                st.write(
                    f"After removing null/invalid/duplicate coordinates: "
                    f"**{len(cleaned_df):,}** "
                    f"(removed {clean_stats['initial'] - clean_stats['after_dedup']:,})"
                )

                if cleaned_df.empty:
                    st.error("No valid coordinates remain after cleaning. Check your lat/lon columns.")
                    st.stop()

                # Step 4 - build geometry
                points_gdf = build_point_geodataframe(cleaned_df, lat_col, lon_col)
                points_gdf = ensure_crs_4326(points_gdf)

                # Step 5 - fast spatial filtering: bbox then polygon clip
                bbox_gdf = filter_by_bbox(points_gdf, boundary_gdf)
                st.write(f"Records after bounding-box filter: **{len(bbox_gdf):,}**")
                records_summary["Records after bounding box"] = len(bbox_gdf)

                if bbox_gdf.empty:
                    st.error(
                        "No points fall inside the boundary's bounding box. "
                        "Check that the boundary and GPS tracks use compatible coordinates."
                    )
                    st.stop()

                try:
                    clipped_gdf = clip_to_polygon(bbox_gdf, boundary_gdf)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Polygon clip failed: {exc}")
                    st.stop()
                st.write(f"Records after polygon clip: **{len(clipped_gdf):,}**")
                records_summary["Records after polygon clip"] = len(clipped_gdf)

                if clipped_gdf.empty:
                    st.error("No points fall inside the boundary polygon(s).")
                    st.stop()

                # Step 6 - speed cleaning
                final_gdf = clipped_gdf
                if speed_col != "<none>" and speed_col in clipped_gdf.columns:
                    final_gdf = filter_by_speed(clipped_gdf, speed_col, speed_threshold)
                    st.write(
                        f"Records after speed filter (< {speed_threshold} mps): "
                        f"**{len(final_gdf):,}**"
                    )
                    records_summary["Records after speed filter"] = len(final_gdf)
                else:
                    st.info("No speed column selected — skipping Step 6 speed cleaning.")

                elapsed = time.time() - t0
                st.success(f"Pipeline completed in {elapsed:.2f}s.")

            st.session_state["prepared_gdf"] = final_gdf
            st.session_state["records_summary"] = records_summary

        # ------------------------------------------------------------- #
        # Dashboard metrics + Export (Step 7)
        # ------------------------------------------------------------- #
        if "prepared_gdf" in st.session_state:
            final_gdf = st.session_state["prepared_gdf"]
            records_summary = st.session_state.get("records_summary", {})

            st.info("💡 **Dataset Ready**: This prepared GTS dataset is automatically preloaded for **Module 2 — GTS Analytics**.")

            st.subheader("Pipeline Summary")
            metric_cols = st.columns(len(records_summary) or 1)
            for col, (label, value) in zip(metric_cols, records_summary.items()):
                col.metric(label, f"{value:,}")

            st.subheader("Step 7 — Export Prepared Dataset")
            if final_gdf.empty:
                st.warning("The prepared dataset is empty — nothing to export.")
            else:
                exp_col1, exp_col2, exp_col3 = st.columns(3)
                with exp_col1:
                    st.download_button(
                        "⬇️ Download GeoPackage",
                        data=to_geopackage_bytes(final_gdf, layer_name="prepared_gts"),
                        file_name="gts_prepared_tracks.gpkg",
                        mime="application/geopackage+sqlite3",
                    )
                with exp_col2:
                    st.download_button(
                        "⬇️ Download CSV",
                        data=to_csv_bytes(final_gdf),
                        file_name="gts_prepared_tracks.csv",
                        mime="text/csv",
                    )
                with exp_col3:
                    st.download_button(
                        "⬇️ Download GeoJSON",
                        data=to_geojson_bytes(final_gdf),
                        file_name="gts_prepared_tracks.geojson",
                        mime="application/geo+json",
                    )

                st.dataframe(final_gdf.drop(columns="geometry").head(50), use_container_width=True)
    else:
        st.warning("Complete Steps 1 and 2 above to unlock the cleaning pipeline.")


if __name__ == "__main__":
    main()
