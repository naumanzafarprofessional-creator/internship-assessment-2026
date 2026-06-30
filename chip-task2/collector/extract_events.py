"""
extract_events.py

Transforms raw daily weather records into discrete WeatherEvent entities
using per-location statistical thresholds. This is the core "entity
extraction" step for Task 2 -- it converts a continuous time series into
the discrete event nodes the knowledge graph schema requires.

Detection logic (documented for the technical report):

- RainfallEvent / Flood candidate: daily precipitation_sum exceeds the
  location's own 90th percentile for precipitation. A stricter 97th
  percentile threshold additionally flags the event as a Flood (high
  severity), giving us both granular Rainfall events and a smaller, more
  significant Flood subset, per location.

- Heatwave: a TimeWindow of >= 3 consecutive days where temperature_2m_max
  exceeds the location's 90th percentile for max temperature. Modeled as a
  single WeatherEvent linked to a TimeWindow node (not a Date), since it is
  inherently a multi-day phenomenon.

- Drought: a TimeWindow of >= 14 consecutive days with near-zero
  precipitation (below the location's 25th percentile, which for most arid
  locations in this dataset is close to 0mm). Also linked to a TimeWindow.

- WindEvent: daily windspeed_10m_max exceeds the location's 95th
  percentile. Single-day event, linked to a Date.

- TemperatureEvent: any day where temperature_2m_max is in the top 5% for
  that location but does NOT form part of a qualifying Heatwave window
  (i.e. an isolated hot day, not a sustained spell). Linked to a Date.

All thresholds are computed per-location (not globally) so that, e.g.,
Karachi's "extreme heat" and Kashgar's "extreme heat" are each calibrated
to their own local climate distribution rather than a single global cutoff
that would make every Kashgar day look mild and every Karachi day look
extreme.
"""

import os
import uuid
import pandas as pd
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(SCRIPT_DIR, "..", "data", "raw_weather.csv")
EVENTS_OUTPUT_PATH = os.path.join(SCRIPT_DIR, "..", "data", "events.csv")

RAIN_EVENT_PCTL = 0.90
FLOOD_PCTL = 0.97
HEAT_PCTL = 0.90
ISOLATED_HOT_DAY_PCTL = 0.95
WIND_EVENT_PCTL = 0.95
DROUGHT_LOW_PCTL = 0.25
HEATWAVE_MIN_DAYS = 3
DROUGHT_MIN_DAYS = 14


def new_id():
    return str(uuid.uuid4())[:8]


def find_consecutive_runs(mask: pd.Series, min_len: int):
    """Given a boolean Series indexed by date, return list of (start, end)
    date pairs for runs of True values with length >= min_len."""
    runs = []
    in_run = False
    run_start = None
    prev_date = None

    dates = mask.index.tolist()
    for i, d in enumerate(dates):
        val = mask.iloc[i]
        if val and not in_run:
            in_run = True
            run_start = d
        elif not val and in_run:
            in_run = False
            run_end = prev_date
            if (run_end - run_start).days + 1 >= min_len:
                runs.append((run_start, run_end))
        prev_date = d

    if in_run:
        run_end = prev_date
        if (run_end - run_start).days + 1 >= min_len:
            runs.append((run_start, run_end))

    return runs


