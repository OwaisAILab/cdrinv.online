# pattern_analysis.py
# Call pattern intelligence for CDR forensic analysis.
# Three detectors:
#   1. burst_detection        — sudden spike in calls within a short window
#   2. first_contact_analysis — new numbers appearing around an incident date
#   3. call_abandonment       — repeated very short calls (coordination pattern)

import pandas as pd
from collections import defaultdict


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────
def _build_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a proper datetime column if not already present."""
    t = df.copy()
    if "datetime" not in t.columns or t["datetime"].dtype == object:
        t["datetime"] = pd.to_datetime(
            t["call_date"].astype(str) + " " + t["call_time"].astype(str),
            errors="coerce"
        )
    else:
        t["datetime"] = pd.to_datetime(t["datetime"], errors="coerce")
    return t.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)


# ─────────────────────────────────────────────
# 1. BURST DETECTION
# Sudden spike in call activity within a rolling window.
# Criminal networks often burst-communicate before/after an event.
# ─────────────────────────────────────────────
def burst_detection(df: pd.DataFrame, window_minutes: int = 30, spike_threshold: int = 5) -> list:
    """
    Detect time windows where call frequency spikes unusually high.

    Parameters
    ----------
    window_minutes   : rolling window size (default 30 min)
    spike_threshold  : minimum calls within window to flag as burst (default 5)

    Returns list of dicts:
      window_start, window_end, call_count, contacts_involved,
      towers_used, avg_duration, severity (HIGH / MEDIUM)
    """
    required = {"call_date", "call_time"}
    if not required.issubset(df.columns):
        return []

    try:
        t = _build_datetime(df)
        if len(t) < spike_threshold:
            return []

        window = pd.Timedelta(minutes=window_minutes)
        results = []
        seen_starts = set()

        for i, row in t.iterrows():
            start = row["datetime"]
            end   = start + window

            # All records within this window
            mask    = (t["datetime"] >= start) & (t["datetime"] <= end)
            window_df = t[mask]

            if len(window_df) < spike_threshold:
                continue

            # Deduplicate: only flag if this window isn't already covered
            bucket = start.floor("30min")
            if bucket in seen_starts:
                continue
            seen_starts.add(bucket)

            contacts = window_df["contact_number"].dropna().unique().tolist() \
                if "contact_number" in window_df.columns else []
            towers   = window_df["tower_address"].dropna().unique().tolist() \
                if "tower_address" in window_df.columns else []
            durations = window_df["duration"].dropna().astype(float) \
                if "duration" in window_df.columns else pd.Series([], dtype=float)

            severity = "HIGH" if len(window_df) >= spike_threshold * 2 else "MEDIUM"

            # Build individual call records for drill-down display
            call_records = []
            for _, cr in window_df.iterrows():
                call_records.append({
                    "datetime":   cr["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                    "contact":    str(cr.get("contact_number", "—")),
                    "direction":  str(cr.get("direction", "—")).upper(),
                    "call_type":  str(cr.get("call_type", "VOICE")).upper(),
                    "duration":   int(cr["duration"]) if pd.notna(cr.get("duration")) else 0,
                    "tower":      str(cr.get("tower_address", "—")),
                })

            results.append({
                "window_start":       start.strftime("%Y-%m-%d %H:%M"),
                "window_end":         end.strftime("%Y-%m-%d %H:%M"),
                "call_count":         int(len(window_df)),
                "contacts_involved":  [str(c) for c in contacts],
                "contact_count":      len(contacts),
                "towers_used":        [str(t_) for t_ in towers],
                "avg_duration_sec":   round(float(durations.mean()), 1) if len(durations) > 0 else 0,
                "severity":           severity,
                "records":            call_records,
            })

        # Sort by call count descending
        results.sort(key=lambda x: x["call_count"], reverse=True)
        return results

    except Exception:
        return []


# ─────────────────────────────────────────────
# 2. FIRST-TIME CONTACT ANALYSIS
# New numbers appearing within a date window around an incident.
# A sudden cluster of previously-unseen contacts is a strong
# investigative signal of coordination or recruitment.
# ─────────────────────────────────────────────
def first_contact_analysis(
    df: pd.DataFrame,
    incident_date: str = None,
    days_before: int = 7,
    days_after: int = 7
) -> dict:
    """
    Identify contact numbers that appear for the FIRST TIME
    within [incident_date - days_before, incident_date + days_after].

    If incident_date is None, uses the entire CDR range and returns
    all first-contact dates for every number (useful for timeline view).

    Returns dict with:
      incident_date, window_start, window_end,
      new_contacts (list), new_contact_count,
      pre_incident_new (contacts appearing before),
      post_incident_new (contacts appearing after),
      all_first_contacts (full list regardless of window)
    """
    required = {"call_date", "call_time", "contact_number"}
    if not required.issubset(df.columns):
        return {}

    try:
        t = _build_datetime(df)
        t = t.dropna(subset=["contact_number"])
        t["contact_number"] = t["contact_number"].astype(str)

        # Find the first appearance date for every contact number
        first_seen = (
            t.groupby("contact_number")["datetime"]
            .min()
            .reset_index()
            .rename(columns={"datetime": "first_seen"})
        )

        # Build full first-contact list
        all_first = []
        for _, row in first_seen.iterrows():
            all_first.append({
                "contact":    row["contact_number"],
                "first_seen": row["first_seen"].strftime("%Y-%m-%d %H:%M"),
                "date":       row["first_seen"].strftime("%Y-%m-%d"),
            })
        all_first.sort(key=lambda x: x["first_seen"])

        if incident_date is None:
            return {
                "incident_date":      None,
                "window_start":       None,
                "window_end":         None,
                "new_contacts":       all_first,
                "new_contact_count":  len(all_first),
                "pre_incident_new":   [],
                "post_incident_new":  [],
                "all_first_contacts": all_first,
            }

        inc_dt      = pd.to_datetime(incident_date, errors="coerce")
        win_start   = inc_dt - pd.Timedelta(days=days_before)
        win_end     = inc_dt + pd.Timedelta(days=days_after)

        window_new = [
            c for c in all_first
            if win_start <= pd.to_datetime(c["first_seen"]) <= win_end
        ]
        pre  = [c for c in window_new if pd.to_datetime(c["first_seen"]) < inc_dt]
        post = [c for c in window_new if pd.to_datetime(c["first_seen"]) >= inc_dt]

        return {
            "incident_date":      str(inc_dt.date()),
            "window_start":       str(win_start.date()),
            "window_end":         str(win_end.date()),
            "new_contacts":       window_new,
            "new_contact_count":  len(window_new),
            "pre_incident_new":   pre,
            "post_incident_new":  post,
            "all_first_contacts": all_first,
        }

    except Exception:
        return {}


# ─────────────────────────────────────────────
# 3. CALL ABANDONMENT ANALYSIS
# Repeated very short calls (0–5 seconds) to the same number.
# Classic coordination/signalling pattern: one ring = "I'm here",
# two rings = "abort", etc. Used by criminal networks to avoid
# leaving voice recordings.
# ─────────────────────────────────────────────
def call_abandonment_analysis(
    df: pd.DataFrame,
    max_duration_sec: int = 5,
    min_occurrences: int = 3
) -> list:
    """
    Find contacts with repeated abandoned/flash calls (duration ≤ max_duration_sec).

    Parameters
    ----------
    max_duration_sec  : calls at or below this duration are considered abandoned (default 5s)
    min_occurrences   : minimum number of such calls to a single contact to flag (default 3)

    Returns list of dicts per flagged contact:
      contact, abandoned_call_count, total_calls_to_contact,
      abandonment_rate_pct, call_dates, first_abandoned, last_abandoned, risk_level
    """
    required = {"contact_number", "duration"}
    if not required.issubset(df.columns):
        return []

    try:
        t = _build_datetime(df)
        t = t.dropna(subset=["contact_number", "duration"])
        t["contact_number"] = t["contact_number"].astype(str)
        t["duration"]       = pd.to_numeric(t["duration"], errors="coerce").fillna(0)

        # Only OUTGOING calls — an abandoned incoming doesn't signal coordination
        if "direction" in t.columns:
            outgoing = t[t["direction"].astype(str).str.upper() == "OUTGOING"]
        else:
            outgoing = t  # direction unknown — include all

        short_calls = outgoing[outgoing["duration"] <= max_duration_sec]

        if short_calls.empty:
            return []

        results = []
        for contact, grp in short_calls.groupby("contact_number"):
            if len(grp) < min_occurrences:
                continue

            total_to_contact = len(outgoing[outgoing["contact_number"] == contact])
            rate = round(len(grp) / total_to_contact * 100, 1) if total_to_contact > 0 else 0

            # Risk: HIGH if >70% of calls abandoned, MEDIUM otherwise
            risk = "HIGH" if rate >= 70 else "MEDIUM"

            dates = sorted(grp["datetime"].dt.strftime("%Y-%m-%d").unique().tolist())

            results.append({
                "contact":                contact,
                "abandoned_call_count":   int(len(grp)),
                "total_calls_to_contact": int(total_to_contact),
                "abandonment_rate_pct":   rate,
                "call_dates":             dates,
                "first_abandoned":        grp["datetime"].min().strftime("%Y-%m-%d %H:%M"),
                "last_abandoned":         grp["datetime"].max().strftime("%Y-%m-%d %H:%M"),
                "risk_level":             risk,
            })

        results.sort(key=lambda x: x["abandoned_call_count"], reverse=True)
        return results

    except Exception:
        return []
