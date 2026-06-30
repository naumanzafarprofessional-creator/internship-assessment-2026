"""
build_graph.py

Loads the extracted events (events.csv) and raw location/country metadata
into Neo4j, constructing the full knowledge graph per the Task 2 schema:

Nodes: Country, Location, Date, TimeWindow, WeatherEvent, ClimateIndicator
Relationships: IN_COUNTRY, OCCURRED_IN, DURING, AFFECTED, ASSOCIATED_WITH,
                PRECEDED, FOLLOWED, UPSTREAM_OF

Requires a running Neo4j instance. Set connection details via environment
variables.

    NEO4J_URI=bolt://localhost:7687
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=<your password>
"""

import os
import pandas as pd
from neo4j import GraphDatabase

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(SCRIPT_DIR, "..", "data", "raw_weather.csv")
EVENTS_PATH = os.path.join(SCRIPT_DIR, "..", "data", "events.csv")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

# Geographic "upstream" pairing: (neighbour_country, pakistan-relevant rationale)
# Used to constrain which cross-border event pairs are eligible for UPSTREAM_OF,
# rather than naively linking every neighbouring event to every Pakistan event.
UPSTREAM_LAG_DAYS = (1, 5)  # min/max lag window in days

# Each neighbouring location is mapped to the Pakistan location(s) it is most
# plausibly hydrologically/meteorologically upstream of. This is a simplification
# (real atmospheric/river-basin modelling is out of scope) but gives a defensible,
# documented basis for the UPSTREAM_OF relationship rather than an arbitrary
# all-pairs join.
UPSTREAM_PAIRS = {
    "Kabul": ["Peshawar", "Multan"],
    "Jalalabad": ["Peshawar"],
    "Kandahar": ["Quetta"],
    "Herat": ["Quetta"],
    "Amritsar": ["Lahore"],
    "Srinagar": ["Peshawar", "Lahore"],
    "Zahedan": ["Quetta", "Karachi"],
    "Mashhad": ["Quetta"],
    "Kashgar": ["Peshawar"],
}


