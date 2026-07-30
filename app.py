"""
app.py
======
Landing page / entry point for the GTS GPS Analytics Streamlit application.

Run with:
    streamlit run app.py

The actual functionality lives in the two independent pages under
``pages/``, which Streamlit automatically surfaces in the sidebar:

    1_Data_Preparation.py  -> Module 1: clean & standardise GPS tracks
    2_GPS_Analytics.py     -> Module 2: spatial join, statistics, mapping
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="GTS Analytics",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Render the landing / home page."""
    st.title("🛰️ GTS Analytics")
    st.caption("A generic, state-agnostic GIS toolkit for campaign GTS-track analysis.")

    st.markdown(
        """
        Welcome. This application is organised into two modules,
        available in the sidebar:

        ### 📦 Module 1 — GTS Data Preparation
        Upload a state boundary and raw GTS-track CSV files. The module
        repairs geometries, cleans coordinates, filters by boundary
        (bounding-box pre-filter + exact polygon clip), removes
        high-speed records, and exports a clean prepared GTS dataset ready for analysis.

        ### 📊 Module 2 — GTS Analytics
        The prepared GTS dataset from Module 1 is automatically preloaded
        (or you can upload a custom file) together with your own campaign grid.
        The module performs a spatial join, computes `Point_Count` and
        `Visitation_Status` per grid cell, renders an interactive map, and
        produces summary tables, charts, and exports.

        ---

        **Nothing is hardcoded.** Every boundary and grid is supplied by
        you, so the same application works for any Nigerian state — or
        any location in the world.

        👈 Use the sidebar to get started.
        """
    )

    with st.expander("ℹ️ Tips for best performance"):
        st.markdown(
            """
            - For very large CSV batches, upload in smaller batches (e.g. 50
              files at a time) if you hit browser upload limits.
            - Run Module 1 first to prepare raw tracks, or upload a pre-cleaned dataset in Module 2.
            - Grid and boundary files should use a consistent, unique ID
              column (e.g. `Grid_ID`) for best results.
            """
        )



if __name__ == "__main__":
    main()
