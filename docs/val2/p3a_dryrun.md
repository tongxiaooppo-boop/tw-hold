# 估值 2.0 P3a 全母體乾跑


評價日：2026-11-02；母體：1019 檔。
新卡：2026-11-02T18:35:50+08:00 ～ 2026-11-02T18:38:47+08:00，176.26 秒；成功 1019，例外 0。
舊卡：2026-11-02T18:38:47+08:00 ～ 2026-11-02T18:39:41+08:00，53.70 秒；成功 1019，例外 0。
新卡計時含共用資料載入；舊卡計時含舊引擎擷取與逐檔計算，不重複計入資料載入。

口徑：依 stocks 原始順序；同一份 live 季報調整 EPS 一次，日線與 PER 排序並裁至評價日。位置比較納入 na（引擎回傳位置）；舊有價嚴格依 no_price is None，不額外以 fair 篩選。例外不列入卡片統計。前瞻三價可用指 cheap／fair／dear 都非空；cap=50 以主三價計算。estimate stop 原因依 items.name 分組，一檔在同一原因只計一次，可跨原因重複；另列原始 why 前三名供追溯。

## 例外

新卡：0 檔。

| ticker | 錯誤 |
| --- | --- |


舊卡：0 檔。

| ticker | 錯誤 |
| --- | --- |


## 分層與路線


| tier | 檔數 |
| --- | --- |
| A | 730 |
| B | 110 |
| C | 124 |
| D | 55 |



| A 路線 | 檔數 |
| --- | --- |
| PE | 575 |
| PB | 155 |



| D reason | 檔數 |
| --- | --- |
| 財報不足 12 季，資料不足，不做估值 | 23 |
| 特殊類型（生技／併購重組等），歷史倍數不可比，不做估值 | 17 |
| 股價淨值比自身歷史不足（有效月數未達門檻） | 9 |
| 現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價 | 5 |
| 近 4 季 EPS 不可用（近 4 季財報不連續或不足（沒有已公布財報）） | 1 |



| route | 檔數 |
| --- | --- |
| PE | 810 |
| PB | 164 |
| — | 45 |


## 三價與購買區間


| 項目 | 檔數 |
| --- | --- |
| 前瞻三價可用 | 0 |
| NOTE_FWD_SAME | 400 |
| NOTE_CAP_FLAT | 9 |
| buy_range normal | 721 |
| buy_range fwd_up | 0 |
| cap=50 | 51 |


## 可信度


| data level | 檔數 |
| --- | --- |
| ok | 959 |
| unchecked | 0 |
| warn | 39 |
| stop | 21 |



| share_basis level | 檔數 |
| --- | --- |
| ok | 0 |
| unchecked | 958 |
| warn | 56 |
| stop | 5 |



| comparability level | 檔數 |
| --- | --- |
| ok | 429 |
| unchecked | 126 |
| warn | 464 |
| stop | 0 |



| estimate level | 檔數 |
| --- | --- |
| ok | 470 |
| unchecked | 0 |
| warn | 261 |
| stop | 288 |


estimate stop：288 檔；前 3 名原因：

| 原因名稱 | 檔數 |
| --- | --- |
| 橋接殘差 | 228 |
| 營收劇變 | 81 |
| 近零EPS | 47 |


原始 why 前三名（保留數值、不合併百分比）：

| why | 筆數 |
| --- | --- |
| 用試算公式重算近 8 季，單季誤差平均占近 4 季 EPS 12%，試算停用 | 25 |
| 用試算公式重算近 8 季，單季誤差平均占近 4 季 EPS 11%，試算停用 | 18 |
| 用試算公式重算近 8 季，單季誤差平均占近 4 季 EPS 13%，試算停用 | 15 |


share_basis stop：

| ticker | 名稱 | 原因 |
| --- | --- | --- |
| 6173 | 信昌電 | 現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價 |
| 6176 | 瑞儀 | 現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價 |
| 1563 | 巧新 | 現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價 |
| 2323 | 中環 | 現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價 |
| 3356 | 奇偶 | 現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價 |


