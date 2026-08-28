#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database access and schema mapping used by GEEDaR."""

import sys
import pandas
from datetime import timedelta
from sqlalchemy import create_engine, text, inspect

from .utils import is_path_valid, list_to_sql, val_to_sql

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
        return self._use_real_col_names
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
                    %variable.unit%        VARCHAR(25),
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

    # Checks if a table is present in the target database.
    def _has_table(self, table, schema=None):
        conn = self._conn
        if conn.dialect.name != "mssql":
            return inspect(conn).has_table(table, schema=schema)

        table = str(table).replace("'", "''")
        sqlstr = ("SELECT TOP 1 1 FROM INFORMATION_SCHEMA.TABLES WHERE "
            + "TABLE_NAME = N'" + table + "'")
        if schema is not None:
            schema = str(schema).replace("'", "''")
            sqlstr = sqlstr + " AND TABLE_SCHEMA = N'" + schema + "'"
        return conn.exec_driver_sql(sqlstr).first() is not None

    # Gets table columns from the target database.
    def _get_table_columns(self, table, schema=None):
        conn = self._conn
        if conn.dialect.name != "mssql":
            return inspect(conn).get_columns(table, schema=schema)

        schema = str(schema or "dbo").replace("'", "''")
        table = str(table).replace("'", "''")
        sqlstr = """
            SELECT c.name, t.name, c.is_identity
            FROM sys.columns c
            JOIN sys.objects o ON o.object_id = c.object_id
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            JOIN sys.types t ON t.user_type_id = c.user_type_id
            WHERE s.name = N'%schema%' AND o.name = N'%table%'
            ORDER BY c.column_id
        """.replace("%schema%", schema).replace("%table%", table)
        return [{"name": row[0], "type": row[1],
            "autoincrement": bool(row[2])}
            for row in conn.exec_driver_sql(sqlstr)]

    # Returns a dictionary with two lists: the db_names' keys of the GEEDaR
    # tables that are present and the ones that are missing in the target
    # database.
    def _check_geedar_tables(self):
        db_names = self._db_names
        conn = self._conn
        present_list = []
        missing_list = []
        for k in [*db_names]:
            schema = db_names[k]["_schema"] or None
            table = db_names[k]["_table_name"]
            if self._has_table(table, schema=schema):
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
                end_date_col = db_names["demand"]["end_date"]
            else:
                demand_id_col = "demand.primary_key"
                start_date_col = "demand.start_date"
                end_date_col = "demand.end_date"
            rows_to_remove = []
            for i in df.index:
                demand_id = df.loc[i, demand_id_col]
                last_date = self.get_last_date(demand_id)
                if last_date is not None:
                    start_date = pandas.to_datetime(last_date) + timedelta(
                        days=1)
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

        schema_str = db_names[table_key]["_schema"]
        if schema_str:
            schema_str = schema_str + "."

        querystr = ("Select MAX(" + db_names[table_key]["primary_key"] + ") "
            + "from " + schema_str+ db_names[table_key]["_table_name"])
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
            only_db_names=True, avoid_duplication=True, commit=True):
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
            commit: if True, commits the insertion immediately (bool, optional).

        Returns
        -------

            The number of rows inserted in the target table (int).

        """
        if not isinstance(df, pandas.DataFrame):
            raise TypeError("'df' must be a pandas data frame.")
        table_key = self._check_table_key(table_key)

        db_names = self._db_names
        schema = db_names[table_key]["_schema"] or None
        table_name = db_names[table_key]["_table_name"]
        if schema:
            table_name = schema + "." + table_name
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

        schema = subdict["_schema"] or None
        table = subdict["_table_name"]
        if not self._has_table(table, schema=schema):
             raise ValueError("The table " + table + " was not found in "
                  + "the target database.")
        cols = self._get_table_columns(table, schema=schema)
        table_cols = [col["name"] for col in cols
            if str(col["type"]).lower() != "geometry"]
        unmatched_cols = [c for c in df_cols
            if c.lower() not in [col.lower() for col in table_cols]]
        if len(unmatched_cols) > 0:
            raise ValueError("One or more columns in the input data frame "
                + "were not found in the table '" + table_name + "': "
                + str(unmatched_cols) + ".")

        # Remove columns with identity restriction (autoincrement).
        valid_cols = df_cols
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
            if commit:
                conn.commit()
        except Exception as e:
            conn.rollback()
            if not commit:
                raise
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
