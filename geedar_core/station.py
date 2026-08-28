#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Virtual station abstraction used by GEEDaR."""



#%% VirtualStation class

class VirtualStation:
    """
    A virtual station is an area of interest, defined by a geometry
    (ee.Geometry), with an id code.

    Instantiation
    -------------

        aoi: geometry defining the area of interest (ee.Geometry or
            ee.Feature).
        station_code: str for the station code (str; if an int is passed, it
            will be converted to str).
        station_name: the station name (str, optional).
        lat: decimal latitude (float, optional).
        long: decimal longitude (float, optional).

    Attributes
    ----------

        aoi: ee.Geometry.
        station_code: str.
        station_name: str.
        lat: float.
        long: float.

    Methods
    -------

        update_aoi: takes an ee.Geometry or an ee.Feature and updates the area
            of interest which defines the virtual station.
        update_code: updates the virtual station code.

    """

    def __init__(self, aoi, station_code, station_name=None,
            lat=None, long=None):

        # Set/check the code.
        self.update_code(station_code)

        # Set/check the name.
        if station_name is None:
            station_name = ""
        if type(station_name) is not str:
            raise TypeError("'station_name' must be a str.")
        self.station_name = station_name

        # Set/check the area of interest.
        self.update_aoi(aoi)

        # Check lat/long. If not provided, get the geometry center.

        if lat is None or long is None:
            coords = aoi.centroid().getInfo()["coordinates"]
        if lat is None:
            lat = coords[1]
        if long is None:
            long = coords[0]

        self.lat = lat
        self.long = long

    @property
    def aoi(self):
        return self._aoi

    @aoi.setter
    def aoi(self, aoi):
        self.update_aoi(aoi)

    @property
    def station_code(self):
        return self._station_code

    @station_code.setter
    def station_code(self, station_code):
        self.update_code(station_code)

    @property
    def lat(self):
        return self._lat

    @lat.setter
    def lat(self, lat):
        if type(lat) not in [float, int]:
            raise TypeError("'lat' must be numeric.")
        self._lat = lat

    @property
    def long(self):
        return self._long

    @long.setter
    def long(self, long):
        if type(long) not in [float, int]:
            raise TypeError("'long' must be numeric.")
        self._long = long

    # Updates the area of interest:
    def update_aoi(self, aoi):
        """
        Takes an ee.Geometry or an ee.Feature and updates the area of interest
        which defines the virtual station. Returns None.

        """

        if not type(aoi).__name__ in ["Geometry","Feature"]:
            raise TypeError("'aoi' must be ee.Geometry or ee.Feature.")
        if type(aoi).__name__ == "Feature":
            self._aoi = aoi.geometry()
        else:
            self._aoi = aoi

    # Updates the station code:
    def update_code(self, station_code):
        """
        Updates the virtual station code (str). Returns None.

        """
        if type(station_code) is int:
            station_code = str(station_code)
        if type(station_code) is not str:
            raise TypeError("'station_code' must be a str.")
        self._station_code = station_code
