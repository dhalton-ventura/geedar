#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration of the database to be used with GEEDaR.

This script defines the configuration of the target database: credentials, 
connection parameters, column names and default values. It will try to load
a json file with custom settings. If not possible, default ones are applied.

Note: database connection string and parameters must be compatible
with the SQLAlchemy package. 

"""

__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.0.2"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"


#%% Import

import os
import json
from geedar_classes import GeedarDB


#%% Export

# The dictionary 'db_config' will be exported containing the database config.
# to be used by GeedarApp.
__all__ = ["db_config"]


#%% Load custom or default settings

# The following JSON template contains default values (the "keys" are fixed 
# and cannot be changed) for database configuration. The template will be 
# saved as a file (if it does not already exist). If you want to use the 
# default values, just keep it as it is. Otherwise, you need to edit the file, 
# inserting data for credentials, connection type and names of tables and 
# columns in your database.

# 'conn_type' currently may be "odbc" or "sqlite". Using "none" will lead to
# default configuration, which is the use of an SQLite3 database.
# In 'credentials', 'data_source_name' is required when using ODBC access and
# 'file_name' is required when using SQLite. 'user_id' and 'password' may be
# empty strings if credentials are not required by the target dabatase.

_json_template = {
    "conn_type": GeedarDB._default_conn_type,
    "credentials": GeedarDB._default_credentials,
    "db_names": GeedarDB._default_db_names,
    "db_values": GeedarDB._default_db_values
}

# Default file:
_json_file = "db_config.json"

# If the json file does not exist, create it.
if not os.path.isfile(_json_file):
    with open(_json_file, "w") as file:
        json.dump(_json_template, file, indent=4)

# Read the json file with the variables used in the connection string (ex: 
# user id, password, filename etc.):
# If not existent, the template above is used (default values).
if os.path.isfile(_json_file):
    with open(_json_file, "r") as file:
        ext_conn_info = json.load(file)
else:
    ext_conn_info = _json_template


#%% Wrap the settings in a template dict.

# The previously loaded settings will be combined with the templates below.

_conn_dict_templates = {
    "none": {
        "connect_string": "",
        "connect_args": {}
    },
    "odbc": {
        "connect_string": ("mssql+pyodbc:///?odbc_connect"
            + "=DSN={};UID={};PWD={}".format(
            ext_conn_info["credentials"]["data_source_name"], 
            ext_conn_info["credentials"]["user_id"], 
            ext_conn_info["credentials"]["password"])),
        "connect_args": {}
    },
    "sqlite": {
        "connect_string": "sqlite:///{}".format(
            ext_conn_info["credentials"]["file_name"]),
        "connect_args": {}
    }
}

# Default connection will be used if the credentials are totally empty (that
# is, neither data for ODBC nor for SQLite connection). So, even if you edited
# 'db_names', your edition will be ignored if you did not provide minimum 
# credential data.
if all(s == "" for s in ext_conn_info["credentials"].values()):
    _conn_dict = _conn_dict_templates["none"]
else:
    _conn_dict = _conn_dict_templates[ext_conn_info["conn_type"]]

#%% Build the db_config dict

# This dictionary will be exported from this module and passed to the 
# GeedarApp constructor for internal instantiation of a GeedarDB oject.
db_config = {
    "conn_dict": _conn_dict,
    "db_names": ext_conn_info["db_names"],
    "db_values": ext_conn_info["db_values"]
}


#%% Testing

# These GeedarDB ojects are created for testing.
# If you want to make tests, run this module and try out commands with
# 'db_handler' (points to your custom database) or with 'default_db' (points
# to an SQLite database named "geedar.db", which may be your operational
# database if you had chosen default setup, so be careful!).

# GeedarDB objects for testing:
default_db = GeedarDB()
try:
    db_handler = GeedarDB(**db_config)
except:
    pass
