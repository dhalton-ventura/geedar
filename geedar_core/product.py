#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Satellite product abstraction used by GEEDaR demands."""

import math
import ee
from datetime import datetime, date, timedelta

from .utils import _validate_args_dict

#%% Product class

class Product:
    """
    A wrapper for a specific image collection (or combination of collections)
    of GEE with added methods and attributes used by GEEDaR. Each Product
    must have a unique id (code).

    Instantiation
    -------------

    For instantiation, it must be passed a dictionary containing:

        "product_code": the product unique identifier (int).
        "product_name": a unique and short name to identify the product (str).
        "description": a text describing the product (str).
        "instrument": an oject of the class Instrument.
        "collection": an Earth Engine ImageCollection.
        "start_date": the date of the earliest image in the collection (str in
            the format 'yyyy-mm-dd' or datetime.date).
        "fixed_time": a default time to be used as the image time (str in the
            format 'hh:mm' or None). Necessary for image collections where the
            images have no useful value for the time of acquisition (ex: Modis
            collections).
        "scale_ref_band": the band used as the default spatial scale for the
            processings with this product (str).
        "rough_scale": an approximate value of spatial scale for the product,
            such as the horizontal resolution at nadir (int).
        "need_to_mosaic": indicates if more than one image may be available
            for a given date and area of interest (bool).
        "band_list": the list of bands of the EE product (list of str).
        "quality_layer_names": the bands containing data for qualification of
            the pixels (list of str).
        "quality_layer_inds": the indices of such bands (relative to the
            attribute 'band_list') defining how to iterate trough the quality
            layers in the pixel masking method applied to the product (list of
            int).
        "quality_layer_start_bits": a list of starting positions of the bits
            useful for pixel qualification in the quality layers (list of int).
        "quality_layer_end_bits": a list of ending positions of the bits useful
            for pixel qualification in the quality layers (list of int).
        "test_expression": the numerical or logical expression applied to the
            quality layers after masking the bits of no interest (list of str).
        "scaling_factor": a list with the coefficients used for rescaling the
            pixel values in each band. It will be an empty list when no
            rescaling is applicable (list of int or float).
        "offset": the offset applied to pixel values in the "data bands" (list
            of int or float).
        "data_band_inds": the indices of the "data_bands" (relative to the
            attribute 'band_list') (list of int).
        "common_bands": a dictionary with the common names of bands (ex: blue,
            green, red...) used across products and their indices relative to
            'band_list' (a value of -1 is used for absent common bands) (dict).
        "vis_params": a dictionary with visualization parameters for GEE. It
            may be empty, but must be a dictionary (dict).

    An example:
    {
        "product_code": 102,
        "product_name": "MYD09GA",
        "instrument": INSTRUMENT_CATALOG[2], # Modis/Aqua
        "description": "Daily MODIS/Aqua 500-m images, bands 1-7,
            collection 6.1",
        "collection": ee.ImageCollection("MODIS/061/MYD09GA"),
        "start_date": "2002-07-04",
        "fixed_time": "13:30",
        "scale_ref_band": "sur_refl_b01",
        "rough_scale": 500,
        "need_to_mosaic": False,
        "band_list": ["sur_refl_b01", "sur_refl_b02", "sur_refl_b03",
            "sur_refl_b04", "sur_refl_b05", "sur_refl_b06", "sur_refl_b07",
            "QC_500m", "state_1km", "SensorZenith", "SensorAzimuth",
            "SolarZenith", "SolarAzimuth"],
        "quality_layer_names": ["state_1km"],
        "quality_layer_inds": [0,0,0],
        "quality_layer_start_bits": [0, 6, 8],
        "quality_layer_end_bits": [2, 7, 10],
        "test_expression": ["b(0) == 0", "b(0) < 2", "b(0) == 0"],
        "scaling_factor": [],
        "offset": [],
        "data_band_inds": [*range(7)],
        "common_bands": {"blue": 2, "green": 3, "red": 0, "NIR": 1, "SWIR": 5,
            "wl400": -1, "wl440": -1, "wl490": 2, "wl620": -1, "wl665": -1,
            "wl675": -1, "wl680": -1, "wl705": -1, "wl740": -1, "wl780": -1,
            "wl800": 1, "wl900": -1, "wl1200": 4, "wl1500": 5, "wl2000": 6,
            "wl10500": -1, "wl11500": -1},
        "vis_params": {"bands": ["sur_refl_b01","sur_refl_b04","sur_refl_b03"],
            "min": 0, "max": 2000}
    }

    Attributes
    ----------

    These ones originate from the arguments for instantiation:

        product_code: the product unique identifier.
        product_name: a unique and short name to identify the product.
        description: a text describing the product.
        instrument: an oject of the class Instrument.
        collection: an Earth Engine object of ImageCollection.
        start_date: the date of the earliest image in the collection
            (datetime.date).
        fixed_time: a default time to be used as the image time. Necessary for
            EE collections where the images have no useful value for the time
            of acquisition (ex: Modis collections).
        scale_ref_band: the band used as the default spatial scale for the
            processings with this product.
        rough_scale: an approximate value of spatial scale for the product,
            such as the horizontal resolution at nadir.
        need_to_mosaic: indicates if more than one image may be available
            for the same date and area of interest.
        band_list: the list of bands of the EE product.
        quality_layer_names: the bands containing data for qualification of
            the pixels.
        quality_layer_inds: the indices of such bands (relative to the
            attribute 'band_list') defining how to iterate trough the quality
            layers in the pixel masking method applied to the product.
        quality_layer_start_bits: a list of starting positions of the bits
            useful for pixel qualification in the quality layers.
        quality_layer_end_bits: a list of ending positions of the bits useful
            for pixel qualification in the quality layers.
        test_expression: the numerical or logical expression applied to the
            quality layers after masking the bits of no interest.
        scaling_factor: a list with the coefficients used for rescaling the
            pixel values in each band. It will be an empty list when no
            rescaling is applicable.
        offset: the offset applied to pixel values in the "data bands".
        data_band_inds: the indices of the "data_bands" (relative to the
            attribute 'band_list').
        common_bands: a dictionary with the common names of bands (ex: blue,
            green, red...) used across products and their indices relative to
            'band_list' (a value of -1 is used for absent common bands).
        vis_params: a dictionary with visualization parameters for GEE.

    These ones are added in instantiation:

        end_date: the end of the period of interest used to filter the
            collection with the method 'optimize_collection' (None at
            instantiation; datetime.date after the 'optimize_collection').
        date_list: the list of dates used to filter the images in the
            collection through the method 'optimize_collection' (an empty list
            at instantiation; a list f date strings after executing
            'optimize_collection').
        available_dates: the list of dates available after filtering the image
            collection with the method 'optimize_collection' (an empty list
            at instantiation; a list of date + time strings in the format
            'yyyy-mm-dd hh:mm' after executing 'optimize_collection').
        original_collection: the full, non-optimized image collection.

    Methods
    -------

        reset: resets the Product object to its original attribute values.
        new: returns a new Product object from the original constructor
            arguments.
        get_data_bands: returns a dictionary with the names and indices of the
            bands with data to be processed, such as the spectral bands. Bands
            are included both with their original names and with 'common names'
            (blue, green etc.).
        optimize_collection: optimizes this object's image collection by
            filtering the images to the area and period of interest, as well
            as applying necessary rescaling factors, mosaicking and clipping,
            if applicable.
        mask_bad_pixels: masks the bad pixels in each image of this object's
            collection (those affected by clouds, for example) using the
            standard pixel quality layers of the images.
        apply_cloud_algo: apply the algorithm contained by a CloudAlgo object
            to this object's collection.

    """

    # Required constructor arguments and their accepted types.
    _required_args = {
        "product_code": {"types": ["int"], "values": []},
        "product_name": {"types": ["str"], "values": []},
        "description": {"types": ["str"], "values": []},
        "instrument": {"types": ["Instrument"], "values": []},
        "collection": {"types": ["ImageCollection"], "values": []},
        "start_date": {"types": ["str", "date"], "values": []},
        "fixed_time": {"types": ["str", "NoneType"], "values": []},
        "scale_ref_band": {"types": ["str"], "values": []},
        "rough_scale": {"types": ["int","float"], "values": []},
        "need_to_mosaic": {"types": ["bool"], "values": []},
        "band_list": {"types": ["list", ["str"]], "values": []},
        "quality_layer_names": {"types": ["list", ["str", "empty"]],
            "values": []},
        "quality_layer_inds": {"types": ["list", ["int", "empty"]],
            "values": []},
        "quality_layer_start_bits": {"types": ["list", ["int", "empty"]],
            "values": []},
        "quality_layer_end_bits": {"types": ["list", ["int", "empty"]],
            "values": []},
        "test_expression": {"types": ["list", ["str", "empty"]],
            "values": []},
        "scaling_factor": {"types": ["list", ["int", "float", "empty"]],
            "values": []},
        "offset": {"types": ["list", ["int", "float", "empty"]], "values": []},
        "data_band_inds": {"types": ["list", ["int", "empty"]], "values": []},
        "common_bands": {"types": ["dict"], "values": []},
        "vis_params": {"types": ["dict"], "values": []}
    }

    # Common band names for universal use (across products).
    # The same image band may be indexed in more than one of these common band
    # keys (ex: in 'blue' and in 'wl490').
    # 'wl' stands for wavelength.
    _common_band_list = ["blue", "green", "red", "NIR", "SWIR", "wl400",
        "wl440", "wl490", "wl620", "wl665", "wl675", "wl680", "wl705", "wl740",
        "wl780", "wl800", "wl900", "wl1200", "wl1500", "wl2000", "wl10500",
        "wl11500"]

    # Constructor. Insructions on instatiation are in the class docstring.
    def __init__(self, args_dict):

        # Store arguments to allow for recreating the product (method 'new').
        self._args_dict = args_dict.copy()

        # Validate the dictionary of arguments.
        _validate_args_dict(args_dict, self._required_args)

        # Check the common_bands dictionary.
        if not Product._validate_common_bands(args_dict["common_bands"]):
            raise TypeError("Wrong band list in the 'common_bands' dictionary "
                + "included in the input dictionary: "
                + str(args_dict["common_bands"]) + ".")

        # Store the unchanged image collection.
        self.original_collection = args_dict["collection"]

        # Convert attributes with flexibe input format to a single standard
        # format.

        # Convert date from string to datetime.date.
        if isinstance(args_dict["start_date"], str):
            try:
                args_dict["start_date"] = datetime.strptime(
                    args_dict["start_date"], "%Y-%m-%d").date()
            except:
                raise TypeError("Could not interpret the string passed in "
                    + "'start_date': '" + args_dict["start_date"]
                    + "'. Required format: 'yyyy-mm-dd'.")

        # Set the attributes from the input dictionary.
        for key, value in args_dict.items():
            # Only set an attribute if it is a required one.
            if key in self._required_args:
                setattr(self, key, value)
        # Only 'start_date' was in the constructor arguments.
        self.end_date = None
        self.date_list = []

        # The available dates will only be filled with the method
        # 'optimize_collection', which will filter the image collection by
        # the location and the period of interest.
        self.available_dates = []
        # Flag for avoiding double application of 'optimize_collection':
        self._optimized = False

        # Store the attribute values to allow for resetting the product.
        self._backup = self.__dict__.copy()

    # Validation: 'common_bands' passed in the input dictionary has all
    # required bands? [True, False]
    @staticmethod
    def _validate_common_bands(common_bands_dict):
        return all(key in [*common_bands_dict]
            for key in Product._common_band_list)

    def reset(self):
        """
        Resets the Product object to its original attribute values.

        """
        for key, value in self._backup.items():
            setattr(self, key, value)

    def new(self):
        """
        Returns a new Product object from the original constructor arguments.

        """
        return Product(self._args_dict)

    # Returns a dictionary with the band names corresponding to the common
    # data bands, such as those corresponding to spectral regions (blue,
    # green, red, ...).
    def get_data_bands(self):
        """
        Returns a dictionary with the names and indices of the bands with data
        to be processed, such as the spectral bands. Bands are included both
        with their original names and with 'common names' (blue, green etc.).

        """

        common_bands = self.common_bands
        band_list = self.band_list
        data_band_inds = self.data_band_inds

        common_bands_dict = {k: band_list[v] for k, v in common_bands.items()
            if v >= 0}
        data_bands_list = [band_list[v] for v in data_band_inds]
        data_bands_dict = {k: k for k in data_bands_list}
        return {**common_bands_dict, **data_bands_dict}

    # Optimizes the product collection by filtering the images to the area and
    # period of interest, as well as applying necessary rescaling factors,
    # mosaicking and clipping, if applicable.
    def optimize_collection(self, virtual_station, start_date=None,
            end_date=None, date_list=None, clip=False):
        """
        Optimizes the product collection by filtering the images to the area
        and period of interest, as well as applying necessary rescaling
        factors, mosaicking and clipping, if applicable.

        Returns nothing.

        Parameters
        ----------

            virtual_station: VirtualStation object.
            start_date: datetime.date or string in the format "yyyy-mm-dd"
                (optional).
            end_date: datetime.date or string in the format "yyyy-mm-dd"
                (optional).
            date_list : list with dates (str or datetime.date) (optional).
            clip : clip each image to the area of interest? (bool, optional)

        """

        # If product was already filtered, it must be reset before new
        # filtering. For example, using a different area of interest in the
        # second attempt would result in an empty collection.
        if self._optimized:
            self.reset()

        # Auxilliary function for setting image properties.
        def set_prop(image):
            image = ee.Image(image)
            img_date = image.date()
            return ee.Image(image.set(
                "img_date", img_date.format("YYYY-MM-dd"),
                "img_time", img_date.format("HH:mm"),
                "img_datetime", img_date.format("YYYY-MM-dd HH:mm")))

        # Auxilliary function for image mosaicking.
        def mosaic_by_date(dt_str, coll):
            date_str = ee.String(dt_str)
            date = ee.Date.parse("YYYY-MM-dd HH:mm", date_str)
            date_filter = ee.Filter.date(date, date.advance(1, "day"))
            local_coll = coll.filter(date_filter)
            first_img = local_coll.first()
            props = first_img.toDictionary(
                first_img.propertyNames()).remove(["system:footprint"], True)
            proj = first_img.select(product.scale_ref_band).projection()
            band_names = first_img.bandNames()
            mosaic = ee.Image(local_coll.reduce(ee.Reducer.median()).set(
                props)).setDefaultProjection(proj).rename(band_names)
            return ee.Image(mosaic)

        # Auxilliary function to rescale the spectral bands.
        def rescale_spectral_bands(image):
            final_image = image.multiply(product.scaling_factor).add(
                product.offset).copyProperties(image)
            return final_image

        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be a VirtualStation "
                + "object.")
        aoi = virtual_station.aoi
        product = self

        # 'clip' parameter must be boolean.
        if not clip in [False,True,0,1]:
            raise TypeError("'clip' must be boolean (False or True).")
        clip = bool(clip)

        # Check start date.
        if start_date is None:
            start_date = product.start_date
        if type(start_date) is str:
            try:
                start_date = datetime.strptime(start_date,
                    "%Y-%m-%d").date()
            except:
                raise ValueError("'start_date' must have the format "
                    + "yyyy-mm-dd. Ex: '2015-07-22'.")
        if type(start_date) is not date:
            raise TypeError("'start_date' must be of type datetime.date.")

        # Check end date.
        if end_date is None:
            end_date = datetime.today().date()
        if type(end_date) is str:
            try:
                end_date = datetime.strptime(end_date,
                    "%Y-%m-%d").date()
            except:
                raise ValueError("'end_date' must have the format "
                    + "yyyy-mm-dd. Ex: '2025-02-18'.")
        if type(end_date) is not date:
            raise TypeError("'end_date' must be of type datetime.date.")
        # Advance one day of end date because it is not inclusive.
        end_date = end_date + timedelta(days=1)

        # Check date list.
        if date_list is None:
            date_list = []
        if type(date_list) is not list:
            raise TypeError("'date_list' should be a list.")
        for i in range(len(date_list)):
            if isinstance(date_list[i], date):
                date_list[i] = date_list[i].strftime("%Y-%m-%d")
            elif type(date_list[i]) is str:
                try:
                    date_list[i] = datetime.strptime(date_list[i],
                    "%Y-%m-%d").date().strftime("%Y-%m-%d")
                except:
                    raise ValueError("Wrong date format in one or more "
                        + "positions of 'date_list'. The string must have "
                        + "the format yyyy-mm-dd.")
            else:
                raise TypeError("'date_list' must contain dates of type "
                    + "str (format yyyy-mm-dd) or datetime.date.")
        # Update the product attribute.
        self.date_list = date_list

        # The product code.
        product_code = product.product_code

        # Filter by area of interest and by dates/period of interest and
        # insert product and date and time str tags.
        image_collection = ee.ImageCollection(
            product.collection.filterBounds(aoi).filterDate(
            start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
            ).map(set_prop))
        # If time info is missing in the product, use the pre-defined time.
        if product.fixed_time is not None:
            if len(product.fixed_time) > 0:
                try:
                    fixed_time = datetime.strptime(product.fixed_time,
                        "%H:%M").strftime("%H:%M")
                except:
                    raise ValueError("Unrecognized time format in the "
                        + "attribute 'fixed_time' of the product "
                        + str(product_code) + ".")
                #fixed_datetime = (start_date.strftime("%Y-%m-%d") + " "
                #    + fixed_time)
                image_collection = ee.ImageCollection(image_collection.map(
                    lambda image: image.set("img_time", fixed_time,
                    "img_datetime", ee.String(image.get("img_date")).cat(
                    " " + fixed_time))))
        # If a list of dates was provided, apply one more filter.
        if(len(date_list) > 0):
            image_collection = ee.ImageCollection(image_collection.filter(
                ee.Filter.inList("img_date", date_list)))

        # Mosaic neighbor/overlapping images.
        if product.need_to_mosaic:
            img_dates = ee.List(
                image_collection.aggregate_array("img_datetime"))
            distinct_dates = ee.List(img_dates.distinct())
            mosaic_collection = ee.ImageCollection(
                distinct_dates.map(
                lambda d: mosaic_by_date(d, image_collection)))
            image_collection = ee.ImageCollection(ee.Algorithms.If(
                img_dates.length().gt(distinct_dates.length()),
                mosaic_collection, image_collection))

        # Clip the images?
        if clip:
            image_collection = image_collection.map(
                lambda image: ee.Image(image).clip(aoi))

        # Rescale spectral bands.
        if product.scaling_factor and product.offset:
            image_collection = image_collection.map(rescale_spectral_bands)

        # Save the list of available dates in the collection.
        available_dates = image_collection.aggregate_array(
            "img_datetime").getInfo()
        available_dates.sort()
        self.available_dates = available_dates

        # Update start and end dates accordingly to the available dates.
        if len(available_dates) > 0:
            start_date = datetime.strptime(available_dates[0],
                "%Y-%m-%d %H:%M").date()
            end_date = datetime.strptime(available_dates[-1],
                "%Y-%m-%d %H:%M").date()
        self.start_date = start_date
        self.end_date = end_date

        # Save the ee.ImageCollection object and set flag.
        self.collection = image_collection
        self._optimized = True

    # Masks "bad" pixels accordingly to the product attributes
    # 'quality_layer_names', 'quality_layer_inds', 'quality_layer_start_bits'
    # and 'quality_layer_end_bits'
    def mask_bad_pixels(self, add_band=False):
        """
        Masks the bad pixels in each image of the product collection (ex:
        those affected by clouds) using the standard pixel quality layers of
        the images.

        Returns nothing.


        Parameters
        ----------

            add_band: the mask applied should be added as a new band to the
                image? [True|False]

        """
        product = self
        image_collection = product.collection

        start_bits = product.quality_layer_start_bits
        end_bits = product.quality_layer_end_bits
        layer_names = product.quality_layer_names
        layer_inds = product.quality_layer_inds
        test_expression = product.test_expression
        if not all([len(start_bits) == len(end_bits),
                   len(start_bits) == len(layer_names),
                   len(start_bits) == len(layer_inds),
                   len(start_bits) == len(test_expression)]):
            raise ValueError("All the following attributes should have the "
                + "same length, but did not: quality_layer_start_bits; "
                + "quality_layer_end_bits; quality_layer_names; "
                + "quality_layer_inds; test_expression")

        # If the parameters are empty, do nothing and return.
        if(len(start_bits) == 0): return

        mask_vals = []
        for i in range(len(start_bits)):
            bit_to_int = 0
            for j in range(start_bits[i], end_bits[i] + 1):
                bit_to_int = bit_to_int + int(math.pow(2, j))
            mask_vals.append(bit_to_int)

        def masker(image):
          mask = ee.Image(1)
          for i in range(len(mask_vals)):
            mask = mask.And(image.select(
                layer_names[layer_inds[i]]).int().bitwiseAnd(
                mask_vals[i]).rightShift(start_bits[i]).expression(
                test_expression[i]));
          if add_band:
            image = image.addBands(mask.rename("qa_mask"))
          return image.updateMask(mask)

        image_collection = image_collection.map(masker)
        self.collection = image_collection

    def apply_cloud_algo(self, cloud_algo, virtual_station, options=None):
        """
        Applies a cloud algorithm (CloudAlgo object) to this object's image
        collection.

        Returns nothing.

        Parameters
        ----------
        cloud_algo : CloudAlgo instance.
        virtual_station : VirtualStation instance.

        """
        if type(virtual_station).__name__ != "VirtualStation":
            raise TypeError("'virtual_station' must be a VirtualStation "
                + "object.")
        if not self._optimized:
            self.optimize_collection(virtual_station)
        self.collection = cloud_algo.apply(self, virtual_station,
            self.collection, options)
