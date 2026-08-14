# -*- coding: utf-8 -*-
"""
Provides a catalog of 'cloud algorithms' to be available for GEEDaR.

Cloud algorithms are those applied on server side. Each one has an id code.
They are used in GEEDaR as a parameter of Demand objects.*

You may edit this module to include your own algorithms.

* On Demand objects, see the class 'Demand' in the module 'geedar_classes'.

"""

__author__ = "Dhalton Ventura"
__copyright__ = "Copyright 2026 HidroSat Project"
__credits__ = ["Dhalton Ventura"]
__license__ = "MIT"
__version__ = "2.0.2"
__maintainer__ = "Dhalton Ventura"
__email__ = "dhalton.ventura@ana.gov.br"
__status__ = "Beta"


#%% Import

import math
import ee
from geedar_classes import CloudAlgorithm
import vinte_core


#%% Export

__all__ = ["cloud_algo_catalog"]


#%% "Reusable" auxilliary functions

# The functions below are useful generic functions which can be used by one or
# more of the algorithms further below. They always return an image collection.

# Mask "bad" pixels accordingly to the attributes 'quality_layer_names', 
# 'quality_layer_inds', 'quality_layer_start_bits' and 'quality_layer_end_bits'
def _mask_bad_pixels(image_collection, product, add_band=False):
    """
    Take an image collection and mask the bad pixels in each image (ex: those
    pointed as affected by clouds) using the standard quality layers of the 
    satellite products.

    Parameters
    ----------
    
        image_collection: ee.ImageCollection.
        product: an instance of the class Product.
        add_band: the mask applied should be added as a new band to the image?

    Returns
    -------
    
        ee.ImageCollection
    
    """
    
    # Check product.
    if type(product).__name__ != "Product":
        raise TypeError(
            "'product' must be an instance of the class Product")
    
    image_collection = ee.ImageCollection(image_collection)
    
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
        image = ee.Image(image)
        mask = ee.Image(1)
        for i in range(len(mask_vals)):
          mask = mask.And(image.select(
              layer_names[layer_inds[i]]).int().bitwiseAnd(
              mask_vals[i]).rightShift(start_bits[i]).expression(
              test_expression[i]));
        if add_band:
          image = image.addBands(mask.rename("qa_mask"))
        return image.updateMask(mask);

    return ee.ImageCollection(image_collection.map(masker))

# Count the number of unmasked pixels and set it as an image attribute.
def _set_pixel_count(image_collection, aoi, ref_band, attr_name):
    """
    Counts the number of unmasked pixel in each image of a collection and set
    that number as an image attribute. Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection
    aoi: area of interes (ee.Geometry)
    ref_band: name of the band to be used as spatial reference (str)
    attr_name: the name of the attribute to be set in each image (str)
    
    """
    
    image_collection = ee.ImageCollection(image_collection)
    
    def setter(image):
        image = ee.Image(image)
        scale = image.select(ref_band).projection().nominalScale()
        n_pixels = image.select(ref_band).reduceRegion(ee.Reducer.count(), 
            aoi, scale).values().getNumber(0)
        return image.set(attr_name, n_pixels)
    
    return ee.ImageCollection(image_collection.map(setter))

# Updates images' masks acoording to a maximum or minimum value. Takes a dict 
# with the applicable band names and values and a threshold mode (str, "max" 
# or "min").
def _apply_thresholds(image_collection, band_val_dict, mode="max"):
    image_collection = ee.ImageCollection(image_collection)
    def mask_updater(image):
        mask = ee.Image(image).mask()
        for band_name, val in band_val_dict.items():
            if mode == "max":
                band_mask = image.select(band_name).lte(val)
            else:
                band_mask = image.select(band_name).gte(val)
            mask = mask.And(band_mask)
        return ee.Image(image.updateMask(mask))
    return ee.ImageCollection(image_collection.map(mask_updater))

# A simple cloud masking algorithm.
def _simple_cloud_mask(image_collection, aoi, ref_band, bands):
    """
    Use the level and difference of visible bands to mask bright pixels that
    presumably correspond to clouds. Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection
    aoi: area of interest (ee.Geometry)
    ref_band: name of the band to be used as spatial reference (str)
    bands: dictionary of common band names and their corresponding names in
        the images.
    
    """
    
    image_collection = ee.ImageCollection(image_collection)
    
    def masker(image):
        image = ee.Image(image)
        vis = image.select([bands["blue"], bands["green"], bands["red"]])
        max_vis = vis.reduce(ee.Reducer.max())
        min_vis = vis.reduce(ee.Reducer.min())
        max_diff_vis = max_vis.subtract(min_vis)
        cloud_index = max_diff_vis.subtract(min_vis)            
        valid_pixels = cloud_index.gte(-1150)
        image = image.updateMask(valid_pixels)
        return image
    
    image_collection = image_collection.map(masker)
    
    return ee.ImageCollection(image_collection)

