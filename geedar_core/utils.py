#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared constants and helper functions used by GEEDaR core classes."""

import sys
import os
import math
import statistics
import copy
import json
import zipfile
import pickle
import time
import pandas
import ee
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, text, inspect
from func_timeout import func_timeout, FunctionTimedOut
from fastkml import KML, Placemark, Folder, Document
from fastkml.utils import find_all

#%% Globals

# Max number of simultaneously processed pixels and images:
_MAX_PROC_PIXELS = 10_000_000
_MAX_SIM_IMAGES = 250
_MAX_ATTEMPTS = 2
_RETRY_WAIT_SECONDS = 300


class _NoGroupRetryError(RuntimeError):
    pass

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
            return strg
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
    if real_list is None:
        return "NULL"
    if not isinstance(real_list, list):
        raise TypeError("'real_list' must be a list.")
    if len(real_list) == 0:
        return "()"

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
    orig_df.attrs = df.attrs
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
