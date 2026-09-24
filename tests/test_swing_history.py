"""`build_lists._update_swing_history()` 的連續天數邏輯——2026-09-24 Opus 審核
抓到三個邊界案例（同日重跑內容不同、資料日期倒退、候選池因缺資料回空），
這裡把它們固定成回歸測試，不用碰真 bundle。"""
from __future__ import annotations

import json
from datetime import date

import build_lists


def _hist_file(tmp_path, monkeypatch):
    monkeypatch.setattr(build_lists, "DERIVED", tmp_path)
    return tmp_path / "swing_history.json"


def _pool(*tickers):
    return [{"ticker": tk} for tk in tickers]


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_連續三天累加(tmp_path, monkeypatch):
    p = _hist_file(tmp_path, monkeypatch)
    build_lists._update_swing_history(_pool("A", "B"), date(2026, 1, 1), "候選池 2 檔")
    build_lists._update_swing_history(_pool("A", "B"), date(2026, 1, 2), "候選池 2 檔")
    pool3 = _pool("A", "B")
    build_lists._update_swing_history(pool3, date(2026, 1, 3), "候選池 2 檔")
    by_tk = {c["ticker"]: c for c in pool3}
    assert by_tk["A"]["streak_days"] == 3
    assert by_tk["A"]["first_seen"] == "2026-01-01"
    assert _load(p)["_asof"] == "2026-01-03"


def test_退出後重新進榜從1重算(tmp_path, monkeypatch):
    _hist_file(tmp_path, monkeypatch)
    build_lists._update_swing_history(_pool("A"), date(2026, 1, 1), "候選池 1 檔")
    build_lists._update_swing_history(_pool("A"), date(2026, 1, 2), "候選池 1 檔")
    build_lists._update_swing_history(_pool(), date(2026, 1, 3), "候選池 0 檔")  # A 退出
    pool4 = _pool("A")  # A 重新進榜
    build_lists._update_swing_history(pool4, date(2026, 1, 4), "候選池 1 檔")
    assert pool4[0]["streak_days"] == 1
    assert pool4[0]["first_seen"] == "2026-01-04"


def test_同日重跑內容不同不會腰斬連續天數(tmp_path, monkeypatch):
    """Opus 抓到的漏洞：D1 有 A/B、D2 有 A/B、D3 第一次跑漏了 B、D3 第二次跑
    補回 B——B 的連續天數應該是 3（D1/D2/D3 都在），不能因為 D3 當天重跑一次
    就被腰斬成 1。"""
    _hist_file(tmp_path, monkeypatch)
    build_lists._update_swing_history(_pool("A", "B"), date(2026, 1, 1), "候選池 2 檔")
    build_lists._update_swing_history(_pool("A", "B"), date(2026, 1, 2), "候選池 2 檔")
    build_lists._update_swing_history(_pool("A"), date(2026, 1, 3), "候選池 1 檔")  # 漏 B
    pool3b = _pool("A", "B")
    build_lists._update_swing_history(pool3b, date(2026, 1, 3), "候選池 2 檔")  # 補回 B
    by_tk = {c["ticker"]: c for c in pool3b}
    assert by_tk["B"]["streak_days"] == 3
    assert by_tk["A"]["streak_days"] == 3


def test_日期倒退不更新紀錄(tmp_path, monkeypatch):
    p = _hist_file(tmp_path, monkeypatch)
    build_lists._update_swing_history(_pool("A"), date(2026, 1, 5), "候選池 1 檔")
    state_before = _load(p)
    pool_old = _pool("A")
    build_lists._update_swing_history(pool_old, date(2026, 1, 3), "候選池 1 檔")  # 倒退
    assert _load(p) == state_before                      # 檔案完全沒被動過
    assert pool_old[0]["streak_days"] == 1                # 沿用舊紀錄帶出去，不是憑空算


def test_缺資料回空不清空連續紀錄(tmp_path, monkeypatch):
    _hist_file(tmp_path, monkeypatch)
    build_lists._update_swing_history(_pool("A"), date(2026, 1, 1), "候選池 1 檔")
    build_lists._update_swing_history([], date(2026, 1, 2),
                                      "候選池缺料（需 prices_adj / index_0050 / chips / revenue）")
    pool3 = _pool("A")
    build_lists._update_swing_history(pool3, date(2026, 1, 3), "候選池 1 檔")
    assert pool3[0]["streak_days"] == 2                   # 缺料那天被跳過，不是斷點
    assert pool3[0]["first_seen"] == "2026-01-01"


def test_真的空頭週回空仍會清空(tmp_path, monkeypatch):
    """跟上一個測試對照：資料本身沒問題、策略判斷真的回空（`pool_note` 不是
    「缺料」開頭），連續紀錄應該正常歸零——這是策略邏輯的事，不是資料問題。"""
    _hist_file(tmp_path, monkeypatch)
    build_lists._update_swing_history(_pool("A"), date(2026, 1, 1), "候選池 1 檔")
    build_lists._update_swing_history([], date(2026, 1, 2), "候選池 0 檔（CANSLIM ∩ …）")
    pool3 = _pool("A")
    build_lists._update_swing_history(pool3, date(2026, 1, 3), "候選池 1 檔")
    assert pool3[0]["streak_days"] == 1
    assert pool3[0]["first_seen"] == "2026-01-03"
