"""全站名詞（docs/val2/upgrade_guide.md §15-1／15-2／15-3；P4_spec §8）。框架由 Opus 定，實作者（P4c）不得改。

P4c 要做的事＝改 app/、screener/、build_*.py 的畫面文字，讓本檔全過。實作者只准動本檔的 WHITELIST
（每條要寫理由，且只准放「程式內部訊息」或「資料 key：…」——寫進／讀自 data/ 檔案的中文 key，改了會斷資料，
畫面要另行轉換）與 OUTSIDE_OK（估值名詞在 val_view 以外合法出現的地方）；
RULES、掃描法、排除範圍、測試本身都不准改。覺得某條規則誤判，停下回報 Opus。

掃描法（同 terms/ui_strings.txt 的抽法，改用 AST 精確化）：
- 收集每個檔案中「含中文」的字串常數；f-string 的 {運算式} 換成「{}」後整串比對。
- 不收：docstring（模組／類別／函式第一個字串敘述）、註解。
- 自動視為程式內部訊息、不收：logging／logger／log 的呼叫、print、warnings.warn、raise 例外的訊息。
- 不收：CSS（含 "<style" 的字串）。
- 排除：月營收封印頁（app/valuation.py 整檔、streamlit_app 的 _rev_view_value／_rev_view_hold），解封時移除排除。

只改畫面文字：不改算法、schema 欄名、JSON key；build_*.py 產出的字串改了以後，data/derived 已 commit 的 JSON
不要手改（等 CI 重跑）。
"""
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import val_view as vv                                        # noqa: E402
from test_val2_card import CLS, MH, PX, RH, card, _events  # noqa: E402,F401

CJK = re.compile(r"[一-鿿]")


# ── 規則（§15-1／15-2 的「禁用（畫面）」欄） ─────────────────────

@dataclass(frozen=True)
class Rule:
    id: str
    pattern: str        # re.search，對單一字串
    use: str            # 統一寫法
    flags: int = 0


RULES = (
    # 15-1 估值與獲利
    Rule("TTM", r"TTM", "近 4 季 EPS／已公布 4 季 EPS／近 4 季配息率", re.I),
    Rule("四季舊稱", r"過去\s*4\s*季|近四季|4\s*季實際|未來\s*4\s*季|EPS_NC", "近 4 季 EPS／已公布 4 季 EPS／前瞻 4 季 EPS"),
    Rule("前瞻EPS不帶4季", r"前瞻\s*EPS(?!\s*年增)", "前瞻 4 季 EPS（前瞻 EPS 年增 可用）"),
    Rule("季類別", r"推算|成長預測|沿用前瞻|(?<!不是)(?<!非)(?<!不)預測", "實際／試算（「試算不是預測」這類否定句可用）"),
    Rule("舊三價名", r"類型參考三價|補位價|成長價|情境價", "三價（相對自身歷史）／前瞻便宜價…"),
    Rule("購買區間舊稱", r"購買參考價|買進區間|買入區間", "購買區間；清單用 價值買價上下限／定存買價上下限"),
    Rule("百分位代號", r"(?<![A-Za-z0-9])P[258]0(?![0-9])|歷史股價\s*\d+\s*%", "歷史 20%／50%／80% 位置的本益比"),
    Rule("合理EPS", r"合理\s*EPS", "反推 EPS 門檻"),
    Rule("本益比英文", r"(?<![A-Za-z])(PE|PER|PB|PBR|per)(?![A-Za-z])", "本益比／股價淨值比"),
    Rule("費用率", r"費損率|(?<!營業)費用率", "營業費用率"),
    Rule("可信度舊稱", r"[高中低]可信度|降級", "資料／股數基準／歷史可比性／試算：正常／提醒／停用／未檢查"),
    # 15-2 成長、價格、風控
    Rule("YoY", r"YoY", "最新月營收年增／季 EPS 年增…", re.I),
    Rule("累計年增", r"累計年增", "今年累計營收年增"),
    Rule("CAGR", r"CAGR|(?<!複合)成長率", "近 5 年 EPS 年複合成長（期間＋指標都寫）"),
    Rule("清單買價舊稱", r"便宜門檻|估值買價|估值上緣", "價值買價／價值上緣／定存買價"),
    Rule("停損參考", r"停損參考", "週線進場停損／進場停損（候選池）"),
    Rule("持股停損不帶週線", r"(?<!週線)持股停損", "週線持股停損"),
    Rule("進場停損不帶出處", r"(?<!週線)進場停損(?!（候選池）)", "週線進場停損（個股頁）／進場停損（候選池）"),
    Rule("Minervini", r"Minervini", "趨勢模板 8 項（候選池）／趨勢模板 7 項（體檢）"),
    Rule("年線指200日", r"200\s*日[線均]?[^，。；\n]{0,4}年線|年線[^，。；\n]{0,3}200", "年線（240 日）；200 日線"),
)

