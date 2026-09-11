# India State-Level Trade Flow Allocation

This script allocates national Indian trade flows and economic data to state/UT level, creating EXIOBASE-compatible matrices for MRIO integration.

## Overview

The script processes the following India datasets:

1. **State Domestic Product (GSDP)** - Total GSDP per state/UT (2011-12 series)
2. **GSVA/NSVA by Economic Activities** - Sectoral value-added per state
3. **Supply Use Tables (SUT)** - National input-output tables
4. **TradeStat-Eidb Export/Import Data** - National exports/imports by HS/commodity codes
5. **GSDP_Current_2011-12_State_wise** - State-level GSDP for scaling

## Output Matrices

The script generates the following EXIOBASE-compatible matrices:

### 1. State × Sector Output Matrix (`state_sector_output.csv`)
- Allocates state GSDP across sectors using GSVA data
- Columns: `state`, `sector`, `output`, `value_added`, `allocation_method`
- Ensures state totals match GSDP totals

### 2. State × Product Export Matrix (`state_product_export.csv`)
- Allocates national exports to states using sector outputs as proxies
- Maps HS codes → EXIOBASE products
- Columns: `state`, `exiobase_product`, `export_value`, `hs_code`, `allocation_method`
- Normalized so state totals match national export totals

### 3. State × Product Import Matrix (`state_product_import.csv`)
- Allocates national imports to states using GSDP/sector outputs
- Maps HS codes → EXIOBASE products
- Columns: `state`, `exiobase_product`, `import_value`, `hs_code`, `allocation_method`
- Normalized so state totals match national import totals

### 4. State-Level A-Matrices (Calculated but not saved)
- Technical coefficient matrices for each state are calculated during processing
- Scaled from national SUT using state sectoral outputs
- **Note**: Individual state A-matrix files are not saved to disk (only calculated in memory)

## Data File Requirements

Place your India data files in the `India_data` folder (or specify with `--data-dir`):

### Required Files:

1. **GSDP Data** (one of):
   - `GSDP_Current_2011-12_State_wise.csv`
   - `GSDP_State_wise.csv`
   - `GSDP.csv`
   - `state_gsdp.csv`

   Expected columns: State name, GSDP value (for target year or 2011-12 series)

2. **GSVA/NSVA Data** (one of):
   - `GSVA_by_economic_activities.csv`
   - `NSVA_by_economic_activities.csv`
   - `GSVA.csv`
   - `NSVA.csv`
   - `state_sector_value_added.csv`

   Expected columns: State name, Sector/Activity name, Value added

3. **SUT Data** (one of):
   - `SUT.csv`
   - `Supply_Use_Tables.csv`
   - `Input_Output_Tables.csv`
   - `IOT.csv`
   - `national_sut.csv`

   Expected columns: From sector, To sector, Transaction value

### Optional Files:

4. **Export Data** (one of):
   - `TradeStat_Export.csv` or `TradeStat-Eidb-Export-Commodity-wise.xlsx`
   - `Export_Commodity_wise.csv`
   - `Exports.csv`
   - `export_data.csv`

   Expected columns: HS code (2-digit or 6-digit), Export value
   - HS codes are automatically normalized to 2-digit format for matching

5. **Import Data** (one of):
   - `TradeStat_Import.csv` or `TradeStat-Eidb-Import-Commodity-wise.xlsx`
   - `Import_Commodity_wise.csv`
   - `Imports.csv`
   - `import_data.csv`

   Expected columns: HS code (2-digit or 6-digit), Import value
   - HS codes are automatically normalized to 2-digit format for matching

6. **HS-EXIOBASE Mapping** (optional):
   - `HS_EXIOBASE_mapping.csv`

   If not provided, a basic mapping will be created automatically.
   Expected columns: `hs_code` (2-digit), `hs_code_2digit`, `exiobase_sector`, `exiobase_product`, `confidence`

   **Note**: The script supports 2-digit HS codes. If your data has 6-digit codes, they will be automatically converted to 2-digit for matching.

## Usage

### Basic Usage

```bash
# From tradeflow directory
python india/main.py
```

This will:
- Look for data in `../India_data` folder
- Use year from `config.yaml`
- Save outputs to `../../trade-data/year/{year}/IN/domestic/` (per `config.yaml` `FOLDERS.domestic`)

### Advanced Usage

```bash
# Specify custom data directory
python india/main.py --data-dir /path/to/India_data

# Specify year
python india/main.py --year 2019

# Specify output directory
python india/main.py --output-dir /path/to/output

# Combine options
python india/main.py --data-dir ../India_data --year 2019 --output-dir ./output
```

## Processing Steps

1. **Load Data**: Reads all India data files from specified directory
2. **Allocate State Sector Outputs**: Uses GSVA to allocate GSDP across sectors
3. **Allocate Exports**: Maps HS codes to EXIOBASE products and allocates to states
4. **Allocate Imports**: Similar to exports, allocates imports to states
5. **Scale SUT**: Creates state-level A-matrices from national SUT
6. **Normalize**: Ensures all allocations match national totals
7. **Save Outputs**: Writes all matrices as CSV files

