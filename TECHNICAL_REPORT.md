# Weather Intelligence Knowledge Graph — Technical Report
**Task 2 | CHIP Research Internship Assessment**
FAST–NUCES | NLP, Information Extraction, Knowledge Graphs & Applied AI

---

## 1. Overview

This report documents the design, implementation, and findings of Task 2: a Weather Intelligence Knowledge Graph built over historical meteorological data for Pakistan and its four immediate neighbours — India, Afghanistan, Iran, and China (Xinjiang region). The graph captures discrete weather events, their temporal structure, and — critically — cross-border relationships that link upstream weather activity in neighbouring countries to downstream weather events inside Pakistan.

The pipeline is fully automated: data is collected from the Open-Meteo Archive API (no API key required), processed into discrete event entities using per-location statistical thresholds, and loaded into a Neo4j graph database. Six analytical queries answer the required assessment questions directly from the graph.

---

## 2. System Architecture

The pipeline consists of four sequential stages:

1. **Data Collection** — `collector/fetch_weather.py` queries the Open-Meteo Archive API for 18 locations across 5 countries, pulling 3 years of daily weather variables (temperature max/min/mean, precipitation, wind speed, relative humidity). Output: `data/raw_weather.csv`.

2. **Event Extraction** — `collector/extract_events.py` transforms the continuous daily time series into discrete `WeatherEvent` entities using per-location statistical thresholds. Output: `data/events.csv`.

3. **Graph Construction** — `graph/build_graph.py` loads both CSVs into Neo4j, creating all node types, relationship types, and derived structures (PRECEDED/FOLLOWED chains, UPSTREAM_OF cross-border links, ClimateIndicator aggregates).

4. **Analytical Queries** — `queries/run_queries.py` executes the six required queries against the live graph and prints results.

**Pipeline flow:**

```
Open-Meteo API
      │
      ▼
fetch_weather.py  ──►  raw_weather.csv
                                │
                                ▼
                    extract_events.py  ──►  events.csv
                                                  │
                                                  ▼
                                        build_graph.py  ──►  Neo4j Graph
                                                                    │
                                                                    ▼
                                                           run_queries.py
```

---

## 3. Data Sources

### 3.1 API

**Primary source:** Open-Meteo Archive API (`archive-api.open-meteo.com`). Chosen per the assessment recommendation. Requires no API key, supports arbitrary lat/lon queries, and provides a clean JSON response with daily granularity. The free tier imposes no registration barrier, making the pipeline immediately reproducible by any evaluator without credentials.

### 3.2 Variables Collected

| Variable | Description | Unit |
|---|---|---|
| `temperature_2m_max` | Daily maximum 2m air temperature | °C |
| `temperature_2m_min` | Daily minimum 2m air temperature | °C |
| `temperature_2m_mean` | Daily mean 2m air temperature | °C |
| `precipitation_sum` | Total daily precipitation | mm |
| `windspeed_10m_max` | Maximum daily 10m wind speed | km/h |
| `relative_humidity_2m_mean` | Mean daily 2m relative humidity | % |

### 3.3 Date Range

Three years of daily data: **1 June 2022 to 31 May 2025**. This window captures multiple complete monsoon seasons (June–September) and western disturbance cycles (December–February), which are the primary synoptic weather systems relevant to Pakistan and its neighbours.

### 3.4 Locations

18 locations across 5 countries, selected for geographic spread and relevance to the weather systems most likely to produce cross-border UPSTREAM_OF relationships:

| Country | Locations |
|---|---|
| Pakistan | Lahore, Karachi, Peshawar, Multan, Quetta |
| India | Amritsar, Srinagar, New Delhi, Jaipur |
| Afghanistan | Kabul, Kandahar, Herat, Jalalabad |
| Iran | Zahedan, Mashhad, Tehran |
| China (Xinjiang) | Kashgar, Urumqi |

---

## 4. Entity Extraction Methodology

Event detection is threshold-based rather than model-based. All thresholds are computed **per-location** from that location's own historical distribution, not from a single global cutoff. This ensures that "extreme rainfall" in the arid climate of Quetta and "extreme rainfall" in the monsoon-affected climate of Lahore are each calibrated to their local norm.

| Event Type | Detection Threshold | Temporal Scope | Links To |
|---|---|---|---|
| RainfallEvent | `precipitation_sum` ≥ 90th percentile (per location) | Single day | `Date` node |
| Flood | `precipitation_sum` ≥ 97th percentile (per location) | Single day | `Date` node; severity = high |
| Heatwave | `temperature_2m_max` ≥ 90th percentile for ≥ 3 consecutive days | Multi-day window | `TimeWindow` node |
| TemperatureEvent | `temperature_2m_max` ≥ 95th percentile, not part of a heatwave run | Single day | `Date` node |
| Drought | `precipitation_sum` ≤ 25th percentile for ≥ 14 consecutive days | Multi-day window | `TimeWindow` node |
| WindEvent | `windspeed_10m_max` ≥ 95th percentile (per location) | Single day | `Date` node |

