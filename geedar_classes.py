#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility facade for the GEEDaR core classes.

The implementations were moved to the ``geedar_core`` package. Existing
imports from ``geedar_classes`` remain supported, including old pickle files
that refer to classes through this module.
"""

__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.1"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"

# Keep the original module-level imports available for compatibility with
# callers that may access these names directly.
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

from geedar_core.algorithms import CloudAlgorithm, LocalAlgorithm
from geedar_core.app import GeedarApp
from geedar_core.catalog_types import Instrument, Reducer, Variable
from geedar_core.database import GeedarDB
from geedar_core.demand import Demand
from geedar_core.options import UserOptions
from geedar_core.product import Product
from geedar_core.station import VirtualStation
from geedar_core.utils import (
    _MAX_PROC_PIXELS,
    _MAX_SIM_IMAGES,
    _MAX_ATTEMPTS,
    _RETRY_WAIT_SECONDS,
    _NoGroupRetryError,
    _AOI_DEFAULT_RADIUS,
    is_path_valid,
    which,
    text_box,
    _valid_argument_list,
    _invalid_argument_types,
    _invalid_argument_values,
    _validate_args_dict,
    autocast_str,
    str_to_list,
    val_to_sql,
    list_to_sql,
    cast_numeric_list,
    unfold_df_lists,
    restore_df_lists,
    reduce_list,
    extract_from_kml,
)

__all__ = [
    "Product",
    "VirtualStation",
    "CloudAlgorithm",
    "LocalAlgorithm",
    "Demand",
    "Variable",
    "Instrument",
    "GeedarDB",
    "UserOptions",
    "GeedarApp",
]
