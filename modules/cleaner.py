import pandas as pd
import numpy as np
import os, uuid, re
from pathlib import Path

# Resolve the uploads directory relative to this module's parent (project root)
_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"


SAMPLE_THRESHOLD = 10000
SAMPLE_SIZE      = 5000

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
        df[col] = df[col].astype(str).str.strip()
        df[col].replace(
            {"nan":"","None":"","NaN":"","NULL":""},
            inplace=True)

    for col in df.select_dtypes(include="number").columns:
        df[col].fillna(df[col].median(), inplace=True)

    for col in df.select_dtypes(include="object").columns:
        df[col].fillna("", inplace=True)

    date_cols = []
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(20)
        hits   = 0
        for val in sample:
            try:
                pd.to_datetime(str(val))
                hits += 1
            except Exception:
                pass
        if hits >= len(sample) * 0.7:
            try:
                df[col] = pd.to_datetime(
                    df[col], errors="coerce")
                date_cols.append(col)
            except Exception:
                pass

    clean_filename = "cleaned_" + str(uuid.uuid4())[:8] + ".csv"
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    clean_path     = str(_UPLOAD_DIR / clean_filename)
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