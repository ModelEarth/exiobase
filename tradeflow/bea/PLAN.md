# BEA Integration Plan

## TradeFlow

### Interstate Pipeline Integration

- Integrate BEA interstate generation into the normal TradeFlow pipeline, accounting for required inputs and API access.
- Validate and publish `interstate.csv` and `interstate_factor.csv` to `ModelEarth/trade-data`.
- Align Rust downloads and column mapping with the approved CSV format.
- Verify successful Azure imports and preserve compatibility with existing datasets where needed.

### Schema and Identifier Alignment

Align Python CSVs, Rust DDL/importer, Azure PostgreSQL, and Rust/JS schema fallbacks.

- Confirm the authoritative interstate format before changing the schema.
- Persist `interstate_id` in Rust/Azure if the current BEA format is adopted.
- Validate replacement keys before removing generic `BIGSERIAL id` columns.
- Remove obsolete generic `BIGSERIAL id` definitions from Rust for `trade`, `trade_factor`, `interstate`, and `interstate_factor`.
- Align Rust `trade_factor` parsing with `trade_id,factor_id,level`.
- Review schema changes with Gary/Loren before implementation.

### Primary Keys

| Table | Current / Candidate Primary Key |
| --- | --- |
| `industry` | `industry_id` — existing |
| `factor` | `factor_id` — existing |
| `trade` | `(trade_id, year, country, flow_type)` — validate duplicates/nulls |
| `trade_factor` | Not yet determined — historical records and nullable `coefficient` require further profiling |
| `interstate` | `interstate_id` or validated composite key — validate uniqueness |
| `interstate_factor` | `(interstate_id, factor_id)` — validate after parent key is finalized |

For `trade_factor`, the primary key remains unresolved. Historical Azure data contains differences across `level` and `coefficient`, while `coefficient` is also `NULL` for some records. Profile these combinations before selecting or enforcing a key.

### Conflict Handling

Use validated primary/unique keys to make repeated imports idempotent.

- Keep `ON CONFLICT ... DO NOTHING` for `industry`, `factor`, and `trade`.
- Determine the `trade_factor` key before defining its conflict behavior.
- Add appropriate conflict handling to `interstate` and `interstate_factor` after their keys/constraints are validated.
- Ensure every `ON CONFLICT` target has a corresponding PostgreSQL primary or unique constraint.

### Data Pipeline Automation

Automate TradeFlow data generation, validation, publication, and Azure PostgreSQL ingestion.

- Validate datasets before importing them.
- Verify imported data against source CSVs.
- Run profiling and change detection after successful imports.
- Record failures and support safe retries.

### Public Read-Only API

Work together to expose selected TradeFlow data from Azure PostgreSQL through a public read-only API.

- Provide read-only endpoints for approved data.
- Limit requests per visitor IP.
- Support data access for the TradeFlow UI and Abundance Engine.
- Keep database credentials and write operations private.

### Dataset Profiling

Generate a profile whenever a dataset is created or refreshed.

- Capture schema, row counts, nulls, duplicates, distinct values, numeric ranges, and candidate-key uniqueness.
- Check relationships between parent and factor tables for missing/orphaned records.
- Store profiles by dataset/year/run so they can be compared over time.
- Use profiling results to validate database constraints and determine forecast readiness.

### Change Detection

Compare each new profile with the previous available profile.

- Detect schema changes, significant row-count changes, new nulls/duplicates, key violations, distribution shifts, and broken relationships.
- Distinguish expected data refreshes from potential data-quality or pipeline regressions.
- Record detected changes with the affected field/metric and previous/current values.

### Forecasting

Evaluate forecast readiness before training models.

- Identify the target, time field, grouping dimensions, historical coverage, frequency, and forecast horizon.
- Require sufficient multi-year observations for chronological training and backtesting.
- Compare a baseline with suitable candidate models using metrics such as MAE/RMSE/MAPE where appropriate.
- Save predictions with model/version, training period, horizon, evaluation metrics, and confidence intervals where supported.
- Compare stored forecasts with future actual values as new data arrives.

