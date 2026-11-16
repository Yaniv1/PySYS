from __future__ import annotations

import datetime as dt
import math
import tempfile
import webbrowser
from html import escape
from numbers import Real
from pathlib import Path

import pandas as pd


def plot_state_history(ts, series, output_dir="results", plot_name="plot"):
    """Plot numeric series against timestamps and return the saved SVG path."""
    ts = list(ts)
    if not ts:
        raise ValueError("No state history is available to plot.")
    if not series:
        raise ValueError("At least one state series is required.")
    if any(not isinstance(t, Real) or not math.isfinite(t) for t in ts):
        raise ValueError("Timestamps must be finite numbers.")
    if any(a > b for a, b in zip(ts, ts[1:])):
        raise ValueError("Timestamps must be in chronological order.")
    data = []
    for name, history in series.items():
        history = list(history)
        if len(history) != len(ts):
            raise ValueError(f"{name} must have one value for each timestamp.")
        points = []
        for t, value in zip(ts, history):
            if not pd.api.types.is_scalar(value):
                raise ValueError(f"{name} must contain numeric values or missing values.")
            if pd.isna(value):
                value = None
            elif not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must contain finite numeric values or missing values.")
            points.append((t, value))
        data.append((name, points))
    return _plot_series(data, "Timestamp (seconds)", "State", "State history",
                        step=True, x_ticks=list(dict.fromkeys(ts)), output_dir=output_dir, plot_name=plot_name)


def plot_df(df, x_column, series_columns, output_dir="results"):
    """Plot numeric dataframe series against a numeric or datetime column.

    Missing series values are gaps. Returns the path of the SVG opened in the browser.
    """
    if isinstance(series_columns, str):
        raise ValueError("series_columns must be a non-empty sequence of column names.")
    series_columns = list(series_columns)
    if not series_columns:
        raise ValueError("series_columns must be a non-empty sequence of column names.")
    if not df.columns.is_unique:
        raise ValueError("Dataframe column names must be unique.")
    missing_columns = [name for name in [x_column, *series_columns] if name not in df.columns]
    if missing_columns:
        raise KeyError(f"Dataframe columns not found: {missing_columns}")
    if df.empty:
        raise ValueError("Cannot plot an empty dataframe.")

    x_values = df[x_column].tolist()
    if any(not pd.api.types.is_scalar(value) for value in x_values):
        raise ValueError(f"{x_column} must contain scalar values.")
    if any(pd.isna(value) for value in x_values):
        raise ValueError(f"{x_column} must not contain missing x values.")
    if all(isinstance(value, (dt.datetime, dt.date)) for value in x_values):
        dates = [pd.Timestamp(value) for value in x_values]
        try:
            origin = min(dates)
            x_values = [(value - origin).total_seconds() for value in dates]
        except TypeError as exc:
            raise ValueError("Datetime x values must have compatible timezones.") from exc
        x_label = f"{x_column} (seconds since {origin.isoformat()})"
        def format_x(value):
            return f"{value:.2f}"
    elif all(isinstance(value, Real) and math.isfinite(value) for value in x_values):
        x_label = str(x_column)
        def format_x(value):
            return f"{value:.8g}"
    else:
        raise ValueError(f"{x_column} must contain finite numeric or datetime values.")

    data = []
    for name in series_columns:
        points = []
        for x, value in zip(x_values, df[name].tolist()):
            if not pd.api.types.is_scalar(value):
                raise ValueError(f"{name} must contain scalar values.")
            if pd.isna(value):
                value = None
            elif not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must contain finite numeric values or missing values.")
            points.append((x, value))
        data.append((name, points))
    return _plot_series(data, x_label, "Value", "Dataframe plot", format_x=format_x,
                        output_dir=output_dir)