class GraphBuilder:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def reset(self):
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def create_constraints(self):
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Location) REQUIRE l.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Date) REQUIRE d.date IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:WeatherEvent) REQUIRE e.event_id IS UNIQUE",
        ]
        with self.driver.session() as session:
            for c in constraints:
                session.run(c)

    def load_countries_and_locations(self, raw_df: pd.DataFrame):
        loc_df = raw_df[["location", "country", "lat", "lon"]].drop_duplicates()
        with self.driver.session() as session:
            for country in loc_df["country"].unique():
                session.run(
                    "MERGE (c:Country {name: $name})", name=country
                )
            for _, row in loc_df.iterrows():
                session.run(
                    """
                    MERGE (l:Location {name: $name})
                    SET l.lat = $lat, l.lon = $lon
                    WITH l
                    MATCH (c:Country {name: $country})
                    MERGE (l)-[:IN_COUNTRY]->(c)
                    """,
                    name=row["location"], lat=row["lat"], lon=row["lon"], country=row["country"],
                )
        print(f"Loaded {loc_df['country'].nunique()} countries, {len(loc_df)} locations")

    def load_events(self, events_df: pd.DataFrame):
        with self.driver.session() as session:
            for _, row in events_df.iterrows():
                # Create the WeatherEvent node with a type-specific extra label
                # (e.g. :WeatherEvent:Heatwave) to satisfy the spec's distinct
                # entity types while keeping a common generic label for queries.
                session.run(
                    f"""
                    MERGE (e:WeatherEvent:{row['event_type']} {{event_id: $event_id}})
                    SET e.event_type = $event_type,
                        e.metric_value = $metric_value,
                        e.severity = $severity
                    WITH e
                    MATCH (l:Location {{name: $location}})
                    MERGE (e)-[:OCCURRED_IN]->(l)
                    """,
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    metric_value=float(row["metric_value"]),
                    severity=row["severity"],
                    location=row["location"],
                )

                if pd.notna(row["date"]):
                    session.run(
                        """
                        MERGE (d:Date {date: $date})
                        WITH d
                        MATCH (e:WeatherEvent {event_id: $event_id})
                        MERGE (e)-[:DURING]->(d)
                        """,
                        date=row["date"], event_id=row["event_id"],
                    )
                elif pd.notna(row["time_window_start"]):
                    tw_id = f"{row['time_window_start']}_{row['time_window_end']}_{row['location']}"
                    session.run(
                        """
                        MERGE (t:TimeWindow {window_id: $tw_id})
                        SET t.start_date = $start, t.end_date = $end
                        WITH t
                        MATCH (e:WeatherEvent {event_id: $event_id})
                        MERGE (e)-[:DURING]->(t)
                        """,
                        tw_id=tw_id,
                        start=row["time_window_start"],
                        end=row["time_window_end"],
                        event_id=row["event_id"],
                    )
        print(f"Loaded {len(events_df)} weather events")

    def load_preceded_followed(self, events_df: pd.DataFrame):
        """Same-location temporal chains: for each location, order events by
        their effective date and link consecutive PRECEDED/FOLLOWED pairs."""
        events_df = events_df.copy()
        events_df["effective_date"] = events_df["date"].fillna(events_df["time_window_start"])
        events_df["effective_date"] = pd.to_datetime(events_df["effective_date"])

        count = 0
        with self.driver.session() as session:
            for location, group in events_df.groupby("location"):
                group = group.sort_values("effective_date")
                ids = group["event_id"].tolist()
                for i in range(len(ids) - 1):
                    session.run(
                        """
                        MATCH (e1:WeatherEvent {event_id: $id1})
                        MATCH (e2:WeatherEvent {event_id: $id2})
                        MERGE (e1)-[:PRECEDED]->(e2)
                        MERGE (e2)-[:FOLLOWED]->(e1)
                        """,
                        id1=ids[i], id2=ids[i + 1],
                    )
                    count += 1
        print(f"Loaded {count} PRECEDED/FOLLOWED pairs (same-location)")

    def load_upstream_relationships(self, events_df: pd.DataFrame):
        """Cross-border UPSTREAM_OF: link significant events (Flood, Heatwave,
        high-severity RainfallEvent) in neighbouring locations to related
        events in their mapped Pakistan location(s) within a lag window."""
        events_df = events_df.copy()
        events_df["effective_date"] = events_df["date"].fillna(events_df["time_window_start"])
        events_df["effective_date"] = pd.to_datetime(events_df["effective_date"])

        significant_types = ["Flood", "RainfallEvent", "Heatwave"]
        sig_events = events_df[events_df["event_type"].isin(significant_types)]

        count = 0
        with self.driver.session() as session:
            for neighbour_loc, pak_locs in UPSTREAM_PAIRS.items():
                neighbour_events = sig_events[sig_events["location"] == neighbour_loc]
                for pak_loc in pak_locs:
                    pak_events = sig_events[sig_events["location"] == pak_loc]

                    for _, n_ev in neighbour_events.iterrows():
                        lag_lo = n_ev["effective_date"] + pd.Timedelta(days=UPSTREAM_LAG_DAYS[0])
                        lag_hi = n_ev["effective_date"] + pd.Timedelta(days=UPSTREAM_LAG_DAYS[1])

                        matches = pak_events[
                            (pak_events["effective_date"] >= lag_lo)
                            & (pak_events["effective_date"] <= lag_hi)
                        ]
                        for _, p_ev in matches.iterrows():
                            session.run(
                                """
                                MATCH (e1:WeatherEvent {event_id: $id1})
                                MATCH (e2:WeatherEvent {event_id: $id2})
                                MERGE (e1)-[:UPSTREAM_OF {lag_days: $lag}]->(e2)
                                """,
                                id1=n_ev["event_id"],
                                id2=p_ev["event_id"],
                                lag=(p_ev["effective_date"] - n_ev["effective_date"]).days,
                            )
                            count += 1
        print(f"Loaded {count} UPSTREAM_OF relationships")

    def load_climate_indicators(self, events_df: pd.DataFrame):
        """Derive simple ClimateIndicator nodes: per-country, per-year event
        frequency for each event type, linked via ASSOCIATED_WITH. This gives
        a queryable trend signal for 'which indicators show increasing trends'."""
        events_df = events_df.copy()
        events_df["effective_date"] = events_df["date"].fillna(events_df["time_window_start"])
        events_df["year"] = pd.to_datetime(events_df["effective_date"]).dt.year

        count = 0
        with self.driver.session() as session:
            for (country, year, event_type), group in events_df.groupby(["country", "year", "event_type"]):
                indicator_name = f"{country}_{event_type}_annual_frequency_{year}"
                session.run(
                    """
                    MERGE (i:ClimateIndicator {name: $name})
                    SET i.country = $country, i.year = $year,
                        i.event_type = $event_type, i.frequency = $freq
                    """,
                    name=indicator_name, country=country, year=int(year),
                    event_type=event_type, freq=len(group),
                )
                for event_id in group["event_id"]:
                    session.run(
                        """
                        MATCH (e:WeatherEvent {event_id: $event_id})
                        MATCH (i:ClimateIndicator {name: $name})
                        MERGE (e)-[:ASSOCIATED_WITH]->(i)
                        """,
                        event_id=event_id, name=indicator_name,
                    )
                count += 1
        print(f"Loaded {count} ClimateIndicator nodes with ASSOCIATED_WITH links")


def main():
    raw_df = pd.read_csv(RAW_PATH)
    events_df = pd.read_csv(EVENTS_PATH)

    builder = GraphBuilder(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    try:
        print("Resetting database...")
        builder.reset()
        builder.create_constraints()

        builder.load_countries_and_locations(raw_df)
        builder.load_events(events_df)
        builder.load_preceded_followed(events_df)
        builder.load_upstream_relationships(events_df)
        builder.load_climate_indicators(events_df)

        print("\nGraph build complete.")
    finally:
        builder.close()


if __name__ == "__main__":
    main()