The current pipeline processes a configured year per run, so building and validating sufficient multi-year history is a prerequisite for forecasting.

### Migration Safety

Before modifying the live Azure schema:

1. Confirm the intended interstate CSV format and validate representative files.
2. Profile replacement keys for uniqueness, nulls, duplicates, and orphaned records.
3. Add and validate replacement identifiers and constraints.
4. Update Rust import logic and foreign-key relationships.
5. Verify successful imports and data integrity.
6. Remove obsolete surrogate `id` columns only after replacement keys and dependencies work.

Do not delete or rewrite historical data solely to satisfy new constraints without investigating the cause. 


## Schema / Rename Tasks

- [x] **Rename `bea_trade_detail.csv` → `interstate.csv`** in Python generation code and validation report.
  - Updated in `main.py` (`_create_interstate_csvfiles`, `_generate_validation_report`).
- [x] **Remove `bea_` prefix from column names** in the Python CSV generation code (not by post-processing).
  - `bea_commodity_code` → `commodity_code`, `bea_industry_code` → `industry_code` (in `main.py` `_merge_bea_*` helpers).
  - `economic_multiplier` has no prefix to strip but needs its final meaning documented (see Open Questions).
- [x] **Rename `state_trade_flows.csv` → `interstate_factor.csv`**.
  - Updated in `main.py` (`_analyze_state_domestic_flows`, `_generate_validation_report`).
- [x] **Add `interstate_id` column to `interstate_factor.csv`** and **remove `origin_state` / `destination_state`**.
  - `interstate_id` format: `{year}-US-{origin}-US-{dest}-{industry}` (generated in `main_trade_analyzer.py` `_disaggregate_single_flow`).
  - Internal `_origin_state`/`_destination_state` columns are retained in the dataframe for use by `calculate_state_industry_impacts`, then dropped before the CSV write in `main.py`.
- [x] **Rename `state_code` → `region` in `state_industry_impacts.csv`** and prepend country prefix (`US-AK`, etc.).
  - Updated in `main_trade_analyzer.py` (`calculate_state_industry_impacts`).
- [x] **Standardize region format to `[country]-[state]` (e.g. `US-GA`)** — applied to `interstate_id` and `region` column via `main_trade_analyzer.py`; `interstate.csv` region columns (region1/region2) come from base Exiobase trade data and are unchanged pending resolution of open question on interstate vs trade table relationship.
- [ ] **Stop generating `bea_industry_mapping.csv`** — replaced by the shared `year/[year]/industry.csv`.
  - `industry.csv` is generated by other tradeflow scripts and already contains the exiobase sector names.
  - Candidate location: `main.py` output generation.
  - Done when: `main.py` no longer writes `bea_industry_mapping.csv` and any doc references are removed.

---

## Investigation Tasks

