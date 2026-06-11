import pandas as pd

from core.cleaner_complete import (
    clean_missing,
    clean_number
)

# ============================================================
#  CDR NORMALIZER  –  Pakistan Telecom (Jazz / Warid / Zong /
#                     Ufone / Telenor)
# ============================================================


# -----------------------------------
# GET SECTOR
# -----------------------------------

def get_sector(cell_id):
    """
    Determine sector from Cell ID.

    Rules:
      - If the value is purely numeric  → use the 5th digit from the right.
      - If it is alphanumeric           → use the last character.

    Mapping:
      1 / 4 / 7  → Sector 1
      2 / 5 / 8  → Sector 2
      3 / 6 / 9  → Sector 3
    """
    try:
        cell_id = str(cell_id).strip()

        if not cell_id or cell_id.lower() in ("nan", "none", ""):
            return ""

        # Decide which digit to examine
        if cell_id.isdigit():
            # Pure numeric: 5th digit from the right (index -5)
            if len(cell_id) >= 5:
                digit = cell_id[-5]
            else:
                # Fallback to last digit when shorter than 5
                digit = cell_id[-1]
        else:
            # Alphanumeric: last character
            digit = cell_id[-1]

        if digit in ("1", "4", "7"):
            return "Sector 1"
        elif digit in ("2", "5", "8"):
            return "Sector 2"
        elif digit in ("3", "6", "9"):
            return "Sector 3"

        return ""

    except Exception:
        return ""


# -----------------------------------
# DETECT CDR SOURCE
# -----------------------------------

# Canonical (lowercased + underscore-normalised) column sets
# used to fingerprint each operator.

_JAZZ_NEW_COLS    = {"calltype", "aparty", "bparty"}
_JAZZ_OLD_COLS    = {"call_type", "a_party", "b_party", "date_and_time"}
_WARID_COLS       = {"call_type", "a_party", "b_party", "date_&_time"}
_ZONG_COLS        = {"msisdn", "strt_tm", "bnumber", "cell_id"}
_UFONE_COLS       = {"a_number", "b_number", "start_time", "end_time", "direction"}
_TELENOR_COLS     = {"msisdn", "b_party", "call_start_dt_tm",
                     "inbound_outbound_ind", "call_network_volume"}


def detect_operator(columns: list[str]) -> str:
    """
    Return the operator name based on column fingerprint.
    Columns must already be lowercased + underscore-normalised.
    """
    col_set = set(columns)

    if _UFONE_COLS.issubset(col_set):
        return "ufone"

    if _TELENOR_COLS.issubset(col_set):
        return "telenor"

    if _ZONG_COLS.issubset(col_set):
        return "zong"

    # Old Jazz has  a_party / b_party  AND  date_and_time
    if _JAZZ_OLD_COLS.issubset(col_set) and "date_and_time" in col_set:
        return "jazz_old"

    # Warid has  a_party / b_party  AND  date_&_time
    if _WARID_COLS.issubset(col_set) and "date_&_time" in col_set:
        return "warid"

    # New Jazz has  aparty / bparty  (no underscore)
    if _JAZZ_NEW_COLS.issubset(col_set):
        return "jazz"

    return "unknown"


# -----------------------------------
# PER-OPERATOR COLUMN MAPS
# -----------------------------------
#  Each map: raw_clean_col → unified_col

_MAP_JAZZ = {
    "calltype":      "call_type",
    "aparty":        "owner_number",
    "bparty":        "contact_number",
    "datetime":      "datetime",
    "duration":      "duration",
    "cellid":        "cell_id",
    "imsi":          "imsi",
    "imei":          "imei",
    "sitelocation":  "tower_address",
}

_MAP_JAZZ_OLD = {
    "call_type":     "call_type",
    "a_party":       "owner_number",
    "b_party":       "contact_number",
    "date_and_time": "datetime",
    "duration":      "duration",
    "cell_id":       "cell_id",
    "imsi":          "imsi",
    "imei":          "imei",
    "sitelocation":  "tower_address",
}

