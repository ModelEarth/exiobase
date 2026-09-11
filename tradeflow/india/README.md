# India State-Level Trade Flow Allocation

Allocates national India trade flow and economic data down to the state/UT level, producing matrices that integrate with the Exiobase MRIO pipeline.

## main.py

### What it processes

Reads national-level Indian economic data and disaggregates it across 36 states and union territories using sector output shares derived from GSDP and GSVA. Indian activity labels are matched via `india_us_exiobase_crosswalk.csv` to **Exiobase `industry_id`** values (same 5-character codes used in US `trade-data` outputs, enabling India–US comparisons on a common taxonomy). The five allocation steps are:

1. **State × Sector output matrix** — GSDP scaled by GSVA sector shares per state; columns include `industry_id` and `exiobase_industry_name`
2. **State × Product export matrix** — national TradeStat exports allocated using state output sliced by `industry_id` where HS→Exiobase mapping resolves; HS codes mapped to Exiobase products
3. **State × Product import matrix** — national TradeStat imports allocated to states via GSDP proportions; includes `industry_id` per product
4. **State A-matrices** — national Supply Use Table (SUT) technical coefficients scaled per state; used in-memory only, not written to disk
5. **india_states.csv** — state-level summary of total output, employment (placeholder), and population (placeholder)

### Uses config.yaml

Yes — reads `../config.yaml` (one level up, in `exiobase/tradeflow/`) via `config_loader.py` for the processing year (`YEAR`), `FOLDERS` (default output under `trade-data/year/{YEAR}/IN/domestic/`), and reference `industry.csv`. The pipeline registry includes an `india` node alongside `us_bea`. The year can be overridden with `--year`.

### Input data

All source files are expected in `exiobase/India_data/` (two levels up from this folder). The script scans that directory on startup and categorizes files automatically:

| Category | Matched by filename | Format |
|---|---|---|
| GSDP | contains `gsdp`, `sdp`, or `gdp` + `state` | CSV or Excel |
| GSVA / NSVA | contains `gsva`, `nsva`, or `value_added` | CSV or Excel |
| SUT / IOT | contains `sut`, `iot`, `input_output`, `supply_use`, or `revision` | CSV or Excel |
| Exports | contains `export` + `tradestat` | CSV or Excel |
| Imports | contains `import` + `tradestat` | CSV or Excel |
| State files | contains a state name (e.g. `gujarat`, `kerala`) | Excel |
| HS mapping | `HS_EXIOBASE_mapping.csv` (auto-generated if absent) | CSV |

State files (individual Excel files per state) are used as a fallback when consolidated GSDP or GSVA files are not present.

### Output

Sent to `../../trade-data/year/{YEAR}/IN/domestic/` by default (from `config.yaml` `FOLDERS.domestic` relative to `tradeflow/`). Override with `--output-dir`.

| File | Description |
|---|---|
| `india_us_exiobase_crosswalk.csv` | Keyword-level India GSVA→Exiobase `industry_id` bridge (copy of `india/india_us_exiobase_crosswalk.csv`) |
| `state_sector_output.csv` | State × sector output matrix; includes `industry_id`, `exiobase_industry_name` |
| `state_product_export.csv` | State × product export matrix; includes `industry_id` |
| `state_product_import.csv` | State × product import matrix; includes `industry_id` |
| `india_states.csv` | State summary; columns: `State, Output, Employment, Population` |
| `allocation_report.md` | Processing summary with row counts and totals per matrix |
| `HS_EXIOBASE_mapping.csv` | Saved to `India_data/` on first run if not already present |

### Run

```bash
# Run from exiobase/tradeflow/
python india/main.py

# Specify a different data directory
python india/main.py --data-dir ../India_data

# Specify a year (overrides config.yaml)
python india/main.py --year 2019

# Specify a custom output directory
python india/main.py --output-dir ../../trade-data/year/2019/IN/domestic
```

### Dependencies

```bash
pip install pandas numpy openpyxl
```

`openpyxl` is required for reading Excel (`.xlsx`/`.xls`) source files. The script will warn and continue with limited functionality if it is not installed.
