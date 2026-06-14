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
# "direction" is optional — some Ufone exports only have "type" (no
# separate Direction column). Match on the columns that are always
# present, then handle "direction" as optional downstream.
_UFONE_COLS       = {"a_number", "b_number", "start_time", "end_time", "type"}
_TELENOR_COLS     = {"msisdn", "b_party", "call_start_dt_tm",
                     "inbound_outbound_ind", "call_network_volume"}

# Variant seen on some CDRs: instead of B PARTY + INBOUND_OUTBOUND_IND,
# the file provides CALL_ORIG_NUM / CALL_DIALED_NUM and the direction
# is carried in CALL_TYPE (OUTGOING/INCOMING). MSISDN is always the
# A-party (owner); the B-party is whichever of orig/dialed is NOT the
# MSISDN, selected based on direction.
_TELENOR_ORIG_DIALED_COLS = {"msisdn", "call_orig_num", "call_dialed_num",
                              "call_start_dt_tm", "call_network_volume"}


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

    if _TELENOR_ORIG_DIALED_COLS.issubset(col_set):
        return "telenor_orig_dialed"

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

_MAP_TELENOR_ORIG_DIALED = {
    "msisdn":                "owner_number",
    # contact_number is resolved separately based on call_type direction
    "imsi":                  "imsi",
    "imei":                  "imei",
    "call_start_dt_tm":      "datetime",
    "call_type":             "direction",          # OUTGOING / INCOMING
    "call_network_volume":   "duration",
    "cell_site_id":          "cell_id",
    "lat":                   "latitude",
    "longitude":             "longitude",
    "location":              "tower_address",
    "call_type_dup1":        "call_type",          # GSM / SMS / DATA etc.
}

