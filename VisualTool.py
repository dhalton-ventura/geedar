#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEEDaR Visual Tool

An application for visualization of satellite images and of results from GEEDaR 
algorithms.

"""
__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.0.2"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"


#%% Import and config

import os
import json
import copy
import streamlit as st
import folium
import ee

# Earth Engine initialization.
# Look for the json config file. If it is not found, try to initialize without
# a project id. It may work if a default project was set for the Earth Engine
# API. If the file is found, use the project id defined there.
@st.cache_resource
def init_earth_engine():
    """
    Initializes the Earth Engine API.
    
    """
    print("\nStarting GEEDaR Visual Tool " + __version__ + "...")
    print("Initializing the Earth Engine API...")

    _json_file = "ee_init.json"
    if not os.path.isfile(_json_file):
        project_id = None
    else:
        with open(_json_file, "r") as file:
            _json_content = json.load(file)
            project_id = _json_content["project_id"]
    try:
        ee.Initialize(project=project_id)
    except:
        ee.Authenticate()
        ee.Initialize(project=project_id)
init_earth_engine()

from folium.plugins import Draw
from streamlit_folium import st_folium
from datetime import datetime, date, timedelta

from products import product_catalog
from cloud_algorithms import cloud_algo_catalog
from reducers import reducer_catalog
from local_algorithms import local_algo_catalog
from variables import variable_catalog
from instruments import instrument_catalog
from db_config import db_config
from geedar_classes import VirtualStation
from visual_tool_functions import (add_ee_layer, 
    reset_session, switch_to_mode,
    get_basic_data_from_csv,
    get_station_list, extract_station_code,
    get_aoi, get_centroid, 
    set_available_dates, set_nav_dates, 
    get_available_products, prepare_product, 
    get_cloud_algo_list, get_local_algo_list,
    get_result_data, create_raster_overlay)

# Add this as a method of Folium's Map to integrate EE to standard Folium.
folium.Map.add_ee_layer = add_ee_layer

# What to show when no station was selected from the list?
st_placeholder = "Draw on map..."


#%% State Management

if "vt_mode" not in st.session_state:
    st.session_state.vt_mode = 0 # 0 - image explorer; 1 - result reviewer
    st.toast("Starting in image exploring mode...", icon="🗺️")
if "uploaded_csv" not in st.session_state:
    st.session_state.uploaded_csv = None
if "geedar_db" not in st.session_state:
    st.session_state.geedar_db = None
if "import_info" not in st.session_state:
    st.session_state.import_info = None
if "last_reading" not in st.session_state:
    st.session_state.last_reading = -1

if "stations" not in st.session_state:
    st.session_state.stations = {}
if "active_station" not in st.session_state:
    st.session_state.active_station = None
if "aoi" not in st.session_state:
    st.session_state.aoi = None
    
if "target_date" not in st.session_state:
    st.session_state.target_date = (datetime.now() - timedelta(days=2)).date()
if "product_dates" not in st.session_state:
    st.session_state.product_dates = dict()
if "nav_dates" not in st.session_state:
    st.session_state.nav_dates = []

if "product_catalog" not in st.session_state:
    st.session_state.product_catalog = copy.deepcopy(product_catalog)
if "product_sel" not in st.session_state:
    st.session_state.product_sel = None
if "active_product" not in st.session_state:
    st.session_state.active_product = None

if "cloud_algo_sel" not in st.session_state:
    st.session_state.cloud_algo_sel = None

if "local_algo_sel" not in st.session_state:
    st.session_state.local_algo_sel = None

if "result_dict" not in st.session_state:
    st.session_state.result_dict = None

if "var_sel" not in st.session_state:
    st.session_state.var_sel = None
if "stat_sel" not in st.session_state:
    st.session_state.stat_sel = None
if "min_val" not in st.session_state:
    st.session_state.min_val = None
if "max_val" not in st.session_state:
    st.session_state.max_val = None

if "start_location" not in st.session_state:
    st.session_state.start_location = [-15.79, -47.81]

if "display_msg" not in st.session_state:
    st.session_state.display_msg = None
else:
    if st.session_state.display_msg:
        st.toast(st.session_state.display_msg["text"], 
            icon=st.session_state.display_msg["icon"])
        st.session_state.display_msg = None
    

#%% Layout

st.set_page_config(layout="wide", page_title="GEEDaR Visual Tool")

# Left panel: date, product, algorithms.
with st.sidebar:
    
    # Import tool: read stations and data from a file or database.
    st.title("Import (optional)")
    source = st.radio("Source:", ["csv", "database"], horizontal=True, 
        label_visibility="collapsed")
    import_info = None    
    if source == "csv":
        st.session_state.geedar_db = None
        st.session_state.uploaded_csv = st.file_uploader("Import CSV", 
            type=["csv"], label_visibility="collapsed")        
        if st.session_state.uploaded_csv:
            with st.spinner("Reading input file..."):
                import_info = get_basic_data_from_csv(
                    st.session_state.uploaded_csv)
    elif source == "database":   
        st.session_state.uploaded_csv = None
        if st.button("Import from DB", use_container_width=True):
            # GeedarDB 
            st.session_state.display_msg = {
                "text": "Database connection triggered!",
                "icon": "🗄️"}
    if import_info:
        if import_info["reading_time"] != st.session_state.last_reading:
            st.session_state.last_reading = import_info["reading_time"]
            st.session_state.import_info = import_info
            st.session_state.stations = import_info["stations"]
            st.rerun()
    else:
        # The user removed the imported file, so reset the session.
        if st.session_state.import_info:
            reset_session()
            st.rerun()
    
    # Selection panel    
    st.title("Selection")
     
    # Station selection
    st.markdown("**1. Select a virtual station:**")
    st_index = 0
    if st.session_state.active_station:
        if st.session_state.active_station.station_code != st_placeholder:
            st_index = [*st.session_state.stations].index(
                st.session_state.active_station.station_code) + 1
    station_sel = st.selectbox("Station...", 
        get_station_list(st.session_state.stations, st_placeholder), 
        label_visibility="collapsed", index=st_index)
    new_station = False
    code_from_sel = extract_station_code(station_sel)
    if not st.session_state.active_station:
        if station_sel != st_placeholder:
            new_station = True
    else:
        station_code = st.session_state.active_station.station_code
        # Changed back to draw position?
        if (station_sel == st_placeholder and station_code != st_placeholder):
            st.session_state.stations[st_placeholder] = VirtualStation(
                st.session_state.active_station.aoi, st_placeholder)
            st.session_state.active_station = st.session_state.stations[
                st_placeholder]            
            switch_to_mode(0)
            st.rerun()
        # Or switched between stations?
        elif station_code != code_from_sel:
            new_station = True
    if new_station:
        station_code = code_from_sel
        st.session_state.active_station = st.session_state.stations[
            station_code]
        st.session_state.aoi = get_aoi(station_code)
        st.session_state.start_location = get_centroid(
            st.session_state.aoi)
        if st.session_state.vt_mode == 0:
            switch_to_mode(1)
        st.rerun()
    
    # Date and product widgets are defined flexibly according to 'vt_mode'.
    
    # List the valid dates.
    if st.session_state.active_station:
        with st.spinner("Checking available dates..."):
            set_available_dates(st.session_state.aoi, st.session_state.vt_mode)
    
    st.markdown("**2. Enter the date:**")       
    # Date navigation.
    date_col1, date_col2, date_col3, date_col4 = st.columns(4)
    set_nav_dates(st.session_state.aoi, station_sel, 
        st.session_state.product_sel, st.session_state.vt_mode)
    with date_col1:
        if st.button("|<"): 
            if st.session_state.product_sel:
                nav_dates = st.session_state.nav_dates
                if len(nav_dates) > 0:
                    st.session_state.target_date = nav_dates[0]
    with date_col2:
        if st.button("<"): 
            if st.session_state.vt_mode == 0:
                st.session_state.target_date -= timedelta(days=1)
            else:
                prev_dates = [d for d in st.session_state.nav_dates 
                    if d < st.session_state.target_date]
                if len(prev_dates) > 0:
                    st.session_state.target_date = prev_dates[-1]
    with date_col3:
        if st.button(">"): 
            if st.session_state.vt_mode == 0:
                st.session_state.target_date += timedelta(days=1)
            else:
                next_dates = [d for d in st.session_state.nav_dates 
                    if d > st.session_state.target_date]
                if len(next_dates) > 0:
                    st.session_state.target_date = next_dates[0]                
    with date_col4:
        if st.button(">|"):
            if st.session_state.product_sel:
                nav_dates = st.session_state.nav_dates
                if len(nav_dates) > 0:
                    st.session_state.target_date = nav_dates[-1]
    
    # Date selector.
    date_sel = st.date_input("Date", st.session_state.target_date, 
        label_visibility="collapsed", disabled=bool(st.session_state.vt_mode),
        min_value=date(1982, 1, 1), max_value=date.today())
    if (st.session_state.vt_mode == 0 
            and st.session_state.target_date != date_sel):
        st.session_state.target_date = date_sel
        st.rerun()
    
    # Product check.
    st.markdown("**3. Select a product:**")
    available_products = []
    if st.session_state.aoi and st.session_state.target_date:
        with st.spinner("Checking product availability..."):
            available_products = get_available_products(
                st.session_state.target_date, st.session_state.vt_mode)
    else:
        st.info("Station not yet defined or no available results.")
    product_index = 0
    if st.session_state.product_sel in available_products:
        product_index = available_products.index(
            st.session_state.product_sel)
    product_sel = st.selectbox("Product...", options=available_products, 
        label_visibility="collapsed", index=product_index)
    if st.session_state.product_sel != product_sel:
        st.session_state.product_sel = product_sel
        st.rerun()
        
    # Prepare the GEEDaR product.
    if product_sel:
        with st.spinner("Preparing product..."):        
            prepare_product(st.session_state.aoi, 
                st.session_state.target_date, product_sel)
    
    # Cloud algorithm.
    st.markdown("**4. Select a cloud algorithm:**")
    compatible_cloud_algos = []
    if st.session_state.active_product:
        with st.spinner("Listing compatible algorithms..."):
            compatible_cloud_algos = get_cloud_algo_list(product_sel, 
                st.session_state.vt_mode)
    cloud_algo_index = 0
    if st.session_state.cloud_algo_sel in compatible_cloud_algos:
        cloud_algo_index = compatible_cloud_algos.index(
            st.session_state.cloud_algo_sel)
    cloud_algo_sel = st.selectbox("Cloud algorithm...", compatible_cloud_algos, 
        label_visibility="collapsed", index=cloud_algo_index)
    if st.session_state.cloud_algo_sel != cloud_algo_sel:
        st.session_state.cloud_algo_sel = cloud_algo_sel
        st.rerun()
    
    # Local algorithm.
    st.markdown("**5. Select a local algorithm:**")
    local_algos = []
    if cloud_algo_sel:
        with st.spinner("Listing algorithms..."):
            local_algos = get_local_algo_list(station_sel, 
                st.session_state.vt_mode)
    local_algo_index = 0
    if st.session_state.local_algo_sel in local_algos:
        local_algo_index = local_algos.index(st.session_state.local_algo_sel)
    local_algo_sel = st.selectbox("Local algorithm...", local_algos, 
        label_visibility="collapsed", index=local_algo_index)
    if st.session_state.local_algo_sel != local_algo_sel:
        st.session_state.local_algo_sel = local_algo_sel
        st.rerun()
    
    # Retrieve data for the current station and demand.
    result_dict = None
    if local_algo_sel:
        with st.spinner("Retrieving data..."):
            result_dict = get_result_data(station_sel, product_sel, 
                cloud_algo_sel, local_algo_sel, st.session_state.vt_mode)
    st.session_state.result_dict = result_dict
    
    # Result visualization: variable selection and scale.
    
    st.markdown("**6. Define the variable, statistic and min-max values for " 
        + "visualization:**")
    
    # Variable selection.
    var_list = []
    if result_dict:
        var_list = [*result_dict["var_dict"]]
    var_index = 0
    if st.session_state.var_sel in var_list:
        var_index = var_list.index(st.session_state.var_sel)
    var_sel = st.selectbox("Variable...", var_list, 
        label_visibility="collapsed", index=var_index)
    if st.session_state.var_sel != var_sel:
        st.session_state.var_sel = var_sel
        st.rerun()
    
    # Stat. and scale.
    var_col1, var_col2, var_col3 = st.columns([2, 1, 1])
    with var_col1:
        stat_list = []
        if result_dict:
            stat_list = [*result_dict["var_dict"][var_sel]]
        stat_index = 0
        if st.session_state.stat_sel in stat_list:
            stat_index = stat_list.index(st.session_state.stat_sel)
        stat_sel = st.selectbox("Statistics...", stat_list, 
            label_visibility="collapsed", index=stat_index)
        if st.session_state.stat_sel != stat_sel:
            st.session_state.stat_sel = stat_sel
            if stat_sel:
                st.session_state.min_val = result_dict["var_dict"][var_sel][
                    stat_sel]["min"]
                st.session_state.max_val = result_dict["var_dict"][var_sel][
                    stat_sel]["max"]
            st.rerun()
    with var_col2:
        val = 0
        if st.session_state.min_val:
            val = st.session_state.min_val
        min_val = st.number_input("Min", value=val, 
            label_visibility="collapsed")
        st.session_state.min_val = min_val
    with var_col3:
        val = 100
        if st.session_state.max_val:
            val = st.session_state.max_val
        max_val = st.number_input("Max", value=val, 
            label_visibility="collapsed")
        st.session_state.max_val = max_val
    
    #run_extraction = st.button("Run Extraction", type="primary", use_container_width=True)

# Main panel: map and graph.

col_map, col_results = st.columns([3, 1])
with col_map:
    st.subheader("Interactive Map")
    
    # Initialize a pure Folium map.
    m = folium.Map(location=st.session_state.start_location, zoom_start=15)
    Draw(export=True).add_to(m)
    
    # Add AoI back to map.
    if st.session_state.aoi:
        aoi_layer = folium.GeoJson(st.session_state.aoi, 
            style_function=lambda x: {'color': 'red'})
        aoi_layer.add_to(m)
    
    # Layers to be added to the map.
    dynamic_layers = []
    
    #  Create a dynamic FeatureGroup for the image.
    satellite_fg = folium.FeatureGroup(name="Satellite Image")
    
    # Bind the product image to the FeatureGroup. 
    if st.session_state.active_product:
        product = st.session_state.active_product
        product_name = product.product_name
        vis_params = product.vis_params        
        try:
            # Fetch the tile URL and add it to the FeatureGroup.
            image = product.collection.first()
            map_id_dict = ee.Image(image).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Map Data © Google Earth Engine',
                name=f"Product image: {product_name}",
                overlay=True,
                control=True
            ).add_to(satellite_fg)
            dynamic_layers.append(satellite_fg)
        except Exception as e:
            print(e)
            st.warning("Could not load image layer.")

    # Prepare a data layer.
    if var_sel and stat_sel:
        raster_dict = create_raster_overlay(result_dict, var_sel, min_val, 
            max_val)
        if raster_dict:
            color_scale = raster_dict["color_scale"]
            color_scale.add_to(m)
            raster_layer = raster_dict["raster_layer"]
            dynamic_layers.append(raster_layer)

    # Pass the FeatureGroup to st_folium to force an in-place frontend update.
    map_data = st_folium(m, height=600, use_container_width=True, 
        feature_group_to_add=dynamic_layers, 
        returned_objects=["last_active_drawing"])
    
    # Capture drawn polygon (if any).
    if map_data and map_data.get("last_active_drawing"):
        new_aoi = map_data["last_active_drawing"]["geometry"]
        # If a new draw was made, create the corresponding virtual station.
        if st.session_state.aoi != new_aoi:
            st.session_state.aoi = new_aoi
            st.session_state.start_location = get_centroid(new_aoi)
            if st.session_state.vt_mode == 1:
                st.session_state.vt_mode = 0
                st.session_state.display_msg = {
                    "text": "Switched to image exploring mode.",
                    "icon": "🗺️"}
            new_station = VirtualStation(ee.Geometry(new_aoi), st_placeholder)
            new_st_dict = {st_placeholder: new_station}
            st.session_state.stations = (new_st_dict 
                | {k:v for k,v in st.session_state.stations.items() 
                if str(k) != st_placeholder})
            st.session_state.active_station = st.session_state.stations[
                st_placeholder]
            st.rerun()

with col_results:
    st.subheader("Results")
    with st.expander("Statistical Summary", expanded=True):
        st.selectbox("Band or variable", [var_sel, "NIR", "red"], key="result_var")
        
        st.metric("Median", "No data")
        st.metric("Min", "No data")
        st.metric("Max", "No data")
        st.metric("Mean", "No data")
        st.metric("Std Dev", "No data")
