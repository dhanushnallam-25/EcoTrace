# EcoTrace — River Pollution Investigation & Response Planner

EcoTrace is a Streamlit app for Karnataka surface water. It screens CPCB water-quality readings, links monitoring stations into a directed river graph built from **HydroRIVERS** topology, and uses hand-written data structures to prioritise and investigate pollution incidents:

* **DirectedRiverGraph:** adjacency lists in both directions.
* **BFS:** downstream impact.
* **DFS:** upstream candidates.
* **MaxHeap:** incident priority.

> **Scope statement.** EcoTrace is an *investigation-support* tool. Its flags are screening signals for follow-up. They are **not proof** of a pollution source or of a regulatory breach.

---

## 1. Quick start (Windows)

```powershell
# 1. (optional) create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. run the app  ->  http://localhost:8501
streamlit run app.py

# 4. tests (synthetic fixtures) and the real-data smoke test
python -m pytest -v
python smoke_test.py

# 5. regenerate benchmark CSVs (data/processed/benchmark_*.csv)
python -m backend.complexity_benchmark
```

On first launch the app finds the bundled files in `files/` and **auto-loads** them. The **Load Default Karnataka CPCB + HydroRIVERS Dataset** button in the sidebar (and on *Dataset Management*) reloads them in one click. The first run clips the 100 MB Asia HydroRIVERS geodatabase to Karnataka and caches it as GeoParquet (about 3 s). Later runs of the whole pipeline take about 2 s.

### Input files (`files/`)
| File | Content | Label in app |
|---|---|---|
| `swq_chemical_parameter_manual_cpcb_ka_2021_2025 (1).csv` | CPCB manual chemical parameters, Karnataka (NWDP) | Government data |
| `swq_biological_parameter_manual_cpcb_ka_2021_2025.csv` | CPCB manual biological parameters (BOD, COD, coliforms) | Government data |
| `HydroRIVERS_v10_as.gdb.zip` | HydroRIVERS v1.0 Asia (Lehner & Grill 2013) | Government/academic reference data |

Discovery is pattern-based (`*chemical*.csv`, `*biological*.csv`, `HydroRIVERS*.zip`), so small renames such as the `(1)` suffix still work. Users can also **upload** Chemical, Biological and optional Physical CSVs plus a HydroRIVERS GDB/Shapefile ZIP on *Dataset Management*. Uploads are saved untouched in `data/uploads/`. `data/sample_test_data/` holds a small, clearly labelled **synthetic** pair of CSVs for trying the upload flow.

---

## 2. Architecture

```
                         ┌──────────────────────── Streamlit UI (app.py + frontend/) ───────────────────────┐
                         │ Dashboard · Dataset · River Explorer · Pollution · Heap · Investigation ·        │
                         │ Response Planner · Reports & Benchmarks          (Plotly charts, Folium maps)    │
                         └───────────────▲──────────────────────────────────────────────▲────────────────────┘
                                         │ PipelineState (cached per files+config)       │ live BFS/DFS/heap ops
┌────────────── backend/ ────────────────┴───────────────────────────────────────────────┴──────────────────┐
│ data_ingestion ─► schema_mapper ─► data_cleaning ─► station_manager ─► graph_builder ─► river_graph       │
│   (raw strings)    (aliases)        (quarantine,      (IDs, type,        (snap ≤1.5 km,    (dict adjacency, │
│                                       dedup, merge)    modal coords)      NEXT_DOWN walk)   forward+reverse) │
│                                                                                │                          │
│ pollution_detection (CPCB rules + modified-z/IQR) ─► incident_scoring (5 components) ─► max_heap          │
│ bfs (downstream)  dfs (upstream)  impact_analysis  investigation_engine  response_planner  report_generator│
│ complexity_benchmark (perf_counter + tracemalloc)          pipeline (orchestration + exports)             │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────┘
utils/  config (paths, PipelineConfig) · constants (aliases, CPCB criteria, plausibility) · validation · helpers
```

### Data-flow diagram (DFD level 1)