## 舊卡與新卡

舊有價：876 檔；其中新卡例外 0 檔。

| 舊位置 → 新 tier | A | B | C | D |
| --- | --- | --- | --- | --- |
| cheap | 152 | 12 | 0 | 11 |
| dear | 265 | 83 | 6 | 33 |
| fair | 252 | 15 | 0 | 7 |
| na | 39 | 0 | 0 | 1 |


位置翻轉：330 檔（兩邊都有 position 且不同，含 na）。
其中兩邊皆為 cheap／fair／dear 的翻轉：117 檔。

| 舊位置 | 新位置 | 檔數 |
| --- | --- | --- |
| cheap | dear | 6 |
| cheap | fair | 36 |
| cheap | na | 23 |
| dear | cheap | 8 |
| dear | fair | 26 |
| dear | na | 130 |
| fair | cheap | 24 |
| fair | dear | 17 |
| fair | na | 22 |
| na | cheap | 13 |
| na | dear | 13 |
| na | fair | 12 |


### 隨機抽 20 檔翻轉（seed=7，先依 ticker 排序再抽樣）


| ticker | 名稱 | 舊位置 | 舊合理價 | 舊 source | 新 tier | 新位置 | 新合理價 | 新 base_name |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5243 | 乙盛-KY | na | 136.91977408286016 | 歷史 | A | fair | 113.80035170327946 | 近 4 季 EPS |
| 2801 | 彰銀 | fair | 27.028239202657808 | 補位 | A | dear | 20.919735796202364 | 每股淨值 |
| 6125 | 廣運 | dear | 4.785 | 補位 | B | na | — | — |
| 1903 | 士紙 | dear | 22.275 | 補位 | B | na | — | — |
| 2354 | 鴻準 | dear | 37.20857673503212 | 歷史 | A | fair | 52.37142353345942 | 近 4 季 EPS |
| 6944 | 兆聯實業 | dear | 357.6942307692307 | 補位 | D | na | — | — |
| 2417 | 圓剛 | dear | 22.770000000000003 | 補位 | B | na | — | — |
| 5864 | 致和證 | cheap | 220.20238095238093 | 補位 | A | dear | 23.465140481222342 | 每股淨值 |
| 7786 | 東方風能 | cheap | 177.92100000000002 | 補位 | D | na | — | — |
| 2059 | 川湖 | na | 9805.882751354731 | 歷史 | A | dear | 4957.333910620114 | 近 4 季 EPS |
| 6831 | 邁科 | dear | 98.175 | 補位 | B | na | — | — |
| 3485 | 敘豐 | dear | 108.24000000000001 | 補位 | B | na | — | — |
| 1736 | 喬山 | cheap | 237.20000000000002 | 歷史 | A | fair | 181.37145896451642 | 較低獲利情境 |
| 2399 | 映泰 | cheap | 65.67 | 補位 | B | na | — | — |
| 6425 | 易發 | dear | 17.325 | 補位 | B | na | — | — |
| 6272 | 驊陞 | cheap | 32.175000000000004 | 補位 | B | na | — | — |
| 2348 | 海悅 | na | 87.64423944107557 | 歷史 | A | dear | 45.58297023709761 | 近 4 季 EPS |
| 3691 | 碩禾 | dear | 45.21 | 補位 | B | na | — | — |
| 2406 | 國碩 | dear | 2.97 | 補位 | B | na | — | — |
| 7712 | 博盛半導體 | fair | 135.9663355528054 | 補位 | B | na | — | — |


## 指定個股完整摘要

第一檔營建：2542；第一檔 C：1101。

### 2330 台積電


