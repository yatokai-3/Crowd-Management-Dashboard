# --------All the imports-----------

from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px


st.set_page_config(
    page_title="Sensor Explorer | SAIL 2025",
    page_icon="📈",
    layout="wide"
)


# -------All the page configurations----------
BASE_DIR=Path(__file__).resolve().parent.parent
DATA_DIR= BASE_DIR / "Final Data"

PED_FILE= DATA_DIR/"pedestrian_counts.parquet"
LOCATION_FILE=DATA_DIR/"sensor_location_clean.csv"

st.title("SAIL 2025 | Crowd Management Dashboard")
st.caption ("Explore pedestrian activity across sensor locations in SAIL event.")



# -----Load Data--------
@st.cache_data
def load_data():
    ped = pd.read_parquet(PED_FILE)
    locations = pd.read_csv(LOCATION_FILE)

    ped["timestamp"] = pd.to_datetime(ped["timestamp"], errors="coerce")
    ped["pedestrian_count"] = pd.to_numeric(
        ped["pedestrian_count"], errors="coerce"
    )

    return ped, locations

# '''checking is the file exists or not'''

if not PED_FILE.exists():
    st.error(f"Pedestrian dataset not found: {PED_FILE}")
    st.info("Export pedestrian_counts.parquet into the Final Data folder.")
    st.stop()

if not LOCATION_FILE.exists():
    st.error(f"Sensor location file not found: {LOCATION_FILE}")
    st.info("Place sensor_locations.csv in the Final Data folder.")
    st.stop()

ped, locations = load_data()


# -------------------------------------------
# SIDEBAR Filters and Design
# --------------------------------------------
st.sidebar.header("Sensor Explorer")


available_locations=sorted(
    ped["location_name"].dropna().unique().tolist()
    )

selected_location=st.sidebar.selectbox(
    "Select Location",
    available_locations
)

location_data=ped[ped["location_name"]==selected_location]

available_dates = sorted(
    location_data["timestamp"].dt.date.dropna().unique()
)

if not available_dates:
    st.warning("No valid timestamps are available for this location.")
    st.stop()

# if user select "ALL", print count across all date.. . . .
date_options=["All"] + available_dates
selected_date = st.sidebar.selectbox(
    "Select date",
    date_options,
)


# --------------------------------------------------
# FILTER SELECTED DATA
# --------------------------------------------------


if selected_date=="All":
    # if all gets selected . . .then select all the dates
    filtered=location_data.copy()

    min_time = filtered["timestamp"].dt.time.min()
    max_time = filtered["timestamp"].dt.time.max()

    start_time, end_time = st.sidebar.slider(
        "Time Range",
        min_value=min_time,
        max_value=max_time,
        value=(min_time, max_time),
        format="HH:mm"
    )


    filtered = filtered[
        filtered["timestamp"].dt.time.between(start_time, end_time)
    ].copy()

else:
    # include only the selected date
    date_data = location_data[
        location_data["timestamp"].dt.date == selected_date
    ]

    min_time = date_data["timestamp"].dt.time.min()
    max_time = date_data["timestamp"].dt.time.max()

    start_time, end_time = st.sidebar.slider(
        "Time range",
        min_value=min_time,
        max_value=max_time,
        value=(min_time, max_time),
        format="HH:mm"
    )


    filtered = date_data[
        date_data["timestamp"].dt.time.between(start_time, end_time)
    ].copy()

# --------------------------------------------------
# LOCATION DESCRIPTION
# --------------------------------------------------
st.subheader(selected_location)

location_info = locations[
    locations["location_name"] == selected_location
]

if not location_info.empty:
    info = location_info.iloc[0]

    c1, c2, c3 = st.columns(3)

    c1.metric("Sensor ID", str(info["object_number"]))

    if "effective_width" in info.index:
        c2.metric(
            "Effective width",
            f"{info['effective_width']} m"
            if pd.notna(info["effective_width"])
            else "Not available"
        )

    if "Latitude" in info.index and "Longitude" in info.index:
        c3.write(
            f"Coordinates  \n"
            f"{info['Latitude']}, {info['Longitude']}"
        )

    if "location_name" in info.index:
        st.info(
            f"Pedestrian sensor location: {info['location_name']}. "
            "Counts represent recorded pedestrian detections per "
            "3-minute interval, not necessarily unique individuals."
        )

# --------------------------------------------------
# SUMMARY METRICS
# --------------------------------------------------
st.subheader("Pedestrian activity")

total_count = filtered["pedestrian_count"].sum()
peak_count = filtered["pedestrian_count"].max()
mean_count = filtered["pedestrian_count"].mean()

m1, m2, m3 = st.columns(3)

m1.metric("Total recorded counts", f"{total_count:,.0f}")
m2.metric(
    "Peak 3-minute count",
    f"{peak_count:,.0f}" if pd.notna(peak_count) else "—"
)
m3.metric(
    "Average per record",
    f"{mean_count:,.1f}" if pd.notna(mean_count) else "—"
)

# --------------------------------------------------
# DIRECTIONAL GRAPHS
# --------------------------------------------------
st.subheader("Pedestrian counts by direction")

if filtered.empty:
    st.warning("No observations match the selected filters.")
else:

    # --------small detouring for x axis labelling---------
    if selected_date=="All":
        x_axis_value="Days"
    else:
        x_axis_value="Time"
    # -----------------------------------------------------

    directions = sorted(
        filtered["direction"].dropna().astype(str).unique()
    )
    
    if not directions:
        st.warning("No direction data available.")
    else:
        cols = st.columns(2)

        for i, direction in enumerate(directions[:2]):
            direction_data = filtered[
                filtered["direction"].astype(str) == direction
            ].sort_values("timestamp")

            with cols[i]:
                # st.markdown(f"##### Direction {direction}")
                (f"Direction {direction}")

                fig = px.line(
                    direction_data,
                    x="timestamp",
                    y="pedestrian_count",
                    labels={
                        "timestamp": x_axis_value,
                        "pedestrian_count": "Pedestrian count"
                    },
                    render_mode="svg"
                )

                fig.update_layout(
                    height=350,
                    margin=dict(l=10, r=10, t=20, b=10)
                )

                st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------
# DATA PREVIEW
# --------------------------------------------------
# with st.expander("View filtered records"):
#     st.dataframe(filtered, use_container_width=True)

# st.caption(
#     "SAIL 2025 | Initial dashboard prototype — "
#     "data preparation and visualisations will be refined."
# )
 