# Comprehensive trade push: every region, direct to Azure, local folders for all 49 by default

Plan for a new `comprehensive` processing mode that extracts trade flows for **every** Exiobase
region in one pass (not a curated 14-country list) and writes them straight into the shared
`industrydb` Azure Postgres database. By default it also writes a local `year/{year}/{country}/`
folder for **all 49 regions** (not just the curated 14) — see `COMPREHENSIVE.folders` below for
scoping that down to just the 14 when the full 49's disk/git footprint isn't wanted. Initial
target year: **2018**.

This is additive: `default`/`all` keep working exactly as they do now (curated country list,
local CSVs, `POST /api/db/insert-trade-data`, per-country `trade_id` blocks). `comprehensive` is a
third, independent code path that happens to share almost all of its extraction and database
logic with the existing one — see "Reuse checklist" at the end.

A comprehensive run also becomes the source of local `.csv` folders going forward, exported from
`industrydb` right after the push commits (see "Local `.csv` output for country folders" below) —
so the `trade_id` values a website page reads out of `year/{year}/{country}/{flow}/trade.csv` are,
by construction, the exact same values a query against `industrydb` returns for that row, not a
second, independently-computed numbering.

## Implementation status

Everything in this plan is now built:

- `config.yaml` — `comprehensive` `COUNTRY.list` value + `COMPREHENSIVE.folders` (default `all`);
  `config_loader.py` — `EXIOBASE_COMPREHENSIVE_FOLDERS` override + `get_comprehensive_folders_scope()`.
- `trade_extraction.py` — the shared module: `EXIOBASE_REGIONS` (49-region canonical order,
  verified against `unit.txt`), `extract_region_chunk` (slice-before-stack), `aggregate_factors`/
  `build_factor_mapping`/`compute_trade_factor` (pulled out of `trade.py`, which now delegates to
  them — confirmed unchanged single-country behavior via a live extraction run against the
  already-downloaded 2021 data), and `ensure_industry_mapping`/`ensure_sector_tables`/
  `ensure_factors_export`.
- `industrydb.py` — direct `psycopg2` connection, `push_trade_rows`/`push_trade_factor_rows`
  (COPY-to-staging-then-`INSERT...ON CONFLICT`), `pull_trade_rows`/`pull_trade_factor_rows`/
  `pull_factor_reference` (the Azure-export side of "Local `.csv` output"), and
  `push_reference_tables` (calls the new Rust endpoint).
- `trade_comprehensive.py` — the region-loop driver: streams all 49 regions to `industrydb`,
  slices exports/domestic locally per in-scope region during the loop, pulls imports from
  `industrydb` after the loop, writes the non-default regions' own `runnote.md` and the
  default-14's `.comprehensive_timing.json` sidecar.
- `export_country_csvs.py` — the ad-hoc "add a folder later" exporter (all three flow types,
  straight from `industrydb`).
- `team/src/merge_years.rs` — `POST /api/db/comprehensive/push-reference-tables` (schema
  preflight + region seed + the four reference-table upserts + `factor_id_map` in the response),
  routed in `main.rs`. Builds clean (`cargo build`, no new warnings).
- `main.py` — `get_country_list_value()`, `run_comprehensive_processing()`, `run_country_processing`
  now takes an optional trimmed `scripts` list (skips `trade.py` for the post-comprehensive
  default-14 pass) and `extra_runnote_lines`, `create_runnote()` takes `extra_lines`.

