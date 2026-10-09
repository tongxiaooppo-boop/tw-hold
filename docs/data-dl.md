# data-dl.md — 免費股票數據／清洗修正／新聞：books 全部 repo 盤點總整理

> 2026-10-05。範圍**只限**：①免費數據怎麼取得 ②數據清洗／修正 ③產業／公司新聞怎麼取得。策略、UI、評分、回測一律不看。
> 依據：`books/` 下所有 repo 的既有分析文件（約 260KB）＋ 原始碼抽驗；沒有分析過的 new-book6（6 個）、finlab-ai-main、moneymoney 從原始碼補；
> tw-stock-scanner（上游 data_pack 產生者）直接引用 `tw-swing/docs/analysis/tw-stock-scanner-1005-analysis.md`。
> 原始盤點稿（逐 repo、逐檔案:行號）：`C:\Users\Max\AppData\Local\Temp\claude\...\scratchpad\datadl\A.md`、`B.md`（暫存；要長期保存請說）。

## 0. 怎麼讀這份文件

**我們的狀態**：✅ 已建｜🔶 部分｜⬜ 未建
**價值**：★★★ 高（補現有缺口或影響資料正確性）｜★★ 中（有用、可排進之後）｜★ 低（有則好）｜✗ 無意義／過時／有風險（不要做）
**證據等級**（很重要，別混用）：
- 【實測】2026-10-05 我們自己打過官方端點／用我們自己的資料驗證過
- 【碼】在別人 repo 的原始碼內確認
- 【文】只見於 repo 文件或註解的自述（歷史下限、筆數、實測數字都是對方寫的，**我們沒重算**）
- 【推】推測

---

## 1. 結論摘要

1. **我們的核心管線（日線、法人、融資券、除權息、集保、處置股、估值、月營收快照、TAIFEX、PCF）別人有的我們幾乎都有**；差別在於他們有的我們沒有的「公司基本資料／股本／產業」「重大訊息」「借券／當沖」「長期停牌／下市清單」「交易日曆」。
2. **本週最直接有用的新發現（已實測）**：官方有**減資**與**面額變更**的結果表可按日期區間查——TWSE `reducation/TWTAUU`（拼字就是這樣）、TPEx `bulletin/revivt`、TWSE `change/TWTB8U`。我們原本以 FinMind 逐檔輪詢減資（600 次/小時、約 5 週輪完），官方表**免逐檔、可日期區間、可 2015 起**。→ 已列為事件表的新來源（§4.1），FinMind 降為交叉驗證。
3. **還原引擎有 3 個口徑要對帳**（兩個 repo 獨立實測得出，我們還沒驗）：①官方參考價無條件捨去到分 → 連乘後單邊偏低 ②現金增資事件應用「減除股利參考價」而不是「除權息參考價」 ③權息與減資同日重疊只算一次（§4.2）。
4. **兩個 repo 的矛盾已用我們的資料裁決**（§6）：TPEx 舊法人／融資券端點到 2026-10-02 仍有效（有 repo 說 2025/12 失效，對我們不成立）；TPEx `dailyQuotes` 可查歷史（有 repo 說日期常被忽略，是他們的格式問題）。
5. **新聞：我們完全沒建**。本批 repo 沒有可直接搬的高品質做法；最低成本是「鉅亨 RSS／Google News RSS 逐產業關鍵字」（歸屬靠查詢字串，個股層大量錯配），官方可歷史回溯的公司事件只有 MOPS（新站 JSON API 可用性未驗）。建議只進 tw-hold AI 層的 briefing、不進規則。
6. **無意義／有風險的不要碰**：券商分點（免費不可行）、MIS 即時／盤中（與「一天一次」定位無關）、第三方站爬蟲（富邦、Stooq、金十、TradingView、r.jina.ai proxy）、`verify=False`、位置索引解析欄位。

---

## 2. 資料來源總表（按資料類型）

### 2.1 日線（價量）
| 來源／端點 | 內容與範圍 | 出處 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| TWSE `rwd/zh/afterTrading/MI_INDEX?date&type=ALLBUT0999` | 上市全市場日 OHLCV（未還原）；可帶日期 | 多數 repo | ✅ 自建上游 | ★★★ | 【實測】≥2015、回應 `date` 可斷言；官方下限 2004-02-11【文 TD】。個股表依標題「每日收盤行情」找，不寫死 `tables[8]` |
| TPEx `www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD` | 上櫃全市場日 OHLCV；**西元斜線**；可帶日期 | db-master、AI、TP | ✅ 自建上游 | ★★★ | 【實測】≥2015、回應 `date` 可斷言；官方下限 2007-07-02【文 TD】；`type` 參數被忽略、ETF／權證／股票混在同表 |
| TPEx openapi `tpex_mainboard_daily_close_quotes`、舊 `stk_quote_result.php` | **日期參數被忽略、只回最新一天** | db-master、scanner | ✗ | ✗ | 「假歷史」陷阱：HTTP 200、格式正常、日期不對（上游 `fetch_daily_official.py` 就用這個） |
| TWSE `exchangeReport/STOCK_DAY_ALL` | 上市當日全部個股；只回最新日 | scanner | ✅（PCF 抓收盤價用） | ★ | 當日用，不可回補 |
| TWSE `STOCK_DAY`／TPEx `st43_result.php`／`tradingStock`（單檔月表） | 單檔月度成交；TPEx 月表量是「千股」要 ×1000 | checkup、dashboard、TP | ⬜ | ✗ | 已有全市場逐日，不需要；st43 為舊 php |
| TWSE MIS `getStockInfo.jsp` | 即時／盤中 | MM、APP、TP、AI | ⬜（刻意不做） | ✗ | 與「一天一次」定位無關；官方限流 5 秒 3 次 |
| yfinance／Yahoo chart（台股 `.TW/.TWO`） | 還原價（auto_adjust）；備援 | 多數 repo | 🔶（只用於國際指數／總經；台股日線上游 data_pack 的來源） | ✗（台股）| 見 §4：Yahoo 對現金增資／權息事件的因子本身會錯，不能當裁判；`yf.download(timeout)` 不是硬逾時 |
| 興櫃日行情（TPEx 興櫃表） | 興櫃價（無開收盤、均價代替） | TD | ⬜ | ★ | 我們宇宙不含興櫃；若要，需處理「無價」與 `price_basis` |

### 2.2 籌碼
| 來源／端點 | 內容與範圍 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- | :-- |
| TWSE `fund/T86?date&selectType=ALLBUT0999` | 三大法人個股買賣超（股） | ✅ | ★★★ | 【實測】≥2015；**2015～至少 2017-12 只有 16 欄**（「外資買賣超股數」，不拆外資自營商），之後 19 欄。欄名互相包含（「自營商買賣超股數」vs「外資自營商…」）→ 必須整欄名完全相等比對；用「包含」比對曾讓 16,833 列中 16,394 列驗算不符【碼 TD】 |
| TPEx `insti/dailyTrade?type=Daily&sect=AL&date` | 上櫃三大法人 | ✅ | ★★★ | 【實測】**兩種格式**：≥2018-03 在 `tables[0]`、24 欄；≤2018-01（至少 2017-06）在 **`tables[1]`**、16 欄。只看 `tables[0]` 會把 2018 前誤判成「回空」 |
| TPEx 舊 `3itrade_hedge_result.php`（上游用） | 同上 | ✅（上游在用） | — | 【實測】到 2026-10-02 仍有資料（母表上櫃法人每天 ~780 檔不斷）；`stat` 恆為 `ok`，失效會變成「成功但空」→ 要靠檔數守門偵測 |
| TWSE `MI_MARGN?selectType=STOCK`／TPEx `margin/balance` | 融資融券個股（張） | ✅ | ★★★ | 【實測】≥2015；個股表在 `tables[1]`，**用欄數==16 辨識**；TWSE 的 `note` 說的是「次一營業日」，與同列餘額不是同一天【文 TD】；表頭有兩代（2026-09-09 起）【文 TD】 |
| TWSE `fund/MI_QFIIS?date&selectType=ALLBUT0999` | 外資持股比重、**逐日發行股數** | ⬜ | ★★ | 【文 TD】上市逐日股本的唯一來源（日線表沒有發行股數）；代號欄用「結尾是代號」避開 `ISIN代號` |
| TWSE `marginTrading/TWT93U`／TPEx `margin/sbl` | 借券賣出／餘額 | ⬜ | ★★ | 【文 TD】note 符號集不可跨表共用，可多符號連寫（用「包含」判斷） |
| TWSE `exchangeReport/TWTB4U`、`SBL/TWT96U` | 當沖標的及統計、可借券賣出股數 | ⬜ | ★★ | 當沖比對短線清單可能有用；OpenAPI 只回最新，需每日累積 |
| TWSE `marginTrading/BFIB9U` | 融資融券成數調整 | ⬜ | ★ | 融資維持率估算的輸入之一 |
| 融資維持率（估算） | 以餘額增量×價格估成本 | ⬜ | ★★ | TWSE 只有餘額加總、沒有個別部位成本；我們 B1 規則「未實作」的原因 |
| 券商分點（BSR、富邦 e 洽、TPEx broker） | 分點買賣 | ⬜ | ✗ | 圖形驗證碼、一次一檔、無日期；FinMind 分點為 Sponsor 付費。免費自動化不可行【文 TD】；hub 的 OCR＋`verify=False` 做法未驗證 |
| TDCC `opendata.tdcc.com.tw/getOD.ashx?id=1-5` | 集保股權分散（週）；**只回最新一週** | ✅（週快照） | ★★★ | 代號 6 碼右補空白要 strip；級距 12＝400~600 張、15＝千張以上、17＝合計（三個 repo 一致）；三道恆等式（股數合計＝Σ(1~15)−差異調整；人數合計＝Σ(1~15)；每檔 17 級）可當守門；官方只保存一年，斷週永久缺 |

