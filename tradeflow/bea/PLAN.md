# BEA Integration Plan

Schema work here is done — interstate_id format, dropping the generic
bigserial ids, removing the `bea_` column prefixes, the interstate/sector
rename, and dropping `bea_industry_mapping.csv`. See
[../README.md](../README.md#schema-notes) for the current design.

## Open

- **trade_price_indices.csv is still empty** — see ../PLAN.md.
- **BEA sample dashboard** (../../../trade-data/bea-dashboard/) needs
  updating for the renamed interstate/sector columns.

See ../PLAN.md for longer-term ideas (profiling, a public API,
forecasting) that aren't started yet.
