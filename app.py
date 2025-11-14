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

# 載入映射檔
@st.cache_data
def load_file_mapping():
    """載入檔案映射檔"""
    from pathlib import Path
    mapping_file = Path(__file__).parent / 'file_mapping.json'

    if not mapping_file.exists():
        return {}

    try:
        import json
        with open(mapping_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"⚠️ 載入映射檔失敗: {e}")
        return {}

@st.cache_data
def load_gemini_id_mapping():
    """載入 Gemini ID 反向映射檔（Gemini file_id → file_id）"""
    from pathlib import Path
    mapping_file = Path(__file__).parent / 'gemini_id_mapping.json'

    if not mapping_file.exists():
        return {}

    try:
        import json
        with open(mapping_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"⚠️ 載入 Gemini ID 映射檔失敗: {e}")
        return {}

def extract_file_id(filename: str, gemini_id_mapping: dict = None) -> str:
    """從檔名中提取 file_id

    Args:
        filename: Gemini 返回的檔名（可能是內部 ID 如 "4ax547mbfiot"）
        gemini_id_mapping: Gemini ID 反向映射 (files/xxx → fsc_pen_xxx)

    Returns:
        file_id（用於查找 file_mapping.json）
    """
    import re

    # 如果有 gemini_id_mapping，先嘗試反向查找
    if gemini_id_mapping:
        # 嘗試完整 ID（files/xxx）
        full_id = f"files/{filename.replace('files/', '')}"
        if full_id in gemini_id_mapping:
            return gemini_id_mapping[full_id]

    # 回退：從檔名提取（適用於舊資料或直接是檔名的情況）
    # 移除 files/ 前綴和 .md 後綴
    filename = filename.replace('files/', '').replace('.md', '')

    # 提取 fsc_pen_YYYYMMDD_NNNN 格式
    match = re.match(r'(fsc_pen_\d{8}_\d{4})', filename)
    if match:
        return match.group(1)

    return filename

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

    store_id = os.getenv('GEMINI_STORE_ID', 'fileSearchStores/fscpenalties-tu709bvr1qti')

    return client, store_id

