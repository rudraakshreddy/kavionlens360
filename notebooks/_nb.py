"""Tiny helper to author notebooks as Python lists of cells (kept in the repo for transparency)."""
import nbformat as nbf


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip("\n"))


def code(text: str):
    return nbf.v4.new_code_cell(text.strip("\n"))


def write(path, cells):
    nb = nbf.v4.new_notebook()
    nb["cells"] = cells
    nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nbf.write(nb, path)


SETUP = code("""
import sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from c360 import db, viz
from c360.config import FIG_DIR
viz.apply_style()
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 50)
""")
