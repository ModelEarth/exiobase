# Trade Data → Industry Database Insert Plan

## Source CSV Locations

All CSVs are fetched from GitHub: `https://raw.githubusercontent.com/ModelEarth/trade-data/refs/heads/main/year/{year}/`

### Root-level (shared, not per country/flow)

| File | Path | Description |
|------|------|-------------|
| `factor.csv` | `year/{year}/factor.csv` | 721 environmental factors |
| `industry.csv` | `year/{year}/industry.csv` | Industry sector definitions |

### Per country + flow-type

| File | Path | Description |
|------|------|-------------|
| `trade.csv` | `year/{year}/{country}/{flow_type}/trade.csv` | Core trade flows |
| `trade_factor.csv` | `year/{year}/{country}/{flow_type}/trade_factor.csv` | Environmental coefficients |

Flow types: `domestic`, `imports`, `exports`
Countries (default set): AU, BR, CA, CN, DE, FR, GB, IN, IT, JP, KR, RU, US
Available years: 2019, 2020, 2021, 2022

### US domestic only (BEA state-to-state)

| Current file | Target table | Path |
|---|---|---|
| `bea_trade_detail.csv` | `interstate` | `year/{year}/US/domestic/bea_trade_detail.csv` |
| `state_trade_flows.csv` | `interstate_factor` | `year/{year}/US/domestic/state_trade_flows.csv` |

**Note:** These will be renamed to `interstate.csv` and `interstate_factor.csv` per [bea/PLAN.md](bea/PLAN.md).

---

## Tables Skipped (redundant — computable via JOIN)

| File | Why skipped |
|---|---|
| `trade_impact.csv` | Aggregation of trade × trade_factor |
| `trade_resource.csv` | Subset of trade_factor (resource rows) |
| `trade_material.csv` | Subset of trade_factor (material rows) |
| `trade_employment.csv` | Subset of trade_factor (employment rows) |

---

## SQL Schema

### `industry` — sector definitions (shared across years and countries)

```sql
industry_id  VARCHAR(10)   PRIMARY KEY
name         TEXT          NOT NULL
category     VARCHAR(100)
```

Source columns: `industry_id, name, category`

---

### `factor` — environmental factor definitions (shared across years)

```sql
factor_id    INTEGER       PRIMARY KEY
unit         VARCHAR(50)
stressor     TEXT
extension    VARCHAR(100)
```

Source columns: `factor_id, unit, stressor, extension`

---

### `trade` — combined domestic + imports + exports for a country/year

```sql
id           BIGSERIAL     PRIMARY KEY
trade_id     INTEGER       NOT NULL
year         SMALLINT      NOT NULL
region1      VARCHAR(10)   NOT NULL
region2      VARCHAR(10)   NOT NULL
industry1    VARCHAR(10)   REFERENCES industry(industry_id)
industry2    VARCHAR(10)   REFERENCES industry(industry_id)
amount       NUMERIC(18,4)
flow_type    VARCHAR(10)   NOT NULL   -- 'domestic', 'imports', 'exports'
country      VARCHAR(10)   NOT NULL
UNIQUE (trade_id, year, country, flow_type)
```

Source columns: `trade_id, year, region1, region2, industry1, industry2, amount`
Added on insert: `flow_type`, `country`

---

### `trade_factor` — environmental coefficients per trade row

```sql
id             BIGSERIAL      PRIMARY KEY
trade_id       INTEGER        NOT NULL
year           SMALLINT       NOT NULL
country        VARCHAR(10)    NOT NULL
flow_type      VARCHAR(10)    NOT NULL
factor_id      INTEGER        NOT NULL   REFERENCES factor(factor_id)
coefficient    NUMERIC(20,10)
level   NUMERIC(20,6)
```

Source columns: `trade_id, factor_id, coefficient, level`
Added on insert: `year`, `country`, `flow_type`

JOIN to `trade`: `trade_factor.trade_id = trade.trade_id AND trade_factor.year = trade.year AND trade_factor.country = trade.country AND trade_factor.flow_type = trade.flow_type`

---

### `interstate` — US BEA state-to-state trade (domestic only)

