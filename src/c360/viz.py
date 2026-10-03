"""Shared chart style (validated reference palette; see docs in README 'Design')."""
import matplotlib as mpl
import matplotlib.pyplot as plt

from .config import FIG_DIR

# Categorical slots in fixed order (never cycled; color follows the entity)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
# Sequential / ordinal blue ramp (ordinal use starts no lighter than step 250)
BLUE = {100: "#cde2fb", 150: "#b7d3f6", 200: "#9ec5f4", 250: "#86b6ef", 300: "#6da7ec", 350: "#5598e7",
        400: "#3987e5", 450: "#2a78d6", 500: "#256abf", 550: "#1c5cab", 600: "#184f95", 650: "#104281",
        700: "#0d366b"}
TIER_COLORS = {"A": BLUE[650], "B": BLUE[500], "C": BLUE[350], "Watch": BLUE[250]}
DIVERGING = ("#2a78d6", "#f0efec", "#e34948")
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"


def apply_style():
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "figure.dpi": 110, "savefig.dpi": 160, "savefig.bbox": "tight",
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 10,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK_2,
        "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlecolor": INK,
        "axes.titlelocation": "left", "axes.titlepad": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
        "axes.axisbelow": True, "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "axes.prop_cycle": mpl.cycler(color=SERIES), "lines.linewidth": 2,
        "legend.frameon": False, "legend.fontsize": 9,
    })


def save(fig, name: str):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def inr(x, _=None):
    """Axis formatter: Indian-style short rupees (K, L, Cr)."""
    a = abs(x)
    if a >= 1e7:
        return f"{x / 1e7:.1f} Cr"
    if a >= 1e5:
        return f"{x / 1e5:.1f} L"
    if a >= 1e3:
        return f"{x / 1e3:.0f}K"
    return f"{x:.0f}"
