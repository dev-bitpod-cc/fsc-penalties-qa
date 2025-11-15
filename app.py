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
        file_id（用於查找 file_mapping.json），如果映射失敗則返回 None
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
    filename_clean = filename.replace('files/', '').replace('.md', '')

    # 提取 fsc_pen_YYYYMMDD_NNNN 格式
    match = re.match(r'(fsc_pen_\d{8}_\d{4})', filename_clean)
    if match:
        return match.group(1)

    # 如果無法提取有效的 file_id，返回 None（避免使用無效的 Gemini 內部 ID）
    return None

def add_law_links_to_text(text: str, law_links_dict: dict) -> str:
    """在文字中為法條加入連結

    Args:
        text: 原始文字
        law_links_dict: 法條到連結的映射 {法條名稱: URL}

    Returns:
        加入連結後的文字
    """
    import re

    if not law_links_dict:
        return text

    # 按法條名稱長度排序（長的優先，避免短的先被替換導致長的無法匹配）
    sorted_laws = sorted(law_links_dict.keys(), key=len, reverse=True)

    result = text
    replaced = set()  # 記錄已替換的法條，避免重複替換

    for law in sorted_laws:
        if law in replaced:
            continue

        link = law_links_dict[law]

        # 使用正則表達式找到法條（確保不在 Markdown 連結中）
        # 不匹配已經是連結的部分：[xxx] 或 (http...)
        pattern = r'(?<!\[)(?<!\()' + re.escape(law) + r'(?!\])(?!\))'

        # 替換為 Markdown 連結格式
        replacement = f'[{law}]({link})'

        # 執行替換
        new_result = re.sub(pattern, replacement, result)

        # 如果有替換發生，記錄下來
        if new_result != result:
            replaced.add(law)
            result = new_result

    return result

def insert_case_links_by_order(text: str, case_urls: list) -> str:
    """
    按順序將案件標題轉換為連結（區塊1用）

    Args:
        text: Gemini 回答文字
        case_urls: 案件連結列表（按順序，從 grounding_metadata 提取）

    Returns:
        插入連結後的文字
    """
    import re

    if not case_urls:
        return text

    # 找出所有標題：### 1. [標題內容]
    pattern = r'(###\s*\d+\.\s+)([^\n]+)'
    matches = list(re.finditer(pattern, text))

    if not matches:
        return text

    # 從後往前替換（避免位置偏移）
    result = text
    for i, match in enumerate(reversed(matches)):
        # 反向索引
        idx = len(matches) - 1 - i

        # 檢查是否有對應的 URL
        if idx >= len(case_urls):
            continue

        prefix = match.group(1)      # "### 1. "
        title = match.group(2).strip()  # "三商美邦人壽保險股份..."
        url = case_urls[idx]

        # 檢查是否已經是連結（避免重複替換）
        if title.startswith('[') and '](' in title:
            continue

        # 替換為連結
        new_text = f"{prefix}[{title}]({url})"
        result = result[:match.start()] + new_text + result[match.end():]

    return result

def remove_social_media_noise(text: str) -> str:
    """
    移除原始文字中的社群媒體分享按鈕等雜訊

    Args:
        text: 原始文字

    Returns:
        清理後的文字
    """
    import re

    # 社群媒體相關關鍵字
    noise_patterns = [
        r'facebook',
        r'Facebook',
        r'twitter',
        r'Twitter',
        r'line',
        r'LINE',
        r'分享',
        r'列印',
        r'轉寄',
        r'友善列印',
        r'回上一頁',
        r':::',
        r'回首頁',
        r'網站導覽',
        r'English',
        r'兒童版',
        r'行動版',
        r'RSS',
        r'字級大小',
        r'小 中 大',
    ]

    # 移除包含這些關鍵字的行
    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        line = line.strip()
        # 跳過空行
        if not line:
            continue

        # 檢查是否包含雜訊關鍵字
        is_noise = False
        for pattern in noise_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                is_noise = True
                break

        if not is_noise:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)

