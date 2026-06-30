"""
fetch_weather.py

Collects historical daily weather data from the Open-Meteo Archive API
for all locations defined in config.py, and saves the combined raw
dataset as a single CSV for downstream event-extraction.

No API key required. Open-Meteo archive endpoint: archive-api.open-meteo.com
"""

import time
import os
import requests
import pandas as pd

from config import (
    LOCATIONS,
    START_DATE,
    END_DATE,
    OPEN_METEO_ARCHIVE_URL,
    DAILY_VARIABLES,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "..", "data", "raw_weather.csv")


def fetch_location(name: str, country: str, lat: float, lon: float) -> pd.DataFrame:
    """Fetch daily historical weather data for a single location."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "auto",
    }

    resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=60)
    resp.raise_for_status()
    payload = resp.json()

    daily = payload.get("daily", {})
    if not daily or "time" not in daily:
        print(f"  WARNING: no daily data returned for {name}, {country}")
        return pd.DataFrame()

    df = pd.DataFrame(daily)
    df.rename(columns={"time": "date"}, inplace=True)
    df["location"] = name
    df["country"] = country
    df["lat"] = lat
    df["lon"] = lon

    return df


def main():
    all_frames = []

    for i, (name, country, lat, lon) in enumerate(LOCATIONS, start=1):
        print(f"[{i}/{len(LOCATIONS)}] Fetching {name}, {country} ...")
        try:
            df = fetch_location(name, country, lat, lon)
            if not df.empty:
                all_frames.append(df)
                print(f"  -> {len(df)} daily records")
        except requests.exceptions.RequestException as e:
            print(f"  ERROR fetching {name}, {country}: {e}")

        # Be polite to the free API; avoid hammering it
        time.sleep(1)

    if not all_frames:
        raise RuntimeError("No data was successfully fetched for any location.")

    combined = pd.concat(all_frames, ignore_index=True)
    combined.sort_values(["country", "location", "date"], inplace=True)
    combined.to_csv(OUTPUT_PATH, index=False)

    print(f"\nDone. Saved {len(combined)} total daily records to {OUTPUT_PATH}")
    print(f"Locations covered: {combined['location'].nunique()}")
    print(f"Countries covered: {combined['country'].nunique()}")
    print(f"Date range: {combined['date'].min()} to {combined['date'].max()}")


if __name__ == "__main__":
    main()
