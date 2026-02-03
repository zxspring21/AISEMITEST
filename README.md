# STDF → Relational DB + Streamlit Dashboard

將 STDF (Standard Test Data Format) 讀入關聯式資料庫，並以 Streamlit 做 Lot-to-Lot / Wafer-to-Wafer / Die-to-Die 分析與查詢視覺化。

## 架構

- **關聯階層**: Company → Product → Stage → TestProgram → Lot → Wafer → Die；Die 關聯 Bin 與 TestItem（TestSuite 可選）。
- **STDF 對應**: MIR → Lot（含 TSTR_TYP、NODE_NAM、FACIL_ID 等 tester 資訊）；SDR → SiteEquipment（probe card、load board、handler）；WIR/WRR → Wafer；PIR/PRR → Die；PTR/FTR → TestItem；PRR bin → Bin；HBR/SBR → Bin 名稱；TSR → TestSuite 與 TestDefinition（test_num→TestSuite）。
- **DB**: SQLite 預設（`stdf_data.db`），可改 `STDF_DB_URL` 使用 PostgreSQL 等。
- **前端**: Streamlit 儀表板（上傳 STDF、總覽、Lot/Wafer/Die 分析、自訂 SQL 查詢與圖表）。

## 安裝

```bash
cd AISemiTest
pip install -r requirements.txt
```

## 使用

### 1. 指令列載入 STDF

```bash
python stdf_loader.py <path/to/file.stdf> [company] [product] [stage]
```

專案內 `data/` 下的 .stdf 可依序載入：

```bash
python stdf_loader.py data/demofile.stdf
python stdf_loader.py data/lot2.stdf
python stdf_loader.py data/lot3.stdf
python stdf_loader.py data/ROOS_20140728_131230.stdf
```

或一次載入全部（需先安裝依賴）：

```bash
chmod +x load_all_stdf.sh
./load_all_stdf.sh
```

範例（指定 company/product/stage）：

```bash
python stdf_loader.py data/demofile.stdf MyCompany MyProduct FT
```

### 2. 啟動 Streamlit 儀表板

```bash
streamlit run app.py
```

在瀏覽器可：

- **Dashboard**: 總覽 Lots / Wafers / Dies 數量與列表（含 Tester 資訊）。
- **Load STDF**: 上傳 STDF 並寫入 DB（可填 Company / Product / Stage）。
- **Lot-to-Lot**: 選多個 Lot，看 die 數與參數分佈（PTR 盒鬚圖）。
- **Wafer-to-Wafer**: 選 Lot 看各 Wafer 的 part/good count 與 yield；**多片比較**：選 2+ wafers 後顯示 bin 或 test 值不同的 die 位置，快速找出差異。
- **Die-to-Die**: 選 Wafer 後看 wafer map（X,Y 著色 bin 或參數）。
- **Fail Pareto**: Die-level 或 Wafer-level 的 fail pareto（依 failing test、依 bin 排名）。
- **TestSuite→TestItem**: 顯示各 TestSuite 對應的 TestDefinition 與 TestItem。
- **Bin Summary**: 依 Lot/Wafer 的 bin 統計與 pie chart。
- **Equipment**: Tester / Node / Facility / Floor 與 SiteEquipment（probe card、load board、handler）、測試時間比較。
- **Custom SQL**: 輸入 SQL 查詢並以表格/圖表檢視結果。

## 環境變數（可選）

| 變數 | 說明 |
|------|------|
| `STDF_DB_URL` | 資料庫 URL，預設 `sqlite:///stdf_data.db` |
| `STDF_DEFAULT_COMPANY` | 未指定時的預設 Company |
| `STDF_DEFAULT_PRODUCT` | 未指定時的預設 Product |
| `STDF_DEFAULT_STAGE` | 未指定時的預設 Stage |

## 依賴

- **pystdf**: 解析 STDF v4。
- **SQLAlchemy**: ORM 與 DB 連線。
- **Streamlit**: 儀表板與互動查詢。
- **pandas / plotly**: 資料表與圖表。

## 授權

pystdf 為 GPL；本專案程式碼可依需求自訂授權。
