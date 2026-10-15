"""推薦歷史（近 30 個工作日回顧）— tw-hold 三條線的每日快照與檢視模型。

三條線（只記候選／訊號，**模擬單不納入**）：
  swing  = tw-swing 短線（只存分享級欄位：代號／名稱／進場／停損／訊號名稱；本 repo 公開，**不存 rule_id 欄位**；
           訊號名稱沿用 tw-swing 公開分享頁上本來就有的文字，其中含「H2」「V6」這類前綴，這不是新洩漏）
  short  = tw-hold 短線（條件掃描 short_scan.json）
  long   = tw-hold 長波段（swing_list.json 的候選池）

data/history/<asof>.json：{"schema":1,"asof","lines":{"swing":{...},"short":{...},"long":{...}}}
每條線各自封存：第一次寫入後不覆寫（--force 才改，舊版摘要進 revisions）。
**「沒跑」與「空清單」分得開**：該日有該線記錄、n=0、status=ok＝真的沒訊號；交易日沒記錄＝沒跑；
git 歷史撈不到的日子＝not_retained（無資料，不補值）。休市日表是獨立來源（證交所公告），不從已有檔推。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HIST_DIR = ROOT / "data" / "history"
SCHEMA = 1
WINDOW = 30
LINES = {"swing": "tw-swing 短線", "short": "tw-hold 短線（條件掃描）", "long": "tw-hold 長波段（候選池）"}
#: tw-swing 在 2026-09-10～10-14 有規則輸入資料不完整（PE 百分位全缺）——該段零訊號不可信。
SWING_DEGRADED = ("2026-09-10", "2026-10-14")


def _r(x, n=2):
    return round(float(x), n) if isinstance(x, (int, float)) and x == x else None


def short_line(doc: dict, origin: str, min_scanned: int | None = None) -> tuple[str, dict]:
    m = doc.get("_meta") or {}
    stocks = doc.get("stocks") or []
    status, note = "ok", ""
    if not (m.get("has_margin") and m.get("has_chips")):
        status, note = "degraded", "這天缺融資券或法人資料，條件不完整"
    if min_scanned is not None and (m.get("scanned") or 0) < min_scanned:
        status, note = "degraded", f"掃描檔數偏少（{m.get('scanned')}）"
    return m["asof"], {
        "origin": origin, "status": status, "note": note, "n": len(stocks),
        "scanned": m.get("scanned"),
        "candidates": [{"t": x["ticker"], "nm": x.get("name"), "px": _r(x.get("close")),
                        "fs": x.get("first_seen"), "st": x.get("streak_days")} for x in stocks],
        "revisions": []}


def long_line(doc: dict, origin: str) -> tuple[str, dict]:
    m = doc.get("_meta") or {}
    pool = doc.get("candidates_pool") or []
    status, note = ("degraded", "上游資料待補（u1b_pending）") if m.get("u1b_pending") else ("ok", "")
    return m["trading_date"], {
        "origin": origin, "status": status, "note": note, "n": len(pool),
        "candidates": [{"t": x["ticker"], "nm": x.get("name"), "px": _r(x.get("close")),
                        "stop": _r(x.get("risk_stop")), "fs": x.get("first_seen"),
                        "st": x.get("streak_days")} for x in pool],
        "revisions": []}


def swing_line(asof: str, cands: list[dict], origin: str) -> tuple[str, dict]:
    """cands：[{ticker,name,entry,stop,signal}]（分享 JSON 或 tw-swing csv 轉出，皆不含規則 ID）。"""
    status, note = "ok", ""
    if SWING_DEGRADED[0] <= asof <= SWING_DEGRADED[1]:
        status, note = "degraded", "這段期間 tw-swing 部分規則的輸入資料不完整，零訊號不代表當天沒有符合的股票"
    rows, seen = [], {}
    for c in cands:
        t = c["ticker"]
        if t in seen:                       # 同一檔被多條規則觸發：合併訊號名稱，停損取低
            r = seen[t]
            r["sig"] = "、".join(dict.fromkeys([*r["sig"].split("、"), c.get("signal") or ""]))
            if c.get("stop") is not None and r["stop"] is not None:
                r["stop"] = min(r["stop"], _r(c["stop"]))
            continue
        seen[t] = {"t": t, "nm": c.get("name"), "px": _r(c.get("entry")), "stop": _r(c.get("stop")),
                   "sig": c.get("signal") or ""}
        rows.append(seen[t])
    return asof, {"origin": origin, "status": status, "note": note, "n": len(rows),
                  "candidates": sorted(rows, key=lambda x: x["t"]), "revisions": []}


def _digest(line: dict) -> str:
    d = {k: v for k, v in line.items() if k != "revisions"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def add_line(asof: str, key: str, line: dict, *, force: bool = False, out_dir: Path | None = None) -> str:
    """'written' | 'sealed'（該線該日已封存）| 'revised'。"""
    out_dir = out_dir or HIST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{asof}.json"
    doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"schema": SCHEMA, "asof": asof, "lines": {}}
    res = "written"
    if key in doc["lines"]:
        old = doc["lines"][key]
        # 封存規則：status=ok 才算封存（交接單 §13.3）；degraded 的可被之後的版本取代。
        # live 同一天會 rebuild 好幾次、內容可能不同：同為 live 時以「當天最後一版」為準（頁面上使用者看到的是最終版），
        # 內容有差才留一筆 revisions；回填（backfill-*）不得蓋掉 live。
        replace = force or old.get("status") == "degraded" or (
            old.get("origin") == "live" and line.get("origin") == "live" and _digest(old) != _digest(line))
        if (str(line.get("origin", "")).startswith("backfill") and old.get("origin") == "live"
                and old.get("status") != "degraded" and not force):
            replace = False
        if not replace:
            return "sealed"
        line["revisions"] = old.get("revisions", []) + [
            {"digest": _digest(old), "origin": old.get("origin"), "status": old.get("status")}]
        res = "revised"
    doc["lines"][key] = line
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def load_view(key: str, asof: pd.Timestamp, hist_dir: Path | None = None, window: int = WINDOW,
              today: str | None = None) -> dict:
    """某條線近 window 個工作日的檢視模型。state：ok／zero／degraded／recomp（含補算）／holiday／pending／notrun／before／not_retained。"""
    hdir = hist_dir or HIST_DIR
    hp = hdir / "_holidays.json"
    try:
        hol = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {}
    except Exception:  # noqa: BLE001   休市表損毀不該讓整個回顧崩潰（最多格子顯示成沒跑）
        hol = {}
    got = {}
    for p in hdir.glob("20??-??-??.json"):
        try:
            ln = json.loads(p.read_text(encoding="utf-8")).get("lines", {}).get(key)
        except Exception:  # noqa: BLE001
            continue
        if ln:
            got[p.stem] = ln
    rc = {}                                          # 補算旁檔：事故日用修好的資料事後重算（不改封存紀錄）
    for p in (hdir / "recomputed").glob("20??-??-??.json"):
        try:
            ln = json.loads(p.read_text(encoding="utf-8")).get("lines", {}).get(key)
        except Exception:  # noqa: BLE001
            continue
        if ln:
            rc[p.stem] = ln
    first_live = min((d for d, ln in got.items() if ln.get("origin") == "live"), default=None)
    start = min(got) if got else asof.date().isoformat()
    days = []
    for d in pd.bdate_range(end=asof, periods=window):
        k = d.date().isoformat()
        row = {"d": k, "wd": "一二三四五"[d.weekday()]}
        ln = got.get(k)
        if ln:
            n = ln.get("n", len(ln.get("candidates", [])))
            state = "ok" if n else ("degraded" if ln["status"] == "degraded" else "zero")
            row.update(state=state, n=n, note=ln.get("note", ""), origin=ln.get("origin"), c=ln["candidates"],
                       deg=(ln.get("status") == "degraded" and n > 0))
            if k in rc:
                live_t = {c["t"] for c in ln["candidates"]}
                nrc = len([c for c in rc[k]["candidates"] if c["t"] not in live_t])   # 同一檔已在當時紀錄就不重複算
                row.update(state="recomp", nrc=nrc, n=n + nrc,
                           c=[dict(c, src="當時") for c in ln["candidates"]]
                           + [dict(c, src="補算") for c in rc[k]["candidates"]])
        elif k in hol:
            row.update(state="holiday", note=hol[k])
        elif today and k == today:
            row.update(state="pending")            # 今天還沒到產出時間，不算沒跑
        elif k < start:
            row.update(state="before")
        elif first_live and k < first_live:
            row.update(state="not_retained")
        else:
            row.update(state="notrun")
        days.append(row)
    return {"line": key, "label": LINES[key], "asof": asof.date().isoformat(), "days": days}


def search(views: list[dict], q: str) -> tuple[list[str], bool]:
    """代號／名稱搜尋（全形數字先正規化）。回傳 (命中描述, 範圍內是否含輸入不完整的日子)。"""
    k = q.translate({ord(c): ord(c) - 65248 for c in "０１２３４５６７８９"}).strip().lower()
    hits, deg = [], False
    if not k:
        return hits, deg
    for v in views:
        for d in v["days"]:
            deg = deg or d["state"] == "degraded" or bool(d.get("deg"))
            for c in d.get("c") or []:
                if k in str(c["t"]).lower() or k in str(c.get("nm") or "").lower():
                    hits.append(f"{d['d']}　{v['label']}　{c['t']} {c.get('nm') or ''}")
    return hits, deg
