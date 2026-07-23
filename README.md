# GTS GPS Analytics

A production-ready Streamlit GIS application for cleaning, filtering, and
analysing GPS tracks collected from GTS devices against user-uploaded
state boundaries and campaign grids. Nothing is hardcoded — every spatial
layer (boundary, grid, and GPS tracks) is supplied at runtime, so the same
app works for any Nigerian state, or any location worldwide.

## Structure

```
app.py                        # Landing page
pages/
    1_Data_Preparation.py     # Module 1 — clean & standardise GPS tracks
    2_GPS_Analytics.py        # Module 2 — spatial join, stats, mapping, charts
utils/
    io.py                     # File readers (Shapefile .zip, GeoPackage, GeoJSON, CSV)
    preprocessing.py          # Geometry repair, reprojection, coordinate cleaning
    spatial.py                # Bbox pre-filter, polygon clip, spatial join, point counts
    analytics.py              # Grid statistics
    mapping.py                # Folium interactive map
    exports.py                # GeoPackage / CSV / GeoJSON export helpers
requirements.txt
```

## Setup

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> Note: `fiona`/`pyogrio` depend on GDAL. On most platforms `pip install`
> pulls prebuilt wheels automatically. If installation fails, install GDAL
> via your OS package manager (e.g. `conda install -c conda-forge gdal`)
> first.

## Run

```bash
streamlit run app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).
Use the sidebar to switch between **Module 1 — Data Preparation** and
**Module 2 — GPS Analytics**.

## Workflow

1. **Module 1**: Upload a state boundary (Shapefile .zip / GeoPackage /
   GeoJSON) and one or many raw GPS-track CSV files. The module merges
   the CSVs, cleans coordinates, clips points to the boundary (bbox
   pre-filter + exact polygon clip for speed), filters by speed, and
   lets you export the cleaned dataset (GeoPackage / CSV / GeoJSON).
2. **Module 2**: Upload the prepared dataset from Module 1 plus your own
   campaign grid. The module spatially joins points to grid cells,
   computes `Point_Count` per cell (including zero-point cells),
   displays dashboard statistics, an interactive Folium map colour-graded
   by `Point_Count`, a searchable/sortable summary table, histogram /
   top-20 bar chart / visited-vs-unvisited pie chart, and lets you export
   the updated grid and summary as GeoPackage, GeoJSON, and CSV.

## Performance notes

- Bounding-box pre-filtering runs before the exact polygon clip to avoid
  expensive geometry operations on points that are obviously outside the
  area of interest.
- CSV uploads are read in chunks to bound memory use for very large files.
- Spatial joins use GeoPandas' `sjoin` (STRtree-indexed) rather than
  nested-loop comparisons.
- Uploads and the analysis pipeline are wrapped in `@st.cache_data` where
  it's safe to do so, so re-running the Streamlit script on widget
  interaction doesn't re-parse unchanged files.
- The map subsamples GPS points (default cap: 20,000) and renders them
  through a marker cluster so the browser stays responsive even when the
  underlying dataset has millions of points.

## Error handling

Every upload path (boundary, grid, GPS CSVs, prepared dataset) validates
input and surfaces a clear `st.error` message rather than crashing on
missing columns, wrong/absent CRS, empty datasets, invalid geometries,
corrupt shapefiles/CSVs, or missing grid IDs. Per-file CSV errors are
collected and shown in an expandable log without aborting the whole batch.
