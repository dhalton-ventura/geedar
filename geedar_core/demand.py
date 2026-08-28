#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demand preparation, execution, reduction and persistence workflow."""

import os
import math
import time
import pandas
import ee
from datetime import datetime
from func_timeout import func_timeout, FunctionTimedOut

from .catalog_types import Reducer
from .utils import (
    _MAX_PROC_PIXELS,
    _MAX_SIM_IMAGES,
    _MAX_ATTEMPTS,
    _RETRY_WAIT_SECONDS,
    _NoGroupRetryError,
    cast_numeric_list,
    is_path_valid,
    reduce_list,
)

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
            last_error = None
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
                    + str(date_inds[
                        cur_date_index + len(cur_date_list) - 1] + 1)
                    + "/" + str(n_all_dates) + ": "
                    + str(short_date_list) + "...")
                try:
                    relax_demand = False
                    retrieved_dict = func_timeout(360, retrieve,
                        args=(image_collection,))
                except FunctionTimedOut as e:
                    last_error = e
                    print("No response from the server.")
                    n_timeouts += 1
                except ee.ee_exception.EEException as e:
                    last_error = e
                    print(f"EEException caught: {e}")
                    if (str(e)[:40] ==
                            "Output of image computation is too large"):
                        relax_demand = True
                    elif str(e) in ("Computation timed out.",
                            "User memory limit exceeded."):
                        n_timeouts += 1
                        relax_demand = True
                except Exception as e:
                    last_error = e
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
                continue
            elif not isinstance(retrieved_dict, dict):
                raise RuntimeError("Data retrieval failed after all retry "
                    + "attempts for date(s) " + str(short_date_list) + ".") \
                    from last_error
            else:
                cur_date_index += len(cur_date_list)

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
            raise RuntimeError("Failed to retrieve image group "
                + str(cur_group) + "/" + str(n_groups) + ".") from e
        if len(reduction_info["data_dict"].keys()) == 0:
            print("No data returned.")
            self._current_image_group = cur_group + 1
            return {
                cur_group: {
                    "reduction_info": reduction_info,
                    "local_algo_info": None
                }
            }

        # Local algorithm application.
        if (self._local_algo is None
                or len(self._local_algo.required_bands) == 0):
            local_algo_info = None
        else:
            try:
                local_algo_info = self._apply_local_algorithm()
            except Exception as e:
                raise _NoGroupRetryError("Failed to apply the local algorithm to "
                    + "image group " + str(cur_group) + "/" + str(n_groups)
                    + ".") from e

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
                for attempt in range(1, _MAX_ATTEMPTS + 1):
                    try:
                        self.save_to_db(check_db=False)
                    except Exception as e:
                        if attempt == _MAX_ATTEMPTS:
                            raise _NoGroupRetryError(
                                "Database save failed.") from e
                        print(e)
                        print("Database save failed; retrying in "
                            + str(_RETRY_WAIT_SECONDS) + " seconds.")
                        time.sleep(_RETRY_WAIT_SECONDS)
                    else:
                        break

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
            while self._current_image_group <= n_groups:
                cur_group = self._current_image_group
                for attempt in range(1, _MAX_ATTEMPTS + 1):
                    try:
                        cur_dict = self.next_group()
                    except _NoGroupRetryError:
                        raise
                    except Exception as e:
                        if attempt == _MAX_ATTEMPTS:
                            raise
                        print("Image group " + str(cur_group) + "/"
                            + str(n_groups) + " failed; retrying in "
                            + str(_RETRY_WAIT_SECONDS) + " seconds.")
                        time.sleep(_RETRY_WAIT_SECONDS)
                    else:
                        break
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
        """Saves the demand results in a single database transaction."""
        try:
            result = self._save_to_db(source_id, data_status, check_db)
            self._save_to._conn.commit()
            return result
        except Exception:
            self._save_to._conn.rollback()
            raise

    def _save_to_db(self, source_id=None, data_status=None, check_db=True):
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
                last_id = geedar_db.get_last_id("variable") #int(var_table[var_id_col].max())
                var_new_record = pandas.DataFrame(columns=var_table.columns)
                var_new_record.loc[0, var_id_col] = last_id + 1
                var_new_record.loc[0, var_name_col] = col_var_name
                var_new_record.loc[0, var_unit_col] = ""
                var_new_record.loc[0, var_label_col] = col_var_name
                r = geedar_db.save_to_table("variable", var_new_record,
                    commit=False)
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
                    avoid_duplication=False, commit=False)
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
                        avoid_duplication=False, commit=False)
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
                            avoid_duplication=False, commit=False)
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
