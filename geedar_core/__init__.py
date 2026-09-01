#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core classes used by the GEEDaR application."""

__version__ = "2.1"

from .app import GeedarApp
from .cloud_algorithm import CloudAlgorithm
from .database import GeedarDB
from .demand import Demand
from .instrument import Instrument
from .local_algorithm import LocalAlgorithm
from .options import UserOptions
from .product import Product
from .reducer import Reducer
from .station import VirtualStation
from .variable import Variable

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
