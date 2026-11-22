# EcoTrace — Viva & DSA Guide

Each answer points to the code that implements it. The numbers quoted come from the bundled Karnataka 2021 data, and `python smoke_test.py` re-verifies them.

---

## A. Project & data

**Q1. What problem does EcoTrace solve?**
CPCB publishes station readings with no river connectivity: the River and Basin columns are all `-`. When a reading is bad, an officer needs to know two things: which monitored points lie upstream (candidates to check) and which lie downstream (who is affected). EcoTrace builds that connectivity from HydroRIVERS, screens readings, ranks incidents and supports the response. See `backend/pipeline.py`.

**Q2. Does EcoTrace identify the polluter?**
No. It produces *screening signals*. DFS returns upstream *candidates*, and the narrative uses "consistent with" and "requires field verification". See `investigation_engine.LIMITATIONS` and `dfs.DFS_CAVEATS`.

**Q3. What data do you use and how is it labelled?**
* CPCB manual chemical and biological CSVs for Karnataka (government data).
* HydroRIVERS v1.0 Asia (reference hydrography).
* Derived tables: stations, edges and incidents, all labelled *Derived*.
* Synthetic data, used only in tests, benchmarks and `data/sample_test_data/`.

`provenance.json` records the sources and processing steps.

**Q4. The file name says 2021–2025. What is the real coverage?**
It is computed, not assumed: 2021-01-01 to 2021-12-31. See `data_cleaning.clean_and_merge` (`date_min`/`date_max`).

**Q5. Why read CSVs with `dtype=str`?**
So nothing is silently converted at load time. A string like `3.16.2` must survive to the cleaning stage, where it is flagged and quarantined with its SlNo. See `data_ingestion.read_quality_csv`.

**Q6. How do you treat SlNo 2300?**
* `DO = "3.16.2"` and `Amonia N = "0.41.83"` are non-blank but unparseable, so they are quarantined as "malformed numeric string".
* `pH = 78.2` is outside 0–14, so it is quarantined as physically impossible.
* All three become NaN, never 0. The raw strings and the SlNo are kept in `quarantine.csv`.

See `data_cleaning.clean_table` and `tests/test_pollution.py`.

**Q7. Why never fill missing values with 0?**
A 0 would be a real measurement: DO = 0 means anoxic water, and BOD = 0 means perfectly clean. Zero-filling fabricates extreme readings and corrupts the statistics. Missing values stay NaN and are skipped by every rule (`evaluate_threshold` returns no violation for NaN).

**Q8. How do you de-duplicate?**
On the full key `(station, timestamp, lat, lon)`. Rows are sorted by SlNo and the lowest is kept (deterministic). This happens *before* the merge.

**Q9. There are 15 duplicate `(Station, Time)` pairs. Why not drop them?**
They are at *different coordinates*: Ulsoor Lake has two sampling points about 200 m apart, and GOTTIGERE LAKE has one row about 110 km away. They are distinct sampling records, so they are kept and reported. The station's location is its modal coordinate. See `station_manager.build_station_table`.

**Q10. How do you guarantee no Cartesian join when merging chemical and biological tables?**
Both tables are de-duplicated on the merge key first, and `pandas.merge(..., validate="one_to_one")` raises an error if any key repeats. Result: 3,019 + 3,019 rows merge to 3,019 records.

**Q11. Why 6 "active" parameters, and why does it matter?**
Coverage is computed per parameter. pH, BOD, DO, Total Coliform, Ammonia-N and Fecal Coliform are at least 10% populated. COD and 22 metal/ion columns are 0–0.1% populated, and SAR is 6.7%. Data-quality scoring divides by the *active* set only, so a station is never penalised for heavy metals that the CPCB suite did not measure. The cutoff is set in `PipelineConfig.active_param_min_coverage`.

**Q12. How are dates parsed?**
Explicit day-first formats are tried in order (`%d-%m-%Y %H:%M`, …). Ambiguous strings are never guessed month-first, and unparseable dates reject the row with a reason. See `data_cleaning.parse_timestamps`.