```
[CPCB chemical CSV]──┐
[CPCB biological CSV]┼─► (1) Ingest as raw strings ─► (2) Map schema ─► (3) Clean ──► D1 records_clean.csv
[Physical CSV (opt)]─┘                                                     │  └──────► D2 quarantine.csv
                                                                           ▼
[HydroRIVERS GDB zip] ─► (4) Clip to Karnataka bbox ─► D3 GeoParquet cache │
                                   │                                       ▼
                                   └──────────────► (5) Build station registry + snap + NEXT_DOWN walk
                                                                           │──► D4 stations.csv, river_edges.csv
                                                                           ▼
                                        (6) Screen thresholds + anomalies ─► (7) Score incidents ─► D5 incidents.csv
                                                                           ▼
                         (8) MaxHeap ranking ─► (9) Investigate (DFS/BFS) ─► (10) Respond (status, notes) ─► D6 response_log.json
                                                                           ▼
                                                              (11) Reports (CSV / Markdown / HTML)
```

---

## 3. Module overview

| Module | Responsibility |
|---|---|
| `backend/data_ingestion.py` | Default-file discovery, upload persistence, CSV read with `dtype=str`, HydroRIVERS bbox read (pushed down to GDAL) + GeoParquet cache |
| `backend/schema_mapper.py` | Raw header → canonical name via normalised aliases; unknown columns kept as slug-named parameters |
| `backend/data_cleaning.py` | Day-first date parsing, `pd.to_numeric(errors="coerce")`, malformed-string & impossible-value quarantine with SlNo, dedup, one-to-one merge, parameter coverage |
| `backend/station_manager.py` | Station registry (`KA-001`…), lake/river/unknown classification, modal coordinate, multi-coordinate flags |
| `backend/river_graph.py` | `DirectedRiverGraph`: `forward_adj`, `reverse_adj`, edge set, vertex metadata |
| `backend/graph_builder.py` | Snap river stations to reaches (`sjoin_nearest`, metric CRS) → edges from `NEXT_DOWN` topology only |
| `backend/bfs.py` / `dfs.py` | Manual BFS (deque) downstream, iterative DFS (stack) upstream with branch paths and caveats |
| `backend/max_heap.py` | Array MaxHeap with index map: insert, extract_max, peek, heapify, update_priority, display_heap, top_k |
| `backend/pollution_detection.py` | CPCB rule exceedance + direction-aware modified-z / IQR anomalies |
| `backend/incident_scoring.py` | 5-component explainable score, per-incident breakdown, rescoring |
| `backend/impact_analysis.py` | BFS downstream counts, nearest-in-time readings |
| `backend/investigation_engine.py` | DFS + BFS + history → plain-English narrative + limitations |
| `backend/response_planner.py` | Status workflow, notes (JSON-persisted), heap-ordered action queue, routing notice |
| `backend/report_generator.py` | Incident CSV, Markdown report, printable HTML report |
| `backend/complexity_benchmark.py` | List vs matrix, heap vs sort, BFS/DFS scaling |
| `backend/pipeline.py` | Orchestration, `PipelineState`, processed-data export + `provenance.json` |
| `frontend/*.py` | One module per page; `styles.py` (theme), `common.py` (caching, maps) |

---

## 4. How the real data is handled (verified by `smoke_test.py`)

| Empirical property | Handling | Result on bundled data |
|---|---|---|
| Date range | computed from the data (`DD-MM-YYYY HH:MM`, day-first only) | 2021-01-01 → 2021-12-31 |
| 3,019 rows per table, 269 stations | counted, never hard-coded | 3,019 merged records |
| 15 `(Station, Time)` pairs at different coordinates | dedup on `(station, timestamp, lat, lon)`; distinct sampling points kept and reported | 0 exact duplicates removed, 15 pairs kept |
| Merge chemical + biological | outer merge with `validate="one_to_one"` → no Cartesian join | 3,019 rows, SlNo refs from both tables |
| SlNo 2300: DO `3.16.2`, NH₃ `0.41.83`, pH `78.2` | malformed → quarantine; pH outside 0–14 → quarantine; value set to NaN (never 0), raw string + SlNo kept | 3 quarantined values |
| Sparse parameters | parameter is *active* only if ≥ 10% populated (configurable); completeness is scored against active parameters only | 6 active: pH 99.8%, BOD 96.9%, DO 96.7%, TC 57.1%, NH₃-N 55.9%, FC 33.5%. SAR (6.7%), COD and 22 metal/ion columns (≤ 0.1%) are not scored |
| River/Basin columns all `-` | treated as missing; topology comes from HydroRIVERS | — |
| Lakes vs rivers | name-based classification (lake words checked first) | 157 lake/tank, 110 river-type, 2 unknown |
| Spatial matching | river-type stations snapped ≤ 1.5 km (UTM 43N) to the nearest reach; lakes, unknown-type and farther stations stay isolated | 102 snapped, 8 unmatched |
| Edges | only from `NEXT_DOWN` pointers between snapped stations, never from proximity | 90 directed edges, every vertex out-degree ≤ 1 |

