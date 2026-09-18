Exiobase US-to-US domestic `trade_id` relates trade to state-to-state `interstate` factors using BEA data.  
`interstate_factor.csv` includes `factor_id` and relates to `factor.csv` through `factor.factor_id`.

[Upcoming SQL Pipeline](https://github.com/garmartirosy/pipeline) | [Database Admin (Rust)](/team/admin/sql/panel/) | [Database Admin (.NET 10 on Azure)](https://model-earth-pipeline-dnfmg3febdhvd8ag.westus2-01.azurewebsites.net/)

# Primary tables: <span style="color:#aaa">trade, factor, industry</span>

Table naming designed for 3rd graders. [View Report Sample](../../profile/footprint/) from [Exiobase .csv output](https://github.com/ModelEarth/trade-data/tree/main/year) and [US State Data](../../profile/footprint/)

**The trade_id field** in trade.csv relates 4 values (region1, region2, industry1, industry2) to multiple impact factors for each trade row.

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

Set a year and country in the config.yaml file. `main.py`/`trade.py` download the Exiobase year
file automatically if it's missing, but for a visible first-time download (roughly 0.2-4 GB, depending on year), run this
first — see [AGENTS.md](AGENTS.md) for details:

```bash
python exiobase_download.py
```

Then run:

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
- `trade.csv` - Core trade flows (trade_id, region1, region2, industry1, industry2, amount)
- `trade_factor.csv` - Environmental coefficients (aggregated flows — see below)
- `trade_factor_lg.csv` - All environmental coefficients (721 factors for domestic flows)
- `trade_impact.csv` - Aggregated environmental impacts
- `trade_resource.csv` - Resource use analysis
- `trade_material.csv` - Material flow analysis
- `trade_employment.csv` - Employment impact analysis

**Aggregated flows, not top-N-by-magnitude:** `trade_factor.csv` no longer ranks the 721 raw Exiobase stressors (air emissions, employment, energy, land, material, water) by `|M-matrix coefficient|` and keeps the largest N — it aggregates (sums) raw stressors into a small, fixed set of flows per industry, mirroring EPA USEEIO's own [import_emission_factors](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors) approach: `air_emissions` collapses to 5 curated GHG flows (EPA's own mapping, copied verbatim — see `exiobase_factors.py`), and the other five extensions each collapse to one flow scoped to the corresponding USEEIO indicator's coverage (e.g. material excludes crops/forestry/fishery/fossil fuels, keeping only metal ores and non-metallic minerals). These five won't numerically match either the older EPA repo's or cornerstone-data's published values, though — USEEIO computes them from separate US government data (BLS for jobs, EIA for energy, USDA for land, USGS for water and minerals), not from Exiobase, so this is a scope match only, not a value match. See [bea/README.md](bea/README.md#beyond-ghgs-employment-energy-land-material-water) for the full writeup. `trade_factor_lg.csv` still retains all 721 raw, unaggregated stressors for anyone who wants the full detail. See [bea/README.md](bea/README.md#epa-import-factor-reduction) for the full comparison against EPA's methodology.

**Two known data gaps in the aggregated flows (Exiobase v3.8.2, confirmed 2019 and 2021):** `energy` reads 0 for every row — Exiobase's own `energy` extension is entirely zero-valued in the raw source data, not something our selection can work around. `SF6`/`HFC`/`PFC` also read 0, but for a different reason — they have real nonzero emissions in Exiobase's raw flow data, but their Leontief-inverse M-matrix computation is 100% NaN for all three across every region, and the `fillna(0)` fix described in [bea/README.md](bea/README.md#epa-import-factor-reduction) (needed elsewhere, to treat genuine 0/0 sectors as real zeros) currently discards that real data here rather than confirming a genuine absence. See [bea/README.md](bea/README.md#beyond-ghgs-employment-energy-land-material-water) for details.

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

**`insert_interstate_rows` reads `interstate.csv` by header name, not fixed position** — a real bug fix: `interstate.csv`'s actual column order is `interstate_id, trade_id, state1, state2, industry1, industry2, state_industry_code, amount, commodity_code, industry_code, economic_multiplier`, which doesn't match `trade.csv`'s simpler layout. The old code read `region1`/`region2`/etc. from fixed positions borrowed from `trade.csv`, which silently misread every field once `interstate_id` shifted the real columns over by one. It now looks each column up by name, with position fallbacks only for files with no matching header.

**One database per year:** the `year` column is dropped from `trade`, `trade_factor`, and `interstate`, both in the database and in the CSV files themselves (`trade.py`, `bea/main.py`) — a given Postgres database now holds exactly one year's data (`{EXIOBASE_NAME}_{year}`), so `year` is implicit in which database you're connected to rather than a per-row value. (`interstate_id`'s embedded `{year}` prefix is unrelated — it's just one more uniqueness component of a composite string key, not a stored `year` column.)

**Import factors now use Exiobase's M matrix, not S** (`trade.py`, `bea/main_trade_analyzer.py`) — `S` is direct-only environmental intensity per unit of output; `M` (`S` combined with the Leontief inverse) also captures everything embodied in a sector's own upstream inputs. EPA USEEIO's [import_emission_factors](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors) methodology (`exiobase_helpers.py`) builds its published import factors from `M`, so `trade_factor.csv`/`interstate_factor.csv` levels previously understated a traded good's true footprint by omitting its supply chain. `trade.amount`/`interstate.amount` remain in Euros (see the TO DO in [bea/README.md](bea/README.md) about a Euro→USD lookup, which EPA's process also applies and ours doesn't yet) — that's a separate, still-open gap from the S→M fix.

**Same-state (`state1 == state2`) rows are kept, not filtered.** `_disaggregate_single_flow` (`bea/main_trade_analyzer.py`) allocates each domestic `trade.amount` across producing-state × consuming-state pairs, normalized to sum to exactly that amount. Earlier it skipped same-state pairs before normalizing, which silently reallocated genuine intra-state consumption onto cross-state pairs, inflating them. Same-state pairs are now included in the normalization and land in `interstate` as ordinary `state1 == state2` rows with `flow_type = 'intra_state'` (cross-state rows stay `'inter_state'`) — so the total across all rows for a `trade_id` still equals `trade.amount`, but now for the right reason.


**`factor.csv` now has two kinds of rows: raw per-stressor (1–721) and aggregated flows (901–910).** The aggregate ID block is a fixed offset chosen well clear of the raw range so both can coexist in one file without collision, regardless of a given year's exact Exiobase stressor count — `trade_factor_lg.csv`/`interstate_factor_lg.csv` reference the raw rows, `trade_factor.csv`/`interstate_factor.csv` reference the aggregate rows. See [bea/README.md](bea/README.md#epa-import-factor-reduction) and `exiobase_factors.py` for what the aggregate rows are and why.
