#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#%% Header
"""
Custom classes used by GEEDaR.

This module contains all the classes created to be used in the GEEDaR 
application, including the class GeedarApp, which integrates all the others.
The list of classes coincides with the list in the section "Export" below.
The module also contains some auxilliary functions that are used by one or 
more classes.

"""

__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.0.1"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"

#%% Import

import sys
import os
import math
import statistics
import copy
import json
import zipfile
import pickle
import pandas
import ee
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, text, inspect
from func_timeout import func_timeout, FunctionTimedOut
from fastkml import KML, Placemark, Folder, Document
from fastkml.utils import find_all


#%% Export

__all__ = ["Product", "VirtualStation", "CloudAlgorithm", "LocalAlgorithm", 
    "Demand", "Variable", "Instrument", "GeedarDB", "UserOptions", 
    "GeedarApp"]


#%% Globals

# Max number of simultaneously processed pixels and images:
_MAX_PROC_PIXELS = 10_000_000
_MAX_SIM_IMAGES = 250

# Default value for the radius of the area of interest, in meters.
_AOI_DEFAULT_RADIUS = 100


#%% Auxilliary functions

# Is a path (string) syntactically valid?    
def is_path_valid(path):
    """
    Checks if the path is syntactically valid and if all directories in the 
    path exist.
    
    """
    
    try:
        # Get the directory part of the path
        directory = os.path.dirname(path)
        # Check if the directory part exists
        if directory and not os.path.exists(directory):
            return False
    except OSError:
        return False # Invalid path format
    
    return True

# An R-like 'which' function for Pandas series.
# Credits to Alex Miller <https://alex.miller.im/posts/python-pandas-which-function-indices-similar-to-R/>
def which(self):
    try:
        self = list(iter(self))
    except TypeError as e:
        raise Exception("""'which' method can only be applied to iterables.
        {}""".format(str(e)))
    indices = [i for i, x in enumerate(self) if bool(x) == True]
    return(indices)

# Arranges a text for printing with defined width and indentation.
def text_box(text, first_line_indent=4, other_lines_indent=4, max_width=80):
    if text == "":
        return ""
    if not isinstance(text, str):
        raise TypeError("'text' must be a string.")
    if not isinstance(first_line_indent, int):
        raise TypeError("'first_line_indent' must be an integer.")
    if not isinstance(other_lines_indent, int):
        raise TypeError("'other_lines_indent' must be an integer.")
    if not isinstance(max_width, int):
        raise TypeError("'max_width' must be an integer.")
        
    eff_max_width = max_width - max(first_line_indent, other_lines_indent)
    if eff_max_width < 1:
        raise ValueError("The values of indent and max width resulted in a "
            + " zero-width text box.")
        
    new_text = " "*first_line_indent
    cur_start_pos = 0
    cur_end_pos = len(text)
    i = 0
    while i < len(text):
        blank_pos = text[i:].find(" ")
        if blank_pos < 0:
            next_break_pos = len(text)
        else:
            next_break_pos = blank_pos + i
                
        # Next word fits? Append it and go for the next.
        if next_break_pos - cur_start_pos <= eff_max_width:
            new_text = new_text + text[i:min(len(text), next_break_pos + 1)]
            cur_end_pos = min(len(text), next_break_pos + 1)
            i = next_break_pos + 1
            continue
        
        # If possible, insert a new line at the last valid break point.
        if (cur_end_pos - 1) - cur_start_pos <= eff_max_width:
            new_text = new_text + "\n" + " "*other_lines_indent
            i = cur_end_pos
            cur_start_pos = i            
            cur_end_pos = next_break_pos
            continue
        
        # If not possible, break the word arbitrarily.
        new_text = (new_text + text[i:(cur_start_pos + eff_max_width)]
            + "\n" + " "*other_lines_indent)
        i = cur_start_pos + eff_max_width
        cur_start_pos = i            
        cur_end_pos = next_break_pos
        
    return new_text 

# Validation for constructors: were all required arguments provided?
# Check '_required_args' of the class Product to see the format of the
# parameter 'required_args'.
def _valid_argument_list(args_dict, required_args):
    return all(key in [*args_dict] for key in required_args)

# Validation: checks argument type(s). Returns dict of invalid arguments.
def _invalid_argument_types(args_dict, required_args):
    r = dict()
    for key in args_dict:
        if key not in required_args:
            continue
        if len(required_args[key]["types"]) == 0:
            continue
        vals = args_dict[key]
        data_type = type(vals).__name__
        if data_type not in required_args[key]["types"]:
            r[key] = data_type
        elif isinstance(vals, list):
            expected_types = required_args[key]["types"][-1]
            invalid_types = [type(v).__name__ for v in vals 
                if type(v).__name__ not in expected_types]
            if len(invalid_types) > 0:
                r[key] = invalid_types
    return r

# Validation: checks argument value(s). Returns dict of invalid arguments.
def _invalid_argument_values(args_dict, required_args):
    r = dict()
    for key in args_dict:
        if key not in required_args:
            continue
        if len(required_args[key]["values"]) == 0:
            continue
        vals = args_dict[key]
        if not isinstance(vals, list):
            vals = [vals]
        invalid_vals = [val for val in vals 
            if val not in required_args[key]["values"]]
        if len(invalid_vals) > 0:
            r[key] = invalid_vals
    return r
        
# Validation: apply all the validation functions above.
def _validate_args_dict(args_dict, required_args):
    if not isinstance(args_dict, dict):
        raise TypeError("A dictionary was expected for instantiation (but "
            + "it was provided '" + type(args_dict).__name__ + "').")
    if not _valid_argument_list(args_dict, required_args):
        raise TypeError("Missing keys in the input attribute dictionary: " 
            + str([key for key in required_args 
            if not key in [*args_dict]]))
    
    # Check argument types.
    invalid_types = _invalid_argument_types(args_dict, required_args)
    if len([*invalid_types]) > 0:
        raise TypeError("Wrong types in the input " 
            + "dictionary: " + str(invalid_types))
    
    # Check the value(s) of the arguments.
    invalid_vals = _invalid_argument_values(args_dict, required_args)
    if len([*invalid_vals]) > 0:
        raise TypeError("Wrong values in the input " 
            + "dictionary: " + str(invalid_vals))

# Converts a string to logical, integer, float, datetime or string (removing 
# the quotes) according to its content. When not obvious, keep it as a string.
def autocast_str(strg, decimal_point=".", 
        na=["NA","na","NaN","nan","<NA>"], null=["NULL","Null","null","None"], 
        true=["T","TRUE","True","true"], false=["F","FALSE","False","false"], 
        date_formats=["%Y-%m-%d","%Y/%m/%d"],  
        datetime_formats=["%Y-%m-%d %H:%M:%S","%Y/%m/%d %H:%M:%S", 
        "%Y-%m-%d %H:%M","%Y/%m/%d %H:%M"], 
        time_formats=["%H:%M:%S","%H:%M","%I:%M:%S%p","%I:%M%p"]):
    
    if not isinstance(strg, str):
        raise TypeError("'strg' must be a string.")
    
    # Blank?
    if len(strg.strip()) == 0:
        return strg
    
    # Remove leading and trailing spaces:
    strg = strg.strip()
        
    # Null?
    if len(null) > 0:
        if strg in null:
            return None
    # NA?
    if len(na) > 0:
        if strg in na:
            return math.nan
    # Logical true?
    if len(true) > 0:
        if strg in true:
            return True
    # Logical false?
    if len(false) > 0:
        if strg in false:
            return False
    # Numeric?
    try:
        n = float(strg)
    except:
        pass
    else:
        if strg.find(decimal_point) >= 0:
            return n
        else:
            return int(strg)
    # To try date/time formats below, first remove enclosing quotes.
    date_str = strg
    if date_str[0] == date_str[-1] and date_str[0] in ["'",'"']:
        date_str = date_str[1:-1]
    # Datetime?
    if (len(date_str) > 6 and len(datetime_formats) > 0 and 
            len(date_str.split()) > 1):
        for datetime_format in datetime_formats:
            try:
                dt = datetime.strptime(date_str, datetime_format)
            except:
                pass
            else:
                return dt
    # Date?
    if len(date_str) > 3 and len(date_formats) > 0:
        for date_format in date_formats:
            try:
                d = datetime.strptime(date_str, date_format)
            except:
                pass
            else:
                return d
    # Time? As there's no "only-time" type of data, a datetime will be created
    # with date = 1900-01-01.
    if len(date_str) > 1 and len(time_formats) > 0:
        for time_format in time_formats:
            try:
                t = datetime.strptime(date_str, time_format)
            except:
                pass
            else:
                return t
    # The string seems not to be convertible.
    # If there are enclosing quotes, remove it.
    if strg[0] == strg[-1] and strg[0] in ["'",'"']:
        if len(strg) == 2:
            # Empty string.
            return ""
        elif len(strg) > 2:
            strg = strg[1:-1]
            return 
    # The last option: return the string "as-is".
    return(strg)

# Converts a list-like string to a real list. 
# Ex: '[a,b,c,d,7,8]' -> ['a','b','c','d',7,8] 
def str_to_list(s, opening=["[","(","{"], closing=["]",")","}"], sep=[",",";"], 
        optional_enclosing=False):
    
    if not isinstance(s, str):
        raise TypeError("'s' must be a string.")
    
    if not isinstance(opening, list):
        if isinstance(opening, str):
            opening = [opening]
        else:
            raise TypeError("'opening' must be a string or list of strings.")
    else:
        if not all(isinstance(o, str) for o in opening):
            raise TypeError("'opening' must be a list of strings.")
    
    if not isinstance(closing, list):
        if isinstance(closing, str):
            closing = [closing]
        else:
            raise TypeError("'closing' must be a string or list of strings.")
    else:
        if not all(isinstance(c, str) for c in closing):
            raise TypeError("'closing' must be a list of strings.")
    
    if not isinstance(sep, list):
        if isinstance(sep, str):
            sep = [sep]
        else:
            raise TypeError("'sep' must be a string or list of strings.")
    else:
        if not all(isinstance(e, str) for e in sep):
            raise TypeError("'sep' must be a list of strings.")
    
    if not isinstance(optional_enclosing, bool):
        raise TypeError("'optional_enclosing' must be a boolean.")
    
    if not optional_enclosing and (
            any("".join(o).strip() == "" for o in opening) 
            or any("".join(c).strip() == "" for c in closing)):
        raise ValueError("'optional_enclosing' is False, but a blank " 
            + "string was passed in 'opening' and/or 'closing'.")
    
    if len(opening) != len(closing):
        raise ValueError("'opening' and 'closing' must have the same length.")
    
    # Remove leading and trailing spaces:
    s = s.strip()
    
    if not optional_enclosing: 
        # Enclosing is required...
        if len(s) < 2:
            # ...but the string has length 0 or 1.
            raise ValueError("The string in 's' should have enclosing chars.")
        if s[0] not in opening or s[-1] not in closing:
            # ...but the string was not enclosed.
            raise ValueError("Could not convert 's' to list. " 
                + "Wrong format.")
    
    chrvector = None
    if len(s) == 0:
        # Empty string will become an empty list.
        chrvector = []
    elif len(s) == 1:
        # Not enclosed (impossible).
        chrvector = [s]
    elif s[0] in opening and s[-1] in closing:
        # There is enclosing chars. But do they match?
        opening_ind = opening.index(s[0])
        closing_ind = closing.index(s[-1])
        if opening_ind != closing_ind:
            raise ValueError("Unmatched enclosing chars in 's'.")
        if len(s) == 2:
            # The string was enclosed, but with nothing inside. 
            # It is considered an empty list.
            chrvector = []
        else:
            s = s[1:-1]
    if chrvector is None:
        # There is at least one potential separator. Enlist.
        cur_sep = ""
        chrvector = []
        j = 0
        openers = []
        for i in range(len(s)):
            # List inside list?
            if s[i] in opening:
                opening_ind = opening.index(s[i])
                openers = openers + [opening_ind] #opening[opening_ind]
                #opener_count += 1
            elif s[i] in closing and len(openers) > 0:
                closing_ind = closing.index(s[i])
                #cl_chr = opening[closing_ind]
                if closing_ind == openers[-1]:
                    openers = openers[:-1]
            if s[i] in sep and len(openers) == 0:
                if s[i] != cur_sep and cur_sep != "":
                    raise ValueError("Different separators found in 's'.")
                cur_sep = s[i]
                chrvector = chrvector + [s[j:i]]
                j = i + 1
        if j > i:
            chrvector = chrvector + [""]
        else:
            chrvector = chrvector + [s[j:]]
            
    # Build a list, converting number-like strings to integer or double:
    result_list = []
    for cur_str in chrvector:
        # List inside list?
        enclosed = False
        if cur_str[0] in opening and cur_str[-1] in closing:
            opening_ind = opening.index(cur_str[0])
            closing_ind = closing.index(cur_str[-1])
            if opening_ind == closing_ind:
                enclosed = True
                tmp_list = str_to_list(cur_str, opening = opening, 
                    closing = closing, sep = sep, 
                    optional_enclosing = optional_enclosing)
                result_list = result_list + [tmp_list]
        if not enclosed:
            result_list = result_list + [autocast_str(cur_str)]
          
    return result_list

# Converts a value to a string to be used in a SQL statement.
# Ex: 5 -> "5"; "test" -> "'test'"
def val_to_sql(val):
    val = autocast_str(str(val), true=["True"], false=["False"])
    if val is None:
        val_str = "NULL"
    elif isinstance(val, str):
        val_str = "'" + val.replace("'","''") + "'"
    elif isinstance(val, datetime):
        val_str = "'" + val.strftime("%Y-%m-%d %H:%M:%S") + "'"
    elif isinstance(val, date):
        val_str = "'" + val.strftime("%Y-%m-%d") + "'"
    else:
        try:
            if math.isnan(val):
                val_str = "NULL"
            else:
                val_str = str(float(val))
        except:
            val_str = "'" + str(val) + "'"
    return val_str

# Converts a real list to the equivalent string in SQL.
# Ex: [4, 5, "f", 7.6] -> "(4, 5, 'f', 7.6)"
def list_to_sql(real_list):
    if not isinstance(real_list, list):
        raise TypeError("'real_list' must be a list.")
    
    sql_list = "("
    for item in real_list:
        item_str = val_to_sql(item)
        # Add the new item and the comma.
        sql_list = sql_list + item_str + ", "
    # Remove the last comma and close the brackets.
    sql_list = sql_list[0:-2] + ")"
    
    return sql_list

# Check and cast elements in a list as float.
def cast_numeric_list(lst):
    if not isinstance(lst, list):
        raise TypeError("'lst' must be a list.")
    lst = copy.deepcopy(lst)
    for i in range(len(lst)):
        if str(lst[i]).lower().replace(" ","") in ["", "none", "na", "nan", 
                "nat", "<na>"]:
            lst[i] = math.nan
            continue
        try:
            lst[i] = float(lst[i])
        except:
            return None
    return lst            

# Unfold lists inside a dataframe, turning each list element into a row.
# Returns the unfolded dataframe with an attribute added ('orig_list_len') 
# containing a series with the number of rows unfolded at each row.
def unfold_df_lists(df):
    if not isinstance(df, pandas.DataFrame):
        raise TypeError("'df' must be a dataframe.")
    
    if len(df) == 0:
        print("Empty dataframe. No lists to be unfolded.")
        return df
    
    def max_len(ax1):
        max_vals = ax1.apply(
            lambda ax2: len(ax2) if isinstance(ax2, list) else -1)
        return max_vals
    
    list_lens = df.apply(max_len, axis = 1)
    row_largest = list_lens.apply(max, axis = 1)
    row_largest.name = "max_list_len"
    
    df_cols = [*df.columns]
    new_dict = dict.fromkeys(df_cols)
    for k in new_dict:
        new_dict[k] = []
    new_index = []
    for row_n in range(len(row_largest)):
        row_max = row_largest.iloc[row_n]
        if row_max == -1:
            new_index.append(copy.deepcopy(row_largest.index[row_n]))
            for k in new_dict:
                new_dict[k].append(copy.deepcopy(df[k].iloc[row_n]))
            continue
        n_rows = max(row_max, 1)
        for col in df.iloc[[row_n]]:
            cell = df[col].iloc[row_n]
            if not isinstance(cell, list):
                vals = [cell]*n_rows
            else:
                vals = [math.nan]*n_rows
                for i in range(len(cell)):
                    vals[i] = copy.deepcopy(cell[i])
            new_dict[col].extend(vals)
        new_index.extend([copy.deepcopy(row_largest.index[row_n])]*n_rows)
    
    new_df = pandas.DataFrame(new_dict, index = new_index)
    new_df.attrs["max_row_len"] = row_largest
    new_df.attrs["orig_list_len"] = list_lens
    
    return new_df

# Restore the dataframes whose lists were unfolded by 'unfold_df_lists'.
def restore_df_lists(df):
    if not isinstance(df, pandas.DataFrame):
        raise TypeError("'df' must be a dataframe.")
    if len(df) == 0:
        return df
    df = df.copy()
    df_cols = list(df.columns)
    
    if "orig_list_len" not in df.attrs:
        raise ValueError("The attribute 'orig_list_len' is missing in 'df'.")
    if "max_row_len" not in df.attrs:
        raise ValueError("The attribute 'max_row_len' is missing in 'df'.")
        
    list_lens = df.attrs["orig_list_len"]
    max_row_len = df.attrs["max_row_len"]
    row_count = 0
    for n in max_row_len:
        if n < 1:
            row_count += 1
        else:
            row_count += n
    if row_count != df.shape[0]:
        raise ValueError("The content of 'max_row_len' is not compatible "
            + "with 'df' shape: different sun of rows.")    
    
    orig_cols = list(list_lens.columns)
    rest_dict = dict()
    for col in df_cols:
        rest_dict[col] = []
        df_row = 0
        for row_n in range(len(max_row_len)):
            row_max = int(max_row_len.iloc[row_n])
            if col in orig_cols:
                list_len = list_lens[col].iloc[row_n]
            else:
                list_len = row_max
            if list_len == -1:
                cell = df[col].iloc[df_row]
            elif list_len == 0:
                cell = []
            elif list_len == 1:
                cell = [df[col].iloc[df_row]]
            else:
                cell = list(df[col].iloc[df_row:(df_row + list_len)])
            rest_dict[col].append(cell)
            df_row = df_row + max(1, row_max)
    
    orig_df = pandas.DataFrame(rest_dict)
    orig_df.index = list_lens.index
    return orig_df

# Calculates the median or mean of a numeric list. Returns None (default) 
# for empty or invalid lists.
def reduce_list(lst, reducer="median", na=None):
    vals = [v for v in lst if pandas.notna(v)]
    if len(vals) == 0:
        return na
    if reducer == "mean":
        return statistics.mean(vals)
    else:
        return statistics.median(vals)

# Extracts the geometry(ies) from a kml file or from a string.
def extract_from_kml(file, what="geojson", aggregate=False):
    """
    Extracts features from a KML or KMZ file and groups them by geometry type,
    ensuring all coordinates are strictly 2D to avoid Earth Engine errors.
    
    Args:
        file: String path to the file or raw KML bytes.
        what: Return type ("geojson", "placemark", "ee_geometry", 
            "ee_collection")
        aggregate: If True, aggregates geometries by their parent KML Folder.
            (Polygons -> MultiPolygon, etc.). Ignored if what="placemark".
                    
    Returns:
        A dictionary where keys are geometry types (e.g., 'Polygon', 
        'MultiPoint') and values are lists of the requested objects (or 
        ee.FeatureCollections).
    """

    # Helper function to recursively strip Z-coordinates
    def remove_z(coords):
        if not coords:
            return coords
        # If the first element is a number, we are at the coordinate pair level
        if isinstance(coords[0], (int, float)):
            return list(coords[:2])
        # Otherwise, dig deeper into the nested lists/tuples
        return [remove_z(c) for c in coords]

    if not isinstance(file, (str, bytes)):
        raise TypeError("'file' must be str/bytes with a path or raw data.")
    
    # Check if the string is a file path or raw XML data.
    is_file = False
    if isinstance(file, str):
        try:
            is_file = os.path.isfile(file)
        except (ValueError, OSError):
            pass # The string is likely raw KML data.

    if is_file:
        file_path = file
        if file_path.lower().endswith(".kmz"):        
            with zipfile.ZipFile(file_path, 'r') as kmz:
                kml_file_name = next((name for name in kmz.namelist() 
                    if name.endswith('.kml')), None)
                if not kml_file_name:
                    raise ValueError("No kml found inside the KMZ.")  
                kml_data = kmz.read(kml_file_name)
        else:
            with open(file_path, 'rb') as f:
                kml_data = f.read()   
    else:
        kml_data = file.encode('utf-8') if isinstance(file, str) else file

    k = KML.from_string(kml_data)
    results_dict = {}

    # Handle standard flat extraction.
    if what == "placemark" or not aggregate:
        placemarks = [
            p for p in find_all(k, of_type=Placemark) 
            if getattr(p, 'geometry', None)
        ]
        
        for p in placemarks:
            geom_type = p.geometry.geom_type 
            
            # Create a 2D clean version of the geo_interface
            gi = dict(p.geometry.__geo_interface__)
            gi['coordinates'] = remove_z(gi['coordinates'])
            
            if geom_type not in results_dict:
                results_dict[geom_type] = []
                
            if what == "placemark":
                results_dict[geom_type].append(p)
            elif what == "ee_geometry":
                results_dict[geom_type].append(ee.Geometry(gi))
            elif what == "ee_collection":
                # Temporarily store as ee.Feature; wrap the list in a 
                # collection at the end.
                results_dict[geom_type].append(
                    ee.Feature(
                        ee.Geometry(gi), 
                        {'name': getattr(p, 'name', 'Unnamed')}
                    )
                )
            else: # geojson
                results_dict[geom_type].append(gi)

    # Handle Folder Aggregation.
    else:
        def get_folder_placemarks(container, current_folder_name="Root"):
            features = getattr(container, 'features', [])
            if callable(features): 
                features = features()
                
            direct_placemarks = []
            if features:
                for feature in features:
                    if isinstance(feature, Placemark):
                        if getattr(feature, 'geometry', None):
                            direct_placemarks.append(feature)
                    elif isinstance(feature, (Folder, Document)):
                        yield from get_folder_placemarks(
                            feature, getattr(feature, 'name', 'Unnamed Folder')
                        )
            
            if direct_placemarks:
                yield current_folder_name, direct_placemarks

        aggregated_data = []
        
        for folder_name, pm_list in get_folder_placemarks(k):
            polys, lines, points = [], [], []
            
            for p in pm_list:
                gi = p.geometry.__geo_interface__
                gtype = gi['type']
                
                # Strip Z coordinates before aggregating
                coords = remove_z(gi['coordinates'])
                
                if gtype == 'Polygon': polys.append(coords)
                elif gtype == 'MultiPolygon': polys.extend(coords)
                
                elif gtype == 'LineString': lines.append(coords)
                elif gtype == 'MultiLineString': lines.extend(coords)
                
                elif gtype == 'Point': points.append(coords)
                elif gtype == 'MultiPoint': points.extend(coords)
                
            if polys:
                aggregated_data.append(({"type": "MultiPolygon", 
                    "coordinates": polys}, f"{folder_name} (Polygons)"))
            if lines:
                aggregated_data.append(({"type": "MultiLineString", 
                    "coordinates": lines}, f"{folder_name} (Lines)"))
            if points:
                aggregated_data.append(({"type": "MultiPoint", 
                    "coordinates": points}, f"{folder_name} (Points)"))

        # Sort aggregated data into the results dictionary
        for geo, name in aggregated_data:
            geom_type = geo["type"]
            
            if geom_type not in results_dict:
                results_dict[geom_type] = []
                
            if what == "ee_geometry":
                results_dict[geom_type].append(ee.Geometry(geo))
            elif what == "ee_collection":
                results_dict[geom_type].append(ee.Feature(ee.Geometry(geo), 
                    {'name': name}))
            else: # geojson
                results_dict[geom_type].append(geo)

    # 5. Final Formatting for Earth Engine Feature Collections
    if what == "ee_collection":
        for key in results_dict:
            results_dict[key] = ee.FeatureCollection(results_dict[key])

    return results_dict


#%% Instrument class

class Instrument:
    """
    An instrument object holds information on an orbital remote sensor. This 
    object is used as an input parameter when creating a Product object.

    Instantiation
    -------------
    
    To instatiate an Instrument object, you must provide:
        
        inst_code: the number which will identify the instrument (int).
        name: name or short identification (ex: 'MSI') (str).
        mission: name or short identification of the satellite or  
            program (str).
        revisit: mean interval, in days, between data acquisitions 
            (int or float).
        description: longer identification of the instrument (ex: 
            'Multispectral Imager (MSI), onboard of the satellites of 
            Sentinel-2 mission') (str). Defaults to the same value of 'name'.
        label: the way an instrument will be displayed on application 
            messages, graphical interfaces etc. (ex: 'MSI/Sentinel-2') (str). 
            Defaults to the same value of 'name'.
    
    Attributes
    ----------
        inst_code
        name
        mission
        revisit
        description
        label
    
    Methods
    -------
        (none)
       
    """
    
    def __init__(self, inst_code, name, mission, revisit, 
            description=None, label=None):
        if type(inst_code) is not int:
            raise TypeError("'inst_code' must be an int.")
        if type(name) is not str:
            raise TypeError("'name' must be a str.")
        if type(mission) is not str:
            raise TypeError("'mission' must be a str.")
        if type(revisit) not in [int, float]:
            raise TypeError("'revisit' must be numeric.")
        if description is None:
            description = name
        if type(description ) is not str:
            raise TypeError("'description' must be a str.")
        if label is None:
            label = name
        if type(label) is not str:
            raise TypeError("'label' must be a str.")
        
        self.inst_code = inst_code
        self.name = name
        self.mission = mission
        self.revisit = revisit
        self.description = description
        self.label = label


#%% Variable class

class Variable:
    """
    A variable object holds information on a variable related to a local
    algorithm. It is used to build a variable catalog which will be loaded by
    GeedarApp and then saved into the target database (only when GEEDaR is 
    running in database mode). It is important to note that variables 
    resulting from local algorithms are automatically saved in the database,
    even if there is no corresponding Variable object in the catalog. The 
    advantage of using a catalog of variable objects, however, is that the 
    variables are saved in the database with complete information instead of 
    only the column names resulted from the local algorithm.
    
    Instantiation
    -------------
    
    To instatiate a Variable object, you must provide:
        
        var_code: the number which will identify the variable (int). It is not 
            the number of the record id in the database, but a number for 
            allocation in the variable catalog used by GeedarApp.
        name: the short (internal) identification corresponding to a column 
            name in the result data frame of a local algorithm (excluded the 
            suffix for the stats; ex: 'TSS' from 'TSS_median') (str).
        unit: the abbreviation of the unit (ex: 'mg/L') (str).
        description: longer identification (ex: 'Total Suspended Solids (TSS), 
            in milligrams per liter (mg/L)') (str).
        label: the way a variable will be displayed on application 
            messages, graphical interfaces etc. (ex: 'TSS (mg/L)') (str). 
    
    Attributes
    ----------
        var_code
        name
        unit
        description
        label
    
    Methods
    -------
        (none)
        
    """

    def __init__(self, var_code, name, unit=None, description=None, label=None):
        if type(var_code) is not int:
            raise TypeError("'var_code' must be an int.")
        if type(name) is not str:
            raise TypeError("'name' must be a str.")
        if unit is None:
            unit = ""
        if type(unit) is not str:
            raise TypeError("'unit' must be a str.")
        if description is None:
            description = name
        if type(description ) is not str:
            raise TypeError("'description' must be a str.")
        if label is None:
            if len(unit) == 0:
                label = name + " (" + unit + ")"
            else:
                label = name
        if type(label) is not str:
            raise TypeError("'label' must be a str.")

        self.var_code = var_code
        self.name = name
        self.unit = unit
        self.description = description
        self.label = label        


#%% Product class