def _plot_series(series, x_label, y_label, title, *, step=False, format_x=None, x_ticks=None,
                 output_dir="results", plot_name="plot.png"):
    x_values = [x for _, points in series for x, _ in points]
    values = [value for _, points in series for _, value in points if value is not None]
    xmin, xmax = min(x_values), max(x_values)
    duration = xmax - xmin or 1
    ymin, ymax = (min(values), max(values)) if values else (0, 1)
    if ymin == ymax:
        ymin, ymax = ymin - 1, ymax + 1
    legend_rows = (len(series) + 1) // 2
    left, top, width, height = 90, 56 + 24 * legend_rows, 650, 360
    svg_height = top + height + 90
    colors = ("#1565c0", "#c62828", "#2e7d32", "#6a1b9a", "#ef6c00", "#00695c")
    format_x = format_x or (lambda value: f"{value:.2f}")
    right_margin = 60
    if x_ticks is not None:
        tick_labels = [str(value) for value in x_ticks]
        width = max(width, len(x_ticks) * (max(map(len, tick_labels)) * 7 + 16))
        right_margin = max(right_margin, max(map(len, tick_labels)) * 4 + 8)

    def x_pos(timestamp):
        return left + (timestamp - xmin) / duration * width

    def y_pos(value):
        return top + (ymax - value) / (ymax - ymin) * height

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{left + width + right_margin}" height="{svg_height}" '
        f'viewBox="0 0 {left + width + right_margin} {svg_height}" role="img" aria-label="{escape(title, quote=True)}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="sans-serif" font-size="13" fill="#222">',
        f'<text x="{left + width / 2}" y="30" text-anchor="middle" font-size="20">{escape(title)}</text>',
    ]
    for i in range(6):
        y = top + height * i / 5
        svg.extend([
            f'<path d="M {left} {y:.2f} H {left + width}" '
            'stroke="#ddd" fill="none"/>',
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end">{ymax - (ymax - ymin) * i / 5:.3g}</text>',
        ])
    ticks = ([(value, str(value)) for value in x_ticks] if x_ticks is not None else
             [(xmin + duration * i / 5, format_x(xmin + duration * i / 5)) for i in range(6)])
    for value, label in ticks:
        x = x_pos(value)
        svg.extend([
            f'<path d="M {x:.2f} {top} V {top + height}" stroke="#ddd" fill="none"/>',
            f'<text x="{x:.2f}" y="{top + height + 20}" text-anchor="middle">{escape(label)}</text>',
        ])
    svg.extend([
        f'<rect x="{left}" y="{top}" width="{width}" height="{height}" fill="none" stroke="#333"/>',
        f'<text x="{left + width / 2}" y="{top + height + 60}" text-anchor="middle">{escape(x_label)}</text>',
        f'<text x="22" y="{top + height / 2}" text-anchor="middle" '
        f'transform="rotate(-90 22 {top + height / 2})">{escape(y_label)}</text>',
    ])
    for index, (name, data) in enumerate(series):
        color = colors[index % len(colors)]
        legend_x = 120 + 300 * (index % 2)
        legend_y = 55 + 24 * (index // 2)
        svg.append(f'<path d="M {legend_x} {legend_y} h 24" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<text x="{legend_x + 30}" y="{legend_y + 4}">{escape(str(name))}</text>')
        commands = []
        points = []
        previous = False
        for x_value, value in data:
            if value is None:
                previous = False
                continue
            x, y = x_pos(x_value), y_pos(value)
            if previous:
                commands.append(f"H {x:.2f} V {y:.2f}" if step else f"L {x:.2f} {y:.2f}")
            else:
                commands.append(f"M {x:.2f} {y:.2f}")
            points.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}"/>')
            previous = True
        svg.append(f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" stroke-width="2"/>')
        svg.extend(points)
    if not values:
        svg.append(f'<text x="{left + width / 2}" y="{top + height / 2}" text-anchor="middle">No recorded numeric values</text>')
    svg.append("</g></svg>")

    directory = Path(output_dir/plot_name).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     prefix=plot_name, suffix=".svg", delete=False) as file:
        file.write("\n".join(svg))
        path = Path(file.name)
    print(f"State history plot saved to {path}")
    if not webbrowser.open(path.as_uri()):
        raise RuntimeError(f"Could not open the plot in a browser. Open {path} manually.")
    return path