# A simple water-pixel selection algorithm.
def _simple_water_detection(image_collection, aoi, ref_band, bands):
    """
    Keep only the potential water pixels, masking the remaining ones.
    Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection
    
    """
    
    image_collection = ee.ImageCollection(image_collection)

    def masker(image):
        image = ee.Image(image)
        swir1 = image.select(bands["wl1500"])
        max_gr = image.select([bands["green"], 
            bands["red"]]).reduce(ee.Reducer.max())
        water_pixels = swir1.lt(1600).And(swir1.lt(max_gr)).selfMask()
        scale = image.select(ref_band).projection().nominalScale()
        n_pixels = water_pixels.reduceRegion(ee.Reducer.count(), aoi, 
            scale).values().getNumber(0)
        return image.updateMask(water_pixels).set("n_water_pixels", n_pixels)
    
    return ee.ImageCollection(image_collection.map(masker))

# Removes apparently shaded pixels.
def _simple_shadow_mask(image_collection, aoi, ref_band, bands):
    """
    Mask apparently shaded pixels using only he visible bands. 
    Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection
    
    """
    
    image_collection = ee.ImageCollection(image_collection)

    def masker(image):
        image = ee.Image(image)
        vis = image.select([bands["blue"], bands["green"], bands["red"]])
        indicator = vis.reduce(ee.Reducer.max())
        indicator_ref = indicator.reduceRegion(reducer = ee.Reducer.median(), 
            geometry = aoi, bestEffort = True).values().getNumber(0)
        proportion_to_ref = indicator.divide(indicator_ref)
        shadow_filter = ee.Image(ee.Algorithms.If(indicator_ref, 
            proportion_to_ref.gte(0.5), indicator.mask()))
        return image.updateMask(shadow_filter)

    return ee.ImageCollection(image_collection.map(masker))

# Applies a generic quality flag based solely on the proportion of selected 
# and valid pixels to the total of pixels.
def _generic_qual_flag(image_collection):
    """
    Adds a 'qual_flag' indicating the quality of the image used for retrieving
    the results. Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection
    
    """
    image_collection = ee.ImageCollection(image_collection)
    
    def set_flag(image):
        image = ee.Image(image)
        nSelecPixels = ee.Number(image.get("n_selected_pixels"))
        nValidPixels = ee.Number(image.get("n_valid_pixels"))
        nTotalPixels = ee.Number(image.get("n_total_pixels"))
        qualFlag = ee.Number(1).add( \
            nValidPixels.divide(nTotalPixels).lt(0.2) \
        ).add( \
            nSelecPixels.divide(nValidPixels).lt(0.1) \
        ).add( \
            nSelecPixels.divide(nValidPixels).lt(0.01) \
        ).min(3).multiply(nSelecPixels.min(1))
        return image.set("qual_flag", qualFlag)       
    
    return ee.ImageCollection(image_collection.map(set_flag))

# Sets a data quality flag to each image. This function depends on standard
# attributes previously defined for the images, namely:
# n_total_pixels, n_valid_pixels, n_water_pixels, n_selected_pixels
def _water_product_qual_flag(image_collection):
    """
    Adds a 'qual_flag' indicating the quality of the image used for retrieving
    water-related results. Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection
    
    """    
    image_collection = ee.ImageCollection(image_collection)

    def set_flag(image):
        n_selec_pixels = ee.Number(image.get("n_selected_pixels"))
        n_water_pixels = ee.Number(image.get("n_water_pixels"))
        n_valid_pixels = ee.Number(image.get("n_valid_pixels"))
        n_total_pixels = ee.Number(image.get("n_total_pixels"))
        qual_flag = ee.Number(1).add(n_valid_pixels.divide(
            n_total_pixels).lt(0.2)).add(n_selec_pixels.divide(
            n_water_pixels).lt(0.2)).add(n_selec_pixels.divide(
            n_water_pixels).lt(0.01)).min(3).multiply(n_selec_pixels.min(1))
        return image.set("qual_flag", qual_flag)

    return ee.ImageCollection(image_collection.map(set_flag))

