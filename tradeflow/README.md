Exiobase US-to-US domestic `trade_id` relates trade to state-to-state `interstate` factors using BEA data.  
`interstate_factor.csv` includes `factor_id` and relates to `factor.csv` through `factor.factor_id`.

[Upcoming SQL Pipeline](https://github.com/garmartirosy/pipeline) | [Database Admin (Rust)](/team/admin/sql/panel/) | [Database Admin (.NET 10 on Azure)](https://model-earth-pipeline-dnfmg3febdhvd8ag.westus2-01.azurewebsites.net/)

# Primary tables: <span style="color:#aaa">trade, factor, industry</span>

Table naming designed for 3rd graders. [View Report Sample](../../profile/footprint/) from [Exiobase .csv output](https://github.com/ModelEarth/trade-data/tree/main/year) and [US State Data](../../profile/footprint/)

**The trade_id field** in trade.csv relates 5 values (year, region1, region2, industry1, industry2) to multiple impact factors for each trade row.

**The factor_id field** represents 721 unique impacts applied to each annual trade row (for imports, exports and domestic).

**trade.amount** is in **million Euros (M EUR)**, sourced directly from the Exiobase Z matrix (inter-industry transaction flows). Environmental factor coefficients are expressed per million EUR of output.

**trade_factor.level** is in physical units — not Euros. The coefficient converts M EUR → a physical quantity whose unit varies by extension:

| Extension | Unit |
|---|---|
| air_emissions | kg |
| employment | 1000 persons |
| energy | TJ (terajoules) |
| land | km² |
| material | kt (kilotonnes) |
| water | Mm³ (million cubic metres) |

The unit for any given row is found by joining to `factor.csv` on `factor_id` and reading the `unit` column.

Trade is traditionally called flow, but the term lacks clarity when relating annual trade rows to multiple factors.

Later, the 6-character "commodity" sectors can reside in the 5-character "trade" tables, or in tables starting with "commodity".

Combing state-to-state consumption: [Exiobase plus BEA](bea) based on the [USEEIO repo](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors)

## Processing

Set a year and country in the config.yaml file and run:

```bash
python main.py
```

Get US Interstate Data (uses the same config.yaml file) - [BEA Details](bea)

```bash
python bea/main.py --bea-key YOUR_API_KEY
```

Lastly, [Send CSV into SQL database](https://github.com/ModelEarth/projects/issues/30):


## Processing Times

Does not include interstate bea/main.py processing

| config.yaml | trade.py | trade_impact.py | trade_resource.py |
|--------------|----------|----------------|-------------------|
| **2019/US/exports** | **2m 14s**<br>**188,735 trade flows**<br/>125,148 trade factors | **5.3s**<br>**188,735 trade impacts** | **9.0s**<br>**38,935 total rows**<br/>(3,469 employment<br/>28,844 resources<br/>6,622 materials) |
| **2019/US/imports** | **2m 11s**<br>**126,166 trade flows**<br/>19,425 trade factors | **3.5s**<br>**126,166 trade impacts** | **5.6s**<br>**7,850 total rows**<br/>(2,578 employment<br/>3,926 resources<br/>1,346 materials) |
| **2019/US/domestic** | **2m 18s**<br>**21,518 trade flows**<br/>11,832 trade factors | **1.7s**<br>**21,518 trade impacts** | **1.9s**<br>**4,272 total rows**<br/>(421 employment<br/>2,656 resources<br/>1,195 materials) |

- trade.py: Includes Exiobase download, trade flow extraction, and trade_factor.csv generation
- trade_impact.py: Creates aggregated environmental impact summary (22 columns)
- trade_resource.py: Creates 3 specialized files (employment, resource, material analysis)
- Total processing time: ~2m 30s for 188,735 trade flows
- Well within timeout limits (20 min/script, 60 min/country, 5 hours/batch)

The main.py command generates the following CSV files for each country/tradeflow combination:
- `factor.csv` - Environmental factor definitions (721 factors)
- `industry.csv` - Industry sector mapping
- `trade.csv` - Core trade flows (trade_id, year, region1, region2, industry1, industry2, amount)
- `trade_factor.csv` - Environmental coefficients (120 Selected Factors for imports/exports)
- `trade_factor_lg.csv` - All environmental coefficients (721 factors for domestic flows)
- `trade_impact.csv` - Aggregated environmental impacts
- `trade_resource.csv` - Resource use analysis
- `trade_material.csv` - Material flow analysis
- `trade_employment.csv` - Employment impact analysis

**120 Selected Factors:** Since each trade flow row gets one row per factor, the row count scales linearly — 120 factors produces 16.6% as many rows as 721 factors (120 / 721 = 16.6%). The top 120 are selected per industry from 721 total Exiobase stressors (air emissions, employment, energy, land, material, water extensions) by ranking all stressors whose absolute S-matrix coefficient meets `min_impact_threshold` (0.001) in descending order and keeping the first `partial_factor_limit` (120). `trade_factor_lg.csv` retains all 721 factors and is generated for domestic flows where the larger file is manageable.

The bea/main.py command generates the following CSV files for US domestic flows:
- `interstate.csv` — one row per state-pair flow (`interstate_id`, `trade_id`, `state1`, `state2`, `industry1`, `industry2`, `state_industry_code`, `amount`, `commodity_code`, `industry_code`, `economic_multiplier`). Now always produced, satellite factor data available or not.
- `interstate_factor.csv` — real per-factor rows (`interstate_id`, `factor_id`, `level`, `flow_type`) when satellite data is available; joins to `interstate.csv` through `interstate_id` and to `factor.csv` through `factor_id`.
- `interstate_factor_lg.csv` — same with all 721 factors (set `use_partial_factors_interstate: false` in config.yaml).
- `interstate_estimate.csv` — produced instead of `interstate_factor.csv` when no satellite data is available: leftover fields from the disaggregation step (`interstate_id`, `employment_impact`, `flow_type`) that don't belong on `interstate` itself and aren't real per-factor data.

## Schema notes: IDs, dedup keys, and one-database-per-year

**`trade_id`** is a plain 1-based sequential row index, assigned per output file (`trade_data['trade_id'] = trade_data.index + 1` in `trade.py`) — it resets on every regeneration and has no meaning across files. Its only job is correlating a `trade.csv` row with its `trade_factor.csv` rows generated in the same run.

**`interstate_id`** is a composite string built during state disaggregation (`bea/main_trade_analyzer.py`): `f"{year}-{trade_id}-US-{origin_state}-US-{dest_state}-{industry}"`. It plays the same structural role for `interstate`/`interstate_factor`/`interstate_estimate` that `trade_id` plays for `trade`/`trade_factor` (the row identity factor/estimate rows key off of) — but it has to be a string, not a plain integer, because one international `trade_id` fans out into many `interstate_id` rows (one per producing-state × consuming-state pair).

**Why `interstate` keeps `trade_id`:** `interstate_id`'s embedded `industry` is only a broad *category* used for state-allocation weighting, not the actual `industry1`→`industry2` pair. `trade_id` is the path back to the *shared originating international flow* (`trade.amount`, `trade.country`, `trade.flow_type`, exact `industry1`/`industry2`) — reliable specifically because the BEA/interstate pipeline only ever disaggregates one file (`country=US`, `flow_type=domestic`), so `trade_id` stays unique in that scope. `interstate_id` itself is `interstate`'s `PRIMARY KEY`, and the real `FOREIGN KEY` target for both `interstate_factor` and `interstate_estimate`.

**Dedup keys, not `trade_id`:** the true identity of a flow is its region/industry (or state/industry) pair, not `trade_id`. `trade` has `UNIQUE(region1, region2, industry1, industry2)` (previously deduped on `trade_id, year, country, flow_type` — not safe, since the same physical flow can be pulled twice from two different country-perspective CSV runs, e.g. "imports to US" and "exports from Canada" both capture the same CA→US leg, under different `trade_id`/`country`/`flow_type`). `interstate` has `UNIQUE(state1, state2, industry1, industry2)` (previously had no dedup at all) — `trade_id` isn't part of either dedup key, it's lineage only.

**No `bigserial id` anywhere now.** Each table uses its natural key as the actual `PRIMARY KEY`: `trade` → `(region1, region2, industry1, industry2)`; `trade_factor` → `(trade_id, country, flow_type, factor_id)`, all four `NOT NULL`; `interstate` → `interstate_id` alone; `interstate_factor` → `(interstate_id, factor_id)`, both `NOT NULL` (real per-factor rows only — see below); `interstate_estimate` → `interstate_id` alone. (`trade.industry1`/`industry2` are `NOT NULL` too — required for a composite primary key column — but the app never actually supplies a true `NULL` there, only `""` at worst, so this doesn't reject anything it produces.) This only applies to freshly-created databases — the fresh `CREATE TABLE` sets the new schema from scratch; there's no destructive migration of any table that might already exist with the old `bigserial id`.

**`interstate_factor` vs `interstate_estimate` — split by whether satellite data was available, mutually exclusive per run.** `interstate_factor.csv` (satellite path) is genuinely per-factor: `factor_id` is never null, so `(interstate_id, factor_id)` is a safe primary key — no need to also carry `trade_id`/`coefficient`/`state_industry_code`/`employment_impact`, since none of those are actually in that file (they live on `interstate`, reachable via the `interstate_id` foreign key). The no-satellite fallback path used to dump the *whole* disaggregation row (including a fixed `factor_id: -1, coefficient: 1.0` placeholder that's never recalculated) into that same table, making `factor_id` nullable there for no good reason. It now writes `interstate_estimate.csv` instead — just the genuinely no-satellite-only fields (`employment_impact`, `flow_type`), excluding the meaningless placeholders entirely. `interstate` ↔ `interstate_estimate` is 1-to-(0-or-1): a detail row only exists for flows where the fallback path ran.

**`interstate.csv` is now always produced**, satellite data available or not (`bea/main.py`) — previously the no-satellite branch only wrote the factor/estimate file, so those flows had no `interstate` row at all (`amount`/`industry1`/`industry2`/`commodity_code` were never recorded anywhere), which would have made the `interstate_factor`/`interstate_estimate` → `interstate` foreign key impossible to satisfy for those rows.

**`interstate.state_industry_code`** was already in `interstate.csv`'s real output but had never been captured in the database — added.

**`interstate.region1`/`region2` are `state1`/`state2`** — both in the database and in the CSV/Python pipeline itself now (`bea/main.py`, `bea/main_trade_analyzer.py`) — they're US state codes (CA, TX, ...), not Exiobase-style regions like `trade`'s. (`state_industry_impacts.csv`'s own unrelated `region1`/`region2` fields, used only for a same-state employment-impact summary, were left alone — that's a different output file, not part of the `interstate` table or the DB ingestion path.)

**Removed `_create_interstate_csvfiles` (`bea/main.py`)** — dead code, never called, and actively wrong if it had been: it just copied the international `trade.csv` verbatim and renamed `trade_id` to `interstate_id`, with no real state disaggregation at all, so it would've written country-level `region1`/`region2` data mislabeled as state-level `interstate.csv`.

**`insert_interstate_rows` reads `interstate.csv` by header name, not fixed position** — a real bug fix: `interstate.csv`'s actual column order is `interstate_id, trade_id, year, state1, state2, industry1, industry2, state_industry_code, amount, commodity_code, industry_code, economic_multiplier`, which doesn't match `trade.csv`'s simpler layout. The old code read `region1`/`region2`/etc. from fixed positions borrowed from `trade.csv`, which silently misread every field once `interstate_id` shifted the real columns over by one. It now looks each column up by name, with position fallbacks only for files with no matching header.

**One database per year:** the `year` column is being dropped from `trade`, `trade_factor`, and `interstate` in the database — a given Postgres database now holds exactly one year's data (`{EXIOBASE_NAME}_{year}`), so `year` is implicit in which database you're connected to rather than a per-row value. The CSV files themselves are unchanged and still carry a `year` column; it's just no longer written into these tables when the API loads the CSVs.

**Same-state (`state1 == state2`) rows are kept, not filtered.** `_disaggregate_single_flow` (`bea/main_trade_analyzer.py`) allocates each domestic `trade.amount` across producing-state × consuming-state pairs, normalized to sum to exactly that amount. Earlier it skipped same-state pairs before normalizing, which silently reallocated genuine intra-state consumption onto cross-state pairs, inflating them. Same-state pairs are now included in the normalization and land in `interstate` as ordinary `state1 == state2` rows with `flow_type = 'intra_state'` (cross-state rows stay `'inter_state'`) — so the total across all rows for a `trade_id` still equals `trade.amount`, but now for the right reason.

