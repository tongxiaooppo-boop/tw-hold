"""核對：app 的 stock_label（兩層）全市場結果＝peak_backtest.py 原型（two_layer.csv）。"""
import sys, warnings; warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import pandas as pd, bundle_data as bd, valuation as v
from factors.factors import quarterly_factors
proto = pd.read_csv(OUT / "two_layer.csv", dtype={"ticker": str}).set_index("ticker")
rows = []
for t in proto.index:
    r = v.estimate(quarterly_factors(bd.financials(t)), bd.revenue(t), bd.prices(t), bd.per_history(t))
    lb, hp = r["label"], r["high_pe"]
    rows.append({"ticker": t, "type": lb["type"], "state": lb["state"] or "",
                 "hp_ok": hp["eligible"], "hp_up": hp["upside_high_pe"]})
app = pd.DataFrame(rows).set_index("ticker")
diff = app[(app["type"] != proto["type"]) | (app["state"] != proto["state"].fillna(""))]
print("不一致", len(diff)); print(diff.join(proto[["type", "state"]], rsuffix="_proto").head(20))
print(pd.crosstab(app["type"], app["state"].replace("", "（無）")))
print("高PE過關", app.index[app["hp_ok"]].tolist())