**Verified so far:** the full region-loop → `trade_id` offsetting → local-folder-derivation →
Azure-imports-pull pipeline was run end-to-end against real, already-downloaded 2021 Exiobase data
with `industrydb` mocked out (a real Postgres round trip needs live `EXIOBASE_*` credentials this
environment doesn't have) — confirmed globally sequential `trade_id`s with zero gaps across
regions, correct `default`-14-vs-other-35 folder/runnote/sidecar branching under both
`COMPREHENSIVE.folders` settings, and `export_country_csvs.py`'s three-flow-type export shape.
**Not yet done:** an actual live run against `industrydb` (needs real `EXIOBASE_*` credentials and
writes real production rows — a deliberate, confirmable step, not something to run silently) and
downloading the 2018 Exiobase file itself (not present in `exiobase_data/` yet). See "Rollout: 2018"
below for that sequence.

## Why today's approach doesn't scale to "every region"

`trade.py` filters Exiobase's global inter-industry matrix (`Z`) down to one country's rows before
writing `trade.csv`, then that file is committed to the `trade-data` repo, fetched back over
`raw.githubusercontent.com` by `team`'s Rust backend (`fetch_github_csv`), and inserted with a
per-country `trade_id` block (`country_block_index`, see `PLAN-merge.md` in `team`). That
mechanism — not the *existence* of local files, which comprehensive still produces by default —
is the part that doesn't scale to 49 regions:

- **The GitHub round-trip is unnecessary.** Committing a file just so a server can immediately
  fetch it back over HTTP only makes sense when the round-trip is the only way to get data into
  Postgres. It isn't here (see "Database write path" below): pushing straight to Postgres and
  *separately* writing the local file from the same in-memory/already-committed data skips two
  network hops for the actual database load, whether or not a local folder also gets written.
- **Per-country `trade_id` blocks aren't needed.** They exist so that adding country #15 to an
  *already-loaded* database can't collide with country #1's ids. Comprehensive builds the entire
  year in one shot, so a plain 1-based sequential id has no gaps and can't collide with itself —
  see "Trade ID scheme" below for why it also can't collide with anything already in `industrydb`.

Local file *volume* is a separate, genuine tradeoff, not eliminated by any of the above: 49
regions' worth of `trade.csv`/`trade_factor.csv` is real disk/git footprint that the curated
14-country list never had to carry. `comprehensive` defaults to accepting that footprint (see
`COMPREHENSIVE.folders` below) because generating it costs nothing extra in *compute* — the
region-chunk that would produce a local file is already sitting in memory for all 49 regions
regardless of how many folders get written (see "Extraction" below) — but it's still real bytes on
disk and, if committed, in `trade-data`'s git history. `COMPREHENSIVE.folders: default` exists
specifically for whoever wants comprehensive's Azure coverage without that footprint.

## `config.yaml`: add `comprehensive` as a third `COUNTRY.list` option, plus a folder-scope knob

Today's `NOTES` section documents two `COUNTRY.list` values that `resolve_country_list()` in
`main.py` special-cases: `default` (14 countries) and `all` (whatever country folders already
exist on disk, i.e. the short curated list currently in `trade-data/year/{year}/`). Add a third,
plus a new, independent `COMPREHENSIVE.folders` setting controlling how many of the 49 pushed
regions also get a local folder (default: all 49):

```yaml
NOTES:
  1: COUNTRY.list "default" = run only incomplete ones within AU, BR, CA,
    CN, DE, FR, GB, IN, IT, JP, KR, RU, WM, US
  2: COUNTRY.list "all" = run all (could take hours)
  3: COUNTRY.list "comprehensive" = push every Exiobase region (all 49 —
    see PLAN-comprehensive.md) directly to Azure industrydb for one year.
    No per-country trade_id blocks. Set TRADEFLOW to anything;
    comprehensive ignores it (imports/exports/domestic all come out of one
    extraction — see PLAN-comprehensive.md). Writes a local
    year/[year]/[country]/ folder for every one of the 49 regions by
    default — set COMPREHENSIVE.folders to "default" to only write
    folders for the 14 default-list countries instead (every region is
    still pushed to Azure either way; this only controls local .csv
    output).
COMPREHENSIVE:
  folders: all   # "all" (default, all 49 regions get a local folder) | "default" (only the 14 default-list countries)
```

`EXIOBASE_COMPREHENSIVE_FOLDERS` overrides `COMPREHENSIVE.folders` the same way
`EXIOBASE_TRADEFLOW`/`EXIOBASE_YEAR`/`EXIOBASE_COUNTRY_LIST` already override their config.yaml
counterparts in `config_loader.load_config()` — same pattern, one more `if
os.environ.get(...)` block, no change to the override mechanism itself.

`main.py` needs one new early branch, not a change to `resolve_country_list()` itself (that
function's job — turning a country list into... a country list — doesn't fit "there is no country
list, run one job for the whole year"). In `process_tradeflow`'s caller (the per-year loop around
`main.py:408`), check `country_list.lower() == 'comprehensive'` *before* calling
`resolve_country_list`/`filter_incomplete_countries`/`process_tradeflow`, and dispatch to a new
`run_comprehensive_processing(year)` instead. That function runs a new script
(`trade_comprehensive.py`, see below) once per year via the same `subprocess.run(...,
env={**os.environ, 'EXIOBASE_YEAR': str(year)})` pattern `run_country_processing` already uses —
no `EXIOBASE_COUNTRY`/`EXIOBASE_TRADEFLOW` needed, since comprehensive has neither, but it does
pass through `EXIOBASE_COMPREHENSIVE_FOLDERS` if set. Once `trade_comprehensive.py` exits,
`run_comprehensive_processing` also runs the new Azure-export step (see "Local `.csv` output for
country folders" below) for whichever region list `COMPREHENSIVE.folders` resolved to (all 49 by
default, or just the `default`-14), so `year/{year}/{country}/{domestic,imports,exports}/
trade.csv` exist locally exactly as if `default`/`all` had been run for that region — `--interstate
US` and the rest of `run_country_processing`'s script chain (`trade_impact.py`/`trade_resource.py`/
`trade_competitiveness.py`) keep working unmodified against those files afterward. That downstream
script chain itself stays scoped to the `default`-14 regardless of `COMPREHENSIVE.folders` — it's
per-country economic/competitiveness analysis, not something this plan extends to the other 35 by
default; a region outside `default` that gets a folder from `COMPREHENSIVE.folders: all` gets
`trade.csv`/`trade_factor.csv` and a `runnote.md`, not `trade_impact.csv`/`export_competitiveness.csv`
unless separately requested.