_MAP_WARID = {
    "call_type":     "call_type",
    "a_party":       "owner_number",
    "b_party":       "contact_number",
    "date_&_time":   "datetime",
    "duration":      "duration",
    "cell_id":       "cell_id",
    "imsi":          "imsi",
    "imei":          "imei",
    "sitelocation":  "tower_address",
}

_MAP_ZONG = {
    "call_type":     "call_type",
    "msisdn":        "owner_number",
    "strt_tm":       "datetime",
    "bnumber":       "contact_number",
    # mins / secs → duration computed separately
    "cell_id":       "cell_id",
    "imei":          "imei",
    "site_address":  "tower_address",
    "lng":           "longitude",
    "lat":           "latitude",
}

_MAP_UFONE = {
    "imei":          "imei",
    "imsi":          "imsi",
    "a_number":      "owner_number",
    "b_number":      "contact_number",
    "start_time":    "datetime",
    # end_time kept for reference only, not in final schema
    "type":          "call_type",
    "direction":     "direction",
    "location":      "tower_address",
    "cell_id":       "cell_id",
    "latitude":      "latitude",
    "longtitude":    "longitude",   # note: original typo preserved
    "longitude":     "longitude",
    "duration":      "duration",
}

_MAP_TELENOR = {
    "msisdn":                "owner_number",
    "b_party":               "contact_number",
    "imsi":                  "imsi",
    "imei":                  "imei",
    "call_start_dt_tm":      "datetime",
    "inbound_outbound_ind":  "direction",
    "call_network_volume":   "duration",
    "cell_site_id":          "cell_id",
    "lat":                   "latitude",
    "longtitude":            "longitude",   # original typo preserved
    "longitude":             "longitude",
    "call_type":             "call_type",
    "location":              "tower_address",
}

OPERATOR_MAPS = {
    "jazz":     _MAP_JAZZ,
    "jazz_old": _MAP_JAZZ_OLD,
    "warid":    _MAP_WARID,
    "zong":     _MAP_ZONG,
    "ufone":    _MAP_UFONE,
    "telenor":  _MAP_TELENOR,
}


# -----------------------------------
# DIRECTION NORMALISATION
# -----------------------------------

_DIRECTION_MAP = {
    # Jazz / Warid / Old Jazz
    "incoming":     "Incoming",
    "outgoing":     "Outgoing",
    "incoming sms": "Incoming SMS",
    "outgoing sms": "Outgoing SMS",

    # Zong
    "call - outgoing": "Outgoing",
    "call - incoming": "Incoming",
    "sms - outgoing":  "Outgoing SMS",
    "sms - incoming":  "Incoming SMS",

    # Telenor
    "i": "Incoming",
    "o": "Outgoing",

    # Ufone type/direction combo is handled separately
    "voice":  "Voice",
    "sms":    "SMS",
    "data":   "Data",
}


def normalize_direction(call_type_val: str, direction_val: str = "") -> str:
    """
    Produce a single unified direction/type label.
    Prefers direction_val when both are present (Ufone / Telenor).
    """
    ct = str(call_type_val).strip().lower()
    dv = str(direction_val).strip().lower()

    # Ufone: direction field is the primary source
    if dv and dv not in ("nan", "none", ""):
        combined = f"{ct} {dv}".strip()
        if combined in _DIRECTION_MAP:
            return _DIRECTION_MAP[combined]
        if dv in _DIRECTION_MAP:
            return _DIRECTION_MAP[dv]
        return direction_val.strip().title()

    if ct in _DIRECTION_MAP:
        return _DIRECTION_MAP[ct]

    return call_type_val.strip().title() if call_type_val.strip() else ""


# -----------------------------------
# EXTRACT LAT / LONG FROM TOWER ADDRESS
# -----------------------------------

def extract_lat_long(tower_series: pd.Series):
    """
    Parse  'name | lat | long [| extra]'  tower address strings.
    Returns (towers, latitudes, longitudes) as lists.
    """
    towers, latitudes, longitudes = [], [], []

    for value in tower_series:
        try:
            parts = str(value).split("|")
            if len(parts) >= 3:
                towers.append(parts[0].strip())
                latitudes.append(parts[1].strip())
                longitudes.append(parts[2].strip())
            else:
                towers.append(value)
                latitudes.append("")
                longitudes.append("")
        except Exception:
            towers.append(value)
            latitudes.append("")
            longitudes.append("")

    return towers, latitudes, longitudes


