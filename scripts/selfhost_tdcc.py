"""自建上游 D09：集保戶股權分散表（TDCC，每週）→ `data/selfhost/tdcc.parquet`。

框架版本：2026-11-08（Opus 定；實作者只填函式內容，不改簽名、欄位、常數名與值、docstring 寫的行為）。

## 為什麼存在
官方開放資料**只給最新一週**，官方查詢頁也只留一年（集保「附件一 持股分級表」說明第 3 條：資料保存期間為一年）
⇒ **沒抓的週一年後永久失去**。目前 tw-swing `fundamentals.yml` 每週六存一份寬表（只有人數／比例、沒有各級股數），
2026-11-07 曾因 rebase 衝突整包沒 commit。

## 狀態：備用程式，**不排程**（使用者 2026-11-08 定）
hold／swing 目前用不到集保 → 平常每週下載 TSD 到本地就好；這支寫好、測過，等 TSD 消失或出 bug 再決定要不要接進
`selfhost_collect.yml`／`selfhost_gate.py`（`gate_checks` 就是給那時候用的）。現在只在本機手動跑，產出 `data/selfhost/tdcc.parquet`（gitignore）。

## 資料源
- 官方：`https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`（CSV，UTF-8 帶 BOM，免金鑰，只有最新一週）。
  表頭 `資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%`；資料日期 YYYYMMDD，整份只有一個日期。
  每檔 17 列：分級 1–15、16＝差異數調整、17＝合計。資料日期通常是週五（遇假日提前）；**週五晚上抓到的通常是上一週**
  （週資料隔天才上架）——每週抓一次照樣每週都收到，只是落後一週。
- 歷史：tw-stock-data（TSD）本機
  ① `data/tdcc_hist/<年>.parquet`（欄位 date, stock_id, level, people, shares, pct；使用者提供的第三方封存，
     2019-06-28～2026-09-11 連續 370 週；2017–2018 只有 10 個離散週且 pct 全空、從未核對；使用者定**從 2020-01-03 起匯**，`HIST_START` 卡掉之前的）
  ② `data/tdcc/YYYY-MM-DD.csv`（同欄位，TSD 自己抓官方的週檔，2026-09-04 起）。
- 2026-11-08 Opus 實測：①②在 09-04、09-11 重疊逐格 100% 相同；tw-swing 週快照 8 週與②人數／比例 100% 相同；
  恆等式在 2019-06-28 起 370 週 **0 週違反**；2020 起匯入預期 17,571,370 列／351 週。

## 欄位（`COLS`）
date（datetime64，日）、ticker（str；寫檔存 category 省記憶體）、level（int8，1–17）、holders（int32，人數）、
shares（int64，股）、pct（float32，占集保庫存比例 %，官方兩位小數；level 16／17 官方給的值照存）、
src（"official"＝我們自己抓；"tw-stock-data"＝TSD 匯入）。主鍵 (date, ticker, level)。

## 規矩
- 只留 `TICKER_PATTERN` 的代號（普通股 4 碼＋ETF `00` 開頭 4–5 碼可帶字母；權證 6 碼丟），與 tw-swing `twswing/data/tdcc.py` 同。
  代號一律先 strip（TSD 封存是定寬 6 碼含空白）。
- 一檔不是剛好 1–17 級各一列 → 整檔丟。整份檔數 < `MIN_TICKERS` → 視為截斷，回 None（不寫）。
- 恆等式（每檔每週）：`holders[17] == Σ holders[1..15]`、`shares[17] == Σ shares[1..15] − shares[16]`。
- 同主鍵：official 蓋 tw-stock-data；同 src 新的勝（`merge_rows`）。official 蓋掉**數值不同**的 TSD 列要印 ::warning:: 筆數。
- 缺週用 **ISO 週**判斷（不是相鄰日期差：快照日會在週四／週五間位移）；已知缺口寫死在 `KNOWN_GAPS`，
  新缺口只警告不擋（漏的那週已經補不回來，擋上傳只會連其他週一起丟）。

用法：
    python scripts/selfhost_tdcc.py                                   # 抓官方最新一週併入
    python scripts/selfhost_tdcc.py --import-tsd <TSD根目錄>           # 一次性匯入歷史（只補檔案沒有的主鍵）
    python scripts/selfhost_tdcc.py --verify-tsd <TSD根目錄>           # TSD 封存 vs TSD 官方週檔重疊週＋官方最新週 vs TSD 同週
    python scripts/selfhost_tdcc.py --verify-twswing <tw-swing/data/tdcc 目錄>   # 本檔 vs tw-swing 週快照重疊週
        # 兩種 verify：任一週相符率 < VERIFY_MIN → exit 1
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import _retry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "selfhost" / "tdcc.parquet"
URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
UA = {"User-Agent": "Mozilla/5.0"}
COLS = ["date", "ticker", "level", "holders", "shares", "pct", "src"]
KEY = ["date", "ticker", "level"]
VALS = ["holders", "shares", "pct"]
SRC_OFFICIAL = "official"
SRC_TSD = "tw-stock-data"
SRC_PRIORITY = {SRC_TSD: 0, SRC_OFFICIAL: 1}     # 數字大的蓋小的
TICKER_PATTERN = r"\d{4}|00\d{2,3}[A-Z]?"
LEVELS = tuple(range(1, 18))
MIN_TICKERS = 2_000
HIST_START = date(2020, 1, 3)
PCT_TOL = 0.005                                  # pct 比對容差（官方兩位小數）
VERIFY_MIN = 0.999
GATE_RATIO_MIN = 0.90                            # 最新週檔數 ≥ 前 8 週中位數的 90%
GATE_IDENT_MAX = 0.01                            # 最新週恆等式違反比例上限
# 2020-01-03～2026-09-11 實測缺的 ISO 週（TSD 封存本來就沒有；2023-W42 是 2023-10-20 那份被截斷、TSD 故意不收；
# 2022-W44 成因不明——不要補成好聽的理由）。新缺口發生時，查明成因後才加進來。
KNOWN_GAPS = frozenset({(2020, 25), (2022, 5), (2022, 44), (2023, 4), (2023, 42), (2025, 5), (2026, 8)})
FIELD_MAP = {"資料日期": "date", "證券代號": "ticker", "持股分級": "level",
             "人數": "holders", "股數": "shares", "占集保庫存數比例%": "pct"}


def _get_text(url: str = URL, retries: int = _retry.TRIES) -> str | None:
    """requests＋UA、timeout 60、`encoding='utf-8-sig'`（去 BOM）回 r.text；失敗走 _retry.wait_after_failure；全失敗回 None。"""
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            r.encoding = "utf-8-sig"
            return r.text
        except Exception as e:
            print(f"請求失敗（第 {i + 1} 次）：{str(e)[:80]}", file=sys.stderr)
            _retry.wait_after_failure(i)
    return None


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    """欄序照 COLS；date→datetime64[ns]（normalize 到日）、ticker→str、level→int8、holders→int32、shares→int64、
    pct→float32、src→str。空表也回帶 COLS 欄位的空表。"""
    df = df.reindex(columns=COLS).copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    for col in ("ticker", "src"):
        df[col] = df[col].astype(str)
    for col, dtype in (("level", "int8"), ("holders", "int32"), ("shares", "int64"), ("pct", "float32")):
        df[col] = df[col].astype(dtype)
    return df


def _clean(df: pd.DataFrame, src: str) -> pd.DataFrame:
    """共用清理（parse_csv 與 import_tsd 都走這裡）：輸入已是 date/ticker/level/holders/shares/pct 六欄。
    ticker strip → 只留 fullmatch TICKER_PATTERN；丟掉「不是剛好 1–17 級各一列」的 (date, ticker) 整組；
    加 src → `_typed`。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"].astype(str)).dt.normalize()
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df = df.loc[df.ticker.str.fullmatch(TICKER_PATTERN)].copy()
    df["level"] = pd.to_numeric(df["level"])
    g = df.groupby(["date", "ticker"], observed=True)["level"]
    valid = (g.transform("size").eq(17) & g.transform("nunique").eq(17)
             & g.transform("min").eq(1) & g.transform("max").eq(17)
             & df.assign(_valid=df.level.isin(LEVELS)).groupby(["date", "ticker"], observed=True)["_valid"].transform("all"))
    return _typed(df.loc[valid].assign(src=src))