def display_grounding_sources_v2(sources: list, file_mapping: dict, gemini_id_mapping: dict, excluded_file_ids: set = None):
    """
    顯示也可以另外參考（區塊3 - 新版）

    只顯示不在查詢結果標題中的額外參考文件

    Args:
        sources: 從 query_penalties 返回的 sources 列表
        file_mapping: file_mapping.json 的內容
        gemini_id_mapping: Gemini ID 映射
        excluded_file_ids: 已在查詢結果標題中的 file_ids（要排除的）
    """
    if not sources:
        return

    if excluded_file_ids is None:
        excluded_file_ids = set()

    # 1. 去重並提取 file_ids（只保留有效且存在於 file_mapping 的檔案）
    unique_file_ids = []
    seen = set()

    for source in sources:
        filename = source.get('filename', '')
        file_id = extract_file_id(filename, gemini_id_mapping)

        # 跳過映射失敗或不存在於 file_mapping 的檔案
        if not file_id or file_id not in file_mapping:
            continue

        if file_id not in seen:
            unique_file_ids.append(file_id)
            seen.add(file_id)

    # 2. 過濾掉已在查詢結果中的文件
    additional_file_ids = [fid for fid in unique_file_ids if fid not in excluded_file_ids]

    # 3. 如果沒有額外的文件，不顯示整個區塊
    if not additional_file_ids:
        return

    # 4. 顯示也可以另外參考
    st.subheader(f"📚 也可以另外參考 ({len(additional_file_ids)} 筆)")

    for file_id in additional_file_ids:
        # 查找 file_mapping
        file_info = file_mapping.get(file_id, {})
        display_name = file_info.get('display_name', file_id)
        detail_url = file_info.get('original_url', '')
        original_content = file_info.get('original_content', {}).get('text', '')

        # 展開式顯示
        with st.expander(f"📄 {display_name}"):
            # 1. 顯示原始案件連結
            if detail_url:
                st.markdown(f"🔗 [查看金管會原始公告]({detail_url})")
                st.markdown("---")

            # 2. 顯示原始案件純文字內容
            st.markdown("**原始案件內容：**")

            if original_content:
                # 移除社群媒體雜訊
                cleaned_content = remove_social_media_noise(original_content)

                # 限制顯示長度，可滾動
                if len(cleaned_content) > 2000:
                    st.text_area(
                        "",
                        value=cleaned_content[:2000] + "\n\n...(內容過長，請點擊上方連結查看完整內容)",
                        height=300,
                        disabled=True,
                        label_visibility="collapsed"
                    )
                else:
                    st.text_area(
                        "",
                        value=cleaned_content,
                        height=300,
                        disabled=True,
                        label_visibility="collapsed"
                    )
            else:
                st.caption("（無可用內容）")

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

