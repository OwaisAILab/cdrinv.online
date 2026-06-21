# map_utils.py
import math

def generate_map_data(df):

    results = []
    skipped = 0
    for _, row in df.iterrows():

        try:

            lat = float(str(row.get("latitude", "")).strip())
            lon = float(str(row.get("longitude", "")).strip())

            if math.isnan(lat) or math.isnan(lon):
                continue

            if math.isinf(lat) or math.isinf(lon):
                continue

        except:
            skipped += 1
            continue

        results.append({
            "latitude": lat,
            "longitude": lon,
            "tower": str(row.get("tower_address", "")),
            "sector": str(row.get("sector", "")),
            "time": str(row.get("call_time", ""))
        })

    print(f"Valid map points: {len(results)}")
    print(f"Skipped records: {skipped}")
    return results