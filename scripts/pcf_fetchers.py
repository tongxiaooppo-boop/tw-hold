"""規模前五大「主動式 ETF」的每日申購買回清單（PCF）/ 完整持股抓取。

## 這是什麼

自建的「主動式 ETF 認養旗標」上游。抓 **發行投信官網每日公開揭露**的 PCF /
投資組合（法定揭露，不需同意），瘦成統一格式，交給 `snapshot_pcf.py` 落每日快照、
`build_active_etf_flags.py` 做前後日差分。

**非官方三大法人／投信買賣超**——這是「主動式 ETF 發行商」的持股，申贖也會動到。

## 涵蓋（wantgoo 2026-09-10 規模排行，國內成分證券主動式 ETF）

| code | 名稱 | 投信 | 內部 id | 抓法 |
| :-- | :-- | :-- | :-- | :-- |
| 00981A | 主動統一台股增長 | 統一 | 49YTW | ezmoney POST GetPCF（要 cookie 暖身） |
| 00403A | 主動統一升級50 | 統一 | 63YTW | 同上 |
| 00991A | 主動復華未來50 | 復華 | ETF23 | fhtrust GET /api/assets?qDate= |
| 00982A | 主動群益台灣精選強棒 | 群益 | 399 | capitalfund POST /CFWeb/api/etf/buyback |
| 00992A | 主動群益科技創新 | 群益 | 500 | 同上 |

前 5 名以外（野村 00980A、國泰 00400A、富邦 00405A…）暫不納。清單穩定，
每月對一次 wantgoo；內部 id 變更時的 resolver 見各 `_resolve_*` 註解。

## 正規化輸出（每檔 fund）

    {
      "code": "00981A", "issuer": "統一", "name": "...",
      "data_date": "2026-09-09",        # PCF 基準日（ISO）
      "post_date": "2026-09-10",        # 生效日，抓不到就同 data_date
      "nav": 285310474996.0,            # 基金淨資產（給規模重排當 sanity check）
      "holdings": [
        {"stock_code": "2330", "stock_name": "台積電",
         "shares": 11864000.0,          # 股（1 張 = 1000 股）
         "weight": 10.38,               # 佔基金淨值 %
         "market_value": 29304080000.0, # 市值（元），抓不到 None
         "price": 2470.0},              # 單價，抓不到 None
        ...
      ],
      "fetched_at": "2026-09-10T12:00:00+00:00",
    }

抓失敗 → raise（呼叫端 per-fund 接住、該檔標 stale）。
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from typing import Any

# Python 3.13+ 的 create_default_context() 預設開 VERIFY_X509_STRICT，會對
# 部分投信網站略不合 RFC 5280 的憑證（缺 Subject Key Identifier）擋下來。
# 仍做完整鏈驗證，只關掉 strict 附加檢查（等同 curl / 舊 Python 行為）。
_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

# ── 設定 ────────────────────────────────────────────────────────────────
FUNDS: list[dict[str, str]] = [
    {"code": "00981A", "name": "主動統一台股增長",   "issuer": "統一", "fetch": "tongyi",  "fund_id": "49YTW"},
    {"code": "00403A", "name": "主動統一升級50",     "issuer": "統一", "fetch": "tongyi",  "fund_id": "63YTW"},
    {"code": "00991A", "name": "主動復華未來50",     "issuer": "復華", "fetch": "fuhwa",   "fund_id": "ETF23"},
    {"code": "00982A", "name": "主動群益台灣精選強棒", "issuer": "群益", "fetch": "capital", "fund_id": "399"},
    {"code": "00992A", "name": "主動群益科技創新",   "issuer": "群益", "fetch": "capital", "fund_id": "500"},
]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 25


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(v: Any) -> float | None:
    """'1,116,000' / '11.759%' / 11.8 → float；空白 / '-' / None → None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "").rstrip("*").strip()
    if s in ("", "-", "—", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _isodate(v: Any) -> str:
    """ISO / ASP.NET `/Date(ms)/` / 民國 `115/09/09` → 'YYYY-MM-DD'；解不出回 ''。"""
    s = str(v or "").strip()
    if not s:
        return ""
    if s.startswith("/Date("):
        try:
            ms = int(s[6:].split(")")[0].split("+")[0].split("-")[0] or 0)
            return (datetime(1970, 1, 1, tzinfo=timezone.utc)
                    + timedelta(milliseconds=ms)).strftime("%Y-%m-%d")
        except Exception:
            return ""
    if "T" in s or (len(s) >= 10 and s[4] == "-"):
        return s[:10]
    p = s.replace("/", "-").split("-")
    if len(p) == 3 and p[0].isdigit():
        y = int(p[0])
        y += 1911 if y < 1911 else 0
        try:
            return f"{y:04d}-{int(p[1]):02d}-{int(p[2]):02d}"
        except ValueError:
            return ""
    return ""


def _taipei_dates(n: int = 8) -> list[datetime]:
    """今天(台北) 起往回 n 個日曆日。"""
    base = datetime.now(timezone.utc) + timedelta(hours=8)
    return [base - timedelta(days=i) for i in range(n)]


# ── 統一（ezmoney）──────────────────────────────────────────────────────
# 整站對非瀏覽器 client 無限 302（session-cookie 反爬）。先用帶 cookie jar 的
# opener GET 任一頁暖身拿 cookie，loop 就解開。之後 POST GetPCF。
# fund_id resolver：https://www.ezmoney.com.tw/ETF/Transaction/PCF 頁面內嵌
#   完整 JSON（sFundShortName ↔ sFundCode，如 "00981A ..." ↔ "49YTW"）。
_EZ_BASE = "https://www.ezmoney.com.tw"


def _tongyi_opener() -> urllib.request.OpenerDirector:
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()),
        urllib.request.HTTPSHandler(context=_CTX))
    op.addheaders = [("User-Agent", _UA), ("Accept-Language", "zh-TW,zh;q=0.9")]
    op.open(_EZ_BASE + "/ETF", timeout=_TIMEOUT).read()          # 暖身
    return op


