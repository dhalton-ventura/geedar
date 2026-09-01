#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orbital instrument type used by the GEEDaR catalogs."""


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


__all__ = ["Instrument"]
