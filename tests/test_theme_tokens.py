"""雙主題色票：變數對得上、文字對比度達標、_CSS 無寫死色、圖表色兩種底色都看得到。"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, "app")


def _load_css() -> str:
    """從 streamlit_app.py 原始碼取出 _CSS（不 import app，避免啟動 Streamlit）。"""
    src = open("app/streamlit_app.py", encoding="utf-8").read()
    a = src.index('_CSS = """')
    b = src.index('"""', a + 10)
    return src[a:b]


def _blocks(css: str):
    light = re.search(r":root\{(.*?)\}", css, re.S)
    dark = re.search(r':root\[data-thc="dark"\]\{(.*?)\}', css, re.S)
    assert light and dark
    return light, dark


def _vars(body: str) -> dict:
    return dict(re.findall(r"(--thc-[a-z0-9-]+)\s*:\s*([^;]+);", body))


def _lum(hexc: str) -> float:
    h = hexc.lstrip("#")
    ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_兩套色票變數名相同():
    light, dark = _blocks(_load_css())
    lv, dv = _vars(light.group(1)), _vars(dark.group(1))
    assert set(dv) <= set(lv)
    assert {k for k in lv if k not in ("--thc-sans", "--thc-mono")} == set(dv)


def test_文字對比度達標():
    light, dark = _blocks(_load_css())
    names = ["ink", "soft", "faint", "accent", "warn", "neutral", "up", "down", "bad"]
    for body in (light.group(1), dark.group(1)):
        v = _vars(body)
        for n in names:
            for bg in ("surface", "bg"):
                c = _contrast(v[f"--thc-{n}"].strip(), v[f"--thc-{bg}"].strip())
                assert c >= 4.5, (n, bg, round(c, 2))


def test_CSS無寫死色():
    css = _load_css()
    for m in (re.search(r":root\{.*?\}", css, re.S),
              re.search(r':root\[data-thc="dark"\]\{.*?\}', css, re.S)):
        css = css.replace(m.group(0), "")
    assert not re.findall(r"#[0-9A-Fa-f]{6}\b", css)
    assert not re.search(r"rgba\(\s*\d", css)


def test_圖表色兩種底色都看得到():
    import stockcharts
    for name, c in stockcharts.CHART_COLORS.items():
        for bg in ("#FFFFFF", "#1A2129"):
            assert _contrast(c, bg) >= 3.0, (name, bg)
    src = open("app/stockcharts.py", encoding="utf-8").read()
    a = src.index("CHART_COLORS = {")
    b = src.index("}", a)
    rest = src[:a] + src[b:]
    assert not re.findall(r"#[0-9A-Fa-f]{6}\b", rest)