```json
{
  "tier": "A",
  "route": "PE",
  "reason": null,
  "price": 2370.0,
  "prices": {
    "cheap": 2034.812459954502,
    "fair": 2456.829267522161,
    "dear": 2752.150419664061,
    "base": 98.73411152125371,
    "base_name": "近 4 季 EPS",
    "metric": "pe",
    "mults": [
      20.60901170429314,
      24.8832873428278,
      27.8743625405656
    ],
    "raw_mults": [
      20.60901170429314,
      24.8832873428278,
      27.8743625405656
    ],
    "capped": false,
    "cap": 50.0,
    "n_valid": 36,
    "n_loss": 0,
    "window": "2023-11～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 2034.812459954502,
    "high": 2456.829267522161,
    "state": "normal",
    "note": null
  },
  "revision": {
    "last_pct": 0.0036387094133858433,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "ok",
      "items": []
    },
    "estimate": {
      "level": "ok",
      "items": []
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+55%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q3",
      "rev_text": "+51%",
      "eps_text": "+71%"
    },
    {
      "key": "ttm",
      "period": "2025Q4～2026Q3",
      "rev_text": "+36%",
      "eps_text": "+61%"
    }
  ]
}
```

### 2327 國巨*


```json
{
  "tier": "A",
  "route": "PB",
  "reason": null,
  "price": 502.0,
  "prices": {
    "cheap": 148.78976772171075,
    "fair": 200.6453058259406,
    "dear": 321.8490711796825,
    "base": 86.13944498145953,
    "base_name": "每股淨值",
    "metric": "pb",
    "mults": [
      1.7273128211324782,
      2.32930808724304,
      3.7363727064756054
    ],
    "raw_mults": [
      1.7273128211324782,
      2.32930808724304,
      3.7363727064756054
    ],
    "capped": false,
    "cap": null,
    "n_valid": 68,
    "n_loss": 0,
    "window": "2020-10～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 148.78976772171075,
    "high": 200.6453058259406,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": -0.0037110066419348,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "warn",
      "items": [
        "股數對不上",
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "warn",
      "items": [
        "僅單一景氣事件"
      ]
    },
    "estimate": {
      "level": "ok",
      "items": []
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+46%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q3",
      "rev_text": "+50%",
      "eps_text": "+62%"
    },
    {
      "key": "ttm",
      "period": "2025Q4～2026Q3",
      "rev_text": "+32%",
      "eps_text": "+68%"
    }
  ]
}
```

### 2881 富邦金


```json
{
  "tier": "A",
  "route": "PB",
  "reason": null,
  "price": 161.5,
  "prices": {
    "cheap": 89.86275527628035,
    "fair": 110.88849927978214,
    "dear": 133.18995979998124,
    "base": 91.48106992671647,
    "base_name": "每股淨值",
    "metric": "pb",
    "mults": [
      0.9823098412411166,
      1.2121469432814083,
      1.4559291873901001
    ],
    "raw_mults": [
      0.9823098412411166,
      1.2121469432814083,
      1.4559291873901001
    ],
    "capped": false,
    "cap": null,
    "n_valid": 73,
    "n_loss": 0,
    "window": "2020-10～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 89.86275527628035,
    "high": 110.88849927978214,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": null,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": 0.14894822244870157,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "股數對不上",
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "ok",
      "items": []
    },
    "estimate": {
      "level": "ok",
      "items": [
        "試算季"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "-45%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2025Q4",
      "rev_text": "+39%",
      "eps_text": "+2%"
    },
    {
      "key": "ttm",
      "period": "2025Q1～2025Q4",
      "rev_text": "+10%",
      "eps_text": "-19%"
    }
  ]
}
```

### 2882 國泰金


```json
{
  "tier": "A",
  "route": "PB",
  "reason": null,
  "price": 116.0,
  "prices": {
    "cheap": 69.94033194538457,
    "fair": 76.2654319243136,
    "dear": 110.79106710880994,
    "base": 77.15546653051204,
    "base_name": "每股淨值",
    "metric": "pb",
    "mults": [
      0.9064857629721653,
      0.9884643999158962,
      1.4359457870039098
    ],
    "raw_mults": [
      0.9064857629721653,
      0.9884643999158962,
      1.4359457870039098
    ],
    "capped": false,
    "cap": null,
    "n_valid": 73,
    "n_loss": 0,
    "window": "2020-10～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 69.94033194538457,
    "high": 76.2654319243136,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": null,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": 0.1348421205428033,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "股數對不上",
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "ok",
      "items": []
    },
    "estimate": {
      "level": "ok",
      "items": [
        "試算季"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "-41%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2025Q4",
      "rev_text": "+37%",
      "eps_text": "+335%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q1～2025Q4",
      "rev_text": "-2%",
      "eps_text": "-3%"
    }
  ]
}
```