# 無法機械判斷、P4c 要人工掃過並在回報列出處理結果的（不進測試）：
MANUAL = (
    "裸稱「年增」「月增」（要寫 最新月營收年增／月營收月增／季 EPS 年增…）",
    "本季營收年增（已公布 n 個月）被寫成「近 3 月年增」",
    "裸稱「停損」「支撐」「壓力」「殖利率」",
    "不帶日期的「股價」「收」",
    "週線市況（多頭／震盪／空頭）與均線位置（偏多／貼近／偏空）混用",
    "候選池頁以外提到「移動停損」要寫 移動停損（候選池）（候選池頁內上下文已清楚，可不加）",
    "法人淨買超單位：張、股、金額混用",
    "停損模擬統計沒寫是哪一種停損",
    "有效月數與虧損月數互相代稱",
    "上修：換季／財報替換顯示 0%",
)

# 程式內部訊息白名單：(檔案, 規則 id, 字串片段, 理由)。框架時為空；P4c 只准加內部訊息（例外文字、CI 摘要等）。
WHITELIST: tuple[tuple[str, str, str, str], ...] = ()

EXCLUDE_FILES = {"app/valuation.py": "月營收封印頁專用，解封時移除排除"}
EXCLUDE_FUNCS = {("app/streamlit_app.py", "_rev_view_value"): "月營收封印頁",
                 ("app/streamlit_app.py", "_rev_view_hold"): "月營收封印頁"}
INTERNAL_ROOTS = {"logging", "logger", "log", "_log", "LOG", "warnings"}
INTERNAL_FUNCS = {"print"}


# ── 掃描 ─────────────────────────────────────────────────────

def scan_files() -> list[Path]:
    files = sorted((ROOT / "app").glob("*.py")) + sorted((ROOT / "screener").glob("*.py")) + sorted(ROOT.glob("build_*.py"))
    return [f for f in files if f.relative_to(ROOT).as_posix() not in EXCLUDE_FILES]


def _call_is_internal(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id in INTERNAL_FUNCS
    while isinstance(f, ast.Attribute):
        f = f.value
    return isinstance(f, ast.Name) and f.id in INTERNAL_ROOTS


def _text(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def ui_strings(path: Path) -> list[tuple[int, str]]:
    """回傳 [(行號, 字串)]：含中文、非 docstring、非內部訊息、非排除函式。"""
    rel = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()

    def mark(node):
        for sub in ast.walk(node):
            skip.add(id(sub))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and _text(body[0].value) is not None:
                mark(body[0])
            if not isinstance(node, ast.Module) and (rel, node.name) in EXCLUDE_FUNCS:
                mark(node)
        elif isinstance(node, ast.Call) and _call_is_internal(node):
            mark(node)
        elif isinstance(node, ast.Raise) and node.exc is not None:
            mark(node.exc)

    out = []
    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(node, ast.Constant) and id(node) in _fstring_parts(tree):
            continue
        s = _text(node)
        if s and CJK.search(s) and "<style" not in s:
            out.append((node.lineno, s))
    return sorted(out)


_FS_CACHE: dict[int, set[int]] = {}


def _fstring_parts(tree) -> set[int]:
    """f-string 內部的 Constant 片段已併在 JoinedStr 裡，不重複收。"""
    key = id(tree)
    if key not in _FS_CACHE:
        _FS_CACHE[key] = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)
                          for v in ast.walk(n) if v is not n and isinstance(v, ast.Constant)}
    return _FS_CACHE[key]