**Q13. How do you decide lake vs river?**
A documented name heuristic (`station_manager.classify_station`):
* Lake words are checked first: LAKE, TANK, TNAK (a typo in the data), POND, KUNTE and the `…KERE` suffix.
* Then river words: RIVER, NALLA, DAM, BRIDGE, D/S, U/S, RESERVOIR, AT …
* Borewell stations become `unknown`.

Result: 157 lakes, 110 river-type and 2 unknown.

---

## B. Spatial matching & graph construction

**Q14. Why HydroRIVERS?**
It is a global vector river network with explicit topology. Each reach has `HYRIV_ID`, `NEXT_DOWN` (the downstream reach), `MAIN_RIV`, `DIST_DN_KM` and Strahler order, which is exactly the flow-direction information CPCB lacks.

**Q15. How do you load a 100 MB Asia geodatabase quickly?**
The bbox (74.0–78.6 E, 11.5–18.5 N) is pushed down to GDAL through `geopandas.read_file(..., bbox=…)` with pyogrio, so only about 25.7k reaches are read. The clip is cached as GeoParquet and reloads in under 0.5 s. See `data_ingestion.load_hydrorivers`.

**Q16. How is a station snapped?**
River-type stations are projected to UTM 43N (metres), then `sjoin_nearest(max_distance=1.5 km)` finds the nearest reach. Ties are broken by distance, then `HYRIV_ID`. Stations farther than the threshold stay unmatched. See `graph_builder.snap_stations`.

**Q17. Why not connect stations that are close together?**
Proximity says nothing about flow: two stations 500 m apart can be on different rivers or on either side of a watershed. Edges come **only** from `NEXT_DOWN` pointer walks. Lakes and unmatched stations stay isolated (in-degree = out-degree = 0).

**Q18. Explain the NEXT_DOWN walk.**
1. For each reach carrying stations, sort those stations upstream to downstream by distance to the outlet, and chain them.
2. From the most-downstream station, follow `next_down[reach]` (a dict lookup) until reaching a reach that carries a station.
3. Add one edge to that reach's most-upstream station.
4. Stop at an outlet (`NEXT_DOWN = 0`) or the bbox edge.

Cost: O(length of path) per station.

**Q19. How do you order two stations on the same reach?**
`f = line.project(point, normalized=True)` gives the station's position along the reach. HydroRIVERS lines are digitised in flow direction: I verified that the end vertex touches `NEXT_DOWN` in 2,946 of 2,946 reaches. So the distance to the outlet is `DIST_DN_KM + (1 − f)·LENGTH_KM`.

**Q20. Why does every vertex have at most one outgoing edge?**
River networks are *in-trees*: water from a point follows a single downstream path. Confluences give in-degree > 1. The smoke test asserts `out_degree ≤ 1` for all vertices.

**Q21. What are the graph's real numbers?**
V = 269, E = 90, 102 snapped stations, 8 unmatched river stations, 157 isolated lakes.

---

## C. Data structures & algorithms

**Q22. Why an adjacency list instead of an adjacency matrix?**
The graph is sparse (E = 90 ≪ V² = 72,361). A list uses O(V + E) memory and lists neighbours in O(deg). A matrix needs O(V²) memory and O(V) to scan a row. Measured: at V = 2,000 the list took 195 KB versus 31.5 MB for the matrix, and BFS took 1.0 ms versus 147 ms. See `complexity_benchmark.bench_list_vs_matrix`.

**Q23. Why store both `forward_adj` and `reverse_adj`?**
BFS downstream needs out-neighbours and DFS upstream needs in-neighbours. With only one direction, every upstream query would need an O(V + E) scan or transpose. Storing both doubles edge memory (still O(V + E)) and makes both queries O(deg) per step. See `river_graph.DirectedRiverGraph`.

**Q24. How are duplicate edges prevented?**
A `set` of `(u, v)` tuples gives O(1) membership. `add_edge` returns False for duplicates and self-loops.

