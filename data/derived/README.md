# data/derived/

**刻意進版控。** 每日 tw-hold Action 重算後 commit 這裡的 JSON，Streamlit app
只讀這個目錄（雲端運算量趨近 0，PRD §8）。

| 檔 | 內容 | 版控 |
| :--- | :--- | :--- |
| `value_list.json` | 價值清單（成分 + 因子 + 買價/不推薦 + 新進/移除） | ✅ |
| `deposit_list.json` | 定存清單 | ✅ |
| `swing_list.json` | 長波段清單（每日重算） | ✅ |
| `_meta.json` | 資料日期、bundle schema_version、上次重算時間 | ✅ |
| `factors_*.parquet` | 完整因子表（大） | ❌ `.gitignore` → 放 Release |

清單 JSON 是「新進/移除」diff 的來源——**讀上一期 JSON，不靠 git diff**（PRD §10 v2.1）。