# -----------------------------------
# CLEAN COLUMN NAMES
# -----------------------------------

def _clean_col_name(col: str) -> str:
    return (
        str(col)
        .lower()
        .strip()
        .replace(" ", "_")
        .replace("-", "_")
    )


# -----------------------------------
# NORMALIZE DATAFRAME  (main entry point)
# -----------------------------------

def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:

    # ── 1. Normalise column names ─────────────────────────────────
    df.columns = [_clean_col_name(c) for c in df.columns]

    print("\nDetected Columns:")
    print(df.columns.tolist())

    # ── 2. Detect operator ────────────────────────────────────────
    operator = detect_operator(df.columns.tolist())
    print(f"\nDetected Operator: {operator.upper()}")

    # ── 3. Clean cell values ──────────────────────────────────────
    for col in df.columns:
        df[col] = df[col].map(clean_missing)

    # ── 4. Operator-specific pre-processing ───────────────────────

    # Zong: data starts at row 5 (already skipped during read_excel
    #       via skiprows=4); just compute duration from MINS + SECS.
    if operator == "zong":
        if "mins" in df.columns and "secs" in df.columns:
            df["duration"] = (
                pd.to_numeric(df["mins"], errors="coerce").fillna(0) * 60
                + pd.to_numeric(df["secs"], errors="coerce").fillna(0)
            )

    # Ufone: build combined direction from Type + Direction columns
    if operator == "ufone":
        type_col  = df["type"].astype(str)      if "type"      in df.columns else pd.Series([""] * len(df))
        dir_col   = df["direction"].astype(str)  if "direction" in df.columns else pd.Series([""] * len(df))
        df["_unified_direction"] = [
            normalize_direction(t, d) for t, d in zip(type_col, dir_col)
        ]

    # Telenor: normalise direction
    if operator == "telenor":
        if "inbound_outbound_ind" in df.columns:
            df["inbound_outbound_ind"] = df["inbound_outbound_ind"].apply(
                lambda v: normalize_direction(str(v))
            )

    # ── 5. Map columns to unified schema ─────────────────────────
    col_map = OPERATOR_MAPS.get(operator, {})
    normalized = pd.DataFrame()

    for raw_col, unified_col in col_map.items():
        if raw_col in df.columns:
            if unified_col in normalized.columns:
                # Already mapped (e.g. longitude mapped twice); skip duplicates
                continue
            normalized[unified_col] = df[raw_col]

    print(f"\nAfter column mapping: {len(normalized)} rows, "
          f"{normalized.columns.tolist()}")

    # ── 6. Post-map direction fix ─────────────────────────────────
    if operator == "ufone":
        normalized["direction"] = df["_unified_direction"].values
    elif "call_type" in normalized.columns:
        normalized["direction"] = normalized["call_type"].apply(
            lambda v: normalize_direction(str(v))
        )
    elif "direction" not in normalized.columns:
        normalized["direction"] = ""

    # Ensure direction column exists
    if "direction" not in normalized.columns:
        normalized["direction"] = ""

    # ── 7. Clean numeric / phone fields ──────────────────────────
    for col in ("owner_number", "contact_number", "imei", "imsi"):
        if col in normalized.columns:
            normalized[col] = normalized[col].map(clean_number)

    # ── 8. Keep only mobile contacts (92 / 03 prefix) ────────────
    if "contact_number" in normalized.columns:
        normalized = normalized[
            normalized["contact_number"]
            .astype(str)
            .str.startswith(("92", "03"), na=False)
        ]

    print(f"After mobile filter: {len(normalized)}")

    # ── 9. Parse datetime ─────────────────────────────────────────
    if "datetime" in normalized.columns:
        normalized["raw_datetime"] = normalized["datetime"].astype(str)

        sample_size = min(10, len(normalized))
        if sample_size > 0:
            print("\nRandom datetime samples:")
            print(normalized["raw_datetime"].sample(sample_size).tolist())

        normalized["datetime"] = pd.to_datetime(
            normalized["raw_datetime"],
            errors="coerce",
            dayfirst=False,
        )

        bad_rows = normalized[normalized["datetime"].isna()]
        print(f"\nInvalid datetime count: {len(bad_rows)}")

        normalized["call_date"] = normalized["datetime"].dt.strftime("%Y-%m-%d")
        normalized["call_time"] = normalized["datetime"].dt.strftime("%H:%M:%S")

    # ── 10. Extract lat / long from tower address ─────────────────
    if "tower_address" in normalized.columns:
        if (
            "latitude"  not in normalized.columns
            or "longitude" not in normalized.columns
        ):
            towers, lats, lngs = extract_lat_long(normalized["tower_address"])
            normalized["tower_address"] = towers
            normalized["latitude"]      = lats
            normalized["longitude"]     = lngs

    # ── 11. Sector ────────────────────────────────────────────────
    if "cell_id" in normalized.columns:
        normalized["sector"] = normalized["cell_id"].map(get_sector)

    # ── 12. Ensure all final columns exist ────────────────────────
    FINAL_COLUMNS = [
        "owner_number",
        "contact_number",
        "imei",
        "imsi",
        "call_date",
        "call_time",
        "duration",
        "direction",
        "cell_id",
        "sector",
        "tower_address",
        "latitude",
        "longitude",
    ]

    # Add missing columns as empty strings so downstream code
    # always receives a consistent schema
    for col in FINAL_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = ""

    normalized = normalized[FINAL_COLUMNS]

    print(f"\nFINAL ROWS: {len(normalized)}")
    return normalized


