"""
OPERATIONAL INTELLIGENCE MODULE
For tactical suspect tracking — NOT for court evidence.
Focuses on: Location, Movement Speed, Dwell Time, and Real-Time Alerts.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ============================================================
# 1. MERGE ALL DATA SOURCES (Voice + SMS + Data + Non-Mobile)
# ============================================================

def merge_all_timelines(
    normalized_df: pd.DataFrame,
    non_mobile_df: pd.DataFrame,
    data_sessions_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Merge ALL location pings into a single timeline for operational tracking.
    This ensures you never miss a location hit.
    """
    # Ensure consistent column naming
    common_cols = ['owner_number', 'call_date', 'call_time', 'datetime', 
                   'cell_id', 'tower_address', 'latitude', 'longitude', 'sector']
    
    # Normalize each DataFrame
    def prepare(df, source_type):
        if df is None or len(df) == 0:
            return pd.DataFrame(columns=common_cols)
        
        df = df.copy()
        
        # Ensure datetime exists
        if 'datetime' not in df.columns and 'call_date' in df.columns and 'call_time' in df.columns:
            df['datetime'] = pd.to_datetime(
                df['call_date'] + ' ' + df['call_time'],
                errors='coerce'
            )
        
        # Add source type for debugging
        df['source_type'] = source_type
        
        # Select only relevant columns
        available_cols = [c for c in common_cols + ['source_type'] if c in df.columns]
        return df[available_cols]
    
    # Merge all
    merged = pd.concat([
        prepare(normalized_df, 'voice_sms'),
        prepare(non_mobile_df, 'non_mobile'),
        prepare(data_sessions_df, 'data_session')
    ], ignore_index=True)
    
    # Sort by time
    if 'datetime' in merged.columns:
        merged = merged.sort_values('datetime')
    
    print(f"✅ OPERATIONAL TIMELINE: {len(merged)} total location pings")
    print(f"   - Voice/SMS: {len(prepare(normalized_df, 'voice_sms'))}")
    print(f"   - Non-Mobile: {len(prepare(non_mobile_df, 'non_mobile'))}")
    print(f"   - Data Sessions: {len(prepare(data_sessions_df, 'data_session'))}")
    
    return merged


# ============================================================
# 2. CALCULATE DWELL TIME & MOVEMENT SPEED
# ============================================================