## Confirmed: Exiobase's regions have a fixed, discoverable order

The plan text asked to investigate whether regions "reside in the Exiobase file in an indexed
order" — yes. Read directly from `unit.txt` inside `exiobase_data/IOT_2021_pxp.zip` (first-seen
order of the `region` column, which matches `Z.txt`'s column order):

```
1  AT   8  EE   15 IE   22 PL   29 US   36 MX   43 ID
2  BE   9  ES   16 IT   23 PT   30 JP   37 RU   44 ZA
3  BG   10 FI   17 LT   24 RO   31 CN   38 AU   45 WA
4  CY   11 FR   18 LU   25 SE   32 CA   39 CH   46 WL
5  CZ   12 GR   19 LV   26 SI   33 KR   40 TR   47 WE
6  DE   13 HR   20 MT   27 SK   34 BR   41 TW   48 WF
7  DK   14 HU   21 NL   28 GB   35 IN   42 NO   49 WM
```
(44 country rows + 5 RoW aggregates: WA/WL/WE/WF/WM, last)

(exact list: `AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK GB
US JP CN CA KR BR IN MX RU AU CH TR TW NO ID ZA WA WL WE WF WM` — 49 total, EU-27 first, then
non-EU OECD-ish countries, then the 5 Rest-of-World aggregates last). This is stable across at
least the 2019–2023 files already downloaded (spot-checked 2021; pymrio's `parse_exiobase3` always
yields this same column order per Exiobase's own file format, not something the loader controls).

**This order is not used to *derive* `trade_id` across regions** (see next section for why a
formula predicting US's block from this list is the wrong tool for that) but it is used to
pre-seed the `region` table (below), and it's useful context for anyone reading a
`region1`/`region2` value that isn't in the curated 14. It's also, since a later revision of this
plan, the basis for `trade_id` order *within* one region's own rows too — see
`extract_region_chunk`'s ordering step in `trade_extraction.py` and README.md's "Exiobase trade
record order" note. That took two attempts to get right: `.stack(future_stack=True)` turned out to
unconditionally re-sort its output alphabetically (no way to opt out), and even after switching to
a numpy-based reshape that preserves file order, a naive "first row to survive the amount
threshold" order turned out to reflect which regions/industries happen to trade early in the
sector list that particular year, not Exiobase's fixed column position (confirmed against real
2021 data: Malta's very first raw sector has zero measured flow to Austria specifically, but not
to Italy, which would make Austria look like it comes "after" Italy under a survival-based order).
The fix computes each row's position from pure structural facts — region's fixed list position,
industry's fixed sector position — entirely decoupled from which cells happen to clear that year's
threshold.

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

**All 49 regions get pushed to `industrydb`; all 49 get a local folder too, by default.** The loop
above runs for every region regardless — that's what makes the year "comprehensive" in
`industrydb` — and since a region's own chunk (exports+domestic) is already sitting in memory the
moment that region has its turn, writing it to `year/{year}/{country}/{domestic,exports}/trade.csv`
costs nothing extra in compute for any of the 49, not just the curated 14 (see "Local `.csv`
output for country folders" below for exactly what's written per region, and how `imports` — the
one flow type that isn't free — gets added afterward). Set `COMPREHENSIVE.folders: default` in
`config.yaml` to fall back to only the 14 `default`-list regions if the other 35 regions' disk/git
footprint isn't wanted; `industrydb` gets all 49 either way.

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

## Local `.csv` output for country folders — memory for exports/domestic, Azure for imports

Three related questions this section answers: (1) can comprehensive produce local `.csv` folders
at all, so a webpage reading `year/{year}/{country}/{flow}/trade.csv` sees `trade_id` values that
line up with `industrydb`, (2) for how many of the 49 regions (all of them, by default — see
`COMPREHENSIVE.folders` above), and (3) can a `[year]/[country]` folder be added *later*, for a
region that wasn't given a folder the first time (e.g. `COMPREHENSIVE.folders: default` was used,
or the region is genuinely new), with the same alignment?

**Chosen design: a hybrid, split along the same "local to one chunk vs. not" line from
"Extraction" above.** A region's own chunk (built when it has its turn as `from_region`) contains
that region's **domestic** rows (`region1 == region2`) and **exports** rows (`region1 == region,
region2 != region1`) in full — nothing else in the 49-region loop can add to either, so they're
final the moment that region's chunk is computed. Its **imports** are not local — they're
scattered across up to 48 *other* regions' chunks (B's imports from A live in chunk A, produced
when A has its turn, not when B does) — so they can only be complete once the entire 49-region
loop has finished. This split is exactly why "for how many regions" and "which mechanism" are
independent questions: `COMPREHENSIVE.folders` only decides *which regions* below get a folder at
all (all 49 by default, or just the `default`-14); every region that does get one still gets its
exports/domestic from memory and its imports from Azure, the same way.

- **Exports + domestic, for every in-scope region (all 49 by default), sliced straight out of that
  region's own in-memory chunk** at the point in the loop where that region has its turn — no
  extra database round-trip, no waiting for the other 48 regions. Same for their `trade_factor`
  rows, which are already computed per-chunk anyway (see "Memory management" above) using the
  `factor_id` mapping already finalized by the reference-table preflight step, so no remap risk
  here either. Written via the same `get_file_path(config, ...)` calls `trade.py` already uses,
  with `EXIOBASE_COUNTRY=<region>` in the environment — same file, same format, same `trade_id`
  values that were just pushed to `industrydb` for that chunk. Skipped entirely for a region
  `COMPREHENSIVE.folders: default` excludes — that region's chunk still gets pushed to
  `industrydb`, just never written to disk.
- **Imports, for every in-scope region, pulled from `industrydb` once the full 49-region loop
  finishes** — a plain `SELECT trade_id, region1, region2, industry1, industry2, amount FROM trade
  WHERE year = :year AND region2 = :country AND region1 != :country`, joined against
  `trade_factor` on the resulting `trade_id` set for `trade_factor.csv`. This is the only part of
  country-folder generation that costs a real network round-trip, and it can only happen after
  every region has had its turn (a country's imports may be contributed by any of the other 48).
  With `COMPREHENSIVE.folders: all` this means 49 pull queries instead of 14 — each one a simple
  indexed lookup, not a scan, so the added count is cheap relative to the loop itself.

`trade_id` alignment is exact either way — the in-memory slice *is* what was pushed to
`industrydb`, not a recomputation, and the Azure pull reads back `industrydb`'s own values — so
`bea/main.py`, `india/main.py`, `trade_impact.py`, `trade_resource.py`, and
`trade_competitiveness.py` all keep reading local files in the same shape they always have,
unmodified. Column layout for both paths matches what `trade.py`/`create_trade_factor` already
write (`trade_id, region1, region2, industry1, industry2, amount` and `trade_id, factor_id, level`
— confirmed against `trade.py:export_to_csv` and the Rust CSV parsers in `insert_trade_rows`/
`insert_trade_factor_rows`, which read those exact headers).

**`runnote.md` records the Azure-pull duration**, written for every region that gets a folder (all
49 by default). `create_runnote()` already writes a `**Duration:**` line per country/tradeflow
from `run_country_processing`'s script-timing. Extend it (or the comprehensive-derived country
folders' equivalent call) with a second line specific to this hybrid — e.g. `**Imports export
(Azure):** {seconds:.1f}s` — timed around just the `SELECT` + write step for that region's
`imports` folder. The exports/domestic slice needs no timing line of its own worth noting (it's a
`DataFrame` filter on data already in memory, not a separate operation with its own cost); the
interesting number here is specifically how long the one real network round-trip per region took,
which varies with how many of the other 48 regions trade with it. Only the `default`-14 get the
full `trade_impact.py`/`trade_resource.py`/`trade_competitiveness.py` subprocess chain afterward,
exactly as `run_country_processing` does today (see previous section) — for those 14,
`create_runnote`'s existing `success_count`/`total_scripts` bookkeeping only needs to account for
those three scripts, not four, since `trade.py` itself was skipped (its output already exists).
The other 35 (when `COMPREHENSIVE.folders: all`) get a `runnote.md` documenting just the
`trade.csv`/`trade_factor.csv` derivation and its Azure-pull timing — no scripts ran for them, so
that line is simply omitted rather than reported as `0/3`.

One correctness detail that's easy to miss: **local `factor.csv` must also be exported from
`industrydb`'s `factor` table, not generated locally by `factors.py`'s `create_factors_csv()`.**
That function assigns `factor_id` by walking Exiobase's own extension/stressor order fresh every
run, starting at 1 — fine in isolation, but `industrydb`'s `factor` table only agrees with that
numbering for the *first* year ever merged into it. Every later year's `upsert_factor_rows_merged`
remaps incoming `factor_id`s to match existing rows by `(extension, stressor)` (see
`PLAN-merge.md`'s "factor table" section), so by the time 2018 runs, `industrydb.factor` already
holds 728 rows from 2019/2021/2023 with IDs that don't line up with a fresh local 1-based count.
Exporting `factor.csv` from `industrydb.factor` (`factor_id, unit, stressor, extension` — same
four columns `create_factors_csv()` writes, different source) keeps `trade_factor.csv`'s
`factor_id` values meaningful against the `factor.csv` shipped alongside it.

**Answering "add a `[year]/[country]` folder later":** once a year has gone through comprehensive,
every region's rows are already in `industrydb` regardless of `COMPREHENSIVE.folders` — that
setting only ever controlled which regions got a *local file*, never which regions got pushed to
Azure (that's always all 49). So "add a folder later" now almost always means "a region
`COMPREHENSIVE.folders: default` excluded the first time," not "a region comprehensive never saw"
— there's no such thing as the latter for a year that's already been through comprehensive. Either
way the answer is the same: **always export from Azure, never re-run the Exiobase extraction, for
any year already loaded.** Unlike the in-loop case above, there's no in-memory chunk left to slice
from by then — the comprehensive run that built it is long finished — so a later request pulls
**all three** flow types (`exports`/`domestic`/`imports`, not just `imports`) from `industrydb`
with the same `SELECT` shape, using `region1 = :country AND region2 != :country` for exports and
`region1 = region2 = :country` for domestic instead of the in-memory filter. Re-deriving from the
raw Exiobase `.zip` (Exiobase's indexed region order, re-parsing, re-stacking) is strictly worse
for this case — slower (re-downloads/re-parses a multi-GB file and re-runs the six-extension
factor merge from scratch), and, if a future code change ever alters a threshold or aggregation
rule, silently *riskier*: a locally-recomputed file could drift from what's actually stored in
`industrydb` without either side erroring, whereas a straight export can't drift because it has no
independent computation to drift from. Re-running the Exiobase extraction only remains relevant
for a year that hasn't been comprehensively loaded into `industrydb` at all yet — an entirely
different situation ("load a new year," covered by "Rollout" below) from "get an existing year's
data into one more local folder."

## `.gitignore` — worth deciding on before the first `COMPREHENSIVE.folders: all` run

With all 49 regions writing local folders by default, `trade-data` gains real new volume every
comprehensive year — not the "many GB" the full in-memory matrix would have been (that risk is
fully handled by the per-region streaming design regardless of folder count), just the ordinary
linear cost of ~3.5x today's 14-country footprint per year. Whether to commit all 49 regions'
folders or only the `default`-14's is a `trade-data` git-history/repo-size decision for whoever
maintains it, independent of this plan — `COMPREHENSIVE.folders: default` avoids generating the
other 35 at all; `.gitignore`-ing a pattern like `year/*/[A-Z][A-Z]/` for the non-`default` codes
is the alternative if the files should exist locally but never be committed. Separately, if a
future debugging pass wants an optional local dump of a comprehensive run for inspection, write it
under `trade-data/year/{year}/comprehensive/` and add that path to `trade-data/.gitignore`
(parallel to the existing `year/**/*-lg.*` entry) before it's ever produced — never commit a
comprehensive-scale file.

## Rollout: 2018

1. Download `IOT_2018_pxp.zip` (`ensure_exiobase_file`, reused as-is — not present in
   `exiobase_data/` yet, unlike 2019/2020/2021/2022/2023).
2. Preflight: call the new reference-tables endpoint (creates/updates `factor`/`industry`/`sector`/
   `sector_industry`, runs `ensure_merge_infra`, seeds `region` with all 49 codes).
3. Run `trade_comprehensive.py` for 2018 (`COMPREHENSIVE.folders` left at its default, `all`) —
   loops all 49 regions, streams `trade`/`trade_factor` chunks straight into `industrydb`
   (`year=2018`), and, for every one of the 49, slices that region's own chunk into
   `year/2018/{country}/{domestic,exports}/trade.csv`+`trade_factor.csv` as it goes (no Azure
   round-trip for these). Consider `COMPREHENSIVE.folders: default` for a first dry run against a
   scratch `trade-data` checkout, to see the Azure-only 35 vs. local-49 split before committing to
   the full footprint.
4. Once all 49 regions are done, pull `imports` for all 49 from `industrydb`
   (`year/2018/{country}/imports/trade.csv`+`trade_factor.csv`), timing each region's pull for its
   `runnote.md` line. Export the shared `year/2018/factor.csv` from `industrydb.factor` (using the
   `factor_map` the preflight step already returned) and copy the locally-produced
   `industry.csv`/`sector.csv`/`sector_industry.csv` into place (never remapped, no Azure round
   trip needed for those).
5. Verify: `SELECT count(*) FROM trade WHERE year=2018` has no gaps in `trade_id` (`max(trade_id) =
   count(*)`), `region` has all 49 codes, `fk_trade_region`/`fk_trade_industry1`/`fk_trade_industry2`
   have zero violations, and every region folder's three `trade_id` ranges (exports/domestic from
   memory, imports from Azure) are disjoint and all present in `industrydb WHERE year=2018`.
6. Run `bea/main.py` (`--interstate US`) against the 2018 `US/domestic` folder exactly as done for
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
| `get_file_path`/`config_loader.load_config` (for writing local folders in the existing layout) | in-loop exports/domestic slice-and-write inside `trade_comprehensive.py`, per in-scope region (all 49 by default) |
| `trade.py`/`create_trade_factor`'s exact CSV column layout (so derived files read identically to today's) | `export_country_imports.py` (or a function `trade_comprehensive.py` calls post-loop) — pulls just `imports` for every in-scope region once the 49-region loop finishes |
| `create_runnote()` (extended with a second timing line, not replaced — see previous section) | `export_country_csvs.py` — pulls **all three** flow types from `industrydb`, for any later ad-hoc `[year]/[country]` folder request where no in-memory chunk exists any more |
| `config_loader.load_config`'s existing env-override pattern (`EXIOBASE_TRADEFLOW` etc.) | `COMPREHENSIVE.folders` config.yaml key + `EXIOBASE_COMPREHENSIVE_FOLDERS` override — `all` (default, all 49 get folders) vs. `default` (just the 14) |
| `trade_row_already_known` — **not reused**, not needed (see "Trade ID scheme") | |
| `country_block_index`/`trade_id_base`/`get_or_assign_country_block` — **not reused**, not needed | |
| `fetch_github_csv` / committing `trade.csv` to `trade-data` — **not used** for comprehensive rows | |
| `factors.py`'s `create_factors_csv()` local numbering — **not reused** for exported `factor.csv` (must come from `industrydb.factor`, see previous section) | |