HydroRIVERS lines are digitised in flow direction. I checked this empirically: the last vertex of a reach touches its `NEXT_DOWN` reach in 2,946 of 2,946 tested reaches. A station's distance to the outlet is therefore `DIST_DN_KM + (1 − f) · LENGTH_KM`, where `f` is its fractional position along the reach.

---

## 5. DSA design and complexity

| Structure / algorithm | Implementation | Time | Space |
|---|---|---|---|
| `DirectedRiverGraph` | `dict[str, list]` forward + reverse adjacency, `set` of edges | add vertex/edge O(1) avg; neighbours O(deg) | O(V + E) |
| BFS downstream | `collections.deque`, visited set, level map | O(V + E) | O(V) |
| DFS upstream | explicit stack (no recursion limit), parent pointers → branch paths | O(V + E) | O(V) |
| NEXT_DOWN walk | hash-map pointer chasing over reaches | O(path length) per station | O(R) |
| MaxHeap | list + `incident_id → index` map; sift-up / sift-down | insert / extract / update O(log I); peek O(1); heapify O(I) | O(I) |
| Incident scoring | one pass over flagged readings with dict lookups | O(N) | O(I) |
| Anomaly statistics | grouped median / MAD / quartiles | O(N log N) | O(N) |

**Priority score** (0–100) = `100 · Σ wᵢ·cᵢ / Σ wᵢ`. Every incident stores its component breakdown.

| Component | Weight | Definition |
|---|---|---|
| Severity | 0.35 | normalised exceedance beyond the CPCB criterion (log scale for coliforms) |
| Persistence | 0.20 | share of the station's sampled months breaching for the primary parameter |
| Downstream reach | 0.20 | `min(BFS-reachable stations / 5, 1)` |
| Anomaly confidence | 0.15 | direction-aware modified z (`0.6745·(x−median)/MAD`) or Tukey-IQR outlier |
| Data quality | 0.10 | completeness of active parameters on the row |

Default screening criteria come from CPCB Designated-Best-Use:

* pH 6.5–8.5.
* DO ≥ 5 mg/L.
* BOD ≤ 3 mg/L.
* Total coliform ≤ 5000 MPN/100 mL.
* Fecal coliform ≤ 2500 MPN/100 mL.
* NH₃-N ≤ 1.2 mg/L, used as a proxy (the CPCB criterion is for free ammonia).

All criteria can be edited in the UI.

### Measured benchmarks (this machine, 2026-11-18; `data/processed/benchmark_*.csv`)

These are synthetic, seeded river-like graphs. Rerun them live on the *Reports & Benchmarks* page.

| V | E | list memory KB | matrix memory KB | list BFS ms | matrix BFS ms | same result |
|---|---|---|---|---|---|---|
| 100 | 148 | 10.9 | 88.9 | 0.050 | 0.318 | ✔ |
| 500 | 747 | 48.8 | 2,003.9 | 0.222 | 8.362 | ✔ |
| 1,000 | 1,497 | 97.5 | 7,925.4 | 0.506 | 36.786 | ✔ |
| 2,000 | 2,999 | 194.8 | 31,485.2 | 1.022 | 147.275 | ✔ |

| Incidents | heap top-10 ms | `sorted()` top-10 ms | heap insert+peek µs | re-sort insert+peek µs |
|---|---|---|---|---|
| 1,000 | 2.21 | 0.21 | 25 | 188 |
| 10,000 | 22.6 | 2.9 | 48 | 3,533 |
| 100,000 | 239.3 | 34.9 | 46 | 34,411 |

Here is how to read these results:

* **One-shot top-k:** Python's C-implemented Timsort beats a pure-Python heap.
* **Incremental prioritisation** (a new incident arrives, then read the max): the heap is roughly 750× faster at 100k incidents because it does O(log n) work instead of O(n log n). That incremental case is what the Response Planner and live re-ranking need.
* **Traversal time:** grows close to linearly with V + E. At 100k vertices, BFS takes 154 ms and DFS takes 344 ms. The ns per (V+E) drifts upward with size because of cache and allocator effects, not because of the algorithm.

