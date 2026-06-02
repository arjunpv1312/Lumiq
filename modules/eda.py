import pandas as pd
import numpy as np

def run_eda(df, clean_meta=None):
    stats = {}

    # ── Basic info ────────────────────────────────────────
    stats["total_rows"]    = int(df.shape[0])
    stats["total_cols"]    = int(df.shape[1])
    stats["numeric_cols"]  = int(len(df.select_dtypes(include="number").columns))
    stats["text_cols"]     = int(len(df.select_dtypes(include="object").columns))
    stats["missing_total"] = int(df.isnull().sum().sum())
    stats["missing_pct"]   = round(
        df.isnull().sum().sum() /
        max(df.shape[0] * df.shape[1], 1) * 100, 2)
    stats["columns"]       = list(df.columns)
    stats["dtypes"]        = {c: str(t) for c, t in df.dtypes.items()}
    stats["dupes_removed"] = clean_meta.get("dupes_removed", 0) \
                             if clean_meta else 0
    stats["original_rows"] = clean_meta.get("original_rows", stats["total_rows"]) \
                             if clean_meta else stats["total_rows"]

    # ── Numeric summary ───────────────────────────────────
    numeric_summary = {}
    for col in df.select_dtypes(include="number").columns:
        s = df[col].dropna()
        q1, q3  = float(s.quantile(0.25)), float(s.quantile(0.75))
        iqr     = q3 - q1
        outliers = int(((s < q1 - 1.5*iqr) | (s > q3 + 1.5*iqr)).sum())
        numeric_summary[col] = {
            "mean":     round(float(s.mean()),   2),
            "median":   round(float(s.median()), 2),
            "std":      round(float(s.std()),    2),
            "min":      round(float(s.min()),    2),
            "max":      round(float(s.max()),    2),
            "q1":       round(q1, 2),
            "q3":       round(q3, 2),
            "skewness": round(float(s.skew()),   2),
            "outliers": outliers,
        }
    stats["numeric_summary"] = numeric_summary

    # ── Correlation matrix ────────────────────────────────
    num_df = df.select_dtypes(include="number")
    if len(num_df.columns) > 1:
        corr = num_df.corr().round(3)
        stats["correlation"] = corr.to_dict()
    else:
        stats["correlation"] = {}

    # ── Text column value counts ──────────────────────────
    text_summary = {}
    for col in df.select_dtypes(include="object").columns[:4]:
        counts = df[col].value_counts().head(8)
        text_summary[col] = {
            str(k): int(v) for k, v in counts.items()
            if str(k).strip()
        }
    stats["text_summary"] = text_summary

    # ── Date column detection ─────────────────────────────
    date_cols = []
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            date_cols.append(col)
    stats["date_cols"] = date_cols

    # ── Missing per column ────────────────────────────────
    missing_per_col = df.isnull().sum()
    stats["missing_per_col"] = {
        c: int(v) for c, v in missing_per_col.items() if v > 0
    }

    return stats