# Sets a data quality flag to each Modis image. This function depends on 
# attributes previously defined for the images, namely:
# n_total_pixels, n_valid_pixels, n_water_pixels, n_selected_pixels.
def _mod3r_qual_flag(image_collection, aoi, product):
    """
    Adds a 'qual_flag' attribute to each Modis image indicating its quality. 
    Returns an ee.ImageCollection.
    
    image_collection: ee.ImageCollection (Modis collection).
    
    """
    
    image_collection = ee.ImageCollection(image_collection)
    bands = product.get_data_bands()
    ref_band = product.scale_ref_band
    product_code = product.product_code
    daily_collections = range(101,110)
    composite_collections = range(111,120)
    if product_code in daily_collections:
        daily = True
    elif product_code in composite_collections:
        daily = False
    else:
        raise ValueError("This function '_mod3r_qual_flag' can only be "
            + "applied to products of code interval 100-119.")

    def set_flag(image):
        tmpImage = image
        tmpImage.set("qual_flag", 0)
        nSelecPixels = ee.Number(image.get("n_selected_pixels"))
        nValidPixels = ee.Number(image.get("n_valid_pixels"))
        nTotalPixels = ee.Number(image.get("n_total_pixels"))
        scale = image.select(ref_band).projection().nominalScale()
        meanVals = image.select([bands["red"], bands["NIR"]]).reduceRegion(
            ee.Reducer.mean(), aoi).values()
        redMean = meanVals.getNumber(0)
        nirMean = meanVals.getNumber(1)
        convrad = ee.Number(math.pi / 180)
        if daily:
            vzen = image.select("SensorZenith").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber("SensorZenith").divide(100).multiply(
                convrad)
            szen = image.select("SolarZenith").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber("SolarZenith").divide(100).multiply(
                convrad)
            solaz = image.select("SolarAzimuth").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber("SolarAzimuth").divide(100).multiply(
                convrad)
            senaz = image.select("SensorAzimuth").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber("SensorAzimuth").divide(100).multiply(
                convrad)
            delta = solaz.subtract(senaz)
            delta = ee.Number(ee.Algorithms.If(
                delta.gte(360), delta.subtract(360), delta))
            delta = ee.Number(ee.Algorithms.If(
                delta.lt(0), delta.add(360), delta))
            raz = delta.subtract(180).abs()
        else:
            vzen = image.select("ViewZenith").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber("ViewZenith").divide(100).multiply(
                convrad)
            szen = image.select("SolarZenith").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber("SolarZenith").divide(100).multiply(
                convrad)
            raz = image.select("RelativeAzimuth").reduceRegion(
                reducer = ee.Reducer.mean(), geometry = aoi, 
                scale = scale).getNumber(
                "RelativeAzimuth").divide(100).multiply(convrad)
        sunglint = vzen.cos().multiply(szen.cos()).subtract(
            vzen.sin().multiply(szen.sin()).multiply(raz.cos())).acos().divide(
            convrad)
        sunglint = sunglint.min(ee.Number(180).subtract(sunglint))
        qual = ee.Number(1).add(nValidPixels.divide(
            nTotalPixels).lt(0.05).Or(nSelecPixels.divide(
            nValidPixels).lt(0.1)).Or(nSelecPixels.lt(10))).add(vzen.divide(
            convrad).gte(45).Or(sunglint.lte(25))).add(
            nirMean.gte(1000).Or(nirMean.subtract(redMean).gte(300)).add(
            nirMean.gte(2000).multiply(2)))
        image = image.set("vzen", vzen.divide(convrad), 
            "sunglint", sunglint, "qual_flag", qual.min(3))
        
        return ee.Image(ee.Algorithms.If(nSelecPixels.gt(0), image, tmpImage))
    
    return ee.ImageCollection(image_collection.map(set_flag))

# Turn Modis composite images into single day ones.
def _split_modis_composites(image_collection, aoi, ref_band, 
        day_of_year_band = "DayOfYear"):   
    
    image_collection = ee.ImageCollection(image_collection)
    
    def splitter(image, append_list):
        image = ee.Image(image)
        img_time = ee.String(image.get("img_time"))
        year = image.date().get("year")
        append_list = ee.List(append_list)
        scale = image.select(ref_band).projection().nominalScale()
        days_of_year = image.select(day_of_year_band).reduceRegion(
            ee.Reducer.toList(), aoi, scale).values().flatten().distinct()
        def mask_updater(day, img_list):
            day = ee.Number(day)
            img_date = ee.Date.fromYMD(year, 1, 1).advance(day.add(-1), "day")
            return ee.List(img_list).add(
                image.updateMask(image.select(day_of_year_band).eq(day)).set(
                "img_date", img_date.format("YYYY-MM-dd"), 
                "img_time", "6:00",# img_time, 
                "img_datetime", img_date.format("YYYY-MM-dd").cat(" ").cat(
                img_time)))
        local_img_list = ee.List(
            days_of_year.iterate(mask_updater, ee.List([])))
        return append_list.cat(local_img_list)
    
    image_collection_list = ee.List(
        image_collection.iterate(splitter, ee.List([])))
    
    return ee.ImageCollection(image_collection_list)


#%% Processing algorithms to be used by GEEDaR

# The functions below are, each one, the core of an algorithm. They must be 
# inserted in the key 'main_function' of the instantiation dictionary of a 
# CloudAlgorithm object. They must take a Product object, a VirtualStation 
# object, an ee.ImageCollection object and a dictionary of options. And they 
# must return an ee.ImageCollection.

# Makes no change to the images.
def do_nothing(product, virtual_station, image_collection, options):
    return ee.ImageCollection(image_collection)

# Applies the function _mask_bad_pixels, which uses attributes of the Product 
# object as a base for removing problematic pixels.
def std_cloud_mask(product, virtual_station, image_collection, options):
    """
    By using the product's quality layer(s), remove pixels marked as cloud or 
    shadow or deffective.
    
    """
    image_collection = ee.ImageCollection(image_collection)
    aoi = virtual_station.aoi
    ref_band = product.scale_ref_band
    # Set the total number of pixels.
    image_collection = _set_pixel_count(image_collection, aoi, ref_band,
        "n_total_pixels")
    # Mask bad pixels.
    image_collection = _mask_bad_pixels(image_collection, product)
    # Set the number of valid pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band, 
        "n_valid_pixels")
    return image_collection

