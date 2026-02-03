# STDF Dashboard 使用說明 (User Guide)

本文件說明儀表板左側 **Navigation** 各頁面功能、可執行操作與使用目的。

---

## 側邊欄篩選（Filters，適用所有頁面）

**功能**：依 **Company → Product → Stage → Test Program** 階層與 **時間區間** 篩選資料，後續 Lot-to-Lot、Wafer-to-Wafer、Die-to-Die、Fail Pareto、Bin Summary、Equipment 等頁面皆只顯示符合條件的 Lot / Wafer。

**可做什麼**：
- **Company**：選擇公司（— All — 表示不篩選）。
- **Product**：選擇產品（依所選 Company 篩選選項）。
- **Stage**：選擇階段（依所選 Product 篩選選項）。
- **Test Program**：選擇測試程式（依所選 Stage 篩選選項）。
- **Time range (lot start)**：勾選「Filter by time」後可設定 **Start date**、**End date**，只顯示 **Lot 開始時間** 落在該區間內的 Lot。

**目的**：依組織階層與時間區間縮小分析範圍，做更聚焦的 Lot / Wafer / Die 分析。

---

## 1. Dashboard（總覽）

**功能**：顯示資料庫整體概況（受側邊欄篩選與時間區間影響）。

**可做什麼**：
- 查看符合篩選條件的 **Lots / Wafers / Dies** 總數量。
- **Hierarchy (Company → Product → Stage → Test Program)**：以可展開區塊顯示階層樹，每個 Test Program 顯示其 Lots、Wafers、Dies 數量。
- **Test time summary (filtered)**：符合篩選的 Lot 列表，含 **Total test time (ms)**（該 Lot 所有 Die 的 test_t 總和）、**Lot start**（Lot 開始時間）。

**目的**：快速確認已載入的 STDF 資料規模、階層分布與測試時間，方便後續選擇要分析的 Lot。

---

## 2. Load STDF（載入 STDF）

**功能**：上傳 STDF 檔案並寫入資料庫。

**可做什麼**：
- 選擇本機 `.stdf` / `.std` 檔案上傳。
- 可選填 **Company / Product / Stage**（不填則用預設或 STDF 內值）。
- 點擊 **Load into DB** 執行載入。

**目的**：不需用指令列即可新增測試資料，方便持續累積多 Lot 資料。

---

## 3. Lot-to-Lot（Lot 間比較）

**功能**：多個 Lot 之間的 Die 數量、不良率、測試時間與單一參數測試的分布比較（僅顯示符合側邊欄篩選與時間區間的 Lot）。

**可做什麼**：
- **Select lots**：勾選要比對的 Lot（可多選；選單僅列出符合篩選的 Lot）。
- 查看每個 Lot 的 **Total dies**、**Part type**、**Total test time (ms)**（該 Lot 所有 Die 的 test_t 總和）、**Lot start** 與長條圖。
- **p-Chart**：以每個 Lot 為一組，畫不良率 p-Chart（UCL/LCL = p̄ ± 3σ），觀察 Lot 間不良率是否受控。
- **Select parametric test to compare**：從下拉選單選擇一個 **PTR 測試項**，系統會：
  - 畫出該測試項在「所選各 Lot」的 **盒鬚圖**（分布比較）。
  - 顯示 **依 Lot 的統計表**（N, Mean, Std, Min, Max）。
  - 顯示 **整體統計**（所有選取 Lot 合併）。

**目的**：比較不同 Lot 的產出量、不良率與特定參數（如電壓、電流）分布，找出 Lot 間差異或異常。

**名詞說明**：
- **Select parametric test to compare**：選擇一個「參數量測測試」（PTR），用它的量測值在各 Lot 的分布做比較；選定後會顯示盒鬚圖與統計。

---

## 4. Wafer-to-Wafer（Wafer 間比較）

**功能**：同一 Lot 內多片 Wafer 的產出、不良率、測試時間、Bin 分布與 TestItem 差異比較（Lot 選單僅列出符合側邊欄篩選與時間區間的 Lot）。