### 2.3 公司行動（還原的官方來源）— 對本週最重要
| 來源／端點 | 內容 | 歷史下限 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| TWSE `exRight/TWT49U?startDate&endDate` | 除權息計算結果（前收、參考價、權值+息值、**減除股利參考價**） | 2003-05-05【文】 | ✅ | ★★★ | 【實測】2015 起；`date` 參數被忽略但會**回音**（只看回音欄會被騙） |
| TPEx `bulletin/exDailyQ?startDate&endDate` | 除權息（權值、息值、現金股利、每仟股無償配股、現金增資欄） | ~2008-01-10【文】 | ✅ | ★★★ | 【實測】2015 起；0 筆不報錯 |
| TWSE `exRight/TWT49UDetail?STK_NO&T1` | 單一事件明細（現金股利、配股率、現增） | 同上 | ⬜ | ★ | 每事件 1 次請求；唯一能拆出現金／配股／現增 |
| TWSE `exRight/TWT48U`、`TWT48U_ALL` | 除權息**預告**（只有未來） | — | ⬜ | ★ | 不可當歷史；可做「即將除息」提醒 |
| **TWSE `reducation/TWTAUU?startDate&endDate`**（拼字如此） | **減資恢復買賣參考價**：最後交易日收盤、恢復買賣參考價、漲跌停、開盤競價基準、原因 | 2011-01-01【文 TD】 | **⬜→本週接入** | ★★★ | 【實測】2025：17 件、2015：26 件；有 2 組重複 `(3536,104/03/20)`、`(5906,105/07/14)` 要 dedup【文 TD】；備註夾「除息併案減資」自由文字 |
| **TPEx `bulletin/revivt?startDate&endDate`** | 上櫃減資（含官方「換股比例」欄） | ~2013-01-16【文】 | **⬜→本週接入** | ★★★ | 【實測】2025：10 件；日期是民國 7 碼 `1140113` |
| **TWSE `change/TWTB8U?startDate&endDate`** | 面額變更恢復買賣 | 實質 2020-08-17【文 TP】 | **⬜→本週接入** | ★★★ | 【實測】2019 起 10 件（8070 長華 2020-08-17 … 6949 沛爾生醫 2026-09-07） |
| TPEx `bulletin/pvChgRslt`（POST） | 上櫃面額變更 | — | ⬜ | ★★ | TD 找到、TP 七種路徑探測全 302；**只有 TD 走通，需實測** |
| TWSE `split/TWTCAU` | ETF 分割 | — | 🔶（FinMind SplitPrice 含 ETF） | ★ | TD 獨有 |
| FinMind `TaiwanStockSplitPrice`／`ParValueChange`／`CapitalReductionReferencePrice`／`DividendResult`／`PriceAdj` | 同上事件；PriceAdj 為付費層 | 2015 起 | ✅（事件表第二來源） | ★★ | 減資需逐檔（全市場是付費層）；`DividendResult` 的參考價欄是 `after_price`，不是 `reference_price`（後者在「權」時等於前收、因子=1 → 配股完全不還原且不報錯）【文 TD】；超額回 402 後退避無效，必須事前節流 550/小時 |

### 2.4 基本面／公司資料
| 來源／端點 | 內容 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- | :-- |
| FinMind 財報三表／月營收／股利／PER（免費層） | 逐檔 | ✅ | ★★★ | `date` 是期別結束日不是公告日（直接回測是未來函數） |
| OpenAPI `t187ap05_L`／`mopsfin_t187ap05_O` | 月營收（最新一期；參數被無視） | ✅（每日快照累積） | ★★ | 單位千元；路徑不要多一層 `opendata/`（會回 HTML） |
| OpenAPI `t187ap06/07_L_{ci,basi,bd,fh,ins,mim}` | 損益表／資產負債表（六業別，最新一期） | ⬜ | ★ | 損益表是**年初至本季累計**，單季＝累計−前幾季；前幾季不齊就整筆略過（否則 TTM EPS 放大 2–4 倍）【碼 HUB `ytd.py:23`】 |
| MOPS 歷史月營收靜態頁 `mopsov.twse.com.tw/nas/t21/{sii\|otc}/t21sc03_<民國年>_<月>_0.html` | 月營收歷史（第二來源） | ⬜ | ★★ | 網域是 **mopsov**（`mops` 回 404）；big5 宣告但要 **cp950**；**完全不含 -KY 外國發行人**（實測 104 檔查無）；robots.txt disallow【碼 TD】；regex 曾因備註欄 `align=left` 漏列 |
| MOPS 財報歷史 POST `ajax_t163sb04/05`、新 JSON `mops/api/t164sb03`（body 須五鍵含空字串）| 財報原始、公告時點 | ⬜ | ★ | 我們用 FinMind；MOPS 新站直接 requests 可能被 WAF 擋（有 repo 說擋、有 repo 說可用）→ 【推】 |
| OpenAPI `t187ap03_L`／`mopsfin_t187ap03_O`／`_R` | **公司基本資料：產業別代碼、實收資本額、已發行股數、上市日** | ⬜ | ★★★ | 產業代碼是子類（13 電子工業＝24~31）；特別股（1101B）要去尾碼用母公司查；91＝DR 不是類股；32／33 中文名由 ISIN 頁補、**不覆蓋** MI_INDEX 用字（「代碼對、名稱錯」是安靜的錯） |
| ISIN `isin.twse.com.tw/isin/C_public.jsp?strMode=2\|4` | 證券主檔、產業別文字、CFI 碼（ES*＝普通股） | ⬜ | ★★ | **必須 cp950**（big5 codec 會把「碁」等 13 檔靜默變 U+FFFD）；代號與名稱以全形空格 U+3000 分隔；區塊順序不固定要用標題比對 |
| **ic.tpex.org.tw 產業價值鏈**（`introduce.php?ic=<code>`） | 產業鏈節點→公司 | ⬜ | ★★ | 官方免費、靜態 HTML；葉節點取法見 db-master `industry_chain.py`；結構穩定性未知；既有分析文件幾乎沒提 |
| `t187ap47_L` ETF 基金基本資料 | ETF 清單 | ⬜ | ★ | |
| 每日 PER／PBR／殖利率：TWSE `BWIBBU_d`、TPEx `peQryDate` | 逐日估值 | ✅（每日快照） | ★★ | `stocks_per` 的 close 欄不能當價格；TWSE 早年欄位順序不同 → 按欄名取 |

### 2.5 市場狀態／日曆／名單
| 來源／端點 | 內容 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- | :-- |
| TWSE `holidaySchedule/holidaySchedule` | 休市日清單（csv big5，前 2 行標題） | ⬜（我們靠「官方實價有／沒有」） | ★★ | 可用來**預判**該日該不該有資料，區分「休市」與「來源當機」；注意：有 repo 自述它只給圖表用 |
| TWSE `FMTQIK`（整月一次） | 大盤成交金額／股數／指數 | 🔶 | ★ | 比 yfinance `^TWII` 成交量可靠（Yahoo 大盤成交量長期不可靠）；**週六補班日**要納入交易日候選（只跳六日會漏補班日） |
| 終止上市清單 TWSE `company/suspendListing`（回應鍵是 `status` 不是 `stat`；csv 是 ms950）／TPEx `company/deListed`（只回當年） | 下市名單 | ⬜ | ★★★ | 存活者偏誤的外部判準：我方 `last_seen` 應 ≤ 官方終止上市日；snapshot 沒出現≠下市（2358/2443 在正式下市前就停牌）；TPEx「終止上櫃」≠下市（5236 轉上市）【文 TP】 |
| 處置／注意／停牌：TWSE `announcement/punish\|notice\|notetrans`、`TWTAWU`、TPEx `bulletin/disposal\|attention\|sprc\|sprcHis` | 處置、注意、暫停交易 | ✅（處置股快照） | ★★ | 四個靜默坑：日期格式相反（TWSE 西元／TPEx 民國斜線）寫錯不報錯；「本日無處置資料」是一列不是空陣列；`sprc` 反而空陣列；證券名稱欄夾連結要清 |
| 長期停止買賣 `t187ap26_L`／`mopsfin_t187ap26_O`／`tpex_cmode` | 只有當日快照 | ⬜ | ★ | 每天不抓即永久損失；無案件時回「一列全空」佔位 |
| 變更交易 `TWT85U`、`violation/stop` | 變更交易、停止買賣 | ⬜ | ★ | |
| 颱風假 `dgpa.gov.tw/typh/daily/nds.html` | 停班停課公告 | ⬜ | ✗ | TD 做單向（台北市＋停止上班同時命中才標休市）避免誤判；我們靠實價日曆即可 |