# -----------------------------------
# HELPER: read Excel with operator-
# aware skiprows
#
#   Jazz / Warid / Ufone → row 1  (skiprows = 0)
#   Telenor              → row 3  (skiprows = 2)
#   Zong                 → row 6  (skiprows = 5)
# -----------------------------------

# Unique column signatures used to identify the header row
# Keys are lowercased strings that MUST appear together in the same row.
_HEADER_SIGNATURES = {
    "zong":    {"msisdn", "bnumber", "strt_tm"},
    "telenor": {"msisdn", "call_start_dt_tm", "inbound_outbound_ind"},
}


def _find_header_row(peek: pd.DataFrame, signatures: dict) -> tuple[str, int]:
    """
    Scan peek (header=None) row by row.
    Return (operator_hint, row_index) for the first row that matches
    a known signature, or ("standard", 0) if nothing matches.
    """
    for row_idx in range(len(peek)):
        row_vals = {
            str(v).strip().lower()
            for v in peek.iloc[row_idx]
        }
        for operator, sig in signatures.items():
            if sig.issubset(row_vals):
                return operator, row_idx

    return "standard", 0


def read_cdr_excel(filepath: str, sheet_name=0) -> pd.DataFrame:
    """
    Read a CDR Excel file, automatically skipping owner-info rows
    that appear before the actual column header row.

    Operator header row positions (1-based, as seen in Excel):
        Jazz / Warid / Ufone  →  Row 1  (no skip needed)
        Telenor               →  Row 3  (skip 2 rows)
        Zong                  →  Row 6  (skip 5 rows)

    Usage:
        df = read_cdr_excel("path/to/cdr.xlsx")
        result = normalize_dataframe(df)
    """
    # Peek at first 7 rows without any header assumption
    peek = pd.read_excel(
        filepath,
        sheet_name=sheet_name,
        nrows=7,
        header=None
    )

    operator_hint, header_row_idx = _find_header_row(peek, _HEADER_SIGNATURES)

    if header_row_idx > 0:
        print(
            f"{operator_hint.upper()} CDR detected — "
            f"header found at Excel row {header_row_idx + 1}, "
            f"skipping {header_row_idx} row(s)"
        )
        df = pd.read_excel(
            filepath,
            sheet_name=sheet_name,
            skiprows=header_row_idx   # pandas uses this row as the header
        )
    else:
        print("Standard CDR detected — reading from row 1")
        df = pd.read_excel(filepath, sheet_name=sheet_name)

    return df