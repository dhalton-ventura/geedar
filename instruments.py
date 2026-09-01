# -*- coding: utf-8 -*-
"""
Provides a catalog of instruments to be available for GEEDaR.

Instrument objects are used in GEEDaR as a parameter of Product objects. They 
hold information on satellite sensors, such as mission, revisit time and 
description. Such information will be saved in the target database (when 
running GEEDaR in mode 3).

The catalog below is required by the module Products, since each GEEDaR 
product must be linked to an instrument.

"""

__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.1"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"


#%% Import

from geedar_core.instrument import Instrument


#%% Export

__all__ = ["instrument_catalog"]


#%% Catalog

_instrument_list = [
    {
        "inst_code": 1,
        "name": "Modis/Terra",
        "mission": "Terra",
        "revisit": 1,
        "description": "Modis sensor onboard of NASA's Terra satellite.",
        "label": "Terra"
    },
    {
        "inst_code": 2,
        "name": "Modis/Aqua",
        "mission": "Aqua",
        "revisit": 1,
        "description": "Modis sensor onboard of NASA's Aqua satellite.",
        "label": "Aqua"
    },
    {
        "inst_code": 3,
        "name": "Modis/Terra & Aqua",
        "mission": "Terra & Aqua",
        "revisit": 1,
        "description": "Modis sensor on NASA's Terra and Aqua satellites.",
        "label": "Terra & Aqua"
    },
    {
        "inst_code": 4,
        "name": "VIIRS/SNPP",
        "mission": "Suomi NPP",
        "revisit": 1,
        "description": "Visible Infrared Imaging Radiometer Suite (VIIRS) "
            + "sensor on the NASA/NOAA Suomi National Polar-orbiting "
            + "Partnership (Suomi NPP) satellite.",
        "label": "VIIRS"
    },
    {
        "inst_code": 5,
        "name": "MSI/Sentinel-2",
        "mission": "Sentinel-2",
        "revisit": 5,
        "description": "Multispectral Imager (MSI), onboard of Sentinel-2 "
            + "satellites (S2A, S2B...).",
        "label": "Sentinel-2"
    },
    {
        "inst_code": 6,
        "name": "TM/Landsat 4",
        "mission": "Landsat 4",
        "revisit": 16,
        "description": "Thematic Mapper (TM) on the Landsat 4 satellite.",
        "label": "Landsat 4"
    },
    {
        "inst_code": 7,
        "name": "TM/Landsat 5",
        "mission": "Landsat 5",
        "revisit": 16,
        "description": "Thematic Mapper (TM) on the Landsat 5 satellite.",
        "label": "Landsat 5"
    },
    {
        "inst_code": 8,
        "name": "ETM+/Landsat 7",
        "mission": "Landsat 7",
        "revisit": 16,
        "description": "Enhanced Thematic Mapper (ETM+) on the Landsat 7 "
            + "satellite.",
        "label": "Landsat 7"
    },
    {
        "inst_code": 9,
        "name": "OLI/Landsat 8",
        "mission": "Landsat 8",
        "revisit": 16,
        "description": "Operational Land Imager (OLI) on the Landsat 8 "
            + "satellite.",
        "label": "Landsat 8"
    },
    {
        "inst_code": 10,
        "name": "OLI/Landsat 9",
        "mission": "Landsat 9",
        "revisit": 16,
        "description": "Operational Land Imager (OLI) on the Landsat 9 "
            + "satellite.",
        "label": "Landsat 9"
    },
    {
        "inst_code": 11,
        "name": "GPM",
        "mission": "GPM",
        "revisit": 1,
        "description": "The Global Precipitation Measurement (GPM) mission.",
        "label": "GPM"
    },
    {
        "inst_code": 12,
        "name": "C-SAR/Sentinel-1",
        "mission": "Sentinel-1",
        "revisit": 6,
        "description": "C-band Synthetic Aperture Radar (C-SAR) instrument on the Sentinel-1 satellites (S1A, S1B).",
        "label": "Sentinel-1"
    }
]

instrument_catalog = {i["inst_code"]: Instrument(inst_code=i["inst_code"], 
    name=i["name"], mission=i["mission"], revisit=i["revisit"], 
    description=i["description"], label=i["label"]) for i in _instrument_list}

