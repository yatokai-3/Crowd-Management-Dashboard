
import streamlit as st

st.set_page_config(
    page_title="SAIL Crowd Management Dashboard",
    page_icon="📊",
    layout="wide"
)

# Register all pages and attach them to sidebar navigation

map_page = st.Page(
    "pages/pedestrian_map.py",
    title="Pedestrian Map",
    icon=":material/map:"
)

sensor_page = st.Page(
    "pages/sensor_explorer.py",
    title="Sensor Explorer",
    icon=":material/sensors:",
    default=True
)

vessel_page = st.Page(
    "pages/vessel_flow.py",
    title="Vessel Flow",
    icon=":material/directions_boat:"
)

# Central navigation
navigation = st.navigation(
    {
        "Crowd Management": [
            sensor_page,
            map_page,
            vessel_page
        ]
    },
    position="sidebar"
)

navigation.run()
