#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the one-class-per-module GEEDaR layout."""

from pathlib import Path
import unittest

import geedar_core
from geedar_core.app import GeedarApp
from geedar_core.cloud_algorithm import CloudAlgorithm
from geedar_core.database import GeedarDB
from geedar_core.demand import Demand
from geedar_core.instrument import Instrument
from geedar_core.local_algorithm import LocalAlgorithm
from geedar_core.options import UserOptions
from geedar_core.product import Product
from geedar_core.reducer import Reducer
from geedar_core.station import VirtualStation
from geedar_core.variable import Variable


class ModularImportTests(unittest.TestCase):
    def test_version_is_unchanged(self):
        self.assertEqual(geedar_core.__version__, "2.1")

    def test_package_exports_are_unchanged(self):
        self.assertEqual(
            geedar_core.__all__,
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

    def test_package_exports_reference_canonical_modules(self):
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
                self.assertIs(getattr(geedar_core, name), expected_class)

    def test_each_moved_class_has_its_own_module(self):
        expected_modules = {
            Instrument: "geedar_core.instrument",
            Variable: "geedar_core.variable",
            Reducer: "geedar_core.reducer",
            CloudAlgorithm: "geedar_core.cloud_algorithm",
            LocalAlgorithm: "geedar_core.local_algorithm",
        }
        for cls, expected_module in expected_modules.items():
            with self.subTest(name=cls.__name__):
                self.assertEqual(cls.__module__, expected_module)

    def test_replaced_modules_were_removed(self):
        project_root = Path(__file__).resolve().parents[1]
        removed_paths = [
            project_root / "geedar_classes.py",
            project_root / "geedar_core" / "algorithms.py",
            project_root / "geedar_core" / "catalog_types.py",
        ]
        for path in removed_paths:
            with self.subTest(path=path.name):
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
