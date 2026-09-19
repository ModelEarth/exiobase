# India Pipeline — Open Gaps and Plan

Findings from a review of how `india/main.py`'s output and raw inputs compare to the rest of the
Exiobase pipeline (US `bea/main.py` output, and how raw data is stored elsewhere in this project).
Nothing described here has been implemented yet — this is a plan to work from, not a changelog.

## 1. Output columns don't match US `bea/main.py` naming

The India output files use their own column names, not the naming used by the US pipeline
(`trade.csv`/`interstate.csv`/`state_industry_impacts.csv`).

| India file | Current columns | Closest US equivalent | Gap to close |
|---|---|---|---|
| `state_product_export.csv` | `state, exiobase_product, industry_id, export_value, hs_code, allocation_method` | `trade.csv` (exports): `trade_id, region1, region2, industry1, industry2, amount` | India's row is a single state + single industry slice of one national export total, not a region-pair/industry-pair flow — a 1:1 rename isn't structurally correct. Closer alignment: rename `export_value` → `amount`; add a `trade_id` column linking back to the national `exports/trade.csv` row this state slice was split from (currently no traceability); drop the free-text `exiobase_product` column once downstream consumers only need `industry_id` (already the shared key via `industry.csv`) |
| `state_product_import.csv` | `state, exiobase_product, industry_id, import_value, hs_code, allocation_method` | `trade.csv` (imports) | Same as above, with `import_value` → `amount` |
| `state_sector_output.csv` | `state, sector, output, value_added, allocation_method, industry_id, exiobase_industry_name` | No direct US equivalent — `bea/main.py` doesn't produce a state-level output/GDP table | `sector`/`exiobase_industry_name` are free text kept for readability; `industry_id` is the real shared key. Keep for now, but don't add new free-text columns |
| `india_states.csv` | `State, Output, Employment, Population` | `state_industry_impacts.csv`: `region1, region2, industry_code, direct_jobs, indirect_jobs, induced_jobs, total_output_impact, tax_revenue_impact` | Different purpose (per-state summary vs. per-flow multiplier impact from BEA data) — not a real rename target. More importantly, `Employment` and `Population` are still hardcoded `0` placeholders (see `generate_india_states_summary()`), so this file isn't yet comparable to real per-state figures on the US side |

**To do:** add `trade_id` traceability to the export/import matrices, rename `export_value`/`import_value`
→ `amount`, and populate real `Employment`/`Population` data in `india_states.csv` before treating
these as directly comparable to US `trade.csv`/`interstate.csv` output.

## 2. Raw India source files are not documented (where they came from)

`config.yaml`'s pipeline registry attributes the inputs only by agency, not URL:
`data_sources: India MOSPI GSDP/GSVA, TradeStat HS, India SUT, HS_EXIOBASE_mapping`. That
almost certainly means MOSPI (Ministry of Statistics and Programme Implementation,
mospi.gov.in — National Accounts Statistics) for GSDP/GSVA/SUT, and the DGCI&S TradeStat
portal (tradestat.commerce.gov.in) for HS export/import data — one raw GDP Excel file's internal
layout ("GDP at Constant Prices, 2011-12 series", "First/Second Advance Estimates") matches
MOSPI's standard release format — but no download URL is recorded anywhere in this repo, in
`../../India_data/README.md`, or in a separate supporting repo (none was found; checked for git
submodules and sibling `india`-named repos). The `*_08082025.xlsx`-style filenames record a
download date (`DDMMYYYY`), not a source — there are no `.xml` files, just `.xlsx`/`.xls`/`.csv`.

**To do:** confirm and record the exact source URL for each file category, in this repo and/or a
new data repo (see §3), so a future data refresh doesn't require re-discovering where each file
came from.

## 3. Where should the raw India files live, to be consistent with the rest of the pipeline?

Checked how the other two raw-data sources in this pipeline are handled:

- **Exiobase's own raw MRIO data** (`exiobase_data/IOT_{year}_pxp.zip`, ~230-240 MB each):
  downloaded on demand by `exiobase_download.py`/`trade.py` into `tradeflow/exiobase_data/`,
  which is `.gitignore`d — never committed anywhere. It's disposable/regeneratable from the
  official Exiobase distribution at any time.
- **BEA's raw API responses**: `bea/main_api_client.py` caches every API response as JSON in
  `tradeflow/bea/bea_cache/` (confirmed — currently ~32 cached `.json` files locally). That
  directory is also `.gitignore`d (`# BEA API response cache (regenerated locally)`) — never
  committed. It's disposable/regeneratable by re-calling the BEA API with `BEA_API_KEY`.
- **Trade-data (pipeline output)**: lives in `github.com/ModelEarth/trade-data`, a fully separate
  sibling git repo from `exiobase` (own remote, own git history), referenced only via the relative
  path `../../trade-data/...`. `exiobase`'s own git history never carries pipeline output.

**India's raw files don't fit either existing pattern.** They aren't regeneratable from a live
API call the way Exiobase/BEA's raw data is — someone downloaded ~40 government spreadsheets by
hand — so they can't be a disposable `.gitignore`d cache; they need durable storage. But today
they're committed directly into `exiobase/India_data/` (confirmed via `git ls-files India_data`),
which bloats the *code* repo with large government statistical spreadsheets, unlike every other
raw or output data source in this pipeline, all of which live outside `exiobase`'s own git
history.

**Proposed fix (not yet done):** create a new sibling repo — e.g. `github.com/ModelEarth/trade-india`
— to hold the raw India source files, mirroring how `trade-data` holds pipeline output as its own
repo rather than living inside `exiobase`. `india/main.py` would then read from
`../../trade-india/...` (or similar), the same relative-path pattern already used for
`../../trade-data/...`. This also gives the raw files a natural home for the source-URL
documentation from §2 (a `trade-india/README.md`), and a clean place to add future years'
downloads without growing `exiobase`'s own repo.

**Not done in this pass:** the files are staying in `exiobase/India_data/` for now. This section
is the plan to revisit, not an instruction that's already been carried out.
