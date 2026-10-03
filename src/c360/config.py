"""Project-wide paths and constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_ZIP = ROOT / "data" / "raw" / "archive.zip"
RAW_MEMBER = "bank_transactions.csv"
SQL_DIR = ROOT / "sql"
EXPORT_DIR = ROOT / "data" / "exports"
OUTPUT_DIR = ROOT / "outputs"
FIG_DIR = OUTPUT_DIR / "figures"
SITE_DIR = ROOT / "docs"

# Observation window. The file runs to 21 Oct 2016 but daily coverage is only
# complete to 15 Sep, so behaviour is analysed on 1 Aug - 15 Sep [A].
# Must match the project_params table in sql/00_schema.sql.
WINDOW_START = "2016-08-01"
WINDOW_END = "2016-09-15"
AS_OF_DATE = "2016-09-16"
WINDOW_DAYS = 46

RANDOM_SEED = 42
