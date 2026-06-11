import re

MISSING_VALUES = {
    "",
    " ",
    "?",
    "??",
    "n/a",
    "na",
    "null",
    "none",
    "-"
}


def clean_missing(value):

    if value is None:
        return ""

    val = str(value).strip().lower()

    if val in MISSING_VALUES:
        return ""

    return str(value).strip()



def clean_number(value):

    if value is None:
        return ""

    value = str(value)

    value = re.sub(r"\D", "", value)

    if value.endswith(".0"):
        value = value[:-2]

    return value