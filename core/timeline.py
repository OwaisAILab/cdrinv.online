# timeline.py

import pandas as pd

SILENT_PERIOD_HOURS = 4
# -----------------------------------
# FORMAT DURATION
# -----------------------------------

def format_duration(seconds):
    try:
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:02}"
    except:
        return "00:00:00"
# -----------------------------------
# IMEI SWITCH TIMELINE
# -----------------------------------
def imei_switch_timeline(df):
    """
    Returns a list of handset-change events for the CDR owner, based
    on the imei_switch flag added by normalizer.flag_imei_switches().

    Each entry includes the date/time of the switch, the new IMEI,
    and the IMEI used immediately before (when available).
    """

    if "imei_switch" not in df.columns:
        return []

    temp = df.copy()

    flagged = temp[temp["imei_switch"] == True]

    if len(flagged) == 0:
        return []

    results = []

    for idx, row in flagged.iterrows():

        results.append({
            "call_date":     row.get("call_date", ""),
            "call_time":     row.get("call_time", ""),
            "new_imei":      str(row.get("imei", "")),
            "previous_imei": str(row.get("previous_imei", "")),
            "imei_switch_count": int(row.get("imei_switch_count", 0)),
        })

    return results


# -----------------------------------
# NON-MOBILE CONTACT SUMMARY
# -----------------------------------
def non_mobile_summary(non_mobile_df):
    """
    Summarises the non-mobile/service contacts frame (hex-encoded
    SMS sender IDs, bank/service short codes, etc.) returned as the
    second element of normalize_dataframe().

    Groups by contact_number (the original sender identifier),
    counting occurrences and total duration, sorted by frequency.
    """

    if non_mobile_df is None or len(non_mobile_df) == 0:
        return []

    if "contact_number" not in non_mobile_df.columns:
        return []

    temp = non_mobile_df.copy()

    temp["duration"] = pd.to_numeric(
        temp["duration"],
        errors="coerce"
    ).fillna(0) if "duration" in temp.columns else 0

    grouped = (
        temp.groupby("contact_number")
        .agg(
            occurrences=("contact_number", "count"),
            total_duration=("duration", "sum") if "duration" in temp.columns else ("contact_number", "count")
        )
        .reset_index()
    )

    grouped = grouped.sort_values(
        by="occurrences",
        ascending=False
    )

    return grouped.head(30).to_dict(orient="records")


# -----------------------------------
# IMSI SWITCH TIMELINE
# -----------------------------------
def imsi_switch_timeline(df):
    """
    Returns a list of SIM-change events for the CDR owner, based on
    the imsi_switch flag added by normalizer.flag_imsi_switches().

    Each entry includes the date/time of the switch, the new IMSI,
    and the IMSI used immediately before (when available).
    """

    if "imsi_switch" not in df.columns:
        return []

    temp = df.copy()

    flagged = temp[temp["imsi_switch"] == True]

    if len(flagged) == 0:
        return []

    results = []

    for idx, row in flagged.iterrows():

        results.append({
            "call_date":     row.get("call_date", ""),
            "call_time":     row.get("call_time", ""),
            "new_imsi":      str(row.get("imsi", "")),
            "previous_imsi": str(row.get("previous_imsi", "")),
            "imsi_switch_count": int(row.get("imsi_switch_count", 0)),
        })

    return results


# -----------------------------------
# MOST CONTACTED
# -----------------------------------
def most_contacted(df):

    if "contact_number" not in df.columns:
        return []

    temp = df.copy()

    temp["duration"] = pd.to_numeric(
        temp["duration"],
        errors="coerce"
    ).fillna(0)

    grouped = (
        temp.groupby("contact_number")
        .agg(
            total_calls=(
                "contact_number",
                "count"
            ),
            total_duration=(
                "duration",
                "sum"
            )
        )
        .reset_index()
    )

    grouped["total_duration"] = (
        grouped["total_duration"]
        .map(format_duration)
    )

    grouped = grouped.sort_values(
        by="total_calls",
        ascending=False
    )

    return grouped.head(20).to_dict(
        orient="records"
    )


# -----------------------------------
# CONTACT TIMELINE
# -----------------------------------
def contact_timeline(df):

    return []


# -----------------------------------
# HOURLY ACTIVITY
# -----------------------------------
def hourly_activity(df):

    if "call_time" not in df.columns:
        return []

    temp = df.copy()

    temp["hour"] = (
        temp["call_time"]
        .str.slice(0, 2)
    )

    activity = (
        temp["hour"]
        .value_counts()
        .sort_index()
        .reset_index()
    )

    activity.columns = [
        "hour",
        "activity_count"
    ]

    return activity.to_dict(
        orient="records"
    )


# -----------------------------------
# FREQUENT TOWERS
# -----------------------------------
def frequent_towers(df):

    if "tower_address" not in df.columns:
        return []

    towers = (
        df["tower_address"]
        .value_counts()
        .reset_index()
    )

    towers.columns = [
        "tower",
        "visits"
    ]

    return towers.head(20).to_dict(
        orient="records"
    )


# -----------------------------------
# DIRECTION ANALYSIS
# -----------------------------------
def direction_analysis(df):

    if "direction" not in df.columns:
        return {}

    incoming = len(
        df[df["direction"] == "INCOMING"]
    )

    outgoing = len(
        df[df["direction"] == "OUTGOING"]
    )

    return {
        "incoming_calls": incoming,
        "outgoing_calls": outgoing
    }