### 3211 順達


```json
{
  "tier": "A",
  "route": "PE",
  "reason": null,
  "price": 297.5,
  "prices": {
    "cheap": 59.37223768152694,
    "fair": 123.12717922901024,
    "dear": 224.4,
    "base": 7.48,
    "base_name": "較低獲利情境",
    "metric": "pe",
    "mults": [
      7.93746493068542,
      16.460852838102973,
      30.0
    ],
    "raw_mults": [
      7.93746493068542,
      16.460852838102973,
      32.761234096228684
    ],
    "capped": true,
    "cap": 30.0,
    "n_valid": 60,
    "n_loss": 0,
    "window": "2021-11～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 59.37223768152694,
    "high": 123.12717922901024,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": -0.0289193872821627,
    "streak": 1,
    "direction": "down"
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": 10.94,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "warn",
      "items": [
        "倍數分布",
        "倍數截斷"
      ]
    },
    "estimate": {
      "level": "stop",
      "items": [
        "橋接殘差",
        "業外閘門",
        "高變動"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "-34%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q2",
      "rev_text": "+7%",
      "eps_text": "-65%"
    },
    {
      "key": "ttm",
      "period": "2025Q3～2026Q2",
      "rev_text": "+19%",
      "eps_text": "-39%"
    }
  ]
}
```

### 2408 南亞科


```json
{
  "tier": "A",
  "route": "PB",
  "reason": null,
  "price": 454.5,
  "prices": {
    "cheap": 88.24095850064603,
    "fair": 116.39015982153929,
    "dear": 173.17650217135193,
    "base": 94.21291958656869,
    "base_name": "每股淨值",
    "metric": "pb",
    "mults": [
      0.936612079191164,
      1.2353948941640935,
      1.838139640840093
    ],
    "raw_mults": [
      0.936612079191164,
      1.2353948941640935,
      1.838139640840093
    ],
    "capped": false,
    "cap": null,
    "n_valid": 73,
    "n_loss": 32,
    "window": "2020-10～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 88.24095850064603,
    "high": 116.39015982153929,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": -0.013109925411839751,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "warn",
      "items": [
        "歷史可比性"
      ]
    },
    "estimate": {
      "level": "warn",
      "items": [
        "稅率／少數股權",
        "前瞻跳升"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+577%（基期低）",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q3",
      "rev_text": "+612%（基期低）",
      "eps_text": "+5114%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q4～2026Q3",
      "rev_text": "+586%（基期低）",
      "eps_text": "虧轉盈"
    }
  ]
}
```

### 5904 寶雅


```json
{
  "tier": "A",
  "route": "PE",
  "reason": null,
  "price": 72.5,
  "prices": {
    "cheap": 61.85037038937903,
    "fair": 69.79896066949482,
    "dear": 79.50557290666694,
    "base": 3.402,
    "base_name": "近 4 季 EPS",
    "metric": "pe",
    "mults": [
      18.18059094338008,
      20.517037233831516,
      23.370244828532314
    ],
    "raw_mults": [
      18.18059094338008,
      20.517037233831516,
      23.370244828532314
    ],
    "capped": false,
    "cap": 30.0,
    "n_valid": 60,
    "n_loss": 0,
    "window": "2021-11～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 61.85037038937903,
    "high": 69.79896066949482,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": null,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "股數對不上",
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "ok",
      "items": []
    },
    "estimate": {
      "level": "ok",
      "items": [
        "試算季"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+16%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q2",
      "rev_text": "+15%",
      "eps_text": "+46%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q3～2026Q2",
      "rev_text": "+10%",
      "eps_text": "+25%"
    }
  ]
}
```

