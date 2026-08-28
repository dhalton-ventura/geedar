#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the modular GEEDaR class layout."""

import unittest

import geedar_core
import geedar_classes
from geedar_core.algorithms import CloudAlgorithm, LocalAlgorithm
from geedar_core.app import GeedarApp
from geedar_core.catalog_types import Instrument, Reducer, Variable
from geedar_core.database import GeedarDB
from geedar_core.demand import Demand
from geedar_core.options import UserOptions
from geedar_core.product import Product
from geedar_core.station import VirtualStation
from geedar_core import utils


class ModularImportTests(unittest.TestCase):
    def test_version_is_consistent(self):
        self.assertEqual(geedar_core.__version__, "2.1")
        self.assertEqual(geedar_classes.__version__, geedar_core.__version__)

    def test_legacy_exports_are_unchanged(self):
        self.assertEqual(
            geedar_classes.__all__,
            [
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
            ],
        )

    def test_legacy_class_imports_reference_modular_classes(self):
        expected_classes = {
            "Product": Product,
            "VirtualStation": VirtualStation,
            "CloudAlgorithm": CloudAlgorithm,
            "LocalAlgorithm": LocalAlgorithm,
            "Demand": Demand,
            "Variable": Variable,
            "Instrument": Instrument,
            "Reducer": Reducer,
            "GeedarDB": GeedarDB,
            "UserOptions": UserOptions,
            "GeedarApp": GeedarApp,
        }
        for name, expected_class in expected_classes.items():
            with self.subTest(name=name):
                self.assertIs(getattr(geedar_classes, name), expected_class)

    def test_legacy_helper_imports_reference_modular_helpers(self):
        helper_names = [
            "is_path_valid",
            "which",
            "text_box",
            "autocast_str",
            "str_to_list",
            "val_to_sql",
            "list_to_sql",
            "cast_numeric_list",
            "unfold_df_lists",
            "restore_df_lists",
            "reduce_list",
            "extract_from_kml",
        ]
        for name in helper_names:
            with self.subTest(name=name):
                self.assertIs(getattr(geedar_classes, name), getattr(utils, name))


if __name__ == "__main__":
    unittest.main()
