【tw-hold】D:\g\claude\tw-hold — 淺色 A／深色 C 雙主題（任務書 v1，2026-11-16 Opus）

## 背景（不用再查）
朋友反映淡字看不清（`--thc-faint` 對白底只有 2.98）。使用者拍板：淺色用「北歐靜謐・加深版」(A)、深色用「深色看盤」(C)，讓使用者在 Streamlit 右上「⋮ → Settings」切換。**預設要淺色 A**；若 Streamlit 有 `[theme.light]`＋`[theme.dark]` 時做不到預設淺色（只能跟系統），照跟系統做、在回報註明，不停。

## 要讀的檔案（只准讀這些）
- `.streamlit/config.toml`（全檔）
- `app/streamlit_app.py:790-1145`（`_CSS`、`_inject_css`）、`:1110-1130`（雷達徽章 rgba）、`:1978-1987`（`_chart`）
- `app/stockcharts.py:25-50`（`_LAYOUT`），以及用 `grep -nE '#[0-9A-Fa-f]{6}'` 找出的各行（約 14 處）
- Streamlit 1.60 原始碼只准查：`site-packages/streamlit/elements/html.py`（`st.html(..., unsafe_allow_javascript=True)`）、`config.py` 裡 theme.light／theme.dark 說明

## 框架（不准改）
1. **CSS 色源仍唯一在 `_CSS` 的 `:root`**：`:root{…}` 換成下面 A 值；新增 `:root[data-thc="dark"]{…}` 放 C 值。其他規則一律 `var(--thc-*)`；`_CSS` 裡剩下寫死的色（例 858–859 行 `rgba(92,122,114,…)`）改成變數（需要半透明就比照 `--thc-up-rgb` 加 `--thc-accent-rgb`）。
2. **怎麼知道現在是深色**：不在 Python 判斷（`st.context.theme` 官方註明首載與切換時會錯）。改在 `_inject_css` 同一次輸出之外，**整個 app 只注入一次** `st.html(<script>, unsafe_allow_javascript=True)`：讀 `.stApp` 的計算後背景色亮度 < 0.5 → `document.documentElement.dataset.thc="dark"`，否則 `"light"`；用 `MutationObserver`（觀察 `.stApp` 的 style/class 與 `<head>` 子節點）＋每 1 秒的保底輪詢，切主題不用重跑頁面就換色。這個 st.html 不能讓分頁列下面多一格空白（見 `_inject_css` docstring 的 flex gap 問題；必要時把元素高度設 0 或放進已有容器）。
3. **config.toml**：`[theme]` 留共用項（font）；`[theme.light]`＝A 的 base/primary/background/secondaryBackground/text；`[theme.dark]`＝C 的對應值。
4. **圖表不判斷主題**：`_LAYOUT` 拿掉 `template="plotly_white"` 與 `font.color`（讓 Streamlit 主題決定字色、格線）；`stockcharts.py` 寫死的線色、K 棒色一律換成下面「圖表色」（兩種底色都看得到），集中成模組頂端常數 `CHART_COLORS = {...}`，各處引用。不准在圖表裡依主題分支。

