#!/usr/bin/env python3
"""
Flask API for the tradeflow Insert Data UI.

Endpoints:
  POST /insert  { year, country, flow_type }  -> insert result JSON
  GET  /schema                                 -> table row counts

Start:
  python api.py          (port 5002)
  PORT=8000 python api.py
"""

import os
import time

import psycopg2
from flask import Flask, jsonify, request
from flask_cors import CORS

from insert_pipeline import insert_trade_data

app = Flask(__name__)
CORS(app)


def _get_conn():
    return psycopg2.connect(
        host=os.environ["EXIOBASE_HOST"],
        port=int(os.environ.get("EXIOBASE_PORT", 5432)),
        dbname=os.environ["EXIOBASE_NAME"],
        user=os.environ["EXIOBASE_USER"],
        password=os.environ["EXIOBASE_PASSWORD"],
        sslmode=os.environ.get("EXIOBASE_SSL_MODE", "require"),
    )


@app.post("/insert")
def insert():
    body = request.get_json(force=True, silent=True) or {}
    year = body.get("year")
    country = body.get("country", "").strip().upper()
    flow_type = body.get("flow_type", "").strip().lower()

    if not year:
        return jsonify({"error": "year is required"}), 400
    try:
        year = int(year)
    except (ValueError, TypeError):
        return jsonify({"error": "year must be a number"}), 400

    if not country or len(country) != 2 or not country.isalpha():
        return jsonify({"error": "country must be a 2-letter code (e.g. US)"}), 400

    if flow_type not in ("domestic", "imports", "exports"):
        return jsonify({"error": "flow_type must be domestic, imports, or exports"}), 400

    start = time.time()
    try:
        result = insert_trade_data(year, country, flow_type)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    elapsed = round(time.time() - start, 1)

    if result.errors:
        return jsonify({"error": result.errors[0]}), 400

    return jsonify({
        "year": year,
        "country": country,
        "flow_type": flow_type,
        "rows_inserted": result.rows_inserted,
        "rows_skipped": result.rows_skipped,
        "elapsed_seconds": elapsed,
    })


@app.get("/schema")
def schema():
    tables = ["factor", "industry", "trade", "trade_factor", "trade_impact"]
    try:
        conn = _get_conn()
        counts = {}
        with conn.cursor() as cur:
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    counts[t] = cur.fetchone()[0]
                except Exception:
                    counts[t] = None
        conn.close()
        return jsonify({"tables": counts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    print(f"Starting tradeflow API on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
