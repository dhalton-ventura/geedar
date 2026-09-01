#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Variable type used by the GEEDaR catalogs."""


class Variable:
    """
    A variable object holds information on a variable related to a local
    algorithm. It is used to build a variable catalog which will be loaded by
    GeedarApp and then saved into the target database (only when GEEDaR is
    running in database mode). It is important to note that variables
    resulting from local algorithms are automatically saved in the database,
    even if there is no corresponding Variable object in the catalog. The
    advantage of using a catalog of variable objects, however, is that the
    variables are saved in the database with complete information instead of
    only the column names resulted from the local algorithm.

    Instantiation
    -------------

    To instatiate a Variable object, you must provide:

        var_code: the number which will identify the variable (int). It is not
            the number of the record id in the database, but a number for
            allocation in the variable catalog used by GeedarApp.
        name: the short (internal) identification corresponding to a column
            name in the result data frame of a local algorithm (excluded the
            suffix for the stats; ex: 'TSS' from 'TSS_median') (str).
        unit: the abbreviation of the unit (ex: 'mg/L') (str).
        description: longer identification (ex: 'Total Suspended Solids (TSS),
            in milligrams per liter (mg/L)') (str).
        label: the way a variable will be displayed on application
            messages, graphical interfaces etc. (ex: 'TSS (mg/L)') (str).

    Attributes
    ----------
        var_code
        name
        unit
        description
        label

    Methods
    -------
        (none)

    """

    def __init__(self, var_code, name, unit=None, description=None, label=None):
        if type(var_code) is not int:
            raise TypeError("'var_code' must be an int.")
        if type(name) is not str:
            raise TypeError("'name' must be a str.")
        if unit is None:
            unit = ""
        if type(unit) is not str:
            raise TypeError("'unit' must be a str.")
        if description is None:
            description = name
        if type(description ) is not str:
            raise TypeError("'description' must be a str.")
        if label is None:
            if len(unit) == 0:
                label = name + " (" + unit + ")"
            else:
                label = name
        if type(label) is not str:
            raise TypeError("'label' must be a str.")

        self.var_code = var_code
        self.name = name
        self.unit = unit
        self.description = description
        self.label = label


__all__ = ["Variable"]
