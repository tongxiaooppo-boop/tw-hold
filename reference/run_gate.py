"""自動班開跑前的資料新鮮度閘門（純函式，不做 IO；IO 在 scripts/run_gate.py）。

目的：Cloudflare 準時 dispatch、GitHub 原 cron 留備援；資料已經是最新就不必再整條重跑
（國際總經每班整批重抓會把前一班的好資料蓋掉）。閘門只能讓班「少跑」，不能害它「不跑」——
任何判斷不了的情況一律回「跑」。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

WORKFLOWS = ("global_macro", "chip_flow_evening", "openapi_daily", "revenue_watch", "heartbeat")
BACKUP_WINDOW_HOURS = {"openapi_daily": 8, "revenue_watch": 8, "heartbeat": 2}
HEARTBEAT_LAST_HOUR = 9          # 台北 09:00 後的 heartbeat 備援班直接跳過（開盤前檢查已無意義）
CHIP_READY_HOUR = 15             # 台北 15:00 後才期待「今天」的籌碼


def _tpe(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc) + timedelta(hours=8)


def _prev_weekday(d: date) -> date:
    """d 之前（不含 d）最近的平日。"""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def expected_us_date(now_utc: datetime) -> date:
    """台北今天之前最近的一個平日（週一～五）。美股假日不處理（→ 判不新鮮 → 照跑，退回現況）。"""
    return _prev_weekday(_tpe(now_utc).date())


def expected_chip_date(now_utc: datetime) -> date:
    """台北時間 ≥15:00 且今天是平日 → 台北今天；否則 → 台北今天之前最近的平日。"""
    t = _tpe(now_utc)
    if t.hour >= CHIP_READY_HOUR and t.weekday() < 5:
        return t.date()
    return _prev_weekday(t.date())


def macro_fresh(meta: dict | None, symbols: set[str] | None, tx_meta: dict | None,
                all_symbols: set[str], now_utc: datetime) -> tuple[bool, str]:
    """全部成立才 True：meta 非 None；meta["reference_date"] >= expected_us_date；meta.get("stale") 為空；
    meta.get("carried_forward", []) 為空；symbols 包含 all_symbols 全部；tx_meta 非 None、
    tx_meta.get("missing_night") 不是 True、tx_meta["date"] >= 台北今天。
    第二個回傳值＝中文理由（不新鮮時寫是哪一條沒過）。meta 的 estimated 不列入判斷。"""
    if meta is None:
        return False, "國際總經 meta 不存在"
    exp = expected_us_date(now_utc)
    ref = _to_date(meta.get("reference_date"))
    if ref is None or ref < exp:
        return False, f"國際總經只到 {ref}，應有 {exp} 收盤"
    if meta.get("stale"):
        return False, f"有 {len(meta['stale'])} 檔部分過期"
    if meta.get("carried_forward"):
        return False, f"有沿用上一版的 symbol：{list(meta['carried_forward'])}"
    miss = sorted(set(all_symbols) - set(symbols or ()))
    if miss:
        return False, f"缺 {len(miss)} 檔：{miss}"
    if tx_meta is None:
        return False, "台指期 meta 不存在"
    if tx_meta.get("missing_night") is True:
        return False, "台指期夜盤缺失"
    tx = _to_date(tx_meta.get("date"))
    today = _tpe(now_utc).date()
    if tx is None or tx < today:
        return False, f"台指期只到 {tx}，應有 {today}"
    return True, f"國際總經已是 {ref} 收盤、{len(all_symbols)} 檔齊、夜盤到齊"


def chip_fresh(dates: dict[str, date | None], now_utc: datetime) -> tuple[bool, str]:
    """dates = {"foreign_futures": 最大日期, "inst_flow": 最大日期}；兩個都 >= expected_chip_date 才 True。"""
    exp = expected_chip_date(now_utc)
    late = {k: v for k, v in dates.items() if v is None or _to_date(v) < exp}
    if late:
        return False, f"籌碼落後（應有 {exp}）：" + "、".join(f"{k}={v}" for k, v in late.items())
    return True, f"籌碼已到 {exp}"


def decide(workflow: str, event: str, source: str | None, now_utc: datetime, *,
           fresh: tuple[bool, str] | None = None,
           last_dispatch_success_utc: datetime | None = None) -> tuple[bool, str]:
    """回傳 (要不要跑, 中文理由)。規則依序見任務書 2a。"""
    if workflow not in WORKFLOWS:
        raise ValueError(f"未知 workflow：{workflow}")
    alarm = source == "alarm"
    if event == "workflow_dispatch" and not alarm:
        return True, "手動觸發，照跑"
    if workflow in ("global_macro", "chip_flow_evening") and (event == "schedule" or alarm):
        if fresh is not None and fresh[0]:
            return False, f"跳過：{fresh[1]}"
        return True, f"照跑：{fresh[1]}" if fresh else "照跑：沒有新鮮度資訊"
    if event == "workflow_dispatch" and alarm:
        return True, "Cloudflare 鬧鐘班，照跑"
    if event == "schedule":
        if workflow == "heartbeat" and _tpe(now_utc).hour >= HEARTBEAT_LAST_HOUR:
            return False, f"跳過：台北 {HEARTBEAT_LAST_HOUR}:00 後的 heartbeat 備援班已無意義"
        if last_dispatch_success_utc is not None:
            win = BACKUP_WINDOW_HOURS[workflow]
            if now_utc - last_dispatch_success_utc <= timedelta(hours=win):
                return False, f"跳過：{win} 小時內 Cloudflare 班已成功（備援班不必跑）"
        return True, "備援班，近期沒有 Cloudflare 成功紀錄，照跑"
    return True, f"未知事件 {event}，照跑"
