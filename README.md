# FSC 裁罰案件查詢系統

使用 Google Gemini File Search Store 建立的金管會裁罰案件查詢前台。

## 專案特色

- 🔍 **智慧查詢**：使用 Gemini AI 進行自然語言查詢
- 📊 **完整資料**：涵蓋 2012-2025 年共 490 筆裁罰案件
- ⚡ **即時回應**：基於 Gemini File Search Store 的高效查詢
- 🌐 **雲端部署**：可輕鬆部署到 Streamlit Cloud
- 🛡️ **防護機制**：自動重試機制防止 AI 編造案例
- 🔗 **智能法條連結**：LLM 自動生成法條超連結（2025-11-19 新增）
- 📄 **透明檢索**：顯示 AI 實際檢索的文本內容（2025-11-19 新增）

## 資料統計

- **總案件數**：490 筆
- **日期範圍**：2012-01-12 至 2025-09-25
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

### 查詢介面

- **簡潔設計**：專注於核心查詢功能，無複雜的篩選選項
- **快速查詢**：提供常見問題的快速查詢按鈕
- **智能搜尋**：使用自然語言描述您的問題即可

### 查詢結果格式

系統會提供：
1. **AI 生成的答案**
   - 基於 Gemini 2.5 Flash 模型
   - 自然語言回答，易於理解
   - **法條自動加上連結**（2025-11-19 新增）

2. **參考來源**（按時間排序）
   - **顯示 AI 實際檢索的文本內容**（2025-11-19 新增）
   - 提供原始公告連結
   - 透明化 RAG 檢索過程

### 核心功能

#### 🔗 LLM 智能法條連結（2025-11-19 重大更新）

**舊方法**：使用複雜的正則表達式後處理（~200 行代碼）
**新方法**：讓 Gemini 在生成答案時自動加入法條連結

**優勢**：
- ✨ **語意理解**：AI 能理解上下文，自動處理簡寫引用
- 🎯 **格式正確**：連接詞自動放在連結外面
- 🛠️ **易維護**：新格式只需調整 Prompt，無需改代碼
- 📉 **代碼簡化**：從 ~200 行 Regex 減少到 ~90 行 Prompt

**範例**：
```
違反[《金融控股公司法》第45條第1項](https://law.moj.gov.tw/...)及[第51條](https://law.moj.gov.tw/...)規定
```

**技術細節**：
- 在 system_instruction 中注入法條連結表格（149 個唯一法條）
- Gemini 根據規則自動生成 Markdown 連結
- 支援完整引用和簡寫引用的自動識別

#### 📄 透明檢索顯示（2025-11-19 新增）

參考來源展開後會顯示：
- **相關內容**：Gemini 實際檢索到的最接近文本片段
- **原始連結**：金管會公告的完整網址

**優勢**：
- 🔍 用戶可以驗證 AI 回答的依據
- 📊 理解為什麼這個來源被引用
- 🛡️ 提高 AI 回答的可信度和透明度

#### 🛡️ Hallucination 防護機制

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
