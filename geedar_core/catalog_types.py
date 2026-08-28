#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small value types used by the GEEDaR catalogs."""



#%% Instrument class

class Instrument:
    """
    An instrument object holds information on an orbital remote sensor. This
    object is used as an input parameter when creating a Product object.

    Instantiation
    -------------

    To instatiate an Instrument object, you must provide:

        inst_code: the number which will identify the instrument (int).
        name: name or short identification (ex: 'MSI') (str).
        mission: name or short identification of the satellite or
            program (str).
        revisit: mean interval, in days, between data acquisitions
            (int or float).
        description: longer identification of the instrument (ex:
            'Multispectral Imager (MSI), onboard of the satellites of
            Sentinel-2 mission') (str). Defaults to the same value of 'name'.
        label: the way an instrument will be displayed on application
            messages, graphical interfaces etc. (ex: 'MSI/Sentinel-2') (str).
            Defaults to the same value of 'name'.

    Attributes
    ----------
        inst_code
        name
        mission
        revisit
        description
        label

    Methods
    -------
        (none)

    """

    def __init__(self, inst_code, name, mission, revisit,
            description=None, label=None):
        if type(inst_code) is not int:
            raise TypeError("'inst_code' must be an int.")
        if type(name) is not str:
            raise TypeError("'name' must be a str.")
        if type(mission) is not str:
            raise TypeError("'mission' must be a str.")
        if type(revisit) not in [int, float]:
            raise TypeError("'revisit' must be numeric.")
        if description is None:
            description = name
        if type(description ) is not str:
            raise TypeError("'description' must be a str.")
        if label is None:
            label = name
        if type(label) is not str:
            raise TypeError("'label' must be a str.")

        self.inst_code = inst_code
        self.name = name
        self.mission = mission
        self.revisit = revisit
        self.description = description
        self.label = label


#%% Variable class

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



#%% Reducer class

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
