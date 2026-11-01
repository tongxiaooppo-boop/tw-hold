"""固定案例回歸：對 build_classification.py 的輸出 json 檢查約 30 檔的類型（2026-11-01 sol／Opus 兩輪定案的預期）。

用法：python build_classification.py --out X.json --no-history && python research/classify_cases_2026-11-01/check_cases.py X.json
預期值是「規格要的結果」，不是「現況」；不符就是回歸，先看規格再決定改程式或改預期（改預期要寫理由）。
"""
import json, sys

EXPECT = {
    # 先驗排除表：基礎建設、航太不是景氣循環
    "2633": "normal", "2634": "normal",
    # 航運（海運、航空）循環
    "2603": "cyclical", "2609": "cyclical", "2615": "cyclical", "2605": "cyclical",
    "2612": "cyclical", "2618": "cyclical", "2610": "cyclical",
    # 傳統循環產業先驗
    "2002": "cyclical", "1301": "cyclical",
    # 記憶體：南亞科景氣反彈不是併購，循環先判
    "2408": "cyclical", "2337": "cyclical", "2344": "cyclical", "8299": "cyclical", "3006": "cyclical",
    # 疑似循環不改類型
    "3443": "normal", "3008": "normal",
    # 成長股
    "2330": "growth", "2345": "growth", "2383": "growth", "3017": "growth", "6669": "growth",
    # 高價股放寬第③條後新進高成長（記憶體模組廠由三價階段高峰閘門處理，不在分類擋）
    "2451": "growth", "3260": "growth", "5289": "growth",
    # 川湖最低年增 −26%，差 1 個百分點沒過 −25% 門檻（刻意記錄：門檻邊界）
    "2059": "normal",
    # 聯發科：振幅過、輔助過 → 循環
    "2454": "cyclical",
}

def main(path):
    d = {r["ticker"]: r for r in json.load(open(path, encoding="utf-8"))["stocks"]}
    bad = 0
    for t, want in EXPECT.items():
        got = d.get(t, {}).get("type")
        if got != want:
            bad += 1
            print(f"不符 {t} {d.get(t, {}).get('name')}: 預期 {want}，實際 {got}")
    print(f"{len(EXPECT) - bad}/{len(EXPECT)} 相符")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
