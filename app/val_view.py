"""估值卡畫面資料層（估值 2.0 P4，規格 docs/val2/P4_spec.md §3；版面 docs/val2/card_demo.html）。

【框架由 Opus 定（2026-11-02），實作者不得改介面、dataclass、常數名與值】函式本體由 P4a 實作。
輸入只有 val_card.build_card 的回傳 dict（與 stock_class.json 頂層 meta）；輸出字串與表格，streamlit 端只負責畫。

鐵則（test_畫面不自己算 會掃）：
- 不 import streamlit／pandas／numpy；不做四則運算（+ 只准接字串）；不呼叫 sum／min／max／abs／round。
  百分比、千分位一律用 format spec（例 f"{v:+.1%}"）。
- 估值畫面所有數字只准經下面的 fmt_* 產生（§9-3 同值同字）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PIN = "📌"
PIN_LEGEND = "📌＝主卡片上的數字"
COVERAGE_MIN_K = 100
MSG_NO_MULTIPLES = "估值倍數資料還沒產生（缺 multiples_hist／eps_revision／industry_pe），暫不顯示估值"
MORE_DETAIL = "詳見 📊 估值定位細節"
NOT_FORECAST = "試算不是預測、不是目標價"
POS = {"cheap": ("便宜區", "good"), "fair": ("合理區", "mid"), "dear": ("昂貴區", "bad")}
BUY_STATE = {"normal": "一般", "fwd_up": "前瞻上調"}

# 試算停用原因的白話（2026-11-03，sol 起草、Opus 審）：鍵＝detect 檢查名稱；「試算公式」再依原因字串的開頭分。
# 值＝(卡片短句, 展開區說明)。展開區說明不放這檔的數字以外的術語。
STOP_PLAIN = {
    "橋接殘差": ("公式回算誤差大", "用同一套公式回算過去幾季，與實際每股盈餘差距超出容許範圍，所以不用它推下一季。多半是本業以外的損益（轉投資、匯兌等）占比高又忽賺忽賠，月營收看不到這部分。"),
    "營收劇變": ("營收變化太大", "這季營收跟上季比的變化，和去年同期差太多，不能假設每筆營收還賺得一樣多（例如接到低毛利的大單）。"),
    "近零EPS": ("試算獲利過低", "試算出來的每股盈餘遠低於近五年的中間水準，可能是實際轉弱，也可能是公式沒反映到，所以不拿來估值。"),
    "月營收口徑": ("月營收與季報對不上", "近 4 季有兩季以上，月營收加總和季報營收差超過 5%，用月營收推每股盈餘不可靠。"),
    "毛利或": ("成本費用資料不齊", "最新一季缺成本或費用資料，算不出每筆營收能留下多少獲利。"),
    "業外有效季數不足": ("業外資料不足", "本業以外的收入與損失，可用的季度資料不夠，估不出下一季要加減多少。"),
    "稅前抵銷比過小": ("近幾季盈虧互抵", "近幾季扣稅前有賺有賠、合計接近打平，用合計數估稅率會失真。"),
    "淨利抵銷比過小": ("近幾季盈虧互抵", "近幾季扣稅後有賺有賠、合計接近打平，估不出有多少屬於這檔股票的股東。不代表最新一季沒賺錢。"),
    "少數股權比不適用": ("子公司股東分走太多", "集團獲利中很大一塊屬於子公司的其他股東，或兩邊一賺一賠，無法用固定比例換算成這檔股票的每股盈餘。"),
    "推不出股數": ("每股盈餘太接近零", "最新一季每股盈虧不到 0.05 元或資料缺漏，無法反推股數來算每股盈餘。"),
    "非有限值": ("計算沒有有效結果", "計算過程出現無效數值，沒有得到可用的每股盈餘。"),
}
FINANCIAL_PLAIN = "金融業的營收與獲利算法不同，不用月營收試算；三價改用股價淨值比。"


def stop_plain(card: dict) -> Optional[tuple]:
    """試算停用 → (卡片短句, 展開區說明)；沒停用或對不到 → None（呼叫端退回原字串）。"""
    items = ((card.get("status") or {}).get("estimate") or {}).get("items") or []
    item = next((i for i in items if i.get("level") == "stop"), None)
    if item is None:
        return None
    if item["name"] != "試算公式":
        return STOP_PLAIN.get(item["name"])
    return next((v for k, v in STOP_PLAIN.items() if k in (item.get("why") or "")), None)
KIND_ZH = {"actual": "實際", "est": "試算"}
REV_ROLL = "窗口更換，本月不比較"
REV_REPORT = "改用財報，本月不比較"
REV_FLAT = "比上月持平"
# 展開區標題（§15 名稱；streamlit 端 expander 用這三個）
EXP_DETAIL = "📊 估值定位細節"
EXP_EXPLAIN = "📐 怎麼算"
EXP_TRIAL = "🔍 試算細節"


# ── 格式化（唯一來源）────────────────────────────────────────

def fmt_px(v) -> str:
    """價位：None／非有限 → "—"；|v| ≥ 100 → 千分位整數（"2,034"）；否則一位小數（"36.9"）。"""
    if v is None or v != v or v in (float("inf"), float("-inf")):
        return "—"
    return f"{v:,.0f}" if v >= 100 or v <= -100 else f"{v:,.1f}"


def fmt_eps(v) -> str:
    """EPS／每股淨值：兩位小數（"98.73"、"-1.20"）；None → "—"。不帶「元」。"""
    if v is None or v != v:
        return "—"
    return f"{v:,.2f}"


def fmt_mult(v, metric: str) -> str:
    """倍數：pe／pe_fwd 一位小數、pb 兩位小數，後接「 倍」（"20.6 倍"、"1.23 倍"）；None → "—"。"""
    if v is None or v != v:
        return "—"
    return f"{v:.2f} 倍" if metric == "pb" else f"{v:.1f} 倍"


def fmt_pct(v, signed: bool = True) -> str:
    """比例 → 百分比一位小數（signed："+3.1%"；否則 "16.5%"）；None → "—"。"""
    if v is None or v != v:
        return "—"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def fmt_yi(v) -> str:
    """金額（元）→ 億，千分位整數＋「 億」（"4,676 億"）；|值| < 10 億留一位小數（"6.4 億"）；None → "—"。
    本函式（與 fmt_shares）是唯一准許除以 1e8 的地方（test_畫面不自己算 白名單）。"""
    if not _valid(v):
        return "—"
    yi = v / 1e8
    return f"{yi:,.0f} 億" if yi >= 10 or yi <= -10 else f"{yi:,.1f} 億"


def fmt_shares(v) -> str:
    """股數（股）→ "259.3 億股"（一位小數）；None → "—"。"""
    return f"{v / 1e8:,.1f} 億股" if _valid(v) else "—"


def fmt_range(lo, hi) -> str:
    """購買區間 "2,034～2,592"（兩端都用 fmt_px）。"""
    return f"{fmt_px(lo)}～{fmt_px(hi)}"


# ── 資料型別 ───────────────────────────────────────────────

@dataclass(frozen=True)
class VTable:
    title: str | None
    kind: str                                  # "derive"（步驟｜數值｜來源／假設）| "kv"（項目｜內容）| "grid"
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]          # 每格 str，多行用 "\n"
    hl: tuple[int, ...] = ()                   # 整列底色的列號（📌 列、「＝ 試算 EPS」）


@dataclass(frozen=True)
class PriceCard:
    head: str                                  # "股價"
    head_sub: str                              # "2330 台積電｜高成長"
    price: str                                 # fmt_px
    price_sub: str                             # "現價（10/30）"
    tri_label: str | None                      # "三價（相對自身歷史）"
    tri_hint: str | None                       # "推導見 🔍 ③"
    tri: tuple[tuple[str, str], ...] | None    # (("便宜價","2,034"),("合理價","2,592"),("昂貴價","2,856"))
    tri_note: str | None                       # 沒有三價時一定有字
    pos: tuple[str, str] | None                # ("合理區","mid")
    base_text: str | None                      # "基準：近 4 季 EPS 98.73 元"
    extra: tuple[str, ...]                     # ROE／B 層／C 層的行
    buy: tuple[str, str] | None                # ("2,034～2,592", "一般｜現價在區間內")
    buy_label: str = "購買區間"
    buy_hint: str = "推導見 🔍 ④"
    fwd_label: str | None = None               # "前瞻三價（相對自身前瞻倍數）"；tier≠A → None
    fwd_tri: tuple[tuple[str, str], ...] | None = None
    fwd_note: str | None = None


@dataclass(frozen=True)
class EpsCard:
    kv: tuple[tuple[str, str, str], ...]       # (標題, 小字副標, 數值)
    growth_label: str                          # "年增率（對去年同期）"
    growth_table: VTable                       # grid：期間｜營收｜EPS


@dataclass(frozen=True)
class CardView:
    full: bool                                 # False＝不在估值範圍：只畫 price 卡
    coverage: str
    asof_line: str
    price: PriceCard
    eps: EpsCard | None
    pins: dict[str, str] = field(default_factory=dict)   # 卡片標籤 → 卡片上的字（不含單位）


# ── 卡片 ──────────────────────────────────────────────────

def coverage_line(meta: Optional[dict]) -> str:
    """meta＝stock_class.json 頂層（count、coverage_mktcap_k）。規則見 P4_spec §3-1。"""
    meta = meta or {}
    n, k = meta.get("count"), meta.get("coverage_mktcap_k")
    if n is None:
        return ""
    if k is not None and k >= COVERAGE_MIN_K:
        return f"估值涵蓋市值前 {k:d} 大"   # 不顯示總檔數（使用者 11/3）
    return f"估值收錄 {n:d} 檔"


def asof_line(card: dict) -> str:
    """"財報 2026Q2｜月營收至 2026-09｜股價 2026/10/30　｜　試算不是預測、不是目標價"（缺的段落省略）。
    財報＝eps.reported 最後一季；月營收＝growth key=="month" 的 period。"""
    parts = []
    reported = (card.get("eps") or {}).get("reported") or {}
    quarters = reported.get("quarters") or []
    if quarters:
        parts.append(f"財報 {quarters[-1]['q']}")
    month = next((r for r in card.get("growth", []) if r["key"] == "month"), None)
    if month:
        parts.append(f"月營收至 {month['period']}")
    if card.get("px_date"):
        parts.append(f"現價 {card['px_date']}")
    return "｜".join(parts) + ("　｜　" if parts else "") + NOT_FORECAST


def revision_text(rev: Optional[dict]) -> str:
    """上修文字，規則見 P4_spec §3-1 EPS 卡第 3 點。"""
    rev = rev or {}
    if rev.get("last_event") == "roll":
        return REV_ROLL
    if rev.get("last_event") == "report":
        return REV_REPORT
    pct = rev.get("last_pct")
    pct_text = fmt_pct(pct)
    if pct is None or pct_text in ("+0.0%", "-0.0%"):
        return REV_FLAT
    text = f"比上月 {pct_text}"
    if rev.get("streak", 0) >= 1 and rev.get("direction") in ("up", "down"):
        direction = "上修" if rev["direction"] == "up" else "下修"
        text += f"，連續{direction} {rev['streak']:d} 個月"
    return text


def card_view(card: dict, label: str, meta: Optional[dict]) -> CardView:
    """label＝"2330 台積電"；meta＝stock_class.json 頂層。規則見 P4_spec §3-1。"""
    full = bool(card.get("ok"))
    tier = card.get("tier")
    p, fp = card.get("prices") or {}, card.get("fwd_prices") or {}
    pins = {}
    tri = _tri(p)
    ftri = _tri(fp) if tier == "A" else None
    base_text = None
    if tier == "A" and _valid(p.get("base")):
        pins["基準"] = fmt_eps(p["base"])
        base_text = f"基準：{p['base_name']} {pins['基準']} 元"
        if p["base_name"] == "較低獲利情境":
            base_text += f"（3 年平均 {fmt_eps(card.get('eps_3y_avg'))}；近 4 季 {fmt_eps((card['eps'].get('ttm') or {}).get('eps'))}）"
    if tri:
        pins.update(dict(tri))
    if ftri:
        pins.update({"前瞻" + k: v for k, v in ftri})
    extra = []
    if card.get("roe") is not None:
        extra.append(f"ROE {fmt_pct(card['roe'], False)}（近 4 季）")
    b = card.get("b_tier") or {}
    if tier == "B":
        parts = []
        if b.get("pe_now") is not None:
            parts.append(f"現價本益比 {fmt_mult(b['pe_now'], 'pe')}")
        if b.get("industry_pct") is not None:
            parts.append(f"同產業排名 {fmt_pct(b['industry_pct'], False)}（{b['n_peers']:d} 家）")
        if b.get("eps_needed") is not None:
            pins["反推 EPS 門檻"] = fmt_eps(b["eps_needed"])
            parts.append(f"反推 EPS 門檻 {pins['反推 EPS 門檻']} 元")
        if parts:
            extra.append("｜".join(parts))
    if tier == "C" and card.get("c_tier"):
        extra.append(card["c_tier"]["text"])
    buy = None
    if card.get("buy_range"):
        br = card["buy_range"]
        pins["購買區間"] = fmt_range(br["low"], br["high"])
        buy = (pins["購買區間"], f"{BUY_STATE[br['state']]}｜{_buy_position(br)}")
    note = None if tri else f"{card.get('price_note') or card.get('reason') or '沒有三價'}，{MORE_DETAIL}"
    if not full:
        note = "不在估值範圍"
    price = PriceCard(
        head="股價", head_sub=label + (f"｜{card['display_type']}" if card.get("display_type") else ""),
        price=fmt_px(card.get("price")), price_sub=f"現價（{card['px_date'][5:]}）" if card.get("px_date") else "現價",
        tri_label=("三價（相對自身股價淨值比歷史）" if card.get("route") == "PB" else "三價（相對自身歷史）") if full else None,
        tri_hint="推導見 🔍 ③" if full else None, tri=tri, tri_note=note, pos=POS.get(card.get("position")),
        base_text=base_text, extra=tuple(extra), buy=buy,
        fwd_label="前瞻三價（相對自身前瞻倍數）" if tier == "A" else None,
        fwd_tri=ftri, fwd_note=card.get("fwd_note") if tier == "A" else None)
    eps_card = None
    if full:
        eps = card.get("eps") or {}
        ttm, fwd = eps.get("ttm") or {}, eps.get("fwd") or {}
        kv = []
        tval = fmt_eps(ttm.get("eps"))
        if _valid(ttm.get("eps")):
            pins["近 4 季 EPS"] = tval
        plain = stop_plain(card)
        disabled = plain[0] if plain else eps.get("est_disabled")
        kv.append(("近 4 季 EPS", _window_sub(ttm, disabled), tval + " 元" if tval != "—" else tval))
        rev = revision_text(card.get("revision"))
        if _same_windows(ttm, fwd) and fwd.get("ok"):
            kv.append(("前瞻 4 季 EPS", f"新季營收未出（{rev}）", "＝近 4 季"))
        elif fwd.get("ok") and _valid(fwd.get("eps")):
            pins["前瞻 4 季 EPS"] = fmt_eps(fwd["eps"])
            kv.append(("前瞻 4 季 EPS", f"{_window_sub(fwd, None)}（{rev}）", pins["前瞻 4 季 EPS"] + " 元"))
        else:
            sub = "試算停用：" + _no_suffix(disabled) if disabled else "財報延遲" if fwd.get("status") == "report_late" else fwd.get("reason") or "新季營收未出"
            kv.append(("前瞻 4 季 EPS", sub, "—"))
        growth = []
        for r in card.get("growth", []):
            key = r["key"]
            period = {"ttm": "近 4 季", "fwd": "前瞻 4 季"}.get(key, r["period"])
            if key == "month":
                period = f"最新月（{r['period'][5:]} 月）"
            elif key == "last_q":
                period += "（財報）" if r["kind"] == "actual" else f"（試算；營收已公布 {r['months_known']:d} 個月）"
            elif key == "next_q":
                period += "（營收已公布 3 個月）"
            eps_text = (r.get("eps") or {}).get("text", "—")
            if key == "next_q" and eps.get("est_disabled"):
                eps_text = "試算停用"
            growth.append((period, (r.get("rev") or {}).get("text", "—"), eps_text))
        eps_card = EpsCard(tuple(kv), "年增率（對去年同期）", VTable(None, "grid", ("期間", "營收", "EPS"), tuple(growth)))
    return CardView(full, coverage_line(meta), asof_line(card), price, eps_card, pins)


# ── 展開區 ────────────────────────────────────────────────

def legend_row() -> str:
    return PIN_LEGEND


def detail_tables(card: dict) -> list[VTable]:
    """📊 估值定位細節（kv）。P4_spec §3-2。不放推導與三價。"""
    if not card.get("ok"):
        return []
    tier = card["tier"]
    tier_text = {"A": "自身歷史倍數足夠", "B": "自身歷史太短，看產業",
                 "C": (card.get("c_tier") or {}).get("text", "虧損中，不用獲利估價"), "D": card.get("reason") or "不做估值"}
    rows = [("分層", f"{tier} 層：{tier_text[tier]}")]
    if card.get("route"):
        rows.append(("估值方法", "股價淨值比" if card["route"] == "PB" else "本益比"))
    types = [card.get("display_type")] + list(card.get("state") or []) + list(card.get("subtags") or [])
    rows.append(("類型", "・".join(t for t in types if t)))
    if card.get("why"):
        rows.append(("分類原因", "；".join(card["why"])))
    for key, name in (("data", "資料"), ("share_basis", "股數基準"), ("comparability", "可比性"), ("estimate", "試算")):
        status = (card.get("status") or {}).get(key)
        if status:
            text = "正常" if status["level"] == "ok" else "；".join(f"{i['name']}：{i['why']}" for i in status.get("items", [])) or "尚未檢查"
            rows.append(("可信度", f"{name}：{text}"))
    stats = card.get("prices") if tier == "A" else card.get("b_tier") if tier == "B" else None
    if stats:
        for key, name in (("n_valid", "有效月數"), ("n_loss", "虧損月數"), ("window", "倍數期間")):
            if stats.get(key) is not None:
                rows.append((name, stats[key] if key == "window" else f"{stats[key]:d}"))
    if card.get("roe") is not None:
        rows.append(("ROE", fmt_pct(card["roe"], False)))
    quality = card.get("quality") or {}
    if quality.get("cfo_ni") is not None:
        rows.append(("營業現金流 ÷ 淨利", fmt_pct(quality["cfo_ni"], False)))
    if quality.get("accrual") is not None:
        rows.append(("應計比率", fmt_pct(quality["accrual"], False)))
    plain = stop_plain(card)
    if plain:
        rows.append(("為什麼沒試算", plain[1]))
    elif card.get("type") == "financial":
        rows.append(("為什麼沒試算", FINANCIAL_PLAIN))
    if card.get("notes"):
        rows.append(("備註", "；".join(card["notes"])))
    rows.append(("樣本", "存活者偏差；分類基準 " + (card.get("class_asof") or "未提供").split("T")[0] + "；版本 " + card.get("version", "")))
    return [VTable(None, "kv", ("項目", "內容"), tuple(rows))]


def explain_tables(card: dict) -> list[VTable]:
    """📐 怎麼算（分組 kv「項目｜規則」；2026-11-03 併入原「📖 估值怎麼看」長文）。不放這檔的任何數字。"""
    if not card.get("ok"):
        return []
    pb = card.get("route") == "PB"
    method = "股價淨值比" if pb else "本益比"
    price = [
        ("在回答什麼", f"拿這檔自己過去的{method}當尺，看現價在便宜／合理／昂貴哪一區；不是預測股價。"),
        ("三價", f"{'每股淨值' if pb else '基準 EPS'} × 自身歷史{method}的 20%／50%／80% 位置。"),
        ("倍數期間", "全部歷史，不設上限（金融、營建、資產很重的循環股走這條）。" if pb
         else "一般與循環股近 5 年月底，高成長近 3 年。"),
        ("本益比上限", "一般 30 倍；長期高本益比例外與高成長 50 倍。連便宜位置都到上限 → 只列倍數、不給三價。"),
        ("較低獲利情境", "循環股用近 4 季 EPS 與 3 年平均較低者，避免景氣高點把價格算太高。"),
        ("有效月", "每股淨值與股價有效，排除不可比月份。" if pb
         else "要有正獲利、倍數不超過 100 倍，排除不可比月份。"),
    ]
    eps = [
        ("近 4 季 EPS", "最近 4 季財報；月營收齊了可含 1 季試算。"),
        ("前瞻 4 季 EPS", "新季有月營收後往後多看一季，最多含 2 季試算；沒有就與近 4 季相同。"),
        ("試算", "月營收（未公布的月先估）× 最新季營業利益率 ＋ 近 8 季業外中位數，扣稅與少數股權，÷ 股數。"),
        ("前瞻三價", "前瞻 4 季 EPS × 自身前瞻本益比。新季沒營收、試算停用、歷史不夠、循環股不給。"),
    ]
    buy = [
        ("一般", "便宜價～合理價。「可買」只代表現價在區間內。"),
        ("改用前瞻", "前瞻獲利連 2 個月上修（每次 ≥ 2%）且前瞻合理價較高 → 上緣改用前瞻合理價。"),
        ("回到原本", "連 2 個月下修或前瞻算不出來。換季、新財報當月不算一次調整。"),
    ]
    tier = [
        ("A 層", "自身歷史夠，給三價（倍數到上限仍可能不給）。"),
        ("B 層", "自身歷史太短，看同產業本益比排名與反推 EPS 門檻，不給三價。"),
        ("C 層", "虧損或獲利接近零，不用獲利估價，可能只列股價營收比／股價淨值比位置。"),
        ("D 層", "資料不夠、股數基準對不上或公司類型不適用；畫面寫原因。"),
        ("反推 EPS 門檻", "現價 ÷ 同產業中位本益比，同產業至少 8 家。"),
        ("可信度", "資料、股數、可比性、試算四組：正常／提醒（要核對）／停用（受影響的方法不給價）／未檢查（不能當正常）。"),
    ]
    limits = [
        ("樣本", "沒有下市股，存活者偏差。"),
        ("財報", "歷史用推定公布日＋今天的更正版財報，無法完全還原當時。"),
        ("試算", "最新季利潤率不一定延續；大額一次性業外不會反映。"),
        ("前瞻", "規則還沒回測驗證。"),
        ("倍數", "歷史倍數不保證重現；股數事件、公司轉型會造成不可比。"),
        ("資料起點", "原始股價 2015 年起。"),
        ("提醒", "情境估算，不是買賣建議。"),
    ]
    if pb:
        price = [r for r in price if r[0] not in ("本益比上限", "較低獲利情境")]
        eps = []
        tier = [r for r in tier if r[0] != "反推 EPS 門檻"]
    groups = (("三價", price), ("EPS 與前瞻", eps), ("購買區間", buy), ("分層與可信度", tier), ("已知限制", limits))
    return [VTable(title, "kv", ("項目", "規則"), tuple(rows)) for title, rows in groups if rows]


def trial_tables(card: dict) -> list[VTable]:
    """🔍 試算細節 ①～⑥。P4_spec §3-2（照 card_demo.html）。📌 列：數值欄 f"{PIN} {字}"、來源欄以 f"＝卡片『{標籤}』" 開頭。"""
    if not card.get("ok"):
        return []
    pins = card_view(card, "", None).pins
    eps = card.get("eps") or {}
    ttm, fwd = eps.get("ttm") or {}, eps.get("fwd") or {}
    tables, rows, hl = [], [], []
    for r in ttm.get("quarters", []):
        rows.append((r["q"], KIND_ZH[r["kind"]], fmt_eps(r["eps"])))
    if "近 4 季 EPS" in pins:
        hl.append(len(rows))
        rows.append(("近 4 季合計", "＝卡片『近 4 季 EPS』", PIN + " " + pins["近 4 季 EPS"]))
    if _same_windows(ttm, fwd):
        rows.append(("前瞻 4 季", "新季營收未出 → 與近 4 季相同", ""))
    else:
        for r in fwd.get("quarters", []):
            rows.append((r["q"], KIND_ZH[r["kind"]], fmt_eps(r["eps"])))
        if "前瞻 4 季 EPS" in pins:
            hl.append(len(rows))
            rows.append(("前瞻 4 季合計", "＝卡片『前瞻 4 季 EPS』", PIN + " " + pins["前瞻 4 季 EPS"]))
    if rows:
        tables.append(VTable("① 窗口表", "grid", ("季", "實際／試算", "EPS（元）"), tuple(rows), tuple(hl)))
    details = {}
    for w in (ttm, fwd):
        for d in w.get("details", []):
            details[d["q"]] = d
    tqs = {d["q"] for d in ttm.get("details", [])}
    fqs = {d["q"] for d in fwd.get("details", [])}
    for q, d in sorted(details.items()):
        rows = [(f"{m[5:]} 月營收", fmt_yi(v), KIND_ZH["actual"] if source == "actual" else f"試算（{source}）") for m, v, source in d["months"]]
        source = next((r.get("params_from") for w in (ttm, fwd) for r in w.get("quarters", []) if r["q"] == q), None)
        rows.extend([
            ("＝ 季營收", fmt_yi(d["revenue"]), "—"),
            ("×（毛利率 − 營業費用率）", f"{fmt_pct(d['gm_last'], False)} − {fmt_pct(d['opex_last'], False)}", f"{source} 財報（最新一季）"),
            ("＝ 營業利益（試算）", fmt_yi(d["op"]), "—"),
            ("＋ 業外", fmt_yi(d["nonop"]), "近 8 季業外中位數"),
            ("×（1−稅率）×（1−少數股權比）", f"{fmt_pct(d['tax'], False)}／{fmt_pct(d['minority'], False)}", "；".join(["近 8 季合計"] + list(d.get("flags", [])))),
            ("＝ 歸母淨利（試算）", fmt_yi(d["ni_parent"]), "—"),
            ("÷ 股數", fmt_shares(d["shares"]), d["shares_from"] + " 隱含股數"),
            ("＝ 試算 EPS", fmt_eps(d["eps"]) + " 元", "規則未經驗證"),
        ])
        title = f"② {q} 試算" + ("（近 4 季、前瞻 4 季共用）" if q in tqs and q in fqs else "")
        tables.append(_derive(title, rows, (next(i for i, r in enumerate(rows) if r[0] == "＝ 試算 EPS"),)))
    if card.get("prices"):
        tables.append(_price_table(card, card["prices"], pins, False))
    if card.get("fwd_prices"):
        tables.append(_price_table(card, card["fwd_prices"], pins, True))
    br = card.get("buy_range")
    if br:
        source = f"見 ③-2 前瞻合理價；前瞻連續 {card['revision']['streak']:d} 個月上修" if br["state"] == "fwd_up" else "見 ③ 合理價；前瞻沒有連續 2 個月上修 → 不改用前瞻合理價"
        rows = [("下緣", fmt_px(br["low"]), "見 ③ 便宜價"), ("上緣", fmt_px(br["high"]), source),
                _pin_row("購買區間", "購買區間", pins, "；" + _buy_position(br))]
        tables.append(_derive("④ 購買區間", rows, (2,)))
    b = card.get("b_tier") or {}
    if b:
        rows = []
        if card.get("price") is not None:
            rows.append(("現價", fmt_px(card["price"]), "原始收盤"))
        if b.get("median_pe") is not None:
            rows.append(("÷ 產業中位本益比", fmt_mult(b["median_pe"], "pe"), f"同產業 {b['n_peers']:d} 家"))
        if "反推 EPS 門檻" in pins:
            rows.append(_pin_row("反推 EPS 門檻", "反推 EPS 門檻", pins))
        if rows:
            tables.append(_derive("⑤ B 層反推 EPS 門檻", rows, tuple(i for i, r in enumerate(rows) if r[1].startswith(PIN))))
    if card.get("nonop_hist"):
        rows = [(r["q"], fmt_yi(r["nonop"]), fmt_yi(r["pretax"]), fmt_pct(r.get("share"), False)) for r in card["nonop_hist"]]
        title = f"⑥ 近 8 季業外（中位數 {fmt_yi(card['nonop_median'])}，用在試算）" if _valid(card.get("nonop_median")) else "⑥ 近 8 季業外"
        tables.append(VTable(title, "grid",
                             ("季", "業外", "稅前", "占稅前"), tuple(rows)))
    return tables


def _valid(v):
    return v is not None and v == v and v not in (float("inf"), float("-inf"))


def _tri(prices):
    if not all(_valid(prices.get(k)) for k in ("cheap", "fair", "dear")):
        return None
    return tuple((name, fmt_px(prices[key])) for name, key in (("便宜價", "cheap"), ("合理價", "fair"), ("昂貴價", "dear")))


def _same_windows(ttm, fwd):
    tq, fq = ttm.get("quarters") or [], fwd.get("quarters") or []
    return bool(tq) and tuple(r["q"] for r in tq) == tuple(r["q"] for r in fq)


def _no_suffix(why: str) -> str:
    """停用原因字串多半以「，試算停用」結尾；前面已寫「試算停用：」時去掉，避免重複。"""
    return why[:-len("，試算停用")] if why.endswith("，試算停用") else why


def _window_sub(window, disabled):
    qs = window.get("quarters") or []
    period = f"{qs[0]['q']}～{qs[-1]['q']}" if qs else ""
    if disabled:
        return period + "，試算停用：" + _no_suffix(disabled)
    if not window.get("ok"):
        return window.get("reason") or "無資料"
    return period + (f"，含 {window['n_est']:d} 季試算" if window.get("n_est") else "，4 季皆已公布")


def _buy_position(br):
    if br.get("where") == "in":
        return "現價在區間內"
    if br.get("where") == "above":
        return "現價高於上緣 " + fmt_pct(br.get("gap"))
    if br.get("where") == "below":
        return "現價低於下緣 " + fmt_pct(br.get("gap"))
    return "無現價"


def _derive(title, rows, hl=()):
    return VTable(title, "derive", ("步驟", "數值", "來源／假設"), tuple(rows), tuple(hl))


def _pin_row(step, label, pins, source=""):
    return (step, PIN + " " + pins[label], f"＝卡片『{label}』" + source)


def _price_table(card, p, pins, fwd):
    pb = p["metric"] == "pb"
    method = "股價淨值比" if pb else "本益比"
    growth = card.get("type") == "growth"
    months, gate = ("36", "30") if growth else ("60", "36")
    window = "全歷史，自建股價淨值比" if pb else f"近 {months} 個月" + ("（高成長）" if growth else "") + "，自建" + method
    rows = [("倍數窗", p["window"], window),
            ("有效月數", f"{p['n_valid']:d}" if pb else f"{p['n_valid']:d}／{months}", "門檻 60 個月" if pb else f"門檻 {gate} 個月")]
    base_label = "前瞻 4 季 EPS" if fwd else "基準"
    base_step = "基準每股淨值" if pb else "基準 EPS"
    if fwd:
        rows.append((base_step, fmt_eps(p["base"]), "見 ① 前瞻 4 季合計"))
    elif base_label in pins:
        rows.append(_pin_row(base_step, base_label, pins, f"（{p['base_name']}）"))
    for i, (pct, key, name, source) in enumerate((("20%", "cheap", "便宜價", "只有 20% 的月份比這更低"), ("50%", "fair", "合理價", "中位數"), ("80%", "dear", "昂貴價", "—"))):
        raw, mult = p["raw_mults"][i], p["mults"][i]
        if p.get("cap") is not None and _valid(raw) and raw > p["cap"]:
            source = f"原始 {fmt_mult(raw, p['metric'])}，上限 {fmt_mult(p['cap'], p['metric'])}截斷"
        rows.append((f"× 歷史 {pct} 位置{method}", fmt_mult(mult, p["metric"]), source))
        label = ("前瞻" if fwd else "") + name
        if label in pins:
            rows.append(_pin_row("＝ " + name, label, pins))
    hl = tuple(i for i, r in enumerate(rows) if r[1].startswith(PIN))
    return _derive("③-2 前瞻三價推導" if fwd else "③ 三價推導", rows, hl)