### 2.6 衍生品／總經／國際
| 來源 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- |
| TAIFEX 官方（期貨三大法人、日夜盤）、TWSE `BFI82U` | ✅ | ★★★ | TAIFEX 會讓端點在 JSON 與 CSV 間來回切換（MCP 一天內觀察到 5 個）→ 以表頭契約驗證的 CSV 退路；OpenAPI 授權：預設禁止再散布，data.gov.tw OGDL 豁免 |
| TAIFEX OpenAPI 擴充（大額交易人、PCR） | ⬜ | ★ | 我們已拿掉 TXO 量比 |
| Yahoo chart/yfinance（國際指數、美股、匯率、商品） | ✅ | ★★ | S&P500 `^GSPC` 要帶 `period1=0&period2=<未來>`，只給 `range=max` 會被降頻成季線；單 ticker 瞬時失敗要重試（`^SOX` 曾讓總分少 2.5 分）；"possibly delisted" 多半暫時性（116 檔失敗 92% 重試成功） |
| FRED `fredgraph.csv?id=` | ⬜ | ★ | 免 key；Python urllib 會被斷連、曾 read timeout；備援層才需要 |
| 國發會景氣／主計總處 CPI／財政部出口／經濟部外銷訂單／PMI | ⬜ | ✗ | 總經頁面已有 Yahoo 層；M1B/M2 要用「貨幣總計數」dataset 6024，**不要用「變動因素分析」**（會出現單月 1000%+）；ZIP 內檔名 big5 要 `name.encode('cp437').decode('big5')`；PMI 掛 Cloudflare 攔截——repo 自己也放棄 |
| Stooq、金十 `jin10.com`、TradingView 經濟日曆、`r.jina.ai` | ⬜ | ✗ | Stooq 已加 JS proof-of-work；其餘非官方、授權不明、要 Worker 補 header 或第三方轉譯 |

### 2.7 ETF／其他
| 來源 | 我們 | 價值 | 備註 |
| :-- | :-- | :-- | :-- |
| 主動式 ETF 官網 PCF（統一／群益／復華） | ✅ | ★★★ | |
| MoneyDJ ETF 成分（`Basic0007b.xdjhtm`） | ⬜ | ✗ | 非官方 HTML，只有 top10 |
| FinLab（`finlab-ai-main`） | ⬜ | ✗ | 文件型、token 制（免費 500MB/日）；唯一可參考：`deadline()`（法定公告截止日）vs `index_str_to_date()`（實際揭露日）的 look-ahead 規則 |

---

## 3. 清洗／修正手法總表（按手法）

| # | 手法 | 具體做法與出處 | 我們 | 價值 |
| :-- | :-- | :-- | :-- | :-- |
| 1 | **回應日期必須等於請求日** | 逐日端點把「靜默回今天」當最危險的錯：TD `fetch.py:1235 _same_day`（連 `title/strDate/endDate` 自述日都核，不能只看會被回音的欄）、db-master `live_momentum.py:67`；2026-09-03 TD 因此事故把 2026-09-02 的 980 檔寫成 2015-01-01 | ✅（實價、法人、融資收集器） | ★★★ |
| 2 | **候選端點清單不得放「只回今天」的 openapi** | TD `backfill.py:140-148`、`feeds.py` 檔頭 | ✅ | ★★★ |
| 3 | **欄名完全相等、不用位置、不用包含** | TD `backfill.py:898-960`、`feeds.py:_exact`；反例：AI／HUB 全用位置索引 → 欄數改版靜默錯位 | 🔶（法人用名稱＋別名；融資券用「欄數==16」＋位置，上櫃用位置——有欄數守門） | ★★★ |
| 4 | **免費恆等式守門** | 外資(兩欄相加)＋投信＋自營＝合計（容差 1）；自營自行＋避險＝合計；不符整列丟棄並回報（TD `backfill.py:944-975`；stocker `update_all.py:341-353`）；集保三道恆等式 | ⬜（gate 只管列數／檔數／日期） | ★★★ |
| 5 | **日檔量守門（硬下限＋相對）** | TWSE≥1000／TPEx≥700／最新日必須等於目標日（stocker）；列數<前後 ±10 交易日中位數 70% 標「不可判定」（TD `margin_universe.py`）；OHLC 一致性 `0<min≤min(o,c)≤max(o,c)≤max`（db-master `live_momentum.py:79-80`）；有效股票<500 raise | 🔶（有相對 90% 與絕對 900/700；**沒有 OHLC 一致性、法人合計校驗**） | ★★★ |
| 6 | **0 列有兩義：休市 vs 抓壞** | 以官方月表／實價日曆當外部判準；空 payload 一律 unresolved（TP `trading_day_evidence.py`）；只在交易日上問（TD `early_backfill.py`）；TWSE `stat != OK` 才當休市 | ✅（實價日曆＋unavailable 分流）| ★★★ |
| 7 | **週六補班日要納入交易日候選** | TD `backfill.py:700 daterange(saturdays=)`；TP 實跑補上 8 個週六（2016-01-30 等）；AI／HUB 只跳六日會漏 | ⬜（**我們全歷史回補用 `weekday()<5`，會漏補班日**） | ★★★ |
| 8 | **缺值不等於 0** | `_num()`：`X/N/A/--/-` 回空字串不填 0；TPEx 漲跌寫成「- 0.35」（號與數字間有空白）先去所有空白，否則上櫃所有下跌日漲跌被清空（TD `fetch.py:481-500`）；官方「--」價格＝有觀測無價格 bar | ✅（無成交列丟棄；**空白符號未處理**）| ★★ |
| 9 | **單位**（股／張／千股／千元） | TPEx 月表千股×1000；MIS `v` 為張；OpenAPI 金額千元；官方日檔 volume 含零股（非千倍數）；AI 存「張」取整會丟零股 | ✅（存股）| ★★ |
| 10 | **編碼／憑證／反爬** | 一律 cp950（big5 codec 缺「碁」等 13 字）；TDCC BOM；T86 宣告 UTF-8 但要 `content.decode` 再 `json.loads`；TPEx 漏送中間憑證（TD `ca_chain.py` 補鏈、不降驗證；HUB `verify=False` 是**錯誤做法**） | ✅（requests＋certifi 已解 TPEx）| ★★ |
| 11 | **重試退避與限流** | TD：一般 3s/6s、3xx 無 Location 或 429＝限流 60s/120s，並讓呼叫端分得出「被擋」與「端點壞」；`IncompleteRead` 同位置＝決定性、不同＝偶發。db-master `_http.py`：同 bucket ≥1.7s、5/20/60s 退避。TP：每主機 token bucket（TWSE/TPEx 16rpm、MOPS 12rpm、FinMind 5/10rpm） | 🔶（固定 2s 間隔、3 次重試；FinMind 550/小時）| ★★ |
| 12 | **回補完成度報告** | 回補腳本輸出「應有幾檔／實有幾檔」、失敗非零退出；tw_stock-master 曾 1098 檔失敗卻被當成已補完（`backfill_tpex_history_gap.py:2-14`）；放寬範圍後 log 只記「抓過」不記範圍 → 舊範圍殘留 | 🔶（有失敗計數與非零退出；**沒有「應有／實有」報告**） | ★★ |
| 13 | **累積檔不可整份覆蓋、低水位檔** | TD：逐鍵合併、一天一檔、coverage 依寫入者拆檔（共用索引檔被兩寫入者整份重寫＝git 衝突白跑 35 分鐘）；資料檔列數不得掉；AI：`--backfill` 會覆蓋成更短的現有檔時拒絕（曾把 478 天蓋成 3 天）、`mtime=0` 確定性壓縮讓 no-op 不誤 commit | ✅（健檢閘門＝列數不減、日期不倒退；狀態檔無時間戳）| ★★★ |
| 14 | **每個守門都要證明「會紅」** | TD `selftest_*`＋突變驗：故意弄壞確認守門會失敗；斷言驗終點不驗中間（「中間那一步成功了就被當成整件事成功」） | 🔶（有測試，無突變驗）| ★★ |
| 15 | **存活者偏誤對策** | 不以現況 allowlist 過濾歷史（TP 實測會把歷史下市股整批丟掉）；`observed_universe` 只記官方 snapshot 當日有沒有出現；終止上市清單當外部判準 | 🔶（實價回補不過濾現況清單；**減資查詢清單改用「實價出現過的代號」含已下市**；尚無終止上市清單對帳）| ★★★ |
| 16 | **讀取契約／基準日** | 基準日讀 manifest 的 `date_max` 不推算；用精確日期 join `adj/` 會漏事件（要用「第一個事件日 > d」）；切近 N 日窗要依日曆不是 `rows[-N:]` | 🔶 | ★★ |
| 17 | **OpenAPI「回 0 筆＝上游故障」** | MCP `ALWAYS_POPULATED`：主檔回 0 筆一律當故障、不當查無資料 | 🔶（處置股／估值有；未逐一確認）| ★★ |
| 18 | **FinMind 額度節流** | 滑動視窗 550/小時、`FinMindTierError` 區分權限不足與網路錯、402/403 立停並把進度寫進表（`finmind_client.py`、`build_valuation.py`）；超額後退避無效 | ✅ | ★★ |

