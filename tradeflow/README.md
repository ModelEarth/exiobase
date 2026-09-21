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

## State-to-State: interstate, factor, sector

Aggregating to 21 BEA Sector categories instead of Exiobase's ~200 industries keeps `interstate_factor.csv` around 55-80 MB instead of 1.4+ GB at full industry detail (real measured 2019/2021 sizes) — well under GitHub's 100 MB file limit.

Combing state-to-state consumption: [Exiobase plus BEA](bea) based on the [USEEIO repo](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors) and newer [Cornerstone repos](https://github.com/cornerstone-data)

## Processing

Set a year and country in the config.yaml file. `main.py`/`trade.py` download the Exiobase year
file automatically if it's missing, but for a visible first-time download (roughly 0.2-4 GB, depending on year), run this
first — see [AGENTS.md](AGENTS.md) for details:

```bash
python3 exiobase_download.py # uses YEARs from config.yaml
python3 exiobase_download.py --year 2023
```

Then run:

```bash
python main.py
```

**To also get US Interstate Data** ([BEA Details](bea)) and/or **India state-level allocation** ([India Details](india)) right after each year's trade data finishes, add `--interstate US`, `--interstate IN`, or both as a comma-separated list (a space after the comma is optional):

```bash
python main.py --interstate US
python main.py --interstate US,IN
python main.py --interstate US, IN
```

Before starting, this checks each requested country's prerequisite — a findable **BEA_API_KEY** for `US` (see [AGENTS.md](AGENTS.md)), and an `exiobase/India_data/` directory for `IN` — so a missing key/directory fails immediately instead of after a long trade-data run. `main.py` never uses either prerequisite itself; `bea/main.py` and `india/main.py` do. With multiple years in `YEAR` (e.g. `2019,2021`), each requested interstate step runs once per year, right after that year's trade data completes. `bea/main.py`/`india/main.py` can still be run on their own afterward if you skip `--interstate`:

```bash
python bea/main.py --bea-key YOUR_API_KEY
python india/main.py
```

**Comprehensive mode** (`COUNTRY.list: comprehensive` in config.yaml, or `EXIOBASE_COUNTRY_LIST=comprehensive`/`COUNTRY_LIST=comprehensive`) pushes all 49 Exiobase regions for a year straight to Azure in one run, instead of a curated country list. Set `COMPREHENSIVE.folders: default` (or its short alias `SCOPE=default`) to limit that push (and local `.csv` output) to just the 14 default-list countries instead — `trade_id` still counts every one of the 49 regions in Exiobase's own row order regardless, so the excluded regions just leave gaps in the numbering rather than shifting the included ones' ids. A kept country's imports are assembled from this same run's in-memory extraction rather than pulled from Azure, so they still cover all 49 possible exporters even though most were never pushed themselves. `COMPREHENSIVE.target` (or `EXIOBASE_COMPREHENSIVE_TARGET`/`DB_TARGET`, optional — defaults to `year_db`) picks which Azure database: `year_db` creates a dedicated `industrydb_[year]`, or `industrydb` adds into the shared multi-year database instead. `YEAR`/`COUNTRY_LIST`/`DB_TARGET`/`SCOPE` are short aliases for `EXIOBASE_YEAR`/`EXIOBASE_COUNTRY_LIST`/`EXIOBASE_COMPREHENSIVE_TARGET`/`EXIOBASE_COMPREHENSIVE_FOLDERS` (the `EXIOBASE_`-prefixed name wins if both are set):

```bash
YEAR=2018 COUNTRY_LIST=comprehensive DB_TARGET=industrydb python main.py
```

With multiple years in `YEAR` (comma-separated), `DB_TARGET` can either be one value applied to every year, or a comma-separated list with exactly one entry per year, in the same order:

```bash
YEAR=2018,2019 COUNTRY_LIST=comprehensive DB_TARGET=industrydb_2018,year_db python main.py
```

`DB_TARGET` entries can also be an explicit per-year database name (`industrydb_[year]`) instead of the bare `year_db` keyword — main.py checks that name's year against the corresponding `YEAR` entry before anything runs, and refuses to start if they don't match (a mismatch like `YEAR=2019` with `DB_TARGET=industrydb_2018` is exactly the kind of typo that would otherwise silently push one year's data into another year's database).

See [PLAN-comprehensive.md](PLAN-comprehensive.md) for the full design.

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
- `industry.csv` - Raw Exiobase industry mapping (~200 rows)
- `sector.csv` - BEA Sector classification (~21 categories + Used/Other, `sector_id, name`)
- `sector_industry.csv` - Many-to-many join between `sector` and `industry` (`sector_id, industry_id, weight`) — see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)
- `trade.csv` - Core trade flows, full Exiobase industry detail (trade_id, region1, region2, industry1, industry2, amount) — trade/trade_factor were never the file-size problem (see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)'s revision note), so unlike interstate they have no separate Sector-level primary tier
- `trade_factor.csv` - Environmental coefficients (aggregated flows — see below)
- `trade_factor_lg.csv` - All environmental coefficients (721 factors for domestic flows)
- `trade_impact.csv` - Aggregated environmental impacts
- `trade_resource.csv` - Resource use analysis
- `trade_material.csv` - Material flow analysis
- `trade_employment.csv` - Employment impact analysis

