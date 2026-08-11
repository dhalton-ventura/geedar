# -*- coding: utf-8 -*-
"""
Builds a catalog of variables.

The catalog will be saved into the database used with GEEDaR. It is only 
relevant when using GEEDaR in mode 3 (database). And even in mode 3 this 
module function is not crucial. If no variable is inserted in the list below,
the database will be filled with the variable names derived from the columns
in the dataframe resulting from local algorithms used*. The advantage of using
this module is simply ensuring that variables are pre-saved in the database 
with complete information (meas. unit, description and label).

* On local algorithms, see the module 'local_algorithms.py'.

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

from geedar_classes import Variable


#%% Export

__all__ = ["variable_catalog"]


#%% Catalog

_var_list = [
    {
        "var_code": 1,
        "name": "SSS",
        "unit": "mg/L",
        "description": "Sedimentos em Suspensão na Superfície (SSS), "
            + "em miligramas por litro (mg/L).",
        "label": "SSS (mg/L)"
    },
    {
        "var_code": 2,
        "name": "SS",
        "unit": "mg/L",
        "description": "Sedimentos em Suspensão (SS), "
            + "em miligramas por litro (mg/L).",
        "label": "SS (mg/L)"
    },
    {
        "var_code": 3,
        "name": "Turb",
        "unit": "NTU",
        "description": "Turbidez, em Unidades de Turbidez Nefelométrica.",
        "label": "Turbidez (NTU)"
    },
    {
        "var_code": 4,
        "name": "Chla",
        "unit": "µg/L",
        "description": "Clorofila a (Chla), "
            + "em microgramas por litro (µg/L).",
        "label": "Chla (µg/L)"
    }
]

variable_catalog = {v["var_code"]: Variable(**v) for v in _var_list}