---

## 4. 還原／公司行動專章（本週重點）

### 4.1 官方事件來源已接上哪些、還差哪些
| 事件 | 官方來源（免逐檔、可日期區間） | FinMind（交叉驗證） | 狀態 |
| :-- | :-- | :-- | :-- |
| 除息／除權／權息 | TWT49U、exDailyQ | DividendResult（逐檔） | ✅ 已在事件表 |
| 面額變更／分割 | TWTB8U（TWSE，2020-08 起）；TPEx pvChgRslt（POST，待驗）；TWTCAU（ETF） | SplitPrice／ParValueChange | ✅ TWTB8U 已接入（`twse_par`，10 件）；TPEx 面額變更仍缺（FinMind 補） |
| 減資 | TWTAUU（TWSE，2011 起）、revivt（TPEx，2013 起） | CapitalReductionReferencePrice（逐檔） | ✅ **已接入並與 FinMind 交叉驗證**（2026-10-05）：官方 2011→今 686 件（TWSE 396、TPEx 290）；FinMind 已查到的 345 件**全部**在官方表內（0 件僅 FinMind 有）、因子相對差中位數 0、僅 2 件 >0.5%（3312、3536：減資併現金增資，官方「除權參考價」＝FinMind `ExrightReferencePrice`，FinMind 收集器原本取了另一欄，已對齊）。FinMind 降為交叉驗證（CI 每週 150 檔）；本機輪詢已停止 |

### 4.2 兩個 repo 獨立發現、我們還沒驗的因子口徑（B 最高優先）
1. **官方參考價是「無條件捨去到分」**，`factor=ref/pre_close` 每筆偏低、連乘後單邊累積偏差。TD 量到 920/920 檔 `cum_factor` 為負、中位 −3.87e-4、最差 −2.9%【文 TD READ_CONTRACT】；TP 量到 0056 季配 40 次累積偏離約 0.4%，建議 `f=(C_prev−cash)/(C_prev×(1+free_ratio))`（TP `corporate_actions.py:132 quantize(…,ROUND_DOWN)`【碼】）。我們目前用 ref/pre，**待用我們的資料對 0056、0050 等季配股驗算**。
2. **現金增資事件應用「減除股利參考價」**（不含現增稀釋），不是「除權息參考價」；否則在純現增事件（例 6658 聯策 2025-01-06）造出 −1.48% 假報酬（TP audit §2.3【文】）。TWT49U 與 exDailyQ 都有該欄。**我們用的是除權息參考價**——這很可能就是 Opus 審查發現的「現金增資因子 >1」那批（TPEx 483 件、TWSE 11 件）的根因。→ **待驗**。
3. **權息與減資同日**：TD 說同日 TWT49U 那列要丟（息值已含在減資公式裡）；TP 說 2015–2025 同日重疊為 0。兩者矛盾，用我們的資料掃一次即可裁決（`selfhost_adjust.py` 已有 `multi_class` 標記）。
4. **減資「前收」要取停牌前最後一個有成交日**，不是日曆前一天（TD `adjust.py`）；減資因子合理範圍與除權息不同（除權息 0.05<f≤1.5，沿用會把真事件整批丟掉）。
5. **事件日當天不乘、之前才乘**（TD 附 worked example 3661；我們同口徑，Opus 以 fresh Yahoo 驗證過）。
6. **漲跌停判定不得用還原價**（TP）；2015-06-01 起漲跌停由 7% 放寬為 10%（TD）。
7. **PIT 因子 API**（TP `adjust_prices_as_of`）：每個 raw row t 只乘 `t<event_effective_date 且 effective_at<=as_of` 的因子；展示型與訓練型分開。我們尚無此需求（價格不用於回測訓練時）。

### 4.3 別人的還原做法與我們的差異
| 專案 | 做法 | 缺陷／評語 |
| :-- | :-- | :-- |
| me（taiwan-stock-analyzer-v3）`price_adjuster.py` | FinMind 三事件表算 `after/before`、連乘、成交量反向調 | **只還原分割／減資／面額，不含現金股利**（非含息還原）；`_fetch_finmind` 吞所有例外回空 DF（額度耗盡與真沒事件分不出）；事件結束日寫死 2026-12-31；既有分析對此只有一行、沒指出 |
| 同檔：用 `TaiwanStockPriceAdj` 事件日前後比值當驗屍 | 概念好（第三方還原價當驗屍工具）；程式缺陷：`"無" in conclusion` 會把「無資料」也當 use_manual | 我們可借鏡「驗屍」概念，但不依賴付費層 |
| APP | yfinance `auto_adjust=False`（OHLC 仍會被拆股調整、只是不含股息） | 口徑含糊 |
| 上游 scanner | yfinance 全量下載＋每日只重抓 7 天 | **還原接縫**（見稽核報告）；Yahoo 對現增／權息事件因子也會錯 |
| 以除息日價差反推現金股利（surge-dna） | `prev_close − Close_ExDate` | 含當日漲跌的估計值；官方表已有，僅備案 |

---

## 5. 新聞（產業／公司）

**結論：我們尚未建；本批 repo 沒有可直接搬的高品質做法。** 只有 tw-stock-hub 有完整管線；TD 明文「資料庫裡沒有新聞，也不會有」。

| 來源 | 怎麼抓 | 去重／歸屬 | 風險 | 價值 |
| :-- | :-- | :-- | :-- | :-- |
| Google News RSS 逐產業關鍵字 | `news.google.com/rss/search?q=…&hl=zh-TW&gl=TW&ceid=TW:zh-Hant`；scanner 約 30 個產業中文關鍵字表（CI 只跑 `--sectors`） | 標題 md5；**歸屬靠查詢字串**（個股層大量錯配，產業層可用）；Google 結果 URL 為跳轉、跨來源無法去重 | 條款限制大量自動化存取【推】；只存標題＋連結授權風險低 | ★★（產業層 briefing 最低成本入口） |
| 鉅亨 RSS `feeds.cnyes.com/market/tw/news.rss`（或 `feed/news/tw_stock`、`headline`） | feedparser | url 唯一鍵；歸屬靠「已知代號出現＋公司名子字串比對」，會誤配短名、4–6 位數可能是價格 | 授權未見說明 | ★★ |
| MOPS **當日**重大訊息 | `POST mopsov.twse.com.tw/mops/web/ajax_t05sr01_1`（先 GET 暖機拿 cookie，HTML 表格解析） | 直接帶 `stock_id`；關鍵字分類 | **只回「今天」、無日期參數**；舊 AJAX 端點疑似已被 WAF 擋【推，兩 repo 說法不一】 | ★★（若可用，官方、有時間戳） |
| MOPS 重大訊息 **JSON API（歷史＋時間戳）** | `POST mops.twse.com.tw/mops/api/t05st01` body `{companyId, year(民國), month, firstDay, lastDay}`，再 `t05st01_detail`；Referer 須為 `/mops/web/t05st01` | 事件 identity＝`{market}/{issuer}/{enterDate}/{serial}`；`available_at＝官方事件時間戳（精確到秒）` | 逐檔逐月＋每筆再打明細、嚴格限速 12rpm；**可用性未驗**（TP 有程式、無實測紀錄）| ★★★（若可用：官方、PIT、可回溯） |
| MOPS OpenAPI 每日 `t187ap04_L`／`mopsfin_t187ap04_O` | 每日快照 82 筆左右；無歷史 | 需每日累積 | 每天不抓即永久缺 | ★★（成本低，先累積） |
| Yahoo 奇摩股市個股新聞（RSS `tw.stock.yahoo.com/rss?s={id}`） | RSS／HTML | HUB 的 `published_at` 直接用抓取時間＝**時間戳不實**；AI Worker 以 KV 快取 4 小時 | HTML 選擇器脆弱、授權不明 | ✗ |
| MoneyDJ 台股新聞 | HTML 清單；日期只有 `MM/DD HH:MM`，年份靠 `target_date` 推 | url 去重 | 年份推算會污染時序；非官方 | ✗ |
| FinMind `TaiwanStockNews` | 逐檔查；不接受 `end_date` | `url\|\|title` 去重 | 免費層額度（1,943 檔在 600/小時下要 3+ 小時）；情緒是詞表 | ★（額度與我們共用，不建議） |
| 證交所新聞／活動 OpenAPI `news/newsList`、`news/eventList` | MCP 目錄有、**沒有 repo 實際使用** | — | — | ★（可試） |
| 金十、TradingView 日曆 | Worker 代抓 | — | 授權不明 | ✗ |
| 券商研究、目標價、PTT／Dcard／法說會 | **本批 repo 皆未見實作**（scanner 的 `analyst_report.py` 是手動貼入【推】）| — | — | — |