def parse_csv(text: str | None) -> pd.DataFrame | None:
    """官方 CSV 文字 → COLS（src=official）。None＝失敗：text 為 None／空、表頭缺 FIELD_MAP 任一欄、
    資料日期不只一個、清理後檔數 < MIN_TICKERS。數字欄可能帶千分位逗號，要先去掉。"""
    from io import StringIO

    if not text or not text.strip():
        return None
    try:
        df = pd.read_csv(StringIO(text.lstrip("\ufeff")), dtype=str)
        if not set(FIELD_MAP).issubset(df.columns):
            return None
        df = df.rename(columns=FIELD_MAP)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        if df.date.nunique() != 1 or df.date.isna().any():
            return None
        for col in ("level", *VALS):
            df[col] = pd.to_numeric(df[col].str.replace(",", "", regex=False))
        df = _clean(df, SRC_OFFICIAL)
        return df if df.ticker.nunique() >= MIN_TICKERS else None
    except (ValueError, TypeError, pd.errors.ParserError):
        return None


def fetch_latest() -> pd.DataFrame | None:
    """`parse_csv(_get_text())`。"""
    return parse_csv(_get_text())


def _prepare_tsd(df: pd.DataFrame, start: date) -> pd.DataFrame:
    df = df.rename(columns={"stock_id": "ticker", "people": "holders"}).copy()
    df["date"] = pd.to_datetime(df["date"].astype(str)).dt.normalize()
    df["ticker"] = df["ticker"].astype(str)
    return _clean(df.loc[df.date.ge(pd.Timestamp(start))], SRC_TSD)


