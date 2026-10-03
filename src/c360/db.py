"""Database helpers: connection from .env, running SQL files, reading tables."""
import os
import time
from contextlib import contextmanager

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from .config import ROOT, SQL_DIR

load_dotenv(ROOT / ".env")


def _params():
    return dict(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", 5432)),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname=os.environ["PGDATABASE"],
    )


@contextmanager
def connect():
    conn = psycopg2.connect(**_params())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        p = _params()
        url = f"postgresql+psycopg2://{p['user']}:{p['password']}@{p['host']}:{p['port']}/{p['dbname']}"
        _ENGINE = create_engine(url)
    return _ENGINE


def run_sql_file(name: str) -> float:
    """Execute one SQL script from sql/ in a single transaction; return seconds taken."""
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    start = time.perf_counter()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
    return time.perf_counter() - start


def query(sql: str, params=None) -> pd.DataFrame:
    with engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)


def scalar(sql: str, params=None):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def write_df(df: pd.DataFrame, table: str) -> int:
    """Replace `table` with the contents of df (schema via pandas, rows via fast COPY)."""
    import io

    with engine().begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    df.head(0).to_sql(table, engine(), index=False)
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep=r"\N")
    buf.seek(0)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    with connect() as conn, conn.cursor() as cur:
        cur.copy_expert(f"COPY \"{table}\" ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
    return len(df)