**共通教訓**：沒有任何 repo 做內容相似度去重（轉載同標題不同 url 會重複），也沒有「事件→產業」歸屬；官方可歷史回溯的公司事件只有 MOPS；市場新聞全部是非官方、無歷史。
**對 tw-hold 的建議**：新聞只進 AI 解說層 briefing、不進規則（既有設計定案）。若要動手，順序：①先累積 MOPS OpenAPI 每日重訊快照（成本最低、官方）②實測 MOPS `t05st01` JSON API 可用性 ③產業層用 Google News／鉅亨 RSS 關鍵字掃描，標明歸屬是查詢字串。

---

## 6. 已驗證的矛盾與更正

| 項目 | 結論 | 證據 |
| :-- | :-- | :-- |
| TPEx 舊法人／融資券端點（`3itrade_hedge_result.php`、`margin_bal_result.php`）2025/12 是否失效 | **對我們不成立，到 2026-10-02 仍有效**（stocker 的說法可能是請求格式問題；TD 說舊 .php 全 404 是對「他的探針路徑」） | 【實測】tw-swing 母表上櫃法人每天 ~740–800 檔、融資 ~800 檔，2025-11～2026-10 不斷；8/26 之後的列正是上游用舊端點抓的。風險仍在：`stat` 恆 ok，失效會變成「成功但空」 |
| TPEx `dailyQuotes` 的 `date` 常被忽略（tw_stock-master） | **不成立**：西元斜線格式可查歷史 | 【實測】2015-01-05、2018、2020、2023、2026 皆回對應日期 |
| TPEx 法人 2018 前回空（我們先前自己的記錄） | **更正**：2018-03 前資料在 `tables[1]`、16 欄 | 【實測】2017-06-01 2,812 列、2018-01-02 3,233 列；Opus 複查發現，已修 |
| TD `_db_status.md`「上市 shares 歷史序列取不到」 | 被後續程式推翻（`fetch.py:1089` 用 MI_QFIIS 補上） | 【碼】引用 TD 結論以 2026-09-24 後的程式與較新章節為準 |
| tw-invest-suite 分析「finmind_month TTL 30 天」 | 程式是 7 天（分析抄自 `cache_format.md` 文件） | 【碼】`cache_manager.py:36-44` |
| tw_stock-master 分析把 `trading_calendar.py` 當交易日判斷 | 檔頭自述只給圖表 rangebreaks；抓資料靠「回空就跳過」 | 【碼】`trading_calendar.py:1-5` |
| scanner `fetch_news.py` 檔頭宣稱四個新聞來源 | CI 只跑 `--sectors`（Google News RSS 逐產業）；MOPS 舊 AJAX 疑似失效 | 【碼】CI 第 49 行 |
| stock-dashboard 分析「TPEX OpenAPI ETF 行情」那層 | 文件宣稱、程式碼未見；「對官方友善」只是序列執行、無 sleep | 【碼】`fetch-prices.mjs` |
| TWT49U 的 `date` 參數 | 被忽略但**會回音**——不能只看回音欄 | 【碼 TD】`_same_day` |
| TP 與 TD 因子口徑（減除股利參考價、同日重疊） | **未裁決**，待我們用資料驗（§4.2） | 見 §4.2 |

---

## 7. 無意義／過時／有風險的做法（不要抄）

1. **位置索引解析欄位**（AI／HUB／我們部分）：欄位增減就靜默錯位。
2. **`verify=False`**（HUB 5 處）：關 TLS 驗證；正解是補中間憑證不降驗證。
3. **TPEx 假歷史端點**（openapi 日線、`stk_quote_result.php`）。
4. **以名稱子字串排除 ETF**（HUB `SKIP_KEYWORDS=["ETF"]`）、以代號形狀判斷股票（AI）：是產品選擇、不是清洗。
5. **Yahoo 新聞 `published_at=now()`、MoneyDJ 年份靠 `target_date` 推**：時間戳不實。
6. **`resp.encoding='big5'`**：不含 MS950 擴充字，靜默產生 U+FFFD。
7. **FinMind 超額後重試／退避**：無效，必須事前節流。
8. **`yf.download(timeout=10)` 當硬逾時**：不可靠（曾卡 12 分鐘使排程死掉）。
9. **版本號當檔名的還原腳本**（`fast_adjuster_v2…v5`）且清理過缺變數：不可當範本。
10. **`r.jina.ai` 當 TPEx proxy、Stooq、金十、TradingView、富邦 e 洽排行、BSR OCR 分點**：第三方轉譯／授權／反爬／驗證碼。
11. **用價差反推除息股利**：官方表已有。
12. **「相鄰兩筆差 > N 天」當缺漏偵測器**（MM `gap>18`）：不是缺漏偵測器（TD）。
13. **直接 requests 打 MOPS 新 SPA 端點／在 CI 加 Playwright 去繞 WAF**：成本／風險／規範都不值得。
14. **MOPS 歷史頁**：TD 自己標 robots.txt disallow，量小且 sleep，但需自行評估再用。

---

## 8. 建議行動（只列與「資料正確性／缺口」有關者）

### 本週（自建上游範圍內，成本低）
| # | 項目 | 理由 |
| :-- | :-- | :-- |
| 1 | ✅ **（2026-10-05 已完成）接入官方減資／面額變更表**（TWTAUU、revivt、TWTB8U）當事件表來源，FinMind 降為交叉驗證 | 免逐檔、可日期區間、2011/2013/2020 起；與 FinMind 交叉驗證 345／345 吻合 |
| 2 | **驗證因子口徑**：①純現增事件改用「減除股利參考價」對照 data_pack／Yahoo 差多少 ②季配股（0056、0050）連乘偏差 ③同日權息＋減資重疊筆數 | 兩個 repo 獨立發現、可能是 Opus 找到的「現增因子>1」根因；直接影響還原正確性 |
| 3 | ✅ **（2026-10-05 已改）週六補班日納入候選**：實價收集器含週六（上市空表即跳過上櫃）、法人融資只在實價日曆有該週六時才問；全歷史實價回補跑完後要再跑一次補週六 | 原用 `weekday()<5` 會漏補班日（2016-01-30、2017-09-30、2018-03-31、2018-12-22 等；我們自己的 `known_data_issues.yaml` 也記過母表漏這些日子） |
| 4 | **健檢加：法人合計恆等式（外資＋投信＋自營＝合計）、OHLC 一致性、「應有／實有」回補報告** | 現有閘門只管列數／檔數／日期 |
| 5 | 對帳用的歷史下限表（§2 各端點）寫進 `DATA_FLOW.md`／pitfalls | 判斷回補範圍；注意其中【文】項我們未實測 |

