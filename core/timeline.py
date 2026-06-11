# timeline.py

import pandas as pd


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
def silent_periods(df):

    if (
        "call_date" not in df.columns
        or
        "call_time" not in df.columns
    ):
        return []

    temp = df.copy()

    temp["datetime"] = pd.to_datetime(
        temp["call_date"]
        + " " +
        temp["call_time"],
        errors="coerce"
    )

    temp = temp.sort_values("datetime")

    temp["previous"] = (
        temp["datetime"]
        .shift(1)
    )

    temp["gap_hours"] = (
        (
            temp["datetime"]
            -
            temp["previous"]
        ).dt.total_seconds()
        / 3600
    )

    silent = temp[
        temp["gap_hours"] >= 4
    ]

    results = []

    for _, row in silent.iterrows():

        results.append({

            "before_time": str(row["previous"]),

            "after_time": str(row["datetime"]),

            "silent_hours": round(
                row["gap_hours"],
                2
            )
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

    required = [
        "call_date",
        "call_time",
        "tower_address",
        "latitude",
        "longitude",
        "sector"
    ]

    for col in required:

        if col not in df.columns:
            return []

    temp = df.copy()

    temp["datetime"] = pd.to_datetime(
        temp["call_date"] + " " + temp["call_time"],
        errors="coerce"
    )

    temp = temp.sort_values("datetime")

    temp["previous_datetime"] = (
        temp["datetime"]
        .shift(1)
    )

    temp["gap_hours"] = (
        (
            temp["datetime"]
            -
            temp["previous_datetime"]
        ).dt.total_seconds()
        / 3600
    )

    silent_rows = temp[
        temp["gap_hours"] >= 4
    ]

    residence_points = []

    for _, row in silent_rows.iterrows():

        previous_index = row.name - 1

        # location BEFORE silence
        if previous_index in temp.index:

            before_row = temp.loc[previous_index]

            residence_points.append({
                "tower_address":
                    before_row["tower_address"],

                "latitude":
                    before_row["latitude"],

                "longitude":
                    before_row["longitude"],

                "sector":
                    before_row["sector"],

                "type":
                    "BEFORE_SILENCE"
            })

        # location AFTER silence
        residence_points.append({

            "tower_address":
                row["tower_address"],

            "latitude":
                row["latitude"],

            "longitude":
                row["longitude"],

            "sector":
                row["sector"],

            "type":
                "AFTER_SILENCE"
        })

    if len(residence_points) == 0:
        return []

    result = pd.DataFrame(
        residence_points
    )

    grouped = (
        result.groupby(
            [
                "tower_address",
                "latitude",
                "longitude",
                "sector"
            ]
        )
        .size()
        .reset_index(name="score")
    )

    grouped = grouped.sort_values(
        "score",
        ascending=False
    )

    return grouped.head(3).to_dict(
        orient="records"
    )