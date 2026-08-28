#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Functions for GEEDaR Visual Tool.

"""
__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.1"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"


#%% Import and config

import json
import copy
import pandas
import numpy as np
import streamlit as st
import folium
import branca.colormap as cm
import ee

from datetime import datetime, timedelta, timezone
from geedar_core.app import GeedarApp
from geedar_core.demand import Demand
from geedar_core.station import VirtualStation
from geedar_core.utils import cast_numeric_list, extract_from_kml
from cloud_algorithms import cloud_algo_catalog
from reducers import reducer_catalog
from local_algorithms import local_algo_catalog
from db_config import db_config


#%% Functions
#%% Functions

# This will be added to Folium's Map to integrate EE and standard Folium.
def add_ee_layer(self, ee_image_object, vis_params, name):
    """
    Fetches Earth Engine image tiles and adds them to a Folium map.
    
    """
    map_id_dict = ee.Image(ee_image_object).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr='Map Data © Google Earth Engine',
        name=name,
        overlay=True,
        control=True
    ).add_to(self)

# Gets the first pair of coordinates of any GeoJSON.
def get_first_coord(geojson_geom):
    """
    Returns the first [latitude, longitude] pair from any GeoJSON geometry.
    
    """
    g_type = geojson_geom['type']
    coords = geojson_geom['coordinates']

    if g_type == 'Point':
        first = coords
    elif g_type in ['LineString', 'MultiPoint']:
        first = coords[0]
    elif g_type in ['Polygon', 'MultiLineString']:
        # First point of the first ring/line.
        first = coords[0][0]
    elif g_type == 'MultiPolygon':
        # First point of the first ring of the first polygon
        first = coords[0][0][0]
    else:
        raise ValueError(f"Unsupported geometry type: {g_type}")
    
    return first[::-1]

# Returns a simple centroid for the input GeoJSON.
def get_centroid(geojson_geom):
    """
    Returns a simple centroid [latitude, longitude] from any GeoJSON geometry.
    
    """
    g_type = geojson_geom['type']
    coords = geojson_geom['coordinates']

    if g_type == 'Point':
        center_lat = coords[1]
        center_long = coords[0]
    elif g_type in ['LineString', 'MultiPoint']:
        center_lat = sum(c[1] for c in coords) / len(coords)
        center_long = sum(c[0] for c in coords) / len(coords)
    elif g_type in ['Polygon', 'MultiLineString']:
        # First point of the first ring/line.
        center_lat = sum(c[1] for c in coords[0]) / len(coords[0])
        center_long = sum(c[0] for c in coords[0]) / len(coords[0])
    elif g_type == 'MultiPolygon':
        # First point of the first ring of the first polygon
        center_lat = sum(c[1] for c in coords[0][0]) / len(coords[0][0])
        center_long = sum(c[0] for c in coords[0][0]) / len(coords[0][0])
    else:
        raise ValueError(f"Unsupported geometry type: {g_type}")
    
    return [center_lat, center_long]

# Resets the crucial state objects.
def reset_session():
    st.session_state.import_info = None
    st.session_state.last_reading = -1
    st.session_state.stations = {}
    st.session_state.aoi = None
    st.session_state.active_station = None
    st.session_state.active_product = None
    st.session_state.vt_mode = 0

# Changes the Visual Tool operation mode.
def switch_to_mode(vt_mode):
    if st.session_state.vt_mode != vt_mode:
        if vt_mode == 0:
            st.session_state.display_msg = {
                "text": "Switched to image exploring mode.",
                "icon": "🗺️"}
        else:
            st.session_state.display_msg = {
                "text": "Switched to result reviewing mode.",
                "icon": "📈"}
    st.session_state.vt_mode = vt_mode

# Returns the station list for the station selector with strings in the form 
# code - name.
def get_station_list(stations, st_placeholder):
    station_list = [st_placeholder]
    for station_code, station in stations.items():
        if str(station_code) == st_placeholder:
            continue
        station_name = station.station_name
        if str(station_code) == station_name:
            sel_str = station_code
        else:
            sel_str = station_code + " - " + station_name
        station_list.append(sel_str)
    return station_list

# Separates the code part from the station identification string.
@st.cache_data(show_spinner=False)
def extract_station_code(station_sel):
    if station_sel in st.session_state.stations:
        return station_sel
    parts = station_sel.split(" - ")
    if len(parts) == 1:
        return station_sel
    else:
        return " - ".join(parts[:-1])

# Retrieves the geometry of the area of interest.
@st.cache_data(show_spinner=False)
def get_aoi(station_code):
    return st.session_state.stations[station_code].aoi.getInfo()

# Sets the available dates for the active station, grouped by product.
@st.cache_data(show_spinner=False)
def set_available_dates(aoi_dict, vt_mode):
    if not aoi_dict:
        return
    station_code = st.session_state.active_station.station_code    
    if vt_mode == 1:
        dates_dict = st.session_state.import_info["available_dates"]
        if station_code not in dates_dict:
            return
    else:
        aoi = ee.Geometry(aoi_dict)

    product_catalog = st.session_state.product_catalog
    product_dates = dict()
    new_target_date = None
        
    for code in product_catalog:
        if st.session_state.vt_mode == 1:
            if code in dates_dict[station_code]:
                unique_dates = dates_dict[station_code][code]
            else:
                unique_dates = []
        else:
            product = product_catalog[code]
            raw_times_ms = ee.ImageCollection(
                product.original_collection).filterBounds(aoi).aggregate_array(
                "system:time_start").getInfo()
            unique_dates = {datetime.fromtimestamp(ts / 1000.0, 
                tz=timezone.utc).date() for ts in raw_times_ms 
                if ts is not None}        
        if len(unique_dates) > 0:
            date_list = sorted(list(unique_dates))
            product_dates[code] = date_list
            if not new_target_date:
                new_target_date = product_dates[code][0]
    st.session_state.product_dates = product_dates
    if new_target_date and st.session_state.vt_mode == 1:
        st.session_state.target_date = new_target_date
        
# Sets the list of dates for panel navigation.
@st.cache_data(show_spinner=False)
def set_nav_dates(aoi_dict, station_sel, product_sel, vt_mode):
    if not product_sel:
        st.session_state.nav_dates = []
        return
    product_code = int(product_sel.split(" ")[0])
    if vt_mode == 0:
        st.session_state.nav_dates = st.session_state.product_dates[
            product_code]
    else:
        st.session_state.nav_dates = sorted(list(set([el for lst in 
            st.session_state.product_dates.values() for el in lst])))      

# Given a date, checks the available products.        
@st.cache_data(show_spinner=False)
def get_available_products(target_date, vt_mode):
    product_catalog = st.session_state.product_catalog
    product_dates = st.session_state.product_dates
    available_products = []
    for product_code in product_dates:
        if target_date in product_dates[product_code]:
            product = product_catalog[product_code]
            product_name = product.product_name
            available_products.append(f"{product_code} - {product_name}")
    return available_products

# Optimizes a product for image displaying.
@st.cache_data(show_spinner=False)
def prepare_product(aoi_dict, target_date, product_sel):
    if not aoi_dict or not product_sel:
        st.session_state.active_product = None
        return
    product_code = int(product_sel.split(" ")[0])
    product_catalog = st.session_state.product_catalog
    if (product_code not in product_catalog or product_code not in 
            st.session_state.product_dates):
        st.session_state.active_product = None
        return
    if target_date not in st.session_state.product_dates[product_code]:
        st.session_state.active_product = None
        return
    product = product_catalog[product_code]
    next_day = (target_date + timedelta(days=1))
    product.optimize_collection(st.session_state.active_station, 
        start_date = target_date, end_date = next_day)
    st.session_state.display_msg = {"text": f"Loading {product_sel}...",
        "icon": "🛰️"}
    st.session_state.active_product = product

# Lists the cloud algorithms compatible with the active product. The returned 
# list has strings in the format "code - name" to feed the corresp. selector.
@st.cache_data(show_spinner=False)
def get_cloud_algo_list(product_sel, vt_mode):
    if not st.session_state.active_product:
        return []
    product = st.session_state.active_product
    if vt_mode > 0:
        station_code = st.session_state.active_station.station_code
        demands = st.session_state.import_info["demands"][station_code]
        ref_list = [d["C"] for d in demands.values()]
    else:
        ref_list = [*cloud_algo_catalog]
    algo_list = []
    for algo_code in ref_list:
        algo = cloud_algo_catalog[algo_code]
        # Check band compatibility.
        bands = [*product.get_data_bands()] + product.band_list
        required_bands = algo.required_bands
        missing = False
        for sublist in required_bands:
            if not isinstance(sublist, list):
                sublist = [sublist]
            if not any(band in sublist for band in bands):
                missing = True
                break
        if not missing:
            algo_name = algo.name
            algo_list.append(f"{algo_code} - {algo_name}")
    return algo_list

# Lists the local algorithms. The returned list has strings in the format 
# "code - name" to feed the corresp. selector.
@st.cache_data(show_spinner=False)
def get_local_algo_list(station_sel, vt_mode):
    if not st.session_state.active_product:
        return []
    if vt_mode > 0:
        station_code = st.session_state.active_station.station_code
        demands = st.session_state.import_info["demands"][station_code]
        ref_list = [d["L"] for d in demands.values()]
    else:
        ref_list = [*local_algo_catalog]
    algo_list = []
    for algo_code in ref_list:
        algo = local_algo_catalog[algo_code]
        algo_name = algo.name
        algo_list.append(f"{algo_code} - {algo_name}")
    return algo_list

# Reads a csv file containing GEEDaR results and extract info on stations, 
# demands and dates.
@st.cache_data(show_spinner=False)
def get_basic_data_from_csv(csv):
    # The dict to be returned.
    import_dict = {
        "success": False,
        "error_msgs": [],
        "reading_time": -1,
        "data_cols": [],
        "coord_cols": [],
        "stations": dict(),
        "available_dates": dict(),
        "demands": dict()
    }
    
    try:
        df = pandas.read_csv(csv)
    except:
        import_dict["error_msgs"].append("Failed to read the csv file.")
        return import_dict
        
    # Check columns.
    df_cols = [*df.columns]
    result_min_cols = GeedarApp._result_min_cols
    missing_cols = [c for c in result_min_cols if c not in df_cols]
    if len(missing_cols) > 0:
        import_dict["error_msgs"].append("Missing columns in the file: " 
            + str(missing_cols) + ".")
        return import_dict
    
    # Check rows.
    if len(df) == 0:
        import_dict["error_msgs"].append("Empty file.")
        return import_dict
    
    # Get station list.
    station_list = sorted(list(df["station_code"].unique()))
    if len(station_list) == 0:
        import_dict["error_msgs"].append("No valid data in the file.")
        return import_dict
    
    # Data columns.
    coord_cols = [c for c in df_cols if c.startswith("latitude_") 
        or c.startswith("longitude_")]
    img_time_ind = df_cols.index("img_time")
    extra_cols = [c for c in df_cols if c not in coord_cols 
        and df_cols.index(c) < img_time_ind]
    data_cols = [c for c in df_cols if c not in result_min_cols 
        + coord_cols + extra_cols]
    if len(data_cols) == 0:
        import_dict["error_msgs"].append("No data columns in the file.")
        return import_dict
    import_dict["data_cols"] = data_cols
    import_dict["coord_cols"] = coord_cols
       
    # Extract station and demand info.
    for station_code in station_list:        
        st_rows = df[df["station_code"] == station_code].index
        st_row = st_rows[0]
        try:
            geojson = json.loads(df.loc[st_row, "geojson"])
            aoi = ee.Geometry(geojson)
        except Exception as e:
            import_dict["error_msgs"].append(str(e) + " Could not determine "
                + "geometry of station " + station_code + ".")
            continue
        try:
            lat = float(df.loc[st_row, "lat"])
            long = float(df.loc[st_row, "long"])
        except:
            coords = get_centroid(geojson)
            lat = coords[0]
            long = coords[1]
        station_name = str(df.loc[st_row, "station_name"])
        # Create station object.
        try:
            cur_station = VirtualStation(aoi, station_code, station_name, 
                lat, long)
        except:
            import_dict["error_msgs"].append("Could not create VirtualStation "
                + "object for station '" + station_code + "'.")
            continue
        
        # Since station data is ok, insert it into the result dict.
        import_dict["stations"][station_code] = cur_station
        
        # Demands and available dates for the current station.
        import_dict["available_dates"][station_code] = dict()
        import_dict["demands"][station_code] = dict()
        demand_list = list(df.loc[st_rows, "demand_code"].unique())
        for demand_code_str in demand_list:
            dm_rows = df.loc[(df["station_code"] == station_code) 
                & (df["demand_code"] == demand_code_str)].index
            dm_row = dm_rows[0]            
            try:
                demand_code_dict = Demand.unfold_demand_code(demand_code_str)
            except:
                import_dict["error_msgs"].append("Invalid demand code in row " 
                    + str(dm_row) + ".")
                continue
            
            # Any valid data?
            data_rows = df.loc[(df["station_code"] == station_code) 
                & (df["demand_code"] == demand_code_str) 
                & pandas.notna(df["img_date"]) 
                & pandas.notna(df["img_time"])].index
            if len(data_rows) == 0:
                import_dict["error_msgs"].append("No data for the station '" 
                    + station_code + "' and demand " + demand_code_str + ".")
                continue
                                    
            # Available dates.
            product_code = demand_code_dict["P"]
            try:
                date_list = list(pandas.to_datetime(df.loc[data_rows, 
                    "img_date"]).dt.date)
            except Exception as e:
                print(e)
                import_dict["error_msgs"].append(str(e) + " Failed to " 
                    + "retrieve dates from the input data for the station '" 
                    + station_code + "' and demand '" + demand_code_str 
                    + "'.")
                continue
            # If there is valid data, save info.
            import_dict["available_dates"][station_code][
                product_code] = date_list
            import_dict["demands"][station_code][
                demand_code_str] = demand_code_dict
            
    import_dict["success"] = True
    import_dict["reading_time"] = datetime.now().microsecond
    st.session_state.display_msg = {"text": "CSV file loaded!",
        "icon": "📄"}    
    return import_dict

# Reads data from GeedarDB and extracts info on stations.
@st.cache_data(show_spinner=False)
def get_basic_data_from_db(_geedar_db):
    import_dict = {
        "success": False,
        "error_msgs": [],
        "reading_time": -1,
        "data_cols": [],
        "coord_cols": [],
        "stations": dict(),
        "available_dates": dict(),
        "demands": dict()
    }
    
    try:
        df_station = _geedar_db.get_table("station")
        df_demand = _geedar_db.get_demands()
    except Exception as e:
        import_dict["error_msgs"].append(f"Database read error: {e}")
        return import_dict
    
    if len(df_station) == 0:
        import_dict["error_msgs"].append("No stations found in database.")
        return import_dict

    db_names = _geedar_db.db_names
    use_real = _geedar_db.use_real_col_names
    
    col_st_code = db_names["station"]["code"] if use_real else "station.code"
    col_st_name = db_names["station"]["name"] if use_real else "station.name"
    col_st_lat = db_names["station"]["lat"] if use_real else "station.lat"
    col_st_long = db_names["station"]["long"] if use_real else "station.long"
    col_st_id = db_names["station"]["primary_key"] if use_real else "station.primary_key"

    col_dm_st_id = db_names["station"]["primary_key"] if use_real else "station.primary_key"
    col_aoi_mode = db_names["demand"]["aoi_mode"] if use_real else "demand.aoi_mode"
    col_aoi_radius = db_names["demand"]["aoi_radius"] if use_real else "demand.aoi_radius"
    col_kml_path = db_names["demand"]["kml_path"] if use_real else "demand.kml_path"
    
    for _, st_row in df_station.iterrows():
        station_id = st_row[col_st_id]
        station_code = str(st_row[col_st_code])
        station_name = str(st_row[col_st_name])
        lat = float(st_row[col_st_lat])
        long = float(st_row[col_st_long])
        
        st_demands = df_demand[df_demand[col_dm_st_id] == station_id]
        if len(st_demands) == 0:
            continue
            
        first_dm = st_demands.iloc[0]
        aoi_mode = first_dm[col_aoi_mode]
        aoi_radius = first_dm[col_aoi_radius]
        kml_path = first_dm[col_kml_path]
        
        geojson = None
        try:
            if aoi_mode == 1 and pandas.notna(kml_path):
                gdict = extract_from_kml(kml_path, what="geojson", aggregate=True)
                for g in ["MultiPolygon", "MultiLineString", "MultiPoint"]:
                    if g in gdict:
                        geojson = gdict[g][0]
                        break
            elif aoi_mode == 0:
                if pandas.isna(aoi_radius) or aoi_radius == 0:
                    geojson = ee.Geometry.Point([long, lat]).getInfo()
                else:
                    geojson = ee.Geometry.Point([long, lat]).buffer(int(aoi_radius)).getInfo()
            
            if geojson is None:
                raise ValueError("Could not determine geometry.")
            
            aoi = ee.Geometry(geojson)
            cur_station = VirtualStation(aoi, station_code, station_name, lat, long)
            import_dict["stations"][station_code] = cur_station
            import_dict["available_dates"][station_code] = dict()
            import_dict["demands"][station_code] = dict()
        except Exception as e:
            import_dict["error_msgs"].append(f"Failed to create VirtualStation for {station_code}: {e}")
            continue
            
    import_dict["success"] = True
    import_dict["reading_time"] = datetime.now().microsecond
    st.session_state.display_msg = {"text": "Database stations loaded!", "icon": "🗄️"}    
    return import_dict

@st.cache_data(show_spinner=False)
def update_import_info_for_station_from_db(_geedar_db, station_code, import_info):
    if not station_code or not import_info:
        return import_info
        
    if len(import_info["demands"].get(station_code, {})) > 0:
        return import_info

    try:
        df_demand = _geedar_db.get_demands()
        df_station = _geedar_db.get_table("station")
    except Exception as e:
        print(f"Error fetching demands: {e}")
        return import_info

    db_names = _geedar_db.db_names
    use_real = _geedar_db.use_real_col_names
    
    col_st_code = db_names["station"]["code"] if use_real else "station.code"
    col_st_id = db_names["station"]["primary_key"] if use_real else "station.primary_key"
    
    st_rows = df_station[df_station[col_st_code] == station_code]
    if len(st_rows) == 0:
        return import_info
    station_id = st_rows.iloc[0][col_st_id]
    
    col_dm_st_id = db_names["station"]["primary_key"] if use_real else "station.primary_key"
    col_dm_id = db_names["demand"]["primary_key"] if use_real else "demand.primary_key"
    col_prod = db_names["product"]["primary_key"] if use_real else "product.primary_key"
    col_cloud = db_names["cloud_algo"]["primary_key"] if use_real else "cloud_algo.primary_key"
    col_local = db_names["local_algo"]["primary_key"] if use_real else "local_algo.primary_key"
    col_reducer = db_names["reducer"]["primary_key"] if use_real else "reducer.primary_key"
    
    st_demands = df_demand[df_demand[col_dm_st_id] == station_id]
    
    if len(st_demands) == 0:
        return import_info
        
    demand_ids = st_demands[col_dm_id].tolist()
    
    try:
        df_data = _geedar_db.get_data(demand_id=demand_ids)
    except Exception as e:
        print(f"Error fetching data for station {station_code}: {e}")
        return import_info

    col_date = db_names["acquisition"]["date"] if use_real else "acquisition.date"
    col_var_name = db_names["variable"]["name"] if use_real else "variable.name"
    col_dm_id_data = db_names["demand"]["primary_key"] if use_real else "demand.primary_key"
    
    for _, dm_row in st_demands.iterrows():
        d_id = dm_row[col_dm_id]
        p = dm_row[col_prod]
        c = dm_row[col_cloud]
        l = dm_row[col_local]
        r = dm_row[col_reducer]
        
        demand_code_str = f"P{p}C{c}L{l}R{r}"
        
        dm_data = df_data[df_data[col_dm_id_data] == d_id]
        if len(dm_data) == 0:
            continue
            
        date_list = list(pandas.to_datetime(dm_data[col_date]).dt.date.unique())
        
        if p not in import_info["available_dates"][station_code]:
            import_info["available_dates"][station_code][p] = []
        
        import_info["available_dates"][station_code][p].extend(date_list)
        import_info["available_dates"][station_code][p] = list(set(import_info["available_dates"][station_code][p]))
        
        import_info["demands"][station_code][demand_code_str] = {
            "P": p, "C": c, "L": l, "R": r
        }
    
    if len(import_info["data_cols"]) == 0 and len(df_data) > 0:
        vars_present = df_data[col_var_name].unique().tolist()
        import_info["data_cols"] = vars_present

    return import_info

# Retrieves GEEDaR results from a csv or database for the current station, 
# product, cloud algo and local algo. All available stats will be included.
@st.cache_data(show_spinner=False)
def get_result_data(station_sel, product_sel, cloud_algo_sel, 
        local_algo_sel, vt_mode):
    if not st.session_state.active_station:
        return
    station_code = st.session_state.active_station.station_code
    product_code = product_sel.split(" - ")[0]
    cloud_algo_code = cloud_algo_sel.split(" - ")[0]
    local_algo_code = local_algo_sel.split(" - ")[0]
    result_dict = None
    if vt_mode > 0 and st.session_state.uploaded_csv:
        result_dict = get_result_data_from_csv(station_code, product_code, 
            cloud_algo_code, local_algo_code)
    elif vt_mode > 0 and st.session_state.geedar_db:
        result_dict = get_result_data_from_db(st.session_state.geedar_db, station_code, product_code, 
            cloud_algo_code, local_algo_code)
    elif vt_mode == 0:
        pass
    else:
        print("(!) Something is missing. Could not retrieve result data.")
        return
    return result_dict

# Auxilliary function for 'get_result_data' to read from db.
def get_result_data_from_db(_geedar_db, station_code, product_code, cloud_algo_code, local_algo_code):
    if not st.session_state.import_info:
        return
        
    db_names = _geedar_db.db_names
    use_real = _geedar_db.use_real_col_names
    
    df_station = _geedar_db.get_table("station")
    col_st_code = db_names["station"]["code"] if use_real else "station.code"
    col_st_id = db_names["station"]["primary_key"] if use_real else "station.primary_key"
    st_rows = df_station[df_station[col_st_code] == station_code]
    if len(st_rows) == 0:
        return
    station_id = st_rows.iloc[0][col_st_id]
    
    df_demand = _geedar_db.get_demands()
    col_dm_st_id = db_names["station"]["primary_key"] if use_real else "station.primary_key"
    col_dm_id = db_names["demand"]["primary_key"] if use_real else "demand.primary_key"
    col_prod = db_names["product"]["primary_key"] if use_real else "product.primary_key"
    col_cloud = db_names["cloud_algo"]["primary_key"] if use_real else "cloud_algo.primary_key"
    col_local = db_names["local_algo"]["primary_key"] if use_real else "local_algo.primary_key"
    
    st_demands = df_demand[
        (df_demand[col_dm_st_id] == station_id) & 
        (df_demand[col_prod] == int(product_code)) & 
        (df_demand[col_cloud] == int(cloud_algo_code)) & 
        (df_demand[col_local] == int(local_algo_code))
    ]
    
    if len(st_demands) == 0:
        return
        
    demand_ids = st_demands[col_dm_id].tolist()
    
    df_data = _geedar_db.get_data(demand_id=demand_ids)
    if len(df_data) == 0:
        return
        
    col_date = db_names["acquisition"]["date"] if use_real else "acquisition.date"
    col_time = db_names["acquisition"]["time"] if use_real else "acquisition.time"
    col_var_name = db_names["variable"]["name"] if use_real else "variable.name"
    col_stat_suffix = db_names["stats"]["suffix"] if use_real else "stats.suffix"
    col_result_val = db_names["result"]["value"] if use_real else "result.value"
    
    var_dict = dict()
    
    df_data["img_date"] = pandas.to_datetime(df_data[col_date]).dt.date
    df_data["img_time"] = df_data[col_time]
    df_data["stat"] = df_data[col_stat_suffix]
    
    sng_rows = []
    
    for (d, t, s), group in df_data.groupby(["img_date", "img_time", "stat"]):
        row = {"img_date": d, "img_time": t, "stat": s}
        for _, r in group.iterrows():
            var_name = r[col_var_name]
            val = r[col_result_val]
            
            if pandas.notna(val):
                row[var_name] = float(val)
                
                if var_name not in var_dict:
                    var_dict[var_name] = dict()
                if s not in var_dict[var_name]:
                    var_dict[var_name][s] = {"min": float(val), "max": float(val)}
                else:
                    var_dict[var_name][s]["min"] = min(float(val), var_dict[var_name][s]["min"])
                    var_dict[var_name][s]["max"] = max(float(val), var_dict[var_name][s]["max"])
        sng_rows.append(row)
        
    df_sng = pandas.DataFrame(sng_rows)
    df_lst = pandas.DataFrame(columns=["img_date", "img_time", "stat", "latitude_list", "longitude_list"])
    
    result_dict = {
        "var_dict": var_dict,
        "time_series_df": df_sng,
        "pixels_df": df_lst
    }
    return result_dict

# Auxilliary function for 'get_result_data'.
def get_result_data_from_csv(station_code, product_code, cloud_algo_code, 
        local_algo_code):
    if not st.session_state.import_info:
        print("(!) 'import_info' should not be None.")
        return
    df = pandas.read_csv(st.session_state.uploaded_csv)
    if len(df) == 0:
        print("(!) Empty csv, no data to retrieve.")
        return    
    data_cols = st.session_state.import_info["data_cols"]
    if len(data_cols) == 0:
        print("(!) No data columns in the csv file.")
        return
    coord_cols = [c for c in st.session_state.import_info["coord_cols"] 
        if c.endswith("_list")]
    
    # List possible stat suffixes.
    all_stat_suffixes = []
    for reducer in reducer_catalog.values():
        all_stat_suffixes.extend(reducer.stat_suffix)
    all_stat_suffixes = list(set(all_stat_suffixes))
    
    # Restore lists in the coordinate columns.
    for col in coord_cols:
        df[col] = df[col].apply(
            lambda val: cast_numeric_list(str(val)[1:-1].split(","))
            if str(val).startswith("[") and str(val).endswith("]") else val)
    
    # Identify columns with values as lists and with single (reduced) values.
    # First, the lists imported as strings must be turned into real lists.
    lst_cols = []
    sng_cols = []
    rename_dict = dict()
    col_stat_dict = dict()
    df_stat_suffixes = []
    for col in data_cols:
        col_stat_dict[col] = "none" # default
        rename_dict[col] = col # default
        substrs = col.split("_")
        
        # Cast to list when applicable.
        df[col] = df[col].apply(lambda val: str(val)[1:-1].split(",") 
            if str(val).startswith("[") and str(val).endswith("]") else val)
        
        # Does the column contain lists?
        if any(isinstance(val, list) for val in [*df[col]]):
            lst_cols.append(col)
            col_stat_dict[col] = "list"
            rename_dict[col] = col.replace("_list", "")
        else:
            sng_cols.append(col)        
            stat = "none"
            if len(substrs) > 1:
                if substrs[-1] in all_stat_suffixes:
                    rename_dict[col] = "_".join(substrs[:-1])
                    stat = substrs[-1]
                    col_stat_dict[col] = stat
            df_stat_suffixes.append(stat)
        
    df_stat_suffixes = list(set(df_stat_suffixes))
    
    # Retrieve data with all possible reducers.
    data_rows = []
    for reducer_code, reducer in reducer_catalog.items():
        demand_code_str = ("P" + str(product_code) 
            + "C" + str(cloud_algo_code) + "L" + str(local_algo_code) 
            + "R" + str(reducer_code))        
        data_rows.extend([*df.loc[(df["station_code"] == station_code) 
            & (df["demand_code"] == demand_code_str) 
            & pandas.notna(df["img_date"]) 
            & pandas.notna(df["img_time"])].index])
    
    # The result dataframes: one for lists, the other for single values.
    base_cols = ["img_date", "img_time", "stat"]
    
    df_lst = pandas.DataFrame(columns = base_cols + coord_cols 
        + lst_cols).rename(columns = {k:v for k,v in rename_dict.items() 
        if str(k) in lst_cols})
    df_lst["img_date"] = [None]*len(data_rows)
    df_lst_row = 0
    
    df_sng = pandas.DataFrame(columns = base_cols + sng_cols).astype(
        {c:"object" for c in base_cols} | 
        {c:"Float32" for c in sng_cols}).rename(
        columns = {k:v for k,v in rename_dict.items() 
        if str(k) in sng_cols})
    df_sng["img_date"] = [pandas.NA]*len(data_rows)*len(df_stat_suffixes)    
    df_sng_row = 0
    
    # Dictionary whose keys are the variables in the input data. Each key 
    # holds a subdicts of stats applicable to that variable which, in turn,
    # holds their minimum and maximum values taken from the data.
    var_dict = {key: dict() for key in rename_dict.values()}
    # Fill the values in the result dataframes.
    for data_row in data_rows:
        img_date = datetime.strptime(str(df.loc[data_row, "img_date"]), 
            "%Y-%m-%d").date()
        img_time = df.loc[data_row, "img_time"]
        
        # Coordinates.
        for col in coord_cols:
            df_lst.at[df_lst_row, col] = copy.deepcopy(df.at[data_row, col])
        
        # Results with values formatted as lists.
        df_lst.loc[df_lst_row, "img_date"] = img_date
        df_lst.loc[df_lst_row, "img_time"] = img_time
        for col in lst_cols:
            stat = col_stat_dict[col]
            df_lst.loc[df_lst_row, "stat"] = stat
            renamed_col = rename_dict[col]
            if stat not in var_dict[renamed_col]:
                var_dict[renamed_col][stat] = {"min": 0, "max": 100}
            val = None
            if isinstance(df.loc[data_row, col], list):
                val = cast_numeric_list(df.loc[data_row, col])
                valid_vals = [v for v in val if pandas.notna(v)]
                if len(valid_vals) > 0:
                    var_dict[renamed_col][stat]["min"] = min(valid_vals 
                        + [var_dict[renamed_col][stat]["min"]])
                    var_dict[renamed_col][stat]["max"] = max(valid_vals 
                        + [var_dict[renamed_col][stat]["max"]])
            df_lst.at[df_lst_row, renamed_col] = copy.deepcopy(val)
        df_lst_row += 1
        
        # Results with single numeric values.
        for stat in df_stat_suffixes:
            df_sng.loc[df_sng_row, "img_date"] = img_date
            df_sng.loc[df_sng_row, "img_time"] = img_time
            df_sng.loc[df_sng_row, "stat"] = stat
            for col in sng_cols:
                if stat == col_stat_dict[col]:
                    renamed_col = rename_dict[col]
                    if stat not in var_dict[renamed_col]:
                        var_dict[renamed_col][stat] = {"min": 0, "max": 100}
                    val = df.loc[data_row, col]
                    df_sng.loc[df_sng_row, renamed_col] = val
                    if pandas.notna(val):
                        var_dict[renamed_col][stat]["min"] = min(val, 
                            var_dict[renamed_col][stat]["min"])
                        var_dict[renamed_col][stat]["max"] = max(val, 
                            var_dict[renamed_col][stat]["max"])                        
            df_sng_row += 1
        
    # Remove rows with no data.
    
    cols_to_check = [c for c in df_lst.columns 
        if str(c) not in ["img_date", "img_time", "stat"]]
    df_lst.dropna(axis=0, how="all", subset=cols_to_check, inplace=True)
    df_lst.reset_index(inplace=True, drop=True)
    
    cols_to_check = [c for c in df_sng.columns 
        if str(c) not in ["img_date", "img_time", "stat"]]
    df_sng.dropna(axis=0, how="all", subset=cols_to_check, inplace=True)
    df_sng.reset_index(inplace=True, drop=True)
    
    # Result dict.
    result_dict = {
        "var_dict": var_dict,
        "time_series_df": df_sng,
        "pixels_df": df_lst
    }
    return result_dict
                
# Returns a feature layer with the results for the cloud and the local algo.
@st.cache_data(show_spinner=False)
def create_raster_overlay(result_dict, var_sel, min_val, max_val):
    if not result_dict:
        return  
    px_df = result_dict["pixels_df"]
    px_df_cols = [*px_df.columns]
    if "latitude_list" not in px_df_cols or "longitude_list" not in px_df_cols:
        st.session_state.display_msg = {"text": "No coordinates columns in "
            + "the input data...", "icon": "❌"}
        return
    if var_sel not in px_df_cols:
        st.session_state.display_msg = {"text": "The variable column was not "
            + "found in the input data...", "icon": "❌"}
        return
    
    target_date = st.session_state.target_date
    data_rows = [*px_df.loc[(px_df["img_date"] == target_date) 
        & (px_df["stat"] == "list")].index]
    if len(data_rows) == 0:
        st.session_state.display_msg = {"text": "No data to display...", 
            "icon": "❌"}
        return
    
    lats = np.array([*px_df.at[data_rows[0], "latitude_list"]])
    lons = np.array([*px_df.at[data_rows[0], "longitude_list"]])
    vals = np.array([*px_df.at[data_rows[0], var_sel]])
    min_lat, max_lat = lats.min(), lats.max()
    min_lon, max_lon = lons.min(), lons.max()
    
    # Define the resolution.
    product = st.session_state.active_product
    resolution = product.rough_scale
    
    # Rasterize the scattered points using 2D Histograms (Binning).    
    lat_bins = np.linspace(min_lat, max_lat, resolution + 1)
    lon_bins = np.linspace(min_lon, max_lon, resolution + 1)    
    
    # Sum the values and count the points in each grid cell.
    sum_vals, _, _ = np.histogram2d(lats, lons, bins=[lat_bins, lon_bins], 
        weights=vals)
    counts, _, _ = np.histogram2d(lats, lons, bins=[lat_bins, lon_bins])
    
    # Calculate average value per cell (ignore divide by zero for empty cells)
    with np.errstate(divide="ignore", invalid="ignore"):
        grid_vals = np.true_divide(sum_vals, counts)    

    # NumPy's histogram puts min_lat at index 0. 
    # Images render top-to-bottom, so flip the array so max_lat is at the top.
    grid_vals = np.flipud(grid_vals)
    counts = np.flipud(counts)    

    # Create the RGBA image array (transparent by default)
    image = np.zeros((resolution, resolution, 4), dtype=np.uint8)
    
    # Create a mask to only colorize cells that actually contain data
    valid_mask = counts > 0    
    if np.any(valid_mask):
        # Normalize the valid values to a 0.0 to 1.0 scale.
        v = np.clip((grid_vals[valid_mask] - min_val) / (max_val - min_val), 
            0, 1)

        # Vectorized Green -> Yellow -> Red Color Mapping
        # Green to Yellow phase
        r = np.where(v <= 0.5, v * 2 * 255, 255).astype(np.uint8)
        # Yellow to Red phase
        g = np.where(v > 0.5, (1.0 - v) * 2 * 255, 255).astype(np.uint8)
        b = np.zeros_like(v, dtype=np.uint8)
        a = np.full_like(v, int(255 * 0.8), dtype=np.uint8) # 80% Opacity

        # Inject the mapped colors back into the image array
        image[valid_mask, 0] = r
        image[valid_mask, 1] = g
        image[valid_mask, 2] = b
        image[valid_mask, 3] = a

    # Create the Folium ImageOverlay.
    raster_layer = folium.raster_layers.ImageOverlay(
        image=image, bounds=[[min_lat, min_lon], [max_lat, max_lon]],
        name=f"Raster: {var_sel}", interactive=True, cross_origin=False)
    
    # Add the standard Branca legend to the map object.
    color_scale = cm.LinearColormap(colors=['green', 'yellow', 'red'],
        vmin=min_val, vmax=max_val)
    color_scale.caption = f"Estimated {var_sel}"
    #color_scale.add_to(m)
    
    return {"raster_layer": raster_layer, "color_scale": color_scale}

    