### 3661 世芯-KY


```json
{
  "tier": "A",
  "route": "PE",
  "reason": null,
  "price": 3425.0,
  "prices": {
    "cheap": 2520.8303419376307,
    "fair": 3285.247305702275,
    "dear": 3612.5,
    "base": 72.25,
    "base_name": "近 4 季 EPS",
    "metric": "pe",
    "mults": [
      34.89038535553814,
      45.47055094397612,
      50.0
    ],
    "raw_mults": [
      34.89038535553814,
      45.47055094397612,
      61.337137887032874
    ],
    "capped": true,
    "cap": 50.0,
    "n_valid": 60,
    "n_loss": 0,
    "window": "2021-11～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 2520.8303419376307,
    "high": 3285.247305702275,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": 0.09236836798904502,
    "streak": 2,
    "direction": "up"
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "warn",
      "items": [
        "倍數截斷"
      ]
    },
    "estimate": {
      "level": "stop",
      "items": [
        "營收劇變",
        "業外閘門",
        "高變動",
        "前瞻跳升"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+496%（基期低）",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q2",
      "rev_text": "-17%",
      "eps_text": "+22%"
    },
    {
      "key": "ttm",
      "period": "2025Q3～2026Q2",
      "rev_text": "-51%",
      "eps_text": "-10%"
    }
  ]
}
```

### 1815 富喬


```json
{
  "tier": "B",
  "route": "PE",
  "reason": null,
  "price": 126.5,
  "prices": null,
  "fwd_prices": null,
  "buy_range": null,
  "revision": {
    "last_pct": 0.003982796487365103,
    "streak": 0,
    "direction": null
  },
  "b_tier": {
    "pe_now": 32.024906923774736,
    "industry_pct": 0.6339285714285714,
    "eps_needed": 5.0833137313455055,
    "n_peers": 112,
    "median_pe": 24.885341862721628
  },
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "warn",
      "items": [
        "倍數分布",
        "倍數截斷"
      ]
    },
    "estimate": {
      "level": "warn",
      "items": [
        "橋接殘差",
        "業外閘門"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+82%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q3",
      "rev_text": "+77%",
      "eps_text": "+100%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q4～2026Q3",
      "rev_text": "+49%",
      "eps_text": "+274%"
    }
  ]
}
```

### 6477 安集


```json
{
  "tier": "C",
  "route": "PE",
  "reason": null,
  "price": 30.0,
  "prices": null,
  "fwd_prices": null,
  "buy_range": null,
  "revision": {
    "last_pct": -0.16604232080584924,
    "streak": 1,
    "direction": "down"
  },
  "b_tier": null,
  "c_tier": {
    "pb_now": 1.2111552490722577,
    "pb_pct": 0.0547945205479452,
    "n_valid": 73,
    "text": "獲利接近零（近 4 季 EPS 不到 0.05 元），不用獲利估價"
  },
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "unchecked",
      "items": []
    },
    "estimate": {
      "level": "stop",
      "items": [
        "橋接殘差",
        "近零EPS",
        "業外閘門",
        "高變動",
        "稅率／少數股權",
        "前瞻跳升"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "-47%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q2",
      "rev_text": "+3%",
      "eps_text": "-27%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q3～2026Q2",
      "rev_text": "+12%",
      "eps_text": "虧轉盈"
    }
  ]
}
```

### 5878 台名


```json
{
  "tier": "A",
  "route": "PB",
  "reason": null,
  "price": 36.7,
  "prices": {
    "cheap": 41.746492549487854,
    "fair": 45.72818447732318,
    "dear": 47.86414386323229,
    "base": 20.76,
    "base_name": "每股淨值",
    "metric": "pb",
    "mults": [
      2.010910045736409,
      2.202706381373949,
      2.3055945984215938
    ],
    "raw_mults": [
      2.010910045736409,
      2.202706381373949,
      2.3055945984215938
    ],
    "capped": false,
    "cap": null,
    "n_valid": 73,
    "n_loss": 0,
    "window": "2020-10～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 41.746492549487854,
    "high": 45.72818447732318,
    "state": "normal",
    "note": null
  },
  "revision": {
    "last_pct": null,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": null,
  "roe": 0.12095921232283995,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "ok",
      "items": []
    },
    "estimate": {
      "level": "ok",
      "items": [
        "試算季"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+1%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2025Q4",
      "rev_text": "+3%",
      "eps_text": "+27%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q1～2025Q4",
      "rev_text": "+4%",
      "eps_text": "+29%"
    }
  ]
}
```

