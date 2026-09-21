# Comprehensive trade push: every region, direct to Azure, no per-country CSVs

Plan for a new `comprehensive` processing mode that extracts trade flows for **every** Exiobase
region in one pass (not a curated 14-country list) and writes them straight into the shared
`industrydb` Azure Postgres database, without generating the large per-country/per-flow-type
`.csv` files `trade.py` writes today. Initial target year: **2018**.

This is additive: `default`/`all` keep working exactly as they do now (curated country list,
local CSVs, `POST /api/db/insert-trade-data`, per-country `trade_id` blocks). `comprehensive` is a
third, independent code path that happens to share almost all of its extraction and database
logic with the existing one — see "Reuse checklist" at the end.

## Why today's approach doesn't scale to "every region"

`trade.py` filters Exiobase's global inter-industry matrix (`Z`) down to one country's rows before
writing `trade.csv`, then that file is committed to the `trade-data` repo, fetched back over
`raw.githubusercontent.com` by `team`'s Rust backend (`fetch_github_csv`), and inserted with a
per-country `trade_id` block (`country_block_index`, see `PLAN-merge.md` in `team`). That's the
right shape for a stable 14-country list where each file is a few hundred KB and a human wants to
browse/download country folders on the website. It's the wrong shape once every region is in
scope:

- **File size / git.** 49 regions × 3 flow types worth of `trade.csv`/`trade_factor.csv` would add
  many GB to a repo (`trade-data`) that's meant to stay downloadable from the website.
- **The GitHub round-trip is unnecessary.** Committing a file just so a server can immediately
  fetch it back over HTTP only makes sense when the file is also a first-class downloadable
  product. Comprehensive rows aren't (see below); pushing them straight to Postgres skips two
  network hops and disk writes.
- **Per-country `trade_id` blocks aren't needed.** They exist so that adding country #15 to an
  *already-loaded* database can't collide with country #1's ids. Comprehensive builds the entire
  year in one shot, so a plain 1-based sequential id has no gaps and can't collide with itself —
  see "Trade ID scheme" below for why it also can't collide with anything already in `industrydb`.

## `config.yaml`: add `comprehensive` as a third `COUNTRY.list` option

Today's `NOTES` section documents two `COUNTRY.list` values that `resolve_country_list()` in
`main.py` special-cases: `default` (14 countries) and `all` (whatever country folders already
exist on disk, i.e. the short curated list currently in `trade-data/year/{year}/`). Add a third:

```yaml
NOTES:
  1: COUNTRY.list "default" = run only incomplete ones within AU, BR, CA,
    CN, DE, FR, GB, IN, IT, JP, KR, RU, WM, US
  2: COUNTRY.list "all" = run all (could take hours)
  3: COUNTRY.list "comprehensive" = push every Exiobase region (all 49 —
    see PLAN-comprehensive.md) directly to Azure industrydb for one year.
    No local per-country .csv files, no per-country trade_id blocks. Set
    TRADEFLOW to anything; comprehensive ignores it (imports/exports/
    domestic all come out of one extraction — see PLAN-comprehensive.md).
```

`main.py` needs one new early branch, not a change to `resolve_country_list()` itself (that
function's job — turning a country list into... a country list — doesn't fit "there is no country
list, run one job for the whole year"). In `process_tradeflow`'s caller (the per-year loop around
`main.py:408`), check `country_list.lower() == 'comprehensive'` *before* calling
`resolve_country_list`/`filter_incomplete_countries`/`process_tradeflow`, and dispatch to a new
`run_comprehensive_processing(year)` instead. That function runs a new script
(`trade_comprehensive.py`, see below) once per year via the same `subprocess.run(...,
env={**os.environ, 'EXIOBASE_YEAR': str(year)})` pattern `run_country_processing` already uses —
no `EXIOBASE_COUNTRY`/`EXIOBASE_TRADEFLOW` needed, since comprehensive has neither. `--interstate
US` continues to work unchanged afterward (see "US/domestic continuity" below for why it can).

## Confirmed: Exiobase's regions have a fixed, discoverable order

The plan text asked to investigate whether regions "reside in the Exiobase file in an indexed
order" — yes. Read directly from `unit.txt` inside `exiobase_data/IOT_2021_pxp.zip` (first-seen
order of the `region` column, which matches `Z.txt`'s column order):

