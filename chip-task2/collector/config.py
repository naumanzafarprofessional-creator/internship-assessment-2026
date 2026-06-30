"""
Configuration for Task 2 - Weather Intelligence Knowledge Graph
Defines locations across Pakistan and neighbouring countries, plus the
historical date range to pull from the Open-Meteo Archive API.
"""

from datetime import date

# 3 years of daily historical data
START_DATE = "2022-06-01"
END_DATE = "2025-05-31"

# (location_name, country, lat, lon)
LOCATIONS = [
    # Pakistan
    ("Lahore", "Pakistan", 31.5497, 74.3436),
    ("Karachi", "Pakistan", 24.8607, 67.0011),
    ("Peshawar", "Pakistan", 34.0151, 71.5249),
    ("Multan", "Pakistan", 30.1575, 71.5249),
    ("Quetta", "Pakistan", 30.1798, 66.9750),

    # India
    ("Amritsar", "India", 31.6340, 74.8723),
    ("Srinagar", "India", 34.0837, 74.7973),
    ("New Delhi", "India", 28.6139, 77.2090),
    ("Jaipur", "India", 26.9124, 75.7873),

    # Afghanistan
    ("Kabul", "Afghanistan", 34.5553, 69.2075),
    ("Kandahar", "Afghanistan", 31.6289, 65.7372),
    ("Herat", "Afghanistan", 34.3482, 62.1997),
    ("Jalalabad", "Afghanistan", 34.4265, 70.4515),

    # Iran
    ("Zahedan", "Iran", 29.4963, 60.8629),
    ("Mashhad", "Iran", 36.2605, 59.6168),
    ("Tehran", "Iran", 35.6892, 51.3890),

    # China (Xinjiang)
    ("Kashgar", "China", 39.4704, 75.9898),
    ("Urumqi", "China", 43.8256, 87.6168),
]

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

DAILY_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "windspeed_10m_max",
    "relative_humidity_2m_mean",
]
