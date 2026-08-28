#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Top-level GEEDaR application orchestration."""

import sys
import os
import copy
import json
import pickle
import pandas
import ee
from datetime import datetime

from .database import GeedarDB
from .demand import Demand
from .station import VirtualStation
from .utils import (
    _AOI_DEFAULT_RADIUS,
    extract_from_kml,
    is_path_valid,
    str_to_list,
    which,
)

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
        auto_save: if True, results will be saved stepwisely during demand's
            execution.

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
            default_demand_code=None, db_config=None, cache_file=True,
            auto_save=False):

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

        # Update the database for products, algorithms etc. (if in mode 3).
        if self._op_mode >= 3:
            print("Updating basic tables in the database...")
            self._update_db()

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

        # Autosave.
        auto_save = args["auto_save"]
        if not isinstance(auto_save, bool):
            raise TypeError("'auto_save' must be boolean")

        # Save attributes:
        self._args = args
        self._options_dict = args["user_options"].options_dict
        self._cache_file = cache_file
        self._default_demand_code = default_demand_code
        self._db_config = db_config
        self._auto_save = auto_save

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
                    db_names=db_config["db_names"],
                    db_values=db_config["db_values"])

                # Get demand data.
                demand_table = geedar_db.get_demands(update_start_date=True)
                # Rename columns to the default demand_df names.
                user_df = demand_table.rename(
                    columns={v[0]:k for k,v in demand_cols_dict.items()
                    if len(v) > 0})
                user_df = user_df.loc[user_df["status"] == 1].copy()
                station_codes = options_dict["stations"]
                if station_codes != ["auto"]:
                    station_codes = [str(code) for code in station_codes]
                    user_df = user_df.loc[user_df["station_code"].astype(
                        str).isin(station_codes)].copy()
                demand_ids = options_dict["demand_ids"]
                if demand_ids != ["auto"]:
                    demand_ids = [str(demand_id) for demand_id in demand_ids]
                    user_df = user_df.loc[user_df["demand_id"].astype(
                        str).isin(demand_ids)].copy()

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
                if (self._options_dict["stations"] == ["auto"] and
                        self._options_dict["demand_ids"] == ["auto"]):
                    sys.exit("No demand records in the database yet.")
                sys.exit("No pending demand found for the selected filter(s).")
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
        # Then build paths.
        for i in [ind for ind in new_df.index
                if pandas.notna(new_df.loc[ind, "kml_path"])]:
            if new_df.loc[i, "kml_path"] == "auto":
                exts = ["kml", "kmz"]
                names = [str(new_df.loc[i, "station_code"]),
                    str(new_df.loc[i, "station_name"]),
                    str(new_df.loc[i, "station_code"])
                    + " - " + str(new_df.loc[i, "station_name"])]
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
                        + str(new_df.loc[i, "station_code"]) + " (row #"
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
            default_demand_code = self._default_demand_code
            if default_demand_code is None:
                raise ValueError("You have not provided a demand code and "
                    + "a default one was not defined when "
                    + "instantiating 'GeedarApp'.")
            # Are the demand codes valid? Get a list of the validated codes.
            demand_codes = self._validate_demand_codes(default_demand_code)
            if len(demand_codes) == 0:
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
            unfolded_codes = new_df["demand_code"].apply(
                lambda codestr: list(Demand.unfold_demand_code(
                codestr).values()) if pandas.notna(codestr)
                else [pandas.NA] * len(demand_code_cols))
            new_df[demand_code_cols] = pandas.DataFrame(
                unfolded_codes.tolist(), index=new_df.index,
                columns=demand_code_cols)

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
            new_df.drop(invalid_rows, inplace=True)

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
                new_df.loc[i, "geojson"] = json.dumps(geojson)
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
                df = pandas.DataFrame({"name": [var_name],
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
        primer_df = self._primer_df.copy()

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
                save_to=save_to, demand_id=demand_id, date_list=date_list,
                auto_save=(op_mode == 3 or self._auto_save))

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
                        if self._op_mode == 3:
                            print("(The last database execution was "
                                + "interrupted. It will resume from the "
                                + "latest data saved in the database.)")
                            rename_old_file = True
                        else:
                            r = input("It seems that the last execution was "
                                + "interrupted. Try to resume it? y/[n]: ")
                            if r.lower() == "y":
                                self._proc_dict = cache_dict
                            else:
                                rename_old_file = True
                if rename_old_file:
                    try:
                        os.replace(cache_file, cache_file + ".bak")
                        print("(The old cache file was renamed to "
                            + cache_file + ".bak and a new one will be "
                            + "created.)")
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
        failed_demands = []
        for demand_ind in [i for i in [*demand_dict] if i > prev_ind]:
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
            try:
                cur_result = cur_demand.execute()
            except Exception as e:
                if self._op_mode != 3:
                    raise
                failed_demands.append(demand_id)
                print("Demand id #" + str(demand_id) + " failed: " + str(e)
                    + " Continuing with the next demand.")
                continue
            proc_dict["demand"]["dict"][demand_ind]["result_obj"] = cur_result
            proc_dict["demand"]["cur_index"] = demand_ind
            # Update cache.
            self._update_cache()
            exec_counter += 1

        if exec_counter == 0 and len(failed_demands) == 0:
            print("Nothing to process.")
        if len(failed_demands) > 0:
            raise RuntimeError(str(len(failed_demands)) + " demand(s) failed: "
                + ", ".join(str(i) for i in failed_demands) + ".")

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
        if op_mode >= 3 and not self._auto_save:
            print("\nSaving results to the database...")
            save_report["db"]["data_dict"] = self._save_results_to_db()
            save_report["db"]["saved"] = True

        self._delete_cache()
        return save_report
