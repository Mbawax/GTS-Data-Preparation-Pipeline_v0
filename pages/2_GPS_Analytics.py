"""
2_GPS_Analytics.py
===================
Module 2 — GPS Analytics.

Consumes the prepared dataset produced by Module 1 together with a
user-uploaded campaign grid, performs a spatial join, computes
per-grid statistics, and renders an interactive map, summary table,
charts, and exports.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.analytics import compute_grid_areas, compute_grid_statistics
from utils.exports import to_csv_bytes, to_geojson_bytes, to_geopackage_bytes
from utils.io import read_prepared_dataset, read_vector_upload
from utils.mapping import build_analytics_map
from utils.preprocessing import ensure_crs_4326, repair_geometries, reproject_to_match
from utils.spatial import count_points_per_grid, join_points_to_grid

st.set_page_config(page_title="Module 2 — GPS Analytics", page_icon="📊", layout="wide")


# --------------------------------------------------------------------------- #
# Cached wrappers
# --------------------------------------------------------------------------- #

class _Wrapped:
    """Lightweight shim so cached functions can key off raw bytes + name."""

    def __init__(self, file_bytes: bytes, file_name: str):
        self._bytes = file_bytes
        self.name = file_name

    def getvalue(self) -> bytes:
        return self._bytes


@st.cache_data(show_spinner=False)
def _load_prepared(file_bytes: bytes, file_name: str) -> gpd.GeoDataFrame:
    gdf = read_prepared_dataset(_Wrapped(file_bytes, file_name))
    return ensure_crs_4326(gdf)


@st.cache_data(show_spinner=False)
def _load_grid(file_bytes: bytes, file_name: str) -> gpd.GeoDataFrame:
    gdf = read_vector_upload(_Wrapped(file_bytes, file_name))
    gdf = repair_geometries(gdf)
    return gdf


def main() -> None:
    st.title("📊 Module 2 — GPS Analytics")
    st.caption("Spatial join, grid statistics, interactive mapping, and exports.")

    # ----------------------------------------------------------------- #
    # Step 1 — Upload prepared GPS dataset
    # ----------------------------------------------------------------- #
    st.header("Step 1 — Upload Prepared GPS Dataset")
    gps_file = st.file_uploader(
        "Upload the dataset exported from Module 1 (CSV, GeoPackage, or GeoJSON)",
        type=["csv", "gpkg", "geojson", "json"],
        key="gps_upload",
    )

    points_gdf = None
    if gps_file is not None:
        try:
            with st.spinner("Loading prepared GPS dataset..."):
                points_gdf = _load_prepared(gps_file.getvalue(), gps_file.name)
            st.success(f"Loaded {len(points_gdf):,} GPS points.")
            with st.expander("Preview GPS points"):
                st.dataframe(points_gdf.drop(columns="geometry").head(20), use_container_width=True)
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error while reading the GPS dataset: {exc}")
    else:
        st.info("Upload the prepared GPS dataset to continue.")

    st.divider()

    # ----------------------------------------------------------------- #
    # Step 2 — Upload target grid
    # ----------------------------------------------------------------- #
    st.header("Step 2 — Upload Target Grid")
    grid_file = st.file_uploader(
        "Upload your campaign grid as Shapefile (.zip), GeoPackage, or GeoJSON",
        type=["zip", "gpkg", "geojson", "json"],
        key="grid_upload",
    )

    grid_gdf = None
    grid_id_col = None
    if grid_file is not None:
        try:
            with st.spinner("Loading and repairing grid geometry..."):
                grid_gdf = _load_grid(grid_file.getvalue(), grid_file.name)

            if points_gdf is not None:
                grid_gdf = reproject_to_match(grid_gdf, points_gdf)
            else:
                grid_gdf = ensure_crs_4326(grid_gdf)

            non_geom_cols = [c for c in grid_gdf.columns if c != "geometry"]
            default_idx = 0
            for i, c in enumerate(non_geom_cols):
                if "grid" in c.lower() and "id" in c.lower():
                    default_idx = i
                    break
            grid_id_col = st.selectbox(
                "Select the unique Grid ID column",
                options=non_geom_cols,
                index=default_idx if non_geom_cols else 0,
            )

            area_gdf = grid_gdf.to_crs("EPSG:6933")
            total_area_km2 = area_gdf.geometry.area.sum() / 1_000_000
            c1, c2, c3 = st.columns(3)
            c1.metric("CRS", str(grid_gdf.crs))
            c2.metric("Number of Grid Cells", f"{len(grid_gdf):,}")
            c3.metric("Total Grid Area (sq km)", f"{total_area_km2:,.2f}")

        except ValueError as exc:
            st.error(str(exc))
            grid_gdf = None
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error while reading the grid: {exc}")
            grid_gdf = None
    else:
        st.info("Upload a campaign grid to continue.")

    st.divider()

    # ----------------------------------------------------------------- #
    # Optional boundary overlay
    # ----------------------------------------------------------------- #
    st.header("Optional — Upload Boundary for Map Context")
    boundary_file = st.file_uploader(
        "Optional: overlay a state boundary on the map",
        type=["zip", "gpkg", "geojson", "json"],
        key="boundary_upload_m2",
    )
    boundary_gdf = None
    if boundary_file is not None:
        try:
            boundary_gdf = _load_grid(boundary_file.getvalue(), boundary_file.name)
            boundary_gdf = ensure_crs_4326(boundary_gdf)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load boundary overlay: {exc}")

    st.divider()

    # ----------------------------------------------------------------- #
    # Steps 3-9 — Run analysis
    # ----------------------------------------------------------------- #
    if points_gdf is None or grid_gdf is None or grid_id_col is None:
        st.warning("Complete Steps 1 and 2 above to unlock the analysis.")
        return

    st.header("Run Analysis")
    if grid_gdf[grid_id_col].isna().any():
        st.warning(
            f"{grid_gdf[grid_id_col].isna().sum():,} grid cell(s) have a missing "
            f"'{grid_id_col}' value. They will still be processed but may be "
            "harder to identify in the results."
        )

    run_button = st.button("▶️ Run Spatial Join & Analytics", type="primary")

    if run_button:
        t0 = time.time()
        with st.spinner("Performing spatial join..."):
            try:
                joined = join_points_to_grid(points_gdf, grid_gdf, grid_id_col)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Spatial join failed: {exc}")
                st.stop()

            grid_with_counts = count_points_per_grid(joined, grid_gdf, grid_id_col)
            grid_with_counts = compute_grid_areas(grid_with_counts)

        elapsed = time.time() - t0
        st.success(f"Spatial join completed in {elapsed:.2f}s.")

        st.session_state["joined_points"] = joined
        st.session_state["grid_with_counts"] = grid_with_counts
        st.session_state["grid_id_col"] = grid_id_col

    if "grid_with_counts" not in st.session_state:
        return

    grid_with_counts = st.session_state["grid_with_counts"]
    joined = st.session_state["joined_points"]
    grid_id_col = st.session_state["grid_id_col"]

    # ------------------------------------------------------------- #
    # Step 5 — Grid statistics dashboard
    # ------------------------------------------------------------- #
    st.header("Step 5 — Grid Statistics")
    stats = compute_grid_statistics(grid_with_counts)

    row1 = st.columns(4)
    row1[0].metric("Total Grids", f"{stats.total_grids:,}")
    row1[1].metric("Visited Grids", f"{stats.visited_grids:,}")
    row1[2].metric("Unvisited Grids", f"{stats.unvisited_grids:,}")
    row1[3].metric("Total GPS Points", f"{stats.total_gps_points:,}")

    row2 = st.columns(4)
    row2[0].metric("Avg Points / Visited Grid", f"{stats.avg_points_per_visited_grid:,.2f}")
    row2[1].metric("Max Points in a Grid", f"{stats.max_points:,}")
    row2[2].metric("Min Points", f"{stats.min_points:,}")
    row2[3].metric("% Grids Visited", f"{stats.pct_visited:,.1f}%")

    row3 = st.columns(2)
    row3[0].metric("Median Points", f"{stats.median_points:,.2f}")
    row3[1].metric("Std Dev of Points", f"{stats.std_points:,.2f}")

    st.divider()

    # ------------------------------------------------------------- #
    # Step 6 — Interactive map
    # ------------------------------------------------------------- #
    st.header("Step 6 — Interactive Map")
    with st.spinner("Rendering map..."):
        fmap = build_analytics_map(
            grid=grid_with_counts,
            grid_id_col=grid_id_col,
            points=points_gdf,
            boundary=boundary_gdf,
        )
    st_folium(fmap, use_container_width=True, height=600, returned_objects=[])

    st.divider()

    # ------------------------------------------------------------- #
    # Step 7 — Grid summary table
    # ------------------------------------------------------------- #
    st.header("Step 7 — Grid Summary Table")
    summary_df = grid_with_counts.drop(columns="geometry").copy()
    summary_df["Visited"] = summary_df["Point_Count"].apply(lambda x: "Yes" if x > 0 else "No")
    display_cols = [grid_id_col, "Point_Count", "Area", "Visited"]
    display_cols = [c for c in display_cols if c in summary_df.columns]
    summary_df = summary_df[display_cols].sort_values("Point_Count", ascending=False)

    search_term = st.text_input("🔍 Search by Grid ID")
    if search_term:
        summary_df_display = summary_df[
            summary_df[grid_id_col].astype(str).str.contains(search_term, case=False, na=False)
        ]
    else:
        summary_df_display = summary_df

    st.dataframe(summary_df_display, use_container_width=True, height=350)
    st.download_button(
        "⬇️ Download Summary Table (CSV)",
        data=summary_df.to_csv(index=False).encode("utf-8"),
        file_name="grid_summary.csv",
        mime="text/csv",
    )

    st.divider()

    # ------------------------------------------------------------- #
    # Step 8 — Charts
    # ------------------------------------------------------------- #
    st.header("Step 8 — Charts")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        hist_fig = px.histogram(
            summary_df, x="Point_Count", nbins=30, title="Histogram of Point_Count"
        )
        st.plotly_chart(hist_fig, use_container_width=True)

    with chart_col2:
        top20 = summary_df.nlargest(20, "Point_Count")
        bar_fig = px.bar(
            top20, x=grid_id_col, y="Point_Count", title="Top 20 Grids by Point Count"
        )
        st.plotly_chart(bar_fig, use_container_width=True)

    pie_df = pd.DataFrame(
        {
            "Status": ["Visited", "Unvisited"],
            "Count": [stats.visited_grids, stats.unvisited_grids],
        }
    )
    pie_fig = px.pie(pie_df, names="Status", values="Count", title="Visited vs Unvisited Grids")
    st.plotly_chart(pie_fig, use_container_width=True)

    st.divider()

    # ------------------------------------------------------------- #
    # Step 9 — Export results
    # ------------------------------------------------------------- #
    st.header("Step 9 — Export Results")
    exp_col1, exp_col2, exp_col3 = st.columns(3)
    with exp_col1:
        st.download_button(
            "⬇️ Download Updated Grid (GeoPackage)",
            data=to_geopackage_bytes(grid_with_counts, layer_name="grid_with_counts"),
            file_name="grid_with_point_count.gpkg",
            mime="application/geopackage+sqlite3",
        )
    with exp_col2:
        st.download_button(
            "⬇️ Download Updated Grid (GeoJSON)",
            data=to_geojson_bytes(grid_with_counts),
            file_name="grid_with_point_count.geojson",
            mime="application/geo+json",
        )
    with exp_col3:
        st.download_button(
            "⬇️ Download CSV Summary",
            data=to_csv_bytes(grid_with_counts),
            file_name="grid_with_point_count.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
