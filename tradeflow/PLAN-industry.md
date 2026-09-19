# Industry Classification Alignment Plan

## Problem

Every table in this pipeline (`trade.csv`, `trade_factor.csv`, `interstate.csv`,
`interstate_factor.csv`, ...) is keyed on **our own** 5-character industry
classification, generated directly from Exiobase's ~200 raw sector names by
`create_sector_mapping.py`. This scheme was never derived from, or reconciled
with, BEA's official industry classifications — which is what EPA's own
USEEIO / `import_emission_factors` process (see `bea/README.md`'s "EPA import
factor reduction" section) actually computes and publishes against.

This matters for two separate reasons, addressed in two phases below:

1. **File size.** Our current ~200-industry granularity, combined with the
   state×state disaggregation in `interstate`/`interstate_factor`, produces
   the multi-GB files described in the repo's size-analysis discussions
   (`interstate_factor.csv` alone was 1.4 GB for 2021 at 10 aggregated
   factors). A coarser industry classification directly reduces row counts.
2. **Matching EPA's published values.** Even with the M-matrix fix, the GHG
   flow aggregation, and the currency fix (still open, see `bea/README.md`),
   our factor levels are computed per **our** industry code, not BEA's. EPA's
   own import factors are published at BEA's **Detail** level (~405-411
   industries — see `bea/README.md`'s note that this is *more* granular than
   our own ~200 codes, not less) and a **Summary** rollup (~71-73 industries).
   Without re-keying through the same crosswalk EPA uses, our numbers can't
   be compared industry-for-industry against theirs, independent of every
   other fix already made.

## What we already have

Two concordance files are already auto-fetched into `trade-data/concordance/`
(see `bea/main.py`'s `_ensure_concordance_file`, currently used only to
populate `interstate.csv`'s `commodity_code`/`industry_code` columns, not for
factor computation or industry-level aggregation):

| File | Maps | Rows | Unique left | Unique right |
|---|---|---|---|---|
| `exio_to_useeio2_commodity_concordance.csv` | Exiobase sector → USEEIO Detail | 558 | 200 (Exiobase) | 376 (USEEIO Detail, intersected with Exiobase) |
| `useeio_internal_concordance.csv` | USEEIO Detail → BEA Summary | 444 | 429 (USEEIO Detail) | 96 (BEA Summary, includes some non-industry adjustment rows — the ~71-73 "core industry" count people usually cite) |

Chaining these two gives a full Exiobase-sector → BEA-Summary crosswalk. Both
mappings are **many-to-many**: a single Exiobase sector can map to more than
one USEEIO Detail code and vice versa (558 rows for 200 Exiobase sectors), so
collapsing requires **weighted aggregation**, not a simple relabel — EPA's own
`generate_import_factors.py` does this via import-quantity-weighted averaging
(`get_weighted_average()`) when multiple MRIO sectors fold into one BEA sector.
We have no equivalent weighting source (BEA import-share data) wired in yet.