class Product:
    """
    A wrapper for a specific image collection (or combination of collections)
    of GEE with added methods and attributes used by GEEDaR. Each Product
    must have a unique id (code).
    
    Instantiation
    -------------
    
    For instantiation, it must be passed a dictionary containing:
    
        "product_code": the product unique identifier (int).
        "product_name": a unique and short name to identify the product (str).
        "description": a text describing the product (str).
        "instrument": an oject of the class Instrument.
        "collection": an Earth Engine ImageCollection.
        "start_date": the date of the earliest image in the collection (str in 
            the format 'yyyy-mm-dd' or datetime.date).
        "fixed_time": a default time to be used as the image time (str in the 
            format 'hh:mm' or None). Necessary for image collections where the 
            images have no useful value for the time of acquisition (ex: Modis 
            collections).
        "scale_ref_band": the band used as the default spatial scale for the 
            processings with this product (str).
        "rough_scale": an approximate value of spatial scale for the product, 
            such as the horizontal resolution at nadir (int).
        "need_to_mosaic": indicates if more than one image may be available 
            for a given date and area of interest (bool).
        "band_list": the list of bands of the EE product (list of str).
        "quality_layer_names": the bands containing data for qualification of 
            the pixels (list of str).
        "quality_layer_inds": the indices of such bands (relative to the 
            attribute 'band_list') defining how to iterate trough the quality 
            layers in the pixel masking method applied to the product (list of 
            int).
        "quality_layer_start_bits": a list of starting positions of the bits 
            useful for pixel qualification in the quality layers (list of int).
        "quality_layer_end_bits": a list of ending positions of the bits useful 
            for pixel qualification in the quality layers (list of int).
        "test_expression": the numerical or logical expression applied to the 
            quality layers after masking the bits of no interest (list of str).
        "scaling_factor": a list with the coefficients used for rescaling the 
            pixel values in each band. It will be an empty list when no 
            rescaling is applicable (list of int or float).
        "offset": the offset applied to pixel values in the "data bands" (list 
            of int or float).
        "data_band_inds": the indices of the "data_bands" (relative to the
            attribute 'band_list') (list of int).
        "common_bands": a dictionary with the common names of bands (ex: blue, 
            green, red...) used across products and their indices relative to 
            'band_list' (a value of -1 is used for absent common bands) (dict).
        "vis_params": a dictionary with visualization parameters for GEE. It 
            may be empty, but must be a dictionary (dict).
    
    An example:
    {
        "product_code": 102,
        "product_name": "MYD09GA",
        "instrument": INSTRUMENT_CATALOG[2], # Modis/Aqua
        "description": "Daily MODIS/Aqua 500-m images, bands 1-7, 
            collection 6.1",
        "collection": ee.ImageCollection("MODIS/061/MYD09GA"),
        "start_date": "2002-07-04",
        "fixed_time": "13:30",
        "scale_ref_band": "sur_refl_b01",
        "rough_scale": 500,
        "need_to_mosaic": False,
        "band_list": ["sur_refl_b01", "sur_refl_b02", "sur_refl_b03", 
            "sur_refl_b04", "sur_refl_b05", "sur_refl_b06", "sur_refl_b07", 
            "QC_500m", "state_1km", "SensorZenith", "SensorAzimuth", 
            "SolarZenith", "SolarAzimuth"],
        "quality_layer_names": ["state_1km"],
        "quality_layer_inds": [0,0,0],
        "quality_layer_start_bits": [0, 6, 8],
        "quality_layer_end_bits": [2, 7, 10],
        "test_expression": ["b(0) == 0", "b(0) < 2", "b(0) == 0"],
        "scaling_factor": [],
        "offset": [],
        "data_band_inds": [*range(7)],
        "common_bands": {"blue": 2, "green": 3, "red": 0, "NIR": 1, "SWIR": 5, 
            "wl400": -1, "wl440": -1, "wl490": 2, "wl620": -1, "wl665": -1, 
            "wl675": -1, "wl680": -1, "wl705": -1, "wl740": -1, "wl780": -1, 
            "wl800": 1, "wl900": -1, "wl1200": 4, "wl1500": 5, "wl2000": 6, 
            "wl10500": -1, "wl11500": -1},
        "vis_params": {"bands": ["sur_refl_b01","sur_refl_b04","sur_refl_b03"], 
            "min": 0, "max": 2000}
    }
    
    Attributes
    ----------
        
    These ones originate from the arguments for instantiation:
        
        product_code: the product unique identifier.
        product_name: a unique and short name to identify the product.
        description: a text describing the product.
        instrument: an oject of the class Instrument.
        collection: an Earth Engine object of ImageCollection.
        start_date: the date of the earliest image in the collection 
            (datetime.date).
        fixed_time: a default time to be used as the image time. Necessary for
            EE collections where the images have no useful value for the time 
            of acquisition (ex: Modis collections).
        scale_ref_band: the band used as the default spatial scale for the 
            processings with this product.
        rough_scale: an approximate value of spatial scale for the product, 
            such as the horizontal resolution at nadir.
        need_to_mosaic: indicates if more than one image may be available 
            for the same date and area of interest.
        band_list: the list of bands of the EE product.
        quality_layer_names: the bands containing data for qualification of 
            the pixels.
        quality_layer_inds: the indices of such bands (relative to the 
            attribute 'band_list') defining how to iterate trough the quality 
            layers in the pixel masking method applied to the product.
        quality_layer_start_bits: a list of starting positions of the bits 
            useful for pixel qualification in the quality layers.
        quality_layer_end_bits: a list of ending positions of the bits useful 
            for pixel qualification in the quality layers.
        test_expression: the numerical or logical expression applied to the 
            quality layers after masking the bits of no interest.
        scaling_factor: a list with the coefficients used for rescaling the 
            pixel values in each band. It will be an empty list when no 
            rescaling is applicable.
        offset: the offset applied to pixel values in the "data bands".
        data_band_inds: the indices of the "data_bands" (relative to the
            attribute 'band_list').
        common_bands: a dictionary with the common names of bands (ex: blue, 
            green, red...) used across products and their indices relative to 
            'band_list' (a value of -1 is used for absent common bands).
        vis_params: a dictionary with visualization parameters for GEE.

    These ones are added in instantiation:
        
        end_date: the end of the period of interest used to filter the 
            collection with the method 'optimize_collection' (None at 
            instantiation; datetime.date after the 'optimize_collection').
        date_list: the list of dates used to filter the images in the 
            collection through the method 'optimize_collection' (an empty list 
            at instantiation; a list f date strings after executing 
            'optimize_collection').
        available_dates: the list of dates available after filtering the image 
            collection with the method 'optimize_collection' (an empty list 
            at instantiation; a list of date + time strings in the format 
            'yyyy-mm-dd hh:mm' after executing 'optimize_collection').
        original_collection: the full, non-optimized image collection.
    
    Methods
    -------
    
        reset: resets the Product object to its original attribute values.
        new: returns a new Product object from the original constructor 
            arguments.
        get_data_bands: returns a dictionary with the names and indices of the 
            bands with data to be processed, such as the spectral bands. Bands 
            are included both with their original names and with 'common names' 
            (blue, green etc.).
        optimize_collection: optimizes this object's image collection by 
            filtering the images to the area and period of interest, as well 
            as applying necessary rescaling factors, mosaicking and clipping, 
            if applicable.
        mask_bad_pixels: masks the bad pixels in each image of this object's
            collection (those affected by clouds, for example) using the 
            standard pixel quality layers of the images.
        apply_cloud_algo: apply the algorithm contained by a CloudAlgo object 
            to this object's collection.

    """
    
    # Required constructor arguments and their accepted types.
    _required_args = {
        "product_code": {"types": ["int"], "values": []},
        "product_name": {"types": ["str"], "values": []},
        "description": {"types": ["str"], "values": []},
        "instrument": {"types": ["Instrument"], "values": []},
        "collection": {"types": ["ImageCollection"], "values": []},
        "start_date": {"types": ["str", "date"], "values": []},
        "fixed_time": {"types": ["str", "NoneType"], "values": []},
        "scale_ref_band": {"types": ["str"], "values": []},
        "rough_scale": {"types": ["int","float"], "values": []},
        "need_to_mosaic": {"types": ["bool"], "values": []},
        "band_list": {"types": ["list", ["str"]], "values": []},
        "quality_layer_names": {"types": ["list", ["str", "empty"]], 
            "values": []},
        "quality_layer_inds": {"types": ["list", ["int", "empty"]], 
            "values": []},
        "quality_layer_start_bits": {"types": ["list", ["int", "empty"]], 
            "values": []},
        "quality_layer_end_bits": {"types": ["list", ["int", "empty"]], 
            "values": []},
        "test_expression": {"types": ["list", ["str", "empty"]], 
            "values": []},
        "scaling_factor": {"types": ["list", ["int", "float", "empty"]], 
            "values": []},
        "offset": {"types": ["list", ["int", "float", "empty"]], "values": []},
        "data_band_inds": {"types": ["list", ["int", "empty"]], "values": []},
        "common_bands": {"types": ["dict"], "values": []},
        "vis_params": {"types": ["dict"], "values": []}
    }
    
    # Common band names for universal use (across products).
    # The same image band may be indexed in more than one of these common band 
    # keys (ex: in 'blue' and in 'wl490').
    # 'wl' stands for wavelength.
    _common_band_list = ["blue", "green", "red", "NIR", "SWIR", "wl400", 
        "wl440", "wl490", "wl620", "wl665", "wl675", "wl680", "wl705", "wl740", 
        "wl780", "wl800", "wl900", "wl1200", "wl1500", "wl2000", "wl10500", 
        "wl11500"]
    
    # Constructor. Insructions on instatiation are in the class docstring.
    def __init__(self, args_dict):
        
        # Store arguments to allow for recreating the product (method 'new').
        self._args_dict = args_dict.copy()
        
        # Validate the dictionary of arguments.
        _validate_args_dict(args_dict, self._required_args)
        
        # Check the common_bands dictionary.
        if not Product._validate_common_bands(args_dict["common_bands"]):
            raise TypeError("Wrong band list in the 'common_bands' dictionary " 
                + "included in the input dictionary: " 
                + str(args_dict["common_bands"]) + ".")

        # Store the unchanged image collection.
        self.original_collection = args_dict["collection"]        
        
        # Convert attributes with flexibe input format to a single standard 
        # format.
        
        # Convert date from string to datetime.date.
        if isinstance(args_dict["start_date"], str):
            try:
                args_dict["start_date"] = datetime.strptime(
                    args_dict["start_date"], "%Y-%m-%d").date()
            except:
                raise TypeError("Could not interpret the string passed in " 
                    + "'start_date': '" + args_dict["start_date"] 
                    + "'. Required format: 'yyyy-mm-dd'.")
                    
        # Set the attributes from the input dictionary.
        for key, value in args_dict.items():
            # Only set an attribute if it is a required one.
            if key in self._required_args:
                setattr(self, key, value)
        # Only 'start_date' was in the constructor arguments.
        self.end_date = None
        self.date_list = []
        
        # The available dates will only be filled with the method 
        # 'optimize_collection', which will filter the image collection by 
        # the location and the period of interest.
        self.available_dates = []
        # Flag for avoiding double application of 'optimize_collection':
        self._optimized = False
        
        # Store the attribute values to allow for resetting the product.
        self._backup = self.__dict__.copy()
    
    # Validation: 'common_bands' passed in the input dictionary has all 
    # required bands? [True, False]
    @staticmethod
    def _validate_common_bands(common_bands_dict):
        return all(key in [*common_bands_dict]
            for key in Product._common_band_list)        
    
    def reset(self):
        """
        Resets the Product object to its original attribute values.
        
        """
        for key, value in self._backup.items():
            setattr(self, key, value)
        
    def new(self):
        """
        Returns a new Product object from the original constructor arguments.
        
        """
        return Product(self._args_dict)

    # Returns a dictionary with the band names corresponding to the common 
    # data bands, such as those corresponding to spectral regions (blue, 
    # green, red, ...).
    def get_data_bands(self):
        """
        Returns a dictionary with the names and indices of the bands with data 
        to be processed, such as the spectral bands. Bands are included both 
        with their original names and with 'common names' (blue, green etc.).

        """
        
        common_bands = self.common_bands
        band_list = self.band_list
        data_band_inds = self.data_band_inds
        
        common_bands_dict = {k: band_list[v] for k, v in common_bands.items() 
            if v >= 0}
        data_bands_list = [band_list[v] for v in data_band_inds]
        data_bands_dict = {k: k for k in data_bands_list}
        return {**common_bands_dict, **data_bands_dict}
    
    # Optimizes the product collection by filtering the images to the area and
    # period of interest, as well as applying necessary rescaling factors,
    # mosaicking and clipping, if applicable.
    def optimize_collection(self, virtual_station, start_date=None, 
            end_date=None, date_list=None, clip=False):
        """
        Optimizes the product collection by filtering the images to the area
        and period of interest, as well as applying necessary rescaling 
        factors, mosaicking and clipping, if applicable.
        
        Returns nothing.

        Parameters
        ----------
        
            virtual_station: VirtualStation object.
            start_date: datetime.date or string in the format "yyyy-mm-dd" 
                (optional).
            end_date: datetime.date or string in the format "yyyy-mm-dd" 
                (optional).
            date_list : list with dates (str or datetime.date) (optional).
            clip : clip each image to the area of interest? (bool, optional)

        """
        
        # If product was already filtered, it must be reset before new 
        # filtering. For example, using a different area of interest in the
        # second attempt would result in an empty collection.
        if self._optimized:
            self.reset()
        
        # Auxilliary function for setting image properties.
        def set_prop(image):            
            image = ee.Image(image)
            img_date = image.date()
            return ee.Image(image.set(
                "img_date", img_date.format("YYYY-MM-dd"), 
                "img_time", img_date.format("HH:mm"),
                "img_datetime", img_date.format("YYYY-MM-dd HH:mm")))
        
        # Auxilliary function for image mosaicking.
        def mosaic_by_date(dt_str, coll):
            date_str = ee.String(dt_str)
            date = ee.Date.parse("YYYY-MM-dd HH:mm", date_str)
            date_filter = ee.Filter.date(date, date.advance(1, "day"))                
            local_coll = coll.filter(date_filter)
            first_img = local_coll.first()
            props = first_img.toDictionary(
                first_img.propertyNames()).remove(["system:footprint"], True)
            proj = first_img.select(product.scale_ref_band).projection()
            band_names = first_img.bandNames()
            mosaic = ee.Image(local_coll.reduce(ee.Reducer.median()).set(
                props)).setDefaultProjection(proj).rename(band_names)
            return ee.Image(mosaic)
        
        # Auxilliary function to rescale the spectral bands.
        def rescale_spectral_bands(image):
            final_image = image.multiply(product.scaling_factor).add(
                product.offset).copyProperties(image)
            return final_image
        
        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be a VirtualStation "
                + "object.")
        aoi = virtual_station.aoi
        product = self
        
        # 'clip' parameter must be boolean.
        if not clip in [False,True,0,1]:
            raise TypeError("'clip' must be boolean (False or True).")
        clip = bool(clip)
        
        # Check start date.
        if start_date is None:
            start_date = product.start_date
        if type(start_date) is str:
            try:
                start_date = datetime.strptime(start_date, 
                    "%Y-%m-%d").date()
            except:
                raise ValueError("'start_date' must have the format " 
                    + "yyyy-mm-dd. Ex: '2015-07-22'.")
        if type(start_date) is not date:
            raise TypeError("'start_date' must be of type datetime.date.")
        
        # Check end date.
        if end_date is None:
            end_date = datetime.today().date()
        if type(end_date) is str:
            try:
                end_date = datetime.strptime(end_date, 
                    "%Y-%m-%d").date()
            except:
                raise ValueError("'end_date' must have the format " 
                    + "yyyy-mm-dd. Ex: '2025-02-18'.")
        if type(end_date) is not date:
            raise TypeError("'end_date' must be of type datetime.date.")
        # Advance one day of end date because it is not inclusive.
        end_date = end_date + timedelta(days=1)
        
        # Check date list.
        if date_list is None:
            date_list = []
        if type(date_list) is not list:
            raise TypeError("'date_list' should be a list.")
        for i in range(len(date_list)):
            if type(date_list[i]) is datetime.date:
                date_list[i] = date_list[i].strftime("%Y-%m-%d")
            elif type(date_list[i]) is str:
                try:
                    date_list[i] = datetime.strptime(date_list[i], 
                    "%Y-%m-%d").date().strftime("%Y-%m-%d")
                except:
                    raise ValueError("Wrong date format in one or more " 
                        + "positions of 'date_list'. The string must have " 
                        + "the format yyyy-mm-dd.")
            else:
                raise TypeError("'date_list' must contain dates of type " 
                    + "str (format yyyy-mm-dd) or datetime.date.")
        # Update the product attribute.
        self.date_list = date_list
        
        # The product code.
        product_code = product.product_code
        
        # Filter by area of interest and by dates/period of interest and 
        # insert product and date and time str tags.
        image_collection = ee.ImageCollection(
            product.collection.filterBounds(aoi).filterDate(
            start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
            ).map(set_prop))
        # If time info is missing in the product, use the pre-defined time.
        if product.fixed_time is not None:
            if len(product.fixed_time) > 0:
                try:
                    fixed_time = datetime.strptime(product.fixed_time,
                        "%H:%M").strftime("%H:%M")
                except:
                    raise ValueError("Unrecognized time format in the "
                        + "attribute 'fixed_time' of the product "
                        + str(product_code) + ".")
                #fixed_datetime = (start_date.strftime("%Y-%m-%d") + " " 
                #    + fixed_time)
                image_collection = ee.ImageCollection(image_collection.map(
                    lambda image: image.set("img_time", fixed_time, 
                    "img_datetime", ee.String(image.get("img_date")).cat(
                    " " + fixed_time))))           
        # If a list of dates was provided, apply one more filter.
        if(len(date_list) > 0):
            image_collection = ee.ImageCollection(image_collection.filter(
                ee.Filter.inList("img_date", date_list)))
        
        # Mosaic neighbor/overlapping images.
        if product.need_to_mosaic:
            img_dates = ee.List(
                image_collection.aggregate_array("img_datetime"))
            distinct_dates = ee.List(img_dates.distinct())
            mosaic_collection = ee.ImageCollection(
                distinct_dates.map(
                lambda d: mosaic_by_date(d, image_collection)))            
            image_collection = ee.ImageCollection(ee.Algorithms.If(
                img_dates.length().gt(distinct_dates.length()), 
                mosaic_collection, image_collection))
            
        # Clip the images?
        if clip:
            image_collection = image_collection.map(
                lambda image: ee.Image(image).clip(aoi))
        
        # Rescale spectral bands.
        if product.scaling_factor and product.offset:
            image_collection = image_collection.map(rescale_spectral_bands)
        
        # Save the list of available dates in the collection.
        available_dates = image_collection.aggregate_array(
            "img_datetime").getInfo()
        available_dates.sort()
        self.available_dates = available_dates    

        # Update start and end dates accordingly to the available dates.
        if len(available_dates) > 0:
            start_date = datetime.strptime(available_dates[0], 
                "%Y-%m-%d %H:%M").date()
            end_date = datetime.strptime(available_dates[-1], 
                "%Y-%m-%d %H:%M").date()
        self.start_date = start_date
        self.end_date = end_date        
        
        # Save the ee.ImageCollection object and set flag.
        self.collection = image_collection        
        self._optimized = True
    
    # Masks "bad" pixels accordingly to the product attributes 
    # 'quality_layer_names', 'quality_layer_inds', 'quality_layer_start_bits'
    # and 'quality_layer_end_bits'
    def mask_bad_pixels(self, add_band=False):
        """
        Masks the bad pixels in each image of the product collection (ex: 
        those affected by clouds) using the standard pixel quality layers of 
        the images.
        
        Returns nothing.
        
        
        Parameters
        ----------
        
            add_band: the mask applied should be added as a new band to the 
                image? [True|False]
                
        """
        product = self
        image_collection = product.collection
        
        start_bits = product.quality_layer_start_bits
        end_bits = product.quality_layer_end_bits
        layer_names = product.quality_layer_names
        layer_inds = product.quality_layer_inds
        test_expression = product.test_expression
        if not all([len(start_bits) == len(end_bits), 
                   len(start_bits) == len(layer_names), 
                   len(start_bits) == len(layer_inds),
                   len(start_bits) == len(test_expression)]):
            raise ValueError("All the following attributes should have the " 
                + "same length, but did not: quality_layer_start_bits; "
                + "quality_layer_end_bits; quality_layer_names; "
                + "quality_layer_inds; test_expression")
        
        # If the parameters are empty, do nothing and return.
        if(len(start_bits) == 0): return
        
        mask_vals = []
        for i in range(len(start_bits)):
            bit_to_int = 0
            for j in range(start_bits[i], end_bits[i] + 1):
                bit_to_int = bit_to_int + int(math.pow(2, j))
            mask_vals.append(bit_to_int)
        
        def masker(image):
          mask = ee.Image(1)
          for i in range(len(mask_vals)):
            mask = mask.And(image.select(
                layer_names[layer_inds[i]]).int().bitwiseAnd(
                mask_vals[i]).rightShift(start_bits[i]).expression(
                test_expression[i]));
          if add_band:
            image = image.addBands(mask.rename("qa_mask"))
          return image.updateMask(mask)
          
        image_collection = image_collection.map(masker)
        self.collection = image_collection
    
    def apply_cloud_algo(self, cloud_algo, virtual_station, options=None):
        """
        Applies a cloud algorithm (CloudAlgo object) to this object's image 
        collection.
        
        Returns nothing.

        Parameters
        ----------
        cloud_algo : CloudAlgo instance.
        virtual_station : VirtualStation instance.

        """
        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be a VirtualStation "
                + "object.")
        if not self._optimized:
            self.optimize_collection(virtual_station)
        self.collection = cloud_algo.apply(self, virtual_station, 
            self.collection, options)

        
#%% VirtualStation class

class VirtualStation:
    """
    A virtual station is an area of interest, defined by a geometry  
    (ee.Geometry), with an id code.
    
    Instantiation
    -------------

        aoi: geometry defining the area of interest (ee.Geometry or 
            ee.Feature).
        station_code: str for the station code (str; if an int is passed, it 
            will be converted to str).
        station_name: the station name (str, optional).
        lat: decimal latitude (float, optional).
        long: decimal longitude (float, optional).
    
    Attributes
    ----------
    
        aoi: ee.Geometry.
        station_code: str.
        station_name: str.
        lat: float.
        long: float.
    
    Methods
    -------
    
        update_aoi: takes an ee.Geometry or an ee.Feature and updates the area 
            of interest which defines the virtual station.
        update_code: updates the virtual station code.
    
    """
    
    def __init__(self, aoi, station_code, station_name=None, 
            lat=None, long=None):
        
        # Set/check the code.
        self.update_code(station_code)

        # Set/check the name.
        if station_name is None:
            station_name = ""
        if type(station_name) is not str:
            raise TypeError("'station_name' must be a str.")
        self.station_name = station_name
        
        # Set/check the area of interest.
        self.update_aoi(aoi)
        
        # Check lat/long. If not provided, get the geometry center.
        
        if lat is None or long is None:
            coords = aoi.centroid().getInfo()["coordinates"]
        if lat is None:
            lat = coords[1]        
        if long is None:
            long = coords[0]
        
        self.lat = lat
        self.long = long        
        
    @property
    def aoi(self):
        return self._aoi
    
    @aoi.setter
    def aoi(self, aoi):
        self.update_aoi(aoi)

    @property
    def station_code(self):
        return self._station_code
    
    @station_code.setter
    def station_code(self, station_code):
        self.update_code(station_code)
    
    @property
    def lat(self):
        return self._lat
    
    @lat.setter
    def lat(self, lat):
        if type(lat) not in [float, int]:
            raise TypeError("'lat' must be numeric.")
        self._lat = lat

    @property
    def long(self):
        return self._long
    
    @long.setter
    def long(self, long):
        if type(long) not in [float, int]:
            raise TypeError("'long' must be numeric.")
        self._long = long

    # Updates the area of interest:
    def update_aoi(self, aoi):
        """
        Takes an ee.Geometry or an ee.Feature and updates the area of interest 
        which defines the virtual station. Returns None.
        
        """
        
        if not type(aoi).__name__ in ["Geometry","Feature"]:
            raise TypeError("'aoi' must be ee.Geometry or ee.Feature.")
        if type(aoi).__name__ == "Feature":
            self._aoi = aoi.geometry()
        else:
            self._aoi = aoi

    # Updates the station code:
    def update_code(self, station_code):
        """
        Updates the virtual station code (str). Returns None.

        """
        if type(station_code) is int:
            station_code = str(station_code)
        if type(station_code) is not str:
            raise TypeError("'station_code' must be a str.")
        self._station_code = station_code
    

#%% CloudAlgorithm class

class CloudAlgorithm:
    """
    Encapsulates a function or combination of functions to be applied to an 
    image collection. The application is assynchronous, only being executed
    later when the results are effectively requested from the server.
    
    Instantiation
    -------------
    
    For instantiation, it must be passed a dictionary containing:
        "algo_code": unique indentifier (int).
        "name": name identifying the algorithm (str).
        "description": the most important information on the algorithm (str).
        "ref": references to literature or URL (str).
        "required_bands": required bands, with the 'real' band names or with 
            their 'common' names (see Product._common_bands) (list of str).
        "main_function": a function object with the algorithm core (function).
            In this main function, auxilliary functions (see below) may be 
            called.
        "aux_functions": auxilliary functions that may be called by the main 
            function (list of function objects).
        "export_vars": a list of resulting variables to be added as a property 
            of each image in the processed collection (list of str).
        "export_bands": result bands added by the algorithm to the images 
            (list of str).
        "options": a dictionary of options for the algorithm (dict or None, 
            optional).
    
    An example:
    {
        "algo_code": 15,
        "name": "Bloom-Tolerant Water Selection",
        "description": "Selects 'good' water pixels, including those affected "
            + "by dense algal blooms, and excluding pixels affected by glint "
            + "and strong spectral mixture or adjacency effects.",
        "ref": "Ventura, D.L.T.V. (unpublished)",
        "required_bands": ["blue","green","red","NIR","wl1500","wl2000"],
        "main_function": bloom_tolerant_water_selection, # function name
        "aux_functions": [_set_pixel_count, _mask_bad_pixels, 
            _simple_cloud_mask, _simple_water_detection, _simple_shadow_mask, 
            _water_product_qual_flag],
        "export_vars": ["n_selected_pixels", "n_valid_pixels", 
            "n_total_pixels", "n_bloom_pixels", "n_water_pixels", "qual_flag"],
        "export_bands": [],
        "options": None
    }
    
    Attributes
    ----------
    
    All these attributes come from the arguments for instantiation:
    
        algo_code
        name
        description
        ref
        required_bands
        main_function
        aux_functions
        export_vars
        export_bands
        options
    
    This is added in instantiation:
        
        add_coords: add bands for latitude and longitude to each image (bool).
    
    Methods
    -------
    
        apply: applies the algorithm to an image collection.
    
    """

    # Required constructor arguments and their accepted types.
    _required_args = {
        "algo_code": {"types": ["int"], "values": []},
        "name": {"types": ["str"], "values": []},
        "description": {"types": ["str"], "values": []},
        "ref": {"types": ["str"], "values": []},
        "required_bands": {"types": ["list", ["str", "list", "empty"]], 
            "values": []},
        "main_function": {"types": ["function"], "values": []},
        "aux_functions": {"types": ["list", ["function"]], "values": []},
        "export_vars": {"types": ["list", ["str", "empty"]], "values": []},
        "export_bands": {"types": ["list", ["str", "empty"]], "values": []},
        "options": {"types": ["dict", "NoneType"], "values": []}
    }

    # Constructor.
    # Help on instantiation is in the class docstring.
    def __init__(self, args_dict):
        
        # Validate the dictionary of arguments.
        _validate_args_dict(args_dict, self._required_args)
        
        # Set the instance attributes from the input dictionary.
        for key, value in args_dict.items():
            # Only set an attribute if it is a required one.
            if key in self._required_args:
                setattr(self, key, value)    
        
        # Attribute regarding the addition of coordinate bands.
        self._add_coords = False
        options = args_dict["options"]
        if isinstance(options, dict):
            if "add_coords" in options:
                if options["add_coords"]:
                    self.add_coords = True
    
    @property
    def add_coords(self):
        return self._add_coords
    @add_coords.setter
    def add_coords(self, val):
        if not isinstance(val, bool):
            raise TypeError("'add_coords' is boolean.")
        cur_val = self._add_coords
        # Update options and export_bands?
        if val and cur_val != val:
            if self.options is None:
                self.options = dict()
            self.options["add_coords"] = True
            if "latitude" not in self.export_bands:
                self.export_bands.append("latitude")
            if "longitude" not in self.export_bands:
                self.export_bands.append("longitude")            
        self._add_coords = val

    # Adds to the image collection resulting from an algorithm, bands of 
    # latitude and longitude values.
    def _add_coord_bands(self, image_collection, ref_band):
        def add_coords(image):
            masked_coords = ee.Image.pixelLonLat().updateMask(
                image.select(ref_band).mask())
            image = image.addBands(masked_coords)
            return image
        return ee.ImageCollection(image_collection).map(add_coords)
    
    # Applies the algorithm.
    def apply(self, product, virtual_station, image_collection=None, 
              options=None):
        """
        Applies the algorithm to an image collection given a virtual station 
        and a GEEDaR product.

        Parameters
        ----------
        
            product: an instance of the class Product, containing the image 
                collection that will be processed (and modified).
            virtual_station: a VirtualStation instance.
            image_collection: the image collection to be processed 
                (ee.ImageCollection, optional). If not provided, the 
                collection of the Product object will be used.
            options: dictionary with variables to be used by the algorithm 
                (dict, optional).

        Returns
        -------
        
            ee.ImageCollection (or None if it fails).

        """
        
        # Check the parameters.
        
        if type(product).__name__ != "Product":
            raise TypeError("'product' must be an instance of the "
                + "Product class.")
        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be an instance of "
                + "VirtualStation.")
        if image_collection is not None:
            if type(image_collection).__name__ != "ImageCollection":
                raise TypeError("'image_collection' must be an "
                    + "ee.ImageCollection object.")
        else:
            image_collection = product.collection
        
        product_code = product.product_code
        
        if options is None:
            options = dict()
        if type(options) is not dict:
            raise TypeError("'options' must be a dictionary")                        
        if self.options is not None:
            options = self.options | options # Add predefined options

        # Check band compatibility.
        bands = [*product.get_data_bands()] + product.band_list
        required_bands = self.required_bands
        missing_bands = []
        for sublist in required_bands:
            if not isinstance(sublist, list):
                sublist = [sublist]
            if not any(band in sublist for band in bands):
                missing_bands.append("or".join(
                    [band for band in sublist if band not in bands]))
        if len(missing_bands) > 0:
            raise TypeError("The algorithm '" + self.name + "' requires bands "
                + "that are not available in the product of code "
                + str(product_code) + ": " + str(missing_bands))
                
        # Load the auxilliary functions.
        for func in self.aux_functions:
            exec(func.__name__ + " = func")
        
        # Apply the main function.
        try:
            image_collection = self.main_function(product, virtual_station, 
                image_collection, options)
            # Add coordinates as bands?
            if self._add_coords:
                image_collection = self._add_coord_bands(image_collection, 
                    product.scale_ref_band)
            return image_collection
        except Exception as e:
            print(e)
            return


#%% LocalAlgorithm class
        
class LocalAlgorithm:
    """
    Encapsulates a function to be applied to a Pandas data frame. In GEEDaR,
    it serves the purpose of applying inversion algorithms to the reflectance
    time series extracted from the server after application of the cloud
    algorithm.
    
    Instantiation
    -------------
    
    For instantiation, it must be passed a dictionary containing:
        "algo_code": unique identifier (int).
        "name": name of the algorithm (str).
        "description": the most important info on the algorithm (str).
        "ref": reference to the literature or URL (str).
        "required_bands": names of the bands used by the algorithm (list of 
            str). In the input dataframe such bands appear with a 'stat 
            suffix' (ex: 'red_median') which must be one of the 'applicable
            suffixes' listed in the next parameter.
        "applicable_suffixes": suitable suffixes (list of str). The suffix 
            names must be in the 'stat_suffix' property of the previously 
            applied Rreducer object. These suffixes are added by GEE to 
            the image band names when an ee.Reducer is applied.
        "function": function object containing the algorithm.
        "options": a dictionary of options for the algorithm (dict or None, 
            optional).

    
    An example:
    {
        "algo_code": 3,
        "name": "SSS Madeira",
        "description": "Estimates the surface suspended solids concentration 
            in the Madeira River.",
        "ref": "Villar, R.E.; Martinez, J.M.; Le Texier, M.; Guyot, J.L.; 
            Fraizy, P.; Meneses, P.R.; Oliveira, E. A study of sediment 
            transport in the Madeira River, Brazil, using MODIS remote-sensing 
            images. Journal of South American Earth Sciences, v. 44, p. 45-54, 
            2013.",
        "required_bands": ["red", "NIR"],
        "applicable_suffixes": ["median","mean"],
        "function": madeira_2013, # Name of the function
        "options": None
    }
    
    Attributes
    ----------
    
    These attributes come from the arguments for instantiation:

        algo_code
        name
        description
        ref
        required_bands
        applicable_suffixes
        function

    Methods
    -------
    
        apply: applies the algorithm to the input dataframe.
    
    """
    
    # Required constructor arguments and their accepted types.
    _required_args = {
        "algo_code":  {"types": ["int"], "values": []},
        "name": {"types": ["str"], "values": []},
        "description": {"types": ["str"], "values": []},
        "ref": {"types": ["str"], "values": []},
        "required_bands": {"types": ["list", ["str", "empty"]], "values": []},
        "applicable_suffixes": {"types": ["list", ["str", "empty"]], 
            "values": []},
        "function": {"types": ["function"], "values": []},
        "options": {"types": ["dict", "NoneType"], "values": []}
    }

    # Help on instantiation is in the class docstring.
    def __init__(self, args_dict):
        
        # Validate the dictionary of arguments.
        _validate_args_dict(args_dict, self._required_args)
                
        # Set the instance attributes from the input dictionary.
        for key, value in args_dict.items():
            # Only set an attribute if it is a required one.
            if key in self._required_args:
                setattr(self, key, value)    

    # Applies the algorithm.
    def apply(self, df, options=None):
        """
        Applies the algorithm to the input dataframe ('df'). The resulting 
        variables will be returned as columns added to the input dataframe.

        Parameters
        ----------
        
            df: a Pandas dataframe with columns corresponding to this object's 
                 attribute 'required_bands' or to a combination of 
                 'required_bands' and 'applicable_suffixes' (with a "_" as
                separator). Othercolumns in the dataframe will be ignored.
            options: dictionary with variables to be used by the algorithm 
                (dict, optional).

        Returns
        -------
            
            A Pandas dataframe with added columns corresponding to the 
            variables resulting from the algorithm application.

        """
        
        # Check the parameters.
        
        if not isinstance(df, pandas.DataFrame):
            raise TypeError("'df' must be a Pandas dataframe.")

        if options is None:
            options = dict()
        if type(options) is not dict:
            raise TypeError("'options' must be a dictionary")                        
        if self.options is not None:
            options = self.options | options # Add predefined options
        
        if "stat_suffixes" in df.attrs:
            reducer_suffixes = df.attrs["stat_suffixes"]
        else:
            reducer_suffixes = []
                
        df = df.copy()
        df_cols = [*df.columns]
        required_bands = self.required_bands
        applicable_suffixes = copy.deepcopy(self.applicable_suffixes)

        # "Explode" lists in df?
        explode = False
        if "list" in reducer_suffixes and "list" not in applicable_suffixes:
            explode = True
            applicable_suffixes.append("list")

        # Check columns compatibility and remove the stat. suffix (if any).        
        comb_names = dict()
        applied_stat = None
        for b in required_bands:
            for s in applicable_suffixes:
                comb_names[b + "_" + s] = b
        for col in df_cols:
            if col in required_bands:
                continue
            if col in comb_names:
                df.rename(columns={col:comb_names[col]}, inplace = True)
                if not applied_stat:
                    applied_stat = col.split("_")[-1]
                continue
            df.drop(columns=col, inplace = True)
                
        df_cols = [*df.columns]
        if not all(col in df_cols for col in required_bands):
            raise TypeError("The algorithm '" + self.name + "' requires one "
                + "or more columns that are not in the 'df' data frame.")
        
        if explode:
            # Turn lists into rows for application of the local algorithm.
            df = unfold_df_lists(df)
            for col in [*df.columns]:
                if df[col].dtype == "object":
                    try:
                        df[col] = df[col].astype("Float32")
                    except:
                        pass
        
        # Apply the main function.
        try:
            preresult_df = self.function(df, options)
        except Exception as e:
            print(e)
            return
        
        # Restore lists.
        if explode:
            preresult_df = restore_df_lists(preresult_df)
        
        # Keep only the result columns.
        nonresult_cols = [c for c in [*preresult_df.columns] if c in df_cols]
        result_df = preresult_df.drop(columns=nonresult_cols)
        # Insert suffix for the applied stat to ensure all data columns will 
        # have a stat suffix.
        if applied_stat:
            result_df.rename(columns={c:(c + "_" + applied_stat) 
                for c in [*result_df.columns]}, inplace=True)
        
        return result_df
            

#%% Reducer class
    
class Reducer:
    """
    A wrapper for ee.Reducer with complementary attributes.
    
    Instantiation
    -------------
    
        reducer_code: a unique identifier (int).
        ee_reducer: ee.Reducer object.
        stat_suffix: a list with the suffixes added by GEE to the image bands
            upon application of the ee.Reducer passed in 'ee_reducer' (list of 
            str).
        description: describes what is calculated by the reducer (ex: 'median', 
            'mean', 'count' etc.) (str).
    
    Attributes
    ----------
    
    All attributes come from the arguments for instantiation:
    
        reducer_code
        ee_reducer
        stat_suffix
        description
        
    Methods
    -------
    
        (none)
    
    """
    def __init__(self, reducer_code, ee_reducer, stat_suffix, 
            description=""):
        
        if type(reducer_code) is not int:
            raise TypeError("'reducer_code' must be an integer.")
        if type(ee_reducer).__name__ != "Reducer":
            raise TypeError("'ee_reducer' must be an ee.Reducer.")
        if type(stat_suffix) is not list:
            raise TypeError("'stat_suffix' must be a list.")
        if not all(type(s) is str for s in stat_suffix):
            raise TypeError("'stat_suffix' must be a list of strings.")
        if type(description) is not str:
            raise TypeError("'description' must be a str.")
        
        self.reducer_code = reducer_code
        self.ee_reducer = ee_reducer
        self.stat_suffix = stat_suffix
        self.description = description


#%% Demand class

