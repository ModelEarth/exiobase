# US Interstate Trade

### US Bureau of Economic Analysis (BEA) Integration with Exiobase international tradeflow

The US-BEA data integration here combines Exiobase MRIO data with US Bureau of Economic Analysis API data to generate relational trade flow tables. This system extends our existing exiobase/tradeflow architecture to include detailed US trade analysis with enhanced state-level and industry-specific insights. Developed by referencing [US generate_import_factors.py](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors) — that USEPA org's active development has since moved to [cornerstone-data](https://github.com/cornerstone-data) (see "Beyond GHGs" below for what we've found there so far).

Our own industry classification (~200 codes, derived from Exiobase's raw sectors) has never been reconciled with BEA's official classifications (Detail ~405-411, Summary ~71-73, Sector ~21) that EPA's own process computes and publishes against — see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md) for the scoped plan to fix that, including the authoritative BEA source for the Sector-level crosswalk ([`apps.bea.gov/industry/release/zip/SUPPLY-USE.zip`](https://apps.bea.gov/industry/release/zip/SUPPLY-USE.zip), `Use_SUT_Framework_{year}_DET.xlsx`, sheet "NAICS Codes" — confirmed via `useeior`'s own build scripts) and the file-size-driven `-lg`/primary two-tier split this feeds into.

### BEA Factor Aggregation

The BEA interstate workflow assigns real Exiobase factor IDs to state-to-state flows by
loading the Exiobase satellite M matrix (total — direct + upstream supply chain, via the
Leontief inverse) with `pymrio`, and writing aggregated factor levels to
`interstate_factor.csv`. Using M rather than the direct-only S matrix matches EPA USEEIO's
[import_emission_factors](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors)
methodology — S alone would omit everything embodied in a sector's own inputs.

