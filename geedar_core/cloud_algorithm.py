#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cloud algorithm abstraction used by GEEDaR."""

import ee

from .utils import _validate_args_dict


class CloudAlgorithm:
    """
    Encapsulates a function or combination of functions to be applied to an
    image collection. The application is assynchronous, only being executed
    later when the results are effectively requested from the server.

    Instantiation
    -------------

    For instantiation, it must be passed a dictionary containing:
        "algo_code": unique indentifier (int).
        "name": name identifying the algorithm (str).
        "description": the most important information on the algorithm (str).
        "ref": references to literature or URL (str).
        "required_bands": required bands, with the 'real' band names or with
            their 'common' names (see Product._common_bands) (list of str).
        "main_function": a function object with the algorithm core (function).
            In this main function, auxilliary functions (see below) may be
            called.
        "aux_functions": auxilliary functions that may be called by the main
            function (list of function objects).
        "export_vars": a list of resulting variables to be added as a property
            of each image in the processed collection (list of str).
        "export_bands": result bands added by the algorithm to the images
            (list of str).
        "options": a dictionary of options for the algorithm (dict or None,
            optional).

    An example:
    {
        "algo_code": 15,
        "name": "Bloom-Tolerant Water Selection",
        "description": "Selects 'good' water pixels, including those affected "
            + "by dense algal blooms, and excluding pixels affected by glint "
            + "and strong spectral mixture or adjacency effects.",
        "ref": "Ventura, D.L.T.V. (unpublished)",
        "required_bands": ["blue","green","red","NIR","wl1500","wl2000"],
        "main_function": bloom_tolerant_water_selection, # function name
        "aux_functions": [_set_pixel_count, _mask_bad_pixels,
            _simple_cloud_mask, _simple_water_detection, _simple_shadow_mask,
            _water_product_qual_flag],
        "export_vars": ["n_selected_pixels", "n_valid_pixels",
            "n_total_pixels", "n_bloom_pixels", "n_water_pixels", "qual_flag"],
        "export_bands": [],
        "options": None
    }

    Attributes
    ----------

    All these attributes come from the arguments for instantiation:

        algo_code
        name
        description
        ref
        required_bands
        main_function
        aux_functions
        export_vars
        export_bands
        options

    This is added in instantiation:

        add_coords: add bands for latitude and longitude to each image (bool).

    Methods
    -------

        apply: applies the algorithm to an image collection.

    """

    # Required constructor arguments and their accepted types.
    _required_args = {
        "algo_code": {"types": ["int"], "values": []},
        "name": {"types": ["str"], "values": []},
        "description": {"types": ["str"], "values": []},
        "ref": {"types": ["str"], "values": []},
        "required_bands": {"types": ["list", ["str", "list", "empty"]],
            "values": []},
        "main_function": {"types": ["function"], "values": []},
        "aux_functions": {"types": ["list", ["function"]], "values": []},
        "export_vars": {"types": ["list", ["str", "empty"]], "values": []},
        "export_bands": {"types": ["list", ["str", "empty"]], "values": []},
        "options": {"types": ["dict", "NoneType"], "values": []}
    }

    # Constructor.
    # Help on instantiation is in the class docstring.
    def __init__(self, args_dict):

        # Validate the dictionary of arguments.
        _validate_args_dict(args_dict, self._required_args)

        # Set the instance attributes from the input dictionary.
        for key, value in args_dict.items():
            # Only set an attribute if it is a required one.
            if key in self._required_args:
                setattr(self, key, value)

        # Attribute regarding the addition of coordinate bands.
        self._add_coords = False
        options = args_dict["options"]
        if isinstance(options, dict):
            if "add_coords" in options:
                if options["add_coords"]:
                    self.add_coords = True

    @property
    def add_coords(self):
        return self._add_coords
    @add_coords.setter
    def add_coords(self, val):
        if not isinstance(val, bool):
            raise TypeError("'add_coords' is boolean.")
        cur_val = self._add_coords
        # Update options and export_bands?
        if val and cur_val != val:
            if self.options is None:
                self.options = dict()
            self.options["add_coords"] = True
            if "latitude" not in self.export_bands:
                self.export_bands.append("latitude")
            if "longitude" not in self.export_bands:
                self.export_bands.append("longitude")
        self._add_coords = val

    # Adds to the image collection resulting from an algorithm, bands of
    # latitude and longitude values.
    def _add_coord_bands(self, image_collection, ref_band):
        def add_coords(image):
            masked_coords = ee.Image.pixelLonLat().updateMask(
                image.select(ref_band).mask())
            image = image.addBands(masked_coords)
            return image
        return ee.ImageCollection(image_collection).map(add_coords)

    # Applies the algorithm.
    def apply(self, product, virtual_station, image_collection=None,
              options=None):
        """
        Applies the algorithm to an image collection given a virtual station
        and a GEEDaR product.

        Parameters
        ----------

            product: an instance of the class Product, containing the image
                collection that will be processed (and modified).
            virtual_station: a VirtualStation instance.
            image_collection: the image collection to be processed
                (ee.ImageCollection, optional). If not provided, the
                collection of the Product object will be used.
            options: dictionary with variables to be used by the algorithm
                (dict, optional).

        Returns
        -------

            ee.ImageCollection (or None if it fails).

        """

        # Check the parameters.

        if type(product).__name__ != "Product":
            raise TypeError("'product' must be an instance of the "
                + "Product class.")
        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be an instance of "
                + "VirtualStation.")
        if image_collection is not None:
            if type(image_collection).__name__ != "ImageCollection":
                raise TypeError("'image_collection' must be an "
                    + "ee.ImageCollection object.")
        else:
            image_collection = product.collection

        product_code = product.product_code

        if options is None:
            options = dict()
        if type(options) is not dict:
            raise TypeError("'options' must be a dictionary")
        if self.options is not None:
            options = self.options | options # Add predefined options

        # Check band compatibility.
        bands = [*product.get_data_bands()] + product.band_list
        required_bands = self.required_bands
        missing_bands = []
        for sublist in required_bands:
            if not isinstance(sublist, list):
                sublist = [sublist]
            if not any(band in sublist for band in bands):
                missing_bands.append("or".join(
                    [band for band in sublist if band not in bands]))
        if len(missing_bands) > 0:
            raise TypeError("The algorithm '" + self.name + "' requires bands "
                + "that are not available in the product of code "
                + str(product_code) + ": " + str(missing_bands))

        # Load the auxilliary functions.
        for func in self.aux_functions:
            exec(func.__name__ + " = func")

        # Apply the main function.
        try:
            image_collection = self.main_function(product, virtual_station,
                image_collection, options)
            # Add coordinates as bands?
            if self._add_coords:
                image_collection = self._add_coord_bands(image_collection,
                    product.scale_ref_band)
            return image_collection
        except Exception:
            raise


__all__ = ["CloudAlgorithm"]