5. **概念性問題處理**（重要）：
   - 當使用者提出概念性問題（如「遭裁罰後有哪些業務限制」），可以提供總結式回答
   - **但仍建議列出至少 1-2 個具體案例**作為說明，使用上述格式
   - 例如：先總結業務限制類型，再列出「### 1. [具體案例]」
   - 這樣既能回答概念問題，也能讓使用者參考實際案例
   - 如果選擇只提供總結而不列出案例，系統會在「也可以另外參考」區塊顯示相關案件

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

        # 根據模型類型設定 token 限制
        # Pro 模型通常提供更詳細的回答，需要更多 tokens
        max_tokens = 8192 if 'pro' in model.lower() else 4096

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
                max_output_tokens=max_tokens,
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

        # 顯示名稱到 model ID 的映射
        model_display_to_id = {
            "標準": "gemini-2.5-flash",
            "專業（較慢）": "gemini-2.5-pro"
        }

        model_display = st.selectbox(
            "選擇模型",
            options=list(model_display_to_id.keys()),
            index=0,
            help="標準：速度快；專業：更準確但較慢"
        )

        # 轉換為實際的 model ID
        model = model_display_to_id[model_display]

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

                # 載入映射檔（用於法條連結和原始連結）
                mapping = load_file_mapping()
                gemini_id_mapping = load_gemini_id_mapping()

                # 收集所有參考文件中的法條連結（過濾無效法條）
                all_law_links = {}
                if result.get('sources') and len(result['sources']) > 0:
                    for source in result['sources']:
                        filename = source.get('filename', '')
                        file_id = extract_file_id(filename, gemini_id_mapping)
                        file_info = mapping.get(file_id, {})
                        law_links = file_info.get('law_links', {})
                        # 過濾掉無效法條（以「與」「同」等開頭的誤匹配）
                        filtered_law_links = {
                            law: link for law, link in law_links.items()
                            if not law.startswith(('與', '同', '及', '或', '和'))
                        }
                        # 合併法條連結
                        all_law_links.update(filtered_law_links)

                # 區塊1：顯示回應（為法條和案件標題加入連結）
                st.markdown("---")
                response_text = result['text']

                # 先計算回答中有多少個標題（### 1. xxx）
                import re
                title_pattern = r'###\s*\d+\.\s+[^\n]+'
                title_matches = re.findall(title_pattern, response_text)
                num_titles = len(title_matches)

                # 從 sources 提取案件連結（只取前 num_titles 個，對應有標題的案件）
                case_urls = []
                seen_file_ids = set()
                count = 0

                for source in result.get('sources', []):
                    # 只處理有標題的案件數量
                    if count >= num_titles:
                        break

                    filename = source.get('filename', '')
                    file_id = extract_file_id(filename, gemini_id_mapping)

                    # 去重（每個文件只取第一次出現）
                    if file_id and file_id not in seen_file_ids:
                        file_info = mapping.get(file_id, {})
                        detail_url = file_info.get('original_url', '')
                        if detail_url:
                            case_urls.append(detail_url)
                            seen_file_ids.add(file_id)
                            count += 1

                # 為案件標題加入連結
                response_with_case_links = insert_case_links_by_order(response_text, case_urls)

                # 為法條加入連結
                response_with_all_links = add_law_links_to_text(response_with_case_links, all_law_links)

                st.markdown(response_with_all_links)

                # ===== 區塊2：相關裁罰案件原始公告（已註解） =====
                # 註解原因：功能已整合到區塊1的標題連結
                # 保留程式碼供未來參考
                #
                # if result.get('sources') and len(result['sources']) > 0:
                #     # 收集所有原始連結（去重）
                #     original_urls = []
                #     seen_urls = set()
                #
                #     for source in result['sources']:
                #         filename = source.get('filename', '')
                #         file_id = extract_file_id(filename, gemini_id_mapping)
                #         file_info = mapping.get(file_id, {})
                #         url = file_info.get('original_url', '')
                #
                #         if url and url not in seen_urls:
                #             original_urls.append({
                #                 'url': url,
                #                 'display_name': file_info.get('display_name', file_id)
                #             })
                #             seen_urls.add(url)
                #
                #     # 顯示原始連結
                #     if original_urls:
                #         st.markdown("---")
                #         st.markdown("**🔗 相關裁罰案件原始公告**")
                #         for item in original_urls:
                #             st.markdown(f"- [{item['display_name']}]({item['url']})")

                # ===== 區塊3：也可以另外參考（新版） =====
                # 只顯示不在查詢結果標題中的額外參考文件
                if result.get('sources') and len(result['sources']) > 0:
                    st.markdown("---")
                    display_grounding_sources_v2(
                        sources=result['sources'],
                        file_mapping=mapping,
                        gemini_id_mapping=gemini_id_mapping,
                        excluded_file_ids=seen_file_ids  # 排除已在區塊1標題中的文件
                    )

                # ===== 除錯資訊：顯示原始參考內容列表 =====
                # 移到條件外，即使 sources 為空也顯示（用於診斷問題）
                st.markdown("---")
                with st.expander("🔍 除錯資訊：Gemini 原始參考列表", expanded=False):
                        # 診斷資訊：檢查 sources 是否存在
                        sources = result.get('sources', [])

                        # 整合顯示 sources 數量（未去重）和原始列表
                        with st.expander(f"📊 Gemini 返回的 sources 數量（未去重）: {len(sources)}", expanded=False):
                            if sources:
                                for i, source in enumerate(sources, 1):
                                    filename = source.get('filename', 'N/A')
                                    file_id = extract_file_id(filename, gemini_id_mapping)
                                    st.caption(f"{i}. Gemini ID: `{filename}` → File ID: `{file_id}`")
                            else:
                                st.caption("無 sources")

                        st.info(f"📝 回答中的標題數量: {num_titles}")
                        st.info(f"✅ 加入查詢結果的文件數量: {len(seen_file_ids)}")

                        if not sources:
                            st.warning("⚠️ Gemini 未返回任何參考文件（sources 為空）")
                            st.caption("可能原因：")
                            st.caption("1. Gemini 回應被截斷，導致 sources 資訊遺失")
                            st.caption("2. File Search Store 查詢失敗")
                            st.caption("3. 回應處理邏輯錯誤")
                        else:
                            # 提取並去重所有 file_ids（包含映射失敗的）
                            all_file_ids = []
                            failed_mappings = []
                            seen_debug = set()

                            for source in sources:
                                filename = source.get('filename', '')
                                file_id = extract_file_id(filename, gemini_id_mapping)

                                # 檢查是否映射成功
                                if file_id and file_id not in seen_debug:
                                    # 檢查是否在 file_mapping 中
                                    if file_id in mapping:
                                        all_file_ids.append(file_id)
                                        seen_debug.add(file_id)
                                    else:
                                        # 映射失敗（file_id 不在 file_mapping 中）
                                        failed_mappings.append({'filename': filename, 'file_id': file_id})
                                elif not file_id and filename not in [f['filename'] for f in failed_mappings]:
                                    # 完全無法提取 file_id
                                    failed_mappings.append({'filename': filename, 'file_id': None})

                            st.write(f"**總共 {len(all_file_ids)} 筆有效參考文件：**")

                            for i, file_id in enumerate(all_file_ids, 1):
                                file_info = mapping.get(file_id, {})
                                display_name = file_info.get('display_name', file_id)

                                # 標註是否已在查詢結果中
                                if file_id in seen_file_ids:
                                    st.write(f"{i}. 📄 {display_name} ✅ *（已在查詢結果中）*")
                                else:
                                    st.write(f"{i}. 📄 {display_name} ⭐ *（額外參考）*")

                            # 顯示映射失敗的檔案
                            if failed_mappings:
                                st.warning(f"⚠️ **{len(failed_mappings)} 筆映射失敗（已自動跳過）：**")
                                for i, item in enumerate(failed_mappings, 1):
                                    filename = item['filename']
                                    file_id = item['file_id']
                                    if file_id:
                                        st.caption(f"{i}. Gemini ID: `{filename}` → File ID: `{file_id}` (不在 file_mapping 中)")
                                    else:
                                        st.caption(f"{i}. Gemini ID: `{filename}` (無法提取 file_id)")
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