### 之後（有價值、排後面）
| # | 項目 | 價值 |
| :-- | :-- | :-- |
| 6 | 公司基本資料／股本／產業：`t187ap03_L`＋`_O`＋ISIN（cp950）＋`MI_QFIIS` 逐日發行股數 | ★★★ 補「股本變動」「產業分類」缺口（也讓市值更準） |
| 7 | 終止上市清單對帳 + 交易日曆（holidaySchedule） | ★★★／★★ 存活者偏誤外部判準；區分休市與來源當機 |
| 8 | MOPS 重大訊息每日快照累積（OpenAPI `t187ap04_L`／`mopsfin_t187ap04_O`）；實測 `t05st01` JSON API | ★★ 新聞／公司事件的官方來源 |
| 9 | 借券（TWT93U／`margin/sbl`）、當沖（TWTB4U）、成數調整（BFIB9U） | ★★ 短線籌碼；融資維持率估算的輸入 |
| 10 | 產業價值鏈 `ic.tpex.org.tw` | ★★ 官方免費、產業鏈分類缺口 |
| 11 | 逐日資料的「突變驗」（故意弄壞守門確認會紅） | ★★ 工程紀律 |

### 不做
券商分點、MIS 即時、第三方站爬蟲、MOPS 繞 WAF、位置索引、`verify=False`。

---

## 9. 局限
- §2 的「歷史下限／筆數」凡標【文】的都是 repo 自述，**我們沒重算**；標【實測】的才是我們今天打過／用自己資料驗過的。
- tw-stock-data（TD）的 `CLAUDE.md`（2191 行）、`READ_CONTRACT.md`（3053 行）只讀了與資料處理直接相關的章節。
- 組 B 對既有分析的抽驗涵蓋 14 個說法，不是全部。
- 新聞授權（Google News、鉅亨、Yahoo、MoneyDJ）與 MOPS WAF 行為**未打網站驗證**。
- 本文不涉及策略或回測績效。

---

## 10. 與 tw-stock-data（TSD）對照：月營收／財報／PER／集保／MOPS（2026-10-06，只記錄，未改程式）

> 範圍：只比「有沒有、涵蓋期間、能算什麼」，**沒有逐列核對內容正確性**（價量／法人／融資券／還原的核對見 data-qu.md §6.9 與 data-fix.md）。TSD 側為檔案清單與表頭實測；我們側為 `tw-swing/data/fundamentals/*`、`tw-swing/data/tdcc`、`tw-hold/data/selfhost/*`。

### 10.1 逐類對照

| 類別 | 我們有 | TSD 有 | 差距 |
| :-- | :-- | :-- | :-- |
| 月營收 | `revenue_history`：2014-12～2026-08、含 `announced`（公告日）、24.5 萬列 | `mops/revenue_hist`：2015-01～2026-08，上市／上櫃各一檔，含上月／去年同月／累計及增減% | 基本打平。TSD 多「累計營收」「產業別」欄（我們可自算）；兩邊都不含 -KY（MOPS 靜態頁限制，TSD 實測） |
| 財報（損益／資產負債／現金流） | FinMind：`income`（eps、營收、毛利、營業利益、稅前、淨利、母公司權益）、`balance`（股本、現金、流動資產／負債、總負債、總資產、權益）、`cashflow`（ocf、icf、capex），約 4.2 萬列／表 | `mops/fs_hist`＋`bs_hist`：2015Q1～2026Q2，**六個業別各自的完整報表欄位**（含金融業的利息淨收益、呆帳提存等） | 我們是**精簡欄位**，金融／保險／證券業專屬欄位沒有；完整科目沒有 |
| 研發費用 | ❌ 無 | `mops/rd_hist`、`fin_hist`：2013Q1 起 | 缺（研發費用率算不出來） |
| 財報**公告日** | ❌ tw-hold 一律「期末＋45 天」；營收有 `announced` | TSD 有 `filing_dates.py`／`filing_probe.py`（公告時點，細節未讀） | 缺：Q4／金融業法定期限較晚，+45 天會**提早**看見財報（輕微前視偏差） |
| PER／PBR／殖利率 | `per.parquet`：2015-01-05～2026-08-28，473 萬列（每日快照另累積） | `stocks_per`：2015 起逐檔；`early/per`、`otcper` 另有 2012 起 | 我們短 3 年（2012–2014 對選股回測用不到）；`per.parquet` 最後日 08-28，之後靠 `data/valuation/` 每日快照（最新 2026-10-03）接續，不算缺；但兩段合併的銜接沒查 |
| 集保股權分散 | 週快照，**只有 4 週**（2026-09-11 起） | `tdcc_hist`：**2017～2026 年檔**（來源與完整度未查） | 缺 9 年歷史；官方只回最新一週、補不回，TSD 的歷史來源值得查 |
| 重大訊息（MOPS news） | ❌ | `mops/news`：1998 起逐年（日期、時間、代號、主旨） | 缺；data-dl.md §5 已列「新聞完全沒建」 |
| 股本／發行股數 | 季資料（`capital_stock`，balance、universe） | 日線每列有 `shares`；`latest/*_capital.csv`（OrdinarySharet 季） | 我們的日線**沒有逐日股數**：市值、週轉率只能用季股本近似 |
| 公司基本資料／產業 | `industry`、`universe`（1,968 檔） | `meta/`、`universe/`（含覆蓋、下市、停牌探測） | 打平；下市清單、長期停牌我們沒有（data-dl §2.5 已列） |
| 借券、庫藏股、券商分點 | ❌ | `sbl_probe`、`treasury`、`broker_probe` | 借券／庫藏股缺；券商分點免費不可行（data-dl §2.2） |

### 10.2 我們「無法計算」或「沒抓」的清單（依影響排序）

1. **財報公告日（PIT）**：無法精確判斷「某天能不能看到某季財報」。影響：價值軌／長波段的基本面條件有輕微前視。
2. **集保歷史 2017–2026-09**：無法算大戶持股變化的長期走勢、也無法回測任何集保規則。官方補不回，只有 TSD 的歷史可能補。
3. **研發費用率**：沒抓，無法算。
4. **金融／保險／證券業專屬科目**（利息淨收益、呆帳提存、承保損益等）：我們的精簡欄位算不出金融股專屬指標；目前金融股走四道門檻的替代判準（見 tw-hold 定存線金融軌設計）。
5. **逐日發行股數**：無法精確算歷史市值、週轉率（%）、外資持股比。官方來源 `MI_QFIIS`（data-dl §2.2）未建。
6. **重大訊息**：沒有事件層的基本面／公司行動訊號（減資、增資、處分資產公告的原文）。
7. **借券賣出／庫藏股／當沖**：空方壓力只剩融券（TSD 實測借券是融券的 77.5 倍），庫藏股買回無資料。
8. **2012–2014 早期 PER／法人**：回測用不到，列低優先。

### 10.3 參考價值判斷

- **直接有價值（建議之後評估是否補）**：集保歷史（查 TSD `tdcc_hist` 的來源與完整度）、財報公告日、逐日股數。這三項是「補現有缺口」，不是新功能。
- **有價值但要先有用途**：研發費用、金融業完整科目、重大訊息。目前沒有規則會用，屬地基，等需求出現再接。
- **打平不用動**：月營收、PER、基本資料。
- **不要抄**：TSD 的 MOPS 財報走 POST 頁面／新站 JSON，有 repo 說會被 WAF 擋（data-dl §2.4），我們用 FinMind 取得財報足夠。
- **本節未驗證**：`tdcc_hist` 的來源與每週完整度、`filing_dates` 的實際做法與涵蓋、TSD 財報內容與 FinMind 是否一致。要引用前先實查。

---

## 11. OpenAPI 增量涵蓋度探測（2026-10-06，唯讀實測）

> 目的：往後每日增量改走 OpenAPI（OGDL v1，可合法再散布、顯名即可），能不能取代我們現在打的網站端點。方法：讀兩邊 swagger（TWSE 143 條、TPEx 225 條路徑）＋逐一實打。**不是已採用的設計**，只是涵蓋度結論。

**共通限制（最關鍵）**：swagger 上這些端點**全部沒有任何查詢參數**，只回「最新一個交易日」。所以①不能補抓某一天（漏跑一天＝永久缺一天）②不能照現在的「近 3 日曆日重抓覆蓋官方更正」做，只能靠「最新日一直掛著、多跑幾班」模擬③歷史完全沒有（歷史維持用現有資料）。