# Emulates, to the possible extent, the MOD3Ralgorithm.
def mod3r(product, virtual_station, image_collection, options):
    """
    MOD3R clusterer/classifier.
    
    Run k-means with up to 20 clusters and choose the cluster which most likely 
    represents water. For such choice, first define the cluster which probably 
    represents soil or vegetation: it is the one with the largest difference 
    between red and NIR. Then test every other cluster as a possible water 
    endmember, choosing the one which yields the smaller error.
    
    """
    image_collection = ee.ImageCollection(image_collection)
    aoi = virtual_station.aoi
    bands = product.get_data_bands()
    ref_band = product.scale_ref_band
    cluster_bands = [bands["red"], bands["NIR"]]
    max_n_clusters = 20 # default
    if isinstance(options, dict):
        if "max_n_clusters" in options:
            max_n_clusters = options["max_n_clusters"]

    def selector(image):
        base_image = ee.Image(image).select(cluster_bands)
        
        # Make the training dataset for the clusterer.
        training_data = base_image.sample(aoi)
        clusterer = ee.Clusterer.wekaCascadeKMeans(2, max_n_clusters).train(
            training_data)
        cluster_image = base_image.cluster(clusterer)
    
        # Update the clusters (classes).
        max_id = ee.Image(
            cluster_image).reduceRegion(ee.Reducer.max(), aoi).values().get(0)
        cluster_ids = ee.List.sequence(0, ee.Number(max_id))
        
        # Get the mean band values for each cluster.
        cluster_band_vals = cluster_ids.map(
            lambda id: base_image.updateMask(cluster_image.eq(ee.Image(
            ee.Number(id)))).reduceRegion(ee.Reducer.mean(), aoi))
    
        # Get a red-NIR difference list.
        red_nir_diff_list = cluster_band_vals.map(
            lambda vals: ee.Number(
                ee.Dictionary(vals).get(bands["NIR"])).subtract(ee.Number(
                ee.Dictionary(vals).get(bands["red"]))))
    
        # Pick the class with the greatest difference to be the land endmember.
        greatest_diff = red_nir_diff_list.sort().reverse().get(0)
        land_cluster_id = red_nir_diff_list.indexOf(greatest_diff)
        # The other clusters are candidates for water endmembers.
        water_candidate_ids = cluster_ids.splice(land_cluster_id, 1)
    
        # Apply, for every water candidate cluster, an unmix procedure with 
        # non-negative-values constraints.
        # Then choose as water representative the one which yielded the smaller 
        # prediction error.
        land_endmember = ee.Dictionary(
            cluster_band_vals.get(land_cluster_id)).values(cluster_bands)
        land_endmember_red = ee.Number(land_endmember.get(0))
        land_endmember_nir = ee.Number(land_endmember.get(1))
        land_image = ee.Image(
            land_endmember_red).addBands(ee.Image(land_endmember_nir)).rename(
            cluster_bands)
        min_error = ee.Dictionary().set("id", ee.Number(
            water_candidate_ids.get(0))).set("val", ee.Number(2147483647))
        
        # Function for getting the best water candidate.
        def pick_water_cluster(id, error_dict):
            candidate_water_endmember = ee.Dictionary(
                cluster_band_vals.get(ee.Number(id))).values(cluster_bands)
            candidate_water_endmember_red = ee.Number(
                candidate_water_endmember.get(0))
            candidate_water_endmember_nir = ee.Number(
                candidate_water_endmember.get(1))
            candidate_water_image = ee.Image(
                candidate_water_endmember_red).addBands(ee.Image(
                candidate_water_endmember_nir)).rename(cluster_bands)
            other_candidates_ids = water_candidate_ids.splice(ee.Number(id), 1)
            
            def test_cluster(other_id, accum):
                masked_image = base_image.updateMask(
                    cluster_image.eq(ee.Number(other_id)))
                fractions = masked_image.unmix(
                    [land_endmember, candidate_water_endmember], True, True)
                predicted = land_image.multiply(
                    fractions.select("band_0")).add(
                    candidate_water_image.multiply(fractions.select("band_1")))
                return ee.Number(
                    masked_image.subtract(predicted).pow(2).reduce(
                    ee.Reducer.sum()).reduceRegion(ee.Reducer.mean(), 
                    aoi).values().get(0)).add(ee.Number(accum))
            
            error_sum = other_candidates_ids.iterate(test_cluster, 0)
            error_dict = ee.Dictionary(error_dict)
            prev_error = ee.Number(error_dict.get("val"))
            prev_id = ee.Number(error_dict.get("id"))
            new_error = ee.Algorithms.If(
                ee.Number(error_sum).lt(prev_error), error_sum, prev_error)
            new_id = ee.Algorithms.If(
                ee.Number(error_sum).lt(prev_error), ee.Number(id), prev_id)
            return error_dict.set("id", new_id).set("val", new_error)
        
        water_cluster_id = ee.Number(ee.Dictionary(water_candidate_ids.iterate(
            pick_water_cluster, min_error)).get("id"))
        
        # Return the image with non-water clusters masked, with the clustering 
        # result as a band and with the water cluster ID as a property.
        return image.updateMask(cluster_image.eq(ee.Image(water_cluster_id)))

    # Set the total number of pixels and then remove pixels with suspect or 
    # negative values.
    image_collection = _set_pixel_count(image_collection, aoi, ref_band,
        "n_total_pixels").map(lambda image: ee.Image(image).updateMask(
        ee.Image(image).select(bands["red"]).gte(0).And(
        ee.Image(image).select(bands["red"]).lt(3000)).And(
        ee.Image(image).select(bands["NIR"]).gte(0))))
    # Mask bad pixels.
    image_collection = _mask_bad_pixels(image_collection, product)
    # Set the number of valid pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band, 
        "n_valid_pixels")
    # Filter out images with too few valid pixels.
    image_collection_out = ee.ImageCollection(image_collection.filterMetadata(
        "n_valid_pixels", "less_than", 10).map(
        lambda image: ee.Image(image).set("n_selected_pixels", 0, 
        "qual_flag", 0).updateMask(ee.Image(0))))
    image_collection_in = ee.ImageCollection(image_collection.filterMetadata(
        "n_valid_pixels", "greater_than", 9))
    # Apply the MOD3R selector.
    image_collection_in = image_collection_in.map(selector)
    # Set the number of selected pixels.
    image_collection_in = _set_pixel_count(image_collection_in, aoi, ref_band, 
        "n_selected_pixels")
    # Quality flag:
    image_collection_in = _mod3r_qual_flag(image_collection_in, aoi, product)   
    # Reinsert the unprocessed images.
    image_collection = ee.ImageCollection(image_collection_in.merge(
        image_collection_out)).copyProperties(image_collection)
    
    if product.product_name in ["MOD09A1", "MYD09A1", "MOD09Q1", "MYD09Q1", 
            "MOD09A1Q1", "MYD09A1Q1", "MODMYD09A1Q1"]:
        image_collection = _split_modis_composites(image_collection, aoi, 
            ref_band)
    
    return ee.ImageCollection(image_collection)