**Aggregated flows, not top-N-by-magnitude:** `trade_factor.csv` no longer ranks the 721 raw Exiobase stressors (air emissions, employment, energy, land, material, water) by `|M-matrix coefficient|` and keeps the largest N — it aggregates (sums) raw stressors into a small, fixed set of flows per industry, mirroring EPA USEEIO's own [import_emission_factors](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors) approach: `air_emissions` collapses to 5 curated GHG flows (EPA's own mapping, copied verbatim — see `exiobase_factors.py`), and the other five extensions each collapse to one flow scoped to the corresponding USEEIO indicator's coverage (e.g. material excludes crops/forestry/fishery/fossil fuels, keeping only metal ores and non-metallic minerals). These five won't numerically match either the older EPA repo's or cornerstone-data's published values, though — USEEIO computes them from separate US government data (BLS for jobs, EIA for energy, USDA for land, USGS for water and minerals), not from Exiobase, so this is a scope match only, not a value match. See [bea](bea#beyond-ghgs-employment-energy-land-material-water) for the full writeup. `trade_factor_lg.csv` still retains all 721 raw, unaggregated stressors for anyone who wants the full detail. See [bea](bea#epa-import-factor-reduction) for the full comparison against EPA's methodology.

**Two known data gaps in the aggregated flows (Exiobase v3.8.2, confirmed 2019 and 2021):** `energy` reads 0 for every row — Exiobase's own `energy` extension is entirely zero-valued in the raw source data, not something our selection can work around. `SF6`/`HFC`/`PFC` also read 0, but for a different reason — they have real nonzero emissions in Exiobase's raw flow data, but their Leontief-inverse M-matrix computation is 100% NaN for all three across every region, and the `fillna(0)` fix described in [bea](bea#epa-import-factor-reduction) (needed elsewhere, to treat genuine 0/0 sectors as real zeros) currently discards that real data here rather than confirming a genuine absence. See [bea](bea#beyond-ghgs-employment-energy-land-material-water) for details.

The bea/main.py command generates the following CSV files for US domestic flows:
- `interstate.csv` — one row per state-pair flow, BEA Sector level (`interstate_id`, `trade_id`, `state1`, `state2`, `sector1`, `sector2`, `state_industry_code`, `amount`, `commodity_code`, `industry_code`, `economic_multiplier`); `interstate-lg.csv` is the same at full Exiobase industry detail (`industry1`/`industry2`). Now always produced, satellite factor data available or not.
- `interstate_factor.csv` — real per-factor rows (`interstate_id`, `factor_id`, `level`, `flow_type`) when satellite data is available; joins to `interstate.csv` through `interstate_id` and to `factor.csv` through `factor_id`.
- `interstate_factor_lg.csv` — same with all 721 factors (set `use_partial_factors_interstate: false` in config.yaml).
- `interstate_estimate.csv` — produced instead of `interstate_factor.csv` when no satellite data is available: leftover fields from the disaggregation step (`interstate_id`, `employment_impact`, `flow_type`) that don't belong on `interstate` itself and aren't real per-factor data.

## Schema notes

**trade_id** is a sequential row index assigned per output file — it resets on every regeneration and only correlates a trade.csv row with its trade_factor.csv rows from the same run.

**Exiobase trade record order.** Comprehensive mode's `trade_id` sequence follows Exiobase's own row order (the `Z` matrix — inter-industry transaction flows), not a fresh alphabetical sort: region2 by its fixed position in Exiobase's own region list, industry1/industry2 by their fixed sector position, both independent of which rows happen to clear that year's amount threshold. Since this structural order never changes for a given Exiobase release, `trade_id` for a year comes out identical across regenerations — a stable, per-year index other systems can key off of when collaborating with this data, without it shifting on every rerun. See [PLAN-comprehensive.md](PLAN-comprehensive.md).

**interstate_id** is a composite string key, not a surrogate integer, since one international trade row fans out into many state-pair rows. Two forms exist depending on the file:

- Primary (interstate.csv, BEA Sector level): `{trade_id}-US-{state1}-US-{state2}-{sector1}-{sector2}`
- Full detail (interstate-lg.csv, Exiobase industry level): `{year}-{trade_id}-US-{state1}-US-{state2}-{state_industry_code}`

interstate keeps trade_id as the only path back to the originating international flow (amount, country, flow_type, exact industry pair) — interstate_id's embedded industry/sector is only a broad category used for state-allocation weighting, not the actual pair.

**Dedup keys.** trade: UNIQUE(region1, region2, industry1, industry2) — the true identity of a flow, since the same physical flow can appear in two different country-perspective CSV runs under different trade_id/country/flow_type. interstate: dedups on interstate_id itself (its primary key) — a narrower UNIQUE(state1, state2, sector1, sector2) constraint was tried and dropped after finding ~50,000 of 164,064 real 2021 rows share that tuple while differing only in state_industry_code.

**No bigserial id anywhere** — each table's primary key is its natural key: trade → (region1, region2, industry1, industry2); trade_factor → (trade_id, country, flow_type, factor_id); interstate → interstate_id; interstate_factor → (interstate_id, factor_id); interstate_estimate → interstate_id.

**interstate_factor vs. interstate_estimate** are mutually exclusive per run, split by whether Exiobase satellite factor data was available: interstate_factor holds real per-factor rows (factor_id always set); interstate_estimate holds only the no-satellite fallback's real fields (employment_impact, flow_type) — no placeholder factor_id/coefficient columns. interstate.csv itself is always produced either way.

**One database per year** — a Postgres database holds exactly one year (`{EXIOBASE_NAME}_{year}`), so trade, trade_factor, and interstate carry no year column; year is implicit in which database you're connected to. (interstate_id's own `{year}` prefix on the full-detail form is unrelated — just one more component of a string key, not a stored column.)

**Merging into one shared, multi-year `industrydb` is planned but not live yet** — see [team/PLAN-merge.md](https://github.com/ModelEarth/team/blob/main/PLAN-merge.md) for the design (a `year` column added only in the shared database, `dblink`-based, currently blocked on an Azure extension allow-list) and the [pipeline repo](https://github.com/ModelEarth/pipeline) for the Azure activation steps and its own `View Schema` link into this page.

**Import factors use Exiobase's M matrix** (total: direct + everything embodied in a sector's own upstream inputs, via the Leontief inverse), not the direct-only S matrix — matching EPA USEEIO's **import_emission_factors** methodology. Amounts stay in Euros (see Open work in [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md) for the USD conversion).

**Same-state rows are kept**, not filtered — `state1 == state2` rows are genuine intrastate flow (`flow_type = 'intra_state'`), included in the same normalization as cross-state rows so totals still sum to trade.amount.

**factor.csv has two row ranges:** raw per-stressor (1–721) and aggregated flows (901–910), a fixed offset so both coexist without collision regardless of a year's exact stressor count. trade_factor_lg.csv/interstate_factor_lg.csv reference the raw rows; the default trade_factor.csv/interstate_factor.csv reference the aggregate rows. See [bea](bea#epa-import-factor-reduction).

**industry, sector, and sector_industry** are a many-to-many split, not a single foreign key column. industry.csv holds Exiobase's ~200 raw sectors; sector.csv holds BEA's ~21 Sector categories; sector_industry.csv (sector_id, industry_id, weight) is the join, since 16 of the 200 Exiobase industries genuinely map to more than one candidate Sector. **Only interstate/interstate_factor are aggregated to Sector level** (via sector1/sector2, weighted-split across ambiguous industries) — trade/trade_factor stay at full Exiobase industry detail, since they were never the file-size problem that motivated the split (see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)).

## Industry Database API (team/src/main.rs)

| Endpoint | Method | Body / query | Purpose |
|---|---|---|---|
| /api/db/insert-trade-data | POST | `{year, country}` | Fetch CSVs from trade-data on GitHub and load them into that year's database, provisioning it first if needed |
| /api/db/delete-database | POST | `{year}` optional | Drop a year's database, or the shared base database if year is omitted |
| /api/db/industry-schema | GET | `?year=` | Live schema + row counts, used by the schema diagram on this page |
| /api/db/list-exiobase-years | GET | — | Years with a provisioned database right now |
| /api/db/test-exiobase-year-connection | GET | `?year=` | Connection health check for one year |
