import os
import datetime
from fpdf import FPDF
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_DIR   = _PROJECT_ROOT / "static" / "outputs"


class LumiqPDF(FPDF):
    def header(self):
        self.set_fill_color(83, 74, 183)
        self.rect(0, 0, 210, 18, "F")
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(255, 255, 255)
        self.set_xy(10, 4)
        self.cell(0, 10, "Lumiq - AI Data Analysis Report",
                  ln=False)
        self.set_font("Helvetica", "", 8)
        self.set_xy(140, 6)
        self.cell(0, 6,
                  datetime.datetime.now().strftime(
                      "%d %b %Y %H:%M"),
                  ln=False)
        self.set_text_color(0, 0, 0)
        self.ln(18)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8,
                  "Lumiq AI  |  Page " + str(self.page_no()),
                  align="C")

    def section(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(238, 237, 254)
        self.set_text_color(83, 74, 183)
        self.cell(0, 9, "  " + title, ln=True, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def row(self, label, value, shade=False):
        self.set_font("Helvetica", "", 9)
        if shade:
            self.set_fill_color(248, 248, 252)
        else:
            self.set_fill_color(255, 255, 255)
        self.cell(80, 7, self.safe(str(label)),
                  border=0, fill=True)
        self.set_font("Helvetica", "B", 9)
        self.cell(0,  7, self.safe(str(value)),
                  border=0, fill=True, ln=True)

    def safe(self, text):
        """Replace special characters not supported by Helvetica."""
        replacements = {
            "\u2014": "-",   # em dash
            "\u2013": "-",   # en dash
            "\u2018": "'",   # left single quote
            "\u2019": "'",   # right single quote
            "\u201c": '"',   # left double quote
            "\u201d": '"',   # right double quote
            "\u2022": "*",   # bullet
            "\u00b1": "+/-", # plus minus
            "\u00d7": "x",   # multiplication
            "\u00f7": "/",   # division
            "\u2026": "...", # ellipsis
            "\u00a0": " ",   # non-breaking space
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        # Remove any remaining non-latin characters
        result = ""
        for ch in text:
            if ord(ch) < 256:
                result += ch
            else:
                result += "?"
        return result


def generate_pdf(filename, eda_stats,
                 sentiment_stats, insights):
    pdf = LumiqPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    # ── Overview ──────────────────────────────────────────
    pdf.section("Dataset Overview")
    pairs = [
        ("File",              pdf.safe(str(filename))),
        ("Total Rows",        str(eda_stats.get(
                                  "total_rows") or 0)),
        ("Total Columns",     str(eda_stats.get(
                                  "total_cols") or 0)),
        ("Numeric Columns",   str(eda_stats.get(
                                  "numeric_cols") or 0)),
        ("Text Columns",      str(eda_stats.get(
                                  "text_cols") or 0)),
        ("Missing Data",      str(eda_stats.get(
                                  "missing_pct") or 0) + "%"),
        ("Duplicates Removed",str(eda_stats.get(
                                  "dupes_removed") or 0)),
    ]
    for i, (k, v) in enumerate(pairs):
        pdf.row(k, v, shade=bool(i % 2))
    pdf.ln(4)

    # ── Numeric summary ───────────────────────────────────
    num = eda_stats.get("numeric_summary") or {}
    if num:
        pdf.section("Numeric Summary")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(83, 74, 183)
        pdf.set_text_color(255, 255, 255)
        headers = ["Column", "Mean", "Median",
                   "Std", "Min", "Max", "Outliers"]
        for h in headers:
            pdf.cell(26, 7, h, border=1, fill=True)
        pdf.ln()
        pdf.set_text_color(0, 0, 0)
        for i, (col, s) in enumerate(num.items()):
            shade = bool(i % 2)
            if shade:
                pdf.set_fill_color(248, 248, 252)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 8)
            vals = [
                pdf.safe(str(col)[:14]),
                str(s.get("mean",     "")),
                str(s.get("median",   "")),
                str(s.get("std",      "")),
                str(s.get("min",      "")),
                str(s.get("max",      "")),
                str(s.get("outliers", "")),
            ]
            for val in vals:
                pdf.cell(26, 6, val, border=1, fill=shade)
            pdf.ln()
        pdf.ln(4)

    # ── Sentiment ─────────────────────────────────────────
    if sentiment_stats.get("available"):
        pdf.section("Sentiment Analysis")
        s_pairs = [
            ("Text Column",
             pdf.safe(str(sentiment_stats.get(
                 "text_column", "N/A")))),
            ("Total Samples",
             str(sentiment_stats.get("total_samples", 0))),
            ("Positive",
             str(sentiment_stats.get("positive_pct", 0)) + "%"),
            ("Negative",
             str(sentiment_stats.get("negative_pct", 0)) + "%"),
            ("Neutral",
             str(sentiment_stats.get("neutral_pct",  0)) + "%"),
        ]
        for i, (k, v) in enumerate(s_pairs):
            pdf.row(k, v, shade=bool(i % 2))
        pdf.ln(4)

        ml = sentiment_stats.get("ml") or {}
        if ml.get("available"):
            pdf.section("ML Model Results")
            ml_pairs = [
                ("Best Model",
                 pdf.safe(str(ml.get("best_model", "N/A")))),
                ("Accuracy",
                 str(ml.get("best_accuracy", 0)) + "%"),
                ("F1 Score",
                 str(ml.get("best_f1", 0)) + "%"),
                ("CV Mean",
                 str(ml.get("cv_mean", 0)) + "%"),
                ("CV Std",
                 "+/- " + str(ml.get("cv_std", 0)) + "%"),
                ("Train Size",
                 str(ml.get("train_size", "N/A"))),
                ("Test Size",
                 str(ml.get("test_size", "N/A"))),
                ("Total Models Trained",
                 str(ml.get("total_models", 0))),
            ]
            for i, (k, v) in enumerate(ml_pairs):
                pdf.row(k, v, shade=bool(i % 2))
            pdf.ln(4)

            # Model comparison table
            model_results = ml.get("model_results", {})
            if model_results:
                pdf.section("Model Comparison Table")
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_fill_color(83, 74, 183)
                pdf.set_text_color(255, 255, 255)
                col_headers = [
                    "Model", "Acc%", "Prec%",
                    "Rec%", "F1%", "CV%", "Time(s)"
                ]
                col_widths = [48, 20, 20, 20, 20, 20, 22]
                for h, w in zip(col_headers, col_widths):
                    pdf.cell(w, 7, h, border=1, fill=True)
                pdf.ln()
                pdf.set_text_color(0, 0, 0)
                for i, (mname, mres) in enumerate(
                        model_results.items()):
                    shade = bool(i % 2)
                    if shade:
                        pdf.set_fill_color(248, 248, 252)
                    else:
                        pdf.set_fill_color(255, 255, 255)
                    pdf.set_font("Helvetica", "", 8)
                    if mres.get("error"):
                        row_vals = [
                            pdf.safe(mname[:20]),
                            "ERR", "ERR", "ERR",
                            "ERR", "ERR", "ERR"
                        ]
                    else:
                        row_vals = [
                            pdf.safe(mname[:20]),
                            str(mres.get("accuracy",  "")),
                            str(mres.get("precision", "")),
                            str(mres.get("recall",    "")),
                            str(mres.get("f1",        "")),
                            str(mres.get("cv_mean",   "")),
                            str(mres.get(
                                "train_time_sec", "")),
                        ]
                    for val, w in zip(row_vals, col_widths):
                        pdf.cell(w, 6, val,
                                 border=1, fill=shade)
                    pdf.ln()
                pdf.ln(4)

    # ── AI Insights ───────────────────────────────────────
    if insights:
        pdf.section("AI-Generated Insights")
        for ins in insights:
            pdf.set_font("Helvetica", "B", 9)
            title = pdf.safe(ins.get("title", ""))
            pdf.cell(0, 6, "* " + title, ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            text = pdf.safe(ins.get("text", ""))
            pdf.multi_cell(0, 5, "  " + text)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)

    # ── Save ──────────────────────────────────────────────
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = str(_OUTPUT_DIR / "lumiq_report.pdf")
    pdf.output(out_path)
    return out_path