**可做什麼**：
- 選定一個 **Lot**，查看該 Lot 內每片 Wafer 的 **Parts / Good / Yield %**、**Total test time (ms)**（該 Wafer 所有 Die 的 test_t 總和）、**Wafer start** 與長條圖。
- **p-Chart**：以每片 Wafer 為一組，畫不良率 p-Chart，觀察 Wafer 間不良率是否受控。
- **Statistics (per wafer)**：每片 Wafer 的 N、Fail、p、Yield% 表格。
- **Multi-Wafer comparison (left vs right)**：
  - **Select 2 wafers to compare**：選兩片 Wafer（左 = 第一個選項，右 = 第二個選項）。
  - **Differing die count (bin)**：兩片在「同一 (x,y) 位置」Bin 不同的 Die 數量。
  - **左右並排 Wafer map**：兩張圖分別為左 / 右 Wafer，依 **Bin 著色**，差異位置用紅 X 標出。
  - **Positions where bin differs**：僅顯示「Bin 不同」的 (x,y) 位置（紅點圖）。
- **TestItem comparison (selected wafers)**：
  - **表格**：列出所選 Wafer 上共同出現的 TestItem，並標示 **Same / Different**（依各 Wafer 的 pass/fail 率與 PTR 均值是否一致）。
  - **Per-wafer** 欄位：每片 Wafer 的 fail rate (p) 與 PTR 均值 (μ)。
  - **Show p-Chart for test**：從下拉選單選一個測試項，即可顯示該測試在「所選各 Wafer」上的 **p-Chart**（不良率隨 Wafer 變化）。
- **Choose a parametric test to see which die positions have different values**：選擇一個 PTR 測試後，會顯示「同一 (x,y) 位置在左、右 Wafer 上量測值不同」的 Die 位置散點圖。

**目的**：比對同一 Lot 內不同 Wafer 的良率、Bin 與測試結果，找出 Wafer 間或空間上的差異。

**名詞說明**：
- **Positions where test values differ**：同一 (x,y) 座標在「左片 Wafer」與「右片 Wafer」上，該 PTR 測試的**量測值不同**的 Die 位置；圖上每一點代表一個有此差異的 Die。
- **Show p-Chart for test**：針對所選測試項，以「每片選中的 Wafer」為子組，畫不良率 p-Chart，可點選不同測試項切換圖表。

---

## 5. Die-to-Die（單片 Wafer 內 Die 分析）

**功能**：針對「單一 Wafer」做 Wafer map、Bin 分布、不良率、測試時間與參數空間分布（Wafer 選單僅列出屬於符合側邊欄篩選與時間區間之 Lot 的 Wafer）。

**可做什麼**：
- 選定一片 **Wafer**（顯示所屬 Lot）。
- **Wafer map (bin)**：以 **Bin 著色** 的 Wafer map，可選是否顯示 Bin 標籤（Die 數少時）。
- **p-Chart**：該片 Wafer 的整體不良率（單一子組）。
- **Statistics (this wafer)**：Bin 數量表、Total dies、Failing dies、Yield %、**Total test time (ms)**（該 Wafer 所有 Die 的 test_t 總和）、**Mean test time per die (ms)**。
- **Select parametric test to color wafer map by measured value**：從下拉選單選一個 **PTR 測試項**，Wafer map 改為依該測試的**量測值**著色，並顯示該測試在此 Wafer 上的統計（N, Mean, Std, Min, Max）。

**目的**：觀察單片 Wafer 上 Bin 或參數的空間分布，找出邊緣、中心或特定區域的異常。

**名詞說明**：
- **Select parametric test to color wafer map by measured value**：選擇一個參數量測測試（PTR），圖上每個 Die 的顏色代表該測試的**量測值**（例如電壓、電流），用來觀察參數在 Wafer 上的空間分布。

---

## 6. Fail Pareto（失敗柏拉圖）

**功能**：依「失敗的測試項」或「Bin」統計失敗次數，找出主要失敗原因。

**可做什麼**：
- 選擇 **Level**：**Die** 或 **Wafer**。
- 選定一個 **Lot**。
- **Die-level**：
  - 依「失敗的測試」（test_txt / Test#）統計失敗 Die 數，顯示表格與長條圖（top 20）。
  - 依 **Bin** 統計失敗 Die 數，顯示 Bin Pareto（top 15）。
- **Wafer-level**：
  - 在該 Lot 內所有 Wafer 上，依「失敗的測試」與「Bin」彙總，顯示 Wafer 層級的 Pareto。

**目的**：快速找出哪幾個測試或哪幾個 Bin 主導失敗，便於優先改善。

---

## 7. TestSuite → TestItem（測試組與測試項對應）