```
1  AT   11 FR   21 PL   31 CA   41 TR
2  BE   12 GR   22 PT   32 KR   42 TW
3  BG   13 HR   23 RO   33 BR   43 NO
4  CY   14 HU   24 SE   34 IN   44 ID
5  CZ   15 IE   25 SI   35 MX   45 ZA
6  DE   16 IT   26 SK   36 RU   46 WA
7  DK   17 LT   27 GB   37 AU   47 WL
8  EE   18 LU   28 US   38 CH   48 WE
9  ES   19 LV   29 JP   39 TR*  49 WF
10 FI   20 MT   30 CN   40 TW*         (44 country rows + 5 RoW: WA/WL/WE/WF/WM)
```

(exact list: `AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK GB
US JP CN CA KR BR IN MX RU AU CH TR TW NO ID ZA WA WL WE WF WM` — 49 total, EU-27 first, then
non-EU OECD-ish countries, then the 5 Rest-of-World aggregates last). This is stable across at
least the 2019–2023 files already downloaded (spot-checked 2021; pymrio's `parse_exiobase3` always
yields this same column order per Exiobase's own file format, not something the loader controls).

**This order is not used for `trade_id` assignment** (see next section for why a derived formula
is the wrong tool here) but it is used to pre-seed the `region` table (below), and it's useful
context for anyone reading a `region1`/`region2` value that isn't in the curated 14.

## `region` table: pre-seed the full 49, decouple from `block_index`

`region(country VARCHAR(10) PRIMARY KEY, block_index INTEGER NOT NULL)` today gets one row per
country *lazily*, the first time that country is loaded (`get_or_assign_country_block`), and
`block_index` feeds directly into `trade_id_base`'s per-country arithmetic. Comprehensive rows
don't use `block_index` for anything (their `trade_id` is a plain running counter — next section),
but the table should still hold the comprehensive list, since it's also the FK target for
`trade.country` and the natural place to document "these are all the regions this database can
ever see a value for."

Add a one-time seed (idempotent, `ON CONFLICT (country) DO NOTHING` so it never disturbs an
already-assigned `block_index` for a country the old per-country path has already loaded) that
inserts all 49 codes above in their canonical order as `block_index` 1–49. A country already
present (e.g. `US` from the existing 2019/2021/2023 loads) keeps whatever `block_index` it already
has — this seed only fills in the gaps. Do this once, in the same preflight step that ensures
`industrydb`'s schema exists (see "Database write path" below), not per comprehensive run.

## Trade ID scheme: plain sequential, no blocks — and why that's safe

`industrydb`'s `trade`/`trade_factor` tables (`ensure_merge_infra` in `team/src/merge_years.rs`)
already have `PRIMARY KEY (year, trade_id)` — **`trade_id` only has to be unique within a year**,
not across the whole table. The per-country block scheme (`(country_block_index - 1) *
3,000,000 + flow_offset`) exists purely to let *multiple separate loads of the same year* (one
per country, on different days) avoid colliding. Comprehensive has no such problem: it builds
2018's entire trade graph in one run, so a plain 1-based counter (`trade_id = row_index + 1`,
first row 1, last row N, zero gaps) can't collide with itself, and `(year, trade_id) = (2018, *)`
can't collide with any other year already in the table either. No `country_block_index`, no
`get_or_assign_country_block` call, no `trade_id_base` arithmetic anywhere in this path.

