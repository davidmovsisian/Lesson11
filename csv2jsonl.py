"""
Convert THE World University Rankings CSV to JSONL format.

Each output line is a self-contained JSON record for one university-year entry,
ready for ingestion into a vector store or knowledge base.
"""

import json
import math
import pandas as pd

INPUT_CSV  = "the-world-university-rankings-2016-2026.csv"
OUTPUT_JSONL = "the_rankings2.jsonl"


def clean_value(val):
    """Convert NaN / numpy scalars to plain Python types."""
    if isinstance(val, float) and math.isnan(val):
        return None
    # numpy int/float → native Python
    if hasattr(val, "item"):
        return val.item()
    return val


def row_to_record(row: pd.Series) -> dict:
    """Map a DataFrame row to a clean dict."""
    return {
        "year":                   clean_value(row["Year"]),
        "rank":                   clean_value(row["Rank"]),
        "name":                   clean_value(row["Name"]),
        "country":                clean_value(row["Country"]),
        "student_population":     clean_value(row["Student Population"]),
        "students_to_staff_ratio":clean_value(row["Students to Staff Ratio"]),
        "international_students": clean_value(row["International Students"]),
        "female_to_male_ratio":   clean_value(row["Female to Male Ratio"]),
        "overall_score":          clean_value(row["Overall Score"]),
        "teaching":               clean_value(row["Teaching"]),
        "research_environment":   clean_value(row["Research Environment"]),
        "research_quality":       clean_value(row["Research Quality"]),
        "industry_impact":        clean_value(row["Industry Impact"]),
        "international_outlook":  clean_value(row["International Outlook"]),
    }


def main():
    print(f"Reading {INPUT_CSV} …")
    df = pd.read_csv(INPUT_CSV)
    print(f"  {len(df):,} rows × {len(df.columns)} columns")

    written = 0
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            if row["Rank"] <= 100:
                record = row_to_record(row)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1

    print(f"Done — {written:,} records written to {OUTPUT_JSONL}")


if __name__ == "__main__":
    main()