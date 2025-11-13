"""
FSC 裁罰案件查詢系統
使用 Google Gemini File Search Store 進行 RAG 查詢
"""

import os
import streamlit as st
from datetime import datetime, date
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 載入環境變數
load_dotenv()

# 設定頁面
st.set_page_config(
    page_title="金管會裁罰案件查詢系統",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化 Gemini
@st.cache_resource
def init_gemini():
    """初始化 Gemini API"""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        st.error("❌ 找不到 GEMINI_API_KEY，請設定環境變數")
        st.stop()

    # 建立 GenAI Client
    client = genai.Client(api_key=api_key)

    store_id = os.getenv('GEMINI_STORE_ID', 'fileSearchStores/fscpenalties-ma1326u8ck77')

    return client, store_id

# 查詢函數
def query_penalties(client: genai.Client, query: str, store_id: str, filters: dict = None) -> dict:
    """
    使用 Gemini File Search Store 查詢裁罰案件

    Args:
        query: 查詢文字
        store_id: Gemini Store ID
        filters: 篩選條件（日期範圍、來源單位等）

    Returns:
        查詢結果字典
    """
    try:
        # 建立系統指令（放在查詢前面）
        system_instruction = """你是金管會裁罰案件查詢助理。

請根據 File Search Store 中的裁罰案件資料，回答使用者的問題。

回答時請：
1. 提供具體的案件資訊（日期、單位、被處罰對象、違規事項、裁罰金額、法律依據）
2. 如果有多筆相關案件，請列出重點摘要
3. 引用具體的文件來源（檔案名稱）
4. 使用繁體中文，保持專業但易懂的語氣
5. 如果找不到相關資料，請明確告知

回答格式範例：

## 查詢結果

找到 X 筆相關裁罰案件：

### 1. [案件標題]
- **日期**：YYYY-MM-DD
- **來源單位**：XXX局
- **被處罰對象**：XXX公司/銀行/保險
- **違規事項**：[簡要說明]
- **裁罰金額**：XXX 萬元
- **法律依據**：[相關法規條文]

---
**資料來源**：fsc_pen_YYYYMMDD_XXXX_XX.md
"""

        # 建立完整查詢（包含系統指令和篩選條件）
        full_query = system_instruction + "\n\n使用者問題：" + query

        if filters:
            filter_parts = []

            if filters.get('start_date') and filters.get('end_date'):
                filter_parts.append(
                    f"日期範圍：{filters['start_date']} 到 {filters['end_date']}"
                )

            if filters.get('source_units'):
                units_str = "、".join(filters['source_units'])
                filter_parts.append(f"來源單位：{units_str}")

            if filters.get('min_penalty'):
                filter_parts.append(f"裁罰金額至少：{filters['min_penalty']:,} 元")

            if filter_parts:
                full_query += "\n\n篩選條件：\n" + "\n".join(f"- {p}" for p in filter_parts)

        # 使用 File Search Store 進行查詢
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=full_query,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=2048,
                tools=[
                    {'file_search': {'file_search_store_names': [store_id]}}
                ]
            )
        )

        return {
            'success': True,
            'text': response.text,
            'candidates': response.candidates if hasattr(response, 'candidates') else None
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

# 主應用
def main():
    """主應用程式"""

    # 標題
    st.title("⚖️ 金管會裁罰案件查詢系統")
    st.markdown("查詢 2011-2025 年間的金融機構裁罰案件（共 495 筆）")

    # 初始化 Gemini
    client, store_id = init_gemini()

    # 側邊欄：篩選條件
    with st.sidebar:
        st.header("🔍 篩選條件")

        # 日期範圍
        st.subheader("日期範圍")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "開始日期",
                value=date(2020, 1, 1),
                min_value=date(2011, 1, 1),
                max_value=date.today()
            )
        with col2:
            end_date = st.date_input(
                "結束日期",
                value=date.today(),
                min_value=date(2011, 1, 1),
                max_value=date.today()
            )

        # 來源單位
        st.subheader("來源單位")
        source_units = st.multiselect(
            "選擇單位",
            options=["銀行局", "保險局", "證券期貨局", "檢查局"],
            default=[]
        )

        # 裁罰金額
        st.subheader("裁罰金額")
        min_penalty = st.number_input(
            "最低金額（元）",
            min_value=0,
            value=0,
            step=100000,
            format="%d"
        )

        # 清除篩選
        if st.button("清除所有篩選", use_container_width=True):
            st.rerun()

        # 顯示資料庫資訊
        st.divider()
        st.caption("📊 資料庫資訊")
        st.caption(f"總案件數：495 筆")
        st.caption(f"日期範圍：2011-11-09 至 2025-09-25")
        st.caption(f"銀行局：225 筆 (45.5%)")
        st.caption(f"保險局：222 筆 (44.8%)")
        st.caption(f"證券期貨局：47 筆 (9.5%)")

    # 主要查詢區域
    st.header("💬 查詢")

    # 範例查詢
    with st.expander("💡 查詢範例"):
        st.markdown("""
        **一般查詢**：
        - 最近有哪些銀行被裁罰？
        - 2024年保險業的裁罰案件有哪些？
        - 查詢洗錢防制相關的裁罰案件

        **特定主題**：
        - 內部控制缺失的裁罰案例
        - 客戶資料外洩相關裁罰
        - 違反資訊安全的案件

        **金額查詢**：
        - 裁罰金額超過 1000 萬的案件
        - 金額最高的 5 個裁罰案例

        **趨勢分析**：
        - 2023 vs 2024 年銀行局裁罰趨勢比較
        - 最常見的違規類型是什麼？
        """)

    # 查詢輸入
    query = st.text_area(
        "請輸入查詢內容：",
        placeholder="例如：2024年有哪些銀行因為洗錢防制被裁罰？",
        height=100
    )

    # 查詢按鈕
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        search_button = st.button("🔍 查詢", type="primary", use_container_width=True)
    with col2:
        clear_button = st.button("🗑️ 清除", use_container_width=True)

    if clear_button:
        st.rerun()

    # 執行查詢
    if search_button and query:
        with st.spinner("🔍 查詢中..."):
            # 準備篩選條件
            filters = {}

            if start_date and end_date:
                filters['start_date'] = start_date.strftime('%Y-%m-%d')
                filters['end_date'] = end_date.strftime('%Y-%m-%d')

            if source_units:
                filters['source_units'] = source_units

            if min_penalty > 0:
                filters['min_penalty'] = min_penalty

            # 執行查詢
            result = query_penalties(client, query, store_id, filters)

            # 顯示結果
            if result['success']:
                st.success("✅ 查詢完成")

                # 顯示回應
                st.markdown("---")
                st.markdown(result['text'])

                # 顯示元資料（如果有）
                if result.get('candidates'):
                    with st.expander("🔍 查詢詳細資訊"):
                        st.json({
                            'model': 'gemini-2.0-flash',
                            'store_id': store_id,
                            'filters': filters if filters else None
                        })
            else:
                st.error(f"❌ 查詢失敗：{result['error']}")

    elif search_button and not query:
        st.warning("⚠️ 請輸入查詢內容")

    # 頁尾
    st.divider()
    st.caption("資料來源：金融監督管理委員會 | 技術支援：Google Gemini File Search")
    st.caption("⚠️ 本系統僅供參考，實際裁罰資訊請以金管會官網公告為準")

if __name__ == "__main__":
    main()