This also removes the need for `trade_row_already_known`'s bilateral-flow dedup check. That check
exists because the *old* per-country model processes the same underlying flow twice — once as
country A's `exports` file, again as country B's `imports` file — and has to notice the second one
is a duplicate. Comprehensive never produces that duplicate in the first place (see next section:
each region pair is visited exactly once, as the exporter's turn), so the existing `UNIQUE
(year, region1, region2, industry1, industry2)` constraint on `trade` is a pure safety net here
(protects a resumed/retried run from double-inserting), not a routine dedup path.

## Extraction: one pass per region-as-exporter, not three passes per country

`trade.py`'s `extract_m_matrix_data` has the right *filtering conditions* for this, but the wrong
*mechanism* to loop 49 times — reusing it as literally written would be a serious mistake, not
just a stylistic one (see the measured numbers in "Memory management" below). Its `exports`
branch does:

```python
Z = exio_model.Z.copy()                                                   # full 9,800 x 9,800 matrix
Z_stacked = Z.stack(level=['to_region', 'to_sector'], future_stack=True).reset_index()  # 96,040,000 rows
Z_filtered = Z_stacked[Z_stacked['from_region'] == self.country].copy()
Z_filtered = Z_filtered[Z_filtered['to_region'] != self.country].copy()   # <- excludes domestic
```

It stacks the **entire** matrix into long format first, and only *then* filters down to one
region with a boolean mask. That's fine when it happens once per single-country run. Looping it
49 times for comprehensive would redo that full 96M-row stack 49 times over — see below for why
that's not acceptable.

Comprehensive's per-region chunk keeps the same filtering *conditions* (drop the
`to_region != self.country` exclusion, since domestic should stay in) but restructures the
*mechanism*: slice `Z.loc[region]` — that region's own 200 rows × 9,800 columns — **before**
calling `.stack()`, so only that region's ~2M-row slice is ever materialized, never the full 96M-row
one. Same filtering logic, applied to a 49x-smaller starting frame:

```python
keep = (
    ((Z_filtered.from_region == Z_filtered.to_region) & (Z_filtered.flow > 0.001)) |
    ((Z_filtered.from_region != Z_filtered.to_region) & (Z_filtered.flow > 0.01))
)
```

Looping this over all 49 regions (each as `from_region` exactly once) visits every
`(region1, region2)` ordered pair exactly once — region A's exports-to-B and region B's
exports-to-A are different pairs, both produced, but A→B is never produced twice. Domestic
(A→A) falls out for free as the diagonal case instead of needing its own separate run. There is
no separate `imports` pass at all: "B's imports from A" *is* "A's exports to B," already produced
when A had its turn. `flow_type` on each row can just be `'domestic'` (region1 == region2) or
`'international'` (otherwise) — there's no more imports/exports distinction to preserve, since
that distinction was only ever about *whose file* a row came from, and there's only one file now.
`country` becomes `region1` (the exporter) for the same reason.

## Memory management: stream by region, don't materialize the global matrix

Measured directly against the already-downloaded `IOT_2021_pxp.zip` (49 regions × 200 sectors
confirmed by counting `unit.txt`, so 9,800 × 9,800 = 96,040,000 possible `(from, to)` combinations)
to ground this in real numbers rather than estimates:

| | Full-matrix stack (`Z.stack()` on the whole matrix, then filter — what `extract_m_matrix_data` does today) | Per-region slice, stacked (`Z.loc[region]` **before** `.stack()`) |
|---|---|---|
| Rows produced | 96,040,000 | 1,960,000 |
| Deep memory (object dtype, as `.stack()` naturally produces) | ~29.8 GB | ~492 MB |
| After casting to `category` dtype | — | ~25.5 MB |
| Wall time | 5.7s | 0.3s |
| Process peak RSS | ~10.1 GB (up from a ~4.3 GB baseline — parsing the model itself, with every satellite extension, already costs that much) | ~4.4 GB (barely above the same baseline) |

Today's single-country code pays the left column's cost *once per run* and evidently survives it
(every country/flow-type/year combination loaded so far has finished successfully). Comprehensive
cannot pay that cost 49 times — looping `extract_m_matrix_data` as literally written would replay
a ~10GB-RSS, ~30GB-logical-size operation on every single region, reprocessing 4.7 billion
row-instances in total instead of 96 million. The right column is the actual design for this plan:

1. **Chunk by `from_region`, sliced *before* stacking.** `Z.loc[region]` — that region's own
   200 rows × 9,800 columns — stacked on its own, not filtered out of an already-stacked whole
   matrix. This is the one non-negotiable change from `extract_m_matrix_data`'s current mechanism;
   everything else in this section is a smaller refinement on top of it.
2. **Filter before mapping/grouping**, same order `trade.py` already uses — apply the amount
   threshold on the raw stacked chunk first, *then* map sector names to `industry_id` and
   `groupby`. Shrinks each chunk further before the more expensive steps.
3. **Categorical dtype** for `from_sector`/`to_region`/`to_sector` immediately after `.stack()`
   — per the table above, this is a ~19x reduction on top of the slicing (492MB → 25.5MB per
   chunk) for a single `astype('category')` call per column.
4. **Running `trade_id` counter carried across chunks**, not reset per region: chunk *n*'s first
   `trade_id` is `1 + (sum of rows written by chunks 1..n-1)`.
5. **`trade_factor` computation also happens per chunk**, immediately after that chunk's `trade`
   rows are finalized, using the *existing* `create_trade_factor`/`_aggregate_factors` logic in
   `trade.py` (already internally chunked at 10,000 rows for the `M`-matrix merge — reused
   unmodified, and operating on the chunk's already-aggregated, already-small `trade_df`, not the
   raw stacked frame) — then both are pushed to Postgres and the chunk is freed before the next
   region starts. Peak memory stays at roughly the ~4.3GB parse-time baseline throughout the whole
   49-region loop, not 49 sequential ~10GB spikes.

Recommend pulling `create_trade_factor`, `_aggregate_factors`, and the sector-mapping/threshold
helpers out of `trade.py`'s `ExiobaseTradeFlow` class into a small shared module (e.g.
`trade_extraction.py`) that both `trade.py` (per-country) and the new `trade_comprehensive.py`
import, rather than duplicating ~250 lines. `trade.py` keeps its existing single-country behavior
unchanged; `trade_comprehensive.py` calls the same functions once per region in a loop.

## Database write path: direct Postgres from Python, reusing `industrydb`'s existing schema

`connect_to_industrydb()` / `ensure_merge_infra()` (`team/src/merge_years.rs`) already point at
exactly the right target: the `EXIOBASE_NAME` database on the `EXIOBASE_HOST` Azure Postgres
server, using `EXIOBASE_USER`/`EXIOBASE_PASSWORD`/`EXIOBASE_PORT`/`EXIOBASE_SSL_MODE` — the same
credentials `db_test_exiobase_connection` already validates and the same database
`insert_trade_data_direct` already writes into for the curated-country path. Its `trade`/
`trade_factor` tables already have the `year` column and `(year, trade_id)` primary key this plan
needs — **no schema changes required**, comprehensive targets `industrydb` directly rather than a
per-year `industrydb_2018` database (there's no reason to create one; nothing else will ever read
`industrydb_2018` on its own).

Two options for how Python actually writes rows:

- **(A) Python connects directly via `psycopg2`/`asyncpg`, no Rust involved for the bulk data.**
  Reuses the exact `EXIOBASE_*` env vars, `COPY`s each region-chunk's rows into a temp staging
  table, then `INSERT ... SELECT ... ON CONFLICT (year, region1, region2, industry1, industry2) DO
  NOTHING` from staging into `trade` (mirrors `trade_natural_key`, and makes a retried/resumed run
  idempotent). Fastest option by far for millions of rows — no per-row HTTP/JSON overhead, no
  re-parsing CSV text server-side. This repo already has a (currently unused) precedent for
  Python→Postgres via `SQLAlchemy`/`psycopg2` in `insert_sql.py`, though that script's plain
  `to_sql(method="multi")` is line-at-a-time compared to `COPY` and has no dedup — worth
  referencing for the connection-string pattern, not for the insert method.
- **(B) A new Rust endpoint accepts a raw CSV/NDJSON body** (not a GitHub URL) and reuses
  `insert_trade_rows`-style chunked-insert code. Keeps all DB-writing logic in one language, but
  adds an HTTP hop + full serialize/deserialize round-trip for every row, which is the exact cost
  this plan is trying to avoid for large-scale data.

**Recommend (A) for `trade`/`trade_factor`** (the only tables large enough for the round-trip cost
to matter), but keep the *small* reference tables — `factor`, `industry`, `sector`,
`sector_industry` — going through Rust's existing `upsert_factor_rows_merged` /
`upsert_industry_rows` / `upsert_sector_rows` / `upsert_sector_industry_rows`. Those aren't pure
appends: `factor` in particular matches incoming rows against `industrydb`'s existing rows by
`(extension, stressor)` and remaps `factor_id` accordingly (see `PLAN-merge.md`'s "factor table"
section) — reimplementing that matching logic in Python would be new, delicate code duplicating
something that already works. Add one new thin Rust endpoint, e.g. `POST
/api/db/comprehensive/push-reference-tables`, that accepts the same four small CSVs `main.py`
already produces locally (`factor.csv`, `industry.csv`, `sector.csv`, `sector_industry.csv` — a
few hundred KB total, no reason to avoid the existing upload path for these) and calls the four
existing `upsert_*` functions directly — no GitHub fetch involved, just the CSV bodies in the
request, since these never need to go in `trade-data` for comprehensive's sake. This endpoint (or
a second tiny one) is also the natural place to call `ensure_merge_infra` + the `region` seed from
the previous section, as a preflight `trade_comprehensive.py` calls once before it starts
streaming region chunks.

## US/domestic local CSV continuity — derive it, don't recompute it

`bea/main.py` reads a local `trade-data/year/{year}/US/domestic/trade.csv` and keys
`interstate.trade_id` off that file's `trade_id` column directly (`interstate.trade_id` has a real
FK to `trade(year, trade_id)` — see `team/src/main.rs`'s `interstate` table comment). The plan text
asked whether the comprehensive run's `trade_id` for US-domestic rows could be *derived* via a
formula from Exiobase's indexed region order. It could (US is region 28 of 49 in the fixed order
above), but that would require knowing exactly how many rows every one of the 27 preceding
regions' chunks produced *before* US's turn — which means running those chunks anyway. There's no
shortcut that avoids computing the earlier chunks, so a derived formula would be strictly more
fragile than the alternative for zero benefit:

**Just slice it out of the in-memory chunk that already has the real `trade_id` values.** When
`trade_comprehensive.py` processes the `US` region's chunk (region 28 in the loop), after
assigning that chunk's `trade_id` range and pushing it to `industrydb`, filter that same in-memory
`DataFrame` for `region1 == 'US' & region2 == 'US'` and write it to
`trade-data/year/{year}/US/domestic/trade.csv` / `trade_factor.csv` in the exact format `trade.py`
writes today (`get_file_path(config, 'industryflow')` / `'trade_factor'` with `EXIOBASE_COUNTRY=US`
in the environment, same as always). Because it's the same objects, not a re-derivation, the
`trade_id` values are guaranteed identical to what's already sitting in `industrydb` — `bea/
main.py` and `run_interstate_step`'s `--interstate US` keep working completely unmodified. (`IN`/
`india/main.py` has no `trade_id` dependency at all — grepped, confirmed — so no equivalent slice
is needed there.)

## `.gitignore` — only relevant if a local staging file is ever used

Design (A) above never needs a durable local CSV for anything except the US-domestic slice (which
already belongs in `trade-data` and was never in question). If a future debugging pass wants an
optional local dump of a comprehensive run for inspection, write it under `trade-data/year/{year}/
comprehensive/` and add that path to `trade-data/.gitignore` (parallel to the existing `year/**/
*-lg.*` entry) before it's ever produced — never commit a comprehensive-scale file.

## Rollout: 2018

1. Download `IOT_2018_pxp.zip` (`ensure_exiobase_file`, reused as-is — not present in
   `exiobase_data/` yet, unlike 2019/2020/2021/2022/2023).
2. Preflight: call the new reference-tables endpoint (creates/updates `factor`/`industry`/`sector`/
   `sector_industry`, runs `ensure_merge_infra`, seeds `region` with all 49 codes).
3. Run `trade_comprehensive.py` for 2018 — loops all 49 regions, streams `trade`/`trade_factor`
   chunks straight into `industrydb` (`year=2018`), writes the `US/domestic` slice locally.
4. Verify: `SELECT count(*) FROM trade WHERE year=2018` has no gaps in `trade_id` (`max(trade_id) =
   count(*)`), `region` has all 49 codes, `fk_trade_region`/`fk_trade_industry1`/`fk_trade_industry2`
   have zero violations, and `US/domestic/trade.csv`'s `trade_id` values are a subset of
   `industrydb`'s `WHERE year=2018 AND region1='US' AND region2='US'` rows.
5. Run `bea/main.py` (`--interstate US`) against the 2018 local domestic CSV exactly as done for
   2019/2021/2023 today, confirm `interstate` rows insert with no FK violations against
   `trade(2018, *)`.

## Reuse checklist

| Reused as-is | New |
|---|---|
| `ensure_exiobase_file`, `pymrio.parse_exiobase3` | `trade_comprehensive.py` (region-loop driver) |
| `load_sector_mapping`/`create_sector_mapping` | `trade_extraction.py` (shared helpers pulled out of `trade.py`) |
| `create_trade_factor`/`_aggregate_factors` (chunked M-matrix merge) | `main.py`: `comprehensive` branch in the per-year loop, `run_comprehensive_processing()` |
| `connect_to_industrydb()` / `ensure_merge_infra()` | `region` 49-code seed (one-time upsert) |
| `upsert_factor_rows_merged`/`upsert_industry_rows`/`upsert_sector_rows`/`upsert_sector_industry_rows` | `POST /api/db/comprehensive/push-reference-tables` (thin wrapper around the four `upsert_*` calls + `ensure_merge_infra` + region seed) |
| `trade`/`trade_factor`'s existing `(year, trade_id)` PK and `trade_natural_key` UNIQUE constraint | Python-side direct `psycopg2` COPY-to-staging-then-`INSERT...ON CONFLICT` path for `trade`/`trade_factor` |
| `EXIOBASE_HOST`/`NAME`/`USER`/`PASSWORD`/`PORT`/`SSL_MODE` env vars | region-loop chunking + running `trade_id` counter + categorical-dtype memory handling |
| `get_file_path`/`config_loader.load_config` (for the US-domestic local slice) | `config.yaml`'s `comprehensive` `COUNTRY.list` value + `NOTES` entry |
| `trade_row_already_known` — **not reused**, not needed (see "Trade ID scheme") | |
| `country_block_index`/`trade_id_base`/`get_or_assign_country_block` — **not reused**, not needed | |
| `fetch_github_csv` / committing `trade.csv` to `trade-data` — **not used** for comprehensive rows | |
