"""Ingestion (FR-001, FR-002): stream the raw CSV from the zip into staging as text."""
import hashlib
import io
import zipfile

from .config import RAW_MEMBER, RAW_ZIP
from .db import connect


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_staging(run_id: str) -> int:
    """COPY every CSV row into stg_bank_transactions untouched; log size, hash and count."""
    with zipfile.ZipFile(RAW_ZIP) as zf, connect() as conn, conn.cursor() as cur:
        info = zf.getinfo(RAW_MEMBER)
        with zf.open(RAW_MEMBER) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            cur.copy_expert(
                """COPY stg_bank_transactions
                   (transaction_id, customer_id, customer_dob, cust_gender, cust_location,
                    cust_account_balance, transaction_date, transaction_time, transaction_amount_inr)
                   FROM STDIN WITH (FORMAT csv, HEADER true)""",
                text,
            )
        cur.execute("SELECT COUNT(*) FROM stg_bank_transactions")
        rows = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO load_log (run_id, file_name, archive_sha256, uncompressed_bytes, rows_loaded)
               VALUES (%s, %s, %s, %s, %s)""",
            (run_id, RAW_MEMBER, file_sha256(RAW_ZIP), info.file_size, rows),
        )
    return rows