def _read_tsd_hist(root: Path, start: date) -> pd.DataFrame:
    parts = []
    for path in sorted((root / "data" / "tdcc_hist").glob("*.parquet")):
        if path.stem.isdigit() and int(path.stem) >= start.year:
            parts.append(_prepare_tsd(pd.read_parquet(path), start))
    return _typed(pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS))


def _read_tsd_csv(root: Path, start: date) -> pd.DataFrame:
    parts = []
    for path in sorted((root / "data" / "tdcc").glob("*.csv")):
        parts.append(_prepare_tsd(pd.read_csv(path, dtype={"stock_id": str}), start))
    return _typed(pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS))


def import_tsd(tsd_root: Path, start: date = HIST_START) -> pd.DataFrame:
    """讀 `<tsd_root>/data/tdcc_hist/<年>.parquet`（只讀年份 ≥ start.year 的檔）與 `<tsd_root>/data/tdcc/*.csv`
    （stock_id 用 str 讀），people 改名 holders，只留 date ≥ start → `_clean(src=tw-stock-data)`。
    同主鍵兩邊都有 → **csv 的勝**（csv 是 TSD 直接抓官方的）。兩個目錄都不存在 → raise FileNotFoundError。"""
    if not (tsd_root / "data" / "tdcc_hist").exists() and not (tsd_root / "data" / "tdcc").exists():
        raise FileNotFoundError(f"TSD 集保目錄不存在：{tsd_root}")
    return merge_rows(_read_tsd_hist(tsd_root, start), _read_tsd_csv(tsd_root, start))[0]


