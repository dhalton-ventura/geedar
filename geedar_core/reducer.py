#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reducer type used by GEEDaR processing demands."""


class Reducer:
    """
    A wrapper for ee.Reducer with complementary attributes.

    Instantiation
    -------------

        reducer_code: a unique identifier (int).
        ee_reducer: ee.Reducer object.
        stat_suffix: a list with the suffixes added by GEE to the image bands
            upon application of the ee.Reducer passed in 'ee_reducer' (list of
            str).
        description: describes what is calculated by the reducer (ex: 'median',
            'mean', 'count' etc.) (str).

    Attributes
    ----------

    All attributes come from the arguments for instantiation:

        reducer_code
        ee_reducer
        stat_suffix
        description

    Methods
    -------

        (none)

    """
    def __init__(self, reducer_code, ee_reducer, stat_suffix,
            description=""):

        if type(reducer_code) is not int:
            raise TypeError("'reducer_code' must be an integer.")
        if type(ee_reducer).__name__ != "Reducer":
            raise TypeError("'ee_reducer' must be an ee.Reducer.")
        if type(stat_suffix) is not list:
            raise TypeError("'stat_suffix' must be a list.")
        if not all(type(s) is str for s in stat_suffix):
            raise TypeError("'stat_suffix' must be a list of strings.")
        if type(description) is not str:
            raise TypeError("'description' must be a str.")

        self.reducer_code = reducer_code
        self.ee_reducer = ee_reducer
        self.stat_suffix = stat_suffix
        self.description = description


__all__ = ["Reducer"]
