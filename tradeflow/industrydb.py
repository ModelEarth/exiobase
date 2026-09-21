#!/usr/bin/env python3
"""
Direct-to-Azure database access for trade_comprehensive.py. See
PLAN-comprehensive.md's "Database write path" and "Local .csv output for
country folders" sections.

Two targets, picked by the `target` argument on every function below
(default `'year_db'`, matching COMPREHENSIVE.target in config.yaml):

  - 'year_db' (default): the per-year database `{EXIOBASE_NAME}_{year}` --
    the same convention already used for industrydb_2019/2021/2023 (see
    team/src/main.rs's year_database_name/
    init_industry_tables_in_pool). Since the database itself is scoped to
    one year, its `trade`/`trade_factor` tables need no `year` column at
    all -- `trade_id` is a plain per-database sequential value (see
    PLAN-comprehensive.md's "Trade ID scheme").
  - 'industrydb': the shared, multi-year database -- `year` is a real
    column on `trade`/`trade_factor`, and `trade_id` is only unique within
    a given year (not globally), matching the shared schema
    team/src/merge_years.rs's ensure_merge_infra already creates.

Two paths in:
  - trade/trade_factor (the large tables): straight psycopg2 COPY-to-a-temp-
    staging-table, then INSERT ... SELECT ... ON CONFLICT DO NOTHING into the
    real table -- no Rust/HTTP round trip, since these can run to millions
    of rows for a comprehensive year.
  - factor/industry/sector/sector_industry (the small reference tables) and
    schema/database creation itself: POST to team's existing Rust API
    (push_reference_tables), which reuses the existing
    ensure_year_database_exists/init_industry_tables_in_pool/upsert_*_rows
    (or, for 'industrydb', ensure_merge_infra/upsert_factor_rows_merged)
    functions -- the psycopg2 user doesn't have CREATEDB, only team's Rust
    process (via EXIOBASE_PROVISION_* credentials) can create a new
    industrydb_{year} database.

Connection uses the same EXIOBASE_HOST/USER/PASSWORD/PORT/SSL_MODE
environment variables team's Rust backend already uses for this server --
same server, same credentials, just a direct psycopg2 connection instead of
going through the Rust process.
"""

import io
import os

import pandas as pd
import psycopg2
import requests

TEAM_API_BASE = os.environ.get('TEAM_API_BASE', 'http://localhost:8081')

TARGET_YEAR_DB = 'year_db'
TARGET_SHARED = 'industrydb'


class IndustryDbNotConfigured(RuntimeError):
    pass


def year_database_name(year):
    """`{EXIOBASE_NAME}_{year}` -- the same naming convention as
    industrydb_2019/2021/2023 (see team/src/main.rs's year_database_name)."""
    base_name = os.environ.get('EXIOBASE_NAME', '')
    if not base_name:
        raise IndustryDbNotConfigured("EXIOBASE_NAME not set")
    return f"{base_name}_{year}"


def get_connection(year, target=TARGET_YEAR_DB):
    """
    Direct psycopg2 connection to either industrydb_{year} (target='year_db',
    the default) or the shared industrydb (target='industrydb'), using the
    same EXIOBASE_* environment variables team's Rust backend uses for this
    server. Does not create the database if missing -- call
    push_reference_tables(year, ..., target=target) first (it does, via
    Rust's ensure_year_database_exists/ensure_database_exists).
    """
    host = os.environ.get('EXIOBASE_HOST', '')
    user = os.environ.get('EXIOBASE_USER', '')
    password = os.environ.get('EXIOBASE_PASSWORD', '')
    port = os.environ.get('EXIOBASE_PORT', '5432')
    sslmode = os.environ.get('EXIOBASE_SSL_MODE', 'require')
    dbname = os.environ.get('EXIOBASE_NAME', '') if target == TARGET_SHARED else year_database_name(year)

    if not host or not user or not password or not dbname:
        raise IndustryDbNotConfigured(
            "industrydb not configured -- set EXIOBASE_HOST, EXIOBASE_NAME, "
            "EXIOBASE_USER, EXIOBASE_PASSWORD (EXIOBASE_PORT/EXIOBASE_SSL_MODE "
            "optional, default 5432/require)."
        )

    return psycopg2.connect(
        host=host, dbname=dbname, user=user, password=password,
        port=port, sslmode=sslmode,
    )