| 我們需要的 | OpenAPI 端點 | 能不能 | 備註 |
| :-- | :-- | :-- | :-- |
| 上市日線 OHLCV＋漲跌價差 | TWSE `exchangeReport/STOCK_DAY_ALL` | ✅ | 1,381 列、有 Date／OHLC／Change／成交量值／筆數；含 ETF 等，需濾 4 碼 |
| 上櫃日線 | TPEx `tpex_mainboard_quotes`（1,012 列）、`tpex_mainboard_daily_close_quotes`（12,060 列含權證） | ✅ | 另有買賣揭示價、**次日參考價與次日漲跌停**（`NextReferencePrice`／`NextLimitUp`／`NextLimitDown`）——比現在更直接解決「無成交日參考價」 |
| 上市融資融券 | TWSE `exchangeReport/MI_MARGN` | ⚠️ | 欄位齊全（含前日餘額、註記），但**回應沒有日期欄**，無法自己斷言是哪一天（違反 data-fix A1），要靠同批 STOCK_DAY_ALL 的日期推定；含 ETF（1,297 列） |
| 上櫃融資融券 | TPEx `tpex_mainboard_margin_balance` | ✅ | 有 Date、前日餘額、Note |
| **上市三大法人個股** | （無） | ❌ | TWSE OpenAPI 沒有 T86；只有外資持股比率類彙總。**這是最大缺口（日資料 100 萬列級）** |
| 上櫃三大法人 | TPEx `tpex_3insti_daily_trading` | ⚠️ | 有 Date，但欄名有空白／重複的 bug（`Dealers -TotalSell`、前導空白），自營拆分欄不可靠（先前實測 148／780 檔對不上） |
| 除權息結果（含參考價） | 上市：無（只有 `TWT48U_ALL` 預告表）；上櫃：`tpex_exright_daily` | ⚠️ | 上櫃只回當天事件（8 列）、含現增欄；上市結果表無，可用已驗證的官方公式（A，99.6% 相符）自算 |
| 減資、面額變更 | （無） | ❌ | TWSE `TWTAUU`／`TWTB8U`、TPEx `revivt`／`pvChgRslt` 都不在 OpenAPI；每年約百件，量小 |
| 停止買賣／變更交易 | 上市 `TWTAWU`（暫停交易）、`BFI84U`；上櫃 `tpex_cmode`、`tpex_spendi_today` | ✅ | 上櫃終於有來源（現在的 `selfhost_stophalt` 只有上市） |
| 處置／注意股、估值 | `announcement/punish`／`notice`、`BWIBBU_d`；上櫃對應端點 | ✅ | tw-swing 已在用 |
| 漲跌標記 `refmark`（X／除息） | 無對應欄位 | ❌ | 事件日對帳基準會少一個獨立來源 |

**結論**
- 價量＋融資券＋停止買賣＋處置：**可以用 OpenAPI 取代每日增量**（約佔現在請求量的一半以上）。
- **取代不了**：上市三大法人、減資／面額變更／上市除權息結果、漲跌標記。這幾項仍得打網站端點，或改用第三方（FinMind，授權條款未查）。
- 副作用：失去「補抓指定日期」與「近 3 天重抓更正」，要用「多班排程＋隔天清晨再抓一次（端點在新交易日資料出來前一直回前一日）」模擬；漏跑一天＝永久缺。
- 工作量：新增一組 OpenAPI 收集器＋與現有網站版並行對帳（至少 15 個交易日）才能切；法人與事件表仍留網站版（但呼叫量從每天上千次降到每天個位數）。


## 12. Workflow 端點與啟動時間對照（2026-10-09）

> 目的：每個 workflow 打哪些端點、排程幾點起跑、官方資料幾點才產生，放在同一張表，看「有沒有在官方公布前去打、公布後多久才抓到」。時間一律**台北時間**（UTC+8；cron 是 UTC）。
> 證據標記：【實測】＝2026-10-08 用 `data/selfhost/_measure_20261008/poll_publish.py` 輪詢，欄位是「該來源首次出現 10/8 當日資料」的時間（輪詢間隔 ≤2 小時，是**上界**，真正公布可能更早）；【碼】＝程式或 workflow 註解寫的；【文】＝常識／官方網站說法，我們沒實測；【未驗】＝還沒量過。
> 排程延遲：GitHub 排程實測會晚 4～9 小時才起跑，下面「cron」是**名義**時間。

### 12.1 自建上游線（3 支 workflow，產出放私有 repo `tw-hold-data` 的 Release）

| Workflow | cron（UTC → 台北，名義） | 實際落點（10/8 實測） | 產出 |
| :-- | :-- | :-- | :-- |
| `openapi_daily.yml`<br>官方 OpenAPI 每日收集 | 平日 08:02／10:02／12:02／15:02／20:02 → 台北 16:02／18:02／20:02／23:02／隔日 04:02 | 延遲約 7.4／7.3／6.8／5.4／4.1 小時（15:24Z、17:17Z、18:47Z、20:24Z、隔日 00:09Z 各一次，皆成功）；台北約 23:24／01:17／02:47／04:24／08:09 | Release `openapi-daily`：openapi_prices／margin／inst／forecast／fetch_log |
| `selfhost_collect.yml`<br>自建上游收集 | 平日 15:58 → 台北 23:58，**只在「當週最後交易日」才真的收集**（`last_trading_day_guard.py` 查休市表） | 10/8 是當週最後交易日（10/9 國慶補假）；實落 20:59Z（台北隔日 04:59），成功 | Release `selfhost-data`：raw_prices／inst／margin／corp_actions／notrade／refmark／stophalt／ev_*／snap-* |
| `selfhost_datapack.yml`<br>自建資料包 | **無 cron**：上面兩支任一跑完（`workflow_run`）就接著跑；來源沒變就跳過 | 每次收集後約 1 分鐘內接跑 | Release `datapack-selfhost`：data_pack_selfhost.zip、merge_manifest.json（完整日） |

#### 12.1.1 端點與官方產生時間