def calculate_movement_metrics(timeline_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each location ping, calculate:
    - Time spent at this tower (dwell time in minutes)
    - Movement speed to next tower (km/h)
    - Time since last ping (gap in minutes)
    
    This tells you: Is the suspect stationary (hiding) or moving (fleeing)?
    """
    if len(timeline_df) < 2:
        return timeline_df
    
    df = timeline_df.copy()
    
    # Ensure datetime is datetime type
    df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
    df = df.dropna(subset=['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    
    # --- Time since previous ping ---
    df['prev_datetime'] = df['datetime'].shift(1)
    df['time_gap_minutes'] = (df['datetime'] - df['prev_datetime']).dt.total_seconds() / 60
    
    # --- Time at same tower (dwell time) ---
    # Check if current tower is the same as previous tower
    df['same_tower_as_prev'] = df['tower_address'] == df['tower_address'].shift(1)
    
    # Calculate dwell time (how long at THIS tower before moving)
    # We'll compute it in reverse
    df['dwell_start_time'] = df['datetime'].copy()
    
    # Group consecutive same-tower visits
    tower_groups = (df['tower_address'] != df['tower_address'].shift(1)).cumsum()
    df['tower_group'] = tower_groups
    
    # Dwell time = time from first ping at tower to last ping at tower
    dwell_times = df.groupby('tower_group').agg({
        'datetime': ['min', 'max']
    })
    dwell_times.columns = ['dwell_start', 'dwell_end']
    dwell_times['dwell_minutes'] = (dwell_times['dwell_end'] - dwell_times['dwell_start']).dt.total_seconds() / 60
    
    # Merge back
    df = df.merge(dwell_times[['dwell_start', 'dwell_end', 'dwell_minutes']], 
                  left_on='datetime', right_on='dwell_start', how='left')
    df['dwell_minutes'] = df['dwell_minutes'].fillna(0)
    
    # --- Movement speed to next tower ---
    # Only calculate if tower changes
    df['next_tower'] = df['tower_address'].shift(-1)
    df['next_datetime'] = df['datetime'].shift(-1)
    df['tower_changed'] = df['tower_address'] != df['next_tower']
    
    # Calculate distance between towers using Haversine
    def haversine(lat1, lon1, lat2, lon2):
        if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
            return np.nan
        R = 6371  # Earth's radius in km
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return R * c
    
    df['distance_km_to_next'] = df.apply(
        lambda row: haversine(
            row.get('latitude', None), row.get('longitude', None),
            row.get('next_lat', None), row.get('next_lon', None)
        ) if pd.notna(row.get('latitude')) else np.nan,
        axis=1
    )
    
    # Handle if next_lat/next_lon columns don't exist
    if 'next_lat' not in df.columns:
        df['next_lat'] = df['latitude'].shift(-1)
        df['next_lon'] = df['longitude'].shift(-1)
        df['distance_km_to_next'] = df.apply(
            lambda row: haversine(
                row['latitude'], row['longitude'],
                row['next_lat'], row['next_lon']
            ) if pd.notna(row['latitude']) and pd.notna(row['next_lat']) else np.nan,
            axis=1
        )
    
    # Calculate speed (km/h) only if tower changed and we have a distance
    df['time_to_next_hours'] = (df['next_datetime'] - df['datetime']).dt.total_seconds() / 3600
    df['speed_kmh'] = np.where(
        df['tower_changed'] & (df['distance_km_to_next'] > 0) & (df['time_to_next_hours'] > 0),
        df['distance_km_to_next'] / df['time_to_next_hours'],
        np.nan
    )
    
    # --- Classify movement type ---
    def classify_movement(speed):
        if pd.isna(speed):
            return 'UNKNOWN'
        if speed < 2:
            return 'STATIONARY'
        elif speed < 10:
            return 'WALKING'
        elif speed < 40:
            return 'SLOW VEHICLE'
        elif speed < 80:
            return 'FAST VEHICLE'
        else:
            return 'RAPID (>80km/h) - FLEEING?'
    
    df['movement_type'] = df['speed_kmh'].apply(classify_movement)
    
    # --- Dwell classification ---
    def classify_dwell(minutes):
        if pd.isna(minutes) or minutes == 0:
            return 'PASSING THROUGH'
        if minutes < 5:
            return 'BRIEF STOP'
        if minutes < 30:
            return 'SHORT VISIT'
        if minutes < 120:
            return 'EXTENDED VISIT'
        if minutes < 480:  # 8 hours
            return 'LONG STAY'
        else:
            return 'OVERNIGHT / RESIDENCE'
    
    df['dwell_type'] = df['dwell_minutes'].apply(classify_dwell)
    
    # Clean up columns
    cols_to_keep = ['datetime', 'call_date', 'call_time', 'tower_address', 'latitude', 'longitude',
                    'cell_id', 'sector', 'source_type', 'time_gap_minutes', 'dwell_minutes', 
                    'dwell_type', 'distance_km_to_next', 'speed_kmh', 'movement_type']
    
    final_cols = [c for c in cols_to_keep if c in df.columns]
    
    return df[final_cols]


# ============================================================
# 3. REAL-TIME "LAST SEEN" ALERT
# ============================================================

def get_last_seen(timeline_df: pd.DataFrame) -> Dict:
    """
    Return the suspect's most recent location ping with human-readable summary.
    This is the most critical field for operational teams.
    """
    if len(timeline_df) == 0:
        return {
            'last_seen_time': None,
            'tower_address': 'Unknown',
            'latitude': None,
            'longitude': None,
            'time_ago_minutes': None,
            'status': 'NO_DATA'
        }
    
    df = timeline_df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
    df = df.dropna(subset=['datetime'])
    df = df.sort_values('datetime')
    
    last_row = df.iloc[-1]
    now = datetime.now()
    
    if pd.isna(last_row['datetime']):
        return {'status': 'INVALID_DATA'}
    
    time_ago = (now - last_row['datetime']).total_seconds() / 60
    
    return {
        'last_seen_time': last_row['datetime'],
        'tower_address': last_row.get('tower_address', 'Unknown'),
        'latitude': last_row.get('latitude', None),
        'longitude': last_row.get('longitude', None),
        'sector': last_row.get('sector', 'Unknown'),
        'source_type': last_row.get('source_type', 'Unknown'),
        'time_ago_minutes': round(time_ago, 1),
        'status': 'RECENT' if time_ago < 15 else 'STALE',
        'urgency': 'IMMEDIATE' if time_ago < 5 else 'SOON' if time_ago < 30 else 'ROUTINE'
    }


# ============================================================
# 4. NIGHT RESIDENCE DETECTION (11PM - 5AM)
# ============================================================

def detect_night_residence(timeline_df: pd.DataFrame) -> List[Dict]:
    """
    Find where the suspect spends most nights (11 PM - 5 AM).
    This is the #1 intelligence for planning a raid.
    """
    if len(timeline_df) == 0:
        return []
    
    df = timeline_df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
    df = df.dropna(subset=['datetime'])
    
    # Filter to night hours (11 PM - 5 AM)
    df['hour'] = df['datetime'].dt.hour
    night_mask = (df['hour'] >= 23) | (df['hour'] <= 5)
    night_df = df[night_mask]
    
    if len(night_df) == 0:
        return []
    
    # Count tower visits during night hours
    tower_counts = night_df.groupby(['tower_address', 'latitude', 'longitude']).size().reset_index(name='night_visits')
    tower_counts = tower_counts.sort_values('night_visits', ascending=False)
    
    # Get days covered
    total_nights = night_df['datetime'].dt.date.nunique()
    
    results = []
    for _, row in tower_counts.iterrows():
        # Calculate what percentage of nights this tower appears
        tower_dates = night_df[night_df['tower_address'] == row['tower_address']]['datetime'].dt.date.nunique()
        coverage_pct = round((tower_dates / total_nights) * 100, 1) if total_nights > 0 else 0
        
        results.append({
            'tower_address': row['tower_address'],
            'latitude': row['latitude'],
            'longitude': row['longitude'],
            'night_visits': row['night_visits'],
            'nights_covered': tower_dates,
            'total_nights': total_nights,
            'coverage_percentage': coverage_pct,
            'confidence': 'VERY_HIGH' if coverage_pct > 70 else 'HIGH' if coverage_pct > 50 else 'MEDIUM'
        })
    
    return results


# ============================================================
# 5. GEOREFERENCE ALERT SYSTEM (Stub - Ready for integration)
# ============================================================

class GeofenceAlert:
    """
    Stub for future geofence implementation.
    In production, you'd define polygons and check if suspect enters them.
    """
    
    def __init__(self):
        self.zones = {
            'AIRPORT': {'lat_range': (24.85, 24.90), 'lon_range': (67.10, 67.15)},
            'BORDER_EAST': {'lat_range': (24.80, 25.00), 'lon_range': (67.25, 67.35)},
            'HIGHWAY_INTERCHANGE': {'lat_range': (24.88, 24.92), 'lon_range': (67.08, 67.12)}
        }
    
    def check_zone(self, lat, lon, zone_name):
        if lat is None or lon is None:
            return False
        zone = self.zones.get(zone_name, {})
        if not zone:
            return False
        lat_min, lat_max = zone.get('lat_range', (0, 0))
        lon_min, lon_max = zone.get('lon_range', (0, 0))
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max
    
    def check_all_zones(self, lat, lon):
        alerts = []
        for zone_name in self.zones:
            if self.check_zone(lat, lon, zone_name):
                alerts.append({
                    'zone': zone_name,
                    'timestamp': datetime.now(),
                    'action': f'🚨 SUSPECT NEAR {zone_name}! Alert ground team.'
                })
        return alerts


# ============================================================
# 6. COMPLETE OPERATIONAL INTELLIGENCE REPORT
# ============================================================

def generate_operational_report(
    normalized_df: pd.DataFrame,
    non_mobile_df: pd.DataFrame,
    data_sessions_df: pd.DataFrame
) -> Dict:
    """
    Generate a complete tactical intelligence report.
    This is what your field teams actually need.
    """
    
    # 1. Merge all sources
    timeline = merge_all_timelines(normalized_df, non_mobile_df, data_sessions_df)
    
    if len(timeline) == 0:
        return {
            'status': 'NO_DATA',
            'error': 'No location data available. Check CDR upload.'
        }
    
    # 2. Calculate movement metrics
    timeline_with_movement = calculate_movement_metrics(timeline)
    
    # 3. Last seen
    last_seen = get_last_seen(timeline_with_movement)
    
    # 4. Night residence
    night_residence = detect_night_residence(timeline_with_movement)
    
    # 5. Daily routine summary
    daily_routine = {}
    if 'call_date' in timeline.columns:
        dates = timeline['call_date'].dropna().unique()
        for date in sorted(dates)[-7:]:  # Last 7 days
            day_df = timeline[timeline['call_date'] == date]
            day_activities = []
            if len(day_df) > 0:
                # Most frequent tower of the day
                top_tower = day_df['tower_address'].mode().iloc[0] if len(day_df) > 0 else 'Unknown'
                day_activities.append({
                    'date': date,
                    'total_pings': len(day_df),
                    'primary_tower': top_tower,
                    'first_ping': day_df['datetime'].min() if 'datetime' in day_df.columns else None,
                    'last_ping': day_df['datetime'].max() if 'datetime' in day_df.columns else None
                })
            daily_routine[date] = day_activities
    
    # 6. Movement hotspots (most frequent towers)
    tower_hotspots = timeline['tower_address'].value_counts().head(10).to_dict()
    
    # 7. Build operational report
    report = {
        'status': 'READY',
        'total_pings': len(timeline),
        'data_sources': {
            'voice_sms': len(normalized_df) if normalized_df is not None else 0,
            'non_mobile': len(non_mobile_df) if non_mobile_df is not None else 0,
            'data_sessions': len(data_sessions_df) if data_sessions_df is not None else 0
        },
        'last_seen': last_seen,
        'night_residence': night_residence[:3],  # Top 3 night locations
        'tower_hotspots': tower_hotspots,
        'daily_routine': daily_routine,
        'movement_summary': {
            'avg_speed_kmh': round(timeline_with_movement['speed_kmh'].mean(), 1) if 'speed_kmh' in timeline_with_movement.columns else 0,
            'max_speed_kmh': round(timeline_with_movement['speed_kmh'].max(), 1) if 'speed_kmh' in timeline_with_movement.columns else 0,
            'stationary_time_minutes': timeline_with_movement['dwell_minutes'].sum() if 'dwell_minutes' in timeline_with_movement.columns else 0,
            'unique_towers': timeline['tower_address'].nunique()
        },
        'tactical_recommendations': []
    }
    
    # 8. Generate tactical recommendations
    if night_residence and len(night_residence) > 0:
        report['tactical_recommendations'].append({
            'priority': 'CRITICAL',
            'action': f"🏠 RAID OPPORTUNITY: Suspect likely resides at {night_residence[0]['tower_address']}",
            'confidence': night_residence[0]['confidence']
        })
    
    if last_seen.get('time_ago_minutes', 999) < 30:
        report['tactical_recommendations'].append({
            'priority': 'IMMEDIATE',
            'action': f"🔴 LAST SEEN {last_seen['time_ago_minutes']} minutes ago at {last_seen['tower_address']}",
            'confidence': 'HIGH'
        })
    
    if report['movement_summary']['max_speed_kmh'] > 80:
        report['tactical_recommendations'].append({
            'priority': 'URGENT',
            'action': f"🚗 SUSPECT FLEEING! Max speed: {report['movement_summary']['max_speed_kmh']} km/h",
            'confidence': 'HIGH'
        })
    
    # Check if suspect has been stationary > 8 hours (likely at a hideout)
    if report['movement_summary']['stationary_time_minutes'] > 480:
        report['tactical_recommendations'].append({
            'priority': 'HIGH',
            'action': f"🕵️ SUSPECT STATIONARY: {round(report['movement_summary']['stationary_time_minutes']/60, 1)} hours at last location",
            'confidence': 'MEDIUM'
        })
    
    return report


# ============================================================
# 7. HELPER: Format for display in Dashboard
# ============================================================

def format_operational_report(report: Dict) -> Dict:
    """
    Format the operational report for display in the dashboard.
    """
    if report.get('status') == 'NO_DATA':
        return {
            'status': 'no_data',
            'message': 'Upload a CDR first to enable operational tracking.'
        }
    
    formatted = {
        'status': 'ready',
        'last_seen': {
            'time': str(report['last_seen'].get('last_seen_time', 'Unknown')),
            'tower': report['last_seen'].get('tower_address', 'Unknown'),
            'lat': report['last_seen'].get('latitude'),
            'lon': report['last_seen'].get('longitude'),
            'minutes_ago': report['last_seen'].get('time_ago_minutes', 999),
            'urgency': report['last_seen'].get('urgency', 'ROUTINE')
        },
        'night_residence': report['night_residence'],
        'recommendations': report['tactical_recommendations'],
        'stats': {
            'total_pings': report['total_pings'],
            'unique_towers': report['movement_summary']['unique_towers'],
            'max_speed': report['movement_summary']['max_speed_kmh']
        }
    }
    return formatted