def load_twswing(snap_dir: Path) -> pd.DataFrame:
    """tw-swing 週快照（`<snap_dir>/YYYY-MM-DD.parquet` 寬表：ticker, date, holders_1..15, pct_1..15,
    total_holders, total_shares）→ 長表 COLS（src=official）：level 1–15 有 holders、pct，shares 填 NA；
    level 17 有 holders=total_holders、shares=total_shares，pct 填 NA；**不產生 level 16**。
    這份只拿來 verify，不寫進 OUT，所以不走 `_clean`／`_typed`（holders／shares 用可為空的 Int64、pct 用 float）。"""
    parts = []
    for path in sorted(snap_dir.glob("????-??-??.parquet")):
        wide = pd.read_parquet(path)
        for level in (*range(1, 16), 17):
            part = wide[["date", "ticker"]].copy()
            part["level"] = level
            part["holders"] = wide[f"holders_{level}" if level < 17 else "total_holders"].astype("Int64")
            part["shares"] = wide["total_shares"].astype("Int64") if level == 17 else pd.Series(pd.NA, index=wide.index, dtype="Int64")
            part["pct"] = wide[f"pct_{level}"].astype(float) if level < 17 else float("nan")
            part["src"] = SRC_OFFICIAL
            parts.append(part)
    if not parts:
        return pd.DataFrame(columns=COLS)
    result = pd.concat(parts, ignore_index=True)[COLS]
    result["date"] = pd.to_datetime(result["date"].astype(str)).dt.normalize()
    result["ticker"] = result["ticker"].astype(str).str.strip()
    return result


def merge_rows(old: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """合併兩份 COLS 表。同 KEY：SRC_PRIORITY 高者勝；同優先序 new 勝。
    回 (合併後依 KEY 排序的表, overridden)。overridden＝official 蓋掉 tw-stock-data 且 holders／shares 任一不同、
    或 pct 差 > PCT_TOL 的筆數；> 0 時印 `::warning::official 覆蓋不同數值 TSD：N 筆` 到 stderr。"""
    joined = pd.concat([old, new], ignore_index=True)
    joined["_priority"] = joined["src"].map(SRC_PRIORITY)
    result = joined.sort_values("_priority", kind="stable").drop_duplicates(KEY, keep="last")[COLS]
    before = old.loc[old.src.eq(SRC_TSD)].drop_duplicates(KEY, keep="last")
    changes = before.merge(result.loc[result.src.eq(SRC_OFFICIAL)], on=KEY, suffixes=("_old", "_new"))
    different = (changes.holders_old.ne(changes.holders_new) | changes.shares_old.ne(changes.shares_new)
                 | changes.pct_old.sub(changes.pct_new).abs().gt(PCT_TOL))
    overridden = int(different.sum())
    if overridden:
        print(f"::warning::official 覆蓋不同數值 TSD：{overridden} 筆", file=sys.stderr)
        print(changes.loc[different, KEY + [f"{v}_{side}" for v in VALS for side in ("old", "new")]]
              .head(10).to_string(index=False), file=sys.stderr)
    return _typed(result.sort_values(KEY).reset_index(drop=True)), overridden


def compare(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """同週逐格比對。只比兩邊都有的 date；依 date 分組回一列：date, n_a, n_b, n_both, n_equal, ratio。
    n_a／n_b＝該週各自的 (ticker, level) 數；n_both＝兩邊都有的 (ticker, level) 數；
    相等＝VALS 中**兩邊都非空**的欄位全部相等（holders、shares 精確；pct 差 ≤ PCT_TOL）；ratio＝n_equal/n_both（n_both=0 → 0.0）。
    兩邊沒有共同 date → 回帶這些欄位的空表。"""
    columns = ["date", "n_a", "n_b", "n_both", "n_equal", "ratio"]
    common = pd.Index(a.date.unique()).intersection(pd.Index(b.date.unique()))
    if common.empty:
        return pd.DataFrame(columns=columns)
    a = a.loc[a.date.isin(common)].drop_duplicates(KEY)
    b = b.loc[b.date.isin(common)].drop_duplicates(KEY)
    counts = pd.concat([a.groupby("date").size().rename("n_a"), b.groupby("date").size().rename("n_b")], axis=1)
    both = a.merge(b, on=KEY, suffixes=("_a", "_b"))
    equal = pd.Series(True, index=both.index)
    for col in VALS:
        left, right = both[f"{col}_a"], both[f"{col}_b"]
        match = left.sub(right).abs().le(PCT_TOL) if col == "pct" else left.eq(right)
        equal &= (left.isna() | right.isna() | match).fillna(False)
    both["_equal"] = equal
    result = counts.join(both.groupby("date")["_equal"].agg(n_both="size", n_equal="sum")).fillna(0)
    result[["n_a", "n_b", "n_both", "n_equal"]] = result[["n_a", "n_b", "n_both", "n_equal"]].astype("int64")
    result["ratio"] = result.n_equal.div(result.n_both.where(result.n_both.ne(0))).fillna(0.0)
    return result.reset_index()[columns]


def identity_bad(df: pd.DataFrame) -> pd.Series:
    """每週恆等式違反比例（index＝date，值＝違反的 ticker 數／該週 ticker 數）。
    違反＝`holders[17] != Σ holders[1..15]` 或 `shares[17] != Σ shares[1..15] − shares[16]`。"""
    if df.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="date"))
    keys = ["date", "ticker"]
    sums = df.loc[df.level.between(1, 15)].groupby(keys, observed=True)[["holders", "shares"]].sum()
    total = df.loc[df.level.eq(17)].set_index(keys)[["holders", "shares"]]
    adjustment = df.loc[df.level.eq(16)].set_index(keys)["shares"]
    bad = total.holders.ne(sums.holders) | total.shares.ne(sums.shares.sub(adjustment))
    return bad.groupby(level="date").mean()