---

## 6. Pages

1. **Overview Dashboard:** eight KPIs, priority distribution, incidents by parameter, network map, top-10 heap incidents.
2. **Dataset Management:** one-click load, uploads, pipeline settings, schema mapping, coverage chart, quarantine, duplicates and multi-coordinate stations, station registry, downloads.
3. **River Network Explorer:** HydroRIVERS reaches, matched and unmatched stations, directed edges along their reach paths, live **Run BFS Downstream** and **Run DFS Upstream** with highlighted traversal, plus the adjacency-list dump.
4. **Pollution Analysis:** parameter selector, editable CPCB thresholds, time series with criterion lines and anomaly markers, distributions, anomaly table.
5. **Incident Prioritization:** ranked heap, Graphviz binary-tree view, array view, Peek / Extract / Insert Test Incident / Reset, score breakdown, live weight adjustment.
6. **Pollution Investigation:** flagged value with source SlNo, history, DFS candidates with contemporaneous upstream comparison, BFS impact, subgraph map, auto-generated narrative, limitations.
7. **Response Planner:** heap-ordered action queue, status (Pending / Investigating / Resolved), assignee, field notes persisted to `data/processed/response_log.json`, recommended actions, road-routing unavailability notice.
8. **Reports & Benchmarks:** incident CSV, Markdown and printable-HTML report, live benchmark lab, complexity table, comparison of existing approaches with EcoTrace.

### Faculty demo sequence (about 8 minutes)
1. Run `python -m pytest -v` (64 tests pass) and `python smoke_test.py` (25 real-data checks pass).
2. Run `streamlit run app.py`. The dashboard loads with live KPIs.
3. *Dataset Management → Quarantine:* show SlNo 2300's raw `3.16.2`, `0.41.83` and `78.2`, and that the values are NaN, not 0.
4. *River Network Explorer:* select **ARKAVATHI AT HESARAGHATTA RESERVOIR** and run BFS (4 downstream stations, down to the Cauvery). Then select **CAUVERY AT AJJIBORE** and run DFS (many upstream branches).
5. *Incident Prioritization:* Peek, Extract twice, insert a TEST incident with all components at 1.0 (it becomes the root), open the tree tab, change weights and watch the re-ranking.
6. *Pollution Investigation:* open the top Manchanabale Dam BOD incident. The narrative notes that upstream stations also breach, but this reading is about 10× worse, which suggests a local input.
7. *Response Planner:* set the incident to Investigating and add a note.
8. *Reports:* download the CSV and HTML report, then run the benchmark lab.

---

## 7. Limitations (scientific and project)

* **Screening, not attribution.** Upstream candidates are stations to check, not culprits.
* **Sampling:** roughly monthly grab samples from a single year (2021). Short events between visits are invisible.
* **Station typing** is a name-keyword heuristic. Reservoir and dam stations are treated as river-type.
* **Snapping:** a 1.5 km snap can attach a station to a tributary next to the main stem. HydroRIVERS has no river names to cross-check against. Co-located stations on the same reach have an indeterminate order, and the edge is flagged.
* **Bounding-box clip:** downstream walks stop where a river leaves the Karnataka bbox (74.0–78.6 E, 11.5–18.5 N).
* **Lakes/tanks:** 157 stations, isolated by design, so no graph inference is made for them.
* **Ammonia:** total NH₃-N is compared with a free-ammonia criterion only as a proxy.
* **Upstream comparison:** readings are matched by nearest date (±45 days), not simultaneity.
* **Multi-coordinate stations:** GOTTIGERE LAKE has one reading about 110 km from its usual location, which is likely a data-entry error. It is reported, not corrected.
* **No road network:** Dijkstra travel routing is unavailable, and river edges are never used as driving routes.
* **Benchmarks:** synthetic and machine-dependent.

## 8. Data provenance
* CPCB manual surface-water quality monitoring, Karnataka. Downloaded from the National Water Data Portal (nwdp.nwic.gov.in) and supplied in `files/` by the project author.
* Lehner, B. & Grill, G. (2013). *Global river hydrography and network routing: baseline data and new approaches to study the world's large river systems.* Hydrological Processes 27(15). HydroRIVERS v1.0, www.hydrosheds.org.
* The pipeline writes `data/processed/provenance.json` with sources, processing steps, audit counts and the active configuration. Every derived table is labelled as government, derived or synthetic in the app.
