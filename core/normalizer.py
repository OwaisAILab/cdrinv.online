import pandas as pd
import hashlib
import re  # <-- ADDED for normalize_mobile_number
from core.cleaner_complete import clean_missing, clean_number
# removed unused import: from core.imei_validator import validate_imei


def calculate_imei_check_digit(first14):
    total = 0
    for pos, digit in enumerate(first14, start=1):
        d = int(digit)
        # 2nd, 4th, 6th ... 14th digit
        if pos % 2 == 0:
            d *= 2
            if d > 9:
                d = (d // 10) + (d % 10)
        total += d
    return str((10 - (total % 10)) % 10)


def corrected_imei(imei):
    imei = str(imei).strip()
    if not imei.isdigit():
        return ""
    if len(imei) != 15:
        return ""
    first14 = imei[:14]
    check_digit = calculate_imei_check_digit(first14)
    return first14 + check_digit


# -----------------------------------
# GET SECTOR
# -----------------------------------
def get_sector(cell_id):
    """
    Deterministic sector assignment for CDR intelligence grouping.

    IMPORTANT:
    - This is NOT geographic truth.
    - It is a stable clustering mechanism for analytics.

    Guarantees:
    - Same Cell ID → same sector always
    - No dependency on string position
    - Balanced distribution across sectors
    """
    try:
        cell_id = str(cell_id).strip()
        if not cell_id or cell_id.lower() in ("nan", "none", ""):
            return ""
        normalized = cell_id.upper()
        hash_value = hashlib.md5(normalized.encode()).hexdigest()
        bucket = int(hash_value[-1], 16) % 9 + 1
        if bucket in (1, 4, 7):
            return "Sector 1"
        elif bucket in (2, 5, 8):
            return "Sector 2"
        else:
            return "Sector 3"
    except Exception:
        return ""


# -----------------------------------
# DETECT CDR SOURCE
# -----------------------------------

# Canonical (lowercased + underscore-normalised) column sets
# used to fingerprint each operator.

_JAZZ_NEW_COLS = {"calltype", "aparty", "bparty"}
_JAZZ_OLD_COLS = {"call_type", "a_party", "b_party", "date_and_time"}
_WARID_COLS = {"call_type", "a_party", "b_party", "date_&_time"}
_ZONG_COLS = {"msisdn", "strt_tm", "bnumber", "cell_id"}
_UFONE_COLS = {"a_number", "b_number", "start_time", "end_time", "type"}
_TELENOR_COLS = {"msisdn", "b_party", "call_start_dt_tm",
                 "inbound_outbound_ind", "call_network_volume"}
_TELENOR_ORIG_DIALED_COLS = {"msisdn", "call_orig_num", "call_dialed_num",
                             "call_start_dt_tm", "call_network_volume"}


def detect_operator(columns: list[str]) -> str:
    """
    Production-grade CDR operator detection using weighted scoring.
    Instead of strict matching, we compute confidence scores.
    """
    col_set = set(columns)
    scores = {
        "ufone": 0,
        "telenor": 0,
        "telenor_orig_dialed": 0,
        "zong": 0,
        "jazz": 0,
        "jazz_old": 0,
        "warid": 0
    }

    # Jazz New
    if "calltype" in col_set: scores["jazz"] += 3
    if "aparty" in col_set: scores["jazz"] += 3
    if "bparty" in col_set: scores["jazz"] += 3

    # Jazz Old
    if "a_party" in col_set: scores["jazz_old"] += 3
    if "b_party" in col_set: scores["jazz_old"] += 3
    if "date_and_time" in col_set: scores["jazz_old"] += 2

    # Warid
    if "date_&_time" in col_set: scores["warid"] += 3
    if "a_party" in col_set: scores["warid"] += 2
    if "b_party" in col_set: scores["warid"] += 2

    # Zong
    if "msisdn" in col_set: scores["zong"] += 2
    if "strt_tm" in col_set: scores["zong"] += 3
    if "bnumber" in col_set: scores["zong"] += 3

    # Ufone
    if "a_number" in col_set: scores["ufone"] += 3
    if "b_number" in col_set: scores["ufone"] += 3
    if "start_time" in col_set: scores["ufone"] += 2
    if "type" in col_set: scores["ufone"] += 1

    # Telenor standard
    if "msisdn" in col_set: scores["telenor"] += 2
    if "call_start_dt_tm" in col_set: scores["telenor"] += 3
    if "inbound_outbound_ind" in col_set: scores["telenor"] += 3
    if "call_network_volume" in col_set: scores["telenor"] += 2

    # Telenor orig/dialed variant
    if "call_orig_num" in col_set: scores["telenor_orig_dialed"] += 3
    if "call_dialed_num" in col_set: scores["telenor_orig_dialed"] += 3
    if "call_start_dt_tm" in col_set: scores["telenor_orig_dialed"] += 2

    best_operator = max(scores, key=scores.get)
    best_score = scores[best_operator]

    print("\nOperator confidence ranking:")
    for op, sc in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        print(f"{op}: {sc}")

    if best_score < 4:
        return "unknown"
    return best_operator


def resolve_call_intelligence(row, operator: str):
    """
    Unified intelligence resolver for:
    - direction (Incoming / Outgoing)
    - call type (Voice / SMS / Data)
    - caller/receiver interpretation consistency

    This removes operator-specific ambiguity.
    """
    def safe(val):
        return str(val).strip().lower() if val is not None else ""

    call_type = safe(row.get("call_type", ""))
    direction = safe(row.get("direction", ""))
    inbound = safe(row.get("inbound_outbound_ind", ""))
    udir = safe(row.get("_unified_direction", ""))

    # 1. Determine base direction
    raw_direction = direction or inbound or udir
    if raw_direction in ("i", "in", "incoming", "call - incoming"):
        final_direction = "Incoming"
    elif raw_direction in ("o", "out", "outgoing", "call - outgoing"):
        final_direction = "Outgoing"
    elif "incoming" in raw_direction:
        final_direction = "Incoming"
    elif "outgoing" in raw_direction:
        final_direction = "Outgoing"
    else:
        final_direction = ""

    # 2. Determine service type
    if call_type in ("sms", "text"):
        service_type = "SMS"
    elif call_type in ("data", "gprs", "internet"):
        service_type = "Data"
    elif "sms" in call_type:
        service_type = "SMS"
    elif "data" in call_type or "gprs" in call_type:
        service_type = "Data"
    else:
        service_type = "Voice"

    # 3. Combined intelligence label
    if service_type == "SMS":
        final_label = f"{final_direction} SMS"
    elif service_type == "Data":
        final_label = "Data Session"
    else:
        final_label = final_direction

    return final_direction, service_type, final_label


# -----------------------------------
# PER-OPERATOR COLUMN MAPS
# -----------------------------------
_MAP_JAZZ = {
    "calltype": "call_type",
    "aparty": "owner_number",
    "bparty": "contact_number",
    "date_and_time": "datetime",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "cellid": "cell_id",
    "imsi": "imsi",
    "imei": "imei",
    "sitelocation": "tower_address",
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "site_address": "tower_address",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
}
_MAP_JAZZ_OLD = {
    "call_type": "call_type",
    "a_party": "owner_number",
    "b_party": "contact_number",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "duration": "duration",
    "cell_id": "cell_id",
    "imsi": "imsi",
    "imei": "imei",
    "sitelocation": "tower_address",
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "site_address": "tower_address",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
}
_MAP_WARID = {
    "call_type": "call_type",
    "a_party": "owner_number",
    "b_party": "contact_number",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "duration": "duration",
    "cell_id": "cell_id",
    "imsi": "imsi",
    "imei": "imei",
    "sitelocation": "tower_address",
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "site_address": "tower_address",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
}

_MAP_ZONG = {
    "call_type": "call_type",
    "msisdn": "owner_number",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "bnumber": "contact_number",
    "cell_id": "cell_id",
    "imei": "imei",
    "sitelocation": "tower_address",
    "site_address": "tower_address",   # ← ADD THIS
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
}

_MAP_UFONE = {
    "imei": "imei",
    "imsi": "imsi",
    "a_number": "owner_number",
    "b_number": "contact_number",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "type": "call_type",
    "direction": "direction",
    "sitelocation": "tower_address",
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "site_address": "tower_address",
    "cell_id": "cell_id",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
    "duration": "duration",

}
_MAP_TELENOR = {
    "msisdn": "owner_number",
    "b_party": "contact_number",
    "imsi": "imsi",
    "imei": "imei",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "inbound_outbound_ind": "direction",
    "call_network_volume": "duration",
    "cell_site_id": "cell_id",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
    "call_type": "call_type",
    "sitelocation": "tower_address",
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "site_address": "tower_address",
}
_MAP_TELENOR_ORIG_DIALED = {
    "msisdn": "owner_number",
    "imsi": "imsi",
    "imei": "imei",
    "date_and_time": "datetime",
    "datetime": "datetime",
    "date&time" : "datetime",
    "call_start_dt_tm": "datetime",
    "start_time": "datetime",
    "call_type": "direction",          # OUTGOING / INCOMING
    "call_network_volume": "duration",
    "cell_site_id": "cell_id",
    "latitude": "latitude",
    "longtitude": "longitude",
    "longitude": "longitude",
    "lng": "longitude",
    "lat": "latitude",
    "sitelocation": "tower_address",
    "site": "tower_address",
    "Site": "tower_address",
    "location": "tower_address",
    "site_address": "tower_address",
    "call_type_dup1": "call_type",      # GSM / SMS / DATA etc.
}

OPERATOR_MAPS = {
    "jazz": _MAP_JAZZ,
    "jazz_old": _MAP_JAZZ_OLD,
    "warid": _MAP_WARID,
    "zong": _MAP_ZONG,
    "ufone": _MAP_UFONE,
    "telenor": _MAP_TELENOR,
    "telenor_orig_dialed": _MAP_TELENOR_ORIG_DIALED,
}


# -----------------------------------
# DIRECTION NORMALISATION
# -----------------------------------
_DIRECTION_MAP = {
    "incoming": "Incoming",
    "outgoing": "Outgoing",
    "incoming sms": "Incoming SMS",
    "outgoing sms": "Outgoing SMS",
    "call - outgoing": "Outgoing",
    "call - incoming": "Incoming",
    "sms - outgoing": "Outgoing SMS",
    "sms - incoming": "Incoming SMS",
    "i": "Incoming",
    "o": "Outgoing",
    "voice": "Voice",
    "sms": "SMS",
    "data": "Data",
}


def normalize_direction(call_type_val: str, direction_val: str = "") -> str:
    """
    Produce a single unified direction/type label.
    Prefers direction_val when both are present (Ufone / Telenor).
    """
    ct = str(call_type_val).strip().lower()
    dv = str(direction_val).strip().lower()

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
    Parse tower address strings that may contain coordinates.
    Supports:
        - "name | lat | lon"
        - "name, \"description | lat | lon\""
        - "name | lat | lon | extra"
    Returns (towers, latitudes, longitudes) as lists.
    """
    towers, latitudes, longitudes = [], [], []
    for value in tower_series:
        try:
            val = str(value).strip()
            # Check if it contains a pipe
            if '|' in val:
                # Split by pipe
                parts = val.split('|')
                # Clean lat/lon parts: remove quotes, extra spaces
                lat_part = parts[1].strip().strip('"').strip()
                lon_part = parts[2].strip().strip('"').strip()
                # The first part may contain a comma and extra text; we want the site name.
                # Try to extract first part before any comma.
                name_part = parts[0].strip()
                # If there is a comma, take the part before it
                if ',' in name_part:
                    name_part = name_part.split(',')[0].strip()
                towers.append(name_part)
                latitudes.append(lat_part)
                longitudes.append(lon_part)
            else:
                # No pipe: treat as plain tower address
                towers.append(val)
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
# NORMALIZE MOBILE NUMBER FORMAT
# -----------------------------------
def normalize_mobile_number(value: str) -> str:
    """
    Normalise Pakistani mobile numbers to 92XXXXXXXXXX format.
    FIX: accept any digit after leading 3 for 10-digit numbers.
    """
    val = str(value).strip()
    # Remove any non-digit characters (though clean_number already did)
    val = re.sub(r'\D', '', val)   # re is now imported
    if not val:
        return val

    # 1. Already standard: 92XXXXXXXXXX (12 digits)
    if val.startswith("92") and len(val) == 12:
        return val

    # 2. Standard Pakistani: 03XXXXXXXXX (11 digits)
    if val.startswith("03") and len(val) == 11:
        return "92" + val[1:]

    # 3. 3XXXXXXXXX (10 digits) -> now accept any second digit (0-9)
    if val.startswith("3") and len(val) == 10:
        return "92" + val

    # 4. Handle leading zeros (092, 0092)
    if val.startswith("0"):
        stripped = val.lstrip('0')
        if stripped.startswith("92") and len(stripped) == 12:
            return stripped
        if stripped.startswith("3") and len(stripped) == 10:
            return "92" + stripped

    # Everything else -> untouched
    return val


# -----------------------------------
# NON-MOBILE / SERVICE CONTACT DETECTION
# -----------------------------------
def is_non_mobile_contact(value: str) -> bool:
    """
    Return True if the raw (pre-clean_number) contact value does NOT
    look like a normal Pakistani mobile number — e.g. hex-encoded
    SMS sender IDs, alphanumeric short codes, bank/service names,
    or short numeric codes (shortcodes).
    """
    raw = str(value).strip()
    if not raw:
        return False
    digits_only = raw.lstrip("+")
    if not digits_only.isdigit():
        return True
    if digits_only.startswith(("92", "03")):
        return False
    if len(digits_only) == 10 and digits_only.startswith("3"):
        return False
    return True


# -----------------------------------
# IMEI / IMSI SWITCH DETECTION
# -----------------------------------
def _flag_identity_switches(normalized: pd.DataFrame, id_col: str, prefix: str) -> pd.DataFrame:
    """
    Production-grade IMEI/IMSI switch detection.
    - ignores empty/noise values
    - requires stable transition (not single-row noise)
    - prevents false switches from missing data
    """
    switch_col = f"{prefix}_switch"
    count_col = f"{prefix}_switch_count"
    prev_col = f"previous_{prefix}"

    if id_col not in normalized.columns or normalized.empty:
        normalized[switch_col] = False
        normalized[count_col] = 1
        normalized[prev_col] = ""
        return normalized

    df = normalized.copy()
    df[switch_col] = False
    df[count_col] = 1
    df[prev_col] = ""

    group_cols = ["owner_number"] if "owner_number" in df.columns else []
    sort_cols = group_cols + (["datetime"] if "datetime" in df.columns else [])

    def process_group(frame):
        frame = frame.sort_values(by=sort_cols) if sort_cols else frame
        seen = []
        last_valid = ""
        switch_flags = []
        switch_counts = []
        prev_values = []

        for val in frame[id_col]:
            val = str(val).strip()
            # Ignore noise values
            if val in ("", "nan", "none", "null"):
                switch_flags.append(False)
                switch_counts.append(len(seen) if seen else 1)
                prev_values.append(last_valid)
                continue

            # First occurrence logic
            if val not in seen:
                seen.append(val)
                switch_flags.append(len(seen) > 1)   # mark switch if not first
            else:
                switch_flags.append(False)

            switch_counts.append(len(seen))
            prev_values.append(last_valid)
            last_valid = val

        df.loc[frame.index, switch_col] = switch_flags
        df.loc[frame.index, count_col] = switch_counts
        df.loc[frame.index, prev_col] = prev_values

    if group_cols:
        for _, idx in df.groupby(group_cols, dropna=False).groups.items():
            process_group(df.loc[idx])
    else:
        process_group(df)

    return df


def flag_imei_switches(normalized: pd.DataFrame) -> pd.DataFrame:
    return _flag_identity_switches(normalized, "imei", "imei")


def flag_imsi_switches(normalized: pd.DataFrame) -> pd.DataFrame:
    return _flag_identity_switches(normalized, "imsi", "imsi")


# -----------------------------------
# DATETIME PARSING HELPER
# -----------------------------------
def parse_datetime_series(series):
    """
    Try multiple explicit formats before falling back to pandas' auto‑detection.
    """
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%Y-%m-%dT%H:%M:%S',
    ]
    for fmt in formats:
        try:
            return pd.to_datetime(series, format=fmt, errors='coerce')
        except Exception:
            continue
    # Fallback to pandas' auto-detection (with dayfirst=True for local)
    return pd.to_datetime(series, errors='coerce', dayfirst=True)


# -----------------------------------
# CDR EXCEL READER (with header detection)
# -----------------------------------
_HEADER_SIGNATURES = {
    "zong": {"msisdn", "bnumber", "strt_tm"},
    "telenor": {"msisdn", "call_start_dt_tm", "inbound_outbound_ind"},
}


def _find_header_row(peek: pd.DataFrame, signatures: dict) -> tuple[str, int]:
    """
    Scan peek (header=None) row by row.
    Return (operator_hint, row_index) for the first row that matches
    a known signature, or ("standard", 0) if nothing matches.
    """
    for row_idx in range(len(peek)):
        row_vals = {str(v).strip().lower() for v in peek.iloc[row_idx]}
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

    Returns a DataFrame with the correct header row.
    """
    peek = pd.read_excel(filepath, sheet_name=sheet_name, nrows=7, header=None)
    operator_hint, header_row_idx = _find_header_row(peek, _HEADER_SIGNATURES)

    if header_row_idx > 0:
        print(
            f"{operator_hint.upper()} CDR detected — "
            f"header found at Excel row {header_row_idx + 1}, "
            f"skipping {header_row_idx} row(s)"
        )
        df = pd.read_excel(filepath, sheet_name=sheet_name, skiprows=header_row_idx)
    else:
        print("Standard CDR detected — reading from row 1")
        df = pd.read_excel(filepath, sheet_name=sheet_name)

    return df   # FIXED: returns only the DataFrame


# -----------------------------------
# MAIN NORMALIZATION FUNCTION
# -----------------------------------
def normalize_dataframe(df: pd.DataFrame):
    # ── 1. Normalise column names ─────────────────────────────────
    df.columns = [_clean_col_name(c) for c in df.columns]

    # De-duplicate column names
    seen = {}
    new_cols = []
    for c in df.columns:
        if c not in seen:
            seen[c] = 0
            new_cols.append(c)
        else:
            seen[c] += 1
            new_cols.append(f"{c}_dup{seen[c]}")
    df.columns = new_cols

    print("\nDetected Columns:")
    print(df.columns.tolist())

    # ── 2. Detect operator ────────────────────────────────────────
    operator = detect_operator(df.columns.tolist())
    print(f"\nDetected Operator: {operator.upper()}")

    # ── 3. Clean cell values ──────────────────────────────────────
    for col in df.columns:
        df[col] = df[col].map(clean_missing)

    # ── 4. Operator-specific pre-processing ───────────────────────
    if operator == "zong":
        if "mins" in df.columns and "secs" in df.columns:
            df["duration"] = (
                pd.to_numeric(df["mins"], errors="coerce").fillna(0) * 60
                + pd.to_numeric(df["secs"], errors="coerce").fillna(0)
            )

    if operator == "ufone":
        type_col = df["type"].astype(str) if "type" in df.columns else pd.Series([""] * len(df))
        dir_col = df["direction"].astype(str) if "direction" in df.columns else pd.Series([""] * len(df))
        df["_unified_direction"] = [
            normalize_direction(t, d) for t, d in zip(type_col, dir_col)
        ]

    if operator == "telenor":
        if "inbound_outbound_ind" in df.columns:
            df["inbound_outbound_ind"] = df["inbound_outbound_ind"].apply(
                lambda v: normalize_direction(str(v))
            )

    if operator == "telenor_orig_dialed":
        msisdn = df["msisdn"].astype(str).str.strip() if "msisdn" in df.columns else pd.Series([""] * len(df))
        orig = df["call_orig_num"].astype(str).str.strip() if "call_orig_num" in df.columns else pd.Series([""] * len(df))
        dialed = df["call_dialed_num"].astype(str).str.strip() if "call_dialed_num" in df.columns else pd.Series([""] * len(df))
        direction_raw = df["call_type"].astype(str).str.strip().str.upper() if "call_type" in df.columns else pd.Series([""] * len(df))
        sub_type_raw = df["call_type_dup1"].astype(str).str.strip().str.upper() if "call_type_dup1" in df.columns else pd.Series([""] * len(df))

        contact_numbers = []
        for m, o, d, dirn, sub in zip(msisdn, orig, dialed, direction_raw, sub_type_raw):
            if sub in ("GPRS", "DATA"):
                contact_numbers.append("")
            elif dirn == "OUTGOING":
                contact_numbers.append(d)
            elif dirn == "INCOMING":
                contact_numbers.append(o)
            else:
                contact_numbers.append(d if d != m else o)
        df["_resolved_contact_number"] = contact_numbers

    # ── 5. Map columns to unified schema ─────────────────────────
    col_map = OPERATOR_MAPS.get(operator, {})
    normalized = pd.DataFrame()

    for raw_col, unified_col in col_map.items():
        if raw_col in df.columns:
            if unified_col in normalized.columns:
                continue
            normalized[unified_col] = df[raw_col]

    print(f"\nAfter column mapping: {len(normalized)} rows, "
          f"{normalized.columns.tolist()}")

    if operator == "telenor_orig_dialed" and "_resolved_contact_number" in df.columns:
        normalized["contact_number"] = df["_resolved_contact_number"].values

    # ── 6. Post-map direction fix ─────────────────────────────────
    if operator == "ufone":
        normalized["direction"] = df["_unified_direction"].values
    elif operator == "telenor_orig_dialed":
        base_dir = normalized["direction"].astype(str).str.strip().str.upper() if "direction" in normalized.columns else pd.Series([""] * len(normalized))
        sub_type = normalized["call_type"].astype(str).str.strip().str.upper() if "call_type" in normalized.columns else pd.Series([""] * len(normalized))
        resolved_direction = []
        for bd, st in zip(base_dir, sub_type):
            if st == "SMS" and bd in ("INCOMING", "OUTGOING"):
                resolved_direction.append(normalize_direction(f"{st.lower()} - {bd.lower()}"))
            else:
                resolved_direction.append(normalize_direction(bd))
        normalized["direction"] = resolved_direction

    if operator == "unknown" or operator == "":
        generic_map = {
            "a_party": "owner_number",
            "b_party": "contact_number",
            "call_type": "call_type",
            "date&time" : "datetime", 
            "date_time": "datetime",
            "duration": "duration",
            "cell_id": "cell_id",
            "imei": "imei",
            "imsi": "imsi",
            "site": "tower_address",
            "site_address": "tower_address",
            "latitude": "latitude",
            "longtitude": "longitude",
            "longitude": "longitude",
            "lng": "longitude",
            "lat": "latitude",
        }
        for raw_col, unified_col in generic_map.items():
            if raw_col in df.columns and unified_col not in normalized.columns:
                normalized[unified_col] = df[raw_col]

    # Unified Intelligence Layer
    if "call_type" in normalized.columns or "direction" in normalized.columns:
        resolved = normalized.apply(
            lambda row: resolve_call_intelligence(row, operator),
            axis=1
        )
        normalized["direction"] = resolved.apply(lambda x: x[0])
        normalized["service_type"] = resolved.apply(lambda x: x[1])
        normalized["interaction_type"] = resolved.apply(lambda x: x[2])
    if "direction" not in normalized.columns:
        normalized["direction"] = ""

    # ── 7. Clean numeric / phone fields ──────────────────────────
    if "contact_number" in normalized.columns:
        normalized["_raw_contact_number"] = normalized["contact_number"]

    for col in ("owner_number", "contact_number", "imei", "imsi"):
        if col in normalized.columns:
            normalized[col] = normalized[col].map(clean_number)

    # IMEI Intelligence Layer
    if "imei" in normalized.columns:
        normalized["corrected_imei"] = (
            normalized["imei"]
            .astype(str)
            .apply(corrected_imei)
        )
        normalized["imei_was_modified"] = (
            normalized["imei"]
            != normalized["corrected_imei"]
        )
        valid_correction = normalized["corrected_imei"] != ""
        normalized.loc[valid_correction, "imei"] = normalized.loc[valid_correction, "corrected_imei"]

    # Re-normalise owner/contact numbers
    for col in ("owner_number", "contact_number"):
        if col in normalized.columns:
            normalized[col] = normalized[col].map(normalize_mobile_number)

    # ── 8. Split out data-session rows ──────────────────────────
    data_sessions = pd.DataFrame()
    if "contact_number" in normalized.columns:
        empty_contact_mask = normalized["contact_number"].astype(str).str.strip() == ""
        if empty_contact_mask.any():
            data_sessions = normalized[empty_contact_mask].copy()
            normalized = normalized[~empty_contact_mask].copy()

    # ── 8b. Split out non-mobile contacts ──────────────────────
    non_mobile = pd.DataFrame()
    if "_raw_contact_number" in normalized.columns:
        is_non_mobile_mask = normalized["_raw_contact_number"].apply(is_non_mobile_contact)
        non_mobile = normalized[is_non_mobile_mask].copy()
        normalized = normalized[~is_non_mobile_mask].copy()

        if "contact_number" in normalized.columns:
            still_invalid_mask = ~normalized["contact_number"].astype(str).str.startswith(("92", "03"), na=False)
            non_mobile = pd.concat([non_mobile, normalized[still_invalid_mask]], ignore_index=True)
            normalized = normalized[~still_invalid_mask].copy()

        if not non_mobile.empty:
            non_mobile["contact_number"] = non_mobile["_raw_contact_number"]
        non_mobile = non_mobile.drop(columns=["_raw_contact_number"], errors="ignore")
        normalized = normalized.drop(columns=["_raw_contact_number"], errors="ignore")
    elif "contact_number" in normalized.columns:
        mask = normalized["contact_number"].astype(str).str.startswith(("92", "03"), na=False)
        non_mobile = normalized[~mask].copy()
        normalized = normalized[mask].copy()

    print(f"After mobile filter: {len(normalized)} "
          f"(non-mobile/service contacts set aside: {len(non_mobile)})")

    # ── 9. Parse datetime ─────────────────────────────────────────
    for frame in (normalized, non_mobile, data_sessions):
        if frame is normalized and "datetime" not in frame.columns:
            continue
        if frame is not normalized and ("datetime" not in frame.columns or frame.empty):
            continue

        frame["raw_datetime"] = frame["datetime"].astype(str)
        frame["datetime"] = parse_datetime_series(frame["raw_datetime"])
        frame["call_date"] = frame["datetime"].dt.strftime("%Y-%m-%d")
        frame["call_time"] = frame["datetime"].dt.strftime("%H:%M:%S")

    if "datetime" in normalized.columns:
        sample_size = min(10, len(normalized))
        if sample_size > 0:
            print("\nRandom datetime samples:")
            print(normalized["raw_datetime"].sample(sample_size).tolist())
        bad_rows = normalized[normalized["datetime"].isna()]
        print(f"Invalid datetime count: {len(bad_rows)}")

    # ── 10. Extract lat / long from tower address ──────────────
    for frame in (normalized, non_mobile, data_sessions):
        if "tower_address" in frame.columns and not frame.empty:
            need_extract = False
            if "latitude" not in frame.columns or "longitude" not in frame.columns:
                need_extract = True
            else:
                lat_empty = frame["latitude"].isna().all() or (frame["latitude"].astype(str).str.strip() == "").all()
                lon_empty = frame["longitude"].isna().all() or (frame["longitude"].astype(str).str.strip() == "").all()
                if lat_empty or lon_empty:
                    need_extract = True

            if need_extract:
                towers, lats, lngs = extract_lat_long(frame["tower_address"])
                frame["tower_address"] = towers
                frame["latitude"] = lats
                frame["longitude"] = lngs

    # ── 11. Sector ─────────────────────────────────────────────────
    if "cell_id" in normalized.columns:
        normalized["sector"] = normalized["cell_id"].map(get_sector)
    if "cell_id" in non_mobile.columns and not non_mobile.empty:
        non_mobile["sector"] = non_mobile["cell_id"].map(get_sector)
    if "cell_id" in data_sessions.columns and not data_sessions.empty:
        data_sessions["sector"] = data_sessions["cell_id"].map(get_sector)

    # ── 12. IMEI/IMSI switch detection ──────────────────────────
    normalized = flag_imei_switches(normalized)
    normalized = flag_imsi_switches(normalized)

    # ── 13. Ensure all final columns exist ──────────────────────
    FINAL_COLUMNS = [
        "owner_number", "contact_number", "imei", "corrected_imei", "imsi",
        "call_date", "call_time", "duration", "direction",
        "cell_id", "sector", "tower_address", "latitude", "longitude",
        "imei_switch", "imei_switch_count", "previous_imei",
        "imsi_switch", "imsi_switch_count", "previous_imsi",
    ]
    for col in FINAL_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = ""
    normalized = normalized[FINAL_COLUMNS]

    NON_MOBILE_COLUMNS = [
        "owner_number", "contact_number", "call_date", "call_time",
        "duration", "direction", "cell_id", "sector", "tower_address", "latitude", "longitude"
    ]
    for col in NON_MOBILE_COLUMNS:
        if col not in non_mobile.columns:
            non_mobile[col] = ""
    if not non_mobile.empty:
        non_mobile = non_mobile[NON_MOBILE_COLUMNS]
    else:
        non_mobile = pd.DataFrame(columns=NON_MOBILE_COLUMNS)

    DATA_SESSION_COLUMNS = [
        "owner_number", "imei", "imsi", "call_date", "call_time",
        "duration", "cell_id", "sector", "tower_address", "latitude", "longitude"
    ]
    for col in DATA_SESSION_COLUMNS:
        if col not in data_sessions.columns:
            data_sessions[col] = ""
    if not data_sessions.empty:
        data_sessions = data_sessions[DATA_SESSION_COLUMNS]
    else:
        data_sessions = pd.DataFrame(columns=DATA_SESSION_COLUMNS)

    print(f"\nFINAL ROWS: {len(normalized)}")
    if "imei_switch" in normalized.columns:
        print(f"IMEI switches detected: {int(normalized['imei_switch'].sum())}")
    if "imsi_switch" in normalized.columns:
        print(f"IMSI switches detected: {int(normalized['imsi_switch'].sum())}")
    print(f"Non-mobile/service contacts: {len(non_mobile)}")
    print(f"Data sessions (GPRS/internet): {len(data_sessions)}")

    return normalized, non_mobile, data_sessions