def week_gaps(dates) -> set[tuple[int, int]]:
    """最早到最晚日期之間，哪些 ISO (year, week) 一個日期都沒有。dates 少於 2 個 → 空集合。"""
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).dropna().unique()
    if len(dates) < 2:
        return set()
    mondays = dates.normalize() - pd.to_timedelta(dates.dayofweek, unit="D")
    iso = dates.isocalendar()
    span = pd.date_range(mondays.min(), mondays.max(), freq="7D").isocalendar()
    return {(int(y), int(w)) for y, w in set(zip(span.year, span.week)) - set(zip(iso.year, iso.week))}


def gate_checks(live: pd.DataFrame) -> tuple[list[str], list[str]]:
    """將來接 selfhost_gate.content_checks 用（目前未接），回 (errors, warnings)。空表 → ([], [])。
    errors：最新週 ticker 數 < MIN_TICKERS；最新週 ticker 數 < 前 8 週（不含最新週，至少 4 週才判）中位數 × GATE_RATIO_MIN；
            最新週 identity_bad > GATE_IDENT_MAX。
    warnings：`week_gaps(live.date) - KNOWN_GAPS` 非空（列出那些週）。
    訊息開頭一律 `tdcc：`。"""
    if live.empty:
        return [], []
    errors, warnings = [], []
    counts = live.groupby("date").ticker.nunique().sort_index()
    latest, count = counts.index[-1], counts.iloc[-1]
    if count < MIN_TICKERS:
        errors.append(f"tdcc：最新週檔數 {count} < {MIN_TICKERS}")
    previous = counts.iloc[:-1].tail(8)
    if len(previous) >= 4 and count < previous.median() * GATE_RATIO_MIN:
        errors.append(f"tdcc：最新週檔數 {count} 低於前 8 週中位數的 {GATE_RATIO_MIN:.0%}")
    bad = identity_bad(live.loc[live.date.eq(latest)]).loc[latest]
    if bad > GATE_IDENT_MAX:
        errors.append(f"tdcc：最新週恆等式違反比例 {bad:.2%}")
    gaps = week_gaps(live.date) - KNOWN_GAPS
    if gaps:
        warnings.append(f"tdcc：新增缺週 {sorted(gaps)}")
    return errors, warnings


def write(df: pd.DataFrame, out: Path = OUT) -> None:
    """寫 parquet（zstd；ticker 轉 category 再寫），寫前檢查：KEY 不重複、level ⊆ LEVELS、holders／shares 全 ≥ 0、
    src ⊆ SRC_PRIORITY；不符 → raise ValueError 不寫。父目錄不存在就建。"""
    if (df.duplicated(KEY).any() or not df.level.isin(LEVELS).all()
            or not df.holders.ge(0).all() or not df.shares.ge(0).all()
            or df[["holders", "shares"]].isna().any().any()
            or not df.src.isin(SRC_PRIORITY).all()):
        raise ValueError("tdcc 主鍵、分級、人數、股數或來源檢查失敗")
    stored = _typed(df)
    stored["ticker"] = stored["ticker"].astype("category")
    out.parent.mkdir(parents=True, exist_ok=True)
    stored.to_parquet(out, compression="zstd", index=False)