```sql
id                  BIGSERIAL      PRIMARY KEY
trade_id            INTEGER        NOT NULL
year                SMALLINT       NOT NULL
region1             VARCHAR(10)    NOT NULL   -- e.g. US-AK
region2             VARCHAR(10)    NOT NULL   -- e.g. US-GA
industry1           VARCHAR(10)    REFERENCES industry(industry_id)
industry2           VARCHAR(10)    REFERENCES industry(industry_id)
amount              NUMERIC(18,4)
commodity_code      VARCHAR(30)
industry_code       VARCHAR(30)
economic_multiplier NUMERIC(10,6)
```

Source columns: `trade_id, year, region1, region2, industry1, industry2, amount, bea_commodity_code (→ commodity_code), bea_industry_code (→ industry_code), economic_multiplier`

---

### `interstate_factor` — state-level factor flows

```sql
id                  BIGSERIAL      PRIMARY KEY
interstate_id       VARCHAR(80)    NOT NULL
factor_id           INTEGER        REFERENCES factor(factor_id)
level               NUMERIC(20,6)
```

Source columns: `trade_id, factor_id, coefficient, state_industry_code, level, flow_type, employment_impact`
`interstate_id` is computed: `{year}-US-{origin_state}-US-{destination_state}-{state_industry_code}`
`factor_id` and `coefficient` are populated from the Exiobase S matrix (satellite intensity); rows
without satellite data (Exiobase zip unavailable) omit these columns and fall back to one aggregate
row per state-pair.

---

## Indexes (PostgreSQL speed optimization)

```sql
-- trade: composite lookup + range scans
CREATE INDEX idx_trade_lookup       ON trade (trade_id, year, country, flow_type);
CREATE INDEX idx_trade_year_country ON trade (year, country);
CREATE INDEX idx_trade_region1      ON trade (region1);
CREATE INDEX idx_trade_region2      ON trade (region2);
CREATE INDEX idx_trade_flow_type    ON trade (flow_type);

-- trade_factor: FK joins and analytical queries
CREATE INDEX idx_tf_lookup          ON trade_factor (trade_id, year, country, flow_type);
CREATE INDEX idx_tf_factor_id       ON trade_factor (factor_id);
CREATE INDEX idx_tf_year_country    ON trade_factor (year, country);

-- interstate: state-level filtering
CREATE INDEX idx_istate_trade_id    ON interstate (trade_id);
CREATE INDEX idx_istate_year        ON interstate (year);
CREATE INDEX idx_istate_region1     ON interstate (region1);
CREATE INDEX idx_istate_region2     ON interstate (region2);

-- interstate_factor: join and lookup
CREATE INDEX idx_isf_interstate_id  ON interstate_factor (interstate_id);
CREATE INDEX idx_isf_factor_id      ON interstate_factor (factor_id);
```

---

## Rust API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/db/init-industry-tables` | POST | CREATE TABLE IF NOT EXISTS all tables + indexes + FKs |
| `/api/db/insert-trade-data` | POST | Fetch CSVs from GitHub → upsert into Industry DB |
| `/api/db/industry-schema` | GET | Return table schema + row counts for ERD diagram |

### Insert request body

```json
{ "year": "2019", "country": "US" }
```

### Insert sequence (order matters for FK constraints)

1. `factor.csv` → `factor` table
2. `industry.csv` → `industry` table
3. For each flow_type (domestic, imports, exports):
   - `trade.csv` → `trade` table (with `flow_type`, `country` added)
   - `trade_factor.csv` → `trade_factor` table (with `year`, `country`, `flow_type` added)
4. US only — domestic:
   - `bea_trade_detail.csv` → `interstate` table
   - `state_trade_flows.csv` → `interstate_factor` table

---

## Schema Diagram

A real-time ERD diagram is rendered in the browser via `/api/db/industry-schema`, which queries `information_schema.columns` for actual DB state and returns row counts per table from `pg_stat_user_tables`.

```
[factor]          [industry]
    ↑              ↑       ↑
    |          (industry1) (industry2)
[trade_factor] ← [trade]
                    |
              (US domestic only)
                    ↓
              [interstate]  ──→  [interstate_factor]
                    ↑
              (industry1/2 → industry)
```

---

## Open Questions (from bea/PLAN.md)

- Should `interstate.csv` replace `trade.csv` for US domestic records in SQL, or always exist as a separate parallel table?
- Is `state_industry_code` in `interstate_factor` the same as `industry_id` from `industry.csv`?
- Should `trade_price_indices.csv` be imported once it has data?
