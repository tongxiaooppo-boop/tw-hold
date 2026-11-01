"""共用：載入資料、組 baseline（現行 assemble_inputs + classify）。只讀。"""
from __future__ import annotations
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "app"))
import numpy as np
import pandas as pd
import build_classification as bc
from screener import classify as cl, quarterly_prep as qp, rev_index as ri
from reference.loader import load_quarterly

OUT = Path(__file__).resolve().parent
ASOF = pd.Timestamp("2026-06-30")
KEY1 = ["2605","2612","2618","2603","2609","2002","1301","1101","2014","2330","2454","2317","2412","1216","3008","3443"]

def load():
    quarterly = load_quarterly()
    monthly = pd.read_parquet(bc.REVENUE)
    universe = pd.read_parquet(bc.UNIVERSE)
    inputs = bc.assemble_inputs(quarterly, monthly, universe, asof=ASOF)
    uni = universe.copy(); uni["ticker"] = uni["ticker"].map(bc._t)
    uni = uni.drop_duplicates("ticker").set_index("ticker")
    m = bc._prep_monthly(monthly); m = m[m["month"] <= ASOF]
    names = uni["stock_name"].to_dict()
    ind = {t: qp.normalize_industry(uni.loc[t, "industry"]) for t in inputs}
    res = {t: cl.classify(i) for t, i in inputs.items()}
    return inputs, res, names, ind, m

def tab(df, floatfmt=3):
    """DataFrame → markdown 表。"""
    d = df.copy()
    cols = list(d.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in d.iterrows():
        cells = []
        for v in r:
            if isinstance(v, (float, np.floating)):
                cells.append("nan" if pd.isna(v) else f"{v:.{floatfmt}f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
