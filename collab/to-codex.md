# 【tw-hold】三方討論 r1：股本含預收股本怎麼修（版本 2026-11-22 r1）

> **專案：tw-hold（`D:\g\claude\tw-hold`，main 分支）。** 指令先 `cd D:\g\claude\tw-hold`。回報覆蓋寫到 `D:\g\claude\tw-hold\collab\from-codex.md`。
> **只讀不改**：不改任何檔案（除了 from-codex.md）、不 commit、不上網。UTF-8 無 BOM，不用 PowerShell 寫檔。

## 要讀的檔案（只准讀這些）

1. `collab/gpt/share_discuss_r1.md`（題目與背景，**照它的回答格式**）
2. 需要查證時才讀：`reference/share_basis.py` 第 155–180 行、`screener/screen.py` 第 60–105 行、`screener/detect.py` 第 170–235 行、`D:\g\claude\tw-swing\scripts\official_xbrl.py` 第 40–60 行與 `parse_report`、`research/share_events_2026-11/opus/CONCLUSION.md`

## 要做的事

照 `share_discuss_r1.md` 的 4 題獨立作答（你看得到程式，可以用來驗證或推翻背景資料，發現背景有錯直接指出）。可以跑唯讀的 python 查資料驗證，暫存檔不留。

## PROOF_CMD

```
python -c "t=open(r'D:\g\claude\tw-hold\collab\from-codex.md',encoding='utf-8').read();assert all(k in t for k in ['Q1：','Q2：','Q3：','Q4：','最大風險']);print('OK')"
```
預期：`OK`

## 回報（覆蓋 `collab/from-codex.md`）

只放 `share_discuss_r1.md` 規定的回答格式，≤ 600 字。
