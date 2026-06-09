def generate_insights(eda_stats, sentiment_stats):
    insights = []

    # ── EDA insights ──────────────────────────────────────
    rows = eda_stats.get("total_rows") or 0
    cols = eda_stats.get("total_cols") or 0
    dupes = eda_stats.get("dupes_removed") or 0
    missing = eda_stats.get("missing_pct") or 0

    insights.append({
        "icon":  "ti-table",
        "color": "purple",
        "title": "Dataset Overview",
        "text":  f"Your dataset has {rows:,} rows and {cols} columns. "
                 f"Lumiq cleaned it automatically.",
    })

    if dupes > 0:
        insights.append({
            "icon":  "ti-copy",
            "color": "orange",
            "title": "Duplicates Removed",
            "text":  f"{dupes} duplicate rows were detected and "
                     f"removed to ensure accurate analysis.",
        })

    if missing > 5:
        insights.append({
            "icon":  "ti-alert-triangle",
            "color": "red",
            "title": "Missing Data Detected",
            "text":  f"{missing}% of your data had missing values. "
                     f"Lumiq filled them using median imputation.",
        })
    elif missing > 0:
        insights.append({
            "icon":  "ti-check",
            "color": "green",
            "title": "Data Quality is Good",
            "text":  f"Only {missing}% missing values found. "
                     f"Your dataset is in great shape.",
        })

    # ── Numeric insights ──────────────────────────────────
    num_summary = eda_stats.get("numeric_summary") or {}
    for col, s in list(num_summary.items())[:2]:
        skew = s.get("skewness", 0)
        out  = s.get("outliers", 0)
        if abs(skew) > 1:
            direction = "right" if skew > 0 else "left"
            insights.append({
                "icon":  "ti-chart-histogram",
                "color": "blue",
                "title": f"{col} is Skewed",
                "text":  f"The '{col}' column is skewed to the "
                         f"{direction} (skewness={skew}). "
                         f"Consider log transformation.",
            })
        if out > 0:
            insights.append({
                "icon":  "ti-point",
                "color": "orange",
                "title": f"Outliers in {col}",
                "text":  f"{out} outliers detected in '{col}' "
                         f"using the IQR method.",
            })

    # ── Sentiment insights ────────────────────────────────
    if sentiment_stats.get("available"):
        pos = sentiment_stats.get("positive_pct") or 0
        neg = sentiment_stats.get("negative_pct") or 0
        neu = sentiment_stats.get("neutral_pct")  or 0
        col = sentiment_stats.get("text_column")  or "text"
        tot = sentiment_stats.get("total_samples") or 0

        if pos >= 60:
            insights.append({
                "icon":  "ti-mood-happy",
                "color": "green",
                "title": "Mostly Positive Sentiment",
                "text":  f"{pos}% of {tot:,} entries in '{col}' "
                         f"are positive. Excellent reception!",
            })
        elif neg >= 40:
            insights.append({
                "icon":  "ti-mood-sad",
                "color": "red",
                "title": "High Negative Sentiment",
                "text":  f"{neg}% of entries are negative. "
                         f"Significant dissatisfaction detected.",
            })
        else:
            insights.append({
                "icon":  "ti-mood-neutral",
                "color": "purple",
                "title": "Mixed Sentiment",
                "text":  f"Positive: {pos}% · Neutral: {neu}% · "
                         f"Negative: {neg}%. Balanced distribution.",
            })

        ml = sentiment_stats.get("ml") or {}
        if ml.get("available"):
            best  = ml.get("best_model", "")
            acc   = ml.get("best_accuracy", 0)
            f1    = ml.get("best_f1", 0)
            cv    = ml.get("cv_mean", 0)
            insights.append({
                "icon":  "ti-trophy",
                "color": "green",
                "title": f"Best Model: {best}",
                "text":  f"Achieved {acc}% accuracy and {f1}% F1 "
                         f"score with {cv}% cross-validation mean.",
            })

        # Keyword insight
        keywords = sentiment_stats.get("keywords") or []
        if keywords:
            top3 = ", ".join(
                f'"{k["word"]}' for k in keywords[:3])
            insights.append({
                "icon":  "ti-key",
                "color": "blue",
                "title": "Top Keywords Found",
                "text":  f"Most important terms: {top3}. "
                         f"These drive the overall sentiment.",
            })

    return insights[:8]   # max 8 insights