**功能**：檢視 TestSuite 與其下 TestDefinition / TestItem 的對應關係。

**可做什麼**：
- 從下拉選單選一個 **TestSuite**（會顯示所屬 Test program）。
- 查看該 Suite 的 **TestDefinition** 表格：Test #、Type、Name、Exec cnt、Fail cnt、Alarm cnt。
- 查看該 Suite 底下的 **TestItem** 樣本（最多 50 筆）：Die id、Test #、Type、Result、Pass/Fail。

**目的**：了解測試程式結構，對照 STDF 的 TSR / 測試編號與實際結果。

---

## 8. Bin Summary（Bin 摘要）

**功能**：依 Lot / Wafer 統計 Hard bin 數量與比例。

**可做什麼**：
- 選定一個 **Lot**。
- **Per wafer**：每片 Wafer 各 Bin 的數量（表格 + 長條圖）。
- **Lot total**：該 Lot 整體 Bin 數量與 **Pie chart**。

**目的**：掌握各 Wafer 與整 Lot 的 Bin 分布，便於良率與分類分析。

---

## 9. Equipment（設備資訊）

**功能**：檢視 Lot 的 Tester / 廠區與 Site 設備、測試時間。

**可做什麼**：
- **Select lots**：選多個 Lot。
- 查看 **Tester / Node / Facility / Floor / Exec** 表格。
- 查看 **Site equipment**：Probe card、Load board、Handler 等。
- **Test time comparison**：各 Lot 的 Mean (ms)、Max (ms) 與 Die 數。

**目的**：比對不同 Lot 使用的機台、站點與測試時間，支援設備與產能分析。

---

## 10. Custom SQL（自訂 SQL）

**功能**：對資料庫執行唯讀 SQL 查詢並以表格呈現。

**可做什麼**：
- 在文字框輸入 **SQL**（例如 `SELECT * FROM lot LIMIT 10`）。
- 點擊 **Run query** 顯示結果表格。

**目的**：進階使用者可直接查表（lot、wafer、die、test_item、bin 等），做自訂分析。

---

## 名詞對照（UI 常見用語）

| UI 用語 | 說明 |
|--------|------|
| **Filters (all pages)** | 側邊欄的 Company / Product / Stage / Test Program 與時間區間篩選；套用於 Dashboard、Lot-to-Lot、Wafer-to-Wafer、Die-to-Die、Fail Pareto、Bin Summary、Equipment。 |
| **Time range (lot start)** | 依 **Lot 開始時間** 篩選；勾選「Filter by time」後設定 Start date / End date，只顯示該區間內開始的 Lot。 |
| **Total test time (ms)** | 該 Lot / Wafer 內所有 Die 的 **test_t**（STDF 每顆 Die 測試時間，ms）加總。 |
| **Select test to compare across lots** (Lot-to-Lot) | 選擇一個「參數量測測試」(PTR)，用它的量測值在各 Lot 的分布畫盒鬚圖並顯示統計。 |
| **Positions where test values differ** (Wafer-to-Wafer) | 左、右兩片 Wafer 上，同一 (x,y) 位置該 PTR 測試**量測值不同**的 Die 位置圖。 |
| **Select test (wafer map by value)** (Die-to-Die) | 選擇一個 PTR 測試，Wafer map 依該測試的**量測值**著色，觀察空間分布。 |
| **Same / Different** (TestItem comparison) | 所選多片 Wafer 上，該 TestItem 的 pass/fail 率與（PTR）均值是否一致：Same = 一致，Different = 有差異。 |
| **p-Chart** | 以子組（Lot 或 Wafer）為橫軸、不良率為縱軸的管制圖；UCL/LCL = p̄ ± 3σ。 |

---

## 快速流程建議

1. **載入資料**：Dashboard 或 Load STDF 確認/上傳 STDF。
2. **Lot 層級**：Lot-to-Lot 選 Lot、看 p-Chart 與參數分布。
3. **Wafer 層級**：Wafer-to-Wafer 選 Lot 與兩片 Wafer，看 Bin 差異、TestItem 表格與 p-Chart。
4. **Die 層級**：Die-to-Die 選 Wafer，看 Bin map 與參數著色 map。
5. **失敗分析**：Fail Pareto 選 Lot 與 Die/Wafer level，看測試與 Bin Pareto。
6. **結構與設備**：TestSuite→TestItem、Bin Summary、Equipment 做結構與設備檢視。