# -----------------------------------
# NIGHT ACTIVITY
# -----------------------------------
def night_activity(df):

    if "call_time" not in df.columns:
        return []

    temp = df.copy()

    temp["hour"] = (
        temp["call_time"]
        .str.slice(0, 2)
        .astype(int)
    )

    temp = temp[
        (temp["hour"] >= 22)
        |
        (temp["hour"] <= 7)
    ]

    return most_contacted(temp)


# -----------------------------------
# SILENT PERIODS
# -----------------------------------
def silent_periods(df, threshold_hours=None):
    """
    Find periods of at least `threshold_hours` between consecutive CDR records.
    Default threshold is SILENT_PERIOD_HOURS (4 hours).
    """
    if threshold_hours is None:
        threshold_hours = SILENT_PERIOD_HOURS

    if "call_date" not in df.columns or "call_time" not in df.columns:
        return []

    temp = df.copy()
    temp["datetime"] = pd.to_datetime(temp["call_date"] + " " + temp["call_time"], errors="coerce")
    temp = temp.sort_values("datetime")
    temp["previous"] = temp["datetime"].shift(1)
    temp["gap_hours"] = (temp["datetime"] - temp["previous"]).dt.total_seconds() / 3600

    silent = temp[temp["gap_hours"] >= threshold_hours]   # use threshold

    results = []
    for _, row in silent.iterrows():
        results.append({
            "before_time": str(row["previous"]),
            "after_time": str(row["datetime"]),
            "silent_hours": round(row["gap_hours"], 2)
        })
    return results


# -----------------------------------
# RESIDENCE / ANCHOR LOCATION ANALYSIS
# -----------------------------------
def residence_zone_analysis(df):

    required_columns = [
        "tower_address",
        "latitude",
        "longitude",
        "sector",
        "datetime"
    ]

    for col in required_columns:

        if col not in df.columns:
            return []

    temp = df.copy()

    temp = temp.sort_values(
        "datetime"
    )

    temp["previous_time"] = (
        temp["datetime"]
        .shift(1)
    )

    temp["gap_hours"] = (
        (
            temp["datetime"]
            -
            temp["previous_time"]
        ).dt.total_seconds()
        / 3600
    )

    silent_periods = temp[
        temp["gap_hours"] >= 4
    ]

    tower_scores = {}

    for idx in silent_periods.index:

        current_row = temp.loc[idx]

        previous_row = temp.loc[idx - 1]

        before_tower = str(
            previous_row["tower_address"]
        )

        after_tower = str(
            current_row["tower_address"]
        )

        if before_tower == after_tower:

            tower_scores[
                before_tower
            ] = (
                tower_scores.get(
                    before_tower,
                    0
                )
                + 2
            )

        else:

            tower_scores[
                before_tower
            ] = (
                tower_scores.get(
                    before_tower,
                    0
                )
                + 1
            )

            tower_scores[
                after_tower
            ] = (
                tower_scores.get(
                    after_tower,
                    0
                )
                + 1
            )

    results = []

    for tower, score in tower_scores.items():

        row = temp[
            temp["tower_address"]
            == tower
        ].iloc[0]

        results.append({

            "tower_address":
                tower,

            "latitude":
                row["latitude"],

            "longitude":
                row["longitude"],

            "sector":
                row["sector"],

            "silent_hits":
                score
        })

    results = sorted(

        results,

        key=lambda x:
            x["silent_hits"],

        reverse=True
    )

    return results[:5]

# -----------------------------------
# SILENT PERIOD RESIDENCE ANALYSIS
# -----------------------------------
def silent_period_residence_analysis(df):
    required = ["call_date", "call_time", "tower_address", "latitude", "longitude", "sector"]
    for col in required:
        if col not in df.columns:
            return []

    temp = df.copy()
    temp["datetime"] = pd.to_datetime(temp["call_date"] + " " + temp["call_time"], errors="coerce")
    temp = temp.sort_values("datetime")
    temp["previous_datetime"] = temp["datetime"].shift(1)
    temp["gap_hours"] = (temp["datetime"] - temp["previous_datetime"]).dt.total_seconds() / 3600

    # Use the same threshold as defined globally
    silent_rows = temp[temp["gap_hours"] >= SILENT_PERIOD_HOURS]

    residence_points = []
    for _, row in silent_rows.iterrows():
        previous_index = row.name - 1
        if previous_index in temp.index:
            before_row = temp.loc[previous_index]
            residence_points.append({
                "tower_address": before_row["tower_address"],
                "latitude": before_row["latitude"],
                "longitude": before_row["longitude"],
                "sector": before_row["sector"],
                "type": "BEFORE_SILENCE"
            })
        residence_points.append({
            "tower_address": row["tower_address"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "sector": row["sector"],
            "type": "AFTER_SILENCE"
        })

    if len(residence_points) == 0:
        return []

    result = pd.DataFrame(residence_points)
    grouped = result.groupby(["tower_address", "latitude", "longitude", "sector"]).size().reset_index(name="score")
    grouped = grouped.sort_values("score", ascending=False)
    return grouped.head(3).to_dict(orient="records")