def extract_events_for_location(df_loc: pd.DataFrame) -> list:
    df_loc = df_loc.sort_values("date").copy()
    df_loc["date"] = pd.to_datetime(df_loc["date"])
    df_loc.set_index("date", inplace=True)

    location = df_loc["location"].iloc[0]
    country = df_loc["country"].iloc[0]

    events = []

    # --- Thresholds (per-location) ---
    rain_thresh = df_loc["precipitation_sum"].quantile(RAIN_EVENT_PCTL)
    flood_thresh = df_loc["precipitation_sum"].quantile(FLOOD_PCTL)
    heat_thresh = df_loc["temperature_2m_max"].quantile(HEAT_PCTL)
    isolated_hot_thresh = df_loc["temperature_2m_max"].quantile(ISOLATED_HOT_DAY_PCTL)
    wind_thresh = df_loc["windspeed_10m_max"].quantile(WIND_EVENT_PCTL)
    drought_low_thresh = df_loc["precipitation_sum"].quantile(DROUGHT_LOW_PCTL)

    # --- Rainfall / Flood events (single-day) ---
    rain_days = df_loc[df_loc["precipitation_sum"] >= rain_thresh]
    for d, row in rain_days.iterrows():
        is_flood = row["precipitation_sum"] >= flood_thresh
        events.append({
            "event_id": new_id(),
            "event_type": "Flood" if is_flood else "RainfallEvent",
            "location": location,
            "country": country,
            "date": d.strftime("%Y-%m-%d"),
            "time_window_start": None,
            "time_window_end": None,
            "metric_value": row["precipitation_sum"],
            "severity": "high" if is_flood else "moderate",
        })

    # --- Heatwave events (multi-day window) ---
    heat_mask = df_loc["temperature_2m_max"] >= heat_thresh
    heat_runs = find_consecutive_runs(heat_mask, HEATWAVE_MIN_DAYS)
    for start, end in heat_runs:
        window_df = df_loc.loc[start:end]
        events.append({
            "event_id": new_id(),
            "event_type": "Heatwave",
            "location": location,
            "country": country,
            "date": None,
            "time_window_start": start.strftime("%Y-%m-%d"),
            "time_window_end": end.strftime("%Y-%m-%d"),
            "metric_value": round(window_df["temperature_2m_max"].max(), 1),
            "severity": "high" if (end - start).days + 1 >= HEATWAVE_MIN_DAYS * 2 else "moderate",
        })

    # --- Isolated hot days (not part of a heatwave run) ---
    heatwave_dates = set()
    for start, end in heat_runs:
        for d in pd.date_range(start, end):
            heatwave_dates.add(d)

    isolated_hot = df_loc[
        (df_loc["temperature_2m_max"] >= isolated_hot_thresh)
        & (~df_loc.index.isin(heatwave_dates))
    ]
    for d, row in isolated_hot.iterrows():
        events.append({
            "event_id": new_id(),
            "event_type": "TemperatureEvent",
            "location": location,
            "country": country,
            "date": d.strftime("%Y-%m-%d"),
            "time_window_start": None,
            "time_window_end": None,
            "metric_value": row["temperature_2m_max"],
            "severity": "moderate",
        })

    # --- Drought events (multi-day window) ---
    drought_mask = df_loc["precipitation_sum"] <= drought_low_thresh
    drought_runs = find_consecutive_runs(drought_mask, DROUGHT_MIN_DAYS)
    for start, end in drought_runs:
        events.append({
            "event_id": new_id(),
            "event_type": "Drought",
            "location": location,
            "country": country,
            "date": None,
            "time_window_start": start.strftime("%Y-%m-%d"),
            "time_window_end": end.strftime("%Y-%m-%d"),
            "metric_value": (end - start).days + 1,
            "severity": "high" if (end - start).days + 1 >= DROUGHT_MIN_DAYS * 2 else "moderate",
        })

    # --- Wind events (single-day) ---
    wind_days = df_loc[df_loc["windspeed_10m_max"] >= wind_thresh]
    for d, row in wind_days.iterrows():
        events.append({
            "event_id": new_id(),
            "event_type": "WindEvent",
            "location": location,
            "country": country,
            "date": d.strftime("%Y-%m-%d"),
            "time_window_start": None,
            "time_window_end": None,
            "metric_value": row["windspeed_10m_max"],
            "severity": "moderate",
        })

    return events


def main():
    df = pd.read_csv(RAW_PATH)

    all_events = []
    for (location, country), group in df.groupby(["location", "country"]):
        loc_events = extract_events_for_location(group)
        all_events.extend(loc_events)
        print(f"{location}, {country}: {len(loc_events)} events extracted")

    events_df = pd.DataFrame(all_events)
    events_df.to_csv(EVENTS_OUTPUT_PATH, index=False)

    print(f"\nTotal events extracted: {len(events_df)}")
    print(events_df["event_type"].value_counts())
    print(f"\nSaved to {EVENTS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