def _read(out: Path = OUT) -> pd.DataFrame:
    """OUT 存在 → read_parquet 後 `_typed`；不存在 → `_typed(空表)`。"""
    return _typed(pd.read_parquet(out) if out.exists() else pd.DataFrame(columns=COLS))


def main(argv=None) -> int:
    """CLI（見檔頭用法）。檔案路徑一律在呼叫時讀模組層 `OUT`（`write(df, OUT)`、`_read(OUT)`），測試會 monkeypatch OUT。
    - 無參數：fetch_latest；None → 印 `::error::集保官方抓取失敗` 回 1。成功 → merge_rows(舊, 新) → write；
      印「資料日期 YYYY-MM-DD｜N 檔｜新增 X 列｜overridden Y｜累積 W 週」回 0。
    - --import-tsd ROOT：import_tsd → merge_rows(**新的當 old、舊檔當 new**，等於只補檔案沒有的主鍵、不動已有列) → write；
      印「匯入新增 X 列｜累積 W 週｜最早 … 最晚 …」回 0。
    - --verify-tsd ROOT：(a) TSD 封存（只讀 tdcc_hist）vs TSD 官方週檔（只讀 tdcc/*.csv）compare；
      (b) fetch_latest vs TSD 官方週檔 compare（官方最新週 TSD 沒有 → 印「官方 YYYY-MM-DD TSD 沒有，略過」，不算失敗；
      官方抓取失敗 → 印 ::error:: 回 1）。兩張表都印出來；任一列 ratio < VERIFY_MIN 或 (a) 0 列 → 回 1。
      為了 (a)(b) 可分開讀，import_tsd 內部請拆出 `_read_tsd_hist(root, start)`、`_read_tsd_csv(root, start)` 兩個私有函式。
    - --verify-twswing DIR：_read() vs load_twswing(DIR) compare；印表；0 列或任一列 ratio < VERIFY_MIN → 回 1。"""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--import-tsd", type=Path)
    modes.add_argument("--verify-tsd", type=Path)
    modes.add_argument("--verify-twswing", type=Path)
    args = parser.parse_args(argv)
    if args.verify_tsd:
        hist = _read_tsd_hist(args.verify_tsd, HIST_START)
        csv = _read_tsd_csv(args.verify_tsd, HIST_START)
        overlap = compare(hist, csv)
        print(overlap.to_string(index=False))
        latest = fetch_latest()
        if latest is None:
            print("::error::集保官方抓取失敗", file=sys.stderr)
            return 1
        current = compare(latest, csv)
        print(current.to_string(index=False))
        if current.empty:
            print(f"官方 {latest.date.max():%Y-%m-%d} TSD 沒有，略過")
        return int(overlap.empty or overlap.ratio.lt(VERIFY_MIN).any() or current.ratio.lt(VERIFY_MIN).any())
    if args.verify_twswing:
        result = compare(_read(OUT), load_twswing(args.verify_twswing))
        print(result.to_string(index=False))
        return int(result.empty or result.ratio.lt(VERIFY_MIN).any())
    old = _read(OUT)
    if args.import_tsd:
        imported = import_tsd(args.import_tsd)
        result, _ = merge_rows(imported, old)
        write(result, OUT)
        print(f"匯入新增 {len(result) - len(old):,} 列｜累積 {result.date.nunique()} 週｜"
              f"最早 {result.date.min():%Y-%m-%d} 最晚 {result.date.max():%Y-%m-%d}")
        return 0
    latest = fetch_latest()
    if latest is None:
        print("::error::集保官方抓取失敗", file=sys.stderr)
        return 1
    result, overridden = merge_rows(old, latest)
    write(result, OUT)
    print(f"資料日期 {latest.date.max():%Y-%m-%d}｜{latest.ticker.nunique():,} 檔｜"
          f"新增 {len(result) - len(old):,} 列｜overridden {overridden}｜累積 {result.date.nunique()} 週")
    return 0


if __name__ == "__main__":
    sys.exit(main())