**Q25. Walk through BFS.**
1. Put the source in a `deque` and the `visited` set, with `level[source] = 0`.
2. Repeatedly `popleft()` a vertex u.
3. For each unvisited v in `forward_adj[u]`, set `level[v] = level[u] + 1`, record the tree edge (u, v), and enqueue v.

Each vertex is enqueued once and each edge is scanned once, so the cost is **O(V + E)**. See `bfs.bfs_downstream`.

**Q26. Why `deque`, not a list?**
`list.pop(0)` is O(n) because it shifts every element, which would make BFS O(V²). `deque.popleft()` is O(1).

**Q27. Why BFS for downstream impact?**
BFS discovers vertices in order of hop distance, so `levels` gives the minimum number of station-to-station links. That supports "notify the nearest downstream intake first".

**Q28. Walk through DFS and why it is iterative.**
An explicit stack is used. The algorithm pops u, pushes its unvisited upstream neighbours (`reverse_adj[u]`) and records `parent`. A vertex with no new children ends a branch, and its path is rebuilt from parent pointers. Cost: O(V + E). It is iterative because Python's recursion limit (about 1,000) would crash on long river chains, and a test with a 5,000-vertex chain proves the iterative version doesn't. See `dfs.dfs_upstream`.

**Q29. Why DFS for upstream, not BFS?**
DFS explores one tributary completely before backtracking, which yields the distinct **branch paths** (source → … → headwater). Investigators walk rivers branch by branch. The visited set is the same as BFS, but the path structure is more useful here.

**Q30. How are cycles handled if bad data introduces one?**
Both traversals keep a `visited` set, so each vertex is expanded once and the traversal terminates. Tests cover this case.

**Q31. Explain the MaxHeap layout.**
A Python list `_heap`. The children of i are 2i+1 and 2i+2, and the parent is (i−1)//2. Invariant: `parent.priority_score ≥ child.priority_score`. `_index` maps `incident_id` to its position for O(1) lookup. Ties are broken by insertion sequence, which keeps the order deterministic. See `max_heap.py`.

**Q32. Complexities of the heap operations?**
* `insert`: append, then sift up, O(log n).
* `extract_max`: move the last leaf to the root, then sift down, O(log n).
* `peek`: O(1).
* `update_priority`: index lookup O(1), then sift up or down, O(log n).
* `heapify`: Floyd's bottom-up construction, O(n).

**Q33. Why is heapify O(n) and not O(n log n)?**
Most nodes are near the bottom. About n/2 leaves need 0 swaps, n/4 need at most 1, n/8 need at most 2, and so on. The sum n·Σ k/2^(k+1) converges to O(n).

**Q34. Why a heap when you could just sort?**
Prioritisation is *incremental*: new incidents arrive, statuses change and weights get adjusted. Measured at 100k incidents, insert + peek on the heap took 46 µs, while re-sorting took 34 ms. I report honestly that a one-shot top-10 is faster with Python's C-implemented `sorted()`. The heap's advantage is the dynamic case.

**Q35. How does `top_k` avoid destroying the heap?**
It uses a second, auxiliary heap over *array positions*. It starts with the root, and each time it pops a position it pushes that position's two children. That gives O(k log k) without mutating the main heap. See `MaxHeap.top_k`.

**Q36. How do you prove the heap is correct?**
`is_valid()` checks the invariant for every parent–child pair and the consistency of the index map. Tests call it after every insert and extract, and check that extract order equals descending sort. See `tests/test_heap.py`.

---

## D. Detection & scoring

**Q37. How is "severity" normalised to [0, 1]?**
* Max-type limits: `(v/limit − 1)/(R − 1)`, where R = 5×.
* Coliforms: on a log scale, `log10(v/limit)/log10(1000)`.
* DO: `(limit − v)/limit`.
* pH: distance outside 6.5–8.5 divided by 1.5.

All values are capped at 1. See `pollution_detection.evaluate_threshold`.