## HS Code to EXIOBASE Mapping

The script includes a basic HS → EXIOBASE mapping using **2-digit HS chapter codes**. For better accuracy, you should:

1. Create `HS_EXIOBASE_mapping.csv` with proper concordance
2. Use official EXIOBASE product classifications
3. Map 2-digit HS codes to EXIOBASE product codes

**HS Code Format**:
- The script supports both 2-digit and 6-digit HS codes in your data
- All codes are automatically normalized to 2-digit format for matching
- 2-digit codes (e.g., "01", "02") are used directly
- 6-digit codes (e.g., "010101") are truncated to first 2 digits (e.g., "01")
- Single-digit codes are padded (e.g., "1" → "01")

The basic mapping covers:
- Agriculture (HS 01-15) → Agricultural sectors
- Textiles (HS 50-63) → Textile sectors
- Chemicals (HS 28-38) → Chemical sectors
- Metals (HS 72-83) → Metal sectors
- Machinery (HS 84-85) → Machinery sectors
- Vehicles (HS 86-89) → Transportation sectors

## Validation

The script includes validation checks:

- **State totals vs GSDP**: Verifies allocated outputs match GSDP
- **Export/Import normalization**: Ensures state totals match national totals
- **A-matrix row sums**: Validates technical coefficients are reasonable

## Output Structure

```
year/{year}/IN/state_allocation/
├── state_sector_output.csv          # State × Sector output matrix (all states)
├── state_product_export.csv         # State × Product export matrix (all states)
├── state_product_import.csv         # State × Product import matrix (all states)
└── allocation_report.md             # Summary report
```

**Note**: State A-matrices are calculated during processing but are not saved as individual CSV files. All output matrices contain data for all states in a single file.

## Integration with EXIOBASE

The output matrices are designed to be EXIOBASE-compatible:

- **Sector codes**: Should match EXIOBASE sector classifications
- **Product codes**: Should match EXIOBASE product classifications
- **A-matrices**: Technical coefficients compatible with EXIOBASE structure
- **Normalization**: All allocations normalized to national totals

## Notes

- **Sector Mapping**: The script uses the existing `industry.csv` file for sector mapping. Ensure this file exists or create it using `create_sector_mapping.py`
- **Missing Data**: If GSVA data is missing for a state, the script uses national proportions
- **HS Mapping**: A basic HS-EXIOBASE mapping is created if not provided. The mapping uses 2-digit HS chapter codes. For production use, provide a comprehensive mapping file
- **SUT Scaling**: State A-matrices are scaled from national SUT using state output ratios. If sector names don't match between SUT and state data, the script uses fuzzy matching or falls back to the national A-matrix
- **File Format Support**: The script supports both CSV and Excel (.xlsx, .xls) files with flexible header detection
- **State Names**: State names with special characters (e.g., "Jammu & Kashmir") are automatically sanitized for filenames
- **Output Files**: Only aggregated matrices are saved (all states in one file). Individual state files are not created

## Troubleshooting

### File Not Found Errors
- Check that data files are in the correct directory
- Verify file names match expected patterns
- Check file extensions (.csv)

### Column Name Issues
- The script tries to auto-detect column names
- If issues occur, check the column standardization functions
- You may need to rename columns in your data files

### Mapping Issues
- If HS-EXIOBASE mapping fails, check HS code format (2-digit or 6-digit are both supported)
- The script automatically normalizes HS codes to 2-digit format
- Check console output for mapping statistics (how many codes mapped vs unmapped)
- Verify EXIOBASE product names match industry.csv
- Review the basic mapping creation logic
- If all products show as "Unmapped", check that your mapping file has `hs_code_2digit` column or that `hs_code` contains 2-digit values

### Validation Warnings
- Large differences in validation checks may indicate data quality issues
- Review allocation methods used (shown in `allocation_method` column)
- Check for missing or zero values in source data
- If A-matrices are empty, check sector name matching between SUT and state sector data
- Console output shows sector matching analysis - review this if issues occur

### Empty A-Matrices
- If state A-matrices are empty, the script will show sector matching analysis
- Check if SUT sector names match state sector names from GSVA data
- The script attempts fuzzy matching but may fall back to national A-matrix if no matches found
- Review console output for sector matching details

## Example Workflow

```bash
# 1. Prepare data files in India_data folder
mkdir India_data
# Copy your CSV files to India_data/

# 2. Run allocation
cd tradeflow
python india/main.py --data-dir ../India_data --year 2019

# 3. Check outputs
ls -la ../../trade-data/year/2019/IN/domestic/

# 4. Review report
cat ../../trade-data/year/2019/IN/domestic/allocation_report.md
```

## Future Enhancements

Potential improvements:
- More sophisticated HS-EXIOBASE mapping using official concordances
- Consumption-based import allocation (using final demand data)
- State-to-state trade flow estimation
- Integration with existing trade.py pipeline
- Support for multiple years
- Enhanced validation and error reporting