| 資料 | 端點（**主**＝網站帶日期端點；OpenAPI 另列） | 哪支打 | 官方資料產生時間 | 我們的請求窗口【碼】 |
| :-- | :-- | :-- | :-- | :-- |
| 上市日線（未還原） | **主**：TWSE `rwd/zh/afterTrading/MI_INDEX?date=&type=ALLBUT0999`<br>OpenAPI：`openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | 主：selfhost_collect<br>OpenAPI：openapi_daily | 官網 **14:00** 首見【實測】；OpenAPI 在 10/8 整個窗口（到 20:00）都沒出現，上市 `Last-Modified` 是**隔天 05:20**【碼】 | 日線 16:00～隔日 08:00；08:00～16:00 不請求 |
| 上櫃日線 | **主**：TPEx `www/zh-tw/afterTrading/dailyQuotes?date=`<br>OpenAPI：`www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes` | 同上 | 官網 **15:01**、OpenAPI **16:02** 首見【實測】 | 同上 |
| 上市三大法人 | TWSE `rwd/zh/fund/T86?date=&selectType=ALLBUT0999`（**OpenAPI 沒有**） | 同上 | **16:32** 首見【實測】（10/7 在 18:00 輪已有） | 18:00 起；隔日清晨班補前一晚；08:00～18:00 不請求 |
| 上櫃三大法人 | TPEx `www/zh-tw/insti/dailyTrade?type=Daily&sect=AL&date=`<br>（OpenAPI `tpex_3insti_daily_trading` 欄名有 bug，不用） | 同上 | **15:10** 首見【實測】（10/7 在 18:00 輪還沒有，每天不同） | 同上 |
| 上市融資融券 | TWSE `rwd/zh/marginTrading/MI_MARGN?date=&selectType=STOCK`（OpenAPI 版沒有日期欄，不用） | 同上 | **20:42** 首見【實測】 | 22:00～隔日 08:00（白天整段不打） |
| 上櫃融資融券 | **主**：TPEx `www/zh-tw/margin/balance?date=`<br>OpenAPI：`tpex_mainboard_margin_balance` | 同上 | 官網 **20:52**、OpenAPI **22:03** 首見【實測】 | 同上 |
| 除權息結果（上市） | TWSE `rwd/zh/exRight/TWT49U?startDate=&endDate=`（日期區間）；現增明細 `exRight/TWT49UDetail?STK_NO=&T1=`（逐件，手動腳本） | selfhost_collect（近兩個月重抓） | 【未驗】當晚是否已含「當日」事件（B6 待驗） | 每週一次 |
| 除權息結果（上櫃） | TPEx `www/zh-tw/bulletin/exDailyQ?startDate=&endDate=` | 同上 | 【未驗】同上（OpenAPI `tpex_exright_daily` 只回當天，8 列） | 每週一次 |
| 減資 | TWSE `rwd/zh/reducation/TWTAUU`；TPEx `bulletin/revivt`（日期區間，近兩年重抓） | 同上 | 【未驗】（事件公告日不固定） | 每週一次 |
| 面額變更 | TWSE `rwd/zh/change/TWTB8U`；TPEx `bulletin/pvChgRslt` | 同上 | 【未驗】 | 每週一次 |
| 除權息預告表 | OpenAPI `openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL`（網站版 `exRight/TWT48U` 內容相同）；上櫃 `tpex_exright_prepost` | openapi_daily（同市場至少間隔 3 小時）；selfhost_collect 每週存快照 | 只有未來事件、沒有歷史，漏存就補不回來 | 每班 |
| 停止買賣中名單（上市） | TWSE `rwd/zh/violation/stop`（`date=` 被官方忽略，只回當天） | selfhost_collect | 當天名單，無歷史 | 每週一天（無下游使用，可接受） |
| 休市日曆 | OpenAPI `openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule` | selfhost_collect 的 guard | 年度表 | 每次 |
| 減資交叉驗證 | FinMind `api.finmindtrade.com/api/v4/data`（非官方，只做交叉驗證） | selfhost_collect | — | 每週 150 檔 |

**結論**
1. 官網端點比 OpenAPI 早出（上櫃日線早約 1 小時；上市日線 OpenAPI 10/8 整個窗口都沒出現，隔天 05:20 才更新）。所以**上市日線以官網為主、OpenAPI 只當備援**。
2. 最晚的是融資券（官網 20:42～20:52、OpenAPI 22:03）。名義的 16:02／18:02／20:02 三班就算準時，抓不到當天融資券，請求窗口（22:00 起）也不讓它們去打；實際因為延遲，第一班在 23:24 才起跑，剛好落在窗口內。
3. GitHub 延遲 4～7 小時，實際起跑多在 23:00 之後，**反而都在官方公布之後**。真正的風險是 OpenAPI 只回最新一天：若某天所有班次都晚到隔日官方新資料出來之後，前一天的 OpenAPI 日線補不回來（網站帶日期端點仍補得回）。
4. 官方事後會更正當日資料（10/5 實測投信 14 檔、成交量 17 檔被改過），所以收集器對近 3 個日曆日重抓覆蓋；週收集在最後交易日 23:58 之後才拿最完整的版本。

#### 12.1.2 一天時間軸（台北，平日）

| 台北時間 | 官方產生（10/8 實測首見） | 我們的動作 |
| :-- | :-- | :-- |
| 14:00 | 上市日線（官網） | 不請求（窗口 16:00 起） |
| 15:01～15:10 | 上櫃日線、上櫃法人（官網） | 不請求 |
| 16:02（名義） | 上櫃日線 OpenAPI 16:02 | openapi_daily 第 1 班名義時間（實落約 23:24） |
| 16:32 | 上市法人（官網） | 18:00 起才請求法人 |
| 18:02／20:02（名義） | — | 第 2、3 班名義時間（實落約次日 01:17、02:47） |
| 20:42～20:52 | 上市／上櫃融資券（官網） | 22:00 起才請求融資 |
| 22:03 | 上櫃融資 OpenAPI | — |
| 23:02（名義） | — | 第 4 班名義時間（實落約次日 04:24） |
| 23:58（名義） | — | selfhost_collect（只在週最後交易日；實落約次日 04:59） |
| 隔日 04:02（名義） | 上市 OpenAPI 日線隔日 05:20 才更新 | 第 5 班名義時間（實落約次日 08:09） |
| 收集完成後 | — | selfhost_datapack 接跑，產出 data_pack_selfhost.zip |

> 「實落」是用 10/8 五班的延遲量推出來的（7.4／7.3／6.8／5.4／4.1 小時）。Actions 紀錄只有建立時間、看不出屬於哪一班，所以是推論；每天延遲不同。

### 12.2 其他 workflow（tw-hold 自己的 6 支＋依賴的 tw-swing 上游）

| Workflow | cron（UTC → 台北，名義） | 觸發鏈 | 主要端點 | 資料產生時間 | 產出 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `rebuild.yml`<br>每日重算三清單 | 平日 08:17 → 16:17（備援）；**主路徑**是 tw-swing publish 完發的 `repository_dispatch: bundle-published` | tw-swing `daily.yml` → `publish_bundle.yml` → dispatch → 本支 | GitHub API 下載 tw-swing Release `data-latest`（bundle）；私有 Release `refdata-latest`；FinMind `TaiwanStockPrice`（006201 代理）；投信 PCF（見 pcf_retry） | 日線來自上游 `data_pack.zip`，約 05:08 才好【碼，DATA_FLOW.md】 | `data/derived/*`（三清單、active_etf_flags、short_scan）、`derived-latest` |
| `chip_flow_evening.yml`<br>籌碼流向（傍晚） | 平日 10:28 → 18:28 | 獨立排程 | TAIFEX `www.taifex.com.tw/cht/3/futContractsDateDown`（CSV）＋`openapi.taifex.com.tw/v1/`（外資台指期）；TWSE `rwd/zh/fund/BFI82U?type=day&dayDate=`（三大法人買賣金額） | 兩者「盤後下午才公布」【碼註解】；**18:30 TAIFEX 當天資料是否已出【未驗】**（沒出會退回前一天，不會錯）；隔天 06:37 那班當補漏 | `data/reference/foreign_futures.parquet`、`inst_flow.parquet` |
| `global_macro.yml`<br>國際總經快照 | 平日 22:37 → 隔日 06:37 | 獨立排程，與 chip_flow 共用 concurrency | yfinance（Yahoo，非官方）：美股指數／VIX／美元／美債／個股、日經／恆生／KOSPI；`openapi.taifex.com.tw/v1/DailyMarketReportFut`（台指期日盤＋夜盤）；另重跑 foreign_futures、inst_flow | 美股常規盤 16:00 ET 收，夏令＝台北 04:00、冬令＝05:00【文】，排 06:37 留緩衝；日經等亞洲指數台北下午就收【文】 | `global_macro.parquet`、`tx_futures.parquet` 等 |
| `pcf_retry.yml`<br>主動式 ETF PCF 補跑 | 平日 09:13、11:13 → 17:13、19:13 | 排在 rebuild 備援 16:17 之後；只在 `missing` 非空或今天完全沒資料才重抓 | 投信官網：統一 `www.ezmoney.com.tw/ETF/Transaction/PCF`（cookie＋GetPCF）、群益 `www.capitalfund.com.tw/CFWeb/api/etf/buyback`、復華 `www.fhtrust.com.tw` assets；收盤價 TWSE `exchangeReport/STOCK_DAY_ALL` | **只給「當天」、沒有歷史**，漏一天永久缺；各家幾點更新【未驗】（非官方承諾，會改版） | `data/pcf/<代號>/<日期>.parquet`、`active_etf_flags.json` |
| `heartbeat.yml`<br>心跳（開盤前新鮮度守門） | 平日 00:28 → 08:28 | 獨立排程 | **不打外部端點**，只讀 `_meta.json`、`index_0050.parquet`、`index_006201.parquet` 的日期 | 實測 GitHub 常延遲到 13:00～14:00 才跑 | 只檢查不修；沒設告警 webhook |
| `check_secrets.yml` | 無（手動） | `workflow_dispatch` | — | — | 檢查 secrets |

**tw-swing 端 workflow（tw-hold 依賴的上游，不在本 repo；取自 DATA_FLOW.md §3，這次沒重新核對）**

| Workflow | 台北時間 | 備註 |
| :-- | :-- | :-- |
| `daily.yml` | 21:07／01:07／05:32（三槍，平日） | 讀別人 repo 的 `data_pack.zip`（約 05:08 才好），產日線、模擬單、share-latest.json |
| `publish_bundle.yml` | daily 完成即接（`workflow_run`）＋cron 06:09／07:09／08:38 | 有閘門（沒新資料跳過）；發 Release `data-latest` 並 dispatch 給 tw-hold |
| `fundamentals.yml` | 週六 10:07 | 財報五表／TDCC／月營收歷史 |

### 12.3 兩條線的差別

- **自建上游**：直接打官方 TWSE／TPEx（網站帶日期端點為主、OpenAPI 補強），自己存原始價、自己還原。目前是影子期（10/12 起只產只比，tw-swing 不讀；go/no-go 看 10/23）。
- **其他 workflow**：日線仍靠 tw-swing 讀的上游 `data_pack.zip`（約 05:08 才好）；籌碼／總經／PCF 是各自直接打 TAIFEX、TWSE、Yahoo、投信官網的小資料源，與自建上游互不相依。
- **還沒量的官方時間**（別當成已知）：事件類（TWT49U／exDailyQ／TWTAUU／TWTB8U）、TAIFEX 盤後、BFI82U、三家投信 PCF 各自的更新時間。要量就沿用 `poll_publish.py` 的做法（官方還沒公布的時段不請求）。
- **ETF 範圍**（使用者 2026-10-09）：5～6 碼與上櫃 ETF **要收**但**不進推薦**，只供個股查詢、多軌體檢、總經導航，並取代總經導航對 FinMind（006201）的依賴。現況自建收集只收純數字 4 碼（`selfhost_raw_prices.py:122` 等四處過濾），不是來源限制；官方日線端點本來會回這些代碼。做法見 `updatePRD-opus.md` §6.2。
