"""排程防呆（2026-10-07 為了避開 GitHub 整點擁擠而把所有 cron 改分鐘時踩到的三個坑，改成自動檢查）：
1. cron 分鐘不得是 :00、:30、:59（GitHub 在整點／半點最擁擠、延遲最嚴重）。
2. workflow 裡用「cron 字串」做判斷的地方（`github.event.schedule == '…'`、`= "…"`）寫的字串，必須真的存在於該 workflow 的 cron 清單——
   否則改了 cron 沒同步，那一步（例如 --require-fresh、每週收集）會**靜默永遠不執行**，不會報錯。
3. 同一個 repo 裡任兩條 cron 至少相隔 MIN_GAP 分鐘（同時觸發會搶 runner、搶 push）。
4.（本機才跑）若旁邊有另一個 repo（tw-hold／tw-swing 並排），兩邊合起來也要滿足第 3 條。
5. 任何 test 不得把「排程分鐘」寫死成 cron 字串以外的真實 workflow 讀取斷言——這點靠人，這裡只列在說明（10/7 test_check_daily 寫死 05:30 導致整班 skipped 的教訓）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
FORBIDDEN_MINUTES = {0, 30, 59}
MIN_GAP = 10          # 分鐘


def _crons(path: Path) -> list[str]:
    return re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M)


def _schedule_strings(path: Path) -> list[str]:
    return re.findall(r"""github\.event\.schedule[^\n]{0,12}?(?:==|=)\s*['"]([^'"]+)['"]""", path.read_text(encoding="utf-8"))


def _all(wf_dir: Path):
    for f in sorted(wf_dir.glob("*.yml")):
        for c in _crons(f):
            yield f.name, c


def _minute_of_day(cron: str) -> int:
    m, h = cron.split()[:2]
    return int(h) * 60 + int(m)


def _min_gap(items) -> tuple[int, tuple]:
    pts = sorted((_minute_of_day(c), n, c) for n, c in items)
    best = (10**9, ())
    for a, b in zip(pts, pts[1:] + [(pts[0][0] + 1440, pts[0][1], pts[0][2])]):
        if b[0] - a[0] < best[0]:
            best = (b[0] - a[0], (a[1], a[2], b[1], b[2]))
    return best


def test_cron_minutes_avoid_round_times():
    bad = [(n, c) for n, c in _all(WF) if int(c.split()[0]) in FORBIDDEN_MINUTES]
    assert not bad, f"cron 不得在 :00／:30／:59（GitHub 整點半點最擁擠）：{bad}"


def test_cron_strings_used_in_conditions_exist_in_cron_list():
    for f in sorted(WF.glob("*.yml")):
        used, have = _schedule_strings(f), set(_crons(f))
        missing = [u for u in used if u not in have]
        assert not missing, f"{f.name} 用 cron 字串做判斷，但 {missing} 不在它的 cron 清單 {sorted(have)}——改 cron 時沒同步，那一步會靜默永遠不跑"


def test_crons_in_repo_are_spaced():
    gap, who = _min_gap(_all(WF))
    assert gap >= MIN_GAP, f"兩條排程相隔只有 {gap} 分鐘：{who}"


def test_crons_across_sibling_repos_are_spaced():
    sibs = [p for p in (ROOT.parent / "tw-hold", ROOT.parent / "tw-swing") if (p / ".github" / "workflows").is_dir()]
    if len(sibs) < 2:
        pytest.skip("另一個 repo 不在旁邊（CI 環境），只在本機檢查跨 repo 間隔")
    items = [(f"{p.name}/{n}", c) for p in sibs for n, c in _all(p / ".github" / "workflows")]
    gap, who = _min_gap(items)
    assert gap >= MIN_GAP, f"跨 repo 兩條排程相隔只有 {gap} 分鐘：{who}"
