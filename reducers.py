# -*- coding: utf-8 -*-
"""
Provides a catalog of "reducers" to be available for GEEDaR.

A Reducer encapsulates the Earth Engine Reducer, which allows for "reducing" 
data of an area of interest to a representative value, such as a statistical 
parameter (mean, median etc.). Reducers are used in GEEDaR as a parameter of 
Demand objects.*

Each Reducer has an id code that is both an attribute and an identification 
in the catalog below.

* On Demand objects, see the class 'Demand' in the module 'geedar_classes'.

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

import ee
from geedar_classes import Reducer
#from stats import stat_catalog


#%% Export

__all__ = ["reducer_catalog"]


#%% Build a catalog of algorithms

_reducer_list = [
    {
        "reducer_code": 0,
        "ee_reducer": ee.Reducer.toList(),
        "description": "all values",
        "stat_suffix": ["list"]
    },
    {
        "reducer_code": 1,
        "ee_reducer": ee.Reducer.median(),
        "description": "median",
        "stat_suffix": ["median"]
    },
    {
        "reducer_code": 2,
        "ee_reducer": ee.Reducer.mean(),
        "description": "mean",
        "stat_suffix": ["mean"]
    },
    {
        "reducer_code": 3,
        "ee_reducer": ee.Reducer.mean().combine(
            reducer2 = ee.Reducer.stdDev(), sharedInputs = True),
        "description": "mean & stdDev",
        "stat_suffix": ["mean", "stdDev"]
    },
    {
        "reducer_code": 4,
        "ee_reducer": ee.Reducer.minMax(),
        "description": "min & max",
        "stat_suffix": ["min", "max"]
    },
    {
        "reducer_code": 5,
        "ee_reducer": ee.Reducer.count(),
        "description": "count",
        "stat_suffix": ["count"]
    },
    {
        "reducer_code": 6,
        "ee_reducer": ee.Reducer.sum(),
        "description": "sum",
        "stat_suffix": ["sum"]
    },
    {
        "reducer_code": 7,
        "ee_reducer": ee.Reducer.median().combine(
            reducer2 = ee.Reducer.mean(), sharedInputs = True).combine(
            reducer2 = ee.Reducer.stdDev(), sharedInputs = True).combine(
            reducer2 = ee.Reducer.minMax(), sharedInputs = True),
        "description": "median, mean, stdDev, min & max",
        "stat_suffix": ["median", "mean", "stdDev", "min", "max"]
    }
]

reducer_catalog = {r["reducer_code"]: Reducer(**r) for r in _reducer_list}
