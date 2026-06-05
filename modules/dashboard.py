import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import json

COLORS = {
    "purple": "#534AB7",
    "green":  "#1D9E75",
    "red":    "#E24B4A",
    "blue":   "#185FA5",
    "orange": "#E8822A",
    "teal":   "#0891B2",
    "pink":   "#C026D3",
}
PALETTE = list(COLORS.values())

# Columns to skip — not useful for analysis
SKIP_COLS = {
    "id","index","idx","row","rowid","row_id",
    "no","num","number","sr","sno","s_no",
    "unnamed","unnamed: 0","key","pk","uuid",
}

def is_skip_col(col):
    return col.lower().strip() in SKIP_COLS or \
           col.lower().startswith("unnamed")

def get_useful_numeric_cols(df, max_cols=6):
    num_cols = df.select_dtypes(include="number").columns.tolist()
    useful   = [c for c in num_cols if not is_skip_col(c)]
    return useful[:max_cols]

def get_useful_text_cols(df, max_cols=4):
    txt_cols = df.select_dtypes(include="object").columns.tolist()
    useful   = [c for c in txt_cols if not is_skip_col(c)]
    return useful[:max_cols]

def base_layout(title=""):
    return dict(
        title=dict(text=title, font=dict(size=13)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=44, r=20, b=48, l=52),
        font=dict(size=12),
        xaxis=dict(
            gridcolor="rgba(150,150,150,0.15)",
            zerolinecolor="rgba(150,150,150,0.2)",
        ),
        yaxis=dict(
            gridcolor="rgba(150,150,150,0.15)",
            zerolinecolor="rgba(150,150,150,0.2)",
        ),
    )

