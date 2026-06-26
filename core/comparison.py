# comparison.py

import pandas as pd


# -----------------------------------
# SAME TOWER SAME TIME
# -----------------------------------
def same_tower_same_time(
    df1,
    df2,
    minute_window=15
):
    required_columns = ["tower_address", "call_date", "call_time"]
    for col in required_columns:
        if col not in df1.columns or col not in df2.columns:
            return []

    temp1 = df1.copy()
    temp2 = df2.copy()

    temp1["datetime"] = pd.to_datetime(
        temp1["call_date"] + " " + temp1["call_time"], errors="coerce"
    )
    temp2["datetime"] = pd.to_datetime(
        temp2["call_date"] + " " + temp2["call_time"], errors="coerce"
    )

    temp1 = temp1.dropna(subset=["datetime"])
    temp2 = temp2.dropna(subset=["datetime"])

    # Normalise join keys
    temp1["_tower"] = temp1["tower_address"].astype(str).str.strip()
    temp2["_tower"] = temp2["tower_address"].astype(str).str.strip()

    if "sector" in temp1.columns and "sector" in temp2.columns:
        temp1["_sector"] = temp1["sector"].astype(str).str.strip()
        temp2["_sector"] = temp2["sector"].astype(str).str.strip()
        join_keys = ["_tower", "_sector"]
    else:
        join_keys = ["_tower"]

    # Merge on tower (+ sector) — reduces candidates from n*m to a small subset
    merged = temp1.merge(temp2, on=join_keys, suffixes=("_1", "_2"))

    if merged.empty:
        return []

    # Vectorised time-gap calculation
    merged["gap_min"] = (
        (merged["datetime_1"] - merged["datetime_2"]).abs().dt.total_seconds() / 60
    )

    merged = merged[merged["gap_min"] <= minute_window]

    if merged.empty:
        return []

    if "direction" in df1.columns and "direction" in df2.columns:
        # We have direction info; we can boost/downgrade confidence
        merged["dir1"] = merged["direction_1"].astype(str).str.upper().str.strip()
        merged["dir2"] = merged["direction_2"].astype(str).str.upper().str.strip()
        # Outgoing calls are more likely to indicate a meeting (both initiated)
        merged["both_outgoing"] = (merged["dir1"] == "OUTGOING") & (merged["dir2"] == "OUTGOING")
        # One outgoing, one incoming – less likely
        merged["mixed"] = (merged["dir1"] != merged["dir2"]) & (merged["dir1"] != "") & (merged["dir2"] != "")
    else:
        merged["both_outgoing"] = False
        merged["mixed"] = False

    def classify(row):
            gap = row["gap_min"]
            base = "LOW"
            if gap <= 2:   base = "VERY HIGH"
            elif gap <= 5: base = "HIGH"
            elif gap <= 10: base = "MEDIUM"
            # Adjust if both outgoing -> boost one level
            if row["both_outgoing"]:
                if base == "VERY HIGH": return "VERY HIGH"  # already max
                if base == "HIGH": return "VERY HIGH"
                if base == "MEDIUM": return "HIGH"
                if base == "LOW": return "MEDIUM"
            # If mixed, downgrade one level
            if row["mixed"]:
                if base == "VERY HIGH": return "HIGH"
                if base == "HIGH": return "MEDIUM"
                if base == "MEDIUM": return "LOW"
                # LOW stays LOW
            return base

    merged["confidence"] = merged.apply(classify, axis=1)


    lat_col = "latitude_1" if "latitude_1" in merged.columns else "latitude"
    lon_col = "longitude_1" if "longitude_1" in merged.columns else "longitude"

    results = []
    for _, row in merged.iterrows():
        results.append({
            "tower":            row["tower_address_1"] if "tower_address_1" in row else row["_tower"],
            "cdr_1_time":       str(row["datetime_1"]),
            "cdr_2_time":       str(row["datetime_2"]),
            "time_gap_minutes": round(row["gap_min"], 2),
            "latitude":         row.get(lat_col, ""),
            "longitude":        row.get(lon_col, ""),
            "sector":           row.get("_sector", row.get("sector_1", "")),
            "confidence":       row["confidence"],
        })

    return results


# -----------------------------------
# COMMON CONTACTS
# -----------------------------------
def common_contacts(df1, df2):

    if (
        "contact_number" not in df1.columns
        or
        "contact_number" not in df2.columns
    ):
        return []

    contacts_1 = set(
        df1["contact_number"]
        .dropna()
        .astype(str)
    )

    contacts_2 = set(
        df2["contact_number"]
        .dropna()
        .astype(str)
    )

    common = contacts_1.intersection(
        contacts_2
    )

    return list(common)

# -----------------------------------
# CROSS-SUSPECT TIMELINE OVERLAY
# -----------------------------------
def cross_suspect_timeline(df1, df2, subject1_label="Subject A", subject2_label="Subject B"):
    """
    Merges both CDRs into a single chronological event list.
    Each event carries: datetime, subject label, call type/direction,
    contact number, tower, and a 'meeting_flag' if the other subject
    was at the same tower within 15 minutes.
    Returns a list of dicts sorted by datetime ascending.
    """
    required = ["call_date", "call_time", "contact_number", "tower_address"]
    for col in required:
        if col not in df1.columns or col not in df2.columns:
            return []

    def prep(df, label):
        t = df.copy()
        t["datetime"] = pd.to_datetime(
            t["call_date"] + " " + t["call_time"], errors="coerce"
        )
        t = t.dropna(subset=["datetime"]).sort_values("datetime")
        t["subject"] = label
        return t

    t1 = prep(df1, subject1_label)
    t2 = prep(df2, subject2_label)

    # Build a set of (tower, minute-bucket) for each subject
    # so we can flag proximity cheaply with a 15-min window
    def tower_minute_set(df, window_min=15):
        result = set()
        for _, row in df.iterrows():
            tower = str(row["tower_address"]).strip()
            ts = row["datetime"]
            for offset in range(-window_min, window_min + 1, 1):
                bucket = (tower, ts.floor("min") + pd.Timedelta(minutes=offset))
                result.add(bucket)
        return result

    set1 = tower_minute_set(t1)
    set2 = tower_minute_set(t2)

    def build_events(df, other_set, label):
        events = []
        for _, row in df.iterrows():
            tower = str(row["tower_address"]).strip()
            ts = row["datetime"]
            bucket = (tower, ts.floor("min"))
            proximity = bucket in other_set

            events.append({
                "datetime":      ts.strftime("%Y-%m-%d %H:%M:%S"),
                "date":          ts.strftime("%Y-%m-%d"),
                "time":          ts.strftime("%H:%M"),
                "subject":       label,
                "direction":     str(row.get("direction", "")).upper(),
                "call_type":     str(row.get("call_type", "VOICE")).upper(),
                "contact":       str(row.get("contact_number", "")),
                "tower":         tower,
                "latitude":      row.get("latitude", ""),
                "longitude":     row.get("longitude", ""),
                "duration":      row.get("duration", 0),
                "proximity_flag": proximity,   # True = other subject nearby
            })
        return events

    events1 = build_events(t1, set2, subject1_label)
    events2 = build_events(t2, set1, subject2_label)

    merged = sorted(events1 + events2, key=lambda x: x["datetime"])
    return merged