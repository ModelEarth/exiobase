# TradeFlow Plan

Current schema, pipeline, and API are documented in README.md and bea/README.md.
This file is only for what's still open.

## Open work

- **BEA Detail-level matching (Phase 2, not started).** EPA publishes import
  factors at BEA's Detail level (~405-411 industries). Ours use Exiobase's own
  ~200-industry grain internally, aggregated only to BEA Sector (~21
  categories) for interstate's primary output — not re-keyed through the
  full Exiobase→USEEIO-Detail concordance the way EPA's own
  **import_emission_factors** pipeline is. Doing that would let our levels
  compare directly against EPA's own detail-level output. Needs a real
  import-share weighting source for the many-to-many splits (EPA weights by
  BEA import data per MRIO country; we don't have an equivalent yet) and the
  currency fix below.
- **Currency.** `trade.amount`/`interstate.amount` stay in Euros; EPA's own
  pipeline converts to USD by year. No lookup wired in yet.
- **trade_price_indices.csv is empty.** Either populate it from BEA's
  Import/Export Price Index API, or document why it stays empty.
- **BEA sample dashboard** (trade-data/bea-dashboard/) still references
  column names from before the interstate/sector rename.

## Longer-term ideas (not started)

- Dataset profiling and change detection on every import — schema, row
  counts, nulls, duplicates, orphaned foreign keys — stored per year/run so
  runs can be compared over time.
- A public read-only API over the Industry Database, rate-limited, for the
  TradeFlow UI and other consumers.
- Multi-year forecasting, once enough years are loaded (the pipeline
  processes one configured year per run today).

## Background: why industry classification changed

Our own ~200-code industry classification (Exiobase's raw sectors) was never
reconciled with BEA's official classifications (Detail ~405-411, Summary
~71-73, Sector ~21) that EPA's own process publishes against. Two separate
problems came from that:

1. **File size** — the state×state disaggregation in interstate/
   interstate_factor multiplied the ~200-industry grain into multi-GB files.
2. **Comparing values to EPA** — factor levels were keyed on our own codes,
   not BEA's, so nothing lined up industry-for-industry with EPA's published
   numbers.

The **Sector** level (~21 categories, the coarsest BEA tier) isn't in either
of the EPA-published concordance files we already had
(`exio_to_useeio2_commodity_concordance.csv`,
`useeio_internal_concordance.csv`, both auto-fetched into
`trade-data/concordance/`). The authoritative source is BEA's own Supply-Use
publication — confirmed by reading `useeior`'s build scripts
([cornerstone-data/useeior](https://github.com/cornerstone-data/useeior)):

> BEA Supply-Use Table framework file, "NAICS Codes" sheet
> `https://apps.bea.gov/industry/release/zip/SUPPLY-USE.zip` →
> `Use_SUT_Framework_{year}_DET.xlsx`

Parsed once into `trade-data/concordance/bea_summary_to_sector_concordance.csv`
(73 Summary codes → 23 Sector codes), chained with the two files above in
`exiobase_industry.py`.

Both concordance hops are **many-to-many** (a single Exiobase sector can map
to more than one USEEIO Detail code, and 16 of the 200 Exiobase industries
chain to more than one candidate BEA Sector). Collapsing this needed weighted
aggregation, not a simple relabel — see README.md's schema notes for how
`sector_industry.weight` handles it, mirroring EPA's own
`generate_import_factors.py` `get_weighted_average()` in spirit (weighted by
Detail-code count rather than real import-share quantity, which we don't
have — see Phase 2 above).

**The 21 BEA Sector categories:**

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

(Plus "Used" and "Other" adjustment rows in sector.csv.) 21 was chosen over
`useeior`'s further-aggregated 15-code tier: most of those merges collapse
distinctions Exiobase's own sectors already respect cleanly, so keeping them
split costs nothing. The one awkward boundary is 31ND vs. 33DG (durable vs.
nondurable manufacturing) — a BEA accounting split that doesn't match how
Exiobase organizes manufacturing (by material/process, not durability), but
it's resolvable through the Detail-level concordance chain regardless.

Only `interstate`/`interstate_factor` (and the export/import state analysis
files that read from them) ended up aggregated to Sector level — `trade`/
`trade_factor` were never the file-size problem (well under 1.5MB even at
full industry detail) and stayed at Exiobase's native grain. See README.md
for the current split.