# Flexible clustering selection of water pixels.
def wcs(product, virtual_station, image_collection, options):
    """
    Water Cluster Selection (WCS) algorithm
    
    Applies k-means clustering and selects the cluster that better represents 
    water pixels. The algorithm behavior and the pixel selection criteria 
    depend on the options passed with the 'options' dictionary:
        selector_id = the identification of the selection method (ex: 
            "min_ndvi", "min_ir" or "max_wi").
        max_n_clusters = maximum number of clusters (20 is the default).
        min_band_vals = minimum reflectance values (pixels with lower values 
            will be masked) (ex: {bands["red"]: 0, bands["NIR"]: 0}).
        max_band_vals = same as before, but for maximum reflectance.
        cluster_bands = the bands to be included in the clustering (ex: 
            [bands["red"], bands["NIR"]]).
    
    Selectors
    ---------
    
    Minimum NDVI (minNDVI)
        Option: selector_id = "min_ndvi" (this is optional since this is the 
            default method).
        Description: Picks the cluster with the lowest NDVI mean value. 

    Minimum IR (minIR)
        Option: selector_id = "min_ir"
        Description: Picks the cluster with the lowest reflectance in the near 
            infraed. 
    
    Maximum Water Index (maxWI).
        Option: selector_id = "max_wi"
        Description: Calculates a custom water index: normalized difference 
        between reflectance in the green band and the maximum reflectance in 
        the SWIR bands (using the max SWIR is a conservative approach and, 
        in Modis images, prevents the usage of deffective zero-valued pixels). 
        Then picks the cluster with the highest index.
    
    Max. Normalized Water Index for Highly Variable Turbidity (NDWIHVT)
        Option: selector_id = "ndwihvt"
        Description: Calculates a custom water index: normalized difference 
        between the maximim reflectance in the green and red bands and the 
        minimum reflectance in the SWIR bands. Then picks the cluster with the 
        highest index.

    """
    image_collection = ee.ImageCollection(image_collection)
    aoi = virtual_station.aoi
    bands = product.get_data_bands()
    ref_band = product.scale_ref_band
    valid_selector_ids = ["min_ndvi", "min_ir", "max_wi", "ndwihvt"]
    
    # Default options:
    selector_id = "min_ndvi"
    max_n_clusters = 20 # default
    min_band_vals = {bands["red"]: 0, bands["NIR"]: 0} 
    max_band_vals = {bands["red"]: 3000} 
    cluster_bands = [bands["red"], bands["NIR"]]
    # Custom options:
    if isinstance(options, dict):
        if "selector_id" in options:
            selector_id = options["selector_id"]
            if selector_id not in valid_selector_ids:
                raise ValueError("Invalid 'selector_id': " + str(selector_id))
        if "max_n_clusters" in options:
            max_n_clusters = options["max_n_clusters"]
        if "min_band_vals" in options:
            min_band_vals = options["min_band_vals"]
        if "max_band_vals" in options:
            min_band_vals = options["min_band_vals"]
        if "cluster_bands" in options:
            cluster_bands = options["cluster_bands"]

    # The function to be mapped.
    def selector(image):
        # The image with bands to be clustered.
        base_image = image.select(cluster_bands)
        
        # Default: normalized difference of the clustering bands.
        # It works for the minNDVI algorithm.
        ref_image = base_image.normalizedDifference()
        # Custom reference image.
        if selector_id == "min_ir":
            ref_image = image.select(bands["NIR"]).multiply(-1)
        elif selector_id == "max_wi":
            max_swir = image.select(
                [bands["wl1500"], bands["wl2000"]]).reduce(ee.Reducer.max())
            ref_image = image.select(
                bands["green"]).addBands(max_swir).normalizedDifference()
        elif selector_id == "ndwihvt":
            max_gr = image.select([bands["green"], bands["red"]]).reduce(
                ee.Reducer.max())
            min_swir = image.select([bands["wl1500"], bands["wl2000"]]).reduce(
                ee.Reducer.min())
            #base_image = max_gr.addBands(min_swir)
            ref_image = max_gr.addBands(min_swir).normalizedDifference()
        
        # Make the training dataset for the clusterer.
        training_data = base_image.sample(aoi)
        clusterer = ee.Clusterer.wekaCascadeKMeans(2, max_n_clusters).train(
            training_data)
        cluster_image = base_image.cluster(clusterer)
    
        # Update the clusters (classes).
        max_id = cluster_image.reduceRegion(
            ee.Reducer.max(), aoi).values().getNumber(0)
        cluster_ids = ee.List.sequence(0, max_id)
                   
        # Default: pick the cluster with the highest value.        
        val_list = cluster_ids.map(
            lambda id: ref_image.updateMask(
            cluster_image.eq(ee.Number(id))).reduceRegion(
            ee.Reducer.mean(), aoi).values().getNumber(0))
        max_val = val_list.sort().getNumber(max_id)
        water_cluster_id = val_list.indexOf(max_val)

        return image.updateMask(cluster_image.eq(water_cluster_id))
        
    # Set the number of total pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band, 
        "n_total_pixels")

    # Apply thresholds to exclude likely problematic pixels.
    image_collection = _apply_thresholds(image_collection, max_band_vals, 
        mode="max")
    image_collection = _apply_thresholds(image_collection, min_band_vals, 
        mode="min")
    # Mask bad pixels.
    image_collection = _mask_bad_pixels(image_collection, product)
    # Set the number of valid pixels
    image_collection = ee.ImageCollection(_set_pixel_count(image_collection, 
        aoi, ref_band, "n_valid_pixels"))
    
    # Filter out images with too few valid pixels.
    image_collection_out = ee.ImageCollection(image_collection.filterMetadata(
        "n_valid_pixels", "less_than", 10).map(
        lambda image: ee.Image(image).set("n_selected_pixels", 0, 
        "qual_flag", 0).updateMask(ee.Image(0))))
    image_collection_in = ee.ImageCollection(image_collection.filterMetadata(
        "n_valid_pixels", "greater_than", 9))
    
    # Apply the pixel selector.
    image_collection_in = image_collection_in.map(selector)
    
    # Set the number of selected pixels.
    image_collection_in = _set_pixel_count(image_collection_in, aoi, ref_band, 
        "n_selected_pixels")
    
    if product.product_code in range(111, 120):
        # Generate an image for each date composing the Modis composite.
        image_collection_in = _split_modis_composites(image_collection_in, 
            aoi, ref_band)
        
    if product.product_code in range(101, 120):
        # Quality flag:
        image_collection_in = _mod3r_qual_flag(image_collection_in, aoi, 
            product)
    else:
        # Quality flag:
        image_collection_in = _generic_qual_flag(image_collection_in)
    
    # Reinsert the unprocessed images.
    image_collection = image_collection_in.merge(
        image_collection_out).copyProperties(image_collection)  
        
    return ee.ImageCollection(image_collection)