The default `trade_factor.csv`/`interstate_factor.csv` files no longer rank raw stressors by
coefficient magnitude and keep the top N — they aggregate (sum) raw stressors into a small,
fixed set of flows, the same way EPA does it. See [EPA import factor
reduction](#epa-import-factor-reduction) and [Aggregated flows](#aggregated-flows) below.
`trade_factor_lg.csv`/`interstate_factor_lg.csv` still carry every raw, unaggregated stressor
(all 721) for anyone who wants the full detail.

## EPA import factor reduction

How our factor selection compares to EPA USEEIO's [import_emission_factors](https://github.com/USEPA/USEEIO/tree/master/import_emission_factors):

**Matches EPA's methodology:**
- **M matrix, not S** — total requirements (direct + everything embodied in a sector's own upstream inputs, via the Leontief inverse), never the direct-only S matrix. We also fill NaN cells with 0 before aggregating, same as EPA — a handful of raw cells are a genuine 0/0 rather than a true 0, and since M is a global Leontief-inverse product, one NaN poisons that stressor's whole row everywhere. Correct when the flow really is absent (see the SF6/HFC/PFC note below for a case where it isn't).
- **Curated flow list, not magnitude ranking.** For air_emissions we copy EPA's own GHG mapping verbatim (see exiobase_factors.py, sourced from EPA's `mrio_config.yml`): CO2, CH4, N2O, and SF6 each map 1:1, HFC and PFC both map to "HFCs and PFCs, unspecified" — 5 output flows from 6 raw prefixes. This replaced an earlier top-N-by-magnitude selection that picked different substances than EPA's list and never aggregated rows together.
- **FEDEFL flow identities** — both use the [Federal LCA Commons Elementary Flow List](https://github.com/USEPA/fedelemflowlist).

**Differs by design (different output goal):**
- **Row-level detail, not regional aggregation.** EPA pre-aggregates countries into 7 import-weighted regions, one row per (sector, region, flow). We keep one row per actual trade flow — aggregated only across raw stressors within a flow, not across flows or countries. A regional rollup is a GROUP BY away, not baked into the pipeline.
- **Currency** — EPA converts EUR to USD; ours stays in Euros (see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)).
- **Country/sector mapping** — EPA uses MRIO-to-USEEIO concordance files; we map to our own industry_id, since our tables aren't scoped to the USEEIO model.

**Beyond EPA's own product:** EPA's factors only cover these 5 GHG flows. Our employment/energy/land/material/water flows (factor_id 906-910) are extra — not something EPA's methodology defines or that we're matching against. See below.

## Census import shares (goods) — closing the country-weighting gap

The CH4/N2O weighting gap noted above (`profile/footprint/PLAN.md` has the full validation writeup) comes down to this: EPA weights each BEA sector by real country-contribution-to-imports shares; we weight by a flat sum of Exiobase's own bilateral trade dollars. Checked 2026-09-24 by reading `USEPA/USEEIO`'s `import_emission_factors` scripts directly (in a local clone, not from memory): EPA's `generate_import_shares.py` computes those shares from **Census** (goods) + BEA (`IntlServTrade`, services) + EIA (electricity) combined, independently of the MRIO. We already call `IntlServTrade` for other things, but never Census — and Census is the half that actually matters for MRIO-based goods emission factors.

**Added so far:**
- `bea/census_api_client.py` — `CensusAPIClient`, same caching pattern as `main_api_client.py` (`census_cache/`), one request per exporting country against `https://api.census.gov/data/timeseries/intltrade/imports/naics` (`COMM_LVL=NA6`, `MONTH=12` for year-to-date-through-December — matches EPA's own `API/Census_API.yml` exactly).
- `bea/census_imports.py` — for a year + country list (defaults to `config.yaml`'s 14-country default, minus US the importer and WM the Exiobase RoW aggregate), fetches each country's imports by NAICS, maps to BEA Detail via a newly-vendored `trade-data/concordance/Census_to_useeio2_sector_concordance.csv` (schema 2017 by default — matches EPA's published `..._2019_17sch.csv` reference file we already compare against), and computes `cntry_cntrb_to_national_detail`/`cntry_cntrb_to_region_detail` (region = the 7-region scheme in the newly-vendored `country_to_region_concordance.csv`, with EPA's own `CA`/`MX`/`JP`/`CN` single-country-region special case). Writes `trade-data/year/{year}/import_shares_census.csv`.
- `census_key.py` — `CENSUS_API_KEY` lookup, same resolution order as `bea_key.py` (`automation/paths.yaml` → `docker/.env` → `.env` → environment).
- New vendored files: `trade-data/concordance/Census_to_useeio2_sector_concordance.csv`, `trade-data/concordance/country_to_region_concordance.csv`, `trade-data/concordance/census_country_codes.csv` (the last one is our own — a clean ISO↔Census-code CSV parsed from USEPA/USEEIO's pipe-delimited `data/Census_country_codes.txt`, since that file isn't published as a proper concordance CSV upstream).

**Needs a real credential, not just our code:** `USEPA/USEEIO`'s own `API/Census_API.yml` says `api_key_required: False`, but that's out of date — a request with no key gets redirected (302) to `https://api.census.gov/data/missing_key.html` with header `X-DataWebAPI-KeyError: 1` (confirmed directly with `curl`, 2026-09-24). A free key is required now, registered at [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html) and added as `CENSUS_API_KEY` to the `.env` file `automation/paths.yaml` points at. `census_api_client.py` follows the same pattern as `bea/main.py`'s `BEA_API_KEY` handling — prints what's blocked and offers an interactive prompt — but unlike a missing `BEA_API_KEY`, there's no graceful degradation here: every request returns 0 rows without a key.

**Run for 2019** (12 countries — see "WM coverage" below for why not 14): 2,827 (BEA Detail, country) rows in `trade-data/year/2019/import_shares_census.csv`, national contribution shares verified to sum to exactly 1.0 across all 244 BEA Detail sectors represented. One data-quality issue found and handled: NAICS `980000` (Census's "not elsewhere classified" catch-all) maps to the literal string `#N/A` in `Census_to_useeio2_sector_concordance.csv` — EPA's own `pandas.read_csv` silently treats that as a null and drops it via `groupby`; our `csv.DictReader`-based code doesn't do that automatically, so `census_imports.py` filters it explicitly.

**WM coverage — an open opportunity, with an unverified assumption to check first:** the 12 countries above are `config.yaml`'s 14-country default minus US (the importer, not a Census-tracked exporter here) and WM (Exiobase's "Rest of World, Middle East" aggregate — not a real country Census has its own code for). WM doesn't have to stay uncovered, though: `trade-data/concordance/exio_country_concordance.csv` already maps a set of real countries to `CountryCode=WM` (Bahrain, Iran, Iraq, Israel, Jordan, Kuwait, Lebanon, Oman, Qatar, Saudi Arabia, Syria, UAE, Yemen, plus a couple of Palestinian-territory rows), each with its own Census code — fetching and summing those individually would give a genuine (if approximate) Census-based WM import-share row instead of leaving WM out entirely.

**But verify that country list against Exiobase's own methodology before summing it.** Checked 2026-09-24: Exiobase's published papers (Stadler et al. 2018, and the "Adding country resolution to EXIOBASE" follow-up) confirm the 5-region RoW split exists, but neither publishes the actual country-by-country table of which nations got folded into each RoW aggregate — that mapping lives in Exiobase's own internal build process, not in anything I could find publicly. `exio_country_concordance.csv`'s WM list may be a BEA/Census-style "Middle East" grouping rather than Exiobase's actual one, and the two don't necessarily agree — Israel and Saudi Arabia in particular are worth double-checking, since a geographic "Middle East" grouping commonly includes both, but Exiobase's own regional/economic classification (it groups by more than pure geography elsewhere, e.g. lumping Mexico with the single-country "MX" region rather than an Americas RoW bucket) might not. If they turn out not to belong in Exiobase's actual WM, they'd need excluding from the sum — summing countries Exiobase itself doesn't count as WM would overstate that bucket's import share. Before implementing this rollup, either find Exiobase's actual technical documentation/build scripts confirming WM's real membership, or treat `exio_country_concordance.csv`'s list as an approximation and say so wherever the resulting WM row is used.

**Not yet done:** the BEA (services) and EIA (electricity) thirds of EPA's own `get_imports_data()`, the Summary-level rollup (`cntry_cntrb_to_*_summary`), the WM rollup above, and — the actual point of all this — wiring `import_shares_census.csv` into `main.py`'s BEA Detail aggregation to replace the flat trade-dollar weighting and re-check the CH4/N2O gap. This gets us the input data; the weighting-methodology change itself is a separate follow-up.

## Beyond GHGs: employment, energy, land, material, water

EPA's own product doesn't cover these five extensions — there's no curated mapping to copy the way there was for GHGs. USEEIO's continuation at [cornerstone-data](https://github.com/cornerstone-data) does define matching target indicators:

| Extension (ours) | USEEIO indicator | Unit |
|---|---|---|
| employment | Jobs Supported (JOBS) | jobs |
| energy | Energy Use (ENRG) | MJ |
| land | Land Use (LAND) | m²·yr |
| material | Minerals and Metals Use (MNRL) | kg |
| water | Water Use (WATR) | m³ |

**These indicators come from separate US government inventories** (BLS jobs, EIA energy, USDA land, USGS water/minerals), not from characterizing MRIO stressors — so there's no dict to copy, and we can't reproduce USEEIO's actual published values without integrating those external sources (not attempted here).

**What we did instead:** kept our own extension names, but replaced "sum every raw stressor" with a selection scoped to match each indicator as closely as Exiobase's own categories allow:

- **employment** — only "Employment people" counts (not "Employment hours" too, a different unit), matching Jobs Supported's headcount scope.
- **energy** — Exiobase has 4 rows (Gross/Net/Final/Emission-relevant) that are different measurement bases of the *same* total, not additive; summing all 4 overcounted ~4x. Only "Energy use - Gross" counts now.
- **water** — similarly, only "Water Withdrawal Blue" counts (not "Consumption Blue," a different measure of the same use, or "Consumption Green," a different resource entirely).
- **material** — Exiobase's "Domestic Extraction Used" spans crops/forestry/fishery/fossil fuels too; Minerals and Metals Use covers only metal ores and non-metallic minerals, so the rest are excluded.
- **land** — genuinely additive across its categories already, unchanged.

**Two known zero-data gaps (Exiobase v3.8.2, confirmed 2019/2021), neither fixable in our own code:**
- **energy reads 0 for every row** — Exiobase's own energy extension is entirely zero in the raw source data. Matching this indicator at all needs a different data source (another Exiobase extension, or EIA directly).
- **SF6/HFC/PFC (factor_id 904/905) also read 0** — but for a different reason: real nonzero values exist in Exiobase's raw flow data, but their M matrix is 100% NaN across every region, so our fillna(0) fix (needed elsewhere for genuine zeros) hides real emissions here instead. Fixing this means finding and correcting whichever underlying cell poisons these three rows — not attempted here.

See exiobase_factors.py's `EXTENSION_STRESSOR_PREFIXES` for the exact selection.

**Will this align with the older EPA repo and the newer cornerstone site?** For GHGs: yes with the older [USEPA/USEEIO](https://github.com/USEPA/USEEIO) `import_emission_factors` repo directly — we copied its exact `mrio_config.yml` mapping and its `clean_exiobase_M_matrix()` split-map-filter-sum approach, so our GHG aggregation implements the same methodology on the same Exiobase data (modulo whatever Exiobase version/year each side uses). cornerstone-data hasn't published its own copy of that specific GHG tool — it isn't in their repo list — so there's nothing there to diverge from; our conceptual alignment with cornerstone is only through `useeior`'s shared "Greenhouse Gases" indicator naming, not a second implementation to check against. For the other five, see the next section — we no longer have to leave this as "scope match only."

### Aligning the other five with USEEIO's own pre-compiled indicators (not raw BLS/EIA/USDA/USGS)

The "not attempted here" above (integrating BLS/EIA/USDA/USGS ourselves) turned out to be
unnecessary — EPA's own model-building pipeline (`useeior`) already computes JOBS/ENRG/LAND/MNRL/
WATR from those four agencies' data and publishes the *result* as a per-BEA-Detail-sector,
per-dollar-of-output matrix. That result is already sitting in this checkout, no network fetch
needed: **`io/build/api/USEEIOv2.0.1-411/`** — a local vendored copy of
[`ModelEarth/useeio-json`](https://github.com/ModelEarth/useeio-json)'s national model, already
used by `profile/footprint/js/config.js`, `io/charts/inflow-outflow/index.html`, and
`io/charts/bubble/js/bubble.js`. `indicators.json` confirms all 23 USEEIO indicators are present
(including JOBS/ENRG/LAND/MNRL/WATR); `matrix/N.json` is the 23×411 total-requirements (direct +
upstream) matrix, `sectors.json` gives each column's BEA Detail code. Joining that to our own
trade data means comparing against USEEIO's real government-sourced numbers instead of only our
own Exiobase-scoped approximation of them.

**`bea/useeio_indicator_alignment.py`** does this join, mirroring
`profile/footprint/index.html`'s already-validated `loadBeaFactorData()` (the CO2/CH4/N2O vs. EPA
comparison above): `trade.csv`'s `industry1` (the exporting country's Exiobase industry — what's
actually being imported) resolves to every matching `USEEIO_Detail_2012` BEA code via
`exio_to_useeio2_commodity_concordance.csv` (full fan-out, no fractional split, same as the GHG
comparison), each BEA Detail's "ours" rate is our own summed `trade_factor.csv` level divided by
our own summed USD imports for that code (`amount * EUR_TO_USD_2019`, no per-year lookup yet — see
the TO DO below), and "USEEIO" is `N[indicator_index][sector_index]` converted from USEEIO's
native unit into ours (jobs→1000 persons, MJ→TJ, m²·yr→km² approximated as a static area, kg→
kilotonnes, kg→Mm³ via 1000 kg/m³). Run it with `python3 bea/useeio_indicator_alignment.py --year
2019`; it writes a per-BEA-Detail CSV alongside itself and prints a summary.

**2019 results** (379 BEA Detail codes matched, `usd_imports > 0`):

| Extension | matched | median ratio (ours/USEEIO) | % within 2x |
|---|---|---|---|
| employment | 376 | 4.23x | 15.7% |
| energy | 0 | n/a — ours is 0 for every row (Exiobase's own energy extension is all-zero, see above) | n/a |
| land | 377 | 1.57x | 47.7% |
| material | 378 | 4.75x | 17.2% |
| water | 378 | 1.16x | 55.0% |

**Reading these numbers:** land and water land in the same rough neighborhood as the CO2 GHG
comparison (median ~0.9-1.6x) — plausibly explained by the uncorrected 2012-vs-2019 dollar-year
mismatch alone (USEEIO's N matrix is fixed at 2012-USD-of-output; our USD imports above are 2019
trade converted at a flat EUR/USD rate with no inflation adjustment back to 2012 dollars — that's
~15-20% of CPI drift baked into every ratio before any real methodology difference). Employment
and material are a real, unexplained gap (~4-5x, systematically over rather than scattered both
ways) too large for currency drift alone to explain — not root-caused here. Candidates worth
checking before trusting these two: whether "Employment people" (our proxy) and JOBS (USEEIO's
headcount, which includes indirect/induced jobs across the whole supply chain) are actually the
same scope of jobs: whether Minerals and Metals Use's Detail-level 2012 vs 2017 boundary drift
(see the NAICS differences note near the end of this file) misattributes some material use, or
whether Exiobase's "Domestic Extraction Used - Metal Ores / Non-Metallic Minerals" and USEEIO's
MNRL indicator just don't line up 1:1 in scope despite the name match.

Related pages:
- [US interstate trade map](../../../profile/trade/map/state.html)
- [State Sankey chart](../../../profile/charts/sankey/state.html#state=CO)
- [International trade map](../../../profile/trade/map)


The following US BEA integration with Exiobase international trade flow data uses the [industry.csv file](https://github.com/ModelEarth/trade-data/blob/main/year/2019/industry.csv) from the separate Exiobase pull of US domestic commodity flow. Industry columns are: industry_id and name (the exiobase sector information).

The term "level" is instead of "flow_value" or "impact_value".
We have "trade_factor.level" (international) and "interstate_factor.level" (state-to-state)

**Units**

Each factor level is one of 6 units. (These apply to all 721 factors.)

- air_emissions (kg)
- employment (1000 persons)
- energy (terajoules)
- land (km²)
- material (kilotonnes)
- water (Mm³ million cubic metres)

The default files aggregate down to 5 GHG flows for `air_emissions` plus one scoped flow per
other extension (10 total per industry) instead of raw per-stressor rows — see [Aggregated
flows](#aggregated-flows) and [EPA import factor reduction](#epa-import-factor-reduction).
(An earlier top-120-by-magnitude scheme produced a 5 GB `interstate_factor.csv`; the aggregated
scheme is far smaller since it's 10 rows per industry rather than up to 120 or 721.)

We don't save a "coefficient" column since it can be derived from `trade_factor.level / 
trade.amount`, and from `interstate_factor.level / interstate.amount`.

Both trade.amount and interstate.amount are in Euros to sync with Exiobase.
TO DO: We need to add a euro_dollar lookup by year.

### Reports
- [Sankey](../../../profile/trade/map/sankey.html)
- [Sample Report from Output](../../../trade-data/bea-dashboard/) — still references pre-rename column names, needs updating (see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md))
- State-to-state domestic trade flows (interstate.csv)
- State export competitiveness analysis (export_competitiveness.csv)
- Import dependency by state (import_dependency.csv)

## Configuration Settings

Get your [BEA API Key](https://apps.bea.gov/api/signup/)

**Year**: set in `../config.yaml` (`YEAR` field)
**Country**: US (from `../config.yaml`)
**Trade Flows**: domestic, imports, exports (from `../config.yaml`)
**Base Architecture**: Leverage existing exiobase/tradeflow preprocessing and Exiobase data downloads

### Prerequisites

Before running, ensure the following exist:
- `exiobase_data/IOT_{year}_pxp.zip` — Exiobase download (run `../main.py` or `../trade.py` first)
- `../../trade-data/year/{year}/US/domestic/trade.csv` — run `../trade.py` for domestic flow, or pass `--force-regen`
- `../../trade-data/year/{year}/US/imports/trade.csv` — run `../trade.py` for imports flow
- `../../trade-data/year/{year}/US/exports/trade.csv` — run `../trade.py` for exports flow
- `BEA_API_KEY` — optional; without it, `commodity_code`, `industry_code`, and `economic_multiplier` fall back to empty/default values. Resolved from a local environment file if present, else `webroot/docker/.env` or `webroot/.env` (or pass via `--bea-key`).
- `trade-data/concordance/*.csv` — fetched automatically from [ModelEarth/trade-data](https://github.com/ModelEarth/trade-data/tree/main/concordance) on first run if not already present locally; the run stops with a clear message if a needed file isn't found there either, rather than silently falling back.

### Primary Module: main.py

Orchestrates all three tradeflows through a five-phase pipeline: base Exiobase data generation, BEA API enhancement, state-level analysis, FEDEFL integration, and relational CSV output.

**Uses:**
- `year/{year}/US/{tradeflow}/trade.csv` — pre-generated by `../trade.py`; skipped if already exists (use `--force-regen` to override)
- `year/{year}/industry.csv` and `year/{year}/factor.csv` — shared reference files from parent tradeflow directory
- A local environment file if present, else `webroot/docker/.env` or `webroot/.env` — reads `BEA_API_KEY`
- `../config.yaml` — year, country, tradeflow settings via `../config_loader.py`
- `exiobase_data/IOT_{year}_pxp.zip` — loaded directly via pymrio to extract the M matrix (total multipliers) for `factor_id` assignment in `interstate_factor.csv`

**Generates:**
- `year/{year}/US/domestic/interstate.csv` — BEA-enhanced state-to-state trade detail; always produced, satellite data available or not
- `year/{year}/US/domestic/interstate_factor.csv` — real per-factor state-level flows (satellite data available)
- `year/{year}/US/domestic/interstate_factor_lg.csv` — same as above with all 721 factors (generated when `use_partial_factors_interstate: false` in `config.yaml`)
- `year/{year}/US/domestic/interstate_estimate.csv` — no-satellite-fallback leftover fields (satellite data unavailable); mutually exclusive with `interstate_factor.csv` per flow
- `year/{year}/US/domestic/trade_price_indices.csv` — trade price indices (currently empty; see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md))
- `year/{year}/US/bea-report.md` — validation and processing summary report

**Note:** interstate factor coefficient (from Exiobase's M matrix — total, direct + upstream) is not stored. coefficient can be derived by trade.amount divided by trade_factor.level


```bash
# Run from exiobase/tradeflow/ using the ~/env Python environment
~/env/bin/python3 bea/main.py

# Using command line API key
~/env/bin/python3 bea/main.py --bea-key YOUR_API_KEY

# Force regeneration of existing trade.csv files
~/env/bin/python3 bea/main.py --force-regen

# Get help on available parameters
~/env/bin/python3 bea/main.py --help
```

Or run it automatically after each year's trade data, via `python main.py --interstate US` from
[../](..) — see [../README.md](../README.md). Add `,IN` (`--interstate US,IN`) to also run
[../india/main.py](../india) in the same combined run.

<br>

# Tables Name and Column Design

For .csv import to SQL

CSV Output preview resides in [trade-data/year/2019/US/domestic](https://github.com/ModelEarth/trade-data/tree/main/year/2019/US/domestic)

See our [bea-report.md](https://github.com/ModelEarth/trade-data/blob/main/year/2019/US/bea-report.md) files for latest output overview.

## interstate

The state-to-state `interstate` table is similar to the international `trade` table — renamed from the older `bea_trade_detail.csv`.

<!--
trade_id, bea_commodity_code, bea_industry_code, trade_balance, import_value, export_value, trade_partner_state, transport_mode
-->

**columns**
interstate_id, trade_id, state1 (NY), state2 (CA), sector1, sector2, state_industry_code, amount,
commodity_code, industry_code, economic_multiplier

(BEA Sector level, the primary/committed file; the full-detail `interstate-lg.csv` sibling has the
same columns at Exiobase's native industry grain, `industry1`/`industry2` instead of `sector1`/`sector2`.)

**Four different industry/commodity classifications appear on this one table, at four different
granularities — confirmed by reading `_merge_bea_domestic()` in `main.py`, since the column names
alone don't make the distinction obvious:**

| Column | Classification | Granularity | Populated from |
|---|---|---|---|
| `industry1`/`industry2` (interstate-lg only) | raw Exiobase industry | ~200 codes, 5-char | `industry.csv` (Exiobase's own taxonomy) |
| `commodity_code` | USEEIO/BEA **Detail** (NAICS-derived) | ~411 codes, 6-char (e.g. `1111A0`) | `trade-data/concordance/exio_to_useeio2_commodity_concordance.csv`, joined via `industry1`'s Exiobase name — no BEA API needed |
| `industry_code` | BEA **Summary** | ~71-73 codes | `trade-data/concordance/useeio_internal_concordance.csv`'s `BEA_Summary` column, keyed off the same commodity_code — no BEA API needed; only `economic_multiplier` (below) actually calls the BEA API |
| `sector1`/`sector2` | BEA **Sector** (the coarsest tier, ~21 categories, e.g. `11`=Agriculture, `21`=Mining) | ~21 codes | `bea_summary_to_sector_concordance.csv`, one more rollup above Summary — see [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md) |

So the full chain, finest to coarsest: `industry1`/`industry2` (Exiobase) → `commodity_code` (BEA
Detail) → `industry_code` (BEA Summary) → `sector1`/`sector2` (BEA Sector).

**`state_industry_code` is a fifth, unrelated classification** — not part of the chain above at
all. It's one of only 7 broad BEA GDP-by-state allocation buckets (`agriculture`, `mining`,
`utilities`, `construction`, `manufacturing`, `transportation`, `services` — see
`BEA_ORIGIN_ALLOCATION_LINES`/`BEA_DESTINATION_ALLOCATION_LINES` in `main.py`), used only to
weight how much of a national flow gets allocated to a given state pair. Don't confuse it with
`industry_code` (BEA Summary) just because both contain the word "industry."

**Matching the USEEIO Excel sheets without a `BEA_API_KEY`:** `commodity_code` and `industry_code`
above don't need one — they're a pure local-file join through the two concordance CSVs. The only
things a missing key actually affects are `economic_multiplier` (falls back to `1.0`) and, without
also passing `--use-bea-placeholder`, domestic processing being skipped entirely (see
`BEA_API_KEY_MISSING_NOTICE` in `bea/main.py` for the exact tradeoffs — `bea/main.py` now prints
this at both the start and end of a run when no key is found, and offers to prompt for one
interactively instead of hard-exiting like it used to).

`interstate_id` is a composite string key (`{year}-{trade_id}-US-{state1}-US-{state2}-{state_industry_code}`), not a surrogate integer — it's the `PRIMARY KEY` of the `interstate` table and the join target for `interstate_factor`/`interstate_estimate`, since one `trade_id` fans out to 150+ state-pair rows. `trade_id` is kept on `interstate` (not on `interstate_factor`/`interstate_estimate`) as the only path back to the originating international `trade` row (`trade.amount`, `trade.country`, `trade.flow_type`) — navigate as `interstate_factor → interstate → trade`. There is no `year` column — one database per year makes it redundant.

**interstate.amount** is in million Euros (M EUR), consistent with `trade.amount` — both are sourced from the Exiobase Z matrix.

The interstate.amount is tradeflow amount allocated to a specific state (region) pair and industry pair.

**economic_multiplier** is the BEA Input-Output total industry output requirement for the mapped BEA Summary `industry_code`. It is used to estimate total output impact:

```text
total_output_impact = interstate.amount * economic_multiplier
```

The value comes from BEA InputOutput TableID 61 rows where `RowDescr` is `Total industry output requirement`. If no BEA match is found, the fallback is `1.0`.

## interstate_factor

**interstate_factor.level** is in physical units — not Euros. The coefficient converts M EUR → a physical quantity whose unit varies by extension:

| Extension | Unit |
|---|---|
| air_emissions | kg |
| employment | 1000 persons |
| energy | TJ (terajoules) |
| land | km² |
| material | kt (kilotonnes) |
| water | Mm³ (million cubic metres) |

The unit for any given row is found by joining to `factor.csv` on `factor_id` and reading the `unit` column.

The "interstate" table has the same structure as the international "trade" table.
In some SQL installs, we'll place state data in the "trade" table with multi-country trade data.


#### interstate_factor - rename from [state_trade_flows.csv](https://raw.githubusercontent.com/ModelEarth/trade-data/refs/heads/main/year/2019/US/domestic/state_trade_flows.csv) (State-Level Analysis)
interstate_id, factor_id, level, flow_type

Real per-factor rows only — generated when Exiobase satellite data is available. `origin_state` and `destination_state` are not separate columns here — they are encoded in `interstate_id` and available via `interstate.state1` / `interstate.state2`.

**Column notes:**
- `interstate_factor.level` = `interstate.amount × coefficient`, rounded per extension (3dp for water/air_emissions, integer for others). `coefficient` is not stored separately — it is derivable as `level / interstate.amount`. The column is named `level` rather than `levelX` to avoid implying a monetary unit — it is a physical quantity (kg, persons, TJ, etc.).
- `state_industry_code` is omitted from `interstate_factor` — available via a join to `interstate`.
- `flow_type` is `inter_state` or `intra_state` (same-state flows are kept, not dropped — see [Schema notes](../README.md#schema-notes)).
- `employment_impact` is not a column here — when satellite data is available, employment is captured as ordinary Exiobase employment-extension factor rows, not a separate field.
- `interstate_factor.trade_id` is omitted — the trade relation can be navigated as `interstate_factor → interstate → trade`; note `interstate.sector1`/`sector2` (BEA Sector codes) don't align 1:1 with `trade.industry1`/`industry2` (Exiobase industry codes) — `trade`/`trade_factor` stayed at full industry detail, only `interstate` was aggregated to Sector level.
- `interstate.state1` and `interstate.state2` are state codes only (e.g. `NY`, `CA`), not prefixed with `US-`.

#### Aggregated flows

Each Exiobase sector has environmental coefficients for up to 721 raw stressors (air emissions, employment, energy, land, material, water). `interstate_factor.csv` no longer keeps a top-N slice of those raw rows — it aggregates them into a small, fixed set of flows per industry: 5 GHG flows for `air_emissions` (EPA's own curated list, see [EPA import factor reduction](#epa-import-factor-reduction)) plus one scoped flow per other extension (employment, energy, land, material, water — matched to USEEIO indicator scope, see [Beyond GHGs](#beyond-ghgs-employment-energy-land-material-water)), for up to 10 rows per industry rather than 50 or 721. Setting `use_partial_factors_interstate: false` in `config.yaml PROCESSING` additionally generates **`interstate_factor_lg.csv`** (Large File — All 721 raw, unaggregated factors) alongside the aggregated default file.

See [EPA import factor reduction](#epa-import-factor-reduction) for how this selection compares to EPA's USEEIO aggregation approach.

## interstate_estimate

interstate_id, employment_impact, flow_type

Generated instead of `interstate_factor.csv` when Exiobase satellite data is **not** available for a given run — the two files are mutually exclusive per flow (a given `interstate_id` produces rows in one or the other, never both). It carries only the no-satellite fallback's real leftover fields: `employment_impact` (from BEA regional employment/output weights, not Exiobase) and `flow_type` (`inter_state`/`intra_state`). The fallback source data's `factor_id`/`coefficient` are fixed placeholders (`-1`/`1.0`, never recalculated against real Exiobase coefficients), so they are deliberately excluded rather than stored as meaningless constants — this is also why `interstate_estimate` is a separate table from `interstate_factor` rather than a shared one with nullable factor columns: a `-1` `factor_id` isn't a valid `factor.factor_id` and would need to be filtered out on every read.

## trade_price_indices

#### [trade_price_indices.csv](https://github.com/ModelEarth/trade-data/blob/main/year/2019/US/domestic/trade_price_indices.csv) (Economic Indicators)
trade_id, import_price_index, export_price_index, exchange_rate, price_year, currency_adjustment_factor

Open question (tracked in [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md)): why is the table above empty?

## industry / sector / sector_industry (created by international tradeflow/main.py)

#### [industry.csv](https://github.com/ModelEarth/trade-data/blob/main/year/2019/industry.csv) (raw Exiobase industry names, ~200 rows)
industry_id, name, category

Used by all countries and states. Industry Mapping - using existing file

#### sector.csv (BEA Sector classification, ~21 categories + Used/Other)
sector_id, name

#### sector_industry.csv (many-to-many join between sector and industry)
sector_id, industry_id, weight

`sector_industry` exists because the Exiobase→BEA-Sector mapping is genuinely many-to-many (16/200
industries chain to more than one candidate Sector, checked empirically) — a single
`industry.sector_id` column can't represent that. `weight` (per `industry_id`, summing to 1.0) is how
BEA-Sector-level `interstate.csv` amounts split proportionally across an ambiguous industry's
candidate sectors. See [PLAN.md](https://github.com/ModelEarth/exiobase/blob/main/tradeflow/PLAN.md).

*Note: `industry.csv` resides at the root of the annual directory (year/{year}/industry.csv) and is
generated by other Python scripts in the tradeflow folder. `bea_industry_mapping.csv` is no longer
generated — the BEA process uses this shared file instead.*


## flow

#### [flow.csv](https://github.com/ModelEarth/trade-data/blob/main/year/2019/flow.csv) (FEDEFL Integration)
flow_uuid, flowable, context, unit, compartment, flow_class, preferred, external_reference

"flow" was included here to review. It will NOT be a SQL table.
The "[flow](https://github.com/ModelEarth/trade-data/blob/main/year/2019/flow.csv) " table is NOT in our relational data structure since it resides in "trade", "interstate" and "factor"

Probably NOT using here. Replaced by our "[factor](https://github.com/ModelEarth/trade-data/blob/main/year/2019/factor.csv)" table.
And in our table naming, "[trade](https://github.com/ModelEarth/trade-data/blob/main/year/2019/US/domestic/trade.csv)" and "interstate" contain the trade flow.

<br>

# Analytical Enhancement Tables

IMPORTANT: These won't be needed in SQL since they can be table joins. Useful for .csv static reports.

## export_competitiveness

#### [export_competitiveness.csv](https://raw.githubusercontent.com/ModelEarth/trade-data/refs/heads/main/year/2019/US/exports/export_competitiveness.csv) (Export Analysis, generated by trade_competitiveness.py)
trade_id, industry_exports_total, destination_share, export_intensity, destination_count, export_concentration_hhi

## import_dependency

#### [import_dependency.csv](https://raw.githubusercontent.com/ModelEarth/trade-data/refs/heads/main/year/2019/US/imports/import_dependency.csv) (Import Analysis, generated by trade_competitiveness.py)
trade_id, industry_imports_total, source_share, import_intensity, supplier_count, import_concentration_hhi

## state_industry_impacts

#### [state_industry_impacts.csv](https://github.com/ModelEarth/trade-data/blob/main/year/2019/US/domestic/state_industry_impacts.csv) (State Economic Impact)

region (US-AK), industry_code, direct_jobs, indirect_jobs, induced_jobs, total_output_impact, tax_revenue_impact

<br>

# Output Structure

The "trade" tables are generated by tradeflow/main.py
The "interstate" tables are generated by tradeflow/bea/main.py

```
year/[year]/
└── US/
    ├── domestic/
    │   ├── trade.csv                     # Base trade flows (pre-exists from ../trade.py)
    │   ├── trade_factor.csv              # Environmental coefficients (pre-exists)
    │   ├── interstate.csv                # BEA-enhanced state-to-state tradeflow
    │   ├── interstate_factor.csv         # State-to-state factor (flow) level — aggregated flows (see EPA import factor reduction)
    │   ├── interstate_factor_lg.csv      # Same, all 721 factors (use_partial_factors_interstate: false)
    │   ├── interstate_estimate.csv       # No-satellite fallback leftovers (mutually exclusive with interstate_factor.csv)
    │   ├── state_industry_impacts.csv    # State economic impacts
    │   ├── trade_price_indices.csv       # Trade price indices (currently empty)
    │   ├── state_codes.csv               # US state reference list
    │   ├── employment_multipliers.csv    # Per-industry employment multipliers
    │   └── state_specializations.csv     # State industry specializations
    ├── exports/
    │   └── export_competitiveness.csv    # RCA and export sophistication by trade_id
    ├── imports/
    │   └── import_dependency.csv         # Import vulnerability and alternatives by trade_id
    ├── bea-report.md                     # Validation and processing summary
    ├── factor.csv                        # Base environmental factors
    ├── flow.csv                          # FEDEFL flow details (review only)
    ├── flow_summary.json                 # Flow counts by context/compartment
    ├── flow_validation.json              # Factor-to-flow mapping completeness
    └── industry.csv                      # Industry mapping (from parent directory)
```

<br>

# Supporting Modules

All 3 are invoked by bea/main.py

## 1. main_api_client.py

BEA API authentication and data retrieval with rate limiting, response caching, and column standardization.
Called during Phase 2 (BEA API Enhancement) of each tradeflow.

**API Endpoint**: https://apps.bea.gov/api/data/
**Datasets fetched:**
- IntlServTrade — International Trade in Goods and Services (imports, exports, and state-level exports)
- InputOutput — Industry input-output tables (`Summary` or `Detail`)
- GDPbyIndustry — GDP by industry

**BEA-sourced columns in `interstate.csv`**

These columns are in `interstate.csv` (not `interstate_factor.csv`, which only has `interstate_id, factor_id, level`).

These columns are populated with BEA API data when available. When the API returns no data, `--use-bea-placeholder` allows the run to continue using fallback values; without it, rows dependent on BEA data are omitted.

Fallback values (used only with `--use-bea-placeholder` when API is unavailable): `import_value`, `export_value`, and `trade_balance` fall back to `interstate.amount` (derived from `trade.csv amount`); `commodity_code`, `industry_code`, and `economic_multiplier` fall back to static defaults.

| Column | Tradeflow | BEA dataset | Fallback when API unavailable |
|---|---|---|---|
| `commodity_code` | imports, exports | IntlServTrade | `""` (empty string) |
| `industry_code` | imports, exports | IntlServTrade | `""` (empty string) |
| `trade_balance` | imports, exports | IntlServTrade | copied from `trade.csv amount` |
| `import_value` | imports | IntlServTrade | copied from `trade.csv amount` |
| `export_value` | exports | IntlServTrade | copied from `trade.csv amount` |
| `economic_multiplier` | domestic | InputOutput | `1.0` |

For domestic rows, `economic_multiplier` is populated from BEA Input-Output TableID 61 rows whose `RowDescr` is `Total industry output requirement`, matched by BEA Summary `industry_code`. Rows without a BEA multiplier match keep the fallback value `1.0`.

**Uses:**
- BEA API key from a local environment file if present, else `docker/.env` or `webroot/.env` (`BEA_API_KEY=...`), or `--bea-key` argument
- `bea_cache/*.json` — cached responses from prior runs (24-hour TTL; API key excluded from cache keys)

**Generates:**
- `bea_cache/*.json` — one file per unique API request; auto-expires after 24 hours

<!--

To clear stale cache manually:
```bash
# Run from exiobase/tradeflow/bea/
python -c "from us_bea_api_client import BEAAPIClient; BEAAPIClient('dummy').clear_cache()"

# Clear only files older than 48 hours
python -c "from us_bea_api_client import BEAAPIClient; BEAAPIClient('dummy').clear_cache(older_than_hours=48)"
```
-->


## 2. main_trade_analyzer.py

State-level trade flow disaggregation, employment and output impact calculations, export competitiveness, and import dependency analysis. Called during Phase 3 (State-Level Analysis).

**Uses:**
- `year/[year]/US/domestic/trade.csv` — base domestic trade flows; must pre-exist (generated by `../trade.py`)
- BEA domestic and state export data passed in from `main.py` after Phase 2
- Internal state employment multipliers and specialization weights (placeholder values; intended to be replaced with live BEA regional data)

**Generates:**
- `year/[year]/US/domestic/interstate_factor.csv` — state-to-state trade flows, aggregated flows (see EPA import factor reduction)
  Columns: `interstate_id` (integer FK to interstate.csv), `factor_id`, `level` (2dp)
- `year/[year]/US/domestic/interstate_factor_lg.csv` — same with all 721 factors; generated when `use_partial_factors_interstate: false` in `config.yaml`
- `year/[year]/US/domestic/state_industry_impacts.csv` — employment and output impacts aggregated by destination region and industry
  Columns: `region (US-AK), industry_code, direct_jobs, indirect_jobs, induced_jobs, total_output_impact, tax_revenue_impact`
- `year/[year]/US/exports/export_competitiveness.csv` — RCA, sophistication index, market share, growth rate per trade_id
- `year/[year]/US/imports/import_dependency.csv` — import penetration ratio, supply chain vulnerability, alternative supplier count, strategic importance per trade_id
- `year/[year]/US/domestic/state_codes.csv` — US state reference list (51 entries including DC)
- `year/[year]/US/domestic/employment_multipliers.csv` — per-industry direct, indirect, and induced multipliers
- `year/[year]/US/domestic/state_specializations.csv` — state industry specialization index

Invoked automatically by `main.py` — domestic tradeflow triggers state disaggregation and impacts; exports triggers competitiveness analysis; imports triggers dependency analysis:


## 3. main_fedefl_integration.py

Federal LCA Commons Elementary Flow List (FEDEFL) integration for environmental flow metadata and factor-to-flow mapping. Called during Phase 4 (FEDEFL Integration) of each tradeflow.

**Uses:**
- Official FEDEFL flow list workbook by default: `https://dmap-data-commons-ord.s3.amazonaws.com/fedelemflowlist/FedElemFlowList_1.3.0_all.xlsx`
- Optional override with `FEDEFL_FLOWLIST_URL` for a newer workbook URL or local workbook path
- 24 built-in FEDEFL-compatible seed flows only as a fallback when the workbook is unavailable: 10 air emissions (CO₂, CH₄, N₂O, SO₂, NOₓ, PM, CO, VOC, NH₃, benzene), 6 water emissions (BOD, COD, suspended solids, total N, total P, heavy metals), 5 resources (water, energy, land, fossil fuel, mineral), 3 economic flows (employment, value added, tax revenue)
- `year/[year]/factor.csv` — trade factor definitions, passed in for completeness validation
- Common Exiobase air-emission labels are normalized before matching, for example `CO2 - combustion - air` maps to the FEDEFL `Carbon dioxide` row with context `emission/air`. Fuzzy FEDEFL matching is limited to air emissions; land, water, material, energy, and employment factors stay as Exiobase-derived rows unless an exact FEDEFL flowable is found.

**Generates:**
- `year/[year]/flow.csv` — comprehensive FEDEFL flow table
  Columns: `flow_uuid, flowable, context, unit, compartment, flow_class, preferred, external_reference, cas_number, formula, synonyms, trade_relevance`
  **Note:** for review only; not a SQL table. The `factor_id` (not `flow_uuid`) is the linkage used in trade and interstate tables.
- `year/[year]/flow_summary.json` — flow counts by context, compartment, and flow class
- `year/[year]/flow_validation.json` — factor-to-flow mapping report: exact matches, partial matches, and auto-created flows

Invoked automatically by `main.py`. To test flow loading in isolation:
```bash
# Run from exiobase/tradeflow/bea/
python -c "
from main_fedefl_integration import FEDEFLIntegrator
f = FEDEFLIntegrator()
flows = f.load_fedefl_flows()
print(f'{len(flows)} flows loaded')
"
```

<br>

# Data Quality and Validation

### 1. Cross-Source Reconciliation (on hold until we have in SQL)
- Compare Exiobase and BEA trade values for consistency
- Flag significant discrepancies for manual review
- Apply scaling factors where appropriate

### 2. State-Level Validation
- Ensure state exports sum to national totals
- Validate employment multipliers against BEA benchmarks
- Cross-check industry classifications

### 3. FEDEFL Integration Quality (Not doing currently since not using UUIDs)
- Verify Flow UUID mapping completeness
- Ensure environmental flow consistency
- Validate units and contexts

### 4. Scalability
- Designed for easy extension to other years
- Enables selective processing of specific tradeflows
- Support incremental updates and data refreshes


<br>

# Trade-Data Repo

Output is deployed in our [trade-data repo](https://github.com/ModelEarth/trade-data) to keep local folders small.

[Intro](https://model.earth/profile/trade/) - output sent to [modelearth/trade-data](https://github.com/ModelEarth/trade-data/tree/main/year/2019/US)
trade-data repo receives from python in [exiobase/tradeflow](https://model.earth/exiobase/tradeflow/) and [exiobase/tradeflow/bea](https://model.earth/exiobase/tradeflow/bea/)

This [EPA download page](https://catalog.data.gov/dataset/useeio-models-with-import-emission-factors-for-greenhouse-gases-for-2017-2022-from-exiobas) is helpful for clarifying the difference between commodities, BEA service categories and sectors. (3 crosswalk files from that page were added to our [trade-data/concordance](https://github.com/ModelEarth/trade-data/tree/main/concordance) folder.)

The EPA page provides these crosswalks:
(1) EXIOBASE commodities to USEEIO commodities.
(2) BEA service category data to USEEIO sectors.
(3) EXIOBASE Country/Region to BEA Service, Census Goods and TiVA trade regions.

The differences between "CEDA Sector" and the new USEEIO_Detail 2017 sector are small.
"CEDA Sector" and "USEEIO_Detail 2012" both correspond to NAICS 2012.
Whereas USEEIO_Detail 2017 split Aluminum into 2 categories and combined 4 Appliance categories. (See notes below)

**NOTES**

CEDA only provides emission data, and doesn't convey the 2017 NAICS splits and merges done by the US EPA for USEEIO2.

We don't use industry_id for the USEEIO or BEA values since neither refer to their data as Industry. (Though it is NAICS industry categories with minor modifications.)

Hence, for easy table names with the Exiobase data, we use "industry" (5-char) and "commodity" (6-char).

There are too many meanings for "sector" to warrant giving it a table. (Plus sector IDs change every 5 years.)  "beasummary" is more clear.

The crosswalks above correspond to the US EPA reports here:

https://model.earth/exiobase/tradeflow/bea/

You could focus on running our bea scripts above to create .csv files so we can review before SQL tables are created, and also add the crosswalks from the first link above to our trade-data repo.

CEDA still uses NAICS 2012:

[This ceda_to_useeio_commodity concordance](https://pasteur.epa.gov/uploads/10.23719/1531906/documents/ceda_to_useeio_commodity_concordance.csv) provides the 2012, CEDA Sector, and 2017


NAICS USEEIO_Detail 2017 has these differences:

Household Appliance Consolidation:
The 2012 NAICS Codes 335221, 335222, 335224 and 335228 for Household Cooking Appliance, Household Refrigerator and Home Freezer, Household Laundry Equipment and Other Major Household Appliance Manufacturing are all combined in 2017 to the single NAICS Code: 335220, "Major Household Appliance Manufacturing" by the U.S. Environmental Protection Agency.

Aluminum Manufacturing:
The 2012 NAICS Code 331313 was split into 2017 NAICS 331313 and 33131B for reclassification in the aluminum manufacturing sector, where CEDA retains the older detailed classification while USEEIO 2017 uses a modified code (33131B).

## For other Countries

  - Canada → Statistics Canada
  - EU countries → Eurostat (NUTS regional data)
  - China → National Bureau of Statistics
  - Germany, France, etc. → Each has its own regional accounts

The state disaggregation method (allocating national Exiobase flows using BEA employment/output weights) could serve as a template for other countries if their statistical agency data were available.
