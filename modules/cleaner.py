import os
import re
import uuid

import numpy as np
import pandas as pd

SAMPLE_THRESHOLD = 10000
SAMPLE_SIZE = 5000


def _looks_like_date(value):
    try:
        pd.to_datetime(value)
        return True
    except (ValueError, TypeError):
        return False

def clean_data(filepath):
    try:
        df = pd.read_csv(filepath, encoding="utf-8",
                         on_bad_lines="skip")
    except Exception:
        df = pd.read_csv(filepath, encoding="latin-1",
                         on_bad_lines="skip")

    original_rows = len(df)
    was_sampled   = False
    sample_note   = ""

    if original_rows > SAMPLE_THRESHOLD:
        df = df.sample(
            n=SAMPLE_SIZE, random_state=42
        ).reset_index(drop=True)
        was_sampled = True
        sample_note = (
            f"Large file detected ({original_rows:,} rows). "
            f"Analysing a representative sample of "
            f"{SAMPLE_SIZE:,} rows for speed."
        )

    df.dropna(how="all", inplace=True)
    df.dropna(axis=1, how="all", inplace=True)

    dupes = int(df.duplicated().sum())
    df.drop_duplicates(inplace=True)

    for col in df.select_dtypes(include="object").columns:
        df[col] = (
            df[col].astype(str)
            .str.strip()
            .replace({"nan": "", "None": "", "NaN": "", "NULL": ""})
        )

    for col in df.select_dtypes(include="number").columns:
        df[col].fillna(df[col].median(), inplace=True)

    for col in df.select_dtypes(include="object").columns:
        df[col].fillna("", inplace=True)

    date_cols = []
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(20).astype(str)
        hits = sum(1 for val in sample if _looks_like_date(val))
        if sample.empty or hits < len(sample) * 0.7:
            continue
        try:
            df[col] = pd.to_datetime(df[col], errors="coerce")
            date_cols.append(col)
        except Exception:
            pass

    clean_filename = "cleaned_" + str(uuid.uuid4())[:8] + ".csv"
    clean_path     = os.path.join("uploads", clean_filename)
    df.to_csv(clean_path, index=False)

    meta = {
        "original_rows": original_rows,
        "clean_rows":    len(df),
        "dupes_removed": dupes,
        "date_cols":     date_cols,
        "was_sampled":   was_sampled,
        "sample_note":   sample_note,
        "sample_size":   SAMPLE_SIZE if was_sampled else None,
    }

    return df, clean_path, meta