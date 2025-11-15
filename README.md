# FSC 裁罰案件查詢系統

使用 Google Gemini File Search Store 建立的金管會裁罰案件查詢前台。

## 專案特色

- 🔍 **智慧查詢**：使用 Gemini AI 進行自然語言查詢
- 📊 **完整資料**：涵蓋 2011-2025 年共 495 筆裁罰案件
- 🎯 **精準篩選**：支援日期、單位、金額等多維度篩選
- ⚡ **即時回應**：基於 Gemini File Search Store 的高效查詢
- 🌐 **雲端部署**：可輕鬆部署到 Streamlit Cloud
- 🛡️ **防護機制**：自動重試機制防止 AI 編造案例 (2025-11-15 新增)

## 資料統計

- **總案件數**：495 筆
- **日期範圍**：2011-11-09 至 2025-09-25
- **來源分布**：
  - 銀行局：225 筆 (45.5%)
  - 保險局：222 筆 (44.8%)
  - 證券期貨局：47 筆 (9.5%)

## 快速開始

### 1. 環境設定

```bash
# 安裝依賴
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env，填入你的 GEMINI_API_KEY
```

### 2. 本地執行

```bash
streamlit run app.py
```

瀏覽器會自動開啟 http://localhost:8501

### 3. 部署到 Streamlit Cloud

1. 將專案推送到 GitHub
2. 前往 [Streamlit Cloud](https://streamlit.io/cloud)
3. 連結你的 GitHub repository
4. 在 Streamlit Cloud 設定環境變數：
   - `GEMINI_API_KEY`
   - `GEMINI_STORE_ID`（可選，預設已設定）
5. 點擊 Deploy

## 查詢範例

### 一般查詢
- 最近有哪些銀行被裁罰？
- 2024年保險業的裁罰案件有哪些？
- 查詢洗錢防制相關的裁罰案件

### 特定主題
- 內部控制缺失的裁罰案例
- 客戶資料外洩相關裁罰
- 違反資訊安全的案件

### 金額查詢
- 裁罰金額超過 1000 萬的案件
- 金額最高的 5 個裁罰案例

### 趨勢分析
- 2023 vs 2024 年銀行局裁罰趨勢比較
- 最常見的違規類型是什麼？

## 技術架構

- **前端框架**：Streamlit
- **AI 模型**：Google Gemini 2.0 Flash
- **RAG 技術**：Gemini File Search Store
- **資料格式**：Markdown (495 個獨立檔案)
- **部署平台**：Streamlit Cloud

## 專案結構

```
FSC-Penalties-Deploy/
├── app.py                 # 主要 Streamlit 應用
├── requirements.txt       # Python 依賴
├── .env.example          # 環境變數範本
├── .gitignore            # Git 忽略清單
└── README.md             # 本文件
```

## 環境變數

| 變數名稱 | 說明 | 必填 |
|---------|------|------|
| `GEMINI_API_KEY` | Google Gemini API 金鑰 | ✅ |
| `GEMINI_STORE_ID` | File Search Store ID | ❌ (有預設值) |

### 取得 API Key

前往 [Google AI Studio](https://aistudio.google.com/app/apikey) 取得免費的 Gemini API Key。

## 功能說明

### 篩選條件

- **日期範圍**：指定開始和結束日期
- **來源單位**：銀行局、保險局、證券期貨局、檢查局
- **裁罰金額**：設定最低金額門檻

### 查詢結果格式

系統會提供：
1. 相關案件數量
2. 每個案件的詳細資訊：
   - 日期
   - 來源單位
   - 被處罰對象
   - 違規事項
   - 裁罰金額
   - 法律依據（**自動加上法條連結**）
3. 資料來源檔案名稱

#### 法條連結功能 (2025-11-15 新增，2025-11-16 修正)

法律依據中的法條會自動加上連結，點擊後跳轉到全國法規資料庫：
- 範例：「[保險法第149條](...)第1項、[第171條之1](...)第4項及第5項」
- 支援完整引用（保險法第149條）和簡寫引用（第171條之1）
- 連結到條文層級，方便查閱完整法條內容

**最新修正 (2025-11-16)**：
- ✅ 修正「證券投資信託及顧問法」pcode（G0400129 → G0400121）
- ✅ 移除快取機制，確保始終載入最新的法條連結
- ✅ 所有 75 個證券投資信託及顧問法相關連結已全部正確

#### Hallucination 防護機制 (2025-11-15 新增)

系統內建自動重試機制，防止 AI 編造不存在的案例：
- **問題**：AI 有時會編造看似真實但實際不存在的裁罰案例
- **解決方案**：
  1. 固定使用 Gemini 2.5 Flash 模型（更穩定）
  2. 檢測到 AI 未使用資料庫時，自動重試一次
  3. 兩次都失敗時，顯示友善提示而非編造的內容
- **效果**：確保所有顯示的案例都來自真實的裁罰文件

## 注意事項

- ⚠️ 本系統僅供參考，實際裁罰資訊請以 [金管會官網](https://www.fsc.gov.tw) 公告為準
- 🔒 請妥善保管你的 API Key，不要上傳到公開的 GitHub repository
- 📊 Gemini API 有免費額度限制，請參考 [定價說明](https://ai.google.dev/pricing)

## 相關專案

- **FSC** - 主要開發專案（爬蟲、資料處理、上傳）
- **FSC-Penalties-Deploy** - 本專案（查詢前台）

## 授權

MIT License

## 聯絡方式

如有問題或建議，歡迎開 Issue 討論。
