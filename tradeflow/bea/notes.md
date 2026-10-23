# Notes: state supply chains and BEA state weights

How the product label's **Top 10 Industries Supplying Production** panel ([profile/item](../../../profile/item/), UN option) uses the Exiobase trade tables in [trade-data](https://github.com/ModelEarth/trade-data) and the BEA state weights that `bea/main.py` uses for the interstate tables. The EPA option uses the USEEIO 2020 state models instead. Started 2026-10-22, updated 2026-10-23.

## What the panel shows

For a product's Exiobase industry (carpet maps to `TEXTI`, Textiles) in a US state, the panel ranks the industries supplying it. Each bar is split three ways: in-state, rest of US, and foreign imports. It can rank by Amount Spent, Greenhouse Gases, Land Use, Water Use, Material Use or Jobs Supported, using factor_id 901–910 in `factor.csv`.

## How the interstate split works

`main_trade_analyzer.py` (`_disaggregate_single_flow`) splits each national US-to-US flow among state pairs. The share for a pair is the origin weight times the destination weight:

- **Origin weight:** the supplying state's share of US GDP in industry1's broad category.
- **Destination weight:** the buying state's share of US GDP in industry2's broad category.

The weights come from BEA Regional table SAGDP2 (GDP by state). The 7 categories are agriculture, mining, utilities, construction, manufacturing, transportation and services. Because a pair's share is just that product, the weights alone describe the whole split. The state-pair rows add no information.

## Why some states were missing (2026-10-23)

`_get_producing_states` and `_get_consuming_states` keep only each category's 8 leading states as producers and 20 as buyers. The shares are then renormalized over those 160 pairs. BEA has data for all 50 states and DC, so the gap comes from the caps:

- **About half of each category's production is moved to its top 8 states.** For 2019 manufacturing, the 8 leading producers hold 50% of GDP but receive all of the production. The 20 leading buyers hold 79% of GDP but receive all of the purchases. Nothing is lost from the national totals; the other states' shares are reassigned to the listed ones.
- **The leading producers are inflated.** California's share of manufacturing production becomes 29.7%, against a real 14.8%.
- **Ten places never appear:** AR, CT, DC, DE, HI, ME, MS, NH, RI and VT.
- **Georgia ranks 11th in manufacturing (2.7%),** so it buys manufactured goods but never produces them.

The caps date from the original placeholder lists of 8 and 20 states (Aug 2025). Commit `0875cf4` (May 2026) switched to BEA rankings but kept the list lengths.

The interstate files still use the caps, since removing them would make each flow fan out to up to 2,601 state pairs instead of 160. Estimated from the 2019 row counts, that's roughly 5–6 GB for `interstate-lg.csv`, and roughly 175 MB for `interstate.csv` (over GitHub's 100 MB file limit). The panel uses the uncapped weights instead.

## Industry categories (fixed 2026-10-23)

`_categorize_industry` used to match keywords in each industry's category and name. About a third of the 200 industries landed in the wrong category:

- **Plurals were missed.** The whole-word match doesn't find "textile" in "Textiles" or "chemical" in "Chemicals", so textiles, chemicals, plastics, ceramics, aluminium and copper fell through to services.
- **"Coal" and "gas" won.** Fuels such as refinery gas and coal-fired and gas-fired electricity went to mining.
- **"Food" and "equipment" overreached.** Hotels, wholesale, retail and computer services went to manufacturing.

`_load_industry_categories` now takes each industry's BEA Sector from `sector_industry.csv` beside `industry.csv`, using the Sector with the largest weight. It maps that Sector to a category with `SECTOR_ALLOCATION_CATEGORY`:

| Sector | Category |
|---|---|
| 11 | agriculture |
| 21 | mining |
| 22 | utilities |
| 23 | construction |
| 31ND, 33DG | manufacturing |
| 48TW | transportation |
| All others | services |

The keyword match remains for industries without a Sector. All 200 industries in 2019 have one. This changes the interstate split on the next `bea/main.py` run. The committed interstate files still use the old categories.

## Pipeline outputs

`bea/main.py` writes three new tables, from [category_state.py](category_state.py), into `trade-data/year/{year}/US/domestic/`:

- **`domestic/category_state.csv`** relates the 7 categories to states. It's written by `_analyze_state_domestic_flows`, before the split. It holds the BEA weights for every state (state_industry_code, weight_type, state, weight, value, source_table, line_code). The weights sum to 1 for each category and weight_type. For 2019 it has 712 rows and 51 states; DC has no mining GDP.
- **The rest is written by `_build_trade_us`** once all trade flows are done, since it reads the imports `trade.csv`:
  - **`domestic/industry_category.csv`:** each Exiobase industry's category.
  - **`domestic/trade-us.csv`:** every industry's national purchases in one table, with columns industry2, industry1, origin, amount and 901–910. Origin is `us` for US producers or `foreign` for imports, summed over countries. For 2019 that's 31,056 rows and 2.0 MB. It's for visualizations that read .csv files; in SQL the same rows are the `trade_us` view.

