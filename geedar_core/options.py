#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Command-line option parsing and validation used by GEEDaR."""

from .utils import autocast_str, str_to_list, text_box

#%% UserOptions class

class UserOptions:
    """
    This class deals with the command line user options, arranging and
    validating them. Instatiation takes as input the command line string and a
    guide dictionary with the valid options.

    Instantiation
    -------------

    These are the instantiation parameters:

        cmd_line: the list of command line parts to be interpreted (list;
            defaults to "-h", which calls for instructions on the command line
            options).
        guide: a dictionary with the structure of the 'guide_example'
            attribute (dict, defaults to the content of '_default_guide').

    Regarding the content of the guide dictionary, here are some instructions:

        To define a command line option as mandatory, the key 'default_value'
        must take None as value. For optional arguments, this key must take a
        string as argument - as a partial string that would come from the user
        command line.

        If a leading command letter (like the '-i:' in '-i:test.csv') is not
        mandatory, set the key 'auto_assign_command' as True.

        The key 'valid_values' takes a list. The list must contain objects
        corresponding to the expected unique values or expected types. A Range
        object is also accepted.

    """

    _default_guide = {
        "i": {
            "name": "input",
            "description": ("The path of the input file. For a path with "
                + "white spaces, you must enclose it in quotes. This argument "
                + "is mandatory if you do not provide the 'mode' argument."),
            "is_a_list": False,
            "valid_values": [str],
            "default_value": "",
            "auto_assign_command": True
        },
        "o": {
            "name": "output",
            "description": ("The path of the output file. For a path with "
                + "white spaces, you must enclose it in quotes."),
            "is_a_list": False,
            "valid_values": [str],
            "default_value": "auto",
            "auto_assign_command": False
        },
        "m": {
            "name": "mode",
            "description": ("The operation mode of GEEDaR: 1, 2 or 3. "
                + "A zero stands for automatic mode detection. This argument "
                + "is mandatory if you do not provide the 'input' argument."),
            "is_a_list": False,
            "valid_values": [0,1,2,3],
            "default_value": "0",
            "auto_assign_command": False
        },
        "c": {
            "name": "code",
            "description": ('The "demand code", describing which product, '
                + "cloud algorithm, local algorithm, and reducer are to be "
                + "used. To pass a list of codes, they MUST be enclosed with "
                + "square brackets and separated by commas, like a Python "
                + "list, without white spaces inside the list."),
            "is_a_list": True,
            "valid_values": [str, int],
            "default_value": "auto",
            "auto_assign_command": False
        },
        "z": {
            "name": "stations",
            "description": ("In operation mode 3, limits execution to "
                + "demands associated with the informed station codes."),
            "is_a_list": True,
            "valid_values": [str, int],
            "default_value": "auto",
            "auto_assign_command": False
        },
        "d": {
            "name": "demand_ids",
            "description": ("In operation mode 3, limits execution to "
                + "demands with the informed database ids."),
            "is_a_list": True,
            "valid_values": [str, int],
            "default_value": "auto",
            "auto_assign_command": False
        },
        "k": {
            "name": "kml",
            "description": "Sets 'kml' as the source of the information for "
                + "defining the geometry of the 'area of interest'.",
            "is_a_list": False,
            "valid_values": [True,False],
            "default_value": "False",
            "auto_assign_command": False
        },
        "r": {
            "name": "radius",
            "description": ("Sets a radius, in meters, for the area of "
                + "interest. Zero is not allowed. "
                + "A value of -1 stands for default. In such case, there is "
                + "no need to use the 'r' parameter in the command line."),
            "is_a_list": False,
            "valid_values": [range(-1,100000)],
            "default_value": "-1",
            "auto_assign_command": False
        },
        "t": {
            "name": "timewindow",
            "description": ("Sets a +/- tolerance, in days, for matching up "
                + "the dates of field data and satellite data."),
            "is_a_list": False,
            "valid_values": [range(0,367)],
            "default_value": "0",
            "auto_assign_command": False
        },
        "s": {
            "name": "separate",
            "description": "When exporting the results as a csv file, an "
                + "extra file will be saved with the results in separate "
                + "groups of columns for each unique demand code. Useful for "
                + "comparing results between instruments.",
            "is_a_list": False,
            "valid_values": [True,False],
            "default_value": "False",
            "auto_assign_command": False
        },
        "h": {
            "name": "help",
            "description": ("Describes command line options for starting "
                + "GEEDaR."),
            "is_a_list": False,
            "valid_values": [True,False],
            "default_value": "False",
            "auto_assign_command": False
        }
    }
    example_guide = _default_guide.copy()

    def __init__(self, cmd_line=["-h"], guide=_default_guide,
            letter_marker = "-", word_marker = "--", separator = [":","="]):
        # Check types.
        if not isinstance(cmd_line, list):
            raise TypeError("'cmd_line' must be a list.")
        if not isinstance(guide, dict):
            raise TypeError("'guide' must be a dict.")
        if not isinstance(letter_marker, str):
            raise TypeError("'letter_marker' must be a string.")
        if not isinstance(word_marker, str):
            raise TypeError("'word_marker' must be a string.")
        if not isinstance(separator, list):
            if isinstance(separator, str):
                separator = [separator]
            else:
                raise TypeError("'separator' must be a string or list of "
                    + "strings.")
        else:
            if not all(isinstance(s, str) for s in separator):
                raise TypeError("'separator' must be a list of strings.")

        self._cmd_line = cmd_line
        self._guide = guide
        self._letter_marker = letter_marker
        self._word_marker = word_marker
        self._separator = separator
        self.options_dict = None
        self._validate_options()

    # Validate 'user_options' and 'guide', returning a standardized dict.
    def _validate_options(self):
        args = self._cmd_line
        guide = self._guide
        letter_marker = self._letter_marker
        word_marker = self._word_marker
        separator = self._separator

        # Validate the structure of the 'guide' dict and get:
        # - the list of param. letters (option ids) and words (option names)
        # - the accepted unsigned arguments
        # - the default values, which will be inserted into a pre-filled user-
        #   options list.
        valid_command_letters = []
        valid_command_words = []
        valid_unsigned_args = []
        user_options = dict()
        for option_id in [*guide]:
            if [*guide[option_id]].sort() != [
                    "name","is_a_list","valid_values","default_value",
                    "auto_assign_command"].sort():
                raise ValueError("'guide' has an incorrect structure.")
            valid_command_letters = valid_command_letters + [option_id]
            valid_command_words = valid_command_words + [guide[option_id][
                "name"]]
            if guide[option_id]["auto_assign_command"]:
                valid_unsigned_args = valid_unsigned_args + [option_id]
            user_options[option_id] = guide[option_id]["default_value"]

        # Check each argument, breaking it into a command part and a value
        # part, in accordance with 'separator'. The default values in the user
        # options list will be replaced by the options provided in 'args'.
        # Unsigned arguments will be dealt with by inserting the presumed
        # command letter before the user-provided value. By unsigned argument
        # we mean an argument without a leading indicator such as "-" or "--".
        # Unsigned arguments receive the presumed command letter by following
        # the original order of the options in 'guide_list' for which
        # 'auto_assign_command' is true.
        unsigned_args_count = 0
        for arg_ind in range(len(args)):
            arg = args[arg_ind]
            # Signed? How?
            if arg[:len(word_marker)] == word_marker:
                marker_end_pos = len(word_marker) - 1
            elif arg[:len(letter_marker)] == letter_marker:
                marker_end_pos = len(letter_marker) - 1
            # Unsigned.
            else:
                marker_end_pos = -1

            if marker_end_pos < 0:
                unsigned_args_count = unsigned_args_count + 1
                if unsigned_args_count > len(valid_unsigned_args):
                    raise ValueError("Unrecognized argument: " + arg)
                else:
                    param_str = valid_unsigned_args[unsigned_args_count - 1]
                    val_str = arg
            else:
                separator_end_pos = [arg.find(s) + len(s) - 1
                    for s in separator if arg.find(s) > 0]
                # Is there a separator (such as ':' in '-r:250')?
                # If not, the argument is in the form '-a', with no value.
                if len(separator_end_pos) == 0:
                    param_str = arg[(marker_end_pos + 1):]
                    val_str = "True" # This kind of command is logical (true
                        # if used by the user, false if omitted)
                else:
                    param_str = arg[(marker_end_pos + 1):
                        (separator_end_pos[0])]
                    val_str = arg[(separator_end_pos[0] + 1):]

            # Validate the parameter:
            if (param_str not in valid_command_letters
                    + valid_command_words):
                raise ValueError("Unrecognized parameter ('" +
                    param_str + "') in the command part '" + arg + "'.")
            # Convert option name (word) to option id (letter).
            if param_str in valid_command_words:
                letter_ind = valid_command_words.index(param_str)
                param_str = valid_command_letters[letter_ind]
            # Update value in the user options list:
            user_options[param_str] = val_str

        # Validate the values associated to each command.
        for option_id in [*user_options]:
            # Get the current value:
            val_str = user_options[option_id]
            # If a value is required but not given, raises an error.
            if val_str == "" and guide[option_id]["default_value"] is None:
                raise ValueError("An argument is required but was not "
                    + "provided for the parameter '" + option_id + "' ("
                    + guide[option_id]["name"] + ").")
            # If the value is an empty string and so is the default value,
            # no analysis is needed.
            #if val_str == "" and guide[option_id]["default_value"] == "":
            #    continue
            # Empty strings need to be enforced as such:
            if val_str == "":
                val_str = "''"
            # Turn the reference and the user values into lists for stepwise
            # validation:
            if guide[option_id]["is_a_list"]:
                val_list = str_to_list(val_str, opening = "[", closing = "]",
                    sep = [",",";"], optional_enclosing = True)
            else:
                val_list = [autocast_str(val_str)]
            ref_list = guide[option_id]["valid_values"]
            if ref_list is None:
                continue
            if ref_list == []:
                continue
            if not isinstance(ref_list, list):
                ref_list = [ref_list]
            # All types are valid?
            valid_types = []
            for r1 in ref_list:
                if type(r1) is not list:
                    r1 = [r1]
                for r2 in r1:
                    if type(r2) is type:
                        valid_types = valid_types + [r2]
                    elif isinstance(r2, range):
                        valid_types = valid_types + [int]
                    else:
                        valid_types = valid_types + [type(r2)]
            value_types = [type(v) for v in val_list]
            if not all(v in valid_types for v in value_types):
                raise ValueError("The value associated with the command '-"
                    + option_id + "' (='--", guide[option_id]["name"]
                    + "') should be of type " + "or".join(
                    [str(t) for t in valid_types]) + ".")
            # Values in accepted range/list?
            out_val = False
            for r1 in ref_list:
                if not isinstance(r1, list):
                    r1 = [r1]
                for r2 in r1:
                    if isinstance(r2, list):
                        raise ValueError("Invalid content of " + option_id
                            + "['valid_values'] in the user options guide.")
                    if isinstance(r2, range):
                        if not all(v in r2 for v in val_list):
                            out_val = True
                            break
            if out_val:
                raise ValueError("One or more invalid values for the option "
                    + option_id + " (" + guide[option_id]["name"] + ").")
            # Set a definitive value to the option:
            if not guide[option_id]["is_a_list"]:
                user_options[option_id] = val_list[0]
            else:
                user_options[option_id] = val_list

        # Finally, convert option ids back to (more friendly) option names:
        final_user_options = dict()
        for k in user_options:
            final_user_options[guide[k]["name"]] = user_options[k]
        self.options_dict = final_user_options

    # Shows automatically generated instructions on command line options based
    # on this object contents.
    def show_help(self):
        options_guide = self._guide
        letter_marker = self._letter_marker
        word_marker = self._word_marker
        separators = self._separator

        legend_range = False
        cmd_dict = dict()
        usage_str = "geedar "
        for cmd_letter, guide in options_guide.items():

            cmd_dict[cmd_letter] = {"syntax": "", "default_value": ""}

            default_value = options_guide[cmd_letter]["default_value"]
            if default_value is None:
                default_value = "None"
            elif default_value not in ["False", "True"]:
                if len(default_value) > 1:
                    if not (default_value[0] == "-" and
                            default_value[1:].isnumeric()):
                        default_value = "'" + default_value + "'"
                elif not default_value.isnumeric():
                    default_value = "'" + default_value + "'"

            cmd_dict[cmd_letter]["default_value"] = default_value

            par_str = letter_marker + str(cmd_letter)
            if default_value == "False":
                cmd_str = par_str
            else:
                par_str = par_str + separators[0]
                val_str = ""
                for obj in guide["valid_values"]:
                    if type(obj) is type:
                        tmp_str = obj.__name__
                    elif type(obj) is range:
                        legend_range = True
                        tmp_str = str(obj.start) + ":" + str(obj.stop - 1)
                    else:
                        tmp_str = str(obj)
                    val_str = val_str + tmp_str + "|"
                val_str = val_str[:-1]
                if guide["is_a_list"]:
                    val_str = "<list " + val_str + ">"
                else:
                    val_str = "<" + val_str + ">"
                cmd_str = par_str + val_str

            cmd_dict[cmd_letter]["syntax"] = cmd_str

            if default_value == "None":
                cmd_str = "<" + cmd_str + ">"
            else:
                cmd_str = "[" + cmd_str + "]"

            usage_str = usage_str + cmd_str + " "

        print("\nUsage: " + usage_str + "\n")

        print("\nCommand options:")

        for cmd_letter in [*options_guide]:
            print("")
            print(text_box(
                letter_marker + cmd_letter + ", "
                + word_marker + options_guide[cmd_letter]["name"],
                first_line_indent=4, other_lines_indent=8, max_width=80))
            print(text_box(
                options_guide[cmd_letter]["description"],
                first_line_indent=8, other_lines_indent=8, max_width=80))
            if cmd_dict[cmd_letter]["default_value"] != "False":
                print(text_box(
                    "Default value: " + cmd_dict[cmd_letter]["default_value"],
                    first_line_indent=8, other_lines_indent=8, max_width=80))

        # Observations.
        print("\nNotes:\n")
        print(text_box(
            "The characters '<', '>' and '|' shown above must not be "
            + "used in the real command line. The same applies to '[' "
            + "and ']', except when the user wants to pass a list of "
            + "values, in which case they must be enclosed in square "
            + "brackets and separated by commas, with no spaces.",
            first_line_indent=4, other_lines_indent=4,
            max_width=80))
        if legend_range:
            print("")
            print(text_box(
                "When a range of integers is accepted as value, a ':' "
                + "separates the minimum and maximum.",
                first_line_indent=4, other_lines_indent=4,
                max_width=80))