class Demand:
    """
    Demand objects describes a demand for data retrieval from Google Earth 
    Engine. It gets, as input, objects of the classes Product, VirtualStation, 
    CloudAlgorithm, Reducer and LocalAlgorithm, which respectively defines the 
    source of data, the area of interest, the algorithm to be applied in the 
    server side, the statistical parameter to "reduce" the data to 
    representative values (ex: median) and the algorithm to be applied locally,
    after the reduction and download. A period of interest or a list of 
    specific dates may also be passed to define the demand.
    
    Instantiation
    -------------
    
        virtual_station: VirtualStation object.
        product: Product object.
        cloud_algo: CloudAlgorithm object.
        reducer: Reducer object or None (optional, defaults to no reducer).
        local_algo: LocalAlgorithm object.
        start_date: datetime.date or str in the format 'yyyy-mm-dd' or None 
            (optional).
        end_date: datetime.date or str in the format 'yyyy-mm-dd' or None 
            (optional).
        date_list: list of dates as str or datetime.date.
        clip: clip the images to the area of interest? (bool, defaults 
            to False).
        cloud_algo_options: dictionary of variables to be passed to the 
            CloudAlgorithm object (dict).
        local_algo_options: dictionary of variables to be passed to the 
            LocalAlgorithm object (dict or None, optional).
        save_to: the path of a CSV file or a GeedarDB object to which save the
            retrieved data (str or GeedarDB or None, optional).
        auto_save: if True, automatically saves each partial result of the 
            demand execution; if False (default), results have to be saved 
            manually with 'save_to_csv' or 'save_to_db'.
        demand_id: the id of the corresponding demand record in the target 
            database (int or None, optional).
        source_id: the id of the data source (useful when the target database 
            integrates data rom multiple source) (int or None, optional).
        data_status: the default code for data status (useful if the data in 
            the target database may have different status such as 'validated', 
            'provisional' and 'reproved') (int or None, optional).
        reload_data: determines if it should be tried to load previous data 
            from the database or from an operation in mode 1 or 2? (bool or 
            None for automatic determination, optional).
        silent_load: if True and preexisting data loading fails, no warning 
            or error will be raised (bool, defaults to False).
    
    Attributes
    ----------
    
    These attributes come from the arguments from instantiation:

        virtual_station (VirtualStation)
        product (Product)
        cloud_algo (Cloudalgo)
        reducer (Reducer)
        local_algo (None of LocalAlgo)
        start_date (datetime.date)
        end_date (datetime.date)
        date_list (list of date-formatted strings)
        clip (bool)
        cloud_algo_options (None or dict)
        local_algo_options (None or dict)
        save_to (None or str or GeedarDB)
        auto_save (bool)
        demand_id (None or int)
        source_id (None or int)
        data_status (None or int)
    
    Properties
    ----------
        
        time_series: returns the result dataframe from the processed demand.
        
    Methods
    -------

        execute
        get_demand_code
        join_codes
        next_group
        reduce_time_series
        reload_data
        save_to_csv
        save_to_db
        unfold_demand_code (or 'split_codes')

    """
    
    # Default name of the column in the imported or exported CSV corresponding 
    # to the datatime index of the time series dataframe.
    _dt_col_name = "date_time"
    # The time series also requires these columns:
    _reserved_columns = ["station_code", "demand_code"]
    # If a dataframe contains lists of pixel values, they must be reduced 
    # before saving the results to a database. Which statistic to apply?
    _list_reducer = "median"
    
    def __init__(self, virtual_station, product, cloud_algo, reducer=None, 
            local_algo=None, start_date=None, end_date=None, date_list=None, 
            clip=False, cloud_algo_options=None, local_algo_options=None, 
            save_to=None, auto_save=False, demand_id=None, source_id=None, 
            data_status=None, reload_data=None, silent_load=False):
        
        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be an instance of "
                + "VirtualStation.")        
        if type(product).__name__ != "Product":
            raise TypeError("'product' must be an instance of "
                + "Product.")
        if type(cloud_algo).__name__ != "CloudAlgorithm":
            raise TypeError("'cloud_algo' must be an instance of "
                + "CloudAlgorithm.")
        if local_algo is not None:
            if type(local_algo).__name__ != "LocalAlgorithm":
                raise TypeError("'local_algo' must be an instance of "
                    + "LocalAlgorithm.")
        if reducer is None:
            reducer = Reducer({"reducer_code": 0, 
                "ee_reducer": ee.Reducer.toList(), 
                "description": "all values",
                "stat_suffix": ["list"]})
        if type(reducer).__name__ != "Reducer":
            raise TypeError("'reducer' must be a Reducer object.")
        if not isinstance(auto_save, bool):
            raise TypeError("'auto_save' must be True or False.")
        if reload_data is not None:
            if not isinstance(reload_data, bool):
                raise TypeError("'reload_data' must be True or False.")
        if not isinstance(silent_load, bool):
            raise TypeError("'silent_load' must be True or False.")
        
        # If the reducer will return a list, then update cloud_algo to also 
        # return coordinate values.
        if "list" in reducer.stat_suffix:
            cloud_algo.add_coords = True

        self._product = product
        self._virtual_station = virtual_station
        self._cloud_algo = cloud_algo
        self._reducer = reducer
        self._local_algo = local_algo
        self._cloud_algo_options = cloud_algo_options
        self._local_algo_options = local_algo_options
        self._silent_load = silent_load
        self._clip = clip
        
        # The time series retrieved from the server with the values of the 
        # selected pixels for each band and variable.
        self._time_series = None
                
        # Custom variables that result from a cloud algorithm.
        export_vars = list(set(cloud_algo.export_vars))
        self._export_vars = export_vars
        # Custom bands added to images by a cloud algorithm.
        export_bands = cloud_algo.export_bands
        self._export_bands = list(set(export_bands))
        
        # Saving-related parameters:
            
        save_type = None
        if save_to is not None:
            if type(save_to) is str:
                if not is_path_valid(save_to):
                    raise ValueError("The path in 'save_to' is invalid.")
                save_type = "csv"
            elif type(save_to).__name__ == "GeedarDB":
                save_type = "db"
            else:
                raise TypeError("Invalid argument type in 'save_to'. Should "
                    + "be str or GeedarDB.")
        self._save_type = save_type
        self._save_to = save_to        
        self._auto_save = auto_save
        
        # Database ids:
            
        if demand_id is not None:
            if not isinstance(demand_id, int):
                raise TypeError("'demand_id' must be an int.")
        self._demand_id = demand_id
        
        if source_id is not None:
            if not isinstance(source_id, int):
                raise TypeError("'source_id' must be an int.")
        self._source_id = source_id
        
        if data_status is not None:
            if not isinstance(data_status, int):
                raise TypeError("'data_status' must be an int.")
        self._data_status = data_status

        # Set preliminary date attributes. They may change after data 
        # reloading or collection optimization.
        tmp_product = product.new()
        tmp_product.optimize_collection(virtual_station, start_date, end_date, 
                date_list, clip)
        self._start_date = tmp_product.start_date
        self._end_date = tmp_product.end_date
        self._date_list = tmp_product.date_list
                                
        # Reload preexisting data?
        if reload_data is None:
            # Determine if it should be tried to load previous data.
            reload_data = False
            if save_type == "csv":
                if os.path.isfile(save_to):
                    reload_data = True
        data_reloaded = False
        if reload_data:
            # Load previous data into '_time_series'. After the loading, the 
            # demand is reset by updating the start and end dates,
            # optimizing the image collection and defining image groups.
            data_reloaded = self.reload_data()
        
        if not data_reloaded:
            # If no reloading was done, then demand preparation is completed 
            # now by optimizing (filtering) the image collection.
            # The following attributes are set or updated: 
            #   _product; _start_date; _end_date; _date_list; _result_bands; 
            #   _n_image_groups; _group_size; _current_image_group.
            self._reset()
        
    @property
    def product(self):
        return self._product
    @property
    def start_date(self):
        return self._start_date
    @property
    def end_date(self):
        return self._end_date
    @property
    def date_list(self):
        return self._date_list
    @property
    def virtual_station(self):
        return self._virtual_station
    @property
    def cloud_algo(self):
        return self._cloud_algo
    @property
    def reducer(self):
        return self._reducer
    @property
    def local_algo(self):
        return self._local_algo
    @property
    def cloud_algo_options(self):
        return self._cloud_algo_options
    @property
    def local_algo_options(self):
        return self._local_algo_options
    @property
    def demand_id(self):
        return self._demand_id
    @property
    def source_id(self):
        return self._source_id
    @property
    def data_status(self):
        return self._data_status
    @property
    def time_series(self):
        return self._time_series
    
    # Resets the demand, optimizing the image collection and defining the 
    # image grouping.
    def _reset(self, check_db=True):
        # Create a new product to avoid making changes to the original.
        new_product = self._product.new()
        virtual_station = self._virtual_station
        export_bands = self._export_bands
        start_date = self._start_date
        end_date = self._end_date
        date_list = self._date_list
        clip = self._clip
        save_type = self._save_type
        
        if save_type == "db":
            if check_db:
                # To operate with a database, it must have records 
                # corresponding to this demand.
                self._check_db()
            # Update 'start_date' and 'end_date' are updated to avoid 
            # requesting again data already stored in the database.            
            last_date_str = self._get_last_db_date()
            if last_date_str is not None:
                start_date, end_date = self._new_start_end_dates(
                    start_date, end_date, last_date_str)
        
        # Optimize (filter) the image collection.
        new_product.optimize_collection(virtual_station, start_date, end_date, 
                date_list, clip)
        # Store the updated attributes.
        self._product = new_product
        self._start_date = new_product.start_date
        self._end_date = new_product.end_date
        self._date_list = new_product.date_list 
            
        # The list of bands to be reduced:
        data_bands = list(set(new_product.get_data_bands().values()))
        result_bands = export_bands + data_bands
        self._result_bands = result_bands

        # To avoid exceeding GEE capacity, the image collection may have to be
        # divided in groups of images. So the number of groups is calculated
        # and stored, as well as the group size and the current group being 
        # requested. The following attributes are set:
        #_n_image_groups
        #_group_size
        #_current_image_group
        self._group_images()        
        
    # Checks if the connection to the database is working and if there is 
    # coherence between this demand's composition (demand id, product, 
    # cloud algo, reducer and local algo) and the record in the database.
    def _check_db(self):
        demand_id = self._demand_id
        geedar_db = self._save_to
        db_names = geedar_db._db_names
        
        if demand_id is None:
            raise ValueError("For database operation, a value of 'demand_id' "
                + "must be passed when instantiating the Demand object.")
        if not str(demand_id).isnumeric():
            raise TypeError("The value of 'demand_id' passed for "
                + "instantiation of the Demand object must be an integer.")
        demand_id = int(demand_id)

        # Use the real column names of the database.        
        cur_colnames_attr = geedar_db._use_real_col_names
        geedar_db.use_real_col_names = True
                
        # Columns of the target tables
        station_id_col = db_names["station"]["primary_key"].upper()
        station_code_col = db_names["station"]["code"].upper()
        demand_id_col = db_names["demand"]["primary_key"].upper()
        demand_st_fk_col = db_names["demand"]["fkey_station"].upper()
        demand_prod_fk_col = db_names["demand"]["fkey_product"].upper()
        demand_cloud_fk_col = db_names["demand"]["fkey_cloud_algo"].upper()
        demand_local_fk_col = db_names["demand"]["fkey_local_algo"].upper()
        demand_reducer_fk_col = db_names["demand"]["fkey_reducer"].upper()
        product_id_col = db_names["product"]["primary_key"].upper()
        product_inst_fk_col = db_names["product"]["fkey_instrument"].upper()
        stat_id_col = db_names["stats"]["primary_key"].upper()
        stat_suffix_col = db_names["stats"]["suffix"].upper()

        # Retrieve the demand record from the database.
        demand_record = geedar_db.get_table("demand", 
            where_str=(demand_id_col + " = " + str(demand_id)))        
        if len(demand_record) == 0:
            raise ValueError("No record matched the provided 'demand_id': "
                + str(demand_id) + ".")
        elif len(demand_record) > 1:
            raise ValueError("More than one record matched the provided " 
                + "'demand_id'. Should be only one.")
        demand_record.columns = [c.upper() for c in [*demand_record.columns]]
        
        # Retrieve the station record from the database.
        station_id = int(demand_record[demand_st_fk_col][0])
        station_record = geedar_db.get_table("station", 
            where_str=(station_id_col + " = " + str(station_id)))
        if len(station_record) == 0:
            raise ValueError("No record matched this station id: " 
                + str(station_id) + ".")
        elif len(station_record) > 1:
            raise ValueError("More than one record matched this station id: " 
                + str(station_id) + ". Should be only one.")
        station_record.columns = [c.upper() for c in [*station_record.columns]]
        
        # Compare demand data from the database to this object.
        station_code = str(station_record[station_code_col][0])
        cur_station_code = str(self._virtual_station.station_code)
        if station_code.upper() != cur_station_code.upper():
            raise ValueError("The station code in the database (" 
                + station_code + ") did not match the one from the current "
                + "Demand object (" + cur_station_code + ").")
        product_code = int(demand_record[demand_prod_fk_col][0])
        cur_product_code = int(self._product.product_code)
        if product_code != cur_product_code:
            raise ValueError("The product code in the database (" 
                + str(product_code) + ") did not match the one from the "
                + "current Demand object (" + str(cur_product_code) + ").")
        cloud_algo_code = int(demand_record[demand_cloud_fk_col][0])
        cur_cloud_algo_code = int(self._cloud_algo.algo_code)
        if cloud_algo_code != cur_cloud_algo_code:
            raise ValueError("The cloud algorithm code in the database (" 
                + str(cloud_algo_code) + ") did not match the one from the "
                + "current Demand object (" + str(cur_cloud_algo_code) + ").")
        local_algo_code = int(demand_record[demand_local_fk_col][0])
        cur_local_algo_code = int(self._local_algo.algo_code)
        if local_algo_code != cur_local_algo_code:
            raise ValueError("The local algorithm code in the database (" 
                + str(local_algo_code) + ") did not match the one from the "
                + "current Demand object (" + str(cur_local_algo_code) + ").")
        reducer_code = int(demand_record[demand_reducer_fk_col][0])
        cur_reducer_code = int(self._reducer.reducer_code)
        if reducer_code != cur_reducer_code:
            raise ValueError("The reducer code in the database (" 
                + str(reducer_code) + ") did not match the one from the "
                + "current Demand object (" + str(cur_reducer_code) + ").")
                
        # Get the instrument id from the product record.
        product_record = geedar_db.get_table("product", 
            where_str=(product_id_col + " = " + str(product_code)))
        if len(product_record) == 0:
            raise ValueError("No record matched this product code: " 
                + str(product_code) + ".")
        elif len(product_record) > 1:
            raise ValueError("More than one record matched this product code: " 
                + str(product_code) + ". Should be only one.")
        product_record.columns = [c.upper() for c in [*product_record.columns]]
        inst_id = product_record[product_inst_fk_col][0]
        if not str(inst_id).isnumeric():
            raise ValueError("An integer was expected for the id of the "
                + "instrument record linked to the product of code #" 
                + str(product_code) + ".")
        
        # Get the statistical parameter id. If a parameter is not registered
        # in the database, it must be inserted, then.
        stat_suffixes = self._reducer.stat_suffix.copy() # list
        for stat_suffix in stat_suffixes:
            stat_table = geedar_db.get_table("stats")
            stat_table.columns = [c.upper() for c in [*stat_table.columns]]
            stat_table.dropna(axis=0, subset=stat_suffix_col, inplace=True)
            stat_id = [stat_table.loc[i, stat_id_col] 
               for i in stat_table.index if stat_table.loc[i, 
               stat_suffix_col].upper() == stat_suffix.upper()]
            if len(stat_id) > 1:
                raise ValueError("More than one record matched this " 
                    + "statistical suffix: " + str(stat_suffix) 
                    + ". Should be only one.")
            elif len(stat_id) == 0:
                raise ValueError("A corresponding record was not found in the "
                    + "database for the statistical suffix '" + stat_suffix 
                    + "'.")
        
        # Undo the enforcement regarding the use of real column names.
        geedar_db.use_real_col_names = cur_colnames_attr        
            
    # Gets the last acquisition date in the database for this demand.
    def _get_last_db_date(self):
        demand_id = self._demand_id
        geedar_db = self._save_to
        
        return geedar_db.get_last_date(demand_id)
            
    # Determines new start and end dates from a given latest date (as str).
    # Used, for example, to update the period of interest of the demand.
    def _new_start_end_dates(self, start_date, end_date, last_date_str):
        last_date = pandas.to_datetime(
            last_date_str) + pandas.Timedelta(days=1)
        if start_date is None:
            new_start_date = last_date 
        else:
            new_start_date = max(last_date, 
                pandas.to_datetime(start_date))
        start_date = new_start_date.date()
        if end_date is not None:
            new_end_date = max(pandas.to_datetime(end_date), 
                new_start_date + pandas.Timedelta(days=1))
            end_date = new_end_date.date()
            
        return (start_date, end_date)
    
    # Define the grouping of images for stepwise processing.
    def _group_images(self):
        aoi = self._virtual_station.aoi
        product = self._product
        n_bands = len(product.band_list)      
        n_dates = len(product.available_dates)
        n_pixels_aoi = aoi.area().getInfo() / math.pow(product.rough_scale, 2)        
        n_sim_imgs = max(1, min(_MAX_SIM_IMAGES,
            math.floor(_MAX_PROC_PIXELS / (n_pixels_aoi * n_bands))))
        n_groups = math.ceil(n_dates / n_sim_imgs)
        self._n_image_groups = n_groups
        self._group_size = n_sim_imgs
        self._current_image_group = 1
    
    # Loads data related to this demand from a file or dataframe.
    def _load_data_from_csv(self, csv_df=None): # <------------------------ APAGAR -------
        silent_load = self._silent_load
        station_code = self._virtual_station.station_code
        demand_code = self.get_demand_code(format_as="str")
        start_date = self._start_date
        reserved_columns = self._reserved_columns
        dt_col_name = self._dt_col_name
        required_columns = [dt_col_name] + reserved_columns
        df = None
        if csv_df is None and self._save_type == "csv":
            source = self._save_to
        elif isinstance(csv_df, pandas.DataFrame):
            df = csv_df.copy()
        else:
            if not isinstance(csv_df, str):
                raise TypeError("'csv_df' must be a str.")
            source = csv_df
        
        if df is None:
            df = pandas.read_csv(source)
        
        # Check for required columns.
        if not all(c in [*df.columns] 
                for c in required_columns):
            if not silent_load:                
                raise ValueError("The pre-existing CSV must have the "
                    + "columns: " + str(required_columns))
            else:
                return
        
        # Set datetime index.
        try:
            df[dt_col_name] = pandas.to_datetime(df[dt_col_name])
        except Exception as e:
            if not silent_load:                
                print(e)
                raise TypeError("The first column of the CSV must have a "
                    + "valid datetime format.")
            else:
                return
        else:
            df.set_index(dt_col_name, inplace=True, drop=True)
        
        # If the data frame has no data, it's not useful.
        if len(df) == 0:
            return
        
        # Check if station and demand are all the same.
        station_vals = df[reserved_columns[0]].tolist()
        demand_vals = df[reserved_columns[1]].tolist()
        if len(set(station_vals)) > 1 or len(set(demand_vals)) > 1:
            if not silent_load:                
                raise ValueError("The preexisting CSV seems to have data "
                    + "of more then one station or demand. It is not allowed.")
            else:
                return
        # Check if station, demand and first date match the current object.
        df_station = station_vals[0]
        df_demand = demand_vals[0]
        df_start_date = df.index[0].date()
        if (df_station != station_code or df_demand != demand_code 
                or df_start_date != start_date):
            if not silent_load:                
                raise ValueError("The preexisting CSV seems to have data "
                    + "of another station or demand, since the value in "
                    + "'station_code' or 'demand_code' or 'start_date' "
                    + "did not match the one of this demand.")
            else:
                return
        
        return df

    # Load data related to this demand from the database.
    def _load_from_db(self):
        geedar_db = self._save_to
        demand_id = self._demand_id
        station_code = self._virtual_station.station_code
        demand_code = self.get_demand_code(format_as="str", 
            include_station=False)
        reserved_columns = self._reserved_columns
        dt_col_name = self._dt_col_name
        required_columns = [dt_col_name] + reserved_columns
        
        # Enforce the use of db_names' keys instead of the real column names.
        # First store the current option to restore it later.
        cur_op = geedar_db.use_real_col_names
        geedar_db.use_real_col_names = False
        # Retrieve the data.
        db_df = geedar_db.get_data(demand_id)
        if geedar_db.use_real_col_names != cur_op:
            geedar_db.use_real_col_names = cur_op
            
        if db_df is None:
            return
        if len(db_df) == 0:
            return
        
        # Build the time series dataframe.
        df = pandas.DataFrame(columns=required_columns).astype({
            required_columns[0]: 'datetime64[s]',
            required_columns[1]: 'string',
            required_columns[2]: 'string'
        })
        df_row = -1
        last_acq_id = -1
        for i in db_df.index:
            acq_id = db_df.loc[i, "acquisition.primary_key"]
            if int(i) > 0:
                last_acq_id = db_df.loc[int(i) - 1, "acquisition.primary_key"]
            date_str = db_df.loc[i, "acquisition.date"].strftime("%Y-%m-%d")
            time = pandas.to_datetime(db_df.loc[i, "acquisition.time"])
            time_str = time.strftime("%H:%M:%S")
            datetime_str = date_str + " " + time_str
            datetime_val = pandas.to_datetime(datetime_str)
            
            if last_acq_id != acq_id:
                df_row += 1
                df.loc[df_row, required_columns[0]] = datetime_val
                df.loc[df_row, required_columns[1]] = station_code
                df.loc[df_row, required_columns[2]] = demand_code
            
            value = db_df.loc[i, "result.value"]
            var_name = db_df.loc[i, "variable.name"]
            stat_suffix = db_df.loc[i, "stats.suffix"]
            if stat_suffix.lower() == "none":
                col_name = var_name
            else:
                col_name = var_name + "_" + stat_suffix
            if col_name not in [*df.columns]:
                df[col_name] = None
            df.loc[df_row, col_name] = value
        
        df.set_index(dt_col_name, inplace=True)
        
        # Undo the change in the database object's attribute regarding the use 
        # of real column names.
        geedar_db.use_real_col_names = cur_op
        
        return df

    # Validates the data being imported (applied by the 'reload_data' method).
    def _validate_time_series(self, df):
        silent_load = self._silent_load
        station_code = self._virtual_station.station_code
        demand_code_str = self.get_demand_code(format_as="str")
        start_date = self._start_date
        reserved_columns = self._reserved_columns
        dt_col_name = self._dt_col_name
        required_columns = [dt_col_name] + reserved_columns
        df_cols = [*df.columns]
        
        # Check for required columns.
        if not all(c in df_cols 
                for c in required_columns):
            if not silent_load:                
                raise ValueError("The input dataframe must have the "
                    + "columns: " + str(required_columns))
            else:
                return
        
        # Get data columns.
        data_cols = [c for c in df_cols if c not in required_columns]
        if len(data_cols) == 0:
            if not silent_load:
                print("(!) No data columns in the input dataframe.")
            return
        
        # Check datetime index.
        try:
            df[dt_col_name] = pandas.to_datetime(df[dt_col_name])
        except Exception as e:
            if not silent_load:                
                print(e)
                raise ValueError("The first column of the CSV must have a "
                    + "valid datetime format with no missing values.")
            else:
                return
        
        # If the data frame has no data, it's not useful.
        if len(df) == 0:
            return
        
        # Check if station and demand values are all the same.
        station_vals = df[reserved_columns[0]].tolist()
        demand_vals = df[reserved_columns[1]].tolist()
        if len(set(station_vals)) > 1 or len(set(demand_vals)) > 1:
            if not silent_load:                
                raise ValueError("The preexisting CSV seems to have data "
                    + "of more then one station or demand. It is not allowed.")
            else:
                return
            
        # Check if station, demand and first date match the current object.
        df_station = station_vals[0]
        df_demand = demand_vals[0]
        df_start_date = df[dt_col_name].iloc[0].date()
        if (df_station != station_code or df_demand != demand_code_str 
                or df_start_date != start_date):
            if not silent_load:                
                raise ValueError("The preexisting CSV seems to have data "
                    + "of another station or demand, since the value in "
                    + "'station_code' or 'demand_code' or 'start_date' "
                    + "did not match the one of this demand.")
            else:
                return
        
        # Enforce dtype for reserved columns.
        for col in reserved_columns:
            df[col] = df[col].astype("string")            
        
        # Check content and data type in the remaining columns.
        for col in data_cols:
            checked_col_vals = []
            has_list = False
            for row in df.index:
                val = df.at[row, col]
                # List?
                if str(val).startswith("[") and str(val).endswith("]"):
                    has_list = True
                    lst = cast_numeric_list(str(val[1:-1]).split(","))
                    if lst is None:
                        if not silent_load:
                            raise ValueError("Invalid list in row " + str(row) 
                                + " of the input dataframe.")
                        else:
                            return
                    checked_col_vals.append(lst)
                else:
                    if str(val).lower().replace(" ","") in ["", "none", "na", 
                            "nan", "nat", "<na>"]:
                        checked_col_vals.append(math.nan)
                    else:
                        try:
                            checked_col_vals.append(float(val))
                        except:
                            if not silent_load:
                                raise ValueError("Invalid value in row " 
                                    + str(row) + " of the input dataframe.")
                            else:
                                return
            # Data type.
            if has_list:
                # The reducer list must include at least one list reducer.
                stat_suffixes = self.reducer.stat_suffix
                if not "list" in stat_suffixes:
                    if not silent_load:
                        raise ValueError("The column '" + col + "' has lists "
                            + "in it, but no reducer in this demand results "
                            + "in lists of values.")
                    else:
                        return
                # The column suffix must be 'list' or none.
                name_parts = col.split("_")
                if len(name_parts) >= 2:
                    suffix = name_parts[-1]
                    if (suffix in stat_suffixes and suffix != "list"):
                        if not silent_load:
                            raise ValueError("Since the column '" + col 
                                + "' of the input data has lists, it was "
                                + "expected its suffix to be 'list', but was '" 
                                + suffix + "'.")
                        else:
                            return
                # All cells must contain a list.
                if all(isinstance(v, list) for v in checked_col_vals):
                    df[col] = pandas.Series(checked_col_vals, dtype="object")
                else:
                    if not silent_load:
                        raise ValueError("Inconsistent data in the column '" 
                            + col + "' of the input data: either all or no "
                            + "element must be of type 'list'.")
                    else:
                        return
            else:
                try:
                    df[col] = pandas.Series(checked_col_vals, dtype="Float32")
                except Exception as e:
                    if not silent_load:
                        print(e)
                        raise ValueError("Inconsistent data in the column '" 
                            + col + "' of the input data: could not cast it "
                            + "to float.")
                    else:
                        return 
        
        # Set the date_time column as the index.
        try:
            df.set_index(dt_col_name, inplace=True, drop=True)
        except Exception as e:
            if not silent_load:
                print(e)
                raise ValueError("Something went wrong when setting the '" 
                    + dt_col_name + "' column as the index of the input "
                    + "dataframe.")
            else:
                return             

        return df

    # Try to reload data from the database or from a file/dataframe.
    def reload_data(self, check_db=True, reset=True, csv_df=None): # <----- No modo 3, precisa passar pelo _validate_time_series também.
        """
        Try to load data previously saved in the database or in a local file. 
        The loaded data will be stored in the 'time_series' property.
        
        Parameters
        ----------
        
            check_db: check if the attributes of this Demand object correspond
                to the foreign keys of the demand record in the database 
                (bool, optional).
            reset: reset this Demand object by reoptizing the image collection 
                and reapplying the cloud algorithm? (bool, optional)
            csv_df: a dataframe or the path to a csv file (str or DataFrame, 
                optional).

        Returns
        -------
            
            True if data was reloaded, False if not.

        """
        
        silent_load = self._silent_load
        start_date = self._start_date
        end_date = self._end_date
        if csv_df is None:
            input_type = self._save_type
            source = self._save_to
        elif isinstance(csv_df, pandas.DataFrame):
            source = csv_df
            input_type = "df"
        else:
            if not isinstance(csv_df, str):
                raise TypeError("'csv_df' must be a str.")
            source = csv_df
            input_type = "csv"
        
        df = None
        # CSV file (mode 1 or 2).
        if input_type == "csv":
            if not os.path.exists(source):
                if not silent_load:
                    raise FileNotFoundError("Could not find the file '"
                        + source + "'.")
                else:
                    return
            #df = self._load_data_from_csv(source)
            df = pandas.read_csv(source)
            df = self._validate_time_series(df)
        # A dataframe was delivered.
        elif input_type == "df":
            #df = self._load_data_from_csv(source.copy())
            df = self._validate_time_series(source.copy())
        # Database mode.
        elif input_type == "db":
            if check_db:
                self._check_db()
            df = self._load_from_db()                
        
        if df is None:
            return False
        
        if len(df) > 0:
            self._time_series = df
            print(str(len(df)) + " record(s) reloaded for the current demand.")
        else:
            print("No data to reload for the current demand.")
            return False
        
        # Reset the Demand object.
        if reset:
            # Update the start and end dates of the demand.
            last_date_str = df.index.max().strftime("%Y-%m-%d")
            print("Demand will start from "
                "the latest saved record: " + last_date_str + ".")
            start_date, end_date = self._new_start_end_dates(
                start_date, end_date, last_date_str)
            self._start_date = start_date
            self._end_date = end_date
            # Reset. No need to check the database again.
            self._reset(check_db=False)
        
        return True

    # Get a code identifying the product, algorithms and reducer to be used.
    # It is a way of summarizing the processing applied to a station.
    def get_demand_code(self, format_as="str", include_station=False):
        """
        Returns a code (as a string, by default) describing the current demand.
        Ex: 'P314C15L3R1', where P stands for Product, C for cloud algorithm,
        L for local algorithm, and R for Reducer, whereas the numbers are the 
        codes identifying them.
        If chosen 'list' as output format, a list is returned with letters and
        codes each being an element for the list. For 'dict' format, the
        letters are the keys and the codes the values.

        Parameters
        ----------
        
            format_as: 'str' (default), 'list' or 'dict'.
            include_station: If True, includes the station identification in 
                the code (letter 'P' plus the code). If False (default), skips 
                station and starts with the product.
        
        Returns
        -------
        
            str or list or dict.       

        """
        
        station_str = str(self.virtual_station.station_code)
        product_str = str(self.product.product_code)
        cloud_algo_str = str(self.cloud_algo.algo_code)
        local_algo_str = str(self.local_algo.algo_code)
        reducer_str = str(self.reducer.reducer_code)

        if format_as=="str":
            if include_station:
                demand_code = "S" + station_str
            else:
                demand_code = ""
            demand_code = (demand_code 
                + "P" + product_str + "C" 
                + cloud_algo_str + "L" 
                + local_algo_str + "R" + reducer_str)
        elif format_as=="list":
            if include_station:
                demand_code = ["S", station_str]
            else:
                demand_code = []
            demand_code = demand_code + ["P", product_str, "C", 
                cloud_algo_str, "L", local_algo_str, "R", reducer_str]
        elif format_as=="dict":
            if include_station:
                demand_code = {"S": station_str}
            else:
                demand_code = {}
            demand_code = {**demand_code, **{"P": product_str, "C": 
                cloud_algo_str, "L": local_algo_str, "R": reducer_str}}
        else:
            raise ValueError("'Invalid value in 'format_as'.")
        
        return demand_code
    
    # Interprets a demand code and returns its parts as a dictionary.
    # If the input is a list, validates it and convert to a dict.
    # If it is a dictionary already, it is validated and returned equal.
    # Only works for a single code, not for a list of codes.
    @staticmethod
    def unfold_demand_code(demand_code):
        """
        Takes a demand code, reads its parts, validates them and returns them 
        arranged as a dict. The input may be a string, a list or a dictionary. 
        For the latter, it is only a matter of validation.
        The format of the returned dict for an input 'P314C15L3R1' is:
            {'P': 314, 'C': 15, 'L': 3, 'R': 1}
            where P stands for Product, C for cloud algorithm, L for local 
            algorithm, and R for Reducer, whereas the numbers are the codes 
            identifying the product, cloud algorithm etc.
        
        Parameters
        ----------
        
            demand_code: str or list or dict describing the demand code.
        
        Returns
        -------
        
            dict.

        """
        
        ref_labels = ["S","P","C","L","R"]
        required = [1,2,3,4]
        
        # For strings, convert them to a list. It will be validated along the
        # next code blocks.
        if type(demand_code) is str:
            # For compatibility, accept the format from the first GEEDaR
            if len(demand_code) == 8 and demand_code.isnumeric():
                demand_code = ("P" + demand_code[:3] + "C" + demand_code[3:5]
                    + "L" + demand_code[5:7] + "R" + demand_code[7:])            
            if len(demand_code) < len(required) * 2:
                raise ValueError("Too short string in 'demand_code'.")
            if demand_code[0].isdigit():
                raise ValueError("'demand_code' can't begin with a number.")
            if not demand_code[-1].isdigit():
                raise ValueError("'demand_code' must end with a number.")
            to_list = [demand_code[0]]
            for i in range(1, len(demand_code)):
                if demand_code[i].isdigit() == demand_code[i-1].isdigit():
                    # It's a continuation.
                    to_list[-1] = to_list[-1] + demand_code[i]
                else:
                    # It's a new code element, then add a new element to the
                    # list. 
                    to_list = to_list + [demand_code[i]]
                    # If the last element was a number, convert it.
                    if demand_code[i-1].isdigit():
                        to_list[-2] = int(to_list[-2])
            # Convert the last numeric element.
            to_list[-1] = int(to_list[-1])
            demand_code = to_list
        
        # If demand_code (original or converted) is a list, validates it and 
        # convert it to a dict (for validation below).
        if type(demand_code) is list:
            if len(demand_code) % 2 != 0:
                raise ValueError("'demand_code' should "
                    + "have an even number of elements (keys and values).")
            tmp_dict = dict()
            for i in range(0, len(demand_code), 2):
                if not (type(demand_code[i]) is str 
                        and type(demand_code[i + 1]) is int):
                    raise ValueError("Invalid configuration of element types "
                        + "in 'demand_code'.")
                tmp_dict[demand_code[i]] = demand_code[i + 1]
            demand_code = tmp_dict
        
        # If it is a dict, check for required and invalid keys.
        if type(demand_code) is dict:
            if not all(ref_labels[i] in demand_code for i in required):
                raise ValueError("One or more required keys are missing in "
                    + "the 'demand_code' argument.")
            if not all(k in ref_labels for k in demand_code):
                raise ValueError("One or more invalid keys in "
                    + "the 'demand_code' argument.")
        # Invalid type.
        else:
            raise TypeError("'demand_code' must be a dict, a list or a str.")
        
        return demand_code
    
    # Another name for the method above.
    split_codes = unfold_demand_code
    
    # The opposite of the above: join separate codes into a demand code.
    @staticmethod
    def join_codes(codes):
        """
        Gets a demand code in the form of a list or dict and join its parts 
        in a single string.

        Parameters
        ----------
        
            codes: list or dict with the letters and integers identifying each 
                component of the demand code. The letter may be ommited as 
                long as the numbers are in the right order: station (optional, 
                letter 'S'), product ('P'), cloud algorithm ('C'), local 
                algorithm ('L') and reducer ('R).

        Returns
        -------
        
            str.

        """
        
        ref_labels = ["S","P","C","L","R"]
        if type(codes) is list:
            if len(codes) not in [4, 5, 8, 10]:
                raise ValueError("'codes' may have 4-5 items for lists with "
                    + "only int values or 8/10 for lists with interleaved "
                    + "str and int values.")
            if ((len(codes) <= 5 
                    and not all(type(item).__name__ in ["int", "int64"] 
                    for item in codes))
                    or (len(codes) >= 8 
                    and not (all(isinstance(codes[i], str) 
                    for i in range(len(codes)) if i % 2 == 0) 
                    and all(type(codes[i]).__name__ in ["int", "int64"] 
                    for i in range(len(codes)) if i % 2 == 1)))):
                raise TypeError("'codes' should contain 4-5 integers "
                    + "or 8-10 interleaved str and int values.")            
            if len(codes) == 4:
                return ("P" + str(codes[0]) + "C" + str(codes[1]) + "L"
                    + str(codes[2]) + "R" + str(codes[3]))
            elif len(codes) == 5:
                return ("S" + str(codes[0]) + "P" + str(codes[1]) + "C" 
                    + str(codes[2]) + "L" + str(codes[3]) + "R" 
                    + str(codes[4]))
            else:
                if len(codes) == 8:
                    offset = 2
                else:
                    offset = 0
                for i in range(offset, len(codes), 2):
                    if codes[i] != ref_labels[i/2]:
                        raise ValueError("Could not recognize the labels in "
                            + "the list.")
                return "".join([str(item) for item in codes])
                
        elif type(codes) is dict:
            if not all(label in ref_labels for label in [*codes]):
                raise ValueError("Could not recognize the labels in the dict.")
            
            if "S" not in codes:
                return ("P" + str(codes["P"]) + "C" + str(codes["C"]) + "L"
                    + str(codes["L"]) + "R" + str(codes["R"]))
            else:
                return ("S" + str(codes["S"]) + "P" + str(codes["P"]) + "C" 
                    + str(codes["C"]) + "L" + str(codes["L"]) + "R" 
                    + str(codes["R"]))
        return
            
    # When a single reducer is applied, GEE does not append the reducer suffix 
    # to the band name. This method does it for standardization sake.
    def _append_stat_suffix(self, data_dict):
        result_bands = self._result_bands
        new_data_dict = data_dict
        if len(self.reducer.stat_suffix) == 1:
            suffix = self.reducer.stat_suffix[0]
            for k1 in data_dict:
                for k2 in [*data_dict[k1]]:
                    if k2 in result_bands:
                        new_data_dict[k1][
                            k2 + "_" + suffix] = new_data_dict[k1].pop(k2)
        return new_data_dict
    
    # Adds to the dictionary columns named as "common bands" (blue, green...) 
    # by duplicating the values corresponding to the data columns.
    def _add_common_band_cols(self, data_dict):
        suffixes = self.reducer.stat_suffix
        common_bands_dict = self._product.get_data_bands()
        
        all_bands_dict = common_bands_dict.copy()
        # Create new data dict with the common bands (correctly ordered).
        new_data_dict = dict()
        for date_str in data_dict:
            new_data_dict[date_str] = dict()
            for common_band in [*all_bands_dict]:
                orig_band = all_bands_dict[common_band]
                for suffix in suffixes:
                    orig_colname = orig_band + "_" + suffix
                    common_colname = common_band + "_" + suffix
                    new_data_dict[date_str][common_colname] = math.nan
                    if orig_colname in data_dict[date_str]:
                        new_data_dict[date_str][
                            common_colname] = data_dict[date_str][orig_colname]
            # Now reinsert the keys added by the algorithm (bands and vars).
            input_keys = [*data_dict[date_str]]
            for key in input_keys:
                if key not in new_data_dict[date_str]:
                    new_data_dict[date_str][key] = data_dict[date_str][key]
                        
        return new_data_dict
    
    # Order the columns of a dataframe following the order of a list or of the 
    # keys of a dict.
    @staticmethod
    def _order_cols(df, ref):
        if type(ref) is dict:
            ref = [*ref]
        # Keep only the columns present in df.
        ref = [c for c in ref if c in df.columns]
        # Move the unmatched columns from df to the end.
        lastcols = [c for c in df.columns if c not in ref]
        df = df[ref + lastcols]
        return df
    
    # Converts a dictionary in the format returned by the 'retrieve' function 
    # in the method '_reduce_img_group' into a Pandas data frame.
    @staticmethod
    def _dict_to_df(data_dict):
        dates = [*data_dict]
        # For an empty dict, return an empty data frame.
        if(len(dates) == 0):
            return pandas.DataFrame()
        
        df = pandas.DataFrame.from_dict(data_dict, orient="index")
        df.index = pandas.to_datetime(df.index)
        
        return df
    
    # Appends data to the '_time_series' attribute.
    def _extend_time_series(self, data):
        if type(data) is dict:
            df2 = Demand._dict_to_df(data)
        elif isinstance(data, pandas.DataFrame):
            df2 = data            
        else:
            raise TypeError("'data' must be a dictionary in the format "
                + "returned by the 'retrieve' function in the method "
                + "'_reduce_img_group' or a Pandas data frame.")
        
        if isinstance(self._time_series, pandas.DataFrame):
            df1 = self._time_series
            xdf = df1.combine_first(df2)
            ordered_col_list = list(df1.columns)
        else:
            xdf = df2
            ordered_col_list = list(df2.columns)
        
        # Order the data frame as in the "common bands dictionary". It only 
        # works because the previously applied method '_add_common_band_cols' 
        # returns a dict correctly ordered.
        xdf = Demand._order_cols(xdf, ordered_col_list)
        
        # Insert the "fixed columns" (if not yet there).
        station_code = self._virtual_station.station_code
        demand_code = self.get_demand_code(format_as="str", 
            include_station=False)
        reserved_columns = self._reserved_columns
        if reserved_columns[1] not in xdf.columns:
            xdf.insert(0, reserved_columns[1], demand_code)
        else:    
            xdf.loc[xdf.index >= pandas.to_datetime(self._start_date), 
                reserved_columns[1]] = demand_code
        if reserved_columns[0] not in xdf.columns:
            xdf.insert(0, reserved_columns[0], station_code)
        else:
            xdf.loc[xdf.index >= pandas.to_datetime(self._start_date), 
                reserved_columns[0]] = station_code
        
        self._time_series = xdf

    # Requests the reduction of a partial image collection (a group of images)
    # and retrieves the resulting time series from the server.
    # This function is central in the processing flow.
    def _reduce_img_group(self, cur_group):
        
        cur_group = cur_group - 1 # Range starts in zero.
        
        all_dates = self._product.available_dates
        n_all_dates = len(all_dates)
        group_size = self._group_size        
        date_inds = range(cur_group * group_size, min(cur_group * group_size 
            + group_size, n_all_dates))
        date_list = [all_dates[i] for i in date_inds]
        n_dates = len(date_list)
                
        product = self._product
        virtual_station = self._virtual_station
        aoi = virtual_station.aoi
        cloud_algo = self._cloud_algo
        cloud_algo_options = self._cloud_algo_options
        ee_reducer = self.reducer.ee_reducer
        ref_band = product.scale_ref_band        
        result_bands = self._result_bands
        export_vars = self._export_vars

        def retrieve(image_collection):
            def get_vars(image, result):
                var_list = ee.List(export_vars)
                return ee.Dictionary(result).set(ee.Image(image).get(
                    "img_datetime"), ee.Dictionary.fromLists(var_list, 
                    var_list.map(lambda var_name: ee.Image(image).get(
                    ee.String(var_name)))))   
            
            def reduce_bands(image, result):
                scale = image.select(ref_band).projection().nominalScale().min(
                    ee.Geometry(aoi).area().sqrt())
                return ee.Dictionary(result).set(ee.Image(image).get(
                    "img_datetime"), ee.Image(image).reduceRegion(
                    reducer = ee.Reducer(ee_reducer), geometry = aoi, 
                    scale = scale, bestEffort = True, tileScale = tile_scale))
            
            # Combine the dictionaries of parameters and of band values.
            def combine_dicts(key, sub_dict):
                return ee.Dictionary(sub_dict).combine(
                    ee.Dictionary(vars_dict).get(key))
            
            # Combine variable and band data.
            first = ee.Dictionary()
            vars_dict = ee.Dictionary(
                ee.ImageCollection(image_collection).iterate(get_vars, first))
            bands_dict = ee.Dictionary(
                ee.ImageCollection(image_collection).iterate(reduce_bands, 
                first))
            combined_dict = bands_dict.map(combine_dicts)
        
            return combined_dict.getInfo()

        # Download the data. Try up to three times. Increase 'tileScale' if
        # output computation is too large. If server response is taking too
        # long, try to process images one by one.
        
        data_dict = dict()
        cur_date_index = 0
        cur_group_size = len(date_inds) #group_size
        while cur_date_index < n_dates:
            retrieved_dict = None
            tile_scale = 2
            n_timeouts = 0
            n_attempt = 1
            while n_attempt <= 3 and n_timeouts < 2:
                cur_date_list = date_list[
                    cur_date_index:(cur_date_index + cur_group_size)]
                # Restrict the collection to the current group (dates).
                image_collection = product.collection.filter(
                    ee.Filter.inList("img_datetime", cur_date_list))
                # Apply the cloud algorithm.
                image_collection = cloud_algo.apply(product, virtual_station, 
                    image_collection, cloud_algo_options)
                if type(image_collection).__name__ != "ImageCollection":
                    raise Exception("The application of the cloud algorithm "
                        + "failed before reduction.")
                # Remove non-result bands.
                image_collection = image_collection.select(result_bands)
            
                # If retrying, warn it.
                if n_attempt > 1: #  and n_attempt <= 3
                    print("Trying again...")
                if len(cur_date_list) > 3:
                    short_date_list = ("['" + cur_date_list[0] + "' - '" + 
                        cur_date_list[-1] + "']")
                else:
                    short_date_list = cur_date_list                    
                print("\nRetrieving data for date(s) " 
                    + str(date_inds[cur_date_index] + 1) + "-" 
                    + str(date_inds[cur_date_index + cur_group_size - 1] + 1) 
                    + "/" + str(n_all_dates) + ": " 
                    + str(short_date_list) + "...")
                try:
                    relax_demand = False
                    retrieved_dict = func_timeout(360, retrieve, 
                        args=(image_collection,))
                except FunctionTimedOut:
                    print("No response from the server.")
                    n_timeouts += 1
                except ee.ee_exception.EEException as e:
                    print(f"EEException caught: {e}")
                    if (str(e)[:40] == 
                            "Output of image computation is too large"):
                        relax_demand = True
                    elif str(e) == "Computation timed out.":
                        n_timeouts += 1
                        relax_demand = True
                except Exception as e:
                    print(f"A general exception was caught: {e}")
                else:
                    print("Done.")
                    break
                finally:
                    if relax_demand:
                        if cur_group_size > 1:
                            cur_group_size = max(1, 
                                math.floor(cur_group_size / 2))
                            print("The image group size will be halved. ", 
                                end="")
                        tile_scale = tile_scale * 2 
                        print("The 'tileScale' param. will be increased to " 
                            + str(tile_scale) + " for the next attempt." )
                    n_attempt += 1
                    if(n_attempt > 3):
                        print("This was the last attempt.")
            
            if n_timeouts >= 2 and cur_group_size > 1:
                print("Now trying to process images one by one...")
                cur_group_size = 1
            else:
                cur_date_index += cur_group_size
                
            if type(retrieved_dict) is dict:
                data_dict = {**data_dict, **retrieved_dict}
        
        # Add stats id suffix to column names.
        data_dict = self._append_stat_suffix(data_dict)
        # Add columns named as "common bands" (blue, green, red...). This is 
        # done by duplicating the corresponding original columns.
        data_dict = self._add_common_band_cols(data_dict)
        
        # Save time series.
        self._extend_time_series(data_dict)
        
        # Return info on the reduction request and its results.
        reduction_info = {
            "image_group": cur_group + 1,
            "start_date": min(date_list),
            "end_date": max(date_list),
            "n_dates": n_dates,
            "date_list": date_list,
            "reduced_bands": result_bands,
            "additional_vars": export_vars,
            "data_dict": data_dict
        }
        return reduction_info
        
    # Applies an algorithm to the reflectance time series stored in the 
    # attribute '_time_series' to produce a time series of estimated values 
    # for one or more variables of interest. The results are appended to the
    # same data frame stored in '_time_series'.
    def _apply_local_algorithm(self, date_list=None):
        if not isinstance(self._time_series, pandas.DataFrame):
            print("No dataframe in '_time_series'.")
            return
        if len(self._time_series) == 0:
            print("No records in '_time_series'.")
            return
        
        df = self._time_series
        if len(df) == 0:
            print("The time series is empty.")
            return
        
        if date_list is not None:
            if len(date_list) == 0:
                print("No date provided for application of the local "
                    + "algorithm.")
                return
            filtered_df = df[df.index.isin(pandas.to_datetime(date_list))]
            if len(filtered_df) == 0:
                print("No records left after filtering time series by date.")
                return
        else:
            filtered_df = df
        
        # Set the stat. suffixes of the reducer as an attribute of the 
        # dataframe, so the local algorithm object can check for the need to 
        # handle list of values resulting from ee.Reducer.list().
        filtered_df.attrs["stat_suffixes"] = self._reducer.stat_suffix
        
        # Set options.
        options = self._local_algo_options
        if options is None:
            options = dict()
        options["metadata"] = {
            "product_code": self._product.product_code
        }
        
        # Apply the local algo.
        returned_df = self._local_algo.apply(filtered_df, options)
        
        if len(returned_df) == 0:
            print("No data was returned from the local algorithm.")
            return
        if len(returned_df.columns) == len(filtered_df.columns):
            return
        
        # Add the result columns to the return data frame.
        result_df = filtered_df.combine_first(returned_df)
        
        result_info = {
            "input_date_list": date_list,
            "result_df": result_df
        }
        
        # Save time series.
        self._extend_time_series(returned_df)
        
        return result_info
    
    # Arranges the columns of the result dataframe in the best order: fixed 
    # cols + export_vars + export_bands + data_bands.
    def _sort_ts_cols(self):
        ts_df = self._time_series
        if ts_df is None:
            return
        ts_cols = list(ts_df.columns)
        reserved_cols = self._reserved_columns
        non_reserved_cols = [c for c in ts_cols if c not in reserved_cols]
        export_vars = self._cloud_algo.export_vars
        export_bands = self._cloud_algo.export_bands
        data_bands = list(self._product.get_data_bands())
        refs = export_vars + export_bands + data_bands
        local_algo_cols = []
        export_var_cols = []
        export_band_cols = []
        data_cols = []
        for col in non_reserved_cols:
            col_parts = col.split("_")
            if len(col_parts) > 1:
                col_wo_suffix = "_".join(col_parts[:-1])
            else:
                col_wo_suffix = col
            
            if not any(c in [col, col_wo_suffix] for c in refs):
                local_algo_cols.append(col)
            elif col in export_vars:
                export_var_cols.append(col)
            elif any(c == col_wo_suffix for c in export_bands):
                export_band_cols.append(col)
            else:
                data_cols.append(col)
        
        sorted_cols = (reserved_cols + local_algo_cols + export_var_cols 
            + export_band_cols + data_cols)
        self._time_series = ts_df[sorted_cols]
    
    # Executes the demand partially, only for the next image group to be 
    # processed. 
    def next_group(self):
        """
        Executes the demand for the current group of images. Stepwise 
        execution allows for the user to retrieve partial results.
        
        Returns
        -------
        
            A dict with info on the results of the application of the reducer 
            (and by extension of the cloud algorithm) and of the local 
            algorithm, if any.
        
        """
        
        cur_group = self._current_image_group
        n_groups = self._n_image_groups
        
        if n_groups == 0:
            print("No data to process.")
            return
        
        if cur_group > n_groups:
            print("Demand execution has already ended (all image groups "
                + "were processed).")
            return

        # Reduction.        
        try:
            reduction_info = self._reduce_img_group(cur_group)
        except Exception as e:
            print(e)
            print("No data was retrieved.")
            return            
        if len(reduction_info["data_dict"].keys()) == 0:
            print("No data returned.")
            return
        
        # Local algorithm application.
        if (self._local_algo is None 
                or len(self._local_algo.required_bands) == 0):
            local_algo_info = None
        else:
            try:
                local_algo_info = self._apply_local_algorithm()
            except Exception as e:
                print(e)
                print("Failed to apply the local algorithm to the previously "
                    + "downloaded time series.")
                local_algo_info = None
        
        # Combined results.
        result_dict = {
            cur_group: {
                "reduction_info": reduction_info,
                "local_algo_info": local_algo_info
            }
        }
        
        # If execution is finished, sort result columns.
        if cur_group >= n_groups:
            self._sort_ts_cols()
            
        # Save?
        if self._auto_save:
            if self._save_type == "csv":
                self.save_to_csv(self._save_to, overwrite=True, append=False)
            elif self._save_type == "db":
                self.save_to_db(check_db=False)
            
        # Increase group counter.
        self._current_image_group = cur_group + 1
                
        return result_dict
    
    # Executes the demand at once, sending successive requests to the server. 
    def execute(self):
        """
        Executes the demand for data retrieval: applies the cloud processing
        algorithm, "reduces" the image collection to a time series through 
        the calculation of one or more statistics (median, mean etc.), 
        retrieves the result from the server, and applies the local algorithm 
        to the donwloaded time series.
                
        """

        n_groups = self._n_image_groups
        
        # Applies the reducer (and donwload the series).
        result_dict = {"time_series": pandas.DataFrame()}
        if self._n_image_groups == 0:
            print("No data to process.")
        else:
            for cur_group in range(n_groups):
                cur_dict = self.next_group()
                if cur_dict is None:
                    return
                result_dict = {**result_dict, **cur_dict}
            result_dict["time_series"] = self._time_series

        return result_dict
    
    # Returns the time series reduced to single representative values for each 
    # band and variable on each date. It is useful only when no reducer was 
    # applied on the data demand, resulting in a list of pixel values at each 
    # cell of the time series dataframe.
    def reduce_time_series(self, reducer_name=_list_reducer):
        """
        Takes the time series dataframe stored in this Demand object and 
        reduces list of pixel values to a single representative value. Options 
        of reducer are 'mean' or 'median'. It is applicable only when the 
        data demand does not uses a reducer, that is, when the reducer code is 
        zero. For other cases, when the reduction is applied on the server, 
        the time series dataframe will have no data as list and this method 
        will return None.

        Parameters
        ----------
        reducer_name : 'mean' or 'median' (str).

        Returns
        -------
        Dataframe or None.

        """
        
        if reducer_name != "mean":
            reducer_name = "median"

        if self._time_series is None:
            return
        
        df = self._time_series.copy()
        df_cols = [*df.columns]
        df_nondata_cols = self._reserved_columns
        df_data_cols = [c for c in df_cols if c not in df_nondata_cols]
        
        cols_with_lists = []
        for col in df_data_cols:
            substrs = col.split("_")
            if substrs[-1] == "list":
                cols_with_lists.append(col)
            elif df[col].dtype == "object":
                if any(isinstance(val, list) for val in df[col]):
                    cols_with_lists.append(col)
        if len(cols_with_lists) == 0:
            return
        
        # Reduce values and rename columns.
        for col in cols_with_lists:
            df[col] = [reduce_list(lst, reducer=reducer_name, na=pandas.NA) 
                if isinstance(lst, list) else lst for lst in df[col]]
            if "_list" in col:
                new_col_name = col.replace("list", reducer_name)
            else:
                new_col_name = col + "_" + reducer_name
            df.rename(columns = {col: new_col_name}, inplace = True)
        
        return df
    
    # Saves the time series to a CSV file.
    def save_to_csv(self, filepath=None, overwrite=False, append=False):       
        """
        Saves the data resulting from the demand processing to a CSV file. If 
        a file name was not provided at instantiation through the parameter 
        'save_to', it must be provided now.
        You may append the current results to a file with previous results, in 
        which case you must use 'append=True' and the file content must be 
        compatible with the content of time series stored here.

        Parameters
        ----------

            filepath: the path of the target file (None or str, optional)
            overwrite: if a file with the same name exists, must it be 
                overwritten? (bool, defaults to False, optional).
            append: if a file with the same name exists, must the data be 
                appended to it? (bool, defaults to False, optional).

        Returns
        -------
        
            A dataframe corresponding to the content of the target file (it
            may be identical to this demand' data or a combination of such 
            data with the previous data in the target file).

        """
        
        if filepath is None:
            filepath = self._save_to
        if type(filepath) is not str:
            raise TypeError("'filepath' must be a str.")
        if type(overwrite) is not bool:
            raise TypeError("'overwrite' must be a bool.")
        # If there isn't time series yet, warn and return.
        if self._time_series is None:
            print("No time series to save.")
            return
        df_to_save = self.time_series
        
        # If the target file already exists, import it if it must be appended 
        # (overwrite=False).
        prime_df = df_to_save.drop(df_to_save.index)
        if os.path.exists(filepath):
            if not overwrite:
                raise FileExistsError("The file pointed by 'filepath' already "
                    + "exists.")
            if append:
                tmp_df = pandas.read_csv(filepath)
                tmp_df = self._validate_time_series(tmp_df)
                #tmp_df = self._load_data_from_csv(filepath)
                if (list(tmp_df.columns).sort() 
                        != list(df_to_save.columns).sort()):
                    print("An 'append' operation will be tried, but because "
                        + "the columns in '_time_series' and in the following "
                        + "file are not the same, unexpected results may be "
                        + "produced: '" + filepath + "'.")
                # Do not append repeated data.
                if len(tmp_df) > 0:
                    prime_df = tmp_df
                    latest_date = max(prime_df.index)
                    if len(latest_date) == 1:
                        df_to_save = df_to_save.loc[latest_date:]
                
        # Concatanate the pre-existing (if any) and the new data frames.
        df_to_save = pandas.concat([prime_df, df_to_save])
        # Save:
        df_to_save.to_csv(filepath, index=True, index_label=self._dt_col_name)
        
        return df_to_save   
    
    # Saves the time series data in the target database.
    # 'source_id' is the id that shoud be used to identify GEEDaR as the source
    # of the data being saved to the database. There is a column in the
    # acquisiton table for the source id.
    # 'data_status' is the default value to be used for the corresponding 
    # column in the 'data' table.
    def save_to_db(self, source_id=None, data_status=None, check_db=True):
        """
        Saves the data resulting from the demand processing into the target 
        database, as pointed by the GeedarDB object passed as argument at 
        instantiation to the parameter 'save_to'.

        Parameters
        ----------

            source_id: the id of the data source that may be required by the 
                target database (None or int, optional).
            data_status: the status id of the data to be saved, if the target 
                database distinguishes status level (ex: approved, provisional 
                etc.) (None or int, optional).
            check_db: before trying to save, should it be checked if this 
                demand's content matches the corresponding record in the 
                database (demand id, product code etc.)? (bool, defaults to 
                True, optional).
                DESCRIPTION. The default is True.

        Returns
        -------
        
            A dict containing dataframes with the data saved to each table of 
                the target database.

        """
        
        geedar_db = self._save_to
        # Check database consistency.
        if check_db:
            self._check_db()     
        db_names = geedar_db._db_names
        db_values = geedar_db._db_values
        # Enforce the use of the real column names in the target database.
        cur_colnames_attr = geedar_db._use_real_col_names
        geedar_db.use_real_col_names = True
        
        demand_id = self._demand_id
        
        # source_id
        if source_id is not None:
            if not str(source_id).isnumeric():
                raise TypeError("'source_id' should be an integer.")
            source_id = int(source_id)
        else:
            if self._source_id is not None:
                source_id = self._source_id
            elif "acquisition.source_id" in [*db_values]:
                source_id = db_values["acquisition.source_id"]
            else:
                raise ValueError("A value of 'source_id' must be passed to "
                    + "the function or at instantiation of the Demand or of "
                    + "the GeedarDB object.")
            
        # data_status
        if data_status is not None:
            if not str(data_status).isnumeric():
                raise TypeError("'data_status' should be an integer.")
            data_status = int(data_status)
        else:
            if self._data_status is not None:
                data_status = self._data_status
            elif "data.status" in [*db_values]:
                data_status = db_values["data.status"]
            else:
                raise ValueError("A value of 'data_status' must be passed to "
                    + "the function or at instantiation of the Demand or of "
                    + "the GeedarDB object.")
        
        # Create a dict with separate data frames corresponding to the target 
        # tables in the database. The dict may be used as a report of the 
        # saved data.
        save_dict = dict()
        for table_key in ["acquisition", "data", "result"]:
            save_dict[table_key] = pandas.DataFrame(columns=[
                db_names[table_key][c].upper() for c in [*db_names[table_key]] 
                if (c[0] != "_" and len(db_names[table_key][c]) > 0)])
                
        # Check data to save.
        no_data = True
        if self._time_series is not None:
            df = self._time_series.copy()
            # Filter the dataframe, keeping only the records with dates later 
            # than the last saved record in the database.
            if len(df) > 0:
                last_date_str = self._get_last_db_date()
                if last_date_str is None:
                    no_data = False
                else:
                    df = df.loc[last_date_str:]
                    if len(df) > 0:
                        no_data = False
        if no_data:
            print("No data to save.")
            return save_dict        
        
        # Columns of the time series data frame        
        df_cols = [*df.columns]
        df_nondata_cols = self._reserved_columns
        if df_nondata_cols is None or df_nondata_cols == "":
            df_nondata_cols = []        
        df_data_cols = [c for c in df_cols if c not in df_nondata_cols]
        
        # If the data contains values of type list (if reducer #0 was used),
        # it must be reduced before sent to the target database, unless other 
        # reducers have also been applied - then the columns with lists are 
        # simply discarded.
        stat_suffixes = self._reducer.stat_suffix.copy() # a list
        
        changed_df = False
        if stat_suffixes == ["list"]:
            df = self.reduce_time_series(self._list_reducer)
            stat_suffixes = [self._list_reducer]
            changed_df = True
        elif "list" in stat_suffixes:
            cols_with_lists = []
            for col in df_data_cols:
                substrs = col.split("_")
                if substrs[-1] == "list":
                    cols_with_lists.append(col)
                elif df[col].dtype == "object":
                    if any(isinstance(val, list) for val in df[col]):
                        cols_with_lists.append(col)
            df.drop(columns=[cols_with_lists], inplace=True)
            stat_suffixes = [s for s in stat_suffixes if s != "list"]
            changed_df = True
        
        if changed_df:
            df_cols = [*df.columns]
            df_data_cols = [c for c in df_cols if c not in df_nondata_cols]
            if len(df_data_cols) == 0:
                raise ValueError("After trying to reduce lists inside "
                    + "the dataframe, no valid column remained.")
            if len(df.dropna(subset = df_data_cols, how = "all")) == 0:
                raise ValueError("After trying to reduce lists inside "
                    + "the dataframe, no valid row remained.")
        
        # Columns of the target tables
        station_id_col = db_names["station"]["primary_key"].upper()
        demand_id_col = db_names["demand"]["primary_key"].upper()
        demand_st_fk_col = db_names["demand"]["fkey_station"].upper()
        demand_prod_fk_col = db_names["demand"]["fkey_product"].upper()
        product_id_col = db_names["product"]["primary_key"].upper()
        product_inst_fk_col = db_names["product"]["fkey_instrument"].upper()
        stat_id_col = db_names["stats"]["primary_key"].upper()
        stat_suffix_col = db_names["stats"]["suffix"].upper()
        var_id_col = db_names["variable"]["primary_key"].upper()
        var_name_col = db_names["variable"]["name"].upper()
        var_unit_col = db_names["variable"]["unit"].upper()
        var_label_col = db_names["variable"]["label"].upper()
        
        acq_id_col = db_names["acquisition"]["primary_key"].upper()
        acq_demand_fkey_col = db_names["acquisition"]["fkey_demand"].upper()
        acq_st_fkey_col = db_names["acquisition"]["fkey_station"].upper()
        acq_inst_fkey_col = db_names["acquisition"]["fkey_instrument"].upper()
        acq_source_col = db_names["acquisition"]["source_id"].upper()
        acq_date_col = db_names["acquisition"]["date"].upper()
        acq_time_col = db_names["acquisition"]["time"].upper()
        acq_proc_col = db_names["acquisition"]["proc_dt"].upper()
        acq_qflag_col = db_names["acquisition"]["qual_flag"].upper()
        data_id_col = db_names["data"]["primary_key"].upper()
        data_acq_fkey_col = db_names["data"]["fkey_acquisition"].upper()
        data_var_fkey_col = db_names["data"]["fkey_variable"].upper()
        data_status_col = db_names["data"]["status"].upper()
        result_data_fkey_col = db_names["result"]["fkey_data"].upper()
        result_stat_fkey_col = db_names["result"]["fkey_stats"].upper()
        result_value_col = db_names["result"]["value"].upper()
        
        # Retrieve the demand record from the database.
        demand_record = geedar_db.get_table("demand", 
            where_str=(demand_id_col + " = " + str(demand_id)))        
        demand_record.columns = [c.upper() for c in [*demand_record.columns]]
        
        # Retrieve the station record from the database.
        station_id = int(demand_record[demand_st_fk_col][0])
        station_record = geedar_db.get_table("station", 
            where_str=(station_id_col + " = " + str(station_id)))
        station_record.columns = [c.upper() for c in [*station_record.columns]]
        
        # Product code.
        product_code = int(demand_record[demand_prod_fk_col][0])
               
        # Get the instrument id from the product record.
        product_record = geedar_db.get_table("product", 
            where_str=(product_id_col + " = " + str(product_code)))
        product_record.columns = [c.upper() for c in [*product_record.columns]]
        inst_id = int(product_record[product_inst_fk_col][0])
        
        # Get the statistical parameter id.
        if "none" not in stat_suffixes:
            stat_suffixes.append("none")
        stat_id_dict = dict()
        stat_table = geedar_db.get_table("stats")
        stat_table.columns = [c.upper() for c in [*stat_table.columns]]
        stat_table.dropna(axis=0, subset=stat_suffix_col, inplace=True)
        for stat_suffix in stat_suffixes:
            stat_id = [stat_table.loc[i, stat_id_col] 
               for i in stat_table.index if stat_table.loc[i, 
               stat_suffix_col].upper() == stat_suffix.upper()]
            stat_id = stat_id[0]
            stat_id_dict[stat_suffix.upper()] = stat_id
        
        # Build a dictionary to relate data columns to variables and stats.
        # The variable records in the database are required.
        
        var_table = geedar_db.get_table("variable")
        var_table.columns = [c.upper() for c in [*var_table.columns]]
        var_names = list(var_table[var_name_col])
        var_col_stat = dict()
        export_vars = self._cloud_algo.export_vars
        for col in df_data_cols:
            substrs = col.split("_")
            # Exported variables or local algorithm results.
            if col in export_vars or len(substrs) == 1 or col in var_names:
                col_stat_suffix = "none".upper()
                col_var_name = col
            else:
                col_stat_suffix = substrs[-1].upper()
                col_var_name = "_".join(substrs[:-1])
            if col_stat_suffix not in [*stat_id_dict]:
                raise ValueError("The statistical suffix of the column '" 
                    + col + "' in the time series dataframe was not "
                    + "recognized: '" + col_stat_suffix + "'.")
            
            if col_var_name not in [*var_col_stat]:
                var_col_stat[col_var_name] = {
                    "col_list": [],
                    "stat_suffix": [],
                    "stat_id": []
                }
            var_col_stat[col_var_name]["col_list"].append(col)
            var_col_stat[col_var_name]["stat_suffix"].append(col_stat_suffix)
            var_col_stat[col_var_name]["stat_id"].append(
                stat_id_dict[col_stat_suffix])
            # Now the var id must be found.
            var_id = [var_table.loc[i, var_id_col] for i in var_table.index 
                if var_table.loc[i, var_name_col].upper() == 
                col_var_name.upper()]
            if len(var_id) == 0:
                # No corresponding variable in the database. A new record 
                # must be created.
                last_id = int(var_table[var_id_col].max())
                var_new_record = pandas.DataFrame(columns=var_table.columns)
                var_new_record.loc[0, var_id_col] = last_id + 1
                var_new_record.loc[0, var_name_col] = col_var_name
                var_new_record.loc[0, var_unit_col] = ""
                var_new_record.loc[0, var_label_col] = col_var_name
                r = geedar_db.save_to_table("variable", var_new_record)
                if r != 1:
                    raise Exception("Failed to insert a new record for the " 
                        + "variable '" + col_var_name + "'.")
                #var_id = last_id + 1
                var_id = geedar_db.get_last_id("variable")
            else:    
                var_id = var_id[0]
            var_col_stat[col_var_name]["var_id"] = var_id
                
        # Unfold each row in the data frame into the target tables and save
        # one by one.

        acq_df = save_dict["acquisition"]
        data_df = save_dict["data"]
        value_df = save_dict["result"]
        
        # First, get preexisting measurement records from the database to 
        # avoid duplication.
        acq_recs = geedar_db.get_table("acquisition", 
            where_str = acq_demand_fkey_col + " = " + str(demand_id))
        acq_recs.columns = [c.upper() for c in [*acq_recs.columns]]
        
        # Get the last primary key values.
        last_acq_id = geedar_db.get_last_id("acquisition")
        if not isinstance(last_acq_id, int):
            raise ValueError("'get_last_id' did not return an integer value "
                + "for the last primary value of the table corresponding to "
                + "the key 'acquisition'.")
        
        last_data_id = geedar_db.get_last_id("data")
        if not isinstance(last_data_id, int):
            raise ValueError("'get_last_id' did not return an integer value "
                + "for the last primary value of the table corresponding to "
                + "the key 'data'.")
        
        acq_row = 0
        data_row = 0
        val_row = 0
        progress_step = 100 / len(df)
        cur_progress = 0
        print("[" + (" " * 100) + "]", end="")
        for df_ind in df.index:
            
            # Acquisiton table.
            
            # Look for a preexisting record.
            datestr = df_ind.strftime("%Y-%m-%d")
            timestr = df_ind.strftime("1900-01-01 %H:%M:%S")
            filt_acq_recs = acq_recs[
                (acq_recs[acq_date_col].astype(str) == datestr) & 
                (acq_recs[acq_time_col].astype(str) == timestr) & 
                (acq_recs[acq_source_col] == source_id)]
            if len(filt_acq_recs) > 0:
                # A record exists. No row will be inserted in the dataframe.
                acq_id = filt_acq_recs[acq_id_col].iloc[-1]
            else:
                # A record must be saved. Insert new row in the dataframe.
                acq_id = last_acq_id + 1
                acq_df.loc[acq_row, acq_id_col] = acq_id
                acq_df.loc[acq_row, acq_demand_fkey_col] = demand_id
                acq_df.loc[acq_row, acq_st_fkey_col] = station_id
                acq_df.loc[acq_row, acq_inst_fkey_col] = inst_id
                acq_df.loc[acq_row, acq_source_col] = source_id
                acq_df.loc[acq_row, acq_date_col] = datestr
                acq_df.loc[acq_row, acq_time_col] = timestr
                acq_df.loc[acq_row, acq_proc_col] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S")
                if "qual_flag" in [*df.columns]:
                    qual_flag = df.loc[df_ind, "qual_flag"]
                else:
                    qual_flag = math.nan
                acq_df.loc[acq_row, acq_qflag_col] = qual_flag
                # Save acquisiton record.
                r = geedar_db.save_to_table("acquisition", 
                    acq_df.loc[[acq_row],:], 
                    avoid_duplication=False)
                if r != 1:
                    print("")
                    print(acq_df.loc[[acq_row],:])
                    raise Exception("Failed to insert a new record for the " 
                        + "acquisiton data above.")
                # Get the id of the new record, which may not be the id used 
                # above (if there is an identity restriction).
                last_acq_id = geedar_db.get_last_id("acquisition")
                acq_id = last_acq_id
                acq_df.loc[acq_row, acq_id_col] = acq_id
                acq_row += 1
                #print("Saved acquisition record #" + str(acq_id) + ".")
            
            # Data table.

            # Look for a preexisting record.
            data_recs = geedar_db.get_table("data", 
                where_str = data_acq_fkey_col + " = " + str(acq_id))
            data_recs.columns = [c.upper() for c in [*data_recs.columns]]
            
            for var_name in [*var_col_stat]:                
                var_id = var_col_stat[var_name]["var_id"]
                filt_data_recs = data_recs[
                    (data_recs[data_var_fkey_col] == var_id)]
                if len(filt_data_recs) > 0:
                    # A record already exists.
                    data_id = filt_data_recs[data_id_col].iloc[-1]
                else:
                    # A record must be saved.
                    data_id = last_data_id + 1
                    data_df.loc[data_row, data_id_col] = data_id
                    data_df.loc[data_row, data_acq_fkey_col] = acq_id
                    data_df.loc[data_row, data_var_fkey_col] = var_id
                    data_df.loc[data_row, data_status_col] = data_status
                    # Save data record.
                    r = geedar_db.save_to_table("data", 
                        data_df.loc[[data_row],:], 
                        avoid_duplication=False)
                    if r != 1:
                        print("")
                        print(data_df.loc[[data_row],:])
                        raise Exception("Failed to insert a new record for " 
                            + "the data above.")
                    last_data_id = geedar_db.get_last_id("data")
                    data_id = last_data_id
                    data_df.loc[data_row, data_id_col] = data_id
                    data_row += 1
                    #print("Saved data record #" + str(data_id) + ".")
                
                # Value (result).

                # Look for a preexisting record.
                val_recs = geedar_db.get_table("result", 
                    where_str = result_data_fkey_col + " = " + str(data_id))
                val_recs.columns = [c.upper() for c in [*val_recs.columns]]
                
                for col_ind in range(len(var_col_stat[var_name]["col_list"])):
                    col = var_col_stat[var_name]["col_list"][col_ind]
                    stat_id = var_col_stat[var_name]["stat_id"][col_ind]                                        
                    filt_val_recs = val_recs[
                        (val_recs[result_stat_fkey_col] == stat_id)]
                    if len(filt_val_recs) == 0:
                        # A record must be saved.
                        value_df.loc[val_row, result_data_fkey_col] = data_id
                        value_df.loc[val_row, result_stat_fkey_col] = stat_id
                        value_df.loc[val_row, result_value_col] = df.loc[
                            df_ind, col]
                        # Save result (value) record.
                        r = geedar_db.save_to_table("result", 
                            value_df.loc[[val_row],:], 
                            avoid_duplication=False)
                        if r != 1:
                            print("")
                            print(value_df.loc[[val_row],:])
                            raise Exception("Failed to insert a new record " 
                                + "for the result data above.")
                        val_row += 1                                

            cur_progress += progress_step
            print("\r[" + ("." * math.floor(cur_progress)) 
                + (" " * (100 - math.floor(cur_progress))) + "]", end="")

        print("\r[" + ("." * 100) + "]")
        no_data_saved = True
        if len(acq_df) > 0:
            no_data_saved = False
            print(str(len(acq_df)) + " acquisition records saved (#" 
                + str(min(acq_df[acq_id_col])) + "-" 
                + str(max(acq_df[acq_id_col])) + ").")
        if len(data_df) > 0:
            no_data_saved = False
            print(str(len(data_df)) + " data records saved (#" 
                + str(min(data_df[data_id_col])) + "-" 
                + str(max(data_df[data_id_col])) + ").")
        if len(value_df) > 0:
            no_data_saved = False
            print(str(len(value_df)) + " result (value) records saved.")
        if no_data_saved:
            print("No data needed to be saved.")

        # Undo the change regarding the use of the real column names.        
        geedar_db.use_real_col_names = cur_colnames_attr
        
        # Rename the dictionary keys to the real table names.
        acq_table_full_name = (db_names["acquisition"]["_table_name"] 
            if db_names["acquisition"]["_schema"] == "" 
            else db_names["acquisition"]["_schema"] 
            + "." + db_names["acquisition"]["_table_name"])
        data_table_full_name = (db_names["data"]["_table_name"] 
            if db_names["data"]["_schema"] == "" 
            else db_names["data"]["_schema"] 
            + "." + db_names["data"]["_table_name"])
        result_table_full_name = (db_names["result"]["_table_name"] 
            if db_names["result"]["_schema"] == "" 
            else db_names["result"]["_schema"] 
            + "." + db_names["result"]["_table_name"])
        save_dict[acq_table_full_name] = save_dict.pop("acquisition")
        save_dict[data_table_full_name] = save_dict.pop("data")
        save_dict[result_table_full_name] = save_dict.pop("result")        
        
        return save_dict
    