`trade-us.csv` has no state column; its rows are national. States appear only in `category_state.csv`, as two-letter postal codes in its `state` column: the 50 states and DC. That's 51 places × 7 categories × 2 weight types = 714 rows, less DC's two mining rows (DC has no mining GDP) = 712. The panel computes a state's split when it's shown, from its weights and `trade-us.csv`.

`category_state.py` also holds the BEA allocation line codes and the weight-building code that `bea/main.py` used to contain. To rebuild a year from existing `trade.csv` files:

```bash
cd exiobase/tradeflow
python bea/category_state.py 2019
```

It uses cached BEA responses of any age and fetches only missing ones, with the `BEA_API_KEY` that `bea/main.py` uses. It replaces `trade-data/scripts/build_state_inputs.py`, which first summarized the `-lg` files and then the Sector-level `interstate.csv`.

## API keys

`BEA_API_KEY` and `CENSUS_API_KEY` are read from the env file that `automation/paths.yaml` points at (its `env_file:` line). `env_key.py` holds that lookup for the whole tradeflow folder. `bea_key.py` (used by `main.py`, `bea/main.py` and `bea/category_state.py`) and `census_key.py` (used by `bea/census_api_client.py`) call it instead of each carrying a copy. The lookup order is:

1. a key passed in, such as `--bea-key`
2. a nearby `cloud*` repo's `automation/paths.yaml`
3. webroot's `automation/paths.yaml`
4. webroot/.env
5. the system environment

The env file's location and the key values are never printed.

## Method in the panel

For buying state ST, target industry T and supplying industry i, let d be ST's destination weight for T's category and o be ST's origin weight for i's category:

1. **US purchases.** The national US-made flow i→T puts amount × o × d in-state and amount × (1 − o) × d from other states.
2. **Imports.** National imports of i→T put amount × d in ST, shown as foreign. Each international flow is placed by the same weights as the domestic flow for its industry pair.
3. **Factors.** Factor levels from `trade_factor.csv` split the same way, so the values match the trade flow map. Amounts are millions of euros, shown in US dollars at the year's rate in `concordance/eur_annual_rates.csv`.

Summed over all 51 states, the purchases equal the national total ($28,945M for textiles in 2019).

## SQL

