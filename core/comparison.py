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

    def classify(g):
        if g <= 2:   return "VERY HIGH"
        if g <= 5:   return "HIGH"
        if g <= 10:  return "MEDIUM"
        return "LOW"

    merged["confidence"] = merged["gap_min"].apply(classify)

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