def _roc(dt: datetime) -> str:
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"


def _parse_tongyi(d: dict, fallback: str) -> dict[str, Any] | None:
    stocks: list[dict] = []
    tran_src = ""
    for a in d.get("asset") or []:
        if a.get("AssetCode") != "ST":
            continue
        for r in a.get("Details") or []:
            sc = str(r.get("DetailCode") or "").strip()
            sh = _num(r.get("Share"))
            if not sc or not sh:
                continue
            tran_src = tran_src or r.get("TranDate")
            amt = _num(r.get("Amount"))
            stocks.append({
                "stock_code": sc,
                "stock_name": str(r.get("DetailName") or "").strip(),
                "shares": sh,
                "weight": _num(r.get("NavRate")),
                "market_value": amt,
                "price": (amt / sh) if (amt and sh) else None,
            })
    if not stocks:
        return None
    pcf = {p.get("PCFCode"): p for p in (d.get("pcf") or [])}
    tran = _isodate(tran_src) or _isodate((pcf.get("NAV") or {}).get("TranDate")) or fallback
    post = _isodate((pcf.get("NAV") or {}).get("PostDate"))
    return {
        "data_date": tran,
        "post_date": post or tran,
        "nav": _num((pcf.get("NAV") or {}).get("Amount")),
        "units": _num((pcf.get("OUT_UNIT") or {}).get("Amount")),
        "name_full": ((d.get("fund") or {}).get("sFundName") or "").strip(),
        "holdings": stocks,
    }