**BEA Sector level (the coarsest published tier, ~21 categories)** isn't in
either concordance file above — it's one level coarser than the BEA Summary
codes we have. The authoritative source for the full Sector↔Summary↔Detail↔
NAICS crosswalk is BEA's own government publication, confirmed by reading
`useeior`'s own build scripts (`data-raw/MasterCrosswalk.R`,
`data-raw/BEAData.R`, both in
[cornerstone-data/useeior](https://github.com/cornerstone-data/useeior)),
which derive `useeior`'s crosswalk from it directly rather than from a
separately-published crosswalk file:

> **BEA Supply-Use Table framework file, "NAICS Codes" sheet**
> `https://apps.bea.gov/industry/release/zip/SUPPLY-USE.zip` →
> `Use_SUT_Framework_{year}_DET.xlsx`, sheet `NAICS Codes`

That sheet lists every BEA Detail code alongside its parent Summary and
Sector codes and related NAICS codes in one table. **Downloaded and parsed**
(the "NAICS Codes" sheet's Sector/Summary columns only, via a one-time script
— not re-derived at pipeline runtime) into
`trade-data/concordance/bea_summary_to_sector_concordance.csv` (73 BEA
Summary codes → 23 BEA Sector codes, including "Used"/"Other" adjustment
rows). Chained with the two files above in `exiobase_industry.py`.

The 21 core Sector categories themselves (from `BEA_2012_Sector_CodeName_mapping.csv`
in the same `useeior` repo, cross-checked against the parsed BEA source
above) are documented below in Phase 1.

## Phase 1 (near-term): `-lg` files + BEA Sector (~21) primary output — IMPLEMENTED

Driven by the file-size problem, not full EPA-value matching. Two tiers, not
three — an intermediate BEA-Summary ("-med") tier was considered and dropped:
it isn't needed for correctness (an unweighted collapse straight to Sector
gives the same totals as collapsing to Summary first, since summation is
associative — the concordances chain through a shared `USEEIO_Detail_2017`
key regardless of how many hops are taken) and nothing has asked for a file
literally comparable to EPA's own published Summary-level report as a
deliverable. Scope:

1. **DONE — full-detail outputs write to a `-lg` sibling.** Our existing
   ~200-industry granularity, not committed — `trade-lg.csv`,
   `trade_factor-lg.csv`, `interstate-lg.csv`, `interstate_factor-lg.csv`,
   `export_competitiveness_state-lg.csv`, `import_dependency_state-lg.csv`.
   (Distinct from the pre-existing `trade_factor_lg.csv`/
   `interstate_factor_lg.csv`, which mean "all 721 raw unaggregated
   factors" and are unaffected — `-lg` here means "full industry detail,"
   a different axis of size. See `exiobase_industry.py`'s `lg_path()`.)
2. **DONE, then narrowed — see "Revision: `trade`/`trade_factor` stay at
   full industry detail" below.** Originally, primary (committed) outputs
   were aggregated to BEA Sector level (~21 categories, see table below)
   for **both** `trade`/`trade_factor` and `interstate`/`interstate_factor`
   via `trade.py`'s `aggregate_to_sector()`. That's since been reverted for
   `trade`/`trade_factor` specifically — they were never the file-size
   problem — leaving only `interstate`/`interstate_factor` (and
   `export_competitiveness_state.csv`/`import_dependency_state.csv`, which
   collapse "for free" once fed the Sector-level `interstate.csv`) with the
   Sector-level split. `bea/main.py`'s domestic-flow and export/
   import-analysis functions take `trade_file_override`/
   `interstate_file_override` + `output_suffix` params and are called a
   second time (when the `-lg` sibling input exists) to produce the
   full-detail `-lg` outputs, reusing the same disaggregation logic rather
   than duplicating it.

   **Many-to-many resolution:** originally resolved by majority vote (one
   winning Sector per ambiguous industry); since replaced by proportional
   weighted splitting — see point 7 below.

   Row-count math (2021 real data): `interstate` rows are keyed on
   `(industry1, industry2)` *pairs*, not one industry dimension, so the
   reduction is quadratic, not linear — 167×171 possible industry values
   with 17,135 pairs actually populated (60% density) collapse to a
   21×21 = 441 pair-space, a ~65x shrink (28,557 → 441) versus the ~9.5x a
   naive linear estimate would suggest.
3. **Kept the long/relational format** (one row per `interstate_id`/`trade_id`
   × `factor_id`) for the Sector-level primary output — no wide-table pivot
   was needed. Real measured sizes, 2021 validation run:

   | File | Primary (BEA Sector) | `-lg` (full detail) |
   |---|---|---|
   | `trade.csv` | 8.0 KB | 485 KB |
   | `trade_factor.csv` | 37 KB | 1.4 MB |
   | `interstate.csv` | 9.4 MB (125,144 rows) | 285 MB (2,741,600 rows) |
   | `interstate_factor.csv` | 55 MB (1,251,440 rows) | 1.4 GB (27,416,000 rows) |
   | `export_competitiveness_state.csv` | 7.4 MB (125,144 rows) | 176 MB |
   | `import_dependency_state.csv` | 7.4 MB (125,144 rows) | 175 MB |

   Every primary file is comfortably under GitHub's 100 MB hard limit — the
   largest, `interstate_factor.csv`, is 55 MB. Total across all primary
   files: ~79 MB.
4. `config.yaml`'s `FILES` block needed no changes — `-lg` paths are derived
   programmatically from each primary path (`exiobase_industry.py`'s
   `lg_path()`) rather than configured separately.
5. **DONE** — `.gitignore` in the `trade-data` repo blocks anything named
   `*-lg.*` under `year/` at any depth: `year/**/*-lg.*` (the literal pattern
   `*/year/*-lg` doesn't match here since `year/` is the repo root, not one
   level down — needed the recursive-glob form instead).
6. **DONE, superseded by a `sector`/`sector_industry` split (see below) —**
   `industry.csv` initially gained the 23 BEA Sector codes as extra rows
   (`cattype='bea_sector'`) so `trade.sector1`/`sector2` would have a
   matching FK target. That approach was replaced once we confirmed the
   Exiobase→Sector mapping is genuinely many-to-many (next point), which a
   single `industry.csv` table with mixed row "levels" can't represent
   correctly.
7. **DONE — real database redesign: separate `sector` table +
   `sector_industry` many-to-many join, `cattype` removed again.**
   Checked empirically (not assumed) how many of the 200 Exiobase
   industries chain to more than one candidate BEA Sector via the
   concordance chain: 184/200 land on exactly one, but 16/200 are genuinely
   ambiguous (up to 7 candidate Sectors, e.g. "Other business services").
   A single `industry.sector_id` FK column would silently duplicate or
   misassign those 16 industries, so instead:
   - `industry.csv` reverted to just the ~200 raw Exiobase rows
     (`industry_id, name, category`) — no `cattype`, no appended Sector
     rows.
   - New `sector.csv` (`sector_id, name`) — the 23 BEA Sector rows.
   - New `sector_industry.csv` (`sector_id, industry_id, weight`) — the
     many-to-many join, one row per (sector, industry) pair a given
     industry chains to, `weight` = fraction of that industry's mapped
     USEEIO Detail codes landing in that Sector (weights for a given
     `industry_id` sum to 1.0). Generated by
     `exiobase_industry.industry_id_to_sector_weights()` /
     `create_sector_mapping.create_sector_table()` /
     `create_sector_industry_table()`.
   - `trade.industry1`/`industry2` and `interstate.industry1`/`industry2`
     **renamed to `sector1`/`sector2`** — both the DB columns (via
     `ALTER TABLE ... RENAME COLUMN` in `team/src/main.rs`, safe no-op on a
     fresh DB) and the primary CSV headers (`trade.py`'s
     `aggregate_to_sector`, `bea/main.py`'s `_aggregate_interstate_to_sector`)
     — since these primary-table columns now genuinely hold BEA Sector
     codes, not Exiobase industry codes. The `-lg` full-detail siblings are
     unaffected and keep `industry1`/`industry2` (genuine Exiobase industry
     codes at that grain). FKs on `trade`/`interstate` now point at
     `sector(sector_id)` instead of `industry(industry_id)`.
   - **Proportional split, not majority vote.** An ambiguous industry's
     `amount`/`level` is split across all of its candidate sectors weighted
     by `sector_industry.weight` (mirroring EPA's own
     `generate_import_factors.py` `get_weighted_average()` in spirit, see
     `exiobase_industry.py`'s module docstring), rather than picking one
     Sector via majority vote as originally implemented. Validated against
     real 2021 output: total `amount` is preserved (~21.87M, matching
     within floating-point rounding) across `trade.csv`/`trade-lg.csv` and
     `interstate.csv`/`interstate-lg.csv` — no double-counting or data loss
     from the weighted explode-and-resum.
   - `team/src/main.rs`: added `sector` and `sector_industry` tables/DDL,
     `upsert_sector_rows`/`upsert_sector_industry_rows`, updated
     `industry_static_schema()`/`relationships`/`valid_tables`/table
     descriptions, and `db_insert_trade_data` now loads `sector.csv`/
     `sector_industry.csv` alongside `industry.csv`. `index.html`'s schema
     preview (`getStaticSchema()`, `layout`, `rels`) updated to match.

### The 21 BEA Sector categories

| Code | Name |
|---|---|
| 11 | Agriculture, forestry, fishing, and hunting |
| 21 | Mining |
| 22 | Utilities |
| 23 | Construction |
| 31ND | Nondurable goods manufacturing |
| 33DG | Durable goods manufacturing |
| 42 | Wholesale trade |
| 44RT | Retail trade |
| 48TW | Transportation and warehousing |
| 51 | Information |
| 52 | Finance and insurance |
| 53 | Real estate and rental and leasing |
| 54 | Professional and technical services |
| 55 | Management of companies and enterprises |
| 56 | Administrative and waste services |
| 61 | Educational services |
| 62 | Health care and social assistance |
| 71 | Arts, entertainment, and recreation |
| 72 | Accommodation and food services |
| 81 | Other services, except government |
| G | Government |

21 was chosen over `useeior`'s further-aggregated 15-code tier (which merges
`52`+`53`→FIRE, `54`+`55`+`56`→PROF, `61`+`62`, `71`+`72`, and `31ND`+`33DG`):
five of those six merges collapse distinctions Exiobase's own sectors already
respect cleanly, so keeping them split costs nothing. The one genuinely
awkward boundary is `31ND` vs. `33DG` (durable vs. nondurable manufacturing)
— a BEA economic-accounting split that doesn't correspond to how Exiobase
organizes manufacturing at all (by material/process — textiles, chemicals,
basic metals — not durable-goods classification). Attributing each Exiobase
manufacturing sector to the correct side is still doable via the Detail-level
concordance chain (Detail codes are unambiguously assigned to one Sector in
BEA's data), just not a natural Exiobase-side boundary.

### Open design questions — resolved

These were the open questions before implementation; each is answered by
what's now built (see point 7 above):

- **`trade.csv` itself moves** to BEA Sector level (not just the
  factor/interstate tables) — `trade_id` is reassigned sequentially at the
  Sector grain by `aggregate_to_sector()`, and the dedup key becomes
  `(region1, region2, sector1, sector2)`. `trade_factor.csv` doesn't need
  independent re-aggregation: it's remapped from the full-detail result via
  the `trade_id_map` `aggregate_to_sector()` returns, not recomputed.
- **`interstate_id` now encodes the Sector grain** for the primary file
  (`{trade_id}-US-{state1}-US-{state2}-{sector1}-{sector2}`, built in
  `bea/main.py`'s `_aggregate_interstate_to_sector`); the `-lg` sibling
  keeps the original Exiobase-industry-grain ids unchanged.
- **`amount`/`level` aggregation** is a straight sum after weighting each
  contributing row by its `sector_industry.weight` (proportional split, not
  an unweighted sum) — see point 7's proportional-split note.
  `economic_multiplier`/`commodity_code`/`industry_code` are dropped to
  fallback defaults in the primary `interstate.csv` since no single value
  is well-defined once ambiguous industries split/collapse.
- **The `team` (Rust) schema did need changes**, beyond just registering
  new codes: `interstate`'s `industry1`/`industry2` columns were renamed to
  `sector1`/`sector2` and its FKs repointed from `industry(industry_id)` to
  the new `sector(sector_id)` table, with the many-to-many detail captured
  in `sector_industry` rather than in `industry.csv` itself. (`trade`
  stayed on `industry1`/`industry2` — see the revision note below.)

## Revision: `trade`/`trade_factor` stay at full industry detail

The Sector-level aggregation above was originally applied to **both**
`trade`/`trade_factor` and `interstate`/`interstate_factor`. Revisited after
implementation, using the actual measured sizes from the Phase 1 validation
table above:

| File | Primary (Sector) | Full detail |
|---|---|---|
| `trade.csv` | 8.0 KB | 485 KB |
| `trade_factor.csv` | 37 KB | 1.4 MB |
| `interstate.csv` | 9.4 MB | 285 MB |
| `interstate_factor.csv` | 55 MB | 1.4 GB |

`trade.csv`/`trade_factor.csv` were never the file-size problem — even at
full ~200-industry detail they're under 1.5 MB, nowhere near GitHub's
100 MB limit. The actual blowup is specific to `interstate`/
`interstate_factor` (and `export_competitiveness_state`/
`import_dependency_state`), from the state×state disaggregation
multiplying row counts quadratically (see the row-count math above).
Aggregating `trade.csv` to Sector level bought no size benefit and cost
real fidelity (loses the ~200-industry detail; needs the proportional
splitting machinery for the 16 ambiguous industries; needs its own `-lg`
tier) for files that didn't need any of it.

**Reverted:** `trade.py` no longer aggregates `trade.csv`/`trade_factor.csv`
to Sector level at all — they're always full Exiobase `industry1`/
`industry2` detail (a single tier again, no `-lg` split for these two
files; `aggregate_to_sector()`/`trade_id_map` removed from `trade.py`
entirely). `bea/main.py`'s `_analyze_state_domestic_flows` no longer
decides whether to aggregate `interstate` to Sector based on whether a
`trade-lg.csv` sibling exists (it never will again) — it now always reads
`trade.csv` (full detail) and always aggregates `interstate`/
`interstate_factor`/`export_competitiveness_state`/
`import_dependency_state` to Sector level for the primary output, writing
full detail to their `-lg` siblings as before. `team/src/main.rs`: `trade`'s
`sector1`/`sector2` renamed back to `industry1`/`industry2`, FK back to
`industry(industry_id)`; `interstate` is unchanged (`sector1`/`sector2` →
`sector(sector_id)`). `index.html`'s schema preview updated to match.

**Distinct from the pre-existing underscore `_lg` convention** — worth
restating since both now coexist on `interstate`'s side: `trade_factor_lg.csv`/
`interstate_factor_lg.csv` (underscore, predates this whole industry-
classification effort, driven by `trade.py`'s `-lag`/`--large` flag) mean
"all 721 raw, unaggregated factors" instead of the ~10 EPA-style aggregated
flows — an orthogonal axis (factor count, not industry granularity) that
this revision doesn't touch at all.

## Phase 2 (long-term): full BEA Detail (405-411) EPA-value matching

Re-key through the same Exiobase→USEEIO-Detail concordance **without**
collapsing to Summary, so factor levels are computed per BEA Detail code —
directly comparable to EPA's own `US_detail_import_factors_*.csv` output.
Requires:

- The same many-to-many weighting question as Phase 1, at finer grain.
- A real weighting source for the many-to-many splits (EPA uses BEA import
  data by MRIO country per `generate_import_shares.py`; we'd need an
  equivalent, or accept unweighted splits as a documented approximation).
- Revisiting the currency gap (Euros vs. USD, see `bea/README.md`'s TO DO) —
  matching EPA's literal published values needs both fixes together, not
  either alone.
- Deciding whether Phase 2 output is a third file tier (raw Exiobase-industry
  `-lg`, BEA Summary primary, BEA Detail as a fourth/EPA-comparison file) or
  replaces the Phase 1 primary output outright.

Not started. This document exists to scope it, per the discussion in this
repo's exiobase/tradeflow session notes — implementation is a separate,
larger effort than Phase 1.