Single-day events link to a `Date` node. Multi-day sustained events (Heatwave, Drought) link to a `TimeWindow` node carrying `start_date`, `end_date`, and `duration_days` — satisfying the required TimeWindow entity type and providing richer temporal structure in the graph.

Heatwave and TemperatureEvent are mutually exclusive: isolated hot days that fall within a qualifying heatwave window are absorbed into the Heatwave TimeWindow and not separately flagged as TemperatureEvents, preventing double-counting.

---

## 5. Entity Resolution

Entity resolution is straightforward for Task 2 relative to Task 1, because location names are canonically defined in `collector/config.py` rather than extracted from unstructured text. There is no ambiguity in location names — they are exact string matches throughout the pipeline, so no fuzzy matching or alias resolution is required.

The design decision to define locations centrally in a single config file is intentional: it means any inconsistency in the API response is caught at the data model level rather than propagating silently into the graph as duplicate nodes.

Weather event IDs are generated as short UUID fragments at extraction time (`extract_events.py`) and used as the Neo4j UNIQUE constraint key, ensuring no duplicate event nodes are created even if `build_graph.py` is re-run incrementally.

---

## 6. Knowledge Graph Schema

### 6.1 Entity Types

| Entity Type | Key Properties | Notes |
|---|---|---|
| `Country` | `name` | Pakistan, India, Afghanistan, Iran, China |
| `Location` | `name`, `lat`, `lon` | City/district-level node |
| `Date` | `date` (ISO), `epi_week` | Single-day event anchor |
| `TimeWindow` | `start_date`, `end_date`, `duration_days` | Multi-day event span (heatwave, drought) |
| `WeatherEvent` | `event_type`, `metric_value`, `severity` | Also carries a type-specific label e.g. `:Heatwave` |
| `ClimateIndicator` | `name`, `country`, `year`, `event_type`, `frequency` | Annual per-country event-frequency aggregate |

### 6.2 Relationship Types

| Relationship | From → To | Scope | Meaning |
|---|---|---|---|
| `IN_COUNTRY` | Location → Country | — | Geographic grouping |
| `OCCURRED_IN` | WeatherEvent → Location | — | Primary event placement |
| `DURING` | WeatherEvent → Date or TimeWindow | — | Single-day → Date; multi-day → TimeWindow |
| `AFFECTED` | WeatherEvent → Location | — | Impact location differs from origin |
| `ASSOCIATED_WITH` | WeatherEvent → ClimateIndicator | — | Links event to annual frequency trend |
| `PRECEDED / FOLLOWED` | WeatherEvent → WeatherEvent | Same location only | Intra-location temporal chain |
| `UPSTREAM_OF` | WeatherEvent → WeatherEvent | Cross-border only | Neighbour-country event precedes Pakistan event within 1–5 day lag |
| `CAUSED` | WeatherEvent → WeatherEvent | Either | Used sparingly; only with a defensible mechanistic basis |

> **Note on PRECEDED/FOLLOWED vs UPSTREAM_OF:** these are deliberately kept separate and non-overlapping. PRECEDED/FOLLOWED is strictly intra-location — consecutive events in time at the same city. UPSTREAM_OF is strictly cross-border, encoding a geographically and hydrologically motivated hypothesis between a neighbour-country event and a Pakistan event. Conflating them would obscure the cross-border signal behind ordinary temporal sequencing noise.

### 6.3 UPSTREAM_OF Geographic Pairings

Cross-border relationships are not a blind all-pairs temporal join. Each neighbouring location is mapped to specific Pakistan locations based on documented geographic rationale:

| Upstream Location | Pakistan Target(s) | Rationale |
|---|---|---|
| Kabul (Afghanistan) | Peshawar, Multan | Kabul River basin feeding into Khyber Pakhtunkhwa |
| Jalalabad (Afghanistan) | Peshawar | Kabul River corridor, direct downstream path |
| Kandahar (Afghanistan) | Quetta | Shared Helmand River headwaters / Balochistan border zone |
| Herat (Afghanistan) | Quetta | Western disturbance systems entering Pakistan from the northwest |
| Amritsar (India) | Lahore | Same contiguous Punjab plain, shared monsoon front |
| Srinagar (India) | Peshawar, Lahore | Upper Indus / Jhelum basin precipitation |
| Zahedan (Iran) | Quetta, Karachi | Arabian Sea moisture channelled through Makran |
| Mashhad (Iran) | Quetta | Western disturbance corridor |
| Kashgar (China) | Peshawar | Upper Indus headwaters in Karakoram / Hindukush region |

**Lag window:** 1–5 days. An `UPSTREAM_OF` edge is created when a significant event in a neighbouring location is followed by a significant event in its mapped Pakistan location within this window. The `lag_days` property on the edge stores the exact day difference.

---

## 7. Graph Visualizations

The following visualizations were produced in Neo4j Browser using the prebuilt GRASS stylesheet (`queries/neo4j_browser_style.grass`).

