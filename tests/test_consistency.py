"""鎖住引擎、估值資料與畫面共用欄位。"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

from screener import val_card as vc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sa = importlib.import_module("streamlit_app")


class Display:
    def __init__(self):
        self.text = []
    def markdown(self, value, **kwargs):
        self.text.append(value)
    def caption(self, value, **kwargs):
        self.text.append(value)






def test_畫面不含舊名詞():
    root = Path(__file__).resolve().parents[1]
    for file in ("app/streamlit_app.py", "screener/val_card.py", "screener/detect.py"):
        tree = ast.parse((root / file).read_text(encoding="utf-8"))
        # 月營收封印頁仍使用舊估值算法。
        skip = {id(n) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name in ("_rev_view_value",)
                for n in ast.walk(f)}
        for node in ast.walk(tree):
            if id(node) in skip or (isinstance(node, ast.Constant) and node.value == "沒有成長價"):
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 文件字串與註解不會顯示；只檢查可執行字串。
                if any(isinstance(parent, ast.Expr) and parent.value is node for parent in ast.walk(tree)):
                    continue
                if '<style>' in node.value:
                    continue
                assert not any(word in node.value for word in ("F4", "前瞻股價", "已公布 TTM", "年化試算", "今年預估", "成長價", "12 個月基準價", "EPS_NC", "滾動獲利估值價", "已公布獲利估值價", "近四季實際")), (file, node.lineno, node.value)


def test_畫面不自己算推導():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app/streamlit_app.py").read_text(encoding="utf-8"))
    names = {"_valuation_block", "_view_table", "_price_tri", "_river_chart"}
    for func in tree.body:
        if not isinstance(func, ast.FunctionDef) or func.name not in names:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                pytest.fail(f"{func.name}:{node.lineno} 畫面自行相乘")






