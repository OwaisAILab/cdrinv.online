import math
import pandas as pd

# -----------------------------------
# WORKPLACE ANALYSIS
# -----------------------------------
def workplace_analysis(df):

    required_columns = [

        "tower_address",
        "call_time"
    ]

    for col in required_columns:

        if col not in df.columns:
            return []

    temp = df.copy()

    try:

        temp["hour"] = (

            temp["call_time"]
            .astype(str)
            .str.slice(0, 2)
            .astype(int)
        )

    except:

        return []

    # Office hours
    daytime = temp[

        temp["hour"]
        .between(8, 18)
    ]

    if len(daytime) == 0:
        return []

    result = (

        daytime.groupby(

            [
                "tower_address",
                "latitude",
                "longitude"
            ],

            dropna=False
        )

        .size()

        .reset_index(
            name="visits"
        )

        .sort_values(
            "visits",
            ascending=False
        )
    )

    return (

        result
        .head(10)
        .to_dict(
            orient="records"
        )
    )


# -----------------------------------
# DAILY ROUTE ANALYSIS
# -----------------------------------
def daily_route_analysis(df):

    required_columns = [

        "call_date",
        "call_time",
        "tower_address"
    ]

    for col in required_columns:

        if col not in df.columns:
            return []

    temp = df.copy()

    temp["datetime"] = pd.to_datetime(

        temp["call_date"]

        + " "

        +

        temp["call_time"],

        errors="coerce"
    )

    temp = temp[
        temp["datetime"].notna()
    ]

    routes = []

    for day in sorted(

        temp["call_date"]
        .dropna()
        .unique()
    ):

        day_df = temp[

            temp["call_date"]
            == day

        ].sort_values(
            "datetime"
        )

        tower_route = []

        previous = None

        for tower in day_df[
            "tower_address"
        ]:

            tower = str(
                tower
            ).strip()

            if tower == "":
                continue

            # Remove duplicates
            if tower != previous:

                tower_route.append(
                    tower
                )

                previous = tower

        routes.append({

            "date": day,

            "route": tower_route,

            "unique_towers":

                len(
                    tower_route
                )
        })

    return routes

# -----------------------------------
# ROUTE FREQUENCY ANALYSIS
# -----------------------------------
def route_frequency_analysis(df):

    routes = daily_route_analysis(df)

    if len(routes) == 0:
        return []

    route_counts = {}

    for day in routes:

        towers = day["route"]

        if len(towers) < 2:
            continue

        for i in range(len(towers) - 1):

            start = towers[i]
            end = towers[i + 1]

            key = f"{start} ---> {end}"

            route_counts[key] = (

                route_counts.get(
                    key,
                    0
                ) + 1
            )

    results = []

    for route, count in route_counts.items():

        parts = route.split(
            " ---> "
        )

        results.append({

            "from":
                parts[0],

            "to":
                parts[1],

            "frequency":
                count
        })

    results = sorted(

        results,

        key=lambda x:
        x["frequency"],

        reverse=True
    )

    return results[:20]

# -----------------------------------
# DISTANCE BETWEEN TWO POINTS
# -----------------------------------
def haversine_distance(
    lat1,
    lon1,
    lat2,
    lon2
):

    R = 6371

    lat1 = math.radians(float(lat1))
    lon1 = math.radians(float(lon1))

    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (

        math.sin(dlat / 2) ** 2

        +

        math.cos(lat1)

        *

        math.cos(lat2)

        *

        math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return R * c

# -----------------------------------
# MOVEMENT RADIUS ANALYSIS
# -----------------------------------
def movement_radius_analysis(df):
    required_columns = ["latitude", "longitude", "tower_address"]
    for col in required_columns:
        if col not in df.columns:
            return {}

    temp = df.copy()
    temp = temp[(temp["latitude"] != "") & (temp["longitude"] != "")]
    if len(temp) < 2:
        return {}

    # FIX: Use centroid (mean lat/lon) as reference point
    try:
        center_lat = temp["latitude"].astype(float).mean()
        center_lon = temp["longitude"].astype(float).mean()
    except:
        # If conversion fails, fallback to first row
        center_lat = temp.iloc[0]["latitude"]
        center_lon = temp.iloc[0]["longitude"]

    distances = []
    furthest_tower = ""
    max_distance = 0

    for _, row in temp.iterrows():
        try:
            distance = haversine_distance(
                center_lat, center_lon,
                row["latitude"], row["longitude"]
            )
            distances.append(distance)
            if distance > max_distance:
                max_distance = distance
                furthest_tower = str(row["tower_address"])
        except:
            pass

    if len(distances) == 0:
        return {}

    average_distance = sum(distances) / len(distances)

    if max_distance < 10:
        travel_type = "LOCAL MOVEMENT"
    elif max_distance < 50:
        travel_type = "CITY MOVEMENT"
    else:
        travel_type = "LONG DISTANCE MOVEMENT"

    return {
        "max_distance_km": round(max_distance, 2),
        "average_distance_km": round(average_distance, 2),
        "furthest_tower": furthest_tower,
        "travel_type": travel_type
    }
# -----------------------------------
# UNUSUAL TRAVEL DETECTION
# -----------------------------------
def unusual_travel_detection(df):

    routes = daily_route_analysis(df)

    if len(routes) < 3:
        return []

    # ----------------------------
    # BUILD FREQUENCY MODEL
    # ----------------------------
    route_frequency = {}

    for day in routes:

        route = tuple(day["route"])

        route_frequency[route] = (

            route_frequency.get(
                route,
                0
            ) + 1
        )

    # ----------------------------
    # MOST COMMON ROUTE
    # ----------------------------
    normal_route = max(

        route_frequency,

        key=route_frequency.get
    )

    results = []

    # ----------------------------
    # COMPARE EACH DAY
    # ----------------------------
    for day in routes:

        current_route = tuple(
            day["route"]
        )

        unusual = (
            current_route
            !=
            normal_route
        )

        results.append({

            "date":
                day["date"],

            "unique_towers":
                day["unique_towers"],

            "route":
                list(
                    current_route
                ),

            "normal_route":
                list(
                    normal_route
                ),

            "unusual_movement":
                unusual
        })

    return results

# -----------------------------------
# ONLY FLAGGED UNUSUAL DAYS
# -----------------------------------
def unusual_days_only(df):

    results = unusual_travel_detection(df)

    flagged = []

    for item in results:

        if item.get(
            "unusual_movement",
            False
        ):

            flagged.append(item)

    return flagged