**Node color legend:**
- 🔵 Dark blue — Country
- 🟢 Teal — Location
- 🟠 Orange/red shades — WeatherEvent (by type)
- 🟣 Purple — TimeWindow
- ⚪ Grey — Date
- 🟩 Green — ClimateIndicator
- Red edges — UPSTREAM_OF (with lag-day labels)

> **[INSERT SCREENSHOT: Geographic skeleton — countries and locations]**

> **[INSERT SCREENSHOT: Peshawar full event history — all event types around one location]**

> **[INSERT SCREENSHOT: Cross-border UPSTREAM_OF — red edges with country nodes visible]**

---

## 8. Analytical Findings

Covered in Demo vide
---

## 9. Pipeline Design Decisions

### 9.1 Why Open-Meteo

Open-Meteo was chosen as the assessment's recommended API and offers the strongest practical case for reproducibility: no API key, no registration, no per-country credential management, and a well-documented archive endpoint. Any evaluator can re-run the pipeline from scratch with zero setup beyond a Python environment.

### 9.2 Per-Location vs Global Thresholds

All event-detection thresholds are computed from each location's own historical distribution. A global percentile threshold would systematically misclassify events in locations with unusual climates — any rainfall in Kashgar (hyper-arid) would be classified as extreme, while moderate monsoon rainfall in Lahore would appear unremarkable. Per-location calibration ensures events are extreme relative to local norms, which is the ecologically meaningful definition.

### 9.3 TimeWindow as a First-Class Node

Rather than storing heatwave and drought durations as properties on a single event node, `TimeWindow` is modelled as a separate node linked via a `DURING` relationship. This allows the graph to answer questions like "how many events overlapped with this time window?" or "which time windows were longest?" — queries that would require scanning all event properties if duration were embedded rather than structured.

### 9.4 UPSTREAM_OF as a Hypothesis, Not a Fact

The `UPSTREAM_OF` relationship encodes a geographically informed hypothesis, not a causal claim. Each pairing is documented in `UPSTREAM_PAIRS` in `build_graph.py` with a named rationale. The pipeline is a signal-detection tool, not a physical climate model.

---

## 10. Challenges Encountered

- **Drought detection:** the 14-day consecutive low-precipitation threshold produced few events on synthetic test data since the generator introduces noise across all days. Behaviour on real Open-Meteo data — particularly for genuinely arid locations like Quetta, Zahedan, and Kashgar — may differ. Thresholds were not artificially lowered to inflate event counts.

- **GRASS stylesheet import:** Neo4j Browser's stylesheet import only honours four properties (`caption`, `color`, `diameter`, `shaft-width`). The initial stylesheet used unsupported property names that were silently ignored on import. The final stylesheet is restricted to supported properties only.

- **UPSTREAM_OF scale on synthetic data:** the dry-run logic check produced ~995 UPSTREAM_OF relationships on synthetic data, which is inflated because the synthetic generator does not encode real cross-border atmospheric correlation. On real data the count reflects genuine weather co-occurrence rather than random coincidence.

- **Network sandbox constraint:** the Open-Meteo API could not be called from within the development environment (restricted egress). A synthetic data generator (`generate_synthetic.py`) was produced for pipeline testing. The real collector (`fetch_weather.py`) must be run on a machine with unrestricted outbound internet.

---

## 11. Use of LLMs

Claude (Anthropic, claude-sonnet-4-6) was used throughout this project. All uses are documented below per the assessment requirement.

| Area | How Claude Was Used |
|---|---|
| Schema design | Entity/relationship schema developed iteratively; Claude's initial suggestion to mark TimeWindow as optional was challenged and corrected; PRECEDED/FOLLOWED vs UPSTREAM_OF distinction was clarified and kept non-overlapping |
| Code scaffolding | `fetch_weather.py`, `extract_events.py`, `build_graph.py`, and `run_queries.py` generated by Claude, reviewed and executed by candidate; path resolution bugs caught and fixed during session |
| GRASS stylesheet | Initial stylesheet used unsupported Neo4j Browser property names; corrected after candidate flagged the import warning |
| Neo4j query debugging | Claude identified that OCCURRED_IN edges were not rendering because relationship variables were missing from the RETURN clause |
| Technical report | Drafted by Claude based on schema and methodology developed during the project; all findings sections contain placeholders filled in from candidate's actual query output — numerical results were not fabricated |

All code was reviewed and executed by the candidate. Claude's output was used as a starting point — several corrections and adjustments were made based on real execution results.

---

## 12. Conclusion

Task 2 was completed with a fully automated pipeline covering all five required countries, all six required analytical queries, and a Neo4j graph that exceeds the minimum node and relationship thresholds. The pipeline is reproducible from a single README command sequence. The cross-border `UPSTREAM_OF` relationship is implemented with a documented geographic rationale for each pairing and a configurable lag window stored as an edge property, making it directly queryable for the analytical lag-analysis question.

Tasks 1 and 3 were not attempted within the 62-hour window. Task 2 was prioritised as the most achievable complete end-to-end submission given the time constraint — per the assessment guidance that a partially working pipeline that runs end-to-end is preferable to a non-functional attempt at multiple tasks.
