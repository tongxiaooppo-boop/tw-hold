"""自建上游：上市「停止買賣中」每日快照（TWSE `violation/stop`）。

## 為什麼一定要每天抓、而且越早開始越好
這個端點**沒有歷史**：`date=` 參數官方會忽略，永遠回「今天仍在停止買賣中」的名單（tw-stock-data 契約 5.u 實測）。
漏抓一天就永久少一天，補抓成本是無限大。壞掉的樣子是「那一天沒有檔」，不是錯誤——所以要每天跑、而且閘門要看得到。

用途：日線「沒有列」有三種成因，只有它能把第一種分出來——
  停更 ∧ 已下市（終止上市清單）→ 不進母體；停更 ∧ 在停止買賣名單 → ⚠ 會復牌，復牌前後兩段不可接續讀；兩張都不在 → 真正的未解釋洞。
每一列附「停止買賣開始日期」，所以**第一次抓到的那天就能把當下這一段的起點整段補回去**；更早結束過的段落補不回來（永久的洞）。

## 資料
`data/selfhost/stophalt.parquet`（累積型：**只增不減**、同 (date,ticker) 以最新為準）：
  date（快照日＝我們抓的那天，台北時區）, ticker, name, market（目前只有 TW）, halt_since, rule, reason

⚠ 上櫃（TPEx）的對應來源尚未找到 ⇒ 沒有上櫃列**不代表上櫃沒有停止買賣**，一律當「不可判定」。
⚠ `meta/suspend`（TWTAWU）不是這張表（那是短暫停牌後復牌，9,594/10,034 列是權證）。

用法：
    python scripts/selfhost_stophalt.py                 # 抓今天
    python scripts/selfhost_stophalt.py --seed DIR      # 用 tw-stock-data 的 data/universe/stophalt/*.csv 當種子（一次性）
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "selfhost" / "stophalt.parquet"
URL = "https://www.twse.com.tw/rwd/zh/violation/stop?response=json"
FIELDS = ["證券代號", "證券名稱", "違反營業細則條款", "停止買賣原因", "停止買賣開始日期"]
COLS = ["date", "ticker", "name", "market", "halt_since", "rule", "reason"]
UA = {"User-Agent": "Mozilla/5.0"}


def today_tw() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def _roc_date(s: str) -> str | None:
    """'115年10月06日' → '2026-10-06'；認不出來回 None（不猜）。"""
    m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", str(s))
    if not m:
        return None
    return f"{int(m.group(1)) + 1911:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def parse(j: dict, snapshot_day: str) -> tuple[pd.DataFrame | None, str]:
    """回傳 (DataFrame, 說明)；結構不符或快照日對不上 → (None, 原因)——寧可明確失敗，不存一份不是今天的名單。"""
    tabs = j.get("tables") or []
    if not tabs:
        return None, f"沒有 tables；頂層鍵={sorted(j)}"
    t = tabs[0]
    if (t.get("fields") or []) != FIELDS:
        return None, f"欄位結構與預期不符，拒收：{t.get('fields')}"
    said = _roc_date(t.get("title", ""))
    if said != snapshot_day:
        return None, f"標題日期 {said!r}（{t.get('title')!r}）≠ 快照日 {snapshot_day}：這份名單不是今天的，拒收"
    rows = []
    for r in t.get("data") or []:
        code = str(r[0]).strip()
        if not code or not code[0].isdigit():
            continue            # 不用「在不在母體」濾：停止買賣中的股多半已不在日檔
        rows.append({"date": pd.Timestamp(snapshot_day), "ticker": code, "name": str(r[1]).strip(), "market": "TW",
                     "halt_since": _roc_date(r[4]) or "", "rule": str(r[2]).strip(),
                     "reason": str(r[3]).replace(chr(13), "").replace(chr(10), "").strip()})
    return pd.DataFrame(rows, columns=COLS), f"{len(rows)} 檔停止買賣中"


def read_seed_csv(f: Path) -> pd.DataFrame:
    """tw-stock-data 的快照 CSV：停止買賣原因有多行文字而**沒有加引號**，直接 read_csv 會把續行當成新列。
    所以自己切：以「YYYY-MM-DD,」開頭的行才是新紀錄，其餘行併進上一筆的 reason。"""
    recs: list[list[str]] = []
    for line in f.read_text(encoding="utf-8-sig").splitlines()[1:]:
        if re.match(r"^\d{4}-\d{2}-\d{2},", line):
            recs.append(line.split(",", 6))
            if len(recs[-1]) < 7:
                recs[-1] += [""] * (7 - len(recs[-1]))
        elif recs:
            recs[-1][6] += line
    if not recs:
        return pd.DataFrame(columns=COLS)
    d = pd.DataFrame(recs, columns=["date", "ticker", "name", "market", "halt_since", "rule", "reason"])
    d["market"] = "TW"
    d["date"] = pd.to_datetime(d["date"])
    d["reason"] = d["reason"].str.strip().str.strip('"')
    return d[COLS]


def merge_into(new: pd.DataFrame, path: Path = OUT) -> int:
    """累積型：只增不減。回傳寫入後總列數。"""
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COLS)
    old["date"] = pd.to_datetime(old["date"])
    allp = pd.concat([old, new], ignore_index=True).drop_duplicates(["date", "ticker"], keep="last")
    assert len(allp) >= len(old), "stophalt 累積檔不可變少"
    path.parent.mkdir(parents=True, exist_ok=True)
    allp.sort_values(["date", "ticker"]).reset_index(drop=True).to_parquet(path, index=False, compression="zstd")
    return len(allp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", help="tw-stock-data 的 data/universe/stophalt 目錄（一次性種子）")
    a = ap.parse_args(argv)
    if a.seed:
        fr = []
        for f in sorted(Path(a.seed).glob("*.csv")):
            d = read_seed_csv(f)
            if len(d):
                fr.append(d)
        if not fr:
            print("種子目錄沒有可用檔", file=sys.stderr)
            return 1
        n = merge_into(pd.concat(fr, ignore_index=True))
        print(f"種子 {len(fr)} 份快照已併入，stophalt.parquet 共 {n} 列")
        return 0
    day = today_tw()
    try:
        r = requests.get(URL, headers=UA, timeout=40)
        r.raise_for_status()
        j = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"::error::停止買賣名單抓取失敗：{e}", file=sys.stderr)
        return 1
    df, note = parse(j, day)
    if df is None:
        print(f"::error::{note}", file=sys.stderr)
        return 1
    n = merge_into(df)
    print(f"{day}：{note}；stophalt.parquet 共 {n} 列")
    return 0


if __name__ == "__main__":
    sys.exit(main())
