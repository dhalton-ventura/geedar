#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core classes used by the GEEDaR application."""

__version__ = "2.1"

from .algorithms import CloudAlgorithm, LocalAlgorithm
from .app import GeedarApp
from .catalog_types import Instrument, Reducer, Variable
from .database import GeedarDB
from .demand import Demand
from .options import UserOptions
from .product import Product
from .station import VirtualStation

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