def fetch_tongyi(fund_id: str) -> dict[str, Any]:
    """ezmoney 的 GetPCF 在多台 server 間偶爾回到舊一天 → 連問前幾個交易日、取
    data_date 最新的那份。"""
    op = _tongyi_opener()
    best: dict[str, Any] | None = None
    last_err: Exception | None = None
    for i, dt in enumerate(_taipei_dates(6)):
        body = json.dumps({"fundCode": fund_id, "date": _roc(dt),
                           "specificDate": i != 0}).encode()
        req = urllib.request.Request(
            _EZ_BASE + "/ETF/Transaction/GetPCF", data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": _EZ_BASE + "/ETF/Transaction/PCF"})
        try:
            d = json.loads(op.open(req, timeout=_TIMEOUT).read().decode("utf-8"))
        except Exception as e:                                   # HTML 錯誤頁 / JSON parse
            last_err = e
            continue
        got = _parse_tongyi(d, dt.strftime("%Y-%m-%d"))
        if got and (best is None or got["data_date"] > best["data_date"]):
            best = got
        if best and i >= 2:                                      # 問到第 3 個就夠了
            break
    if best is None:
        raise RuntimeError(f"統一 GetPCF 連問都拿不到持股（fund_id={fund_id}）：{last_err}")
    return best


# ── 群益（capitalfund）─────────────────────────────────────────────────
# POST /CFWeb/api/etf/buyback {"fundId": "<內部數字 id>"}。站掛 Imperva 但 curl/urllib+UA 可過。
# fund_id resolver：GET https://www.capitalfund.com.tw/CFWeb/api/etf/items
#   → [{"fundNo","stockNo","shortName"}]（00982A=399、00992A=500）。
_CAP_BUYBACK = "https://www.capitalfund.com.tw/CFWeb/api/etf/buyback"
_CAP_ITEMS = "https://www.capitalfund.com.tw/CFWeb/api/etf/items"


def resolve_capital_ids() -> dict[str, str]:
    """stockNo(00992A) → fundNo(500)。呼叫端可用來對照/驗證寫死的 fund_id。"""
    req = urllib.request.Request(_CAP_ITEMS, headers={"User-Agent": _UA})
    d = json.loads(urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX).read().decode("utf-8"))
    return {r["stockNo"]: str(r["fundNo"]) for r in (d.get("data") or []) if r.get("stockNo")}


def fetch_capital(fund_id: str) -> dict[str, Any]:
    body = json.dumps({"fundId": str(fund_id)}).encode()
    req = urllib.request.Request(
        _CAP_BUYBACK, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA,
                 "Referer": "https://www.capitalfund.com.tw/"})
    d = json.loads(urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX).read().decode("utf-8"))
    if d.get("code") != 200 or not (d.get("data") or {}).get("stocks"):
        raise RuntimeError(f"群益 buyback 無資料（fundId={fund_id}）：{d.get('message') or d.get('code')}")
    data = d["data"]
    pcf = data.get("pcf") or {}
    nav = _num(pcf.get("nav"))
    stocks: list[dict] = []
    for r in data["stocks"]:
        sc = str(r.get("stocNo") or "").strip()
        sh = _num(r.get("share"))
        if not sc or sh is None:
            continue
        w = _num(r.get("weight"))
        mv = (nav * w / 100) if (nav and w is not None) else None
        stocks.append({
            "stock_code": sc,
            "stock_name": str(r.get("stocName") or "").strip(),
            "shares": sh,
            "weight": w,
            "market_value": mv,
            "price": (mv / sh) if (mv and sh) else None,
        })
    d2 = _isodate(pcf.get("date2")) or str(pcf.get("date2") or "")[:10]
    d1 = _isodate(pcf.get("date1")) or str(pcf.get("date1") or "")[:10]
    return {
        "data_date": d2 or d1,
        "post_date": d1 or d2,
        "nav": nav,
        "units": _num(pcf.get("totUnit")),
        "name_full": (pcf.get("fundName") or "").strip(),
        "holdings": stocks,
    }


# ── 復華（fhtrust）─────────────────────────────────────────────────────
# GET /api/assets?fundID=ETF23&qDate=YYYYMMDD → result[0].detail[]（當日完整持股）。
#   ⚠️ 不是 /api/ETFPcf（主動 ETF 回空籃子）也不是 /api/stockhold（月頻 top-10）。
# fund_id resolver：GET /api/fundList?ec001=3 → result[].{fundID, etf002(=ticker)}。
_FH_BASE = "https://www.fhtrust.com.tw"


