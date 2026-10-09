"""R6：頁尾資料來源標示（舊 bundle 沒 pack_source 欄就不顯示）。"""
from reference.freshness import pack_source_label


def test_labels():
    assert pack_source_label({"pack_source": {"used": "selfhost"}}) == "資料來源：自建官方"
    assert pack_source_label({"pack_source": {"used": "upstream", "level": "fallback"}}) == "資料來源：上游（退回）"
    assert pack_source_label({"pack_source": {"used": "upstream"}}) == "資料來源：上游"


def test_missing_is_blank():
    assert pack_source_label({}) == ""
    assert pack_source_label(None) == ""
    assert pack_source_label({"pack_source": None}) == ""
