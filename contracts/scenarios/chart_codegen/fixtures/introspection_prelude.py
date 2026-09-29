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
        series = [line for line in ax.get_lines() if len(line.get_xdata()) > 1]
        scatter = [c for c in ax.collections if type(c).__name__ == "PathCollection"]
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
            # The plotted data itself, so graders can check that every data point is there with the right value.
            "line_data": [{"label": line.get_label(), "y": [float(v) for v in line.get_ydata()]} for line in series],
            "bar_values": [p.get_width() if getattr(c, "orientation", "vertical") == "horizontal" else p.get_height()
                           for c in bars for p in c.patches],
            "scatter_offsets": [[float(x), float(y)] for c in scatter for x, y in c.get_offsets()][:5000],
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