def push_reference_tables(year, factor_csv_path=None, industry_csv_path=None,
                           sector_csv_path=None, sector_industry_csv_path=None,
                           target=TARGET_YEAR_DB):
    """
    Preflight call to team's Rust API: for target='year_db' (default),
    creates industrydb_{year} if it doesn't already exist and ensures its
    schema exists; for target='industrydb', ensures the shared database's
    schema exists instead. Either way, seeds `region` with all 49 Exiobase
    codes and upserts whichever of the four small reference CSVs are
    supplied. Returns the parsed JSON response (includes "factor_id_map"
    when target='industrydb' -- the old->new factor_id remap needed to
    export a correct local factor.csv; empty for 'year_db', which has
    nothing to remap against).
    """
    def _read(path):
        if path is None:
            return None
        with open(path, 'r') as f:
            return f.read()

    payload = {
        'year': str(year),
        'target': target,
        'factor_csv': _read(factor_csv_path),
        'industry_csv': _read(industry_csv_path),
        'sector_csv': _read(sector_csv_path),
        'sector_industry_csv': _read(sector_industry_csv_path),
    }
    resp = requests.post(
        f"{TEAM_API_BASE}/api/db/comprehensive/push-reference-tables",
        json=payload, timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    if not result.get('success'):
        raise RuntimeError(f"push_reference_tables failed: {result.get('errors')}")
    return result


def _copy_and_upsert(conn, staging_table, staging_ddl_columns, columns, df, insert_sql, insert_params=None):
    """
    Shared COPY-to-a-temp-staging-table-then-INSERT...ON CONFLICT pattern
    behind both push_trade_rows and push_trade_factor_rows: create a session
    temp table, COPY `df[columns]` into it, run `insert_sql` (which selects
    out of that staging table into the real one), then commit. Returns
    cur.rowcount from insert_sql (rows actually inserted, excluding ON
    CONFLICT no-ops).
    """
    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE {staging_table} ({staging_ddl_columns}) ON COMMIT DROP")

        buf = io.StringIO()
        df[columns].to_csv(buf, index=False, header=False)
        buf.seek(0)
        cur.copy_expert(f"COPY {staging_table} ({', '.join(columns)}) FROM STDIN WITH CSV", buf)

        cur.execute(insert_sql, insert_params)
        inserted = cur.rowcount

    conn.commit()
    return inserted


def push_trade_rows(conn, trade_df, year=None, target=TARGET_YEAR_DB):
    """
    COPY trade_df (columns: trade_id, region1, region2, industry1,
    industry2, amount, flow_type) into a temp staging table, then
    INSERT ... SELECT ... ON CONFLICT DO NOTHING into `trade` -- mirrors the
    trade_natural_key constraint (plus `year` for target='industrydb', where
    that constraint is per-year), so a retried/resumed run is idempotent.
    `country` is set to region1 (the exporter) -- see
    PLAN-comprehensive.md's "Extraction" section for why there's no separate
    imports/exports distinction to preserve here.

    `year` is required when target='industrydb' (ignored for 'year_db',
    where the database itself is already year-scoped).

    Returns the number of rows actually inserted (excludes ON CONFLICT
    no-ops).
    """
    if trade_df.empty:
        return 0

    if target == TARGET_SHARED:
        insert_sql = """
            INSERT INTO trade (year, trade_id, region1, region2, industry1, industry2, amount, flow_type, country)
            SELECT %s, trade_id, region1, region2, industry1, industry2, amount, flow_type, region1
            FROM _trade_staging
            ON CONFLICT (year, region1, region2, industry1, industry2) DO NOTHING
        """
        insert_params = (year,)
    else:
        insert_sql = """
            INSERT INTO trade (trade_id, region1, region2, industry1, industry2, amount, flow_type, country)
            SELECT trade_id, region1, region2, industry1, industry2, amount, flow_type, region1
            FROM _trade_staging
            ON CONFLICT (region1, region2, industry1, industry2) DO NOTHING
        """
        insert_params = None

    return _copy_and_upsert(
        conn,
        staging_table='_trade_staging',
        staging_ddl_columns="""
            trade_id INTEGER, region1 VARCHAR(10), region2 VARCHAR(10),
            industry1 VARCHAR(10), industry2 VARCHAR(10),
            amount NUMERIC(18,4), flow_type VARCHAR(10)
        """,
        columns=['trade_id', 'region1', 'region2', 'industry1', 'industry2', 'amount', 'flow_type'],
        df=trade_df,
        insert_sql=insert_sql,
        insert_params=insert_params,
    )


def push_trade_factor_rows(conn, trade_factor_df, country, trade_id_flow_type, year=None, target=TARGET_YEAR_DB):
    """
    Same COPY-to-staging-then-INSERT pattern as push_trade_rows, for
    trade_factor (columns: trade_id, factor_id, level). `country` is a
    single value for the whole chunk (the region whose turn this is);
    `flow_type` varies per trade_id ('domestic' vs 'international') and is
    looked up from trade_id_flow_type (a {trade_id: flow_type} dict built
    from the same chunk's trade_df -- see trade_comprehensive.py).

    `year` is required when target='industrydb' (ignored for 'year_db').

    Returns the number of rows actually inserted.
    """
    if trade_factor_df.empty:
        return 0

    df = trade_factor_df.copy()
    df['country'] = country
    df['flow_type'] = df['trade_id'].map(trade_id_flow_type)

    if target == TARGET_SHARED:
        insert_sql = """
            INSERT INTO trade_factor (year, trade_id, country, flow_type, factor_id, level)
            SELECT %s, trade_id, country, flow_type, factor_id, level
            FROM _trade_factor_staging
            ON CONFLICT (year, trade_id, factor_id) DO NOTHING
        """
        insert_params = (year,)
    else:
        insert_sql = """
            INSERT INTO trade_factor (trade_id, country, flow_type, factor_id, level)
            SELECT trade_id, country, flow_type, factor_id, level
            FROM _trade_factor_staging
            ON CONFLICT (trade_id, factor_id) DO NOTHING
        """
        insert_params = None

    return _copy_and_upsert(
        conn,
        staging_table='_trade_factor_staging',
        staging_ddl_columns="""
            trade_id INTEGER, factor_id INTEGER, level NUMERIC(20,6),
            country VARCHAR(10), flow_type VARCHAR(10)
        """,
        columns=['trade_id', 'factor_id', 'level', 'country', 'flow_type'],
        df=df,
        insert_sql=insert_sql,
        insert_params=insert_params,
    )


def pull_trade_rows(conn, region, kind, year=None, target=TARGET_YEAR_DB):
    """
    Export a region's own trade rows back out of industrydb, for the local
    .csv output every in-scope region gets (see PLAN-comprehensive.md's
    "Local .csv output for country folders" section). kind is one of
    'exports', 'domestic', 'imports' -- matching config.yaml's FOLDERS keys.

    'exports'/'domestic' are never actually pulled through this path during
    a comprehensive run itself (they're sliced from the in-memory chunk
    instead, at zero extra cost); this function exists so the same
    mechanism also serves ad-hoc later requests (a country
    COMPREHENSIVE.folders: default excluded, or a genuinely new export) via
    export_country_csvs.py, where no in-memory chunk exists any more.

    `year` is required when target='industrydb' (ignored for 'year_db').

    Returns a DataFrame with columns trade_id, region1, region2, industry1,
    industry2, amount.
    """
    if kind == 'exports':
        where = "region1 = %(country)s AND region2 != %(country)s"
    elif kind == 'domestic':
        where = "region1 = %(country)s AND region2 = %(country)s"
    elif kind == 'imports':
        where = "region2 = %(country)s AND region1 != %(country)s"
    else:
        raise ValueError(f"Unknown kind: {kind}")

    params = {'country': region}
    if target == TARGET_SHARED:
        where = f"year = %(year)s AND {where}"
        params['year'] = year

    query = f"""
        SELECT trade_id, region1, region2, industry1, industry2, amount
        FROM trade
        WHERE {where}
        ORDER BY trade_id
    """
    return pd.read_sql_query(query, conn, params=params)


def pull_trade_factor_rows(conn, trade_ids, year=None, target=TARGET_YEAR_DB):
    """
    Companion to pull_trade_rows -- the trade_factor rows for a given set of
    trade_id values, in the trade_id, factor_id, level column layout
    trade.py's create_trade_factor already writes locally.

    `year` is required when target='industrydb' (ignored for 'year_db').
    """
    if not trade_ids:
        return pd.DataFrame(columns=['trade_id', 'factor_id', 'level'])

    where = "trade_id = ANY(%(trade_ids)s)"
    params = {'trade_ids': list(trade_ids)}
    if target == TARGET_SHARED:
        where = f"year = %(year)s AND {where}"
        params['year'] = year

    query = f"""
        SELECT trade_id, factor_id, level
        FROM trade_factor
        WHERE {where}
        ORDER BY trade_id, factor_id
    """
    return pd.read_sql_query(query, conn, params=params)


def pull_flow(conn, region, kind, year=None, target=TARGET_YEAR_DB):
    """
    pull_trade_rows + pull_trade_factor_rows in one call -- both
    trade_comprehensive.py's post-loop imports pass and
    export_country_csvs.py's per-flow-type loop always want the pair
    together (a flow's trade.csv is never written without its matching
    trade_factor.csv), so this is the one they both call instead of each
    repeating the two-step "pull trade, then pull factor rows for those
    trade_ids" sequence.

    Returns (trade_df, trade_factor_df).
    """
    trade_df = pull_trade_rows(conn, region, kind, year=year, target=target)
    trade_factor_df = pull_trade_factor_rows(conn, set(trade_df['trade_id']), year=year, target=target)
    return trade_df, trade_factor_df


def pull_factor_reference(conn):
    """
    Export industrydb's own `factor` table as a DataFrame with the same four
    columns factors.py's create_factors_csv() writes locally (factor_id,
    unit, stressor, extension) -- see PLAN-comprehensive.md's "local
    factor.csv must also be exported from industrydb.factor" note. `factor`
    has no `year` column in either target, so no year filter is needed here.
    """
    return pd.read_sql_query(
        "SELECT factor_id, unit, stressor, extension FROM factor ORDER BY factor_id", conn,
    )
