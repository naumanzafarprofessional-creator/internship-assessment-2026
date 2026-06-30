"""
run_queries.py

Executes the six required Task 2 analytical queries against the Neo4j
graph and prints results. Intended to be run live during the video demo.
"""

import os
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")


QUERIES = {
    "Q1: Which locations experienced the highest rainfall?": """
        MATCH (e:WeatherEvent)-[:OCCURRED_IN]->(l:Location)
        WHERE e.event_type IN ['RainfallEvent', 'Flood']
        RETURN l.name AS location, sum(e.metric_value) AS total_rainfall_mm,
               count(e) AS event_count
        ORDER BY total_rainfall_mm DESC
        LIMIT 10
    """,

    "Q2: Which regions experienced multiple extreme weather events?": """
        MATCH (e:WeatherEvent)-[:OCCURRED_IN]->(l:Location)
        WHERE e.severity = 'high'
        RETURN l.name AS location, count(e) AS extreme_event_count,
               collect(DISTINCT e.event_type) AS event_types
        ORDER BY extreme_event_count DESC
        LIMIT 10
    """,

    "Q3: What weather patterns frequently occur together?": """
        MATCH (e1:WeatherEvent)-[:OCCURRED_IN]->(l:Location),
              (e2:WeatherEvent)-[:OCCURRED_IN]->(l)
        WHERE e1.event_id < e2.event_id
          AND e1.event_type <> e2.event_type
        WITH e1.event_type AS type1, e2.event_type AS type2, count(*) AS co_occurrences
        WHERE co_occurrences > 5
        RETURN type1, type2, co_occurrences
        ORDER BY co_occurrences DESC
        LIMIT 10
    """,

    "Q4: Which climate indicators show increasing trends?": """
        MATCH (i:ClimateIndicator)
        WITH i.country AS country, i.event_type AS event_type,
             i.year AS year, i.frequency AS frequency
        ORDER BY country, event_type, year
        WITH country, event_type, collect({year: year, freq: frequency}) AS series
        WHERE size(series) >= 2
        RETURN country, event_type, series
        LIMIT 15
    """,

    "Q5: Which locations appear most vulnerable to extreme weather?": """
        MATCH (e:WeatherEvent)-[:OCCURRED_IN]->(l:Location)-[:IN_COUNTRY]->(c:Country)
        WHERE e.severity = 'high'
        WITH l.name AS location, c.name AS country, count(e) AS high_severity_count
        RETURN location, country, high_severity_count
        ORDER BY high_severity_count DESC
        LIMIT 10
    """,

    "Q6: Do extreme weather events in neighbouring countries precede related events in Pakistan, and by what lag?": """
        MATCH (n:WeatherEvent)-[u:UPSTREAM_OF]->(p:WeatherEvent)
        MATCH (n)-[:OCCURRED_IN]->(nl:Location)-[:IN_COUNTRY]->(nc:Country)
        MATCH (p)-[:OCCURRED_IN]->(pl:Location)
        RETURN nc.name AS neighbour_country, nl.name AS neighbour_location,
               n.event_type AS neighbour_event_type,
               pl.name AS pakistan_location, p.event_type AS pakistan_event_type,
               u.lag_days AS lag_days, avg(u.lag_days) AS avg_lag
        ORDER BY lag_days
        LIMIT 15
    """,
}


def run_all():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            for label, query in QUERIES.items():
                print("=" * 80)
                print(label)
                print("=" * 80)
                result = session.run(query)
                rows = list(result)
                if not rows:
                    print("  (no results)")
                for row in rows:
                    print(" ", dict(row))
                print()
    finally:
        driver.close()


if __name__ == "__main__":
    run_all()