### 2542 興富發


```json
{
  "tier": "A",
  "route": "PB",
  "reason": null,
  "price": 39.3,
  "prices": {
    "cheap": 36.54866565249011,
    "fair": 38.42198315205707,
    "dear": 41.13881755666227,
    "base": 23.38872221680107,
    "base_name": "每股淨值",
    "metric": "pb",
    "mults": [
      1.5626619237127761,
      1.6427568293772368,
      1.7589168478434698
    ],
    "raw_mults": [
      1.5626619237127761,
      1.6427568293772368,
      1.7589168478434698
    ],
    "capped": false,
    "cap": null,
    "n_valid": 73,
    "n_loss": 0,
    "window": "2020-10～2026-10"
  },
  "fwd_prices": null,
  "buy_range": {
    "low": 36.54866565249011,
    "high": 38.42198315205707,
    "state": "normal",
    "note": "現價高於購買區間上緣"
  },
  "revision": {
    "last_pct": 0.032199691317712054,
    "streak": 1,
    "direction": "up"
  },
  "b_tier": null,
  "c_tier": null,
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "ok",
      "items": []
    },
    "estimate": {
      "level": "stop",
      "items": [
        "營收劇變",
        "高變動"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+104%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q2",
      "rev_text": "+254%",
      "eps_text": "+469%（基期低）"
    },
    {
      "key": "ttm",
      "period": "2025Q3～2026Q2",
      "rev_text": "+111%",
      "eps_text": "+66%"
    }
  ]
}
```

### 1101 台泥


```json
{
  "tier": "C",
  "route": "PE",
  "reason": null,
  "price": 28.35,
  "prices": null,
  "fwd_prices": null,
  "buy_range": null,
  "revision": {
    "last_pct": null,
    "streak": 0,
    "direction": null
  },
  "b_tier": null,
  "c_tier": {
    "pb_now": 1.0547044621368278,
    "pb_pct": 0.3561643835616438,
    "n_valid": 73,
    "text": "虧損中，不用獲利估價"
  },
  "roe": null,
  "eps_3y_avg": null,
  "status": {
    "data": {
      "level": "ok",
      "items": []
    },
    "share_basis": {
      "level": "unchecked",
      "items": [
        "面額與特別股"
      ]
    },
    "comparability": {
      "level": "unchecked",
      "items": []
    },
    "estimate": {
      "level": "ok",
      "items": [
        "試算季"
      ]
    }
  },
  "growth": [
    {
      "key": "month",
      "period": "2026-09",
      "rev_text": "+8%",
      "eps_text": null
    },
    {
      "key": "last_q",
      "period": "2026Q2",
      "rev_text": "+8%",
      "eps_text": "去年同期為 0"
    },
    {
      "key": "ttm",
      "period": "2025Q3～2026Q2",
      "rev_text": "-6%",
      "eps_text": "轉虧"
    }
  ]
}
```

## 執行驗證


倍數重建
```json
{
  "command": "python build_multiples.py --asof 2026-11-02 --out-dir _dryrun --workers 5",
  "seconds": 1406.502,
  "exit_code": 0,
  "output_modified": "2026-11-02T18:02:40+08:00",
  "industries_with_values": 37
}
```

全套 pytest
```json
{
  "passed": 1261,
  "failed": 0,
  "skipped": 14,
  "seconds": 244.45,
  "temporary_directory_removed": true
}
```

倍數母體 1019；成功 1019；失敗 0。