#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Earth Engine Data Retriever - GEEDaR

This application makes it easier to retrieve data from Google Earth 
Engine, especially time series or date-matched data for the specified 
'virtual stations', which are spatially delimited areas of interest.

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

import sys
import os

# Create a message logger to copy all text output to a file.
if hasattr(sys.stdout, "isatty"):
    if sys.stdout.isatty() and "SPYDER_ARGS" not in os.environ:
        class ConsoleToLogger:
            def __init__(self, filename):
                self.terminal = sys.stdout
                self.log = open(filename, "w", encoding="utf-8")
        
            def write(self, message):
                self.terminal.write(message)  # Print to the console
                self.log.write(message)       # Write to the file
        
            def flush(self):
                # Ensure text is written immediately.
                self.terminal.flush()
                self.log.flush()
        sys.stdout = ConsoleToLogger("msg_log.txt")
        sys.stderr = sys.stdout

print("\nStarting GEEDaR " + __version__ + "...")

# Get the path to the environment's root folder.
conda_env_path = os.path.dirname(sys.executable)
# Define the crucial subfolders where Conda hides DLLs.
required_paths = [
    conda_env_path,
    os.path.join(conda_env_path, 'Library', 'mingw-w64', 'bin'),
    os.path.join(conda_env_path, 'Library', 'usr', 'bin'),
    os.path.join(conda_env_path, 'Library', 'bin'),
    os.path.join(conda_env_path, 'Scripts'),
    os.path.join(conda_env_path, 'bin')
]
# Inject them into the system PATH for this process.
original_path = os.environ.get('PATH', '')
os.environ['PATH'] = ';'.join(required_paths) + ';' + os.environ['PATH']
# Change the working dir to the script's dir.
app_path = None
if getattr(sys, 'frozen', False):
    # If the application is run as a bundle (PyInstaller):
    app_path = os.path.dirname(sys.executable)
else:
    try:
        app_path = os.path.dirname(os.path.abspath(__file__))
    except Exception as e:
        print(e)
if app_path:
    if app_path not in sys.path:
        sys.path.insert(0, app_path)
    os.chdir(app_path)

import json
import ee
# Earth Engine initialization.
# Look for the json config file. If it is not found, try to initialize without
# a project id. It may work if a default project was set for the Earth Engine
# API. If the file is found, use the project id defined there.
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

from products import product_catalog
from cloud_algorithms import cloud_algo_catalog
from reducers import reducer_catalog
from local_algorithms import local_algo_catalog
from variables import variable_catalog
from instruments import instrument_catalog
from db_config import db_config
from geedar_core.app import GeedarApp
from geedar_core.options import UserOptions


#%% Get the user options

# Ignore the first argument, which is the script file's name.
cmd_line = sys.argv[1:]

# Validate the command line arguments, importing them as a dictionary.
user_options = UserOptions(cmd_line=cmd_line)

# If the user needs help, display instructions and quit.
if user_options.options_dict["help"]:
    print("Help was requested on the command line options.")
    user_options.show_help()
    # Examples.
    if os.path.isfile("examples.hlp"):
        with open("examples.hlp", 'r') as file:
            txt = file.read()
        print(txt)
    exit()
    sys.exit(0)
        

#%% Instantiate the app

app = GeedarApp(user_options, 
        product_catalog, cloud_algo_catalog, local_algo_catalog,
        reducer_catalog, instrument_catalog, variable_catalog,
        db_config=db_config)


#%% Process the user demands

app.execute_demands()


#%% Save the results

saving_report = app.save_results()

# Save a json as log.
_log_file = "result_metadata.json"
with open(_log_file, "w") as file:
    json.dump(saving_report, file, indent=4, 
        default=lambda obj: obj.to_dict(orient='records'))

#%% Restore path variable

os.environ['PATH'] = original_path
