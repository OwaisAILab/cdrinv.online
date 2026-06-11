import pandas as pd


def meeting_hotspots(meetings):

    if not meetings:
        return []

    df = pd.DataFrame(meetings)

    if len(df) == 0:
        return []

    hotspots = (

        df.groupby("tower")

        .agg(

            meetings=(
                "tower",
                "count"
            )
        )

        .reset_index()
    )

    results = []

    for _, row in hotspots.iterrows():

        count = int(
            row["meetings"]
        )

        if count >= 10:

            risk = "VERY HIGH"

        elif count >= 5:

            risk = "HIGH"

        elif count >= 3:

            risk = "MEDIUM"

        else:

            risk = "LOW"

        results.append({

            "tower":
                row["tower"],

            "meeting_count":
                count,

            "risk":
                risk
        })

    results = sorted(

        results,

        key=lambda x:
        x["meeting_count"],

        reverse=True
    )

    return results

def hotspot_dates(meetings):

    if not meetings:
        return []

    results = {}

    for item in meetings:

        tower = item["tower"]

        date = str(
            item["cdr_1_time"]
        )[:10]

        if tower not in results:

            results[tower] = set()

        results[tower].add(date)

    output = []

    for tower, dates in results.items():

        output.append({

            "tower":
                tower,

            "meeting_dates":
                sorted(
                    list(dates)
                ),

            "total_dates":
                len(dates)
        })

    return output