# Calculates the daily mean of the hourly GPM precipitation.
def gpm_daily_mean(product, virtual_station, image_collection, options):
    image_collection = ee.ImageCollection(image_collection)
    aoi = virtual_station.aoi
    ref_band = product.scale_ref_band
    area = aoi.area()

    date_list = ee.List(
        image_collection.aggregate_array("img_date")).distinct().sort()

    def reduce_date(date_str):
        date_str = ee.String(date_str)
        daily_collection = image_collection.filter(
            ee.Filter.eq("img_date", date_str))
        first_image = ee.Image(daily_collection.first())
        daily_image = ee.Image(
            daily_collection.select([ref_band]).mean()
        ).rename([ref_band]).setDefaultProjection(
            first_image.select(ref_band).projection()
        ).copyProperties(first_image)
        return daily_image.set(
            "img_date", date_str,
            "img_time", "12:00",
            "img_datetime", date_str.cat(" 12:00"))

    image_collection = ee.ImageCollection.fromImages(
        date_list.map(reduce_date))
    image_collection = _set_pixel_count(image_collection, aoi, ref_band,
        "n_selected_pixels")
    return ee.ImageCollection(image_collection.map(
        lambda image: ee.Image(image).set("area", ee.Number(area))))

# A simplified algorithm for selection of good water pixels.
def simple_water_selection(product, virtual_station, image_collection, 
        options):
    """
    Selects water pixels free from glint and atmospheric interference based 
    on a SWIR threshold. Excludes pixels with negative reflectance in visible 
    or near infrared. For algal-bloom tolerance, set 'bloom_tolerant' as 
    True in 'options'. It is based on a custom bloom index.
    To define a custom threshold for the first SWIR band, set the value of 
    'max_swir1_val' in options. Default is 100.

    """                
    image_collection = ee.ImageCollection(image_collection)
    aoi = virtual_station.aoi
    bands = product.get_data_bands()
    ref_band = product.scale_ref_band
    if "bloom_tolerant" not in options:
        options["bloom_tolerant"] = False
    bloom_tolerant = options["bloom_tolerant"]
    if "max_swir1_val" not in options:
        options["max_swir1_val"] = 100
    max_swir1_val = options["max_swir1_val"]
    if "min_vnir_val" not in options:
        options["min_vnir_val"] = 0
    min_vnir_val = options["min_vnir_val"]
    if "max_vis_val" not in options:
        options["max_vis_val"] = 3000
    max_vis_val = options["max_vis_val"]

    def pixel_selector(image):
        blue = image.select(bands["blue"])
        green = image.select(bands["green"])
        red = image.select(bands["red"])
        nir = image.select(bands["NIR"])
        swir1 = image.select(bands["wl1500"])
        swir2 = image.select(bands["wl2000"])
        min_vnir = image.select([bands["blue"], bands["green"], bands["red"], 
            bands["NIR"]]).reduce(ee.Reducer.min())
        vis = image.select([bands["blue"], bands["green"], bands["red"]])
        max_vis = vis.reduce(ee.Reducer.max())
        sum_vis = vis.reduce(ee.Reducer.sum())
        bloom_index = nir.multiply(green.subtract(blue.max(red)).divide(
            sum_vis).max(0))        
        
        if bloom_tolerant:
            swir1_thr = bloom_index.pow(0.5826).multiply(8.679).add(80).max(
                max_swir1_val)
        else:
            swir1_thr = max_swir1_val
        
        selected_water_pixels = min_vnir.gte(min_vnir_val).And(
            max_vis.lt(max_vis_val)).And(swir1.lt(swir1_thr).Or(swir2.lt(75)))

        if bloom_tolerant:
            algal_bloom_pixels = selected_water_pixels.And(
                bloom_index.gte(300))
            scale = image.select(ref_band).projection().nominalScale()
            n_bloom_pixels = algal_bloom_pixels.selfMask().reduceRegion(
                ee.Reducer.count(), aoi, scale).values().getNumber(0)
            image = image.set("n_bloom_pixels", 
                n_bloom_pixels)
        
        return image.updateMask(selected_water_pixels)
    
    # Set the total number of pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band,
        "n_total_pixels")
    # Mask bad pixels.
    image_collection = _mask_bad_pixels(image_collection, product)
    # Additional (simple) cloud masking.
    image_collection = _simple_cloud_mask(image_collection, aoi, ref_band, 
        bands)
    # Set the number of valid pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band, 
        "n_valid_pixels")
    # Keep only potential water pixels.
    image_collection = _simple_water_detection(image_collection, aoi, ref_band, 
        bands)
    # Set the number of potential water pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band, 
        "n_water_pixels")
    # Remove potential shadow pixels.
    image_collection = _simple_shadow_mask(image_collection, aoi, ref_band, 
        bands)
    # Keep only the "good" water pixels.
    image_collection = image_collection.map(pixel_selector)
    # Set the number of selected (good) water pixels
    image_collection = _set_pixel_count(image_collection, aoi, ref_band, 
        "n_selected_pixels")
    # Apply a data quality flag.
    image_collection = _water_product_qual_flag(image_collection)
    
    return ee.ImageCollection(image_collection)
    

