#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local algorithm abstraction used by GEEDaR."""

import copy

import pandas

from .utils import restore_df_lists, unfold_df_lists, _validate_args_dict


class LocalAlgorithm:
    """
    Encapsulates a function to be applied to a Pandas data frame. In GEEDaR,
    it serves the purpose of applying inversion algorithms to the reflectance
    time series extracted from the server after application of the cloud
    algorithm.

    Instantiation
    -------------

    For instantiation, it must be passed a dictionary containing:
        "algo_code": unique identifier (int).
        "name": name of the algorithm (str).
        "description": the most important info on the algorithm (str).
        "ref": reference to the literature or URL (str).
        "required_bands": names of the bands used by the algorithm (list of
            str). In the input dataframe such bands appear with a 'stat
            suffix' (ex: 'red_median') which must be one of the 'applicable
            suffixes' listed in the next parameter.
        "applicable_suffixes": suitable suffixes (list of str). The suffix
            names must be in the 'stat_suffix' property of the previously
            applied Rreducer object. These suffixes are added by GEE to
            the image band names when an ee.Reducer is applied.
        "function": function object containing the algorithm.
        "options": a dictionary of options for the algorithm (dict or None,
            optional).


    An example:
    {
        "algo_code": 3,
        "name": "SSS Madeira",
        "description": "Estimates the surface suspended solids concentration
            in the Madeira River.",
        "ref": "Villar, R.E.; Martinez, J.M.; Le Texier, M.; Guyot, J.L.;
            Fraizy, P.; Meneses, P.R.; Oliveira, E. A study of sediment
            transport in the Madeira River, Brazil, using MODIS remote-sensing
            images. Journal of South American Earth Sciences, v. 44, p. 45-54,
            2013.",
        "required_bands": ["red", "NIR"],
        "applicable_suffixes": ["median","mean"],
        "function": madeira_2013, # Name of the function
        "options": None
    }

    Attributes
    ----------

    These attributes come from the arguments for instantiation:

        algo_code
        name
        description
        ref
        required_bands
        applicable_suffixes
        function

    Methods
    -------

        apply: applies the algorithm to the input dataframe.

    """

    # Required constructor arguments and their accepted types.
    _required_args = {
        "algo_code":  {"types": ["int"], "values": []},
        "name": {"types": ["str"], "values": []},
        "description": {"types": ["str"], "values": []},
        "ref": {"types": ["str"], "values": []},
        "required_bands": {"types": ["list", ["str", "empty"]], "values": []},
        "applicable_suffixes": {"types": ["list", ["str", "empty"]],
            "values": []},
        "function": {"types": ["function"], "values": []},
        "options": {"types": ["dict", "NoneType"], "values": []}
    }

    # Help on instantiation is in the class docstring.
    def __init__(self, args_dict):

        # Validate the dictionary of arguments.
        _validate_args_dict(args_dict, self._required_args)

        # Set the instance attributes from the input dictionary.
        for key, value in args_dict.items():
            # Only set an attribute if it is a required one.
            if key in self._required_args:
                setattr(self, key, value)

    # Applies the algorithm.
    def apply(self, df, options=None):
        """
        Applies the algorithm to the input dataframe ('df'). The resulting
        variables will be returned as columns added to the input dataframe.

        Parameters
        ----------

            df: a Pandas dataframe with columns corresponding to this object's
                 attribute 'required_bands' or to a combination of
                 'required_bands' and 'applicable_suffixes' (with a "_" as
                separator). Othercolumns in the dataframe will be ignored.
            options: dictionary with variables to be used by the algorithm
                (dict, optional).

        Returns
        -------

            A Pandas dataframe with added columns corresponding to the
            variables resulting from the algorithm application.

        """

        # Check the parameters.

        if not isinstance(df, pandas.DataFrame):
            raise TypeError("'df' must be a Pandas dataframe.")

        if options is None:
            options = dict()
        if type(options) is not dict:
            raise TypeError("'options' must be a dictionary")
        if self.options is not None:
            options = self.options | options # Add predefined options

        if "stat_suffixes" in df.attrs:
            reducer_suffixes = df.attrs["stat_suffixes"]
        else:
            reducer_suffixes = []

        df = df.copy()
        df_cols = [*df.columns]
        required_bands = self.required_bands
        applicable_suffixes = copy.deepcopy(self.applicable_suffixes)

        # "Explode" lists in df?
        explode = False
        if "list" in reducer_suffixes and "list" not in applicable_suffixes:
            explode = True
            applicable_suffixes.append("list")

        # Check columns compatibility and remove the stat. suffix (if any).
        comb_names = dict()
        applied_stat = None
        for b in required_bands:
            for s in applicable_suffixes:
                comb_names[b + "_" + s] = b
        for col in df_cols:
            if col in required_bands:
                continue
            if col in comb_names:
                df.rename(columns={col:comb_names[col]}, inplace = True)
                if not applied_stat:
                    applied_stat = col.split("_")[-1]
                continue
            df.drop(columns=col, inplace = True)

        df_cols = [*df.columns]
        if not all(col in df_cols for col in required_bands):
            raise TypeError("The algorithm '" + self.name + "' requires one "
                + "or more columns that are not in the 'df' data frame.")

        if explode:
            # Turn lists into rows for application of the local algorithm.
            df = unfold_df_lists(df)
            for col in [*df.columns]:
                if df[col].dtype == "object":
                    try:
                        df[col] = df[col].astype("Float32")
                    except:
                        pass

        # Apply the main function.
        try:
            preresult_df = self.function(df, options)
        except Exception as e:
            print(e)
            return

        # Restore lists.
        if explode:
            preresult_df = restore_df_lists(preresult_df)

        # Keep only the result columns.
        nonresult_cols = [c for c in [*preresult_df.columns] if c in df_cols]
        result_df = preresult_df.drop(columns=nonresult_cols)
        # Insert suffix for the applied stat to ensure all data columns will
        # have a stat suffix.
        if applied_stat:
            result_df.rename(columns={c:(c + "_" + applied_stat)
                for c in [*result_df.columns]}, inplace=True)

        return result_df


__all__ = ["LocalAlgorithm"]