**Q38. What is the modified z-score and why use it instead of the ordinary z?**
`M = 0.6745·(x − median)/MAD` (Iglewicz & Hoaglin). The median and MAD are robust: one extreme spike does not inflate the scale and hide itself, which an ordinary mean/SD z-score would do. If MAD = 0, the code falls back to IQR/1.349, and a Tukey IQR fence acts as a second test.

**Q39. What does "direction-aware" mean?**
Only deviations toward *worse* water count: low DO, and high BOD, coliforms or ammonia. A DO spike to 12 mg/L is not an anomaly incident. Stations with fewer than 4 readings are never called anomalous. Tests cover both cases.

**Q40. Explain the priority score.**
`100·Σ wᵢcᵢ / Σ wᵢ`, with severity 0.35, persistence 0.20, downstream reach 0.20, anomaly 0.15 and data quality 0.10. Each incident stores the values, weights and points, so the UI shows exactly where every point comes from. Changing the weights rescores from the stored components in O(I) without re-running detection. See `incident_scoring.py`.

**Q41. Why does downstream reach saturate at 5 stations?**
Each additional downstream station matters less than the first few, and saturation stops one long river chain from dominating the score. The value is configurable (`downstream_saturation`).

**Q42. How does the narrative decide "local input" vs "upstream origin"?**
It compares the nearest-in-time upstream readings (±45 days):
* If no upstream station breaches, the narrative points to the stretch between the nearest clean upstream station and this one.
* If upstream stations also breach but this reading is at least 2× worse (for example, Manchanabale BOD 98 mg/L versus a worst upstream value of 10 mg/L), the narrative points to an additional local input.
* Otherwise, it suggests the problem originates upstream or is basin-wide.

See `investigation_engine._narrative`.

---

## E. Engineering, testing, limitations

**Q43. How is the app kept fast?**
* HydroRIVERS is clipped by bbox and cached as GeoParquet.
* The pipeline result is cached per (file fingerprint, config) with `st.cache_resource`.
* Hot loops use dict lookups instead of per-row pandas indexing. Profiling showed the first version took 67 s, which fell to about 2 s after this change.

**Q44. What do the tests cover?**
64 pytest tests on **synthetic** fixtures:
* Graph: reverse edges, duplicates, isolated lakes, removal.
* BFS: levels, cycles, agreement between the list and matrix versions.
* DFS: branch paths, a 5,000-deep chain.
* Heap: invariant, ordering, update/remove, ties, top-k.
* Pollution: SlNo-2300-style defects, no zero-filling, thresholds, direction-aware anomalies, score maths.
* Ingestion: schema aliases, dedup, multi-coordinate rows, one-to-one merge, day-first dates.

`smoke_test.py` adds 25 checks on the real files.

**Q45. Why no NetworkX?**
The project's goal is to implement and defend the data structures. NetworkX would hide the adjacency representation and the traversal logic. `river_graph.py`, `bfs.py`, `dfs.py` and `max_heap.py` use only built-ins and `collections.deque`.

**Q46. Why is road routing (Dijkstra) not implemented?**
No road network was supplied. River edges represent water flow, not drivable roads, so using them for routing would be wrong. The Response Planner states this explicitly (`response_planner.ROUTING_NOTICE`). With an OSM road graph, Dijkstra with a binary heap would run in O((V + E) log V).

**Q47. Main limitations?**
* Monthly grab samples from one year.
* Name-based station typing.
* Snapping uncertainty: no river names exist in HydroRIVERS to cross-check against.
* Bbox truncation of downstream paths.
* Lakes excluded from graph inference.
* The ammonia criterion is used as a proxy.
* Upstream matching is by nearest date, not simultaneity.
* GOTTIGERE LAKE has a probable coordinate error.

See README §7.

**Q48. What would you add next?**
* An OSM road graph for Dijkstra dispatch.
* Lake inflow/outflow linking using HydroLAKES.
* Multi-year CPCB data for seasonal baselines.
* Confidence weighting of edges by snap distance.
* A persistent database (SQLite) for the response log.