#%% Build a catalog of algorithms

_algo_list = [
    {
    "algo_code": 0,
    "name": "none",
    "description": "This algorithm makes no change to the image data.",
    "ref": "",
    "required_bands": [], 
    "main_function": do_nothing,
    "aux_functions": [],
    "export_vars": [],
    "export_bands": [],
    "options": None
    },
    {
    "algo_code": 1,
    "name": "StdCloudMask",
    "description": "This algorithm removes pixels with cloud, cloud "
        + "shadow or high aerosol, based on the product's pixel quality "
        + "layer.",
    "ref": "",
    "required_bands": [], 
    "main_function": std_cloud_mask,
    "aux_functions": [_set_pixel_count, _mask_bad_pixels],
    "export_vars": ["n_valid_pixels", "n_total_pixels"],
    "export_bands": [],
    "options": None
    },
    {
    "algo_code": 2,
    "name": "MOD3R emulator",
    "description": "This algorithm replicates, to the possible extent, "
        + "the MOD3R algorithm, developed by the researcher Jean-Michel "
        + "Martinez (IRD, France).",
    "ref": "Ventura, D.L.T. (2019, unpublished)",
    "required_bands": ["red", "NIR", ["SensorZenith","ViewZenith"], 
        "SolarZenith", ["SensorAzimuth","RelativeAzimuth"]],
    "main_function": mod3r,
    "aux_functions": [_split_modis_composites, _mod3r_qual_flag, 
        _set_pixel_count, _mask_bad_pixels],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "vzen", "sunglint", "qual_flag"],
    "export_bands": [],
    "options": None
    },
    {
    "algo_code": 3,
    "name": "minNDVI",
    "description": "Applies k-means clustering to bands red and NIR and "
        + "defines as the water-representative cluster the one with the "
        + "lowest NDVI.",
    "ref": "Ventura, D.L.T. (2019, unpublished)",
    "required_bands": ["red", "NIR"],
    "main_function": wcs,
    "aux_functions": [_set_pixel_count, _apply_thresholds, 
        _mask_bad_pixels, _split_modis_composites, _mod3r_qual_flag, 
        _generic_qual_flag],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "vzen", "sunglint", "qual_flag"],
    "export_bands": [],
    "options": {"max_n_clusters": 20, "selector_id": "min_ndvi"}
    },
    {
    "algo_code": 4,
    "name": "minIR",
    "description": "Applies k-means clustering to bands red and NIR and "
        + "defines as the water-representative cluster the one with the "
        + "lowest reflectance in the near-infrared.",
    "ref": "Ventura, D.L.T. (2019, unpublished)",
    "required_bands": ["red", "NIR"],
    "main_function": wcs,
    "aux_functions": [_set_pixel_count, _apply_thresholds, 
        _mask_bad_pixels, _split_modis_composites, _mod3r_qual_flag, 
        _generic_qual_flag],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "vzen", "sunglint", "qual_flag"],
    "export_bands": [],
    "options": {"max_n_clusters": 20, "selector_id": "min_ir"}
    },
    {
    "algo_code": 5,
    "name": "maxWI",
    "description": "Applies k-means clustering to bands red and NIR and "
        + "defines as the water-representative cluster the one with the "
        + "highest value of a custom water index.",
    "ref": "Ventura, D.L.T. (2026, unpublished)",
    "required_bands": ["green", "red", "NIR", "wl1500", "wl2000"],
    "main_function": wcs,
    "aux_functions": [_set_pixel_count, _apply_thresholds, 
        _mask_bad_pixels, _split_modis_composites, _mod3r_qual_flag, 
        _generic_qual_flag],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "vzen", "sunglint", "qual_flag"],
    "export_bands": [],
    "options": {"max_n_clusters": 20, "selector_id": "max_wi"}
    },
    {
    "algo_code": 6,
    "name": "maxNDWIHVT",
    "description": "Applies k-means clustering and selects as water-"
        + "representative the cluster with the highest NDWIHVT, a custom "
        + "water index.",
    "ref": "Ventura, D.L.T. (2026, unpublished)",
    "required_bands": ["green", "red", "NIR", "wl1500", "wl2000"],
    "main_function": wcs,
    "aux_functions": [_set_pixel_count, _apply_thresholds, 
        _mask_bad_pixels, _split_modis_composites, _mod3r_qual_flag, 
        _generic_qual_flag],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "vzen", "sunglint", "qual_flag"],
    "export_bands": [],
    "options": {"max_n_clusters": 20, "selector_id": "ndwihvt"}
    },
    {
    "algo_code": 14,
    "name": "GPM_daily_mean",
    "description": "Average of the calibrated hourly precipitation in the "
        + "area of interest.",
    "ref": "Ventura, D.L.T. (2021, unpublished)",
    "required_bands": ["precipitation"],
    "main_function": gpm_daily_mean,
    "aux_functions": [],
    "export_vars": ["n_selected_pixels", "area"],
    "export_bands": [],
    "options": {}
    },
    {
    "algo_code": 15,
    "name": "Bloom-Tolerant Water Selection",
    "description": "Selects 'good' water pixels, including those affected "
        + "by dense algal blooms, and excluding pixels affected by glint "
        + "and strong spectral mixture or adjacency effects.",
    "ref": "Ventura, D.L.T.V. (unpublished)",
    "required_bands": ["blue","green","red","NIR","wl1500","wl2000"],
    "main_function": simple_water_selection,
    "aux_functions": [_set_pixel_count, _mask_bad_pixels, 
        _simple_cloud_mask, _simple_water_detection, _simple_shadow_mask, 
        _water_product_qual_flag],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "n_bloom_pixels", "n_water_pixels", "qual_flag"],
    "export_bands": [],
    "options": {"bloom_tolerant": True, "max_swir1_val": 100, 
        "min_vnir_val": 0, "max_vis_val": 3000}
    },
    {
    "algo_code": 16,
    "name": "Simple Water Selection",
    "description": "Selects 'good' water pixels, excluding pixels "
        + "affected by glint and strong spectral mixture or adjacency " 
        + "effects.",
    "ref": "Ventura, D.L.T.V. (unpublished)",
    "required_bands": ["blue","green","red","NIR","wl1500","wl2000"],
    "main_function": simple_water_selection,
    "aux_functions": [_set_pixel_count, _mask_bad_pixels, 
        _simple_cloud_mask, _simple_water_detection, _simple_shadow_mask, 
        _water_product_qual_flag],
    "export_vars": ["n_selected_pixels", "n_valid_pixels", 
        "n_total_pixels", "n_bloom_pixels", "n_water_pixels", "qual_flag"],
    "export_bands": [],
    "options": {"bloom_tolerant": False, "max_swir1_val": 100, 
        "min_vnir_val": 0, "max_vis_val": 3000}
    }
]

cloud_algo_catalog = {a["algo_code"]: CloudAlgorithm(a) 
    for a in _algo_list}