def resolve_fuhwa_ids() -> dict[str, str]:
    """etf002(00991A) → fundID(ETF23)。"""
    req = urllib.request.Request(_FH_BASE + "/api/fundList?ec001=3",
                                 headers={"User-Agent": _UA})
    d = json.loads(urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX).read().decode("utf-8"))
    return {str(r.get("etf002") or "").strip(): r["fundID"]
            for r in (d.get("result") or []) if r.get("etf002") and r.get("fundID")}


def fetch_fuhwa(fund_id: str) -> dict[str, Any]:
    last_err: Exception | None = None
    for dt in _taipei_dates(8):
        q = dt.strftime("%Y%m%d")
        req = urllib.request.Request(
            f"{_FH_BASE}/api/assets?fundID={fund_id}&qDate={q}",
            headers={"User-Agent": _UA, "Referer": _FH_BASE + "/ETF/etf_detail"})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX).read().decode("utf-8"))
            row = (d.get("result") or [{}])[0]
        except Exception as e:
            last_err = e
            continue
        detail = row.get("detail") or []
        stocks: list[dict] = []
        for r in detail:
            if r.get("ftype") != "股票":
                continue
            sc = str(r.get("stockid") or "").strip()
            sh = _num(r.get("qshare"))
            if not sc or sh is None:
                continue
            w = _num(r.get("prate_addaccint"))
            stocks.append({
                "stock_code": sc,
                "stock_name": str(r.get("stockname") or "").strip(),
                "shares": sh,
                "weight": w,
                "market_value": _num(r.get("mvalue")),
                "price": _num(r.get("price")),
            })
        if not stocks:
            continue
        dd = _isodate(row.get("dDate")) or dt.strftime("%Y-%m-%d")
        return {
            "data_date": dd,
            "post_date": dd,
            "nav": _num(row.get("pcf_FundNav")),
            "units": _num(row.get("pcf_FundQissue")),
            "name_full": (row.get("twNameFull") or "").strip(),
            "holdings": stocks,
        }
    raise RuntimeError(f"復華 /api/assets 連 8 個日期都拿不到持股（fund_id={fund_id}）：{last_err}")


_FETCHERS = {"tongyi": fetch_tongyi, "capital": fetch_capital, "fuhwa": fetch_fuhwa}


def fetch_one(fund: dict[str, str]) -> dict[str, Any]:
    out = _FETCHERS[fund["fetch"]](fund["fund_id"])
    out["code"] = fund["code"]
    out["issuer"] = fund["issuer"]
    out["name"] = fund["name"]
    out["fetched_at"] = _now_iso()
    # 基本理智檢查：至少 10 檔、權重總和落在 60~130%
    hs = out["holdings"]
    wsum = sum(h["weight"] for h in hs if h.get("weight"))
    if len(hs) < 10 or not (55 <= wsum <= 135):
        raise RuntimeError(f"{fund['code']} 持股不合理（{len(hs)} 檔、權重和 {wsum:.0f}%）")
    return out


def fetch_all(sleep: float = 1.0) -> tuple[list[dict], list[dict]]:
    """回 (成功清單, 失敗清單[{code, error}])。單一投信掛掉不影響其他。"""
    ok, bad = [], []
    for f in FUNDS:
        try:
            ok.append(fetch_one(f))
        except Exception as e:                                   # noqa: BLE001
            bad.append({"code": f["code"], "issuer": f["issuer"],
                        "error": f"{type(e).__name__}: {e}"})
        time.sleep(sleep)
    return ok, bad


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ok, bad = fetch_all()
    for o in ok:
        print(f"{o['code']} {o['name']}　data_date={o['data_date']}　"
              f"{len(o['holdings'])} 檔　nav={o['nav']:,.0f}" if o['nav'] else
              f"{o['code']} {o['name']}　data_date={o['data_date']}　{len(o['holdings'])} 檔")
    for b in bad:
        print(f"✗ {b['code']}　{b['error']}")