OPERATOR_MAPS = {
    "jazz":     _MAP_JAZZ,
    "jazz_old": _MAP_JAZZ_OLD,
    "warid":    _MAP_WARID,
    "zong":     _MAP_ZONG,
    "ufone":    _MAP_UFONE,
    "telenor":  _MAP_TELENOR,
    "telenor_orig_dialed": _MAP_TELENOR_ORIG_DIALED,
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
# NORMALIZE MOBILE NUMBER FORMAT
# -----------------------------------

def normalize_mobile_number(value: str) -> str:
    """
    Standardise mobile numbers to the '92XXXXXXXXXX' (12-digit) format.

    Handles:
      - '03XXXXXXXXX'  (11 digits, leading 0)        -> '92XXXXXXXXXX'
      - '3XXXXXXXXX'   (10 digits, missing leading 0,
                        seen in some Zong exports)    -> '92XXXXXXXXXX'
      - '92XXXXXXXXXX' (already 12 digits)            -> unchanged
      - anything else (shortcodes, hex, text)         -> unchanged
    """
    val = str(value).strip()
    if not val.isdigit():
        return val

    if val.startswith("92") and len(val) == 12:
        return val
    if val.startswith("03") and len(val) == 11:
        return "92" + val[1:]
    if val.startswith("3") and len(val) == 10:
        return "92" + val

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

    A normal mobile number (raw) is digits-only (possibly with a
    leading '+') and either:
      - starts with '92' or '03', OR
      - is exactly 10 digits starting with '3' (some Zong exports
        drop the leading '0', e.g. '3001234567')
    """
    raw = str(value).strip()
    if not raw:
        return False

    digits_only = raw.lstrip("+")
    if not digits_only.isdigit():
        return True

    if digits_only.startswith(("92", "03")):
        return False

    # 10-digit numbers starting with '3' (missing leading 0): treat as mobile
    if len(digits_only) == 10 and digits_only.startswith("3"):
        return False

    return True


# -----------------------------------
# IMEI-SWITCH DETECTION
# -----------------------------------

# -----------------------------------
# IMEI / IMSI SWITCH DETECTION
# -----------------------------------

def _flag_identity_switches(normalized: pd.DataFrame, id_col: str, prefix: str) -> pd.DataFrame:
    """
    Generic handset/SIM-swap detector.

    Within each owner_number group (sorted by datetime), flag rows
    where the value in `id_col` (e.g. 'imei' or 'imsi') differs from
    the value used in the previous row for that owner.

    Adds three columns (named using `prefix`, e.g. 'imei' / 'imsi'):
      - {prefix}_switch       : bool, True when a new value first
                                appears (excluding the first row)
      - {prefix}_switch_count : int, running count of distinct
                                values seen so far (1-based)
      - previous_{prefix}     : str, the value used immediately
                                before this row (chronologically)

    Always groups by 'owner_number' only (never by `id_col` itself —
    grouping by the identity field being tracked would defeat the
    purpose, e.g. when id_col == 'imsi').

    Safe no-op if `id_col` or 'datetime' columns are missing/empty.
    """
    switch_col  = f"{prefix}_switch"
    count_col   = f"{prefix}_switch_count"
    prev_col    = f"previous_{prefix}"

    if id_col not in normalized.columns or normalized.empty:
        normalized[switch_col] = False
        normalized[count_col]  = 1
        normalized[prev_col]   = ""
        return normalized

    normalized = normalized.copy()
    normalized[switch_col] = False
    normalized[count_col]  = 1
    normalized[prev_col]   = ""

    group_cols = []
    if "owner_number" in normalized.columns:
        group_cols.append("owner_number")

    sort_cols = group_cols + (["datetime"] if "datetime" in normalized.columns else [])

    def _process(frame_idx, frame):
        seen_vals = []
        switch_flags = []
        switch_counts = []
        previous_vals = []
        last_val = ""
        for val in frame[id_col]:
            val = str(val).strip()
            if val and val not in seen_vals:
                seen_vals.append(val)
                switch_flags.append(len(seen_vals) > 1)
            else:
                switch_flags.append(False)
            switch_counts.append(max(len(seen_vals), 1))
            previous_vals.append(last_val)
            if val:
                last_val = val

        normalized.loc[frame_idx, switch_col] = switch_flags
        normalized.loc[frame_idx, count_col]  = switch_counts
        normalized.loc[frame_idx, prev_col]   = previous_vals

    if not group_cols:
        # No grouping key — treat whole frame as one group
        ordered = normalized.sort_values(by=sort_cols) if sort_cols else normalized
        _process(ordered.index, ordered)
        return normalized

    for _, group_idx in normalized.groupby(group_cols, dropna=False).groups.items():
        group = normalized.loc[group_idx]
        if sort_cols and "datetime" in normalized.columns:
            group = group.sort_values(by="datetime")
        _process(group.index, group)

    return normalized


def flag_imei_switches(normalized: pd.DataFrame) -> pd.DataFrame:
    """Detect handset (IMEI) changes for the CDR owner. See
    _flag_identity_switches for column details (imei_switch,
    imei_switch_count, previous_imei)."""
    return _flag_identity_switches(normalized, "imei", "imei")


def flag_imsi_switches(normalized: pd.DataFrame) -> pd.DataFrame:
    """Detect SIM (IMSI) changes for the CDR owner. See
    _flag_identity_switches for column details (imsi_switch,
    imsi_switch_count, previous_imsi)."""
    return _flag_identity_switches(normalized, "imsi", "imsi")


# -----------------------------------
# NORMALIZE DATAFRAME  (main entry point)
# -----------------------------------

def normalize_dataframe(df: pd.DataFrame):
    """
    Returns a tuple: (normalized_df, non_mobile_contacts_df)

      normalized_df          : the standard 13(+)-column unified CDR,
                                with mobile contacts only (as before),
                                plus new imei_switch / imei_switch_count
                                columns.
      non_mobile_contacts_df : rows whose contact_number (raw, before
                                clean_number) was NOT a normal mobile
                                number — e.g. hex-encoded SMS sender
                                IDs, bank/service short codes. These
                                are excluded from the main analysis
                                but kept for review (financial /
                                service profiling).
    """

    # ── 1. Normalise column names ─────────────────────────────────
    df.columns = [_clean_col_name(c) for c in df.columns]

    # De-duplicate column names (e.g. 'CALL TYPE' and 'CALL_TYPE' both
    # clean to 'call_type'). Keep the first occurrence, drop later
    # duplicates by suffixing with _dupN so they don't collide.
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

    # Telenor (orig/dialed variant): resolve contact_number using
    # MSISDN as A-party. B-party is whichever of CALL_ORIG_NUM /
    # CALL_DIALED_NUM is NOT the MSISDN, chosen by direction:
    #   OUTGOING -> contact = call_dialed_num
    #   INCOMING -> contact = call_orig_num
    # Falls back to "the field that differs from MSISDN" if the
    # direction value is unrecognised.
    if operator == "telenor_orig_dialed":
        msisdn = df["msisdn"].astype(str).str.strip() if "msisdn" in df.columns else pd.Series([""] * len(df))
        orig   = df["call_orig_num"].astype(str).str.strip()   if "call_orig_num"   in df.columns else pd.Series([""] * len(df))
        dialed = df["call_dialed_num"].astype(str).str.strip() if "call_dialed_num" in df.columns else pd.Series([""] * len(df))
        direction_raw = df["call_type"].astype(str).str.strip().str.upper() if "call_type" in df.columns else pd.Series([""] * len(df))
        sub_type_raw  = df["call_type_dup1"].astype(str).str.strip().str.upper() if "call_type_dup1" in df.columns else pd.Series([""] * len(df))

        contact_numbers = []
        for m, o, d, dirn, sub in zip(msisdn, orig, dialed, direction_raw, sub_type_raw):
            if sub in ("GPRS", "DATA"):
                # Data/internet session — no real B-party
                contact_numbers.append("")
            elif dirn == "OUTGOING":
                contact_numbers.append(d)
            elif dirn == "INCOMING":
                contact_numbers.append(o)
            else:
                # Unknown direction: pick whichever field differs from MSISDN
                contact_numbers.append(d if d != m else o)

        df["_resolved_contact_number"] = contact_numbers

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

    # Telenor (orig/dialed variant): plug in the resolved contact number
    if operator == "telenor_orig_dialed" and "_resolved_contact_number" in df.columns:
        normalized["contact_number"] = df["_resolved_contact_number"].values

    # ── 6. Post-map direction fix ─────────────────────────────────
    if operator == "ufone":
        normalized["direction"] = df["_unified_direction"].values
    elif operator == "telenor_orig_dialed":
        # 'direction' currently holds raw OUTGOING/INCOMING (from CALL_TYPE)
        # 'call_type' (from CALL_TYPE dup) holds GSM/SMS/DATA etc.
        base_dir = normalized["direction"].astype(str).str.strip().str.upper()
        sub_type = normalized["call_type"].astype(str).str.strip().str.upper() if "call_type" in normalized.columns else pd.Series([""] * len(normalized))

        resolved_direction = []
        for bd, st in zip(base_dir, sub_type):
            if st == "SMS" and bd in ("INCOMING", "OUTGOING"):
                resolved_direction.append(normalize_direction(f"{st.lower()} - {bd.lower()}"))
            else:
                resolved_direction.append(normalize_direction(bd))
        normalized["direction"] = resolved_direction
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
    # Keep a raw copy of contact_number BEFORE clean_number strips
    # non-digit characters, so we can detect hex/alpha sender IDs.
    if "contact_number" in normalized.columns:
        normalized["_raw_contact_number"] = normalized["contact_number"]

    for col in ("owner_number", "contact_number", "imei", "imsi"):
        if col in normalized.columns:
            normalized[col] = normalized[col].map(clean_number)

    # Re-normalise owner/contact numbers into the 92XXXXXXXXXX format
    # (handles 03XXXXXXXXX and 10-digit-no-leading-zero variants)
    for col in ("owner_number", "contact_number"):
        if col in normalized.columns:
            normalized[col] = normalized[col].map(normalize_mobile_number)

    # ── 8. Split out data-session rows (no real B-party) ───────────
    # Some Telenor (orig/dialed) files contain GPRS/internet rows with
    # contact_number resolved to "" — these aren't calls/SMS to another
    # party, keep them separate.
    data_sessions = pd.DataFrame()
    if "contact_number" in normalized.columns:
        empty_contact_mask = normalized["contact_number"].astype(str).str.strip() == ""
        if empty_contact_mask.any():
            data_sessions = normalized[empty_contact_mask].copy()
            normalized = normalized[~empty_contact_mask].copy()

    # ── 8b. Split out non-mobile contacts (hex/service sender IDs) ──
    non_mobile = pd.DataFrame()
    if "_raw_contact_number" in normalized.columns:
        is_non_mobile_mask = normalized["_raw_contact_number"].apply(is_non_mobile_contact)

        non_mobile = normalized[is_non_mobile_mask].copy()
        normalized = normalized[~is_non_mobile_mask].copy()

        # Also catch rows where contact_number simply doesn't start
        # with 92/03 after cleaning (covers cases the raw check missed)
        if "contact_number" in normalized.columns:
            still_invalid_mask = ~normalized["contact_number"].astype(str).str.startswith(("92", "03"), na=False)
            non_mobile = pd.concat([non_mobile, normalized[still_invalid_mask]], ignore_index=True)
            normalized = normalized[~still_invalid_mask].copy()

        # Restore the human-readable sender/contact identifier for the
        # non-mobile frame, then drop the helper column from both frames
        if not non_mobile.empty:
            non_mobile["contact_number"] = non_mobile["_raw_contact_number"]
        non_mobile = non_mobile.drop(columns=["_raw_contact_number"], errors="ignore")
        normalized = normalized.drop(columns=["_raw_contact_number"], errors="ignore")
    elif "contact_number" in normalized.columns:
        # Fallback to original behaviour if contact_number was never present
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
        frame["datetime"] = pd.to_datetime(
            frame["raw_datetime"],
            errors="coerce",
            dayfirst=False,
            format="mixed",
        )
        frame["call_date"] = frame["datetime"].dt.strftime("%Y-%m-%d")
        frame["call_time"] = frame["datetime"].dt.strftime("%H:%M:%S")

    if "datetime" in normalized.columns:
        sample_size = min(10, len(normalized))
        if sample_size > 0:
            print("\nRandom datetime samples:")
            print(normalized["raw_datetime"].sample(sample_size).tolist())

        bad_rows = normalized[normalized["datetime"].isna()]
        print(f"\nInvalid datetime count: {len(bad_rows)}")

    # ── 10. Extract lat / long from tower address ──────────────────
    for frame in (normalized, non_mobile, data_sessions):
        if "tower_address" in frame.columns and not frame.empty:
            if (
                "latitude"  not in frame.columns
                or "longitude" not in frame.columns
            ):
                towers, lats, lngs = extract_lat_long(frame["tower_address"])
                frame["tower_address"] = towers
                frame["latitude"]      = lats
                frame["longitude"]     = lngs

    # ── 11. Sector ───────────────────────────────────────────────────
    if "cell_id" in normalized.columns:
        normalized["sector"] = normalized["cell_id"].map(get_sector)
    if "cell_id" in non_mobile.columns and not non_mobile.empty:
        non_mobile["sector"] = non_mobile["cell_id"].map(get_sector)
    if "cell_id" in data_sessions.columns and not data_sessions.empty:
        data_sessions["sector"] = data_sessions["cell_id"].map(get_sector)

    # ── 11.5. IMEI-switch detection ──────────────────────────────────
    normalized = flag_imei_switches(normalized)
    normalized = flag_imsi_switches(normalized)

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
        "imei_switch",
        "imei_switch_count",
        "previous_imei",
        "imsi_switch",
        "imsi_switch_count",
        "previous_imsi",
    ]

    # Add missing columns as empty strings so downstream code
    # always receives a consistent schema
    for col in FINAL_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = ""

    normalized = normalized[FINAL_COLUMNS]

    # non_mobile frame keeps a simplified schema (no imei_switch cols —
    # not meaningful for service/sender IDs)
    NON_MOBILE_COLUMNS = [
        "owner_number",
        "contact_number",   # original sender ID / hex string / short code
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
    for col in NON_MOBILE_COLUMNS:
        if col not in non_mobile.columns:
            non_mobile[col] = ""
    if not non_mobile.empty:
        non_mobile = non_mobile[NON_MOBILE_COLUMNS]
    else:
        non_mobile = pd.DataFrame(columns=NON_MOBILE_COLUMNS)

    # data_sessions: GPRS/internet rows — no contact_number, but keep
    # cell/tower/time info for location-history purposes
    DATA_SESSION_COLUMNS = [
        "owner_number",
        "imei",
        "imsi",
        "call_date",
        "call_time",
        "duration",
        "cell_id",
        "sector",
        "tower_address",
        "latitude",
        "longitude",
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
        normalized, non_mobile = normalize_dataframe(df)
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