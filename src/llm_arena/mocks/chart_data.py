"""Synthetic CSV datasets for chart tasks, plus the matplotlib introspection harness.

The harness patches `Figure.savefig` so that whatever figure the model saves is first described
as JSON (series, bars, labels, legend). Evaluators then check chart specs with code instead of
asking a model to look at pixels.
"""

from __future__ import annotations

import csv
import io
import math
import random

SITES = ["Harbor Array", "Ridge Farm", "Valley Roof"]
PRODUCTS = ["Ember", "Lumen", "Nightjar", "Solstice"]


def energy_csv(seed: int = 3) -> str:
    rng = random.Random(seed)
    rows = [["month", "site", "kwh"]]
    for month in range(1, 13):
        season = 1 + 0.6 * math.sin((month - 3) / 12 * 2 * math.pi)
        for index, site in enumerate(SITES):
            rows.append([f"2025-{month:02d}", site, str(round((900 + 300 * index) * season + rng.uniform(-60, 60)))])
    return _to_csv(rows)


def roastery_csv(seed: int = 5) -> str:
    rng = random.Random(seed)
    rows = [["week_start", "product", "units", "revenue_eur"]]
    prices = {"Ember": 11.5, "Lumen": 13.0, "Nightjar": 14.5, "Solstice": 12.0}
    popularity = {"Ember": 1.4, "Lumen": 0.9, "Nightjar": 0.6, "Solstice": 1.1}
    for week in range(52):
        month = 1 + week * 12 // 52
        for product in PRODUCTS:
            units = max(5, round(80 * popularity[product] + rng.gauss(0, 12)))
            rows.append(
                [f"2025-{month:02d}-{1 + (week % 4) * 7:02d}", product, str(units), f"{units * prices[product]:.2f}"]
            )
    return _to_csv(rows)


def weather_sales_csv(seed: int = 11) -> str:
    rng = random.Random(seed)
    rows = [["date", "max_temp_c", "cold_brew_cups"]]
    for day in range(1, 61):
        temperature = rng.uniform(12, 34)
        rows.append(
            [
                f"2025-06-{(day - 1) % 30 + 1:02d}",
                f"{temperature:.1f}",
                str(max(0, round(6 * temperature - 40 + rng.gauss(0, 15)))),
            ]
        )
    return _to_csv(rows)


def _to_csv(rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


INTROSPECTION_PRELUDE = r"""
import json
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

_original_savefig = Figure.savefig

def _describe(fig):
    axes = []
    for ax in fig.get_axes():
        bars = [c for c in ax.containers if type(c).__name__ == "BarContainer"]
        legend = ax.get_legend()
        axes.append({
            "title": ax.get_title(),
            "xlabel": ax.get_xlabel(),
            "ylabel": ax.get_ylabel(),
            "lines": sum(1 for line in ax.get_lines() if len(line.get_xdata()) > 1),
            "bar_groups": len(bars),
            "bars": [[p.get_x(), p.get_y(), p.get_width(), p.get_height()] for c in bars for p in c.patches],
            "bar_orientation": [getattr(c, "orientation", None) for c in bars],
            "scatter_points": sum(len(c.get_offsets()) for c in ax.collections if type(c).__name__ == "PathCollection"),
            "legend": [t.get_text() for t in legend.get_texts()] if legend else [],
            "y_inverted": ax.yaxis_inverted(),
        })
    figure_legends = [t.get_text() for lg in fig.legends for t in lg.get_texts()]
    suptitle = fig._suptitle.get_text() if getattr(fig, "_suptitle", None) else ""
    return {"axes": axes, "figure_legend": figure_legends, "suptitle": suptitle}

def _savefig(self, *args, **kwargs):
    # Introspection must never break the model's own savefig call.
    try:
        with open("figure_spec.json", "w") as handle:
            json.dump(_describe(self), handle, default=lambda value: float(value) if hasattr(value, "__float__") else str(value))
    except Exception as exc:
        print(f"[arena] figure introspection failed: {exc}")
    return _original_savefig(self, *args, **kwargs)

Figure.savefig = _savefig
with open("user_code.py") as _source:
    _code = compile(_source.read(), "user_code.py", "exec")
exec(_code, {"__name__": "__main__"})
"""