#%% GeedarDB class

class GeedarDB:
    """
    The GeedarDB class is intended to be a bridge between GEEDaR and the
    target database.
    
    Instantiation
    -------------
    
        conn_dict: a dictionary with two elements: 
            connect_string: a string in a format accepted by the sqlalchemy 
                package describing the database connection.
            connect_args: a dictionary with additional arguments to be passed 
                to the database engine.
        db_names: a dictionary with the names of the database tables and 
            columns. The keys of the dictionary are predefined.
        db_values: a dictionary with the default values for specific columns.
            The columns must be identified in the form "table_key.col_key",
            where "table_key" and "col_key" correspond to keys in 'db_names'.
        use_real_col_names: if True, the column names of the retrieved data
            frames will be the "real" names in the target database; if
            False (the default), the keys of the db_names dict will be used 
            instead, which will work as standard naming.
    
    Attributes
    ----------
    
    These attributes come from the instantiation parameters:
        conn_dict: dict
        db_names: dict
        db_values: dict
    
    And this property is set in instantiation:
        use_real_col_names: indicates if the dataframes resulting from 
            database queries should have columns with names equal to the 
            columns of the database tables (True) or equal to the keys of 
            the 'db_names' dict (False).
    
    Methods
    -------
    
        connect
        disconnect
        create_geedar_tables
        get_table
        get_basic_tables
        get_demands
        get_data
        get_last_id
        get_last_date
        get_query
        save_to_table
        import_table
        import_demands
    
    """

    # The 'conn_dict' dictionary must have these keys:
    _req_keys_in_conn_dict = ["connect_string", "connect_args"]
    
    # Default credentials.
    _default_credentials = {
        "data_source_name": "",
        "user_id": "",
        "password": "",
        "file_name": "geedar.db"
    }
    
    # Default connection type.
    _default_conn_type = "sqlite"
    
    # Default connection dictionary.
    _default_conn_dict = {
        "connect_string": "sqlite:///" + _default_credentials["file_name"],
        "connect_args": {}
    }

    # The table and column names in the target database must be provided 
    # through the 'db_names' dictionary. The default values are:    
    _default_db_names = {
        "station": {
            "_schema": "",
            "_table_name": "Station",
            "primary_key": "StationId",
            "code": "StationCode",
            "name": "StationName",
            "lat": "StationLatitude",
            "long": "StationLongitude"
        },
        "instrument": {
            "_schema": "",
            "_table_name": "Instrument",
            "primary_key": "InstrumentId",
            "name": "InstrumentName",
            "mission": "InstrumentSatName",
            "revisit": "InstrumentRevisit",
            "description": "InstrumentDescription",
            "label": "InstrumentLabel"
        },
        "variable": {
            "_schema": "",
            "_table_name": "Variable",
            "primary_key": "VariableId",
            "unit": "VariableUnit",
            "name": "VariableName",
            "description": "VariableDescription",
            "label": "VariableLabel"
        },
        "product": {
            "_schema": "",
            "_table_name": "Product",
            "primary_key": "ProductCode",
            "fkey_instrument": "ProductInstrumentId",
            "name": "ProductName",
            "description": "ProductDescription"
        },
        "cloud_algo": {
            "_schema": "",
            "_table_name": "CloudAlgo",
            "primary_key": "CloudAlgoCode",
            "name": "CloudAlgoName",
            "description": "CloudAlgoDescription",
            "ref": "CloudAlgoReference"
        },
        "local_algo": {
            "_schema": "",
            "_table_name": "LocalAlgo",
            "primary_key": "LocalAlgoCode",
            "name": "LocalAlgoName",
            "description": "LocalAlgoDescription",
            "ref": "LocalAlgoReference"
        },
        "reducer": {
            "_schema": "",
            "_table_name": "Reducer",
            "primary_key": "ReducerCode",
            "description": "ReducerDescription"
        },
        "demand": {
            "_schema": "",
            "_table_name": "Demand",
            "primary_key": "DemandId",
            "fkey_station": "DemandStationId",
            "fkey_product": "DemandProductCode",
            "fkey_cloud_algo": "DemandCloudAlgoCode",
            "fkey_local_algo": "DemandLocalAlgoCode",
            "fkey_reducer": "DemandReducerCode",
            "status": "DemandStatusCode",
            "start_date": "DemandStartDate",
            "end_date": "DemandEndDate",
            "aoi_mode": "DemandAoiMode",
            "aoi_radius": "DemandAoiRadius",
            "kml_path": "DemandKmlPath"
        },
        "acquisition": {
            "_schema": "",
            "_table_name": "Measurement",
            "primary_key": "MeasurementId",
            "fkey_station": "MeasurementStationId",
            "fkey_demand": "MeasurementDemandId",
            "fkey_instrument": "MeasurementInstrumentId",
            "date": "MeasurementDate",
            "time": "MeasurementTime",
            "proc_dt": "MeasurementProcessingDateTime",
            "source_id": "MeasurementSourceId",
            "qual_flag": "MeasurementQualFlagCode"
        },
        "data": {
            "_schema": "",
            "_table_name": "Data",
            "primary_key": "DataId",
            "fkey_acquisition": "DataMeasurementId",
            "fkey_variable": "DataVariableId",
            "status": "DataStatusCode"
        },
        "result": {
            "_schema": "",
            "_table_name": "Result",
            "primary_key": "",
            "fkey_data": "ResultDataId",
            "fkey_stats": "ResultStatsCode",
            "value": "ResultValue"
        },
        "stats": {
            "_schema": "",
            "_table_name": "Stats",
            "primary_key": "StatsCode",
            "name": "StatsName",
            "label": "StatsLabel",
            "suffix": "StatsSuffix"
        },
        "application": {
            "_schema": "",
            "_table_name": "Application",
            "primary_key": "ApplicationId",
            "attribute": "ApplicationAttribute",
            "value": "ApplicationValue"
        }
    }

    # And 'db_names' has sub-dictionaries which must contain, each one, 
    # the following keys, at least:
    _reserved_keys = ["_schema", "_table_name", "primary_key"]
    
    # Default 'db_values': columns with predefined values.
    _default_db_values = {
        "acquisition.source_id": 1,
        "data.status": 1
    }
        
    def __init__(self, conn_dict=_default_conn_dict, 
            db_names=_default_db_names, 
            db_values=_default_db_values, 
            use_real_col_names=False):
        
        # Check 'db_names'.
        
        if not isinstance(db_names, dict):
            raise TypeError("'db_names' must be a dict.")
        
        default_db_names = self._default_db_names
        if not all(k in db_names for k in default_db_names):
            raise ValueError("The dictionary 'db_names' does not contain "
                + "all the required keys: " 
                + str([k for k in default_db_names 
                if k not in db_names]))

        for k1, v1 in default_db_names.items():
            if not isinstance(db_names[k1], dict):
                raise TypeError("A dictionary was expected in the key '"
                    + k1 + "' of 'db_names'.")
            if not all(k2 in db_names[k1] for k2 in v1):
                raise ValueError("The sub-dictionary '" + k1 + "' in "
                    + "'db_names' does not contain all the required keys: " 
                    + str([k2 for k2 in v1 if k2 not in db_names[k1]]))
            if not all(isinstance(db_names[k1][k2], str) 
                    for k2 in db_names[k1]):
                raise TypeError("All the values in the subdictionary '" + k1
                    + "' should be a string.")
       
        # Check 'db_values'.
        if not isinstance(db_values, dict):
            raise TypeError("'db_values' must be a dict.")
        
        # Check 'conn_dict'.
        if not isinstance(conn_dict, dict):
            raise TypeError("'conn_dict' must be a dict.")
        req_keys_in_conn_dict = self._req_keys_in_conn_dict
        if not all(k in req_keys_in_conn_dict for k in conn_dict):
            raise ValueError("Invalid content of the sub-dictionary "
                + "'conn_dict' in the input dictionary. It should have the "
                + "keys: " + str(req_keys_in_conn_dict) + ".")
        if not isinstance(conn_dict["connect_string"], str):
            raise TypeError("'connect_string' in 'conn_dict' must be a "
                + "str.")
        if conn_dict["connect_args"] is None:
            conn_dict["connect_args"] = dict()
        if not isinstance(conn_dict["connect_args"], dict):
            raise TypeError("'connect_args' in 'conn_dict' must be a "
                + "dict.")
        
        # Check 'use_real_col_names'.
        if not isinstance(use_real_col_names, bool):
            raise TypeError("'use_real_col_names' should be a boolean.")
        
        # If the connection parameters are empty, use the default.
        if (len(conn_dict["connect_args"]) == 0 and 
                len(conn_dict["connect_string"]) == 0):
            self._conn_dict = self._default_conn_dict.copy()
        else:
            self._conn_dict = conn_dict.copy()
        
        self._db_names = db_names.copy()
        self._db_values = db_values.copy()
        self._use_real_col_names = use_real_col_names
        
        # Set the attribute '_conn_type', which may be ODBC or SQLite.
        self._set_conn_type()
        
        # Set the query attributes:
        # - self._queries stores a dict with the specific select queries.
        # - self._demand_view stores the extended demand query.
        # - self._data_view stores the extended data query.
        # - self._table_creation_dict stores the snippets for creation of the 
        #   required GEEDaR tables.
        self._update_queries()            
            
        # Here are the connection attributes, which will store the connection 
        # object and the connection state upon execution of the method 
        # 'connect'.
        self._conn = None
        self._connected = False
    
    @property
    def conn_dict(self):
        return self._conn_dict
    @property
    def db_names(self):
        return self._db_names
    @property
    def db_values(self):
        return self._db_values
    @property
    def is_conn_valid(self):
        return self._is_conn_valid()
    @property
    def use_real_col_names(self):
        return self._is_conn_valid()
    @use_real_col_names.setter
    def use_real_col_names(self, new_value=True):
        if not isinstance(new_value, bool):
            raise TypeError("'use_real_col_names' requires a boolean value.")            
        old_value = self._use_real_col_names
        self._use_real_col_names = new_value
        # If necessary, update the queries.
        if new_value != old_value:
            self._update_queries()
    
    # Pickle cannot handle the database connhection object, so it has to be 
    # removed for picke to work.
    def __getstate__(self):
        state = self.__dict__.copy()
        state['_conn'] = None
        return state    
    
    # When pickle restores the object, it is tried to restore the connection.
    def __setstate__(self, state):
        self.__dict__.update(state)
        if self._connected:
            conn_dict = self._conn_dict        
            try:
                self._conn = create_engine(conn_dict["connect_string"],
                    connect_args=conn_dict["connect_args"]).connect()
            except Exception as e:
                print(e)
                print("Database connection could not be restablished.")
                self._connected = False
        
    # Sets '_conn_type' attr.
    def _set_conn_type(self):
        conn_str = self._conn_dict["connect_string"].lower()
        if "sqlite" in conn_str:
            self._conn_type = "sqlite"
        elif "odbc" in conn_str:
            self._conn_type = "odbc"
        else:
            self._conn_type = "unknown"
    
    # Takes a "prequery", that is, a query with provisional table and column 
    # names, and replaces the provisional names by the real names in the target 
    # database. For the replacement to work, the provisional names must be
    # tagged with a leading and a trailing % symbol and must correspond to
    # keys of the db_names dictionary (self._db_names).
    # Instead of replacing the provisional names by the "real" names, they can
    # be replaced by the keys of db_names, which are always the same and serve,
    # therefore, as standard names. In such case, the expression indicated by
    # 'alias_placeholder' is replaced by the key names.
    def _replace_db_names(self, prequery, alias_placeholder=" as keyname", 
            composite_col_name=True, default_db_names=False):
        query = prequery
        if default_db_names:
            db_names = self._default_db_names
        else:
            db_names = self._db_names
        use_real_col_names = self._use_real_col_names
        
        if use_real_col_names:
             query = query.replace(alias_placeholder, "")
        
        for k1 in db_names:
            schema = db_names[k1]["_schema"]
            if schema == "":
                schema_str = ""
            else:
                schema_str = schema + "."
            table_name = db_names[k1]["_table_name"]

            table_var = "%" + k1 + "._table_name%" 
            query = query.replace(table_var, schema_str + table_name)
            
            for col_key in [k2 for k2 in db_names[k1] 
                    if k2[0] != "_"]:
                col_var = "%" + k1 + "." + col_key + "%"
                colname = db_names[k1][col_key]
                if composite_col_name:
                    colname_str = table_name + "." + colname
                else:
                    colname_str = colname
                if not use_real_col_names:
                    query = query.replace(col_var + alias_placeholder, 
                        colname_str + " as '" + k1 + "." 
                        + col_key + "'")
                query = query.replace(col_var, colname_str)
        return query      
    
    # Builds the query strings for retrieval of records from each table.
    def _build_select_queries(self):
        self._queries = dict()
        min_keys_in_db_names = self._reserved_keys
        db_names = self._db_names
        use_real_col_names = self._use_real_col_names
        
        for k1 in db_names:
            if db_names[k1]["_schema"] == "":
                schema_str = ""
            else:
                schema_str = db_names[k1]["_schema"] + "."
            table_query = "Select "
            # Start with the primary key (if any).
            if len(db_names[k1]["primary_key"]) > 0:
                if use_real_col_names:
                    alias_str = ""
                else:
                    alias_str = " as '" + k1 + "." + "primary_key'"
                table_query = table_query + (db_names[k1]["_table_name"] + "." 
                    + db_names[k1]["primary_key"] + alias_str + ", ")
            # Add the other columns (ignoring the special keys).
            for k2 in db_names[k1]:
                if k2 not in min_keys_in_db_names:
                    if len(db_names[k1][k2]) == 0:
                        raise ValueError("The string in the key " + k2 
                            + " of the subdictionary " + k1 
                            + " in 'db_names' is empty.")
                    if use_real_col_names:
                        alias_str = ""
                    else:
                        alias_str = " as '" + k1 + "." + k2 + "'"
                    table_query = (table_query + db_names[k1]["_table_name"] 
                        + "." + db_names[k1][k2]) + alias_str + ", "
            # Remove the comma and complete the table query.
            table_query = (table_query[0:-2] + " from " 
                + schema_str + db_names[k1]["_table_name"])
            self._queries[k1] = table_query

    # Builds the extended demand query, combining the demand table with the 
    # related ones (station, product, cloud algorithm etc.).
    def _build_demand_view(self):
        prequery = """
            Select
            	%demand.primary_key% as keyname, %demand.status% as keyname, 
            	%station.primary_key% as keyname, %station.code% as keyname, %station.name% as keyname, %station.lat% as keyname, %station.long% as keyname,
            	%product.primary_key% as keyname, %product.name% as keyname, %product.description% as keyname,
            	%instrument.primary_key% as keyname, %instrument.name% as keyname, %instrument.mission% as keyname, %instrument.revisit% as keyname, %instrument.description% as keyname, %instrument.label% as keyname,
            	%cloud_algo.primary_key% as keyname, %cloud_algo.name% as keyname, %cloud_algo.description% as keyname, %cloud_algo.ref% as keyname,
            	%local_algo.primary_key% as keyname, %local_algo.name% as keyname, %local_algo.description% as keyname, %local_algo.ref% as keyname, 
            	%reducer.primary_key% as keyname, %reducer.description% as keyname,
            	%demand.start_date% as keyname, %demand.end_date% as keyname, %demand.aoi_mode% as keyname, %demand.aoi_radius% as keyname, %demand.kml_path% as keyname
            From
            	%demand._table_name%
            	Join %station._table_name% on %station.primary_key% = %demand.fkey_station%
            	Join %product._table_name% on %product.primary_key% = %demand.fkey_product%
            	Join %instrument._table_name% on %instrument.primary_key% = %product.fkey_instrument%
            	Join %cloud_algo._table_name% on %cloud_algo.primary_key% = %demand.fkey_cloud_algo%
            	Join %local_algo._table_name% on %local_algo.primary_key% = %demand.fkey_local_algo%
            	Join %reducer._table_name% on %reducer.primary_key% = %demand.fkey_reducer%
        """
        self._demand_view = self._replace_db_names(prequery, 
            alias_placeholder=" as keyname", 
            composite_col_name=True, default_db_names=False)

    # Builds the data query, combining the tables of demand, station, 
    # acquisition, data, result and stats.
    def _build_data_view(self):
        prequery = """
            Select
            	%demand.primary_key% as keyname, %demand.fkey_station% as keyname, %demand.fkey_product% as keyname, %demand.fkey_cloud_algo% as keyname, %demand.fkey_local_algo% as keyname, %demand.fkey_reducer% as keyname,
            	%acquisition.primary_key% as keyname, %acquisition.fkey_instrument% as keyname, %acquisition.date% as keyname, %acquisition.time% as keyname, %acquisition.source_id% as keyname, %acquisition.qual_flag% as keyname,
            	%data.primary_key% as keyname, %data.status% as keyname,
            	%variable.primary_key% as keyname, %variable.name% as keyname, %variable.description% as keyname, %variable.label% as keyname,
            	%stats.primary_key% as keyname, %stats.name% as keyname, %stats.suffix% as keyname,
            	%result.value% as keyname
            From
            	%demand._table_name%
            	Join %acquisition._table_name% on %acquisition.fkey_demand% = %demand.primary_key%
            	Join %data._table_name% on %data.fkey_acquisition% = %acquisition.primary_key%
            	Join %variable._table_name% on %variable.primary_key% = %data.fkey_variable%
            	Join %result._table_name% on %result.fkey_data% = %data.primary_key%
            	Join %stats._table_name% on %stats.primary_key% = %result.fkey_stats%
            Where
                1=1
            Order by
                %acquisition.date%, %data.primary_key%
        """
        self._data_view = self._replace_db_names(prequery, 
            alias_placeholder=" as keyname", 
            composite_col_name=True, default_db_names=False)
    
    # Builds the script for creation of the minimum set of tables required to
    # run GEEDaR in database mode.
    def _build_table_creation_dict(self):
        creation_dict = {
            "application": """
                CREATE TABLE %application._table_name% (
                	%application.primary_key% INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%application.attribute%   VARCHAR(50) NOT NULL,
                	%application.value%       VARCHAR(255) NOT NULL
                )
            """,
            "station": """
                CREATE TABLE %station._table_name% (
                	%station.primary_key% INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%station.code%        VARCHAR(13) NOT NULL,
                	%station.name%        VARCHAR(100) NOT NULL,
                	%station.lat%         DECIMAL(7,5) NOT NULL,
                	%station.long%        DECIMAL(8,5) NOT NULL
                );
                CREATE UNIQUE INDEX IX_Station_Code ON %station._table_name% (%station.code%)
            """,
            "instrument": """
                CREATE TABLE %instrument._table_name% (
                	%instrument.primary_key% INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%instrument.name%        VARCHAR(50),
                	%instrument.description% VARCHAR(255),
                	%instrument.mission%     VARCHAR(50),
                	%instrument.label%       VARCHAR(50),
                	%instrument.revisit%     INT DEFAULT 1 NOT NULL
                )            
            """,
            "variable": """
                CREATE TABLE %variable._table_name% (
                	%variable.primary_key% INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%variable.name%        VARCHAR(50),
                	%variable.label%       VARCHAR(50),
                	%variable.description% VARCHAR(100)
                )            
            """,
            "acquisition": """
                CREATE TABLE %acquisition._table_name% (
                	%acquisition.primary_key%     INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%acquisition.fkey_station%    INT NOT NULL,
                	%acquisition.fkey_demand%     INT,
                	%acquisition.fkey_instrument% INT NOT NULL,
                	%acquisition.date%            DATE NOT NULL,
                	%acquisition.time%            TIMESTAMP,
                	%acquisition.source_id%       SMALLINT,
                	%acquisition.proc_dt%         TIMESTAMP,
                	%acquisition.qual_flag%       SMALLINT DEFAULT 2,
                	CONSTRAINT FK_Acquisition_Instrument FOREIGN KEY (%acquisition.fkey_instrument%) REFERENCES %instrument._table_name% (%instrument.primary_key%),
                	CONSTRAINT FK_Acquisition_Station FOREIGN KEY (%acquisition.fkey_station%) REFERENCES %station._table_name% (%station.primary_key%) ON DELETE CASCADE
                );
                CREATE INDEX IX_Acquisition_StationId ON %acquisition._table_name% (%acquisition.fkey_station%);
                CREATE INDEX IX_Acquisition_InstId ON %acquisition._table_name% (%acquisition.fkey_instrument%)                
            """,
            "data": """
                CREATE TABLE %data._table_name% (
                	%data.primary_key%      INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%data.fkey_variable%    INT NOT NULL,
                	%data.fkey_acquisition% INT NOT NULL,
                	%data.status%           SMALLINT DEFAULT 2,
                	CONSTRAINT FK_Data_Variable FOREIGN KEY (%data.fkey_variable%) REFERENCES %variable._table_name% (%variable.primary_key%),
                	CONSTRAINT FK_Data_Acquisition FOREIGN KEY (%data.fkey_acquisition%) REFERENCES %acquisition._table_name% (%acquisition.primary_key%) ON DELETE CASCADE
                );                
                CREATE INDEX IX_Data_AcquisitionId ON %data._table_name% (%data.fkey_acquisition%);
                CREATE INDEX IX_Data_VariableId ON %data._table_name% (%data.fkey_variable%)            
            """,
            "stats": """
                CREATE TABLE %stats._table_name% (
                	%stats.primary_key% SMALLINT NOT NULL,
                	%stats.name%        VARCHAR(50) NOT NULL,
                	%stats.label%       VARCHAR(50),
                	%stats.suffix%      VARCHAR(25),
                	CONSTRAINT PK_Stats PRIMARY KEY (%stats.primary_key%)
                )
            """,
            "result": """
                CREATE TABLE %result._table_name% (
                	%result.fkey_data%  INT NOT NULL,
                	%result.fkey_stats% SMALLINT NOT NULL,
                	%result.value%      DECIMAL(18,3),
                	CONSTRAINT PK_Result PRIMARY KEY (%result.fkey_data%, %result.fkey_stats%),
                	CONSTRAINT FK_Result_Stats FOREIGN KEY (%result.fkey_stats%) REFERENCES %stats._table_name% (%stats.primary_key%),
                	CONSTRAINT FK_Result_Data FOREIGN KEY (%result.fkey_data%) REFERENCES %data._table_name% (%data.primary_key%) ON DELETE CASCADE
                )
            """,
            "product": """
                CREATE TABLE %product._table_name% (
                	%product.primary_key%     INT NOT NULL,
                	%product.fkey_instrument% INT NOT NULL,
                	%product.name%            VARCHAR(50),
                	%product.description%     VARCHAR(255),
                	CONSTRAINT PK_Product PRIMARY KEY (%product.primary_key%),
                	CONSTRAINT FK_Product_Instrument FOREIGN KEY (%product.fkey_instrument%) REFERENCES %instrument._table_name% (%instrument.primary_key%)
                )            
            """,
            "cloud_algo": """
                CREATE TABLE %cloud_algo._table_name% (
                	%cloud_algo.primary_key% INT NOT NULL,
                	%cloud_algo.name%        VARCHAR (50),
                	%cloud_algo.description% VARCHAR (100),
                	%cloud_algo.ref%         VARCHAR (255),
                	CONSTRAINT PK_Cloud_Algo PRIMARY KEY (%cloud_algo.primary_key%)
                )
            """,
            "local_algo": """
                CREATE TABLE %local_algo._table_name% (
                	%local_algo.primary_key% INT NOT NULL,
                	%local_algo.name%        VARCHAR (50),
                	%local_algo.description% VARCHAR (100),
                	%local_algo.ref%         VARCHAR (255),
                	CONSTRAINT PK_Local_Algo PRIMARY KEY (%local_algo.primary_key%)
                )
            """,
            "reducer": """
                CREATE TABLE %reducer._table_name% (
                	%reducer.primary_key% INT NOT NULL,
                	%reducer.description% VARCHAR (50),
                	CONSTRAINT PK_Reducer PRIMARY KEY (%reducer.primary_key%)
                )
            """,
            "demand": """
                CREATE TABLE %demand._table_name% (
                	%demand.primary_key%     INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                	%demand.fkey_station%    INT NOT NULL,
                	%demand.status%          SMALLINT,
                	%demand.fkey_product%    INT NOT NULL,
                	%demand.fkey_cloud_algo% INT NOT NULL,
                	%demand.fkey_local_algo% INT NOT NULL,
                	%demand.fkey_reducer%    INT NOT NULL,
                	%demand.start_date%      TIMESTAMP,
                	%demand.end_date%        TIMESTAMP,
                	%demand.aoi_mode%        SMALLINT,
                	%demand.aoi_radius%      DECIMAL(7,5),
                	%demand.kml_path%        VARCHAR(255),
                	CONSTRAINT FK_Demand_Station FOREIGN KEY (%demand.fkey_station%) REFERENCES %station._table_name% (%station.primary_key%)
                )
            """
        }
                
        conn_type = self._conn_type
        if conn_type == "sqlite":
            # For SQLite, primary key + autoincrement is defined differently.
            for k in [*creation_dict]:
                creation_dict[k] = creation_dict[k].replace(
                    "INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", 
                    "INTEGER PRIMARY KEY AUTOINCREMENT")
        
        # Replace varlike names by the real names of the target database.
        for k in [*creation_dict]:
            creation_dict[k] = self._replace_db_names(creation_dict[k], 
                composite_col_name=False, default_db_names=False)
        
        self._table_creation_dict = creation_dict

    # Updates the query-storing attributes.
    def _update_queries(self):
        self._build_select_queries()
        self._build_demand_view()
        self._build_data_view()
        self._build_table_creation_dict()

    # Returns a dictionary with two lists: the db_names' keys of the GEEDaR 
    # tables that are present and the ones that are missing in the target 
    # database.
    def _check_geedar_tables(self):
        db_names = self._db_names
        conn = self._conn
        inspector = inspect(conn)
        
        present_list = []
        missing_list = []
        for k in [*db_names]:
            schema = db_names[k]["_schema"]
            table = db_names[k]["_table_name"]
            if inspector.has_table(table, schema=schema):
                present_list.append(k)
            else:
                missing_list.append(k)
        
        return {"present": present_list, "missing": missing_list}
                        
    # Checks the connection.
    def _is_conn_valid(self):
        conn = self._conn
        if conn is None:
            return False
        elif type(conn).__name__ != "Connection":
            return False
        elif not conn.closed:
            return True
        else:
            return False
    
    # Connects to the database as configured in 'conn_dict'. If it is a new 
    # database, the missing GEEDaR tables will be created.
    def connect(self):
        """
        Establishes a connection to the target database. Upon connection, the 
        required GEEDaR tables are searched in the database. If one or more 
        are missing, it is offered to create them.
        
        The method has no parameters and returns None.

        """
        
        if self._connected:
            return
        print("Connecting to the database...", end=" ")
        conn_dict = self._conn_dict        
        self._conn = create_engine(conn_dict["connect_string"],
            connect_args=conn_dict["connect_args"]).connect()
        
        # Check the GEEDaR tables.
        
        missing_tables = self._check_geedar_tables()["missing"]
        if len(missing_tables) > 0:
            print("\nThe following GEEDaR tables are missing in the target "
                + "database: " + str(missing_tables))
            r = input("Proceed to create them? y/[n]: ")
            if r.lower() == "y":
                self.create_geedar_tables(missing_tables)
            else:
                sys.exit("GEEDaR tables creation aborted by the user. "
                    + "Without them, database mode will not work.")
        else:
            print("Ok.")
            self._connected = True

    # Disconnects from the database.
    def disconnect(self):
        """
        Closes the connection to the target database.
        
        The method has no parameters and returns None.

        """
        
        self._conn.close()
        self._connected = False
        print("The database connection was closed.")
    
    # Creates the tables required by GEEDaR that are missing in the target
    # database. It takes an optional list of db_names' keys.
    def create_geedar_tables(self, table_keys=[*_default_db_names]):
        """
        Creates, in the target database, the tables required by GEEDaR that 
        are missing.

        Returns None.

        Parameters
        ----------
        
            table_keys: the list of ids to be used as a guide for the table 
                checking. It defaults to all the keys (list of str, optional).
        
        """
        
        if not isinstance(table_keys, list):
            raise TypeError("'table_keys' must be a list.")
        if not all(k in [*self._default_db_names] for k in table_keys):
            raise ValueError("'table_keys' must contain only strings "
                + "corresponding to the keys of the 'db_names' dict.")
            
        creation_dict = self._table_creation_dict
        
        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()
        conn = self._conn
        
        # The creation must be in the right order, following the order of the 
        # keys in 'creation_dict'.
        for k in [*creation_dict]:
            if k not in table_keys:
                continue
            statements = creation_dict[k].split(";")
            for statement in statements:
                conn.execute(text(statement))
        conn.commit()
        
        db_names = self._db_names
        table_names = [db_names[k]["_table_name"] for k in table_keys]
        print("These GEEDaR tables were created: " + str(table_names))
    
    # Check if the argument identifying the table is valid.
    # It returns table_key because if the real table name is provided, then it 
    # is transformed into the corresponding key in db_names.
    def _check_table_key(self, table_key):
        if not isinstance(table_key, str):
            raise TypeError("'table_key' must be a str.")
        db_names = self._db_names
        if table_key not in db_names:
            for k in db_names:
                if table_key in [db_names[k]["_table_name"],
                        db_names[k]["_schema"] + "." 
                        + db_names[k]["_table_name"],
                        "%" + k + "._table_name" + "%"]:
                    table_key = k
                    break
            if table_key not in db_names:
                raise ValueError("'table_key' does not match any key in "
                    + "'db_names'. Accepted values: " + str([*db_names]) + ".")
        return table_key
    
    # Gets the contents of a table.
    def get_table(self, table_key, where_str=""):
        """
        Retrieves the records of the table specified in 'table_key'.
        Valid values are: ['station', 'instrument', 'variable', 'product', 
        'cloud_algo', 'local_algo', 'reducer', 'demand', 'acquisition', 'data', 
        'result', 'stats', 'application']
        
        Parameters
        ----------
        
            table_key: the table id (str).
            where_str: a where statement to filter the retrieved records (str).

        Returns
        -------
            
            Pandas data frame.

        """

        query_dict = self._queries        
        table_key = self._check_table_key(table_key)
        if table_key not in query_dict:
            raise ValueError("Invalid value in 'table_key'. Valid ones are: " 
                + str([*query_dict]))
        if not isinstance(where_str, str):
            raise TypeError("'where_str' must be a str.")
        
        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()

        if where_str.replace(" ", "") != "":
            where_str = self._replace_db_names(where_str)
            where_str = " where " + where_str.upper().replace("WHERE", "")
            
        df = pandas.read_sql_query(query_dict[table_key] + where_str, 
            self._conn)
        
        return df

    # Returns a dictionary with data from basic tables of the database: demand, 
    # variable, instrument, product, cloud algorithm etc.
    def get_basic_tables(self):
        """
        Returns a dictionary with dataframes contaning the records retrieved 
        from the basic GEEDaR tables, that is, those corresponding to these 
        keys: ["variable", "instrument", "stats", "product", "cloud_algo", 
        "local_algo", "demand"].

        Returns
        -------
        
            dict.

        """
        
        table_keys = ["variable", "instrument", "stats", "product", 
            "cloud_algo", "local_algo", "demand"]
        
        tables_dict = dict()
        for table_key in table_keys:
            tables_dict[table_key] = self.get_table(table_key)
        
        return tables_dict       

    # An extended query on Demand, including the related tables which describe
    # a demand for data retrieval from GEE.
    def get_demands(self, update_start_date=False):
        """
        Retuns a Pandas data frame with the records of the Demand table joined 
        with the records of the related tables (those for stations, products, 
        cloud algorithms etc.).
        
        Parameters
        ----------
        
            update_start_date: if True, the returned start_dates will be the 
                next date after the latest measurement record in the database 
                (bool, optional).
        
        Returns
        -------
        
            dataframe.
        
        """
        
        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()

        df = pandas.read_sql_query(self._demand_view, self._conn)
        if update_start_date:
            if self._use_real_col_names:
                db_names = self._db_names
                demand_id_col = db_names["demand"]["primary_key"]
                start_date_col = db_names["demand"]["start_date"]
                end_date_col = db_names["demand"]["start_date"]
            else:
                demand_id_col = "demand.primary_key"
                start_date_col = "demand.start_date"
                end_date_col = "demand.end_date"
            rows_to_remove = []
            for i in df.index:
                demand_id = df.loc[i, demand_id_col]
                last_date = self.get_last_date(demand_id)
                if last_date is not None:
                    start_date = last_date + timedelta(days=1)
                    df.loc[i, start_date_col] = start_date.strftime("%Y-%m-%d")
                    # Check end_date.
                    end_date = df.loc[i, end_date_col]
                    if not pandas.isna(end_date):
                        if (pandas.to_datetime(end_date) < 
                                pandas.to_datetime(start_date)):
                            rows_to_remove.append(i)
            # Remove rows with demands already finished?
            if len(rows_to_remove) > 0:
                df.drop(rows_to_remove, inplace=True)
        
        return df
    
    # Get the pre-existing data records for a given demand.
    def get_data(self, demand_id=None):
        """
        Returns a pandas dataframe with the combination of the records in the 
        tables related to the data acquisition.
        
        Parameters
        ----------
        
            demand_id: the record id of the demand to which the data is linked
                (None or int, optional).
        
        Returns
        -------
        
            dataframe.
        
        """
        
        db_names = self._db_names
        
        if demand_id is not None:
            if isinstance(demand_id, list):
                where_str = (db_names["demand"]["primary_key"] 
                    + " in " + list_to_sql(demand_id))
            else:
                if not isinstance(demand_id, int):
                    raise TypeError("'demand_id' must be an int.")
                where_str = (db_names["demand"]["primary_key"] 
                    + " = " + str(demand_id))
        else:
             where_str = "1=1"
        
        # Extends the data query with a where clause directed to the demand id
        # passed as argument (if any).
        querystr = self._data_view.replace("1=1", where_str)
            
        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()
        
        df = pandas.read_sql_query(querystr, self._conn)
        
        return df
    
    # Gets the maximum value of the primary key for a given table.
    def get_last_id(self, table_key):
        """
        Gets the last record id of the table corresponding to 'table_key'.

        Parameters
        ----------
        
            table_key: the identification of the table (str). Valid values are: 
                ['station', 'instrument', 'variable', 'product', 'cloud_algo', 
                'local_algo', 'reducer', 'demand', 'acquisition', 'data', 
                'result', 'stats', 'application']

        Returns
        -------
        
            int.

        """
             
        table_key = self._check_table_key(table_key)
        db_names = self._db_names
        if len(db_names[table_key]["primary_key"]) == 0:
            print("The table corresponding to the key '" + table_key 
                + "' has no primary key.")
            return

        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()

        querystr = ("Select MAX(" + db_names[table_key]["primary_key"] + ") "
            + "from " + db_names[table_key]["_schema"] + "." 
            + db_names[table_key]["_table_name"])
        df = pandas.read_sql_query(querystr, self._conn)
        try:
            r = int(df.iloc[0,0])
        except:
            return 0
        else:
            return r
    
    # Gets the last acquisition date in the database for the given demand.
    def get_last_date(self, demand_id):
        """
        Gets the date of the latest measurement record corresponding to the 
        given demand_id.

        Parameters
        ----------
        
            demand_id: the id of the demand record (int).

        Returns
        -------
        
            A date formatted as string or None if there is no record.

        """
        if str(demand_id).isnumeric():
            demand_id = int(demand_id)
        else:
            raise TypeError("'demand_id' must be an integer.")
            
        db_names = self._db_names
        acq_demand_fkey_col = db_names["acquisition"]["fkey_demand"].upper()
        acq_date_col = db_names["acquisition"]["date"].upper()

        # Get the last date in the database.
        schemastr = db_names["acquisition"]["_schema"]
        tablestr = db_names["acquisition"]["_table_name"]
        if schemastr != "":
            tablestr = schemastr + "." + tablestr
        querystr = ("Select MAX(" + acq_date_col + ") from " + tablestr 
            + " where " + acq_demand_fkey_col + " = " + str(demand_id))
        df = self.get_query(querystr)
        if df is None:
            return
        if len(df) > 0:
            last_date = df.iloc[0,0]
            return last_date
        else:
            return
    
    # Determines new start and end dates from a given latest date (as str).
    # Used, for example, to update the period of interest of the demand.
    def _new_start_end_dates(self, start_date, end_date, last_date_str):
        last_date = pandas.to_datetime(
            last_date_str) + pandas.Timedelta(days=1)
        if start_date is None:
            new_start_date = last_date 
        else:
            new_start_date = max(last_date, 
                pandas.to_datetime(start_date))
        start_date = new_start_date.date()
        if end_date is not None:
            new_end_date = max(pandas.to_datetime(end_date), 
                new_start_date + pandas.Timedelta(days=1))
            end_date = new_end_date.date()
            
        return (start_date, end_date)
    
    
    # Sends a custom query to the database engine. The result must be
    # compatible with pandas dataframe.
    def get_query(self, querystr):
        """
        Sends a custom data query to the target database. It must be a query 
        that returns data storable in a dataframe.

        Parameters
        ----------
        
            querystr: SQL query (str).

        Returns
        -------
        
            dataframe.

        """
        
        if not isinstance(querystr, str):
            raise TypeError("'querystr' must be a str.")
    
        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()
        
        return pandas.read_sql_query(querystr, self._conn)
    
    # Takes a dataframe related to a table and rename its columns to the real
    # column names in the database. The input columns can be in the format 
    # table_name.col_name, in which case the table name will be removed, or 
    # in the format table_key.col_key or simply col_key, in which case the key
    # from db_names will be replaced by the real column name.
    def _to_real_col_names(self, df, table_key):
        table_key = self._check_table_key(table_key)
        db_names = self._db_names
        df_cols = [*df.columns]
        subdict = db_names[table_key]
        key_list = [*subdict.keys()]
        subdict_fullkey = {(table_key + "." + k):v 
            for k, v in subdict.items()}
    
        # Rename df columns to the real names in the database.
        subdict_fullkey = {(table_key + "." + k):v 
            for k, v in subdict.items()}
        for i in range(len(df_cols)):
            if df_cols[i] in key_list:
                df_cols[i] = subdict[df_cols[i]]
            elif df_cols[i] in [*subdict_fullkey]:
                df_cols[i] = subdict_fullkey[df_cols[i]]
        
        # Rename extended real names (with table and schema) to column 
        # names only.
        subdict_extname1 = {(subdict["_table_name"].lower() + "." 
            + v.lower()):v for k, v in subdict.items()}
        subdict_extname2 = {(subdict["_schema"].lower() + "." 
            + subdict["_table_name"].lower() + "." + v.lower()):v 
            for k, v in subdict.items()}
        for i in range(len(df_cols)):
            if df_cols[i].lower() in [*subdict_extname1]:
                df_cols[i] = subdict_extname1[df_cols[i].lower()]
            elif df_cols[i].lower() in [*subdict_extname2]:
                df_cols[i] = subdict_extname2[df_cols[i].lower()]
        
        df.columns = df_cols  
        
        return df
    
    # Saves records to a table, identified by a key of 'db_names' ('station',
    # 'product', 'variable' etc.).
    # If 'only_db_names'=False, the columns to be saved won't be restricted
    # to those pointed by the db_names dict. That is, extra columns (if 
    # present in the target table) will be saved.
    # Returns the number of saved records.
    def save_to_table(self, table_key, df, 
            only_db_names=True, avoid_duplication=True):
        """
        Saves the data in the argument 'df' into the table specified by 
        'table_key'. Valid table keys: ['station', 'instrument', 'variable', 
        'product', 'cloud_algo', 'local_algo', 'reducer', 'demand', 
        'acquisition', 'data', 'result', 'stats', 'application'].

        Parameters
        ----------
        
            table_key: str.
            df: dataframe.
            only_db_names: if True, only saves the data in known GEEDaR 
                columns; if False, any column in 'df' will be saved - if it 
                exsists in the target database (bool, optional).
            avoid_duplication: if True, check for presumably identical records 
                in the database to avoid duplication; if False, saves without 
                checking for that (bool, optional).

        Returns
        -------
        
            The number of rows inserted in the target table (int).

        """
        if not isinstance(df, pandas.DataFrame):
            raise TypeError("'df' must be a pandas data frame.")        
        table_key = self._check_table_key(table_key)
        
        db_names = self._db_names
        table_name = (db_names[table_key]["_schema"] + "." 
            + db_names[table_key]["_table_name"])
        subdict = db_names[table_key]
        key_list = [*subdict.keys()]
        
        # Rename columns to the real column name.
        
        df = self._to_real_col_names(df, table_key)
        df_cols = [*df.columns]
        
        # Check if the df has valid columns.
        
        geedar_cols = [subdict[k].lower() for k in key_list 
            if k[0] != "_"]
        # Unexpected columns?
        if only_db_names:
            unexpected_cols = [c for c in df_cols 
                if c.lower() not in geedar_cols]
            if len(unexpected_cols) > 0:
                raise ValueError("'df' contains columns which do not match "
                    + "the columns listed in db_names['" + table_key + "']: " 
                    + str(unexpected_cols) + ".")
        # Missing columns?
        missing_cols = [c for c in geedar_cols 
            if c not in [col.lower() for col in df_cols] and 
            c != subdict["primary_key"].lower()]
        ext_missing_cols = [(k + " ('" + subdict[k] + "')") 
            for k in key_list 
            if (subdict[k].lower()) in [col.lower() for col in missing_cols]]
        if len(ext_missing_cols) > 0:
            raise ValueError("Required columns were not found in 'df': "
                + str(ext_missing_cols) + ".")

        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()
        conn = self._conn
                
        # Check if table and columns in 'db_names' exist in the database.
        
        schema = subdict["_schema"]
        table = subdict["_table_name"]
        sqlstr = f"""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}';
        """
        querydf = pandas.read_sql_query(sqlstr, conn)
        if querydf.iloc[0,0] == 0:
             raise ValueError("The table " + table + " was not found in "
                 + "the target database.")
        
        sqlstr = f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table}' AND DATA_TYPE <> 'geometry';
        """
        table_cols = pandas.read_sql_query(sqlstr, conn)
        unmatched_cols = [c for c in df_cols 
            if c.lower() not in 
            [col.lower() for col in list(table_cols["COLUMN_NAME"])]]                
        if len(unmatched_cols) > 0:
            raise ValueError("One or more columns in the input data frame "
                + "were not found in the table ''" + table_name + "': " 
                + str(unmatched_cols) + ".")

        # Remove columns with identity restriction (autoincrement).
        valid_cols = df_cols
        cols = inspect(conn).get_columns(db_names[table_key]["_table_name"], 
            schema=db_names[table_key]["_schema"])    
        has_identity = False
        for col in cols:
            if (col.get('autoincrement') is True 
                    or col.get('identity') is not None):
                has_identity = True
            else:
                default_val = str(col.get('default', '') or '').lower()
                if 'nextval' in default_val:
                    has_identity = True
            if has_identity:
                valid_cols = [c for c in valid_cols 
                    if c.upper() != col["name"].upper()]
            has_identity = False
                
        # Check preexisting records to avoid saving a duplicated one.
        if avoid_duplication:
            if table_key == "station":
                # In the dataframe, the names may be different from the names
                # in db_names (in upper or lower case, for example).
                lower_cols = [db_names["station"][k].lower() for k in ["code"]]
                check_cols = [col for col in df_cols 
                    if col.lower() in lower_cols]
            elif table_key == "demand":
                lower_cols = [db_names["demand"][k].lower() for k in 
                    ["fkey_station", "fkey_product", "fkey_cloud_algo", 
                     "fkey_local_algo", "fkey_reducer"]]
                check_cols = [col for col in df_cols 
                    if col.lower() in lower_cols]
            else:
                check_cols = valid_cols           
            
            rows_to_remove = []
            for i in df.index:
                sqlstr = ("SELECT COUNT(*) FROM " + table_name + " WHERE ")
                for col in check_cols:
                    sqlstr = (sqlstr + col + " = " 
                        + val_to_sql(df.loc[i, col]) + " AND ")
                # Remove the last "and".
                sqlstr = sqlstr[:-5]
                querydf = pandas.read_sql_query(sqlstr, conn)
                if querydf.iloc[0,0] > 0:
                    rows_to_remove.append(i)
            if len(rows_to_remove) > 0:
                print(str(len(rows_to_remove)) + " rows will not be saved in "
                    + "the database to avoid duplication.")
                df.drop(rows_to_remove, axis=0, inplace=True)
        
        # Check if df is empty.
        if len(df) == 0:
            print("No data in the dataframe to be saved in the database.")
            return 0
        
        # Build the column list for the SQL insert.
        col_list_str = " (" + ",".join(valid_cols) + ")"
        # Build the value list.
        val_list_str = ""
        for i in df.index:
            row_vals = list_to_sql(list(df.loc[i,valid_cols]))
            val_list_str = val_list_str + row_vals + ","
        val_list_str = val_list_str[:-1] + ";"
        # Build the SQL clause.
        sqlstr = ("INSERT INTO " + table_name + col_list_str + " VALUES " 
            + val_list_str)
        
        # Try to save.
        conn = self._conn
        try:
            result = conn.execute(text(sqlstr))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(e)
            return -1
        else:
            return result.rowcount
    
    # Reads a dataframe or csv file and saves the data into the table 
    # specified by 'table_key'.
    # If 'df' is a string, it will be treated as the address of a csv file to 
    # be read.
    # Important: this method won't limit the columns to the ones pointed by 
    # the values in the db_names dict. Instead, if a column is found in the 
    # target table, it will be kept in the data frame which will be used to 
    # request the creation of the new records. For consistency, therefore, 
    # this method only works with the column real names.
    def import_table(self, df, table_key):
        """
        Imports the data in 'df' to the database table indicated by 
        'table_key'. Valid table keys: {}.
        
        You may pass either a dataframe or the path of a CSV file as argument 
        for 'df'.
        
        Important: it will be tried to save the all the columns in df, so they 
        must match the ones in the target table.
        
        Returns None.

        Parameters
        ----------
        
            df: dataframe or str.
            table_key: str.

        """
               
        if isinstance(df, str):
            df = pandas.read_csv(df)
        elif not isinstance(df, pandas.DataFrame):
            raise TypeError("'df' should be a data frame or the address of "
                + "a csv file.")
            
        r = self.save_to_table(table_key, df, only_db_names=False)
        if r > 0:
            print(str(r) + " records were imported.")
        else:
            print("No record was imported.")
            
    # Imports demands to the database. This method makes easier for the user
    # to import demands than with the method 'import_table'. It accepts 
    # the station name instead of the station record id. And it accepts the 
    # column keys instead of the real column names.
    def import_demands(self, df):
        """
        Reads a dataframe with data describing GEEDaR demands and creates the 
        corresponding records in the demand table of the target database.
        
        You may pass a dataframe or the path of a CSV file as argument for 
        'df'.
        
        Returns None.

        Parameters
        ----------
        
            df: dataframe or str.

        """

        if isinstance(df, str):
            df = pandas.read_csv(df)
        elif not isinstance(df, pandas.DataFrame):
            raise TypeError("'df' should be a data frame or the address of "
                + "a csv file.")
        
        if len(df) == 0:
            raise ValueError("The input dataframe is empty.")
        
        db_names = self._db_names
        df_cols = [*df.columns]
        
        station_schema = db_names["station"]["_schema"]
        station_table = db_names["station"]["_table_name"]
        station_name_col = db_names["station"]["name"]
        station_id_col = db_names["station"]["primary_key"]
        station_code_col = db_names["station"]["code"]
        product_code_col = db_names["product"]["primary_key"]
        cloud_algo_code_col = db_names["cloud_algo"]["primary_key"]
        local_algo_code_col = db_names["local_algo"]["primary_key"]
        reducer_code_col = db_names["reducer"]["primary_key"]
        station_fk_col = db_names["demand"]["fkey_station"]
        product_fk_col = db_names["demand"]["fkey_product"]
        cloud_algo_fk_col = db_names["demand"]["fkey_cloud_algo"]
        local_algo_fk_col = db_names["demand"]["fkey_local_algo"]
        reducer_fk_col = db_names["demand"]["fkey_reducer"]
        start_date_col = db_names["demand"]["start_date"]
        end_date_col = db_names["demand"]["end_date"]
        aoi_mode_col = db_names["demand"]["aoi_mode"]
        kml_path_col = db_names["demand"]["kml_path"]
        required_cols = [product_fk_col, cloud_algo_fk_col, local_algo_fk_col, 
            reducer_fk_col, start_date_col, end_date_col]
        
        # Rename columns to the real column name.   
        df = self._to_real_col_names(df, "demand")
        df_cols = [*df.columns]
        
        missing_cols = [r for r in required_cols 
            if r.lower() not in [col.lower() for col in df_cols]]
        if len(missing_cols) > 0:
            raise ValueError("One or more required columns were not found "
                + "in the input dataframe: " + str(missing_cols) + ".")
        
        # Enforce the use of the real column names.
        cur_op = self.use_real_col_names
        self.use_real_col_names = True
        
        # If not yet connected, do it.
        if not self._is_conn_valid():
            self.connect()
        conn = self._conn
        
        # Retrieve station names and ids from the database.
        station_table_full_name = (station_table if station_schema == "" else 
            station_schema + "." + station_table)        
        sqlstr = ("SELECT " + station_name_col + ", " + station_id_col 
            + " FROM " + station_table_full_name)
        existing_stations = pandas.read_sql_query(sqlstr, conn)
        
        # Fill the station id data.
        
        has_name = station_name_col in df_cols
        has_id = station_id_col in df_cols
        has_code = station_code_col in df_cols
        has_fkid = station_fk_col in df_cols
        if not any([has_name, has_id, has_code, has_fkid]):
            raise ValueError("The input dataframe must contain a column for "
                + "identification of the station associated to the demand.")      
        if not has_fkid:
            if has_id:
                df[station_fk_col] = df[station_id_col]
            else:
                df[station_fk_col] = [None]*len(df)
            df_cols.append(station_fk_col)
        for i in df.index:
            id_val = df.loc[i, station_fk_col]
            if not has_name and not has_code and not str(id_val).isnumeric():
                raise ValueError("The input dataframe should have station "
                    + "names, codes or ids. None was found in row " + str(i) 
                    + ".")
            elif not str(id_val).isnumeric():
                station_id = []
                if has_code:
                    station_code = df.loc[i, station_code_col]
                    station_id = [existing_stations.loc[j, station_id_col] 
                        for j in existing_stations.index if str(
                        existing_stations.loc[j, station_code_col]).lower() 
                        == station_code.lower()]
                if has_name and len(station_id) == 0:
                    station_name = df.loc[i, station_name_col]
                    station_id = [existing_stations.loc[j, station_id_col] 
                        for j in existing_stations.index if str(
                        existing_stations.loc[j, station_name_col]).lower() 
                        == station_name.lower()]
                if len(station_id) == 0:
                    raise ValueError("Could not find the record id of the "
                        + "station " + station_name + " (row " + str(i) 
                        + " of the input dataframe).")
                elif len(station_id) > 1:
                    raise ValueError("More than one id was returned when "
                        + "searching for station " + station_name + " in the " 
                        + "database.")
                df.loc[i, station_fk_col] = station_id[0]
            else:
                # Check if the id val matches a record in the database.
                if id_val not in [*existing_stations[station_id_col]]:
                    raise ValueError("The station id value (" + str(id_val) 
                        + ") in the row " + str(i) 
                        + " was not found in the database")
                        
        # Remove non-demand columns.
        geedar_cols = [db_names["demand"][k].lower() 
            for k in [*db_names["demand"]]]        
        df.drop([c for c in df_cols if c.lower() not in geedar_cols], axis=1, 
            inplace=True)
        df_cols = [*df.columns]
             
        # Check each row for the valid values of product, cloud and local algo, 
        # reducer, aoi_mode and kml_path (if present).
        
        product_table = self.get_table("product")
        cloud_algo_table = self.get_table("cloud_algo")
        local_algo_table = self.get_table("local_algo")
        reducer_table = self.get_table("reducer")

        for i in df.index:
            product_code = df.loc[i, product_fk_col]
            if product_code not in [*product_table[product_code_col]]:
                raise ValueError("The product code in the row " + str(i) 
                    + "does not match any in the target database: " 
                    + str(product_code) + ".")
            cloud_algo_code = df.loc[i, cloud_algo_fk_col]
            if cloud_algo_code not in [*cloud_algo_table[cloud_algo_code_col]]:
                raise ValueError("The cloud algorithm in the row " + str(i) 
                    + " does not match any code in the target database: " 
                    + str(cloud_algo_code) + ".")
            local_algo_code = df.loc[i, local_algo_fk_col]
            if local_algo_code not in [*local_algo_table[local_algo_code_col]]:
                raise ValueError("The local algorithm in the row " + str(i) 
                    + "does not match any code in the target database: " 
                    + str(local_algo_code) + ".")
            reducer_code = df.loc[i, reducer_fk_col]
            if reducer_code not in [*reducer_table[reducer_code_col]]:
                raise ValueError("The reducer code in the row " + str(i) 
                    + "does not match any in the target database: " 
                    + str(reducer_code) + ".")
            if aoi_mode_col in df_cols:
                aoi_mode = df.loc[i, aoi_mode_col]
                if aoi_mode is None:
                    continue
                if pandas.isna(aoi_mode):
                    df.loc[i, aoi_mode_col] = None
                    continue
                elif not str(aoi_mode).isnumeric():
                    raise TypeError("The values in the column '" 
                        + aoi_mode_col + "' should be integers.")
                elif aoi_mode > 1:
                    raise TypeError("The values in the column '" 
                        + aoi_mode_col + "' should be 0 or 1.")
                elif aoi_mode == 1: # KML
                    if kml_path_col in df_cols:
                        kml_path = df.loc[i, kml_path_col]
                        if kml_path is None or pandas.isna(kml_path):
                            kml_path = "auto"
                        if not isinstance(kml_path, str):
                            raise TypeError("The values in the column '"
                                + kml_path_col + "' should be strings.")
                        if kml_path == "auto":
                            df.loc[i, kml_path_col] = None
                        elif not is_path_valid(kml_path):
                            raise ValueError("The values in the column '"
                                + kml_path_col + "' should be valid paths.")            
        
        r = self.save_to_table("demand", df, only_db_names=True)
        if r > 0:
            print(str(r) + " records were inserted.")
        else:
            print("No record was saved.")
        
        # Undo the change in the option regarding real column names.
        self.use_real_col_names = cur_op
        
        
#%% UserOptions class

class UserOptions:
    """
    This class deals with the command line user options, arranging and 
    validating them. Instatiation takes as input the command line string and a 
    guide dictionary with the valid options.
    
    Instantiation
    -------------
    
    These are the instantiation parameters:
    
        cmd_line: the list of command line parts to be interpreted (list; 
            defaults to "-h", which calls for instructions on the command line 
            options).
        guide: a dictionary with the structure of the 'guide_example' 
            attribute (dict, defaults to the content of '_default_guide').
    
    Regarding the content of the guide dictionary, here are some instructions:
        
        To define a command line option as mandatory, the key 'default_value' 
        must take None as value. For optional arguments, this key must take a 
        string as argument - as a partial string that would come from the user 
        command line.
        
        If a leading command letter (like the '-i:' in '-i:test.csv') is not 
        mandatory, set the key 'auto_assign_command' as True.
        
        The key 'valid_values' takes a list. The list must contain objects 
        corresponding to the expected unique values or expected types. A Range 
        object is also accepted.
    
    """
    
    _default_guide = {
        "i": {
            "name": "input",
            "description": ("The path of the input file. For a path with "
                + "white spaces, you must enclose it in quotes. This argument "
                + "is mandatory if you do not provide the 'mode' argument."),
            "is_a_list": False,
            "valid_values": [str],
            "default_value": "",
            "auto_assign_command": True
        },
        "o": {
            "name": "output",
            "description": ("The path of the output file. For a path with "
                + "white spaces, you must enclose it in quotes."),
            "is_a_list": False,
            "valid_values": [str],
            "default_value": "auto",
            "auto_assign_command": False
        },
        "m": {
            "name": "mode",
            "description": ("The operation mode of GEEDaR: 1, 2 or 3. " 
                + "A zero stands for automatic mode detection. This argument "
                + "is mandatory if you do not provide the 'input' argument."),
            "is_a_list": False,
            "valid_values": [0,1,2,3],
            "default_value": "0",
            "auto_assign_command": False
        },
        "c": {
            "name": "code",
            "description": ('The "demand code", describing which product, ' 
                + "cloud algorithm, local algorithm, and reducer are to be "
                + "used. To pass a list of codes, they MUST be enclosed with "
                + "square brackets and separated by commas, like a Python "
                + "list, without white spaces inside the list."),
            "is_a_list": True,
            "valid_values": [str, int],
            "default_value": "auto",
            "auto_assign_command": False
        },
        "k": {
            "name": "kml",
            "description": "Sets 'kml' as the source of the information for " 
                + "defining the geometry of the 'area of interest'.",
            "is_a_list": False,
            "valid_values": [True,False],
            "default_value": "False",
            "auto_assign_command": False
        },
        "r": {
            "name": "radius",
            "description": ("Sets a radius, in meters, for the area of "
                + "interest. Zero is not allowed. "
                + "A value of -1 stands for default. In such case, there is "
                + "no need to use the 'r' parameter in the command line."),
            "is_a_list": False,
            "valid_values": [range(-1,100000)],
            "default_value": "-1",
            "auto_assign_command": False
        },
        "t": {
            "name": "timewindow",
            "description": ("Sets a +/- tolerance, in days, for matching up " 
                + "the dates of field data and satellite data."),
            "is_a_list": False,
            "valid_values": [range(0,367)],
            "default_value": "0",
            "auto_assign_command": False
        },
        "s": {
            "name": "separate",
            "description": "When exporting the results as a csv file, an " 
                + "extra file will be saved with the results in separate "
                + "groups of columns for each unique demand code. Useful for "
                + "comparing results between instruments.",
            "is_a_list": False,
            "valid_values": [True,False],
            "default_value": "False",
            "auto_assign_command": False
        },
        "h": {
            "name": "help",
            "description": ("Describes command line options for starting " 
                + "GEEDaR."),
            "is_a_list": False,
            "valid_values": [True,False],
            "default_value": "False",
            "auto_assign_command": False
        }
    }  
    example_guide = _default_guide.copy()  
    
    def __init__(self, cmd_line=["-h"], guide=_default_guide, 
            letter_marker = "-", word_marker = "--", separator = [":","="]):       
        # Check types.
        if not isinstance(cmd_line, list):
            raise TypeError("'cmd_line' must be a list.")
        if not isinstance(guide, dict):
            raise TypeError("'guide' must be a dict.")
        if not isinstance(letter_marker, str):
            raise TypeError("'letter_marker' must be a string.")
        if not isinstance(word_marker, str):
            raise TypeError("'word_marker' must be a string.")
        if not isinstance(separator, list):
            if isinstance(separator, str):
                separator = [separator]
            else:
                raise TypeError("'separator' must be a string or list of " 
                    + "strings.")
        else:
            if not all(isinstance(s, str) for s in separator):
                raise TypeError("'separator' must be a list of strings.")
        
        self._cmd_line = cmd_line
        self._guide = guide
        self._letter_marker = letter_marker
        self._word_marker = word_marker
        self._separator = separator
        self.options_dict = None
        self._validate_options()
    
    # Validate 'user_options' and 'guide', returning a standardized dict.
    def _validate_options(self):        
        args = self._cmd_line
        guide = self._guide
        letter_marker = self._letter_marker
        word_marker = self._word_marker
        separator = self._separator
        
        # Validate the structure of the 'guide' dict and get:
        # - the list of param. letters (option ids) and words (option names)
        # - the accepted unsigned arguments
        # - the default values, which will be inserted into a pre-filled user- 
        #   options list.
        valid_command_letters = []
        valid_command_words = []
        valid_unsigned_args = []
        user_options = dict()
        for option_id in [*guide]:
            if [*guide[option_id]].sort() != [
                    "name","is_a_list","valid_values","default_value",
                    "auto_assign_command"].sort():
                raise ValueError("'guide' has an incorrect structure.")
            valid_command_letters = valid_command_letters + [option_id]
            valid_command_words = valid_command_words + [guide[option_id][
                "name"]]
            if guide[option_id]["auto_assign_command"]:
                valid_unsigned_args = valid_unsigned_args + [option_id]
            user_options[option_id] = guide[option_id]["default_value"]
        
        # Check each argument, breaking it into a command part and a value 
        # part, in accordance with 'separator'. The default values in the user 
        # options list will be replaced by the options provided in 'args'.
        # Unsigned arguments will be dealt with by inserting the presumed 
        # command letter before the user-provided value. By unsigned argument 
        # we mean an argument without a leading indicator such as "-" or "--".
        # Unsigned arguments receive the presumed command letter by following 
        # the original order of the options in 'guide_list' for which 
        # 'auto_assign_command' is true.
        unsigned_args_count = 0
        for arg_ind in range(len(args)):
            arg = args[arg_ind]
            # Signed? How?
            if arg[:len(letter_marker)] == letter_marker:
                marker_end_pos = len(letter_marker) - 1
            elif arg[:len(word_marker)] == word_marker:
                marker_end_pos = len(word_marker) - 1
            # Unsigned.
            else:
                marker_end_pos = -1
            
            if marker_end_pos < 0:
                unsigned_args_count = unsigned_args_count + 1
                if unsigned_args_count > len(valid_unsigned_args): 
                    raise ValueError("Unrecognized argument: " + arg)
                else:
                    param_str = valid_unsigned_args[unsigned_args_count - 1]
                    val_str = arg
            else:
                separator_end_pos = [arg.find(s) + len(s) - 1 
                    for s in separator if arg.find(s) > 0]
                # Is there a separator (such as ':' in '-r:250')? 
                # If not, the argument is in the form '-a', with no value.
                if len(separator_end_pos) == 0:
                    param_str = arg[(marker_end_pos + 1):]
                    val_str = "True" # This kind of command is logical (true 
                        # if used by the user, false if omitted)
                else:
                    param_str = arg[(marker_end_pos + 1):
                        (separator_end_pos[0])]
                    val_str = arg[(separator_end_pos[0] + 1):]                
            
            # Validate the parameter:
            if (param_str not in valid_command_letters 
                    + valid_command_words):
                raise ValueError("Unrecognized parameter ('" + 
                    param_str + "') in the command part '" + arg + "'.")
            # Convert option name (word) to option id (letter).
            if param_str in valid_command_words:
                letter_ind = valid_command_words.index(param_str)
                param_str = valid_command_letters[letter_ind]
            # Update value in the user options list:
            user_options[param_str] = val_str
        
        # Validate the values associated to each command.
        for option_id in [*user_options]:
            # Get the current value:
            val_str = user_options[option_id]
            # If a value is required but not given, raises an error.
            if val_str == "" and guide[option_id]["default_value"] is None:
                raise ValueError("An argument is required but was not "
                    + "provided for the parameter '" + option_id + "' (" 
                    + guide[option_id]["name"] + ").")
            # If the value is an empty string and so is the default value, 
            # no analysis is needed.
            #if val_str == "" and guide[option_id]["default_value"] == "":
            #    continue            
            # Empty strings need to be enforced as such:
            if val_str == "":
                val_str = "''"
            # Turn the reference and the user values into lists for stepwise 
            # validation:
            if guide[option_id]["is_a_list"]:
                val_list = str_to_list(val_str, opening = "[", closing = "]", 
                    sep = [",",";"], optional_enclosing = True)
            else:
                val_list = [autocast_str(val_str)]
            ref_list = guide[option_id]["valid_values"]
            if ref_list is None:
                continue
            if ref_list == []:
                continue
            if not isinstance(ref_list, list):
                ref_list = [ref_list]
            # All types are valid?
            valid_types = []
            for r1 in ref_list:
                if type(r1) is not list:
                    r1 = [r1]
                for r2 in r1:
                    if type(r2) is type:
                        valid_types = valid_types + [r2]
                    elif isinstance(r2, range):
                        valid_types = valid_types + [int]
                    else:
                        valid_types = valid_types + [type(r2)]
            value_types = [type(v) for v in val_list]
            if not all(v in valid_types for v in value_types):
                raise ValueError("The value associated with the command '-" 
                    + option_id + "' (='--", guide[option_id]["name"] 
                    + "') should be of type " + "or".join(
                    [str(t) for t in valid_types]) + ".")
            # Values in accepted range/list?
            out_val = False
            for r1 in ref_list:
                if not isinstance(r1, list):
                    r1 = [r1]
                for r2 in r1:                
                    if isinstance(r2, list):
                        raise ValueError("Invalid content of " + option_id  
                            + "['valid_values'] in the user options guide.")
                    if isinstance(r2, range):
                        if not all(v in r2 for v in val_list):
                            out_val = True
                            break
            if out_val:
                raise ValueError("One or more invalid values for the option " 
                    + option_id + " (" + guide[option_id]["name"] + ").")
            # Set a definitive value to the option:
            if not guide[option_id]["is_a_list"]:
                user_options[option_id] = val_list[0]
            else:
                user_options[option_id] = val_list
        
        # Finally, convert option ids back to (more friendly) option names:
        final_user_options = dict()
        for k in user_options:
            final_user_options[guide[k]["name"]] = user_options[k]
        self.options_dict = final_user_options
    
    # Shows automatically generated instructions on command line options based
    # on this object contents.
    def show_help(self):
        options_guide = self._guide
        letter_marker = self._letter_marker
        word_marker = self._word_marker
        separators = self._separator
        
        legend_range = False
        cmd_dict = dict()
        usage_str = "geedar "
        for cmd_letter, guide in options_guide.items():
            
            cmd_dict[cmd_letter] = {"syntax": "", "default_value": ""}
            
            default_value = options_guide[cmd_letter]["default_value"]
            if default_value is None:
                default_value = "None"
            elif default_value not in ["False", "True"]:
                if len(default_value) > 1:
                    if not (default_value[0] == "-" and 
                            default_value[1:].isnumeric()):
                        default_value = "'" + default_value + "'"
                elif not default_value.isnumeric():
                    default_value = "'" + default_value + "'"
            
            cmd_dict[cmd_letter]["default_value"] = default_value
            
            par_str = letter_marker + str(cmd_letter)
            if default_value == "False":
                cmd_str = par_str
            else:
                par_str = par_str + separators[0]
                val_str = ""
                for obj in guide["valid_values"]:
                    if type(obj) is type:
                        tmp_str = obj.__name__
                    elif type(obj) is range:
                        legend_range = True
                        tmp_str = str(obj.start) + ":" + str(obj.stop - 1)
                    else:
                        tmp_str = str(obj)
                    val_str = val_str + tmp_str + "|"
                val_str = val_str[:-1]
                if guide["is_a_list"]:
                    val_str = "<list " + val_str + ">"
                else:
                    val_str = "<" + val_str + ">"
                cmd_str = par_str + val_str
            
            cmd_dict[cmd_letter]["syntax"] = cmd_str
            
            if default_value == "None":
                cmd_str = "<" + cmd_str + ">"
            else:
                cmd_str = "[" + cmd_str + "]"
            
            usage_str = usage_str + cmd_str + " "
        
        print("\nUsage: " + usage_str + "\n")
        
        print("\nCommand options:")
        
        for cmd_letter in [*options_guide]:            
            print("")
            print(text_box(
                letter_marker + cmd_letter + ", " 
                + word_marker + options_guide[cmd_letter]["name"], 
                first_line_indent=4, other_lines_indent=8, max_width=80))
            print(text_box(
                options_guide[cmd_letter]["description"], 
                first_line_indent=8, other_lines_indent=8, max_width=80))
            if cmd_dict[cmd_letter]["default_value"] != "False":
                print(text_box(
                    "Default value: " + cmd_dict[cmd_letter]["default_value"], 
                    first_line_indent=8, other_lines_indent=8, max_width=80))
            
        # Observations.
        print("\nNotes:\n")
        print(text_box(
            "The characters '<', '>' and '|' shown above must not be "
            + "used in the real command line. The same applies to '[' "
            + "and ']', except when the user wants to pass a list of "
            + "values, in which case they must be enclosed in square "
            + "brackets and separated by commas, with no spaces.", 
            first_line_indent=4, other_lines_indent=4, 
            max_width=80))            
        if legend_range:
            print("")
            print(text_box(
                "When a range of integers is accepted as value, a ':' "
                + "separates the minimum and maximum.", 
                first_line_indent=4, other_lines_indent=4, 
                max_width=80))


#%% GeedarApp class

# Operation modes: 1 - matchup; 2 - time series; 3 - database
# Mode 1: input csv, output csv
# Mode 2: input csv, output csv
# Mode 3: GeedarDB object
class GeedarApp:
    """
    This class integrates all the others in this module and allows for the 
    instantiation of an object that is the core of the GEEDaR application.
    
    Instantiation
    -------------
    
    For instantiation it must get a UserOptions object and the catalogues of 
    products, algorithms, reducers, instruments and variables.
    
    The app may operate in three modes: 1 - matchup; 2 - time series; and 
    3 - database. For modes 1 and 2, it must read an input csv file (or a set 
    of kml files) and will save the results to another csv file. For mode 3, 
    a configuration dictionary must be passed to the parameter 'db_config' for 
    the app to be able to connect to a database, from which the data demands 
    will be read and to which the results will be saved.
    
    The parameters are:
    
        user_options: an instance of UserOptions.
        product_catalog: a dictionary of Product ojects identified by a 
            unique number.
        cloud_algo_catalog: a dictionary of CloudAlgo ojects identified by a 
            unique number.
        local_algo_catalog: a dictionary of LocalAlgo ojects identified by a 
            unique number.
        reducer_catalog: a dictionary of Reducer ojects identified by a 
            unique number.
        instrument_catalog: a dictionary of Instrument ojects identified by a 
            unique number.
        variable_catalog: a dictionary of Variable ojects identified by a 
            unique number.
        default_demand_code: a list of strings or a list-like string with the 
            demand codes, which are a combination of letters and numbers 
            describing the data demands as for the satellite product, the 
            cloud and local algorithms and the reducer (list or str or None, 
            defaults to None).
        db_config: a dictionary with the configuration of a target database, 
            including connection parameters and the names of tables and 
            columns required by GEEDaR (dict or None, defaults to None).
        cache_file: if True, the app will save the progress of the processing 
            of data demands (bool, defaults to True).
    
    Properties
    ----------
    
        result_df: if the demands were all processed, returns the dataframe 
            with the consolidated results (None or Dataframe).
    
    Methods
    -------
    
        execute_demands
        save_results
    
    """
    
    # Correspondence between the standard internal demand data frame and the
    # columns in the target database or in the user input file. 
    # For operation mode 3 (database), only the first item of the lists are
    # used. For operation mode 2, all the values in the lists are valid.
    _demand_cols_dict = {
        "demand_id": ["demand.primary_key", "demand_id"],
        "status": ["demand.status", "demand_status", "status"],
        "station_id": ["station.primary_key", "station.id", "station_id"],
        "station_code": ["station.code", "station_code", "id", "code", 
            "stcode"],
        "station_name": ["station.name", "station_name", "name", "station", 
            "site"],
        "lat": ["station.lat", "lat", "latitude"],
        "long": ["station.long", "long", "lon", "longitude"],
        "product_code": ["product.primary_key", "product_code"],
        "cloud_algo_code": ["cloud_algo.primary_key", "cloud_algo_code"],
        "local_algo_code": ["local_algo.primary_key", "local_algo_code"],
        "reducer_code": ["reducer.primary_key", "reducer_code"],
        "start_date": ["demand.start_date", "start_date"],
        "end_date": ["demand.end_date", "end_date"],
        "date_list": [], # This column is only in the internal data frame.
        "aoi_mode": ["demand.aoi_mode", "aoi_mode"],
        "aoi_radius": ["demand.aoi_radius", "aoi_radius", "radius"],
        "kml_path": ["demand.kml_path", "kml_path", "file_path", "path"],
        "geojson": [] # This column is only in the internal data frame.
    }
    
    # Valid column names for the input file in operation mode 1 (matchup mode).
    _matchup_cols_dict = {
        "id": (_demand_cols_dict["station_code"] 
            + _demand_cols_dict["station_name"]),
        "lat": _demand_cols_dict["lat"],
        "long": _demand_cols_dict["long"],
        "date": ["date"],
        "product_code": _demand_cols_dict["product_code"],
        "cloud_algo_code": _demand_cols_dict["cloud_algo_code"],
        "local_algo_code": _demand_cols_dict["local_algo_code"],
        "reducer_code": _demand_cols_dict["reducer_code"],
        "aoi_mode": _demand_cols_dict["aoi_mode"],
        "aoi_radius": _demand_cols_dict["aoi_radius"],
        "kml_path": _demand_cols_dict["kml_path"],
    }
    
    # These are the minimum columns included in the result dataframe. 
    # Additional columns may include custom columns provided in the input file 
    # (in mode 1, only) and, obviously, the columns corresponding to satellite 
    # bands and calculated variables.
    _result_min_cols = ["station_code", "station_name", "lat", "long", "date", 
        "geojson", "demand_code", "img_date", "img_time"]
    
    # Address (string) of the temporary pickle file where to save the general 
    # processing progress.
    _app_cache_file = "proc_dict.pkl"
    
    def __init__(self, user_options, 
            product_catalog, cloud_algo_catalog, local_algo_catalog,
            reducer_catalog, instrument_catalog, variable_catalog,
            default_demand_code=None, db_config=None, cache_file=True):
        
        print("Instantiating GeedarApp...")

        # Validate arguments and add these attributes: '_options_dict', 
        # '_args', '_cache_file", '_default_demand_code' and 'db_config'.
        # '_options_dict' stores a copy the 'options_dict' attribute of 
        # 'user_options'.
        # '_args' stores a copy of the constructor arguments.
        # '_cache_file' stores the address of the cache file to be used.
        self._validate_args(locals())
        options_dict = self._options_dict
        
        # Set attributes for input path: '_input_path', '_input_dir' and 
        # '_input_file'.
        input_path = options_dict["input"]
        self._set_input_path(input_path)

        print("Analyzing the input data...")
        
        # Load user input data and set/check several parameters on the app 
        # operation and on the definition of the areas of interest.
        # The input data may come from a database, a shapefile, kml files or 
        # from a csv file. 
        # The attributes set are:
        #   - self._user_df: stores the input data.
        #   - self._op_mode: the operation mode: 1 - matchup; 2 - time series; 
        #       3 - database/monitoring.
        #   - self._aoi_mode: 0 - areas of interest are defined from the input 
        #       data; 1 - they are defined from kml files.
        #   - self._aoi_radius: for aoi_mode=0, which radius should be applied 
        #       around the point coordinates.
        #   - self._demand_codes: the codes describing the pipelines of data 
        #       demand that will be executed for each area of interest.
        #   - self._geedar_db: the object that intermediates data storing and 
        #       retrieving with the target database (mode 3 only).
        # Each demand code is a dictionary describing a demand: the product to 
        # be used and the cloud algorithm, reducer and local algorithm to be 
        # applied.
        self._setup_operation()
                
        # Set '_time_window", an attribute that defines how many days before
        # and after the target dates are valid for matching up the satellite
        # images.
        self._set_time_window()
        
        # Validate the user input data.
        self._validate_user_df()
        if self._time_window > 0 and self._op_mode == 1:
            print("The input data was expanded to meet the argument for the "
                + "'time window' (" + str(self._time_window) + ").")
        
        # Set attributes for output path: 'output_path', '_output_dir' and 
        # '_output_file'.
        output_path = options_dict["output"]
        self._set_output_path(output_path)
                
        # Build 'demand_df', a dataframe describing the data demands to be 
        # sent to the server.
        print("Preparing the demand dataframe...")
        self._build_demand_df()
        
        # Build the dataframe to be used a the base for the result dataframe.
        print("Preparing the primer dataframe...")
        self._build_primer_df()
        
        # Update the database for products, algorithms etc. (if in mode 3).
        if self._op_mode >= 3:
            print("Updating basic tables in the database...")
            self._update_db()
                
        # Set '_separate_cols', which indicates if an extra csv file should be 
        # saved with results with different demand codes in separate columns.
        # The default behavior is to combine all results in common columns 
        # (ex: a single result column for the "red" band).
        self._set_separate_cols()
        
        # Sets _proc_dict: a dictionay which will hold processing parameters
        # and auxilliary data for supporting the progressive building of the 
        # result data frame.
        # First, try to load the dict from a cache file (for interrupted 
        # executions). If not found, build the dict.
        print("Building the processing dictionary...")
        self._set_proc_dict()
        # Save _'proc_dict' to cache.
        self._update_cache()
                
        print("Ok. Ready for demand execution.\n")
    
    @property
    def result_df(self):
        proc_dict = self._proc_dict
        if proc_dict["result"]["finished"]:
            return proc_dict["result"]["result_df"]
        else:
            print("Not all demands were processed yet.")
            return

    # Validates the constructor arguments and sets them as attributes.
    def _validate_args(self, args):        
        # Options.
        if type(args["user_options"]).__name__ != "UserOptions":
            raise TypeError("'user_options' must be an instance of the " 
                + "class UserOptions.")
        # Default demand code.
        default_demand_code = args["default_demand_code"]
        if default_demand_code is not None:
            if isinstance(default_demand_code, list):
                if not all(isinstance(c, str) for c in default_demand_code):
                    raise TypeError("'default_demand_code' must be a list of "
                        + "strings. Ex: ['P311C15L0R1','P312C15L0R1'].")
            else:
                if not isinstance(default_demand_code, str):
                    raise TypeError("'default_demand_code' must be a list or "
                        + "a list-like string. Ex: "
                        + "'[P311C15L0R1,P312C15L0R1]'.")
                default_demand_code = str_to_list(default_demand_code, 
                    opening = "[", closing = "]", optional_enclosing=True)
        # Database configuration.
        db_config = args["db_config"]
        if db_config is not None:
            if not isinstance(db_config, dict):
                raise TypeError("'db_config' must be a dict.")
            required_keys = ["conn_dict", "db_names"]
            if not all(k in db_config for k in required_keys):
                raise TypeError("'db_config' must have these keys: "
                    + str(required_keys) + ".")            
        # Cache file for storing the results from the ongoing processing.
        app_cache_file = self._app_cache_file
        cache_file = args["cache_file"]
        if cache_file is not None:
            if isinstance(cache_file, bool):
                if cache_file:
                    cache_file = app_cache_file
                else:
                    cache_file = None
            elif not isinstance(cache_file, str):
                raise TypeError("'cache_file' must be a string.")
        
        # "Catalog-type" parameters.
        catalogs = {
            "name": ["product_catalog", "cloud_algo_catalog", 
                    "local_algo_catalog", "reducer_catalog", 
                    "instrument_catalog", "variable_catalog"],
            "class": ["Product", "CloudAlgorithm", 
                    "LocalAlgorithm", "Reducer", 
                    "Instrument", "Variable"]
        }
        for catalog_ind in range(len(catalogs["name"])):
            catalog_name = catalogs["name"][catalog_ind]
            catalog_type = catalogs["class"][catalog_ind]
            catalog = args[catalog_name]
            if not isinstance(catalog, dict):
                raise TypeError("'" + catalog_name + "' must be a dict.")
            else:
                if any(type(catalog[c]).__name__ != catalog_type 
                        for c in catalog):
                    raise TypeError("'" + catalog_name + "' must be a dict of " 
                        + catalog_type + " objects.")               
        # Save attributes:
        self._args = args
        self._options_dict = args["user_options"].options_dict
        self._cache_file = cache_file
        self._default_demand_code = default_demand_code
        self._db_config = db_config
    
    # Sets input path attributes.
    def _set_input_path(self, input_path):
        options_dict = self._options_dict
        op_mode = options_dict["mode"]
        
        if op_mode >= 3:
            if input_path != "":
                if input_path.lower() != "geedar_db":
                    print("(!) Since you are running GEEDaR in database mode, "
                        + "the path to an input file will be ignored.")        
            input_path = "geedar_db"
        elif input_path == "":
            raise ValueError("An input path was not provided.")
        
        splitted_path = os.path.split(input_path)
        input_dir = splitted_path[0]
        input_file = splitted_path[1]        
        self._input_file = input_file
        self._input_dir = input_dir
        self._input_path = input_path        

    # Sets output path attributes.
    def _set_output_path(self, output_path):
        op_mode = self._op_mode
        
        # Is the path syntactically valid?
        if not is_path_valid(output_path):
            raise ValueError("Nonexistent or invalid output path: '"
                + output_path + "'.")
        if op_mode >= 3 and output_path.lower() == "auto":
            output_path = "geedar_db"
            output_dir = ""
            output_file = output_path
        else:
            input_dir = self._input_dir
            if output_path.lower() == "auto":
                output_path = os.path.join(input_dir, ("geedar_output_" 
                    + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"))
            # Warn about the file extension, if not csv.
            elif output_path[-4:].lower() != ".csv":
                print("The name you provided for the output file does not "
                    + "have a .csv extension, but be aware that the file "
                    + "will be formatted like a csv.")
            splitted_path = os.path.split(output_path)
            output_dir = splitted_path[0]
            output_file = splitted_path[1]
            if output_dir == "":
                output_dir = input_dir
                output_path = os.path.join(output_dir, output_file)
        
        self._output_file = output_file
        self._output_dir = output_dir
        self._output_path = output_path    

    # Sets the _separate_cols attribute.
    def _set_separate_cols(self):
        self._separate_cols = self._options_dict["separate"]    
            
    # Checks if the user provided demand codes match the available products,
    # algorithms and reducers and return them as a list of dicts.
    def _validate_demand_codes(self, demand_codes_strlist):
        product_catalog = self._args["product_catalog"]
        cloud_algo_catalog = self._args["cloud_algo_catalog"]
        local_algo_catalog = self._args["local_algo_catalog"]
        reducer_catalog = self._args["reducer_catalog"]
        
        product_codes = [product_catalog[p].product_code 
            for p in product_catalog]
        cloud_algo_codes = [cloud_algo_catalog[a].algo_code 
            for a in cloud_algo_catalog]
        local_algo_codes = [local_algo_catalog[a].algo_code 
            for a in local_algo_catalog]
        reducer_codes = [reducer_catalog[r].reducer_code 
            for r in reducer_catalog]
        
        demand_codes = []
        for code_as_str in demand_codes_strlist:            
            code_as_dict = Demand.unfold_demand_code(code_as_str)
            # Check product
            if code_as_dict["P"] not in product_codes:
                raise ValueError("This product code does not match the ones "
                    + "available in the catalog loaded to GEEDaR: "
                    + str(code_as_dict["P"]) + ".")
            # Check cloud algo
            if code_as_dict["C"] not in cloud_algo_codes:
                raise ValueError("This cloud algorithm code does not match "
                    + "the ones available in the catalog loaded to GEEDaR: "
                    + str(code_as_dict["C"]) + ".")
            # Check local algo
            if code_as_dict["L"] not in local_algo_codes:
                raise ValueError("This local algorithm code does not match "
                    + "the ones available in the catalog loaded to GEEDaR: "
                    + str(code_as_dict["L"]) + ".")
            # Check reducer
            if code_as_dict["R"] not in reducer_codes:
                raise ValueError("This reducer code does not match "
                    + "the ones available in the catalog loaded to GEEDaR: "
                    + str(code_as_dict["R"]) + ".")
            demand_codes = demand_codes + [code_as_dict]
            
        return demand_codes
        
    # Sets the _time_window attribute.
    def _set_time_window(self):
        op_mode = self._op_mode
        options_dict = self._options_dict
        time_window = options_dict["timewindow"]
        
        if op_mode >= 2:
            if time_window != 0:
                print("(!) 'time_window' can only be defined for operation "
                    + "mode 1.")
            time_window = 0
        self._time_window = time_window

    # Loads the input data and defines parameters of operation, the demand 
    # pipeline and the delimitation of the areas of interest.
    def _setup_operation(self):
        input_path = self._input_path
        input_dir = self._input_dir
        input_file = self._input_file
        options_dict = self._options_dict
        demand_cols_dict = self._demand_cols_dict
        matchup_cols_dict = self._matchup_cols_dict
        db_config = self._db_config
        demand_codes_strlist = options_dict["code"]        
        op_mode = options_dict["mode"]
        aoi_mode = int(options_dict["kml"])
        radius = options_dict["radius"]
        user_df = None
        geedar_db = None
        
        # Load input data.
        
        # If len(input_file) >= 5: the provided string may be a filename with 
        # typical extension (csv, kml, kmz).
        if len(input_file) >= 5:
            
            # If it is a kml file...
            # Build the user dataframe from kml file(s). The station id.
            # is defined from the file name. Internal names of geometries 
            # are ignored.
            # Enforce pertaining options.
            if input_file[-4:].lower() in [".kml", ".kmz"]:
                if not op_mode in [0, 2]:
                    print("(!) Since your input file(s) is .kml, the "
                        + "operation will be enforced to mode 2.")
                op_mode = 2
                aoi_mode = 1
                if radius != -1:
                    print("(!) Since your input file(s) is .kml, the "
                        + "radius parameter will be ignored.")
                radius = -1
                
                if input_file.lower() in ["*.kml", "*.kmz"]:
                    kml_files = [f for f in os.listdir(input_dir) 
                        if os.path.isfile(os.path.join(input_dir, f)) 
                        and f[-4:].lower() in [".kml", ".kmz"]]
                else:
                    kml_files = [input_file]
                # Build a data frame.
                n_kml_files = len(kml_files)
                if n_kml_files == 0:
                    raise FileNotFoundError("No kml file was found in the " 
                        + "target folder: " + input_dir + ".")
                user_df = pandas.DataFrame(columns = ["station_code",
                    "station_name", "start_date", "end_date"])
                for i in range(n_kml_files):
                    fname = kml_files[i][:-4]
                    fname_parts = fname.split(" - ")
                    station_code = fname_parts[0]
                    if len(fname_parts) > 1:
                        station_name = "".join(fname_parts[1:])
                    else:
                        station_name = ""
                    user_df.loc[i] = [station_code, station_name, 
                        "auto", "auto"]
            
            # Input data is in a shapefile. The attribute table must 
            # contain the same miminum data expected for a CSV input file.
            elif input_file[-4:] == ".shp":
                if aoi_mode == 1:
                    print("(!) You provided a shapefile, but added the kml "
                        + "parameter. Incompatible options.")
                aoi_mode = 0
                raise ValueError("Shapefile input not implemented yet.")
                # user_df = stations_from_shp(input_path)
            
            # Import demands from the database.
            elif op_mode == 3 or (op_mode == 0 and input_path == "geedar_db"):
                if input_path not in ["", "geedar_db"]:
                    print("(!) Since you've chosen operation mode 3 (database "
                        + "mode), the input file will be ignored.")
                input_path = "geedar_db"
                op_mode = 3
                
                if aoi_mode == 1 or radius != -1:
                    print("(!) Since you've chosen operation mode 3 (database "
                        + "mode, the parameters pertaining to the "
                        + "delimitation of the area of interest will be "
                        + "ignored.")
                aoi_mode = -1
                radius = -1
                
                # Instantiate GeedarDB.
                if db_config is None:
                    raise ValueError("For operation mode 3 (database mode), "
                        + "the parameter 'db_config' must be provided when "
                        + "initializing GeedarApp.")                
                geedar_db = GeedarDB(conn_dict=db_config["conn_dict"], 
                    db_names=db_config["db_names"])
                
                # Get demand data.
                demand_table = geedar_db.get_demands(update_start_date=True)
                # Rename columns to the default demand_df names.
                user_df = demand_table.rename(
                    columns={v[0]:k for k,v in demand_cols_dict.items() 
                    if len(v) > 0})
           
            # CSV file.
            elif input_file[-4:] == ".csv":
                user_df = pandas.read_csv(input_path)
        
        # If none of the above, try to read a tabulated text file (no 
        # extension restriction).
        if user_df is None:
            user_df = pandas.read_table(input_path)        

        # The user_df columns.
        user_cols = [c.lower() for c in [*user_df.columns]]

        # Ensure the definition of the operation mode.        
        if op_mode == 0:
            start_date_cols = demand_cols_dict["start_date"]
            end_date_cols = demand_cols_dict["end_date"]
            single_date_cols = matchup_cols_dict["date"]
            
            if (any(c in user_cols for c in start_date_cols) 
                    and any(c in user_cols for c in end_date_cols)):
                # Time series mode:
                op_mode = 2
            elif any(c in user_cols for c in single_date_cols):
                # Matchup mode:
                op_mode = 1
            else:
                raise ValueError("Could not determine the operation mode.")                
        
        # Ensure the definition of aoi_mode.
        aoi_mode_cols = demand_cols_dict["aoi_mode"]
        aoi_col = False
        if any(c in user_cols for c in aoi_mode_cols):
            aoi_col = True
        if not aoi_col and aoi_mode == -1:
            raise ValueError("A column for 'aoi_mode' should be in the "
                +"input data.")
        elif aoi_col:
            if aoi_mode == 1: # Shouldn't it be aoi_mode >= 0 ?
                print("(!) Since your input data contains a column "
                    + "'aoi_mode', the corresponding command line parameter "
                    + "will be ignored.")
            aoi_mode = -1
        elif "geojson" in user_cols:            
            if aoi_mode == 1:
                print("(!) Since your input data contains a column "
                    + "'geojson', the command line parameter for reading "
                    + "kml file(s) will be ignored.")
            aoi_mode = 0
        
        # Check AoI radius.
        radius_cols = demand_cols_dict["aoi_radius"]
        if any(c in user_cols for c in radius_cols):
            if radius >= 0:
                print("(!) Since your input data contains a column for the "
                    + "'radius', the command line parameter will be "
                    + "ignored.")
                radius = -1
        else:
            # Use default radius value?
            if radius == -1 and aoi_mode <= 0:
                radius = _AOI_DEFAULT_RADIUS
                print("No radius value informed. Using the default value: "
                    + str(radius) + ".")

        # Check demand codes.        
        if demand_codes_strlist == ["auto"]:
            # Definition and validation will occur in _validate_user_df.
            demand_codes = None
        elif op_mode >= 3:
            print("(!) Since you are starting GEEDaR in database "
                + "mode, you should not provide demand code(s).")
            demand_codes = None
        else:
            # Get a list of the validated codes.
            demand_codes = self._validate_demand_codes(
                demand_codes_strlist)
        
        self._op_mode = op_mode
        self._aoi_mode = aoi_mode
        self._aoi_radius = radius
        self._user_df = user_df
        self._demand_codes = demand_codes
        self._geedar_db = geedar_db

    # Validates the user input csv file.
    def _validate_user_df(self):
        op_mode = self._op_mode
        user_df = self._user_df
        if user_df is None:
            self._validated_user_df = None
            return
        if len(user_df) == 0:
            if op_mode >= 3:
                sys.exit("No demand records in the database yet.")
            else:
                print("No row to process in the input file.")
                raise ValueError("Missing input data.")
        input_dir = self._input_dir
        aoi_mode = self._aoi_mode
        if aoi_mode is None:
            aoi_mode = -1 # Must be defined in the input file.
        radius = self._aoi_radius
        if radius is None:
            radius = -1
        demand_codes = self._demand_codes
        demand_cols_dict = self._demand_cols_dict
        matchup_cols_dict = self._matchup_cols_dict
        time_window = self._time_window
        if time_window is None:
            time_window = 0
        
        df = user_df.copy()
        df.reset_index(drop=True, inplace=True)        
        user_cols = [str(c) for c in df.columns]
        user_lower_cols = [str(c).lower() for c in df.columns]
        base_cols = ["station_code", "station_name", "lat", "long"]
        if op_mode == 1:
            date_cols = ["date"]
            exclusive_demand_cols = []
        else:
            date_cols = ["start_date", "end_date"]
            exclusive_demand_cols = ["demand_id", "status", "station_id"]
        
        demand_code_cols = ["product_code", "cloud_algo_code", 
            "local_algo_code", "reducer_code"]
        aoi_related_cols = ["aoi_mode", "aoi_radius", "kml_path"]       
        future_primer_df_cols = ["demand_code", "img_date", "img_time"]
        user_demand_cols_dict = dict()
        user_demand_code_cols_dict = dict()
        user_extra_cols_dict = dict()
        if op_mode == 1:
            # Map extra (non-default) columns.
            matchup_ref_cols = [c for lst in matchup_cols_dict.values() 
                for c in lst]
            demand_ref_cols = [c for lst in demand_cols_dict.values() 
                for c in lst]
            user_extra_cols_dict = {c:c for c in df.columns 
                if str(c).lower() not in matchup_ref_cols + demand_ref_cols 
                + future_primer_df_cols}            

        # Reference for validating (further below) the minimum required
        # columns.
        if op_mode == 1:
            if aoi_mode == 1:
                ref_cols = {"id": matchup_cols_dict["id"], 
                    "date": matchup_cols_dict["date"]}
            elif aoi_mode == 0:
                ref_cols = {"lat": matchup_cols_dict["lat"], 
                    "long": matchup_cols_dict["long"],
                    "date": matchup_cols_dict["date"]}
            else:
                ref_cols = {"id": matchup_cols_dict["id"], 
                    "lat": matchup_cols_dict["lat"], 
                    "long": matchup_cols_dict["long"],
                    "date": matchup_cols_dict["date"],
                    "aoi_mode": matchup_cols_dict["aoi_mode"]}      
        else:            
            if aoi_mode == 1:
                ref_cols = {"id": demand_cols_dict["station_code"]
                    + demand_cols_dict["station_name"],
                    "start_date": demand_cols_dict["start_date"], 
                    "end_date": demand_cols_dict["end_date"]}
            elif aoi_mode == 0:
                ref_cols = {"start_date": demand_cols_dict["start_date"], 
                    "end_date": demand_cols_dict["end_date"], 
                    "lat": demand_cols_dict["lat"],
                    "long": demand_cols_dict["long"]}
            else:
                ref_cols = {"id": demand_cols_dict["station_code"]
                    + demand_cols_dict["station_name"],
                    "start_date": demand_cols_dict["start_date"], 
                    "end_date": demand_cols_dict["end_date"],
                    "lat": demand_cols_dict["lat"],
                    "long": demand_cols_dict["long"],
                    "aoi_mode": demand_cols_dict["aoi_mode"]}
            
        # Check minimum required columns.
        if not all(any(validcols in user_lower_cols for validcols in testlist) 
                for testlist in [*ref_cols.values()]):
            about_ext_geom = ""
            if aoi_mode in [-1, 1]:
                about_ext_geom = ("Note that, if you've chosen to define the "
                    + "delimitation of the stations from external files then "
                    + "the input csv must have, at least a column to identify "
                    + "the station, whose content must match the file names. ")
            raise ValueError(about_ext_geom + "The input file should have "
                + "the columns: " + str([*ref_cols]) + ".")

        # Map the columns pertaining to demand and operation.
        for k,v in demand_cols_dict.items():
            demand_col = [c for c in df.columns if str(c).lower() in v]
            if len(demand_col) > 0:
                user_demand_cols_dict[k] = demand_col[0]
        # Filter for the "code columns" only.
        user_demand_code_cols_dict = {
            k:v for k,v in user_demand_cols_dict.items() 
            if k in demand_code_cols}
        # Check: either all or no demand-code column is accepted.
        if len(user_demand_code_cols_dict) > 0 and not all(
                c in user_demand_code_cols_dict for c in demand_code_cols):
            raise ValueError("You provided insufficient columns "
                + "describing the demand. Missing columns: " 
                + str([c for c in demand_code_cols 
                if c not in user_demand_code_cols_dict]))
            
        # Build the new dataframe, initially with the basic columns only.
        # Note the 'geojson' column, which will store the string that codes 
        # the GeoJSON defining each station's area of interest (AoI).
        # For mode 1, two more columns will be added further below: 'img_date'
        # and 'img_time'.
        new_df_dtypes = ({"station_code": "string", "station_name": "string", 
        "lat": "Float32", "long": "Float32", "product_code": "Int16",
        "cloud_algo_code": "Int16", "local_algo_code": "Int16",
        "reducer_code": "Int16", "demand_code": "string", 
        "aoi_mode": "Int8", "aoi_radius": "Int16","kml_path": "string", 
        "geojson": "string"} | {k:"string" for k in date_cols})
        new_df = pandas.DataFrame(columns = exclusive_demand_cols + base_cols 
            + date_cols + demand_code_cols + aoi_related_cols 
            + [*user_extra_cols_dict] + ["geojson", "demand_code"], 
            index=df.index).astype(new_df_dtypes)
        
        # Set the first (exclusive) demand columns (if any).
        for k in exclusive_demand_cols:
            ref_cols = demand_cols_dict[k]
            cols = [c for c in user_cols if c.lower() in ref_cols]
            if len(cols) > 0:
                new_df[k] = df[cols[0]]
        
        # Set the column for the station name.
        name_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["station_name"]]
        if len(name_col) > 0:
            new_df["station_name"] = df[name_col[0]]
        
        # Set lat and long columns.
        lat_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["lat"]]
        long_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["long"]]
        if len(lat_col) > 0:
            new_df["lat"] = df[lat_col[0]]
        if len(long_col) > 0:
            new_df["long"] = df[long_col[0]]
        
        # Set the column for the station code.
        id_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["station_code"]]
        if len(id_col) == 0:
            if len(name_col) > 0:
                new_df["station_code"] = new_df["station_name"]
            elif aoi_mode == 0:
                lat_long_str_series = (new_df["lat"].astype("string") 
                    + new_df["long"].astype("string"))
                station_list = list(lat_long_str_series.unique())
                new_df["station_code"] = lat_long_str_series.apply(
                    lambda s: str(station_list.index(s) + 1)).astype(
                    "string")
        else:
            new_df["station_code"] = df[id_col[0]]
            # Replace NA, None or "" for the station name (if any) or row numb.
            for i in new_df.index:
                code = new_df.loc[i, "station_code"]
                name = new_df.loc[i, "station_name"]
                lat = new_df.loc[i, "lat"]
                long = new_df.loc[i, "long"]
                if (pandas.isna(code) or code == ""): 
                    if not (pandas.isna(name) or name == ""):
                        new_df.loc[i, "station_code"] = name
                    elif (not (pandas.isna(lat) or lat == ""  
                            or pandas.isna(long) or long == "")
                            and aoi_mode == 0):
                        new_df.loc[i, "station_code"] = ("[" + str(lat) + "," 
                            + str(long) + "]")

        # Fill empty station names.
        new_df["station_name"] = new_df["station_name"].fillna(
            new_df["station_code"])
                
        # Set date columns.        
        if op_mode == 1:
            date_col = [c for c in df.columns 
                if str(c).lower() in matchup_cols_dict["date"]][0]
            new_df["date"] = df[date_col]
        else:
            start_date_col = [c for c in df.columns 
                if str(c).lower() in demand_cols_dict["start_date"]][0]
            new_df["start_date"] = df[start_date_col]
            end_date_col = [c for c in df.columns 
                if str(c).lower() in demand_cols_dict["end_date"]][0]
            new_df["end_date"] = df[end_date_col]
                        
        # Check date and coordinate formats.
        for i in new_df.index:
            # Lat/long.
            if (pandas.notna(new_df.loc[i, "lat"]) 
                    and pandas.notna(new_df.loc[i, "long"])):
                try:
                    float(new_df.loc[i, "lat"])
                    float(new_df.loc[i, "long"])
                except:
                    if aoi_mode <= 0:
                        print("(!) Invalid coordinates in the input file: " 
                            + "row #" + str(i) + ".")
                    new_df.loc[i, "lat"] = pandas.NA
                    new_df.loc[i, "long"] = pandas.NA
            # Dates.
            for date_col in date_cols:
                date_val = new_df.loc[i, date_col]
                if str(date_val).replace(" ", "").lower() in ["auto", "", 
                        "nan", "<na>", "nat", "none", "nonetype"]:
                    if op_mode == 1:
                        print("(!) Missing date in the input file: row #" 
                            + str(i) + ".")
                    new_df.loc[i, date_col] = pandas.NA
                else:
                    try:
                        pandas.to_datetime(date_val, format="%Y-%m-%d")
                    except:
                        print("(!) Invalid date in the input file: row #" 
                            + str(i) + ".")
                        new_df.loc[i, date_col] = "invalid"
        
        # Fill other demand columns.
        other_demand_cols_dict = {k:v for k,v in user_demand_cols_dict.items() 
            if k not in base_cols + date_cols}
        for k,v in other_demand_cols_dict.items():
            new_df[k] = df[v]        
        
        # Fill extra columns.
        for k,v in user_extra_cols_dict.items():
            new_df[k] = df[v]
        
        # Was the column 'demand_code' provided? If so, it will be used further 
        # below to retrieve the separate codes for product, cloud algo. etc.
        orig_demand_code_col = [c for c in df.columns 
            if str(c).lower() == "demand_code"]
        if len(orig_demand_code_col) > 0:
            new_df["demand_code"] = df[orig_demand_code_col[0]]
        
        # For mode 1, two more columns are inserted: 'img_date' and 'img_time'.
        # For mode 2, they will be inserted later, when building 'primer_df'  
        # in the method '_build_primer_df'.
        if op_mode == 1:        
            new_df["img_date"] = new_df["date"]
            new_df["img_time"] = pandas.Series(index=new_df.index, 
                dtype="string")
        
        # Check columns and parameters pertaining to the definition of the 
        # area of interest (AoI).
        
        aoi_mode_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["aoi_mode"]]
        path_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["kml_path"]]
        radius_col = [c for c in df.columns 
            if str(c).lower() in demand_cols_dict["aoi_radius"]]
        
        # Area of interest (AoI).
        if len(aoi_mode_col) > 0:
            aoi_mode = -1
            new_df["aoi_mode"] = df[aoi_mode_col[0]].copy()
            # Check aoi values.
            for i in new_df["aoi_mode"].index:
                if str(new_df.loc[i, "aoi_mode"]) not in ["0", "1"]:
                    new_df.loc[i, "aoi_mode"] = pandas.NA
            new_df["aoi_mode"] = new_df["aoi_mode"].astype("Int8")
        else:
            if aoi_mode == -1:
                raise ValueError("Since no column was provided for 'aoi_mode' "
                    + "in the input data, it should have been defined in the "
                    + "command line.")
            new_df["aoi_mode"] = pandas.Series(data=aoi_mode, index=df.index, 
                dtype="Int8")

        # Check the radius for point AoIs.
        if len(radius_col) > 0:
            radius = -1            
            new_df["aoi_radius"] = df[radius_col[0]].copy()
            # Check values.
            for i in new_df["aoi_radius"].index:
                if not str(new_df.loc[i, "aoi_radius"]).isnumeric():
                    new_df.loc[i, "aoi_radius"] = pandas.NA
            new_df["aoi_radius"] = new_df["aoi_radius"].astype("Int16")
        else:
            new_df["aoi_radius"] = pandas.Series(data=radius, index=df.index, 
                dtype="Int16")
        new_df.loc[new_df["aoi_mode"] == 1, "aoi_radius"] = pandas.NA
        
        # Set kml path series.
        # First, normalize entries.
        if len(path_col) > 0 and aoi_mode != 0:
            new_df["kml_path"] = df[path_col[0]].copy().astype("string")
            # Normalize non-path values.
            for i in new_df.index:
                if pandas.isna(new_df.loc[i, "kml_path"]):
                    new_df.loc[i, "kml_path"] = "auto"
                elif new_df.loc[i, "kml_path"].replace(" ", "").lower() in [
                        "auto", "", "nan", "<na>", "nat", "none", "nonetype"]:
                    new_df.loc[i, "kml_path"] = "auto"
        else:
            new_df["kml_path"] = pandas.Series(data="auto", index=df.index, 
                dtype="string")
            new_df.loc[new_df["aoi_mode"] == 0, "kml_path"] = pandas.NA
        # Then validate paths.
        for i in [ind for ind in new_df.index 
                if pandas.notna(new_df.loc[ind, "kml_path"])]:
            if new_df.loc[i, "kml_path"] == "auto":
                exts = ["kml", "kmz"]
                names = [new_df.loc[i, "station_code"], 
                    new_df.loc[i, "station_name"], 
                    new_df.loc[i, "station_code"] 
                    + " - " + new_df.loc[i, "station_name"]]
                folders = [input_dir, os.path.join(input_dir, "KML"), 
                    os.curdir, os.path.join(os.curdir, "KML")]
                full_paths = [os.path.join(f, n + "." + e) 
                    for e in exts for n in names for f in folders]
                for full_path in full_paths:
                    if is_path_valid(full_path):
                        if os.path.isfile(full_path):
                            new_df.loc[i, "kml_path"] = full_path
                            break
                if new_df.loc[i, "kml_path"] == "auto":
                    new_df.loc[i, "kml_path"] = pandas.NA
                    print("(!) Could not find external file with the "
                        + "geometry for the station " 
                        + str(new_df.loc[i, "station_code"] + " (row #")
                        + str(i) + ").")
                    
        # Check and fill demand codes.
        # If the user provided demand codes in command line arguments, use 
        # them (replicating the dataframe); if the codes were provided in the 
        # input file, use them (joining the separate codes, if necessary); if 
        # both were provided or none, raise an error. It is not accepted, 
        # either, the inclusion of both the 'demand_code' column and the 
        # separate columns describing the demand ('product_code', 
        # 'cloud_algo_code', 'local_algo_code' and 'reducer_code').
        
        user_sep_demand_code_cols = False
        user_demand_code_col = False
        
        if all(c in [*df.columns] for c in demand_code_cols):
               user_sep_demand_code_cols = True
        
        if len(orig_demand_code_col) > 0:
            user_demand_code_col = True

        if user_sep_demand_code_cols and user_demand_code_col:
            raise ValueError("You provided both the column 'demand_code' and "
                + "the separate columns describing the demand: "
                + "'product_code', 'cloud_algo_code', 'local_algo_code' and "
                + "'reducer_code'. For avoiding ambiguities, only one source "
                + "is accepted.")
                
        if demand_codes is None:
            demand_codes = []
        
        if len(demand_codes) == 0 and not (
                user_sep_demand_code_cols or user_demand_code_col):
            # Was a default code provided in instantiation?
            default_demand_code = self._args["default_demand_code"]
            if default_demand_code is None:
                raise ValueError("You have not provided a demand code and "
                    + "a default one was not defined when "
                    + "instantiating 'GeedarApp'.")            
            # Are the demand codes valid? Get a list of the validated codes.
            demand_codes = self._validate_demand_codes(default_demand_code)
            if len(demand_codes):
                raise ValueError("You did not provide demand codes in either "
                    + "the command line or in the input file.")
        
        if len(demand_codes) > 0 and (
                user_sep_demand_code_cols or user_demand_code_col):
            raise ValueError("You provided demand codes in both the "
                + "command line and in the input file. For avoiding "
                + "ambiguities, only one source is accepted.")
        
        # Demand codes provided in the command line.
        if len(demand_codes) > 0:
            concat_list = []
            for demand_code in demand_codes:
                tmp_df = new_df.copy()
                demand_code_str = Demand.join_codes(demand_code)
                tmp_df["demand_code"] = demand_code_str
                tmp_df["product_code"] = demand_code["P"]
                tmp_df["cloud_algo_code"] = demand_code["C"]
                tmp_df["local_algo_code"] = demand_code["L"]
                tmp_df["reducer_code"] = demand_code["R"]                    
                concat_list.append(tmp_df)
            new_df = pandas.concat(concat_list)
            new_df.reset_index(drop=True, inplace=True)
        # Demand codes provided as separate columns in the input file.
        elif user_sep_demand_code_cols:
            # Check NAs and fill the column 'demand_code'.
            for i in new_df.index:
                if all([*pandas.notna(new_df.loc[i, demand_code_cols])]):
                    new_df.loc[i, "demand_code"] = Demand.join_codes(
                        dict(zip(["P","C","L","R"], 
                        list(new_df.loc[i, demand_code_cols]))))            
            demand_code_strs = list(new_df.loc[pandas.notna(
                new_df["demand_code"]), "demand_code"].unique())
            if len(demand_code_strs) == 0:
                raise ValueError("No valid demand code combination in the "
                    + "input file.")
            self._validate_demand_codes(demand_code_strs)
        # Demand codes provided as a combined string in column 'demand_code'.
        elif user_demand_code_col:
            demand_code_strs = list(new_df.loc[pandas.notna(
                new_df["demand_code"]), "demand_code"].unique())
            self._validate_demand_codes(demand_code_strs)
            new_df[demand_code_cols] = df["demand_code"].apply(
                lambda codestr: list(Demand.unfold_demand_code(
                codestr).values()) if pandas.notna(codestr) else pandas.NA)
        
        # Invalid rows will be removed.        
        invalid_rows = []
        
        # Drop rows without identification.
        invalid_rows.extend(which(pandas.isna(new_df["station_code"])))
        # Drop rows without a demand code.
        invalid_rows.extend(which(pandas.isna(new_df["demand_code"])))
        # Drop rows with missing/invalid date.
        for col in date_cols:
            invalid_rows.extend(which(new_df[col] == "invalid"))
        if op_mode == 1:
            invalid_rows.extend(which(pandas.isna(new_df["date"])))
        # Drop rows without enough info for AoI definition.
        invalid_rows.extend(which(pandas.isna(new_df["aoi_mode"])))
        invalid_rows.extend(which((pandas.isna(new_df["kml_path"])) 
            & (new_df["aoi_mode"] == 1)))
        invalid_rows.extend(which((new_df["aoi_mode"] == 0) 
            & ((new_df["aoi_radius"] < 0) | (pandas.isna(new_df["lat"])) 
            | (pandas.isna(new_df["long"])))))
        
        # Check remaining rows.
        invalid_rows = list(set(invalid_rows))        
        if len(new_df) == len(invalid_rows):
            raise ValueError("No row will remain for processing after "
                + "removing the invalid ones from the input file.")
        
        # Report invalid rows.
        if len(invalid_rows) > 0:
            print("(!) These invalid rows in the input file will not be "
                + "included in the result file: " + str(invalid_rows) + ".")
            r = input("Do you want to continue? y/[n]")
            if r.replace(" ", "").lower() != "y":
                sys.exit(0)
            new_df.drop(invalid_rows)

        # Reset the index.
        new_df.reset_index(drop=True, inplace=True)
        
        # Add the adjacents dates according to the time window.
        nrows = len(new_df)
        if time_window > 0 and op_mode == 1:
            window_size = 1 + (time_window * 2)
            future_nrows = nrows * window_size
            tmp_df = pandas.DataFrame(index=range(future_nrows), 
                columns=new_df.columns)
            row_j = 0
            for row_i in range(nrows):
                date_j = (pandas.Timestamp(new_df.loc[row_i, "date"]) 
                    - pandas.Timedelta(time_window, "day"))
                for window_i in range(window_size):
                    tmp_df.iloc[row_j] = new_df.iloc[row_i]
                    tmp_df.loc[row_j, "img_date"] = date_j.strftime(
                        "%Y-%m-%d")
                    date_j = date_j + pandas.Timedelta(1, "day")
                    row_j = row_j + 1
            new_df = tmp_df
            # Reset the index once more.
            new_df.reset_index(drop=True, inplace=True)

        # Create or validate GeoJSON strings for each station.
        # Because a complex geometry is described by a very long string, the 
        # string is saved only for the first row of ocurrence of each station.
        # That avoids producing a too large dataframe.
        # This loop is also used to warn about the existence of divergences in 
        # the values of a parameter for the same station (aoi, radius...).
        station_geoms = dict()
        for i in new_df.index:
            station_code = new_df.loc[i, "station_code"]
            local_aoi_mode = new_df.loc[i, "aoi_mode"]
            local_radius = new_df.loc[i, "aoi_radius"]
            lat = new_df.loc[i, "lat"]
            long = new_df.loc[i, "long"]
            geojson_str = new_df.loc[i, "geojson"]
            geojson = None
            
            # AoI already defined for this station.
            if station_code in station_geoms:
                first_row = station_geoms[station_code]
                new_df.loc[i, "geojson"] = "idem"
                if pandas.notna(new_df.loc[first_row, "kml_path"]):
                    new_df.loc[i, "kml_path"] = "idem"
                else:
                    new_df.loc[i, "kml_path"] = pandas.NA
                cols = ["aoi_mode", "aoi_radius"]
                for col in cols:                
                    new_df.loc[i, col] = new_df.loc[first_row, col]                
                continue

            # If a GeoJSON string is already in the input data, validated it.
            if pandas.notna(geojson_str):
                try:
                    geojson = ee.Geometry(json.loads(geojson_str)).getInfo()
                except Exception as e:
                    print(e)
                    raise ValueError("Invalid GeoJSON in row #" + str(i) + ".")
                new_df.loc[i, "geojson"] = json.dump(geojson)
                new_df.loc[i, "kml_path"] = pandas.NA
                        
            # Extract geometry from external file.
            if pandas.notna(new_df.loc[i, "kml_path"]):
                # Try to extract geometry. Priority order is MultiPolygon, 
                # MultiLineString and MultiPoint. Only the first found 
                # geometry is used.
                try:
                    gdict = extract_from_kml(new_df.loc[i, "kml_path"], 
                        what="geojson", aggregate=True)
                    gorder = ["MultiPolygon", "MultiLineString", "MultiPoint"]
                    for g in gorder:                    
                        if g in gdict:
                            if len(gdict[g]) > 1:
                                print("(!) Only the first " + g + " extracted "
                                    + "from '" + new_df.loc[i, "kml_path"] 
                                    + "' will be used.")
                            geojson = gdict[g][0]
                            if (g in ["Point", "MultiPoint"] and
                                    local_aoi_mode == 0 and not 
                                    pandas.isna(local_radius)):
                                geojson = ee.Geometry(geojson).buffer(
                                    int(local_radius)).getInfo()
                            new_df.loc[i, "geojson"] = json.dumps(geojson)
                            break
                except Exception as e:
                    print(e)
                    raise ValueError("Failed to extract geometry from '" 
                        + new_df.loc[i, "kml_path"] + "'.")
            
            # Create geometry from station coordinates.
            elif local_aoi_mode == 0 and geojson is None:
                try:
                    if local_radius == 0:
                        geojson = ee.Geometry.Point(
                            [float(long), float(lat)]).getInfo()
                    else:
                        geojson = ee.Geometry.Point(
                            [float(long), float(lat)]).buffer(
                            int(local_radius)).getInfo()
                except Exception as e:
                    print(e)
                    raise ValueError("Failed to create geometry for station '" 
                        + station_code + "'.")
                new_df.loc[i, "geojson"] = json.dumps(geojson)
            
            # If a GeoJSON was obtained, update this temporary dict to avoid 
            # reprocessing the same area of interest.
            if geojson is not None:
                station_geoms[station_code] = i
                # Check coordinates.
                if (len(new_df.loc[new_df["station_code"] 
                        == station_code, "lat"].dropna().unique()) > 1 or 
                        len(new_df.loc[new_df["station_code"] 
                        == station_code, "long"].dropna().unique()) > 1):
                    print("(!) Not all coordinates are equal for the station "
                        + station_code + ". Only the first will be "
                        + "considered.")
                if (len(new_df.loc[new_df["station_code"] 
                        == station_code, "aoi_mode"].dropna().unique()) > 1):
                    print("(!) Not all 'aoi_mode' values are equal for the "
                        + "station " + station_code + ". Only the first will "
                        + "be considered.")
                if (len(new_df.loc[new_df["station_code"] 
                        == station_code, "aoi_radius"].dropna().unique()) > 1):
                    print("(!) Not all radius values are equal for the "
                        + "station " + station_code + ". Only the first will "
                        + "be considered.")
                if (len(new_df.loc[new_df["station_code"] 
                        == station_code, "kml_path"].dropna().unique()) > 1):
                    print("(!) Not all path values are equal for the "
                        + "station " + station_code + ". Only the first will "
                        + "be considered.")

        # Enforce dtpyes and store the validated dataframe.
        new_df = new_df.astype(new_df_dtypes)               
        self._validated_user_df = new_df

    # Takes the validated user input and build the demand dataframe.
    def _build_demand_df(self):
        product_catalog = self._args["product_catalog"]
        op_mode = self._op_mode
        demand_cols_dict = self._demand_cols_dict
        valid_user_df = self._validated_user_df.copy()
        if valid_user_df is None:
            valid_user_df = pandas.DataFrame()
        if len(valid_user_df) == 0:
            self._demand_df = None
            return
        user_df_cols = [*valid_user_df.columns]
        demand_df = pandas.DataFrame(columns = [*demand_cols_dict])
        
        # User df is already in the form of demand.
        if op_mode > 1:
            # drop_cols = [c for c in user_df_cols 
            #     if c not in [*demand_cols_dict] + ["demand_code"]]
            # valid_user_df.drop(columns=drop_cols, inplace=True)
            for col in [c for c in [*demand_cols_dict] + ["demand_code"] 
                    if c in user_df_cols]:
                demand_df[col] = valid_user_df[col]
            st_list = list(demand_df["station_code"].unique())
            
            # Replace empty dates and fill ids.            
            for row in demand_df.index:
                if pandas.isna(demand_df.loc[row, "demand_id"]):
                    demand_df.loc[row, "demand_id"] = row + 1
                if pandas.isna(demand_df.loc[row, "status"]):
                    demand_df.loc[row, "status"] = 1
                if pandas.isna(demand_df.loc[row, "station_id"]):
                    demand_df.loc[row, "station_id"] = st_list.index(
                        demand_df.loc[row, "station_code"]) + 1

                # Start date.
                start_date = demand_df.loc[row, "start_date"]
                product_code = demand_df.loc[row, "product_code"]
                if (pandas.isna(start_date) or start_date.lower() in ["none", 
                        "nonetype", "", "nan", "na", "nat", "<na>", "auto"]):
                    start_date = str(pandas.to_datetime(
                        product_catalog[product_code].start_date).date())
                    demand_df.loc[row, "start_date"] = start_date
            
                # End date
                end_date = demand_df.loc[row, "end_date"]
                if (pandas.isna(end_date) or end_date.lower() in ["none", 
                        "nonetype", "", "nan", "na", "nat", "<na>", "auto"]):
                    end_date = str(pandas.to_datetime("today").date())
                    demand_df.loc[row, "end_date"] = end_date
            
                # With start and end dates, generate date list.
                date_series = pandas.date_range(start_date, end_date, freq="D")
                demand_df.at[row, "date_list"] = list(
                    date_series.strftime('%Y-%m-%d'))
                    
        # If user df is in "matchup format", build the demand dataframe.
        else:
            st_cols = ["station_code", "station_name", "lat", "long", 
                "geojson"]
            dm_cols = ["product_code", "cloud_algo_code", "local_algo_code", 
                "reducer_code", "aoi_mode", "aoi_radius", "kml_path", 
                "demand_code"]
            st_series = valid_user_df["station_code"]
            st_list = list(st_series.unique())
            demand_series = valid_user_df["demand_code"]
            demand_code_strs = list(demand_series.unique())
            row = 0
            for st_ind in range(len(st_list)):
                station = st_list[st_ind]
                st_rows = valid_user_df.loc[st_series == station].index
                st_row = st_rows[0]
                for demand_code_str in demand_code_strs:
                    dm_rows = valid_user_df.loc[(st_series == station) 
                        & (demand_series == demand_code_str)].index
                    if len(dm_rows) > 0:
                        dm_row = dm_rows[0]
                        date_list = list(set(list(
                            valid_user_df.loc[dm_rows, "img_date"])))
                        date_list.sort()
                        start_date = date_list[0]
                        end_date = date_list[-1]
                        demand_df.loc[row, "demand_id"] = row + 1
                        demand_df.loc[row, "status"] = 1
                        demand_df.loc[row, "station_id"] = st_ind + 1
                        demand_df.loc[row, "start_date"] = start_date
                        demand_df.loc[row, "end_date"] = end_date
                        demand_df.at[row, "date_list"] = date_list
                        demand_df.loc[row, st_cols] = valid_user_df.loc[
                            st_row, st_cols]
                        demand_df.loc[row, dm_cols] = valid_user_df.loc[
                            dm_row, dm_cols]
                        row += 1
        
        self._demand_df = demand_df

    # Build the "primer" dataframe, which will be used to compose the result
    # dataframe.
    def _build_primer_df(self):
        op_mode = self._op_mode
        orig_user_df = self._user_df
        valid_user_df = self._validated_user_df
        demand_df = self._demand_df
        if demand_df is None:
            demand_df = pandas.DataFrame()
        if len(demand_df) == 0:
            self._primer_df = None
            return
        matchup_cols_dict = self._matchup_cols_dict
        primer_cols = self._result_min_cols
        
        # For mode 1, primer_df is almost ready.
        if op_mode == 1:
            primer_df = valid_user_df.copy()
            validated_cols = [*valid_user_df.columns]
            orig_cols = [str(c) for c in orig_user_df.columns]
            drop_cols = []
            for col in validated_cols:
                if col in matchup_cols_dict and col not in primer_cols:
                    if not any(c.lower() in matchup_cols_dict[col] 
                            for c in orig_cols):
                        drop_cols.append(col)
            primer_df.drop(columns=drop_cols, inplace=True)
        
        # For mode 2 or 3, prime_df must be built.
        else:
            concat_list = []
            for row in demand_df.index:
                start_date = demand_df.loc[row, "start_date"]
                end_date = demand_df.loc[row, "end_date"]
                dates = [*pandas.Series(pandas.date_range(
                    start_date, end_date)).astype("string")]            
                n_dates = len(dates)
                if not n_dates > 0:
                    print("(!) Failed to interpret the date range defined by "
                        + "'start_date' and 'end_date' in the row of index "
                        + str(row) + " of '_demand_df'. Row ignored.")
                    continue
                
                tmp_df = pandas.DataFrame(columns=primer_cols)
                tmp_df["date"] = dates
                tmp_df["station_code"] = demand_df.loc[row,"station_code"]
                tmp_df["station_name"] = demand_df.loc[row,"station_name"]
                tmp_df["lat"] = demand_df.loc[row,"lat"]
                tmp_df["long"] = demand_df.loc[row,"long"]
                tmp_df["geojson"] = demand_df.loc[row,"geojson"]
                if len(tmp_df) > 1:
                    tmp_df.loc[1:,"geojson"] = "idem"
                tmp_df["demand_code"] = demand_df.loc[row,"demand_code"]
                tmp_df["img_date"] = dates
                tmp_df["img_time"] = pandas.NA                
                concat_list.append(tmp_df)
            
            primer_df = pandas.concat(concat_list)
            primer_df.reset_index(drop=True, inplace=True)
            primer_df["img_time"] = primer_df["img_time"].astype("string")   
        
        self._primer_df = primer_df        
        
    # If in mode 3, connects to the database, update basic records (products,
    # algorithms etc.).
    def _update_db(self):
        args = self._args                
        geedar_db = self._geedar_db
        db_names = geedar_db._db_names
        any_change = False
        
        # Product and instrument.
        
        product_catalog = args["product_catalog"]
        db_instruments = geedar_db.get_table("instrument")
        db_products = geedar_db.get_table("product")
        for product_code in [*product_catalog]:
            product = product_catalog[product_code]
            product_name = product.product_name
            product_description = product.description
            instrument = product.instrument
            instrument_name = instrument.name
            instrument_description = instrument.description
            instrument_label = instrument.label
            instrument_mission = instrument.mission
            instrument_revisit = instrument.revisit
            # If it is a new instrument, save it to the database.
            # And get the instrument record id.
            ind = [i for i in db_instruments.index 
                if db_instruments.loc[i, "instrument.name"].lower() == 
                instrument_name.lower()]
            if len(ind) == 0:
                df = pandas.DataFrame({"name": [instrument_name], 
                    "description": [instrument_description], 
                    "mission": [instrument_mission],
                    "label": [instrument_label], 
                    "revisit": [instrument_revisit]})
                geedar_db.save_to_table("instrument", df)
                any_change = True
                instrument_id = geedar_db.get_last_id("instrument")
            else:
                instrument_id = db_instruments.loc[ind[0], 
                    "instrument.primary_key"]
            # Now save the product, if necessary.
            ind = [i for i in db_products.index 
                if db_products.loc[i, "product.primary_key"] == product_code]
            if len(ind) == 0:
                df = pandas.DataFrame({"primary_key": [product_code], 
                    "fkey_instrument": [instrument_id], 
                    "name": [product_name],
                    "description": [product_description]})
                geedar_db.save_to_table("product", df)
                any_change = True
        
        # Variables.
        var_catalog = args["variable_catalog"]
        db_vars = geedar_db.get_table("variable")
        for var_code in [*var_catalog]:
            variable = var_catalog[var_code]
            var_name = variable.name
            var_unit = variable.unit
            var_description = variable.description
            var_label = variable.label
            # Save the variable if it is new.
            ind = [i for i in db_vars.index 
                if db_vars.loc[i, "variable.name"] == var_name]
            if len(ind) == 0:
                df = pandas.DataFrame({"primary_key": [var_code], 
                    "name": [var_name],
                    "unit": [var_unit],
                    "description": [var_description],
                    "label": [var_label]})
                geedar_db.save_to_table("variable", df)
                any_change = True
        
        # Algorithms.
        db_attr_map = {
            "cloud_algo": {
                "_catalog": "cloud_algo_catalog",
                "primary_key": "algo_code",
                "name": "name",
                "description": "description",
                "ref": "ref"
            },
            "local_algo": {
                "_catalog": "local_algo_catalog",
                "primary_key": "algo_code",
                "name": "name",
                "description": "description",
                "ref": "ref"
            }
        }
        for tab_key in [*db_attr_map]:
            db_df = geedar_db.get_table(tab_key)
            attr_primary_key = db_attr_map[tab_key]["primary_key"]
            catalog = args[db_attr_map[tab_key]["_catalog"]]
            for cat_key in [*catalog]:
                obj = catalog[cat_key]
                primary_key = getattr(obj, attr_primary_key)
                ind = [i for i in db_df.index 
                    if db_df.loc[i, tab_key + ".primary_key"] == primary_key]
                if len(ind) == 0:
                    cols = [c for c in [*db_names[tab_key]] if c[0] != "_"]
                    df = pandas.DataFrame(data=None, columns=cols)
                    for col in cols:
                        df.loc[0, col] = getattr(obj, 
                            db_attr_map[tab_key][col])
                    geedar_db.save_to_table(tab_key, df)       
                    any_change = True
        
        # Reducers and stats.
        reducer_catalog = args["reducer_catalog"]
        db_reducers = geedar_db.get_table("reducer")
        db_stats = geedar_db.get_table("stats")
        for reducer_code in [*reducer_catalog]:
            reducer = reducer_catalog[reducer_code]
            reducer_description = reducer.description
            stat_suffixes = reducer.stat_suffix.copy() # list
            if "none" not in stat_suffixes:
                stat_suffixes.append("none")
            # Check for the statistical parameter.
            for stat_suffix in stat_suffixes:
                ind = [i for i in db_stats.index 
                    if db_stats.loc[i, "stats.suffix"] == stat_suffix]
                if len(ind) == 0:
                    if len(db_stats) == 0:
                        stat_code = 0
                    else:
                        stat_code = (int(db_stats["stats.primary_key"].max()) 
                            + 1)
                    df = pandas.DataFrame({"primary_key": [stat_code], 
                        "name": [stat_suffix], "suffix": [stat_suffix],
                        "label": [stat_suffix]})
                    geedar_db.save_to_table("stats", df)
                    any_change = True
                    db_stats = geedar_db.get_table("stats")
            # Now save reducer if necessary.
            ind = [i for i in db_reducers.index 
                if db_reducers.loc[i, "reducer.primary_key"] == reducer_code]
            if len(ind) == 0:
                df = pandas.DataFrame({"primary_key": [reducer_code], 
                    "description": [reducer_description]})
                geedar_db.save_to_table("reducer", df)
                any_change = True
            
        if any_change:
            print("The target database was updated for basic records "
                + "(products, algorithms etc.).")
                
    # Sets, as an attribute, the dict which will store processing parameters
    # and auxilliary data.  
    def _set_proc_dict(self):
        # Try to load cached _proc_dict (if any).
        self._load_cache()
        if hasattr(self, "_proc_dict"):
            return
        demand_df = self._demand_df
        primer_df = self._primer_df.copy()
        product_catalog = self._args["product_catalog"]
        cloud_algo_catalog = self._args["cloud_algo_catalog"]
        local_algo_catalog = self._args["local_algo_catalog"]
        reducer_catalog = self._args["reducer_catalog"]
        op_mode = self._op_mode
        geedar_db = self._geedar_db
        if op_mode == 3:
            save_to = geedar_db
        else:
            save_to = None
        proc_dict = None

        # Any data to process?
        if demand_df is None:
            demand_df = pandas.DataFrame()
        if len(demand_df) == 0:
            raise ValueError("No valid data demand to be processed.")

        # Build the demand dictionary.
        
        geom_dict = dict()
        demand_dict = dict()
        demand_count = 1
        for row in demand_df.index:
            demand_id = int(demand_df.loc[row, "demand_id"])
            station_code = demand_df.loc[row, "station_code"]            
            station_name = demand_df.loc[row, "station_name"]
            start_date = demand_df.loc[row, "start_date"]
            end_date = demand_df.loc[row, "end_date"]
            date_list = demand_df.loc[row, "date_list"]
            product_code = int(demand_df.loc[row, "product_code"])
            cloud_algo_code = int(demand_df.loc[row, "cloud_algo_code"])
            local_algo_code = int(demand_df.loc[row, "local_algo_code"])
            reducer_code = int(demand_df.loc[row, "reducer_code"])
            geojson_str = demand_df.loc[row, "geojson"]

            if station_code not in geom_dict:
                aoi = ee.Geometry(json.loads(geojson_str))
                geom_dict[station_code] = aoi
            else:
                aoi = geom_dict[station_code]
            
            cur_station = VirtualStation(aoi, station_code, station_name)
            cur_product = product_catalog[product_code]
            cloud_algo = cloud_algo_catalog[cloud_algo_code]
            local_algo = local_algo_catalog[local_algo_code]
            reducer = reducer_catalog[reducer_code]
            cur_demand = Demand(cur_station, cur_product, cloud_algo, reducer, 
                local_algo, start_date=start_date, end_date=end_date, 
                save_to=save_to, demand_id=demand_id,
                date_list=date_list)
            
            demand_dict[demand_count] = {
                "demand_id": demand_id,
                "demand_obj": cur_demand,
                "result_obj": None
            }
            demand_count += 1
        
        # Set the _proc_dict attribute.
        df_cols = [*primer_df.columns]
        proc_dict = {
            "demand": { 
                "df": demand_df,
                "dict": demand_dict,
                "cur_index": -1,
            },
            "aux": {
                "primer_df": primer_df, 
                "valid_rows": [*range(len(primer_df))], 
                "date_col": df_cols.index("date"), 
                "id_col": df_cols.index("station_code"), 
                "lat_col": df_cols.index("lat"), 
                "long_col": df_cols.index("long"), 
                "site_series": primer_df["station_code"], 
                "site_list": [*primer_df["station_code"].unique()]
            },
            "result": {
                "finished": False,
                "result_df": primer_df
            }
        }
        self._proc_dict = proc_dict
    
    # Load cached content (if any).
    def _load_cache(self):
        cache_file = self._cache_file
        
        if cache_file is not None:
            if os.path.isfile(cache_file):
                rename_old_file = False
                # Try to load the cache contents.
                try:
                    with open(cache_file, 'rb') as f:
                        cache_dict = pickle.load(f)
                except Exception as e:
                    print(e)
                    print("Failed to load the cache file (" 
                        + cache_file + ").")
                    rename_old_file = True
                else:
                    if not cache_dict["result"]["finished"]:
                        r = input("It seems that the last execution was " 
                            + "interrupted. Try to resume it? y/[n]: ")
                        if r.lower() == "y":
                            self._proc_dict = cache_dict
                        else:
                            rename_old_file = True
                if rename_old_file:
                    try:
                        os.replace(cache_file, cache_file + ".bak")
                        print("The old cache file was renamed to " 
                            + cache_file + ".bak and a new one will be "
                            + "created.")
                    except:
                        self._cache_file = None
                        print("A cache will not be used.")
    
    # Save _proc_dict to cache.
    def _update_cache(self):
        cache_file = self._cache_file
        
        if cache_file is not None:
            proc_dict = self._proc_dict
            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(proc_dict, f)
            except Exception as e:
                print(e)
                print("Cache will not be updated.")
                self._cache_file = None
    
    # Rename the cache file, deleting the previous backup (if any).
    def _delete_cache(self):
        cache_file = self._cache_file
        if not isinstance(cache_file, str):
            return
        
        backup_file = cache_file + ".bak"
        try:
            os.replace(cache_file, backup_file)
        except:
            pass        
    
    # Given all the loaded demands and their current stored results, gets the 
    # list of columns that will be necessary to accommodate the combined 
    # results.
    def _required_result_cols(self):
        proc_dict = self._proc_dict
        demand_dict = proc_dict["demand"]["dict"]
        primer_df = proc_dict["aux"]["primer_df"]
        
        base_cols = list(primer_df.columns)
        local_algo_cols = []
        export_var_cols = []
        export_band_cols = []
        common_band_cols = []
        other_cols = []
        for demand_ind in [*demand_dict]:
            cur_demand = demand_dict[demand_ind]["demand_obj"]
            export_vars = cur_demand.cloud_algo.export_vars
            export_bands = cur_demand.cloud_algo.export_bands                        
            data_bands = list(cur_demand.product.get_data_bands())
            common_bands = [c for c in list(cur_demand.product.common_bands) 
                if c in data_bands]
            ts_df = cur_demand._time_series
            if ts_df is not None:
                ts_cols = list(ts_df.columns)
                reserved_cols = cur_demand._reserved_columns
                non_reserved_cols = [c for c in ts_cols 
                    if c not in reserved_cols]
                refs = (export_vars + export_bands + data_bands)
                for col in non_reserved_cols:
                    col_parts = col.split("_")
                    if len(col_parts) > 1:
                        col_wo_suffix = "_".join(col_parts[:-1])
                    else:
                        col_wo_suffix = col
                        
                    if not any(c in [col, col_wo_suffix] for c in refs):
                        local_algo_cols.append(col)
                    elif col in export_vars:
                        export_var_cols.append(col)
                    elif any(c == col_wo_suffix for c in export_bands):
                        export_band_cols.append(col)
                    elif any(c == col_wo_suffix for c in common_bands):
                        common_band_cols.append(col)
                    else:
                        other_cols.append(col)
            
        col_list = list(dict.fromkeys(
            base_cols + local_algo_cols + export_var_cols + export_band_cols 
            + common_band_cols + other_cols))
        
        return col_list 
    
    # Returns the columns of the result dataframe in the best order, starting 
    # with the exported variables and bands, followed by the "common" bands 
    # and finishing with real band names. 
    def _sort_result_cols(self, result_df):
        required_list = self._required_result_cols()
        result_cols = list(result_df.columns)        
        sorted_cols = [c for c in required_list if c in result_cols]
        return result_df[sorted_cols]
    
    # Returns a dataframe to receive the result data from all demands.
    def _build_result_df(self):
        proc_dict = self._proc_dict
        id_col = proc_dict["aux"]["id_col"]
        demand_dict = proc_dict["demand"]["dict"]
        primer_df = proc_dict["aux"]["primer_df"]
        if primer_df is None:
            return
        if len(primer_df) == 0:
            return
        
        result_df = primer_df.copy()
        stcode_series = result_df.iloc[:,id_col]
        date_series = result_df["img_date"]
        demand_series = result_df["demand_code"]        
        
        for demand_ind in [*demand_dict]:
            cur_demand = demand_dict[demand_ind]["demand_obj"]
            ts_df = cur_demand._time_series
            if ts_df is None:
                continue
            if len(ts_df) == 0:
                continue
            stcode = cur_demand.virtual_station.station_code
            demand_code_str = cur_demand.get_demand_code(format_as="str")
            data_cols = [c for c in list(ts_df.columns) 
                if c not in cur_demand._reserved_columns]
            ts_copy = ts_df.copy()
            ts_copy.dropna(subset = data_cols, how = 'all', inplace = True)
            dt_series = ts_copy.index.to_series()
            for source_row in ts_copy.index:
                cur_date = dt_series[source_row].strftime('%Y-%m-%d')
                cur_time = dt_series[source_row].strftime('%H:%M')
                target_row_inds = which((date_series == cur_date) 
                    & (stcode_series == stcode) 
                    & (demand_series == demand_code_str))
                target_rows = result_df.index[target_row_inds]
                result_df.loc[target_rows, "img_time"] = cur_time
                for target_row in target_rows:
                    for col in data_cols:
                        if ts_copy[col].dtype == "object":
                            source_val = copy.deepcopy(
                                ts_copy.at[source_row, col])
                            if col not in list(result_df.columns):
                                result_df[col] = None
                        else:
                            source_val = ts_copy.at[source_row, col]
                        result_df.at[
                            target_row, col] = source_val
        
        # Rplace the word "idem" for na's in the GeoJSON column.
        result_df.loc[result_df["geojson"] == "idem", "geojson"] = pandas.NA
        
        # Remove empty rows (in modes 2 and 3).
        if self._op_mode >= 2:
            time_col = result_df.columns.get_loc("img_time")
            result_df.dropna(subset = [*result_df.columns[time_col:]] 
                + ["geojson"], how = "all", inplace = True)
        # Neaten up columns and return the result dataframe.
        return self._sort_result_cols(result_df)
        
    # Execute the data demands one by one.
    def execute_demands(self):
        proc_dict = self._proc_dict
        demand_dict = proc_dict["demand"]["dict"]
        prev_ind = proc_dict["demand"]["cur_index"]
        
        print("Executing demands...")
        
        exec_counter = 0
        for demand_ind in [i for i in [*demand_dict] if i > prev_ind]:
            proc_dict["demand"]["cur_index"] = demand_ind
            demand_id = demand_dict[demand_ind]["demand_id"]
            cur_demand = demand_dict[demand_ind]["demand_obj"]
            site_code = cur_demand._virtual_station.station_code
            site_name = cur_demand._virtual_station.station_name
            if site_name != "" and site_name != site_code:
                site_name_str = " (" + site_name + ")"
            else:
                site_name_str = ""
            demand_code_str = cur_demand.get_demand_code(format_as="str")
            print("\n->> Demand id #" + str(demand_id) + ": " + site_code 
                + site_name_str + ", " + demand_code_str)
            cur_result = cur_demand.execute()
            proc_dict["demand"]["dict"][demand_ind]["result_obj"] = cur_result
            # Update cache.
            self._update_cache()
            exec_counter += 1
        
        if exec_counter == 0:
            print("Nothing to process.")
        
        proc_dict["result"]["result_df"] = self._build_result_df()
        proc_dict["result"]["finished"] = True
        self._update_cache()
        
    # Rearrange the results, separating the ones from different processing 
    # chains (different demand codes) into separate groups of columns.
    def _to_separate_cols(self):
        source_df = self._proc_dict["result"]["result_df"]
        source_cols = [*source_df.columns]
        # No data:
        if source_cols[-1] == "img_time":
            return
        time_col = source_df.columns.get_loc("img_time")
        base_cols = source_cols[:time_col]
        base_cols.remove("demand_code")
        data_cols = source_cols[time_col:]
        demand_codes = list(source_df["demand_code"].unique())
        new_data_cols = [];
        for demand_code in demand_codes:
            for col in data_cols:
                target_col = str(demand_code) + "_" + col
                new_data_cols.append(target_col)
        
        target_df = source_df.loc[:, base_cols].drop_duplicates(
            subset = ["station_code", "img_date"], ignore_index = True)
        tmp_df = pandas.DataFrame(columns=new_data_cols)
        target_df = pandas.concat([target_df, tmp_df])
        
        for target_row in target_df.index:
            station = target_df.at[target_row, "station_code"]
            img_date = target_df.at[target_row, "img_date"]
            source_rows = source_df.loc[(source_df["station_code"] == station) 
                & (source_df["img_date"] == img_date)].index
            for source_row in source_rows:
                demand_code = source_df.at[source_row, "demand_code"]
                for col in data_cols:
                    target_col = str(demand_code) + "_" + col
                    target_df.at[target_row, target_col] = source_df.at[
                        source_row, col]
        
        # Drop empty columns.
        return target_df.dropna(axis=1, how='all')
    
    # Saves data into the target database.
    def _save_results_to_db(self):
        proc_dict = self._proc_dict
        demand_dict = proc_dict["demand"]["dict"]
        geedar_db = self._geedar_db
        db_values = geedar_db._db_values
        source_id = db_values["acquisition.source_id"]
        data_status = db_values["data.status"]
        
        # Save demand by demand.
        all_saved_data = dict()
        for demand_i in [*demand_dict]:
            demand_id = demand_dict[demand_i]["demand_id"]
            cur_demand = demand_dict[demand_i]["demand_obj"]
            site_code = cur_demand._virtual_station.station_code
            site_name = cur_demand._virtual_station.station_name
            if site_name != "" and site_name != site_code:
                site_name_str = " (" + site_name + ")"
            else:
                site_name_str = ""
            demand_code_str = cur_demand.get_demand_code(format_as="str")
            print("\nDemand id #" + str(demand_id) + ": " + site_code 
                + site_name_str + ", " + demand_code_str)
            all_saved_data[demand_id] = cur_demand.save_to_db(
                source_id=source_id, data_status=data_status, check_db=False)
        return(all_saved_data)
    
    # Saves the results.
    def save_results(self, overwrite=None):
        if overwrite is not None:
            if type(overwrite) is not bool:
                raise TypeError("'overwrite' must be a bool.")

        save_report = {
            "options": {
                "input_path": self._input_path,
                "output_path": self._output_path,
                "op_mode": self._op_mode,
                "demand_codes": self._demand_codes,
                "aoi_mode": self._aoi_mode,
                "aoi_radius": self._aoi_radius
            },
            "demand_df": self._proc_dict["demand"]["df"],
            "csv": {
                "saved": False,
                "output_path": "",
                "df": None
            },
            "db": {
                "saved": False,
                "data_dict": {},
                "db_config": self._db_config
            }
        }

        proc_dict = self._proc_dict
        result_df = proc_dict["result"]["result_df"]
        output_path = self._output_path
        op_mode = self._op_mode
        
        if len(result_df) == 0:
            print("No data yet to be saved.")
            return save_report
        
        # Warn if not finished:
        if not proc_dict["result"]["finished"]:
            print("Not all demands have been executed yet.")
            return save_report
        
        # Save a CSV (if not directed only to the database).
        if output_path != "geedar_db":            
            if os.path.exists(output_path):
                print("\nThe output file already exists: '" 
                    + output_path + "'.")
                if overwrite is None:
                    r = input("Do you want to overwrite it? y/[n]: ")
                    if r.lower().replace(" ", "") == "y":
                        overwrite = True
                    else:
                        overwrite = False
                if not overwrite:
                    print("Ok, saving aborted.")
                    return
                else:
                    print("It will be overwritten...")
            else:
                print("")
            # Save:
            result_df.to_csv(output_path, index = False, encoding="utf-8-sig")
            print("Results saved as a CSV file: '" + output_path + "'.")
            save_report["csv"]["saved"] = True
            save_report["csv"]["output_path"] = output_path
            save_report["csv"]["df"] = result_df
            
            # Extra file with results rearranged?
            if self._separate_cols:
                if "." not in output_path:
                    insert_pos = -1
                else:
                    point_pos = output_path[::-1].index(".")
                    insert_pos = -point_pos - 1
                extra_output_path = (output_path[:insert_pos] + "_sepcols"
                    + output_path[insert_pos:])
                tmp_df = self._to_separate_cols()
                if len(tmp_df) > 0:
                    tmp_df.to_csv(extra_output_path, index = False, 
                        encoding="utf-8-sig")
                    print("\nExtra file saved: '" + extra_output_path + "'.")
        
        # Save to database?
        if op_mode >= 3:
            print("\nSaving results to the database...")
            save_report["db"]["data_dict"] = self._save_results_to_db()
            save_report["db"]["saved"] = True

        self._delete_cache()        
        return save_report