## 色票（照抄）
A（淺色，`:root`）：
```
--thc-bg:#EEF1F4; --thc-surface:#FFFFFF; --thc-surface2:#F5F7F9; --thc-line:#E4E8EC;
--thc-ink:#2B333B; --thc-soft:#4E5A64; --thc-faint:#5E6A75; --thc-accent:#4F6E66; --thc-accent-rgb:79,110,102;
--thc-good:#4F6E66; --thc-good-bg:#DEE9E6; --thc-warn:#7A5A4F; --thc-warn-bg:#F1E3DF;
--thc-neutral:#526A7A; --thc-neutral-bg:#DEE7EC; --thc-flag:#7A5A4F; --thc-bad:#B5453B;
--thc-up:#B8463A; --thc-down:#3B6E65; --thc-up-rgb:184,70,58;
```
C（深色，`:root[data-thc="dark"]`，同一組變數名全部重定義）：
```
--thc-bg:#11161C; --thc-surface:#1A2129; --thc-surface2:#202832; --thc-line:#2A333D;
--thc-ink:#E8ECF1; --thc-soft:#B2BCC7; --thc-faint:#8F9BA8; --thc-accent:#4FA3A5; --thc-accent-rgb:79,163,165;
--thc-good:#4FA3A5; --thc-good-bg:#173236; --thc-warn:#D49A4A; --thc-warn-bg:#3A2C18;
--thc-neutral:#7FA3BA; --thc-neutral-bg:#1C2A35; --thc-flag:#D49A4A; --thc-bad:#F07A6E;
--thc-up:#FF6B5E; --thc-down:#3CC48A; --thc-up-rgb:255,107,94;
```
config.toml：light＝`base="light"`, primary `#4F6E66`, background `#EEF1F4`, secondaryBackground `#FFFFFF`, text `#2B333B`；dark＝`base="dark"`, primary `#4FA3A5`, background `#11161C`, secondaryBackground `#1A2129`, text `#E8ECF1`。
圖表色 `CHART_COLORS`：`up #D2574A`、`down #3E9A86`、`ink_line #7D8A96`（原 #2B333B 的線）、`warn #B07A5E`（原 #8A6A5F）、`accent #5E9488`（原 #5C7A72）。其他寫死色依語意對到這五個；對不到就停下問。

**注意**：卡片若有用 `--thc-good-bg` 等當底、上面再疊 `--thc-ink` 字，深色下照樣成立（C 的 bg 都是深色）。若發現某處用 `color:#fff` 之類假設淺底的寫法，改成變數。

## 要做的事
1. 照框架改 `.streamlit/config.toml`、`app/streamlit_app.py`、`app/stockcharts.py`。
2. 新測試 `tests/test_theme_tokens.py`（名稱照抄）：
   - `test_兩套色票變數名相同`：解析 `_CSS`，`:root` 與 `:root[data-thc="dark"]` 的 `--thc-*` 名稱集合相等
   - `test_文字對比度達標`：A 的 ink/soft/faint/accent/warn/neutral/up/down/bad 對 `--thc-surface` 與 `--thc-bg` 都 ≥4.5；C 同組對 C 的 surface 與 bg 都 ≥4.5（WCAG 相對亮度公式，自己寫在測試裡）
   - `test_CSS無寫死色`：`_CSS` 去掉兩個 `:root` 區塊後，不得再出現 `#xxxxxx` 或 `rgba(數字`
   - `test_圖表色兩種底色都看得到`：`CHART_COLORS` 每色對 `#FFFFFF` 與 `#1A2129` 都 ≥3.0；且 `stockcharts.py` 除 `CHART_COLORS` 定義外不再出現 `#xxxxxx`
3. 截圖：本機 `streamlit run app/streamlit_app.py`，用 `D:\prog\pw-venv\Scripts\python.exe`（Playwright 已裝）寫一次性腳本，**淺、深各一輪**（深色用 Settings 選單切，或 `emulate_media(color_scheme="dark")`＋跟系統；兩種都試，回報哪種有效），每輪截：價值、定存、長波段、短線、個股查詢（輸入 2330，含估值卡展開與 K 線圖）、多軌體檢。寬 1280 與 390 各一張。存 `D:\g\claude\tmp\theme_shots\`（檔名 `{light|dark}_{頁}_{寬}.png`）。另截一組「從淺切到深、不重新整理」的個股頁，證明不用重跑就換色。

## 不准做
不改版面、字級、間距、文字內容；不動任何計算；不改其他檔；不加套件（requirements 不動）；一次性腳本放 worktree 內、結束前刪（截圖例外，放上面指定目錄）。介面覺得不對就停下回報（最多問 2 次）。

## PROOF_CMD（tw-hold 根目錄）
```
python -m pytest -q tests/test_theme_tokens.py && python -m pytest -q
```
預期：新測試 4 passed；全套 ≥1,466 passed（目前 1,462＋新 4）、0 failed。

## 回報（寫在你的最終訊息，不貼程式碼）
- commit 清單（worktree 分支，不 push、不合併）
- PROOF_CMD 數字
- 預設是淺色還是跟系統；Settings 切換是否不用重新整理就換色
- 截圖目錄與張數；你自己看到深色下仍不好讀的地方（頁／元素）
- 需要決定的事