The bea [README](README.md#category_state) documents `category_state` and `industry_category` as tables. It also gives two SQL views:

- **`trade_us`** builds the same rows as `trade-us.csv` from `trade` and `trade_factor`.
- **`trade_state`** applies the weights to give each state's in-state, other-state and import purchases.

Both views were tested in SQLite against the 2019 CSV files.

## The trade_id link

In `interstate-lg.csv`, each row's `trade_id` is the national flow it was split from. In the Sector-level `interstate.csv`, each row totals many flows that share a Sector pair, state pair and `state_industry_code`. The row keeps only the first flow's trade_id (`main.py`, `_aggregate_interstate_to_sector`, `trade_id=('trade_id', 'first')`), so it can't be joined to matching import flows row by row. The weights make that join unnecessary: an import flow and the domestic flow for the same industry pair share the same destination weight.

## Browser load

The panel loads four files the first time it shows a UN ranking, and the browser reuses them for every product and state after that.

| Files | Rows | Raw | Gzip |
|---|---:|---:|---:|
| `domestic/trade-us.csv` | 31,056 | 2.0 MB | 675 KB |
| `domestic/category_state.csv`, `domestic/industry_category.csv`, `industry.csv` | 1,112 | 51 KB | 11 KB |
| **Total** | **32,168** | **2.0 MB** | **686 KB** |

Until 2026-10-23 the panel used `state-inputs/industry/{industry2}.csv` (about 17 KB gzipped per product), which split the same rows by industry. Those files were removed so that one table serves both the label and other visualizations.

Without the preprocessing, the browser would load the full 2019 tables:

| File | Rows | Raw | Gzip |
|---|---:|---:|---:|
| US/imports/trade_factor.csv | 666,683 | 12.5 MB | 3.7 MB |
| US/imports/trade.csv | 163,655 | 5.1 MB | 1.2 MB |
| US/domestic/trade_factor.csv | 95,285 | 1.8 MB | 0.5 MB |
| US/domestic/trade.csv | 19,043 | 0.6 MB | 0.2 MB |
| category_state.csv, sector_industry.csv and industry.csv | 1,135 | 51 KB | 11 KB |
| **Total** | **945,801** | **20.0 MB** | **5.6 MB** |

That's about 946,000 rows parsed in JavaScript. The weights also remove the need for `interstate.csv` (171,136 rows, 10.8 MB), which the Sector-share version needed: 1.1 million rows and 30.8 MB in all. The files download gzipped when the server compresses them; GitHub raw does.

## Would an uncapped -lg file help as a temporary file?

No. Generating the 5–6 GB uncapped `interstate-lg.csv` only to aggregate it would add no information. Every state pair's share is origin weight × destination weight, so any total over states, Sectors or industries can be computed directly from `trade.csv` and `category_state.csv`. For example, `interstate.csv` at Sector level could be written straight from them. The temporary file would only repeat that multiplication 2,601 times per flow and then sum it away.

It would help only if the split stopped being a product of two weights, for example with real state-to-state shipment data such as the Commodity Flow Survey or FAF.

## Years to rerun

| Year | Pipeline run | Status |
|---|---|---|
| 2018–2021 | Sept 2026 | Current pipeline: factor_id 901–910 and BEA interstate tables. |
| **2022** | **Aug 12, 2025** | **Older pipeline.** Uses raw stressor factor_ids (414, 427, …) with levels around 10¹⁶, has no interstate tables, and its `trade_impact.csv` sums to impossible totals (34,208 Gt CO₂ for US imports). Rerun next with `python main.py --interstate US`. |
| 2023 | Sept 2026 | Current pipeline, but only material (909) has values and there are no interstate tables. |
| 2024 | Sept 2026 | Current pipeline, but only material (909) has values. |

A rerun of any year now also writes `category_state.csv`, `trade-us.csv` and `industry_category.csv`, and uses the Sector-based categories.

## Other limits

- **The split is an estimate.** Weights come from GDP by state, not from surveys of shipments. A state's in-state supply is its share of the category's GDP, whether or not its producers sell to its own buyers.
- **Imports follow the buyer's weight.** They are not placed by the ports or buyers that actually received them.
- **Some factors are empty.** In 2019, energy (907), SF₆ (904) and HFCs/PFCs (905) have no rows in `trade_factor.csv`, so the panel's Energy Use is EPA only. The causes are in the README's [Beyond GHGs](README.md#beyond-ghgs-employment-energy-land-material-water) section. Employment (906) is in thousands of people and coarse.

## Example: Georgia carpet, 2019, Amount Spent

The top suppliers are Textiles at $156M (GA $4M, rest of US $131M, foreign $21M) and Chemicals at $155M. Georgia's textile industry buys $784M in all, 2.7% of the national total, matching its share of manufacturing GDP. Before this change, in-state supply was $2K and the totals followed the capped split.

## Next steps for the process (2026-10-23 review)

In rough order of value:

1. **Done (2026-10-23): the interstate map uses current data.** `profile/trade/map/state.html` builds its state-to-state flows in the browser from `trade-us.csv`, `industry_category.csv` and `category_state.csv`, for all 50 states and DC. Its Indicator list has amount spent, greenhouse gases, carbon dioxide, jobs, energy, land, material and water, leaving out any with no values for the year (energy in 2019). In-state purchases appear in the note under the toolbar rather than as arrows.
2. **Rerun 2022, then the other years.** 2022 is on the Aug 2025 pipeline (see Years to rerun). Rerunning 2018–2021 and 2024 would apply the Sector-based categories to their interstate files, which still use the keyword categories.
3. **Write interstate.csv from the weights, without the caps.** The Sector-level table can be computed directly as national flows × origin weight × destination weight, with no `-lg` intermediate. A full 51 × 51 split may be too large for one committed file. Options: drop `state_industry_code` from the grouping, keep only flows above a threshold, or split by state.
4. **Document what interstate.csv's trade_id points to.** It's a valid key to a US→US `trade` row, so it ties each row to the domestic flows. But it's only the first of the trade rows summed into that row: the 2019 file references 1,056 of 19,043 US→US rows, and a row's amount is a median 13 times its referenced trade row's. All of a row's trade rows can be found by joining `trade` (region1 = region2 = 'US') to `sector_industry` (industry to sector1 and sector2) and `industry_category` (industry1 to `state_industry_code`).
5. **Keep BEA responses for past years.** `main_api_client.py`'s 24-hour cache TTL re-fetches unchanged GDP by state on every run. A long TTL for completed years would save calls and keep results stable.
6. **Replace or label placeholders.** `state_industry_impacts.csv` has zero jobs and a flat 12% tax rate. `employment_multipliers.csv` and `state_specializations.csv` hold hard-coded values. Either fill them from BEA or say so in each file's description.
7. **Use the yearly EUR rates everywhere.** `useeio_indicator_alignment.py` still uses a flat 2019 rate; `concordance/eur_annual_rates.csv` has every year.
8. **Done (2026-10-23): distinct names for the large files.** The 721-raw-factor files are now `trade_factor-max.csv` and `interstate_factor-max.csv`, so `-lg` only means Exiobase industry IDs (`interstate-lg.csv`). See the naming rules in the bea README's Output Structure.
9. **Fix the documented Python environment.** The docs say `~/env/bin/python3`, which may not exist. On this machine the pipeline ran with webroot's `env` after installing pandas, numpy, PyYAML, python-dotenv and requests from `requirements.txt`.