def _whitelisted(rel: str, rule: Rule, s: str) -> bool:
    return any(f == rel and r == rule.id and frag in s for f, r, frag, _ in WHITELIST)


def violations() -> list[str]:
    out = []
    for path in scan_files():
        rel = path.relative_to(ROOT).as_posix()
        for line, s in ui_strings(path):
            for rule in RULES:
                m = re.search(rule.pattern, s, rule.flags)
                if m and not _whitelisted(rel, rule, s):
                    out.append(f"{rel}:{line} [{rule.id}] 「{m.group(0)}」→ {rule.use}｜{s[:60]!r}")
    return out


# ── 掃描法本身的測試（框架時就要過） ───────────────────────────

def _scan_src(tmp_path, src: str, name="app/x.py"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    global ROOT
    old, ROOT = ROOT, tmp_path
    try:
        return [s for _, s in ui_strings(p)]
    finally:
        ROOT = old


def test_掃描法_收畫面字串_不收docstring與內部訊息(tmp_path):
    src = '''"""模組說明 TTM"""
import logging
def f(x):
    """函式說明 PE"""
    logging.warning("內部 TTM %s", x)
    print(f"進度 {x} PE")
    if x:
        raise ValueError(f"例外 {x} TTM")
    st.write(f"近 4 季 EPS {x:.2f} 元")
    return "合理價" + "english only"
'''
    assert _scan_src(tmp_path, src) == ["近 4 季 EPS {} 元", "合理價"]


def test_掃描法_排除封印函式(tmp_path):
    src = 'def _rev_view_value(r):\n    st.write("TTM 年增")\ndef g():\n    st.write("TTM 年增")\n'
    assert _scan_src(tmp_path, src, "app/streamlit_app.py") == ["TTM 年增"]


@pytest.mark.parametrize("text,rule_id", [
    ("TTM EPS", "TTM"), ("配息率 ttm", "TTM"), ("過去 4 季", "四季舊稱"), ("未來4季", "四季舊稱"),
    ("前瞻 EPS 5.2", "前瞻EPS不帶4季"), ("推算", "季類別"), ("成長預測", "季類別"), ("營收預測", "季類別"),
    ("補位價", "舊三價名"), ("買進區間", "購買區間舊稱"), ("P50", "百分位代號"), ("歷史股價 20%", "百分位代號"),
    ("合理 EPS", "合理EPS"), ("PE 12 倍", "本益比英文"), ("PBR", "本益比英文"), ("費用率", "費用率"),
    ("低可信度", "可信度舊稱"), ("月營收 YoY", "YoY"), ("累計年增", "累計年增"), ("CAGR", "CAGR"),
    ("成長率", "CAGR"), ("估值買價", "清單買價舊稱"), ("停損參考位", "停損參考"), ("持股停損", "持股停損不帶週線"),
    ("進場停損", "進場停損不帶出處"), ("Minervini 趨勢模板", "Minervini"),
    ("200 日年線", "年線指200日"),
])
def test_規則_抓得到禁用寫法(text, rule_id):
    hit = [r.id for r in RULES if re.search(r.pattern, text, r.flags)]
    assert rule_id in hit, hit


@pytest.mark.parametrize("text", [
    "近 4 季 EPS", "已公布 4 季 EPS", "前瞻 4 季 EPS", "前瞻 EPS 年增", "試算不是預測、不是目標價", "實際／試算",
    "購買區間 2,034～2,592", "歷史 20% 位置的本益比", "反推 EPS 門檻", "本益比（自建）", "股價淨值比",
    "營業費用率", "今年累計營收年增", "近 5 年 EPS 年複合成長率", "價值買價", "定存買價", "週線持股停損",
    "週線進場停損", "進場停損（候選池）", "移動停損（候選池）", "趨勢模板 8 項（候選池）", "年線（240 日）",
    "200 日線", "ROE 25.0%", "PCF", "前瞻便宜價",
])
def test_規則_統一寫法不誤判(text):
    assert [r.id for r in RULES if re.search(r.pattern, text, r.flags)] == []


def test_白名單每條都有理由且用得到():
    for f, t, frag, why in OUTSIDE_OK:
        assert why.strip() and t in VAL_ONLY, (f, frag)
        assert any(frag in s and t in s for _, s in ui_strings(ROOT / f)), f"OUTSIDE_OK 沒用到：{f} {frag}"
    for f, rid, frag, why in WHITELIST:
        assert why.strip(), (f, frag)
        assert rid in {r.id for r in RULES}, rid
        path = ROOT / f
        assert path.exists(), f
        assert any(frag in s for _, s in ui_strings(path)), f"白名單沒用到：{f} {frag}"


# ── §15-3 ────────────────────────────────────────────────────

def test_glossary_禁用寫法():
    bad = violations()
    assert not bad, f"{len(bad)} 處禁用寫法：\n" + "\n".join(bad)


def _cards():
    return {
        "A_前瞻上調": card(rh=RH(3.0, 3.1, 3.2)),
        "A_一般": card(),
        "A_現價高於上緣": card(px=PX(60.0)),
        "A_循環": card(cls=CLS("cyclical")),
        "B": card(mh=MH(valid_until="2021-12")),
    }


@pytest.mark.parametrize("name", list(_cards()))
def test_glossary_同名同源(name):
    """一個名詞＝一個引擎欄位：卡片上的「近 4 季 EPS」「合理價」「購買區間」只從這三個欄位來，
    三個展開區只要出現這三個名詞的 📌，數字跟卡片一字不差。（估值卡沒有「複製給 AI」匯出；日後加了要一起比。）"""
    c = _cards()[name]
    pins = vv.card_view(c, "9999 測試", None).pins
    src = {
        "近 4 季 EPS": vv.fmt_eps(((c.get("eps") or {}).get("ttm") or {}).get("eps")),
        "合理價": vv.fmt_px((c.get("prices") or {}).get("fair")),
        "購買區間": vv.fmt_range(c["buy_range"]["low"], c["buy_range"]["high"]) if c.get("buy_range") else "—",
    }
    for label, want in src.items():
        if want in ("—", "—～—"):
            assert label not in pins, label
            continue
        assert pins.get(label) == want, (label, pins.get(label), want)
        cells = [x for t in vv.detail_tables(c) + vv.explain_tables(c) + vv.trial_tables(c) for r in t.rows
                 if any(str(y).startswith(f"＝卡片『{label}』") for y in r) for x in r if str(x).startswith(vv.PIN)]
        assert cells, label
        assert all(x == f"{vv.PIN} {want}" or x.startswith(f"{vv.PIN} {want} ") for x in cells), (label, cells)


# 估值專用名詞只准由估值模組群產生（別的頁面用同名詞指不同數字＝名詞衝突，memory：卡片文字不能互相矛盾）。
VAL_ONLY = ("近 4 季 EPS", "前瞻 4 季 EPS", "合理價", "便宜價", "昂貴價", "購買區間")
VAL_MODULES = {"app/val_view.py", "app/val_inputs.py", "screener/val_card.py", "screener/detect.py",
               "screener/river.py", "screener/eps_windows.py", "screener/multiples_self.py", "screener/growth.py",
               "build_multiples.py"}
# (檔案, 名詞, 字串片段, 理由)：估值模組群以外合法出現（同一個引擎欄位，或明講兩者無關）。P4c 可加，要寫理由。
OUTSIDE_OK: tuple[tuple[str, str, str, str], ...] = (
    ("app/streamlit_app.py", "購買區間", "現價在購買區間內給週線進場停損", "⑦ 讀 buy_range.where，同一欄位"),
    ("app/streamlit_app.py", "購買區間", "沒有購買區間", "⑦ 讀 card.buy_range，同一欄位"),
    ("app/streamlit_app.py", "購買區間", "現價不在購買區間", "⑦ 讀 buy_range.where，同一欄位"),
    ("app/streamlit_app.py", "合理價", "跟估值、合理價", "可買上限說明：明講跟估值卡合理價無關"),
)


def test_glossary_估值名詞只在估值模組():
    bad = []
    for path in scan_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in VAL_MODULES:
            continue
        for line, s in ui_strings(path):
            for term in VAL_ONLY:
                if term in s and not any(f == rel and t == term and frag in s for f, t, frag, _ in OUTSIDE_OK):
                    bad.append(f"{rel}:{line} 「{term}」｜{s[:60]!r}")
    assert not bad, f"{len(bad)} 處：\n" + "\n".join(bad)