# 查詢函數
def query_penalties(client: genai.Client, query: str, store_id: str, model: str = 'gemini-2.5-flash', filters: dict = None) -> dict:
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
        # 建立系統指令（針對裁罰案件的時效性優化）
        system_instruction = """你是金融監督管理委員會的裁罰案件查詢助手。

【重要】時效性與獨立性規則：

1. **裁罰案件特性**：
   - 每個裁罰案件都是獨立的歷史記錄
   - 不同日期的案件不互相取代
   - 可引用多個案件作為參考
   - 按日期或相關性排序

2. **查詢優先順序**（當有多筆相關案件時）：
   - 優先列出**最近**的案件（日期越新越優先）
   - 同時參考相似違規類型的歷史案件
   - 如果使用者明確要求特定時間範圍，嚴格遵守

3. **回答格式要求**：
   - 提供具體的案件資訊（日期、單位、被處罰對象、違規事項、裁罰金額、法律依據）
   - 始終註明**發文日期**和**發文字號**
   - **重要：不要在回答中列出「資料來源」或檔名**（系統會自動顯示參考文件）
   - 使用繁體中文，保持專業但易懂的語氣
   - 如果找不到相關資料，請明確告知

4. **多案件處理**：
   - 如果有多筆相關案件，列出前 3-5 筆最相關的
   - 按時間順序（最新在前）或相關性排序
   - 每個案件獨立說明，不要混淆

回答格式範例：

## 查詢結果

找到 X 筆相關裁罰案件：

### 1. [案件標題]（最新）
- **日期**：YYYY-MM-DD
- **發文字號**：金管XX字第XXXXXXXXX號
- **來源單位**：XXX局
- **被處罰對象**：XXX公司/銀行/保險
- **違規事項**：[簡要說明]
- **裁罰金額**：新臺幣 XXX 萬元
- **法律依據**：[相關法規條文]

（注意：不要在每個案件後面加上「資料來源」或檔名，系統會自動在最下方顯示參考文件）
"""

        # 建立完整查詢（篩選條件）
        full_query = query

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

        # 使用 File Search Store 進行查詢（使用正確的型別物件）
        response = client.models.generate_content(
            model=model,  # 使用用戶選擇的模型
            contents=full_query,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[store_id]
                        )
                    )
                ],
                temperature=0.1,
                max_output_tokens=2048,
                system_instruction=system_instruction
            )
        )

        # 提取來源文件
        sources = []
        seen_files = {}  # 用於去重

        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            candidate = response.candidates[0]

            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata

                # 優先從 grounding_supports 提取（包含引用資訊）
                if hasattr(metadata, 'grounding_supports') and metadata.grounding_supports:
                    for support in metadata.grounding_supports:
                        if hasattr(support, 'grounding_chunk_indices'):
                            for chunk_idx in support.grounding_chunk_indices:
                                if chunk_idx < len(metadata.grounding_chunks):
                                    chunk = metadata.grounding_chunks[chunk_idx]

                                    if hasattr(chunk, 'retrieved_context'):
                                        context = chunk.retrieved_context

                                        # 提取文件 ID/名稱
                                        filename = "未知文件"
                                        if hasattr(context, 'title') and context.title:
                                            filename = context.title
                                        elif hasattr(context, 'uri') and context.uri:
                                            filename = context.uri.split('/')[-1]

                                        # 提取內容片段
                                        snippet = ""
                                        if hasattr(context, 'text') and context.text:
                                            snippet = context.text

                                        # 使用 snippet 的部分內容作為唯一標識避免重複
                                        snippet_id = snippet[:100] if snippet else str(len(sources))

                                        if snippet_id not in seen_files:
                                            sources.append({
                                                'filename': filename,
                                                'snippet': snippet
                                            })
                                            seen_files[snippet_id] = True

                # 如果沒有 grounding_supports，回退到 grounding_chunks
                if not sources and hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                    for chunk in metadata.grounding_chunks:
                        if hasattr(chunk, 'retrieved_context'):
                            context = chunk.retrieved_context

                            # 提取文件 ID/名稱
                            filename = "未知文件"
                            if hasattr(context, 'title') and context.title:
                                filename = context.title
                            elif hasattr(context, 'uri') and context.uri:
                                filename = context.uri.split('/')[-1]

                            # 提取內容片段
                            snippet = ""
                            if hasattr(context, 'text') and context.text:
                                snippet = context.text

                            # 使用 snippet 的部分內容作為唯一標識避免重複
                            snippet_id = snippet[:100] if snippet else str(len(sources))

                            if snippet_id not in seen_files:
                                sources.append({
                                    'filename': filename,
                                    'snippet': snippet
                                })
                                seen_files[snippet_id] = True

        return {
            'success': True,
            'text': response.text,
            'sources': sources
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
    st.info("💡 本系統為展示用，如遇畫面無反應，請重新整理頁面")

    # 初始化 Gemini
    client, store_id = init_gemini()

    # 側邊欄：篩選條件
    with st.sidebar:
        # 模型選擇
        st.header("🤖 AI 模型")
        model = st.selectbox(
            "選擇模型",
            options=["gemini-2.5-flash", "gemini-2.5-pro"],
            index=0,
            help="Flash 速度快且成本低；Pro 更準確但較慢"
        )

        st.divider()
        st.header("🔍 篩選條件")

        # 日期範圍
        st.subheader("日期範圍（可選）")
        enable_date_filter = st.checkbox("啟用日期篩選", value=False)

        if enable_date_filter:
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
        else:
            start_date = None
            end_date = None

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

    # 初始化 session state（使用不同的變數名）
    if 'current_query' not in st.session_state:
        st.session_state.current_query = ""

    # 查詢輸入
    query = st.text_area(
        "請輸入查詢內容：",
        value=st.session_state.current_query,
        placeholder="例如：2024年有哪些銀行因為洗錢防制被裁罰？",
        height=100
    )

    # 快速查詢按鈕
    st.markdown("#### 🚀 快速查詢")

    quick_queries = [
        "違反金控法利害關係人規定會受到什麼處罰？",
        "請問在證券因為專業投資人資格審核的裁罰有哪些？",
        "辦理共同行銷被裁罰的案例有哪些？",
        "金管會對創投公司的裁罰有哪些？",
        "證券商遭主管機關裁罰「警告」處分，有哪些業務會受限制？",
        "內線交易有罪判決所認定重大訊息成立的時點"
    ]

    cols = st.columns(2)
    for idx, quick_query in enumerate(quick_queries):
        col_idx = idx % 2
        with cols[col_idx]:
            if st.button(f"📌 {quick_query}", key=f"quick_{idx}", use_container_width=True):
                st.session_state.current_query = quick_query
                st.rerun()

    st.markdown("")  # 空行分隔

    # 查詢按鈕
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        search_button = st.button("🔍 查詢", type="primary", use_container_width=True)
    with col2:
        clear_button = st.button("🗑️ 清除", use_container_width=True)

    if clear_button:
        st.session_state.current_query = ""
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
            result = query_penalties(client, query, store_id, model, filters)

            # 顯示結果
            if result['success']:
                st.success("✅ 查詢完成")

                # 區塊1：顯示回應（已包含結構化資料，Markdown 已渲染）
                st.markdown("---")
                st.markdown(result['text'])

                # 新增：從參考文件中提取並顯示原始連結
                if result.get('sources') and len(result['sources']) > 0:
                    mapping = load_file_mapping()
                    gemini_id_mapping = load_gemini_id_mapping()

                    # 收集所有原始連結（去重）
                    original_urls = []
                    seen_urls = set()

                    for source in result['sources']:
                        filename = source.get('filename', '')
                        file_id = extract_file_id(filename, gemini_id_mapping)
                        file_info = mapping.get(file_id, {})
                        url = file_info.get('original_url', '')

                        if url and url not in seen_urls:
                            original_urls.append({
                                'url': url,
                                'display_name': file_info.get('display_name', file_id)
                            })
                            seen_urls.add(url)

                    # 顯示原始連結
                    if original_urls:
                        st.markdown("---")
                        st.markdown("**🔗 相關裁罰案件原始公告**")
                        for item in original_urls:
                            st.markdown(f"- [{item['display_name']}]({item['url']})")

                # 區塊2：參考文件
                if result.get('sources') and len(result['sources']) > 0:
                    st.markdown("---")
                    st.subheader(f"📚 參考文件 ({len(result['sources'])} 筆)")
                    st.caption("點擊展開可查看完整原始內容")

                    # 載入映射檔
                    mapping = load_file_mapping()
                    gemini_id_mapping = load_gemini_id_mapping()

                    # 除錯資訊
                    with st.expander("🔍 除錯資訊", expanded=False):
                        st.write(f"映射檔載入狀態: {'✅ 成功' if mapping else '❌ 失敗'}")
                        st.write(f"映射檔筆數: {len(mapping)}")
                        st.write(f"Gemini ID 映射檔載入狀態: {'✅ 成功' if gemini_id_mapping else '❌ 失敗'}")
                        st.write(f"Gemini ID 映射檔筆數: {len(gemini_id_mapping)}")
                        if result['sources']:
                            st.write("第一個來源完整結構:")
                            st.json(result['sources'][0])
                            # 顯示映射過程
                            first_filename = result['sources'][0].get('filename', '')
                            first_file_id = extract_file_id(first_filename, gemini_id_mapping)
                            st.write(f"檔名映射: {first_filename} → {first_file_id}")
                            # 顯示法條資訊
                            first_file_info = mapping.get(first_file_id, {})
                            first_laws = first_file_info.get('applicable_laws', [])
                            first_law_links = first_file_info.get('law_links', {})
                            st.write(f"適用法條數: {len(first_laws)}")
                            st.write(f"法條連結數: {len(first_law_links)}")

                    for i, source in enumerate(result['sources'], 1):
                        # 從映射檔取得資訊
                        filename = source.get('filename', '')
                        file_id = extract_file_id(filename, gemini_id_mapping)
                        file_info = mapping.get(file_id, {})

                        # 顯示名稱：日期_來源_機構
                        display_name = file_info.get('display_name', f"來源 {i}")
                        original_url = file_info.get('original_url', '')
                        original_content = file_info.get('original_content', {}).get('text', source.get('snippet', ''))

                        # 使用 expander 顯示
                        with st.expander(f"📄 {display_name}", expanded=False):
                            # 原始網頁連結
                            if original_url:
                                st.markdown(f"🔗 [查看原始公告]({original_url})")
                                st.markdown("")  # 空行

                            # 適用法條與連結
                            applicable_laws = file_info.get('applicable_laws', [])
                            law_links = file_info.get('law_links', {})

                            if applicable_laws:
                                st.markdown("**📜 適用法條**：")
                                for law in applicable_laws:
                                    # 如果有法規資料庫連結，顯示為可點擊連結
                                    if law in law_links:
                                        st.markdown(f"- [{law}]({law_links[law]}) 🔗")
                                    else:
                                        st.markdown(f"- {law}")
                                st.markdown("")  # 空行

                            # 顯示原始內容
                            if original_content:
                                st.markdown("**原始內容**：")
                                # 限制顯示長度避免過長
                                if len(original_content) > 2000:
                                    st.text(original_content[:2000] + "\n\n...(內容過長，請點擊上方連結查看完整內容)")
                                else:
                                    st.text(original_content)
                            else:
                                st.caption("（無可用內容）")
            else:
                st.error(f"❌ 查詢失敗：{result['error']}")

    elif search_button and not query:
        st.warning("⚠️ 請輸入查詢內容")

    # 頁尾
    st.divider()
    st.caption("資料來源：金融監督管理委員會")
    st.caption("⚠️ 本系統僅供參考，實際裁罰資訊請以金管會官網公告為準")

if __name__ == "__main__":
    main()