def run_dashboard(df, sentiment_stats):
    charts = {}

    num_cols = get_useful_numeric_cols(df)
    txt_cols = get_useful_text_cols(df)

    # ── Sentiment bar ──────────────────────────────────────
    if sentiment_stats.get("available"):
        fig = go.Figure(go.Bar(
            x=["Positive", "Neutral", "Negative"],
            y=[sentiment_stats["positive_pct"],
               sentiment_stats["neutral_pct"],
               sentiment_stats["negative_pct"]],
            marker_color=[COLORS["green"],
                          COLORS["purple"],
                          COLORS["red"]],
            text=[str(sentiment_stats["positive_pct"]) + "%",
                  str(sentiment_stats["neutral_pct"])  + "%",
                  str(sentiment_stats["negative_pct"]) + "%"],
            textposition="auto",
        ))
        lay = base_layout("Sentiment Distribution")
        fig.update_layout(**lay)
        charts["sentiment_bar"] = fig.to_json()

        # Donut
        fig2 = go.Figure(go.Pie(
            labels=["Positive", "Neutral", "Negative"],
            values=[sentiment_stats["positive"],
                    sentiment_stats["neutral"],
                    sentiment_stats["negative"]],
            marker_colors=[COLORS["green"],
                           COLORS["purple"],
                           COLORS["red"]],
            hole=0.5,
            textinfo="label+percent",
        ))
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20,r=20,b=20,l=20),
            showlegend=True,
        )
        charts["sentiment_donut"] = fig2.to_json()

    # ── Distribution histogram (skip id cols) ──────────────
    if num_cols:
        # Pick best column: highest std/mean ratio
        best_col = num_cols[0]
        best_ratio = 0
        for c in num_cols:
            mn = df[c].mean()
            if mn and mn != 0:
                ratio = df[c].std() / abs(mn)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_col   = c

        fig3 = px.histogram(
            df, x=best_col, nbins=25,
            color_discrete_sequence=[COLORS["purple"]],
        )
        fig3.update_traces(opacity=0.85)
        lay3 = base_layout(f"Distribution of {best_col}")
        fig3.update_layout(**lay3)
        charts["distribution"] = fig3.to_json()

    # ── Box plots (useful numeric only) ───────────────────
    if num_cols:
        fig_box = go.Figure()
        for i, col in enumerate(num_cols[:5]):
            fig_box.add_trace(go.Box(
                y=df[col].dropna(),
                name=col,
                marker_color=PALETTE[i % len(PALETTE)],
                boxmean=True,
                line_width=2,
            ))
        lay_box = base_layout("Box Plots - Outlier Detection")
        lay_box["xaxis"] = dict(
            gridcolor="rgba(150,150,150,0.15)")
        fig_box.update_layout(**lay_box)
        charts["boxplot"] = fig_box.to_json()

    # ── Correlation heatmap ────────────────────────────────
    if len(num_cols) > 1:
        corr = df[num_cols].corr().round(2)
        fig4 = px.imshow(
            corr,
            color_continuous_scale=[
                [0.0, "#E24B4A"],
                [0.5, "#F5F5F7"],
                [1.0, "#534AB7"],
            ],
            aspect="auto",
            text_auto=True,
            zmin=-1, zmax=1,
        )
        fig4.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=30,r=20,b=40,l=80),
            title=dict(
                text="Correlation Heatmap",
                font=dict(size=13)),
            font=dict(size=11),
        )
        charts["heatmap"] = fig4.to_json()

    # ── Scatter plot (best 2 numeric cols) ────────────────
    if len(num_cols) >= 2:
        # Find 2 most correlated useful columns
        col_x = num_cols[0]
        col_y = num_cols[1]

        # Try to find better pair
        if len(num_cols) > 2:
            corr_m = df[num_cols].corr().abs()
            best_corr = 0
            for i in range(len(num_cols)):
                for j in range(i+1, len(num_cols)):
                    c = corr_m.iloc[i,j]
                    if 0.1 < c < 0.99 and c > best_corr:
                        best_corr = c
                        col_x = num_cols[i]
                        col_y = num_cols[j]

        color_col = None
        if (sentiment_stats.get("available") and
                "vader_label" in df.columns):
            color_col = "vader_label"

        fig5 = px.scatter(
            df, x=col_x, y=col_y,
            color=color_col,
            color_discrete_map={
                "Positive": COLORS["green"],
                "Neutral":  COLORS["purple"],
                "Negative": COLORS["red"],
            },
            opacity=0.7,
            trendline="ols" if not color_col else None,
        )
        lay5 = base_layout(f"{col_x} vs {col_y}")
        fig5.update_layout(**lay5)
        charts["scatter"] = fig5.to_json()

    # ── Time series ────────────────────────────────────────
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            try:
                temp = df.copy()
                temp["_date"] = pd.to_datetime(
                    temp[col], errors="coerce")
                temp = temp.dropna(subset=["_date"])
                temp = temp.sort_values("_date")

                if (sentiment_stats.get("available") and
                        "vader_label" in temp.columns):
                    ts = temp.groupby(
                        [temp["_date"].dt.to_period("M"),
                         "vader_label"]
                    ).size().reset_index(name="count")
                    ts["_date"] = ts["_date"].astype(str)
                    fig_ts = px.line(
                        ts, x="_date", y="count",
                        color="vader_label",
                        color_discrete_map={
                            "Positive": COLORS["green"],
                            "Neutral":  COLORS["purple"],
                            "Negative": COLORS["red"],
                        },
                        markers=True,
                    )
                else:
                    ts = temp.groupby(
                        temp["_date"].dt.to_period("M")
                    ).size().reset_index(name="count")
                    ts["_date"] = ts["_date"].astype(str)
                    fig_ts = px.line(
                        ts, x="_date", y="count",
                        color_discrete_sequence=[
                            COLORS["purple"]],
                        markers=True,
                    )

                lay_ts = base_layout(
                    "Sentiment Trend Over Time")
                fig_ts.update_layout(**lay_ts)
                charts["timeseries"] = fig_ts.to_json()
                break
            except Exception as e:
                print(f"Timeseries error: {e}")

    # ── Category bar (useful text col) ────────────────────
    for col in txt_cols:
        vc = df[col].value_counts().head(10)
        if 2 <= len(vc) <= 25:
            fig6 = px.bar(
                x=vc.values,
                y=vc.index.astype(str),
                orientation="h",
                color_discrete_sequence=[COLORS["blue"]],
            )
            fig6.update_traces(opacity=0.85)
            lay6 = base_layout(f"Top Categories - {col}")
            lay6["yaxis"] = dict(
                autorange="reversed",
                gridcolor="rgba(150,150,150,0.15)")
            fig6.update_layout(**lay6)
            charts["category_bar"] = fig6.to_json()
            break

    # ── Radar chart for model comparison ──────────────────
    ml = sentiment_stats.get("ml", {})
    if ml.get("available") and ml.get("model_results"):
        cats = ["Accuracy","Precision","Recall",
                "F1","CV Mean"]
        fig_r = go.Figure()
        colors_list = list(COLORS.values())
        for i, (name, res) in enumerate(
                ml["model_results"].items()):
            if "error" in res:
                continue
            vals = [
                res.get("accuracy",  0),
                res.get("precision", 0),
                res.get("recall",    0),
                res.get("f1",        0),
                res.get("cv_mean",   0) or 0,
            ]
            fig_r.add_trace(go.Scatterpolar(
                r=vals + [vals[0]],
                theta=cats + [cats[0]],
                fill="toself",
                name=name,
                line_color=colors_list[i%len(colors_list)],
                opacity=0.75,
            ))
        fig_r.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=30,r=30,b=30,l=30),
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    gridcolor="rgba(150,150,150,0.2)",
                ),
                angularaxis=dict(
                    gridcolor="rgba(150,150,150,0.2)",
                ),
            ),
            showlegend=True,
            title=dict(
                text="Model Performance Radar",
                font=dict(size=13)),
        )
        charts["radar"] = fig_r.to_json()
      # Add placeholder for missing charts
    expected_charts = {

        "distribution", "scatter", "boxplot",
        "sentiment_bar", "sentiment_donut"
        }
    for chart_name in expected_charts:

        if chart_name not in charts:

            # Return empty figure instead of None
            empty_fig = go.Figure().add_annotation(
                text="No data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False)
            charts[chart_name] = empty_fig.to_json()  

    return charts