- [x] **Add `factor_id` to `interstate_factor.csv`** — to relate state-level flows to the `factor` table.

  **Current state (confirmed from live data):**
  - `state_trade_flows.csv` has 817,684 rows across 21,518 unique `trade_id` values and only 38 unique state pairs.
  - It produces a **single aggregate `level`** per (trade_id, origin_state, destination_state) — the geographic disaggregation of the domestic trade `amount`, not a per-factor environmental impact.
  - It has no `factor_id` column. `employment_impact` is a derived BEA scalar, not mapped to a specific Exiobase factor.

  **Limitations preventing a direct add:**

  1. **Source data has no factor dimension.** `level` is the total disaggregated flow (equivalent to `amount` in `trade`). The factor dimension is never applied during state disaggregation in `main_trade_analyzer.py`. To add `factor_id`, the Python generator must loop over factors from `trade_factor.csv` during `_disaggregate_single_flow`, multiplying each state-pair flow by each factor coefficient.

  2. **Scale impact.** The current 817,684 rows × 120 factors (trade_factor.csv) = ~98 million rows. If all 721 factors (trade_factor_lg.csv) are used, ~590 million rows. This is a significant storage and query performance consideration.

  3. **Employment ambiguity.** `employment_impact` uses BEA employment multipliers (from the BEA API), not Exiobase factor coefficients. It does not map directly to any Exiobase `factor_id` (the closest are IDs 419–428: employment people/hours by skill and gender). Mapping it would require choosing which employment factor(s) to link it to.

  4. **`state_industry_code` is currently only `'services'`** — a single placeholder category. Until real industry-level disaggregation is implemented, per-factor rows would all have the same industry context.

  **Path forward (requires Python changes in `main_trade_analyzer.py`):**
  - In `_disaggregate_single_flow`, after computing the state-pair flow fraction, join with `trade_factor.csv` on `trade_id` and emit one row per `factor_id` with `level * coefficient` as the impact.
  - Add `factor_id` and (optionally) `coefficient` columns to the output.
  - Consider a `factor_limit` parameter (default 120) to match the `trade_factor.csv` selection and keep row counts manageable.
  - The SQL `interstate_factor` table already has a `bigserial` PK and is ready to receive the column once the Python output includes it — no schema change needed beyond adding the FK: `ALTER TABLE interstate_factor ADD COLUMN factor_id INTEGER REFERENCES factor(factor_id)`.

  Done when: `main_trade_analyzer.py` emits `factor_id` in `interstate_factor.csv` output, `README.md` documents the column, and the SQL insert in `team/src/main.rs` (`insert_interstate_factor_rows`) reads the column.

- [ ] **Clarify how `interstate.csv` relates to the international `trade` table**.
  - Both have the same structure; in some SQL installs state data will be merged into `trade`.
  - Determine: does BEA domestic processing read from or write into the international `trade.csv`, or is `interstate.csv` always a separate parallel table?
  - Done when: `README.md` clearly states the relationship and code reflects it.

- [ ] **Investigate why `trade_price_indices.csv` is empty**.
  - Candidate location: `main.py` (`_create_trade_price_indices`).
  - Options: populate from BEA Import/Export Price Index API endpoint, or explicitly mark deferred with rationale.
  - Done when: file has populated rows, or `README.md` documents why it remains intentionally empty.

- [ ] **Resolve status of `trade_factor_bea.csv`**.
  - Planned schema: `trade_id, factor_id, coefficient_value, bea_multiplier, regional_adjustment, data_source`.
  - File does not currently appear to be generated.
  - Options: implement generation in `main.py`, or remove from docs if `trade_factor.csv` is sufficient for all flows.
  - Done when: file is generated and documented, or removed from `README.md` with rationale.

---

## Follow-up Tasks (after schema changes land)

- [ ] **Update BEA sample dashboard** to reflect renamed files and columns.
  - Target: `../../trade-data/bea-dashboard/`
  - Done when: dashboard sources reference final filenames and column names.

- [ ] **Add upcoming reports** (currently listed as "upcoming" in `README.md`):
  - State-to-state domestic trade flows
  - State export competitiveness analysis
  - Import dependency by state

---

## Open Questions

> Once resolved, document the answer in `README.md` and check the box here.

- [ ] For the renamed BEA columns, what are the preferred final names: `commodity_code` / `industry_code`, or domain-specific alternatives?
- [x] What does `economic_multiplier` represent, and is that the intended final column name?
- [ ] Should `trade_price_indices.csv` be generated for all three tradeflows (`domestic`, `imports`, `exports`) or only selected ones?
- [ ] Is `trade_factor_bea.csv` a required SQL deliverable, or should `trade_factor.csv` remain the single factor table?
- [ ] In `interstate_factor.csv`, is `state_industry_code` the same as `industry_id` from `industry.csv`, or a separate BEA-specific code?

---

## Status

- [ ] Open questions resolved and documented in `README.md`
- [ ] Schema / rename tasks complete
- [ ] Investigation tasks resolved
- [ ] Schema changes validated against `trade-data` outputs
- [ ] Dashboard/report updated
- [ ] `README.md` TODOs removed or updated to reflect completed work
