"""
FSC 裁罰案件查詢系統
使用 Google Gemini File Search Store 進行 RAG 查詢

Version: 1.3.3 - 在頁尾顯示版本號 (2025-11-20)
  - 🏷️ 在頁面左下角顯示版本號 (v1.3.3)
  - 📐 使用兩欄佈局：左邊版本號，右邊資料來源

Previous: 1.3.2 (2025-11-20)
  - 完全移除中間標題，保持流暢段落
  - 只有具體案例才使用 ### 標題

Previous: 1.2.0 (2025-11-19)
  - 簡化 UI（參考 Sanction-Deploy 風格）+ Plain Text Store
  - 指標欄只顯示：來源數量
  - Plain Text Store: 490 筆資料，100% pcode 映射覆蓋率
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
def load_file_mapping():
    """載入檔案映射檔（移除快取以確保始終使用最新版本）"""
    from pathlib import Path
    import os

    mapping_file = Path(__file__).parent / 'data/penalties/file_mapping.json'

    if not mapping_file.exists():
        return {}

    try:
        import json
        with open(mapping_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 顯示檔案資訊供除錯
        file_mtime = os.path.getmtime(mapping_file)
        file_size = os.path.getsize(mapping_file) / (1024 * 1024)  # MB
        # st.sidebar.text(f"📄 file_mapping.json\n更新時間: {datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')}\n大小: {file_size:.2f} MB")

        return data
    except Exception as e:
        st.warning(f"⚠️ 載入映射檔失敗: {e}")
        return {}

def load_gemini_id_mapping():
    """載入 Gemini ID 反向映射檔（Gemini file_id → file_id）（移除快取以確保始終使用最新版本）"""
    from pathlib import Path
    mapping_file = Path(__file__).parent / 'data/penalties/gemini_id_mapping.json'

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
    replaced_positions = set()  # 記錄已替換的位置，避免重複替換

    # === 第一階段：處理完整法條名稱 ===
    for law in sorted_laws:
        # 跳過簡寫形式（留待第二階段處理）
        if law.startswith('第'):
            continue

        link = law_links_dict[law]

        # 提取法律名稱和條號
        law_match = re.match(r'^(.+?)(第\d+條(?:之\d+)?)', law)
        if not law_match:
            continue

        law_name = law_match.group(1)  # 例如：「金融控股公司法」
        article = law_match.group(2)   # 例如：「第45條」

        # 建立彈性匹配模式：支援書名號、項/款/目、前置連接詞
        law_name_escaped = re.escape(law_name)
        article_escaped = re.escape(article)

        # 匹配模式：可選的前置連接詞 + 法律名稱 + 條號 + 項/款/目
        pattern = (
            r'(?<!\[)(?<!\()'  # 不在連結中
            r'(?:[、，及與和以]\s*)?'  # 可選的前置連接詞
            r'(?:《)?' + law_name_escaped + r'(?:》)?'  # 法律名稱（可選書名號）
            r'\s*' + article_escaped +  # 條號
            r'(?:第\d+項)?(?:第\d+款)?(?:第\d+目)?'  # 可選的項/款/目
            r'(?!\])(?!\))'  # 不在連結中
        )

        # 找到所有匹配並收集
        matches = []
        for match in re.finditer(pattern, result):
            start, end = match.span()

            # 檢查這個位置是否已被替換
            is_overlapping = False
            for pos, pos_end in replaced_positions:
                if (start < pos_end and end > pos):
                    is_overlapping = True
                    break

            if not is_overlapping:
                matched_text = match.group(0)
                matches.append((start, end, matched_text))

        # 從後往前替換（避免位置偏移）
        for start, end, matched_text in reversed(matches):
            # 檢查是否有前置連接詞
            connector_match = re.match(r'^([、，及與和以]\s*)?(.+)$', matched_text)
            if connector_match:
                connector = connector_match.group(1) or ''
                law_part = connector_match.group(2)
                replacement = f'{connector}[{law_part}]({link})'
            else:
                replacement = f'[{matched_text}]({link})'

            result = result[:start] + replacement + result[end:]
            new_end = start + len(replacement)
            replaced_positions.add((start, new_end))

    # === 第二階段：處理簡寫形式（如「、第51條」「及第60條」） ===
    for law in sorted_laws:
        # 只處理簡寫形式
        if not law.startswith('第'):
            continue

        link = law_links_dict[law]

        # 匹配簡寫形式：前面有「、」「及」「與」「和」等連接詞
        article_escaped = re.escape(law)
        pattern = (
            r'(?<!\[)(?<!\()'  # 不在連結中
            r'(?:[、，及與和])\s*' + article_escaped +  # 連接詞 + 條號
            r'(?:第\d+項)?(?:第\d+款)?(?:第\d+目)?'  # 可選的項/款/目
            r'(?!\])(?!\))'  # 不在連結中
        )

        matches = []
        for match in re.finditer(pattern, result):
            start, end = match.span()

            # 檢查這個位置是否已被替換
            is_overlapping = False
            for pos, pos_end in replaced_positions:
                if (start < pos_end and end > pos):
                    is_overlapping = True
                    break

            if not is_overlapping:
                matched_text = match.group(0)
                # 保留前面的連接詞
                matches.append((start, end, matched_text))

        # 從後往前替換
        for start, end, matched_text in reversed(matches):
            # 提取連接詞和條號部分
            connector_match = re.match(r'([、，及與和]\s*)(.+)', matched_text)
            if connector_match:
                connector = connector_match.group(1)
                article_part = connector_match.group(2)
                replacement = f'{connector}[{article_part}]({link})'
                result = result[:start] + replacement + result[end:]
                new_end = start + len(replacement)
                replaced_positions.add((start, new_end))

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

def display_sources_simple(sources: list, file_mapping: dict, gemini_id_mapping: dict):
    """
    簡化版參考來源顯示

    顯示 Gemini 回覆的最接近 chunk 內容和原始連結

    Args:
        sources: 從 query_penalties 返回的 sources 列表（包含 snippet）
        file_mapping: file_mapping.json 的內容
        gemini_id_mapping: Gemini ID 映射
    """
    if not sources:
        st.warning("⚠️ 未找到參考來源")
        return

    # 去重並提取有效的 file_ids，同時保存對應的 snippet
    unique_sources = []
    seen = set()

    for source in sources:
        filename = source.get('filename', '')
        snippet = source.get('snippet', '')
        file_id = extract_file_id(filename, gemini_id_mapping)

        # 跳過映射失敗或不存在於 file_mapping 的檔案
        if not file_id or file_id not in file_mapping:
            continue

        if file_id not in seen:
            unique_sources.append({
                'file_id': file_id,
                'snippet': snippet
            })
            seen.add(file_id)

    if not unique_sources:
        st.warning("⚠️ 未找到有效的參考來源")
        return

    # 按日期排序（最新→最舊）
    unique_sources.sort(
        key=lambda item: file_mapping.get(item['file_id'], {}).get('date', ''),
        reverse=True  # 降序：最新的在前面
    )

    # 顯示參考來源
    st.subheader(f"📚 參考來源 ({len(unique_sources)} 筆，依時間排序）")

    for i, source_item in enumerate(unique_sources, 1):
        file_id = source_item['file_id']
        snippet = source_item['snippet']
        file_info = file_mapping.get(file_id, {})
        display_name = file_info.get('display_name', file_id)
        detail_url = file_info.get('original_url', '')

        # 使用 expander 顯示
        with st.expander(f"來源 {i}: {display_name}", expanded=False):
            # 顯示 Gemini 檢索到的最接近 chunk 內容
            if snippet:
                st.markdown("**📄 相關內容：**")
                st.markdown(f"> {snippet}")
            else:
                st.info("無可用的內容片段")

            # 原始公告連結
            if detail_url:
                st.markdown("---")
                st.markdown(f"🔗 [查看金管會原始公告]({detail_url})")

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

    store_id = os.getenv('GEMINI_STORE_ID', 'fileSearchStores/fscpenaltiesplaintext-4f87t5uexgui')

    return client, store_id

def generate_law_links_instruction() -> str:
    """
    生成法條連結的 system instruction

    從 file_mapping.json 收集所有唯一的完整法條連結，
    生成包含連結表格和格式規則的指令文字
    """
    import json
    from pathlib import Path

    # 讀取 file_mapping.json
    mapping_file = Path(__file__).parent / 'data/penalties/file_mapping.json'

    if not mapping_file.exists():
        return ""

    try:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            mapping = json.load(f)

        # 收集所有唯一的完整法條連結（不包含簡寫形式）
        all_law_links = {}
        for file_id, info in mapping.items():
            law_links = info.get('law_links', {})
            for law_text, url in law_links.items():
                # 只保留完整法條名稱（不以「第」開頭）
                if not law_text.startswith('第'):
                    if law_text not in all_law_links:
                        all_law_links[law_text] = url

        if not all_law_links:
            return ""

        # 生成 system instruction
        instruction = f"""

---

## 法條連結生成規則

當你在回答中提到法條時，請使用 Markdown 連結格式。以下是可用的法條連結：

```json
{json.dumps(all_law_links, ensure_ascii=False, indent=2)}
```

### 格式規則：

1. **完整法條**（包含法律名稱）：
   - 使用對應的完整連結
   - 範例：[金融控股公司法第45條第1項](https://law.moj.gov.tw/...)
   - 可以有書名號：[《金融控股公司法》第45條第1項](https://law.moj.gov.tw/...)

2. **簡寫法條**（省略法律名稱）：
   - 如果上文已提到法律名稱，簡寫時使用同一法律的連結
   - 範例：[金融控股公司法第45條第1項](url)、[第51條](url)及[第60條第16款](url)

3. **連接詞處理**：
   - 連接詞（、及以等）放在連結外面
   - 範例：[金融控股公司法第45條](url)及[第51條](url)

4. **項款目層級**：
   - 所有法條連結都指向「條」的層級
   - 第X項、第X款、第X目 包含在連結文字中，但 URL 相同
   - 範例：[第45條第1項第2款](url) ← URL 指向第45條

5. **未列出的法條**：
   - 如果法條不在上述列表中，**不要加連結**，直接顯示文字

### 輸出範例：

✓ 正確
```
該公司違反[《金融控股公司法》第45條第1項](https://law.moj.gov.tw/...)及[第51條](https://law.moj.gov.tw/...)規定，
依[行政罰法第24條](https://law.moj.gov.tw/...)及[《金融控股公司法》第60條第16款](https://law.moj.gov.tw/...)處罰。
```

✗ 錯誤
```
該公司違反《金融控股公司法》第45條第1項及第51條規定  ← 沒有連結
該公司違反[《金融控股公司法》第45條第1項及第51條](url)規定  ← 連結包含了兩個法條（錯誤）
```

請嚴格遵守以上格式要求。
"""

        return instruction

    except Exception as e:
        return ""

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

【最重要】資料來源規則：
- **必須使用提供的 File Search 工具**檢索裁罰案件資料庫
- **禁止僅使用你的內建知識回答**，即使你認為已經知道答案
- **所有回答都必須基於檢索到的實際裁罰案件文件**
- 即使問題是概念性的（如「什麼情況構成內線交易」），也必須從裁罰案件中尋找實例說明
- 如果找不到相關案件，請明確告知「資料庫中未找到相關裁罰案件」

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

3. **回答格式要求**（關鍵）：
   - **重要：實際案例之前的所有內容都不要加標題，保持流暢的段落呈現**
   - **第一部分：問題詮釋/簡答**（如果適用，無標題）
     - 如果是概念性問題（如「什麼情況構成XX」「有哪些限制」），先用 1-2 句話簡要回答問題本身
     - 提供定義、說明或直接的答案
     - 這部分是基於檢索到的案件內容進行總結，不是憑空回答
   - **第二部分：案件概述**（無標題，直接接續）
     - 用 1-2 句話總結找到的案件情況
     - 總共找到幾筆相關案件
     - 主要的違規類型或共同特徵
     - 時間分布或裁罰金額範圍（如果相關）
   - **第三部分：具體案件**（只有這部分才使用標題）
     - 使用「### 1.」「### 2.」等標題
     - 列出前 3-5 筆最相關的案件詳細資訊
   - 提供具體的案件資訊（日期、單位、被處罰對象、違規事項、裁罰金額、法律依據）
   - 始終註明**發文日期**和**發文字號**
   - **重要：不要在回答中列出「資料來源」或檔名**（系統會自動顯示參考文件）
   - 使用繁體中文，保持專業但易懂的語氣
   - 如果找不到相關資料，請明確告知

4. **多案件處理**（重要）：
   - 如果有多筆相關案件，列出前 3-5 筆最相關的
   - **必須嚴格按時間順序排列：最新的案件（日期較大）在前面，最舊的（日期較小）在後面**
   - 每個案件使用編號「### 1.」、「### 2.」等，依時間由新到舊
   - 每個案件獨立說明，不要混淆

5. **概念性問題處理**（重要）：
   - 當使用者提出概念性問題（如「遭裁罰後有哪些業務限制」），可以提供總結式回答
   - **但必須列出至少 1-3 個從 File Search 檢索到的具體案例**作為說明
   - 例如：先總結業務限制類型，再列出「### 1. [具體案例]」
   - **絕對禁止使用你的內建知識創造案例** - 所有案例都必須來自檢索到的實際文件
   - 如果 File Search 檢索到相關案件，就必須列出；如果真的沒有相關案件，請明確告知

6. **回答品質檢查**（關鍵）：
   - 在回答前，確認你是否真的使用了 File Search 工具
   - 確認你列出的案例確實來自檢索到的文件
   - 不要使用訓練數據中的案例，除非它們出現在 File Search 結果中

回答格式範例：

**範例 1：概念性問題（有問題詮釋）**

證券商遭主管機關裁罰「警告」處分後，根據相關法規，主要會受到以下業務限制：包括暫停新業務申請、限制分支機構設立、以及在一定期間內無法申請業務許可等。

資料庫中共找到 X 筆相關案件，主要涉及 [違規類型]，裁罰金額從 [最小金額] 到 [最大金額] 不等。以下列出最具代表性的案件：

### 1. [案件標題]（最新）
...

**範例 2：一般查詢（無問題詮釋）**

資料庫中共找到 X 筆相關裁罰案件，這些案件主要涉及 [違規類型]，集中在 [時間範圍]。以下列出最具代表性的案件：

### 1. [案件標題]（最新）
- **日期**：YYYY-MM-DD
- **發文字號**：金管XX字第XXXXXXXXX號
- **來源單位**：XXX局
- **被處罰對象**：XXX公司/銀行/保險
- **違規事項**：[簡要說明]
- **裁罰金額**：新臺幣 XXX 萬元
- **法律依據**：[相關法規條文]

### 2. [案件標題]
- **日期**：YYYY-MM-DD
- **發文字號**：金管XX字第XXXXXXXXX號
- **來源單位**：XXX局
- **被處罰對象**：XXX公司/銀行/保險
- **違規事項**：[簡要說明]
- **裁罰金額**：新臺幣 XXX 萬元
- **法律依據**：[相關法規條文]

（注意：不要在每個案件後面加上「資料來源」或檔名，系統會自動在最下方顯示參考文件）
"""

        # 附加法條連結指令（讓 Gemini 直接生成帶連結的答案）
        law_links_instruction = generate_law_links_instruction()
        if law_links_instruction:
            system_instruction += law_links_instruction

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

        # 診斷資訊（用於排查 sources 提取失敗）
        debug_info = {
            'has_candidates': False,
            'has_grounding_metadata': False,
            'has_grounding_supports': False,
            'has_grounding_chunks': False,
            'grounding_supports_count': 0,
            'grounding_chunks_count': 0
        }

        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            debug_info['has_candidates'] = True
            candidate = response.candidates[0]

            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                debug_info['has_grounding_metadata'] = True
                metadata = candidate.grounding_metadata

                # 記錄 grounding_supports 和 grounding_chunks 的狀態
                if hasattr(metadata, 'grounding_supports'):
                    debug_info['has_grounding_supports'] = bool(metadata.grounding_supports)
                    debug_info['grounding_supports_count'] = len(metadata.grounding_supports) if metadata.grounding_supports else 0

                if hasattr(metadata, 'grounding_chunks'):
                    debug_info['has_grounding_chunks'] = bool(metadata.grounding_chunks)
                    debug_info['grounding_chunks_count'] = len(metadata.grounding_chunks) if metadata.grounding_chunks else 0

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
            'sources': sources,
            'debug_info': debug_info  # 診斷資訊
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
    st.info("💡 本系統為展示用，如遇畫面無反應，請重新整理頁面")

    # 初始化 Gemini
    client, store_id = init_gemini()

    # 側邊欄：資料庫資訊
    with st.sidebar:
        # 固定使用 Flash 模型（Pro 模型在 File Search 上有 hallucination 問題）
        model = "gemini-2.5-flash"

        # 顯示資料庫資訊
        st.header("📊 資料庫資訊")
        st.caption(f"總案件數：490 筆")
        st.caption(f"日期範圍：2012-01-12 至 2025-09-25")

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
            # 第一次查詢
            result = query_penalties(client, query, store_id, model)

            # 檢查是否需要重試（sources = 0 表示 Gemini 沒有使用 File Search）
            retry_attempted = False
            if result['success'] and len(result.get('sources', [])) == 0:
                retry_attempted = True
                st.info("🔄 正在重新查詢...")
                result = query_penalties(client, query, store_id, model)

        # 顯示結果
        if result['success']:
                # 檢查是否兩次查詢都沒有 sources（防止 Hallucination）
                sources_count = len(result.get('sources', []))
                if retry_attempted and sources_count == 0:
                    # 兩次查詢都沒有使用 File Search，顯示友善訊息並停止
                    st.warning("你查詢的問題在目前的文件庫中沒有合適的結果，請更具體的描述問題，或更換其他詢問方式。")
                    # 不顯示查詢回答（避免顯示可能被捏造的內容）
                else:
                    # 有 sources 或第一次查詢就成功，正常顯示結果
                    st.success("✅ 查詢完成")

                    # 保留 sources_count 變數供後續除錯資訊使用
                    sources_count = len(result.get('sources', []))

                    st.markdown("---")

                    # 載入映射檔（用於法條連結）
                    mapping = load_file_mapping()
                    gemini_id_mapping = load_gemini_id_mapping()

                    # 收集所有參考文件中的法條連結和案例連結（用於在答案中加入連結）
                    all_law_links = {}
                    case_urls = []  # 案例連結列表（按時間排序）

                    if result.get('sources') and len(result['sources']) > 0:
                        # 先收集所有 file_id 及其資訊
                        file_ids_with_info = []
                        for source in result['sources']:
                            filename = source.get('filename', '')
                            file_id = extract_file_id(filename, gemini_id_mapping)
                            file_info = mapping.get(file_id, {})

                            if file_info:
                                file_ids_with_info.append({
                                    'file_id': file_id,
                                    'date': file_info.get('date', ''),
                                    'original_url': file_info.get('original_url', ''),
                                    'law_links': file_info.get('law_links', {})
                                })

                        # 按日期排序（最新→最舊）
                        file_ids_with_info.sort(key=lambda x: x['date'], reverse=True)

                        # 收集法條連結
                        for info in file_ids_with_info:
                            law_links = info['law_links']
                            # 過濾掉無效法條
                            filtered_law_links = {
                                law: link for law, link in law_links.items()
                                if not law.startswith(('與', '同', '及', '或', '和'))
                            }
                            all_law_links.update(filtered_law_links)

                        # 收集案例連結（按時間排序）
                        case_urls = [info['original_url'] for info in file_ids_with_info if info['original_url']]

                    # 顯示答案（加入案例連結）
                    st.subheader("📝 答案")
                    response_text = result['text']

                    # 法條連結已由 Gemini 在生成答案時自動加入（透過 system_instruction）
                    # 不再需要後處理 add_law_links_to_text()

                    # 加入案例連結（按時間順序）
                    response_with_all_links = insert_case_links_by_order(response_text, case_urls)

                    st.markdown(response_with_all_links)

                    # 顯示參考來源（簡化版）
                    if result.get('sources') and len(result['sources']) > 0:
                        st.markdown("---")
                        display_sources_simple(
                            sources=result['sources'],
                            file_mapping=mapping,
                            gemini_id_mapping=gemini_id_mapping
                        )

                    # 除錯資訊（折疊）
                    st.markdown("---")
                    with st.expander("⚠️ 本系統僅供參考，實際裁罰資訊請以金管會官網公告為準", expanded=False):
                        st.info(f"📊 參考來源數量: {sources_count} 筆")
                        if sources_count == 0:
                            st.warning("⚠️ 此次查詢未使用參考文件（可能是 Gemini 自行回答）")
        else:
            st.error(f"❌ 查詢失敗：{result['error']}")

    elif search_button and not query:
        st.warning("⚠️ 請輸入查詢內容")

    # 頁尾
    st.divider()

    # 使用兩欄佈局：左邊版本號，右邊資料來源
    footer_col1, footer_col2 = st.columns([1, 4])

    with footer_col1:
        st.caption("v1.3.3")

    with footer_col2:
        st.caption("資料來源：金融監督管理委員會")

if __name__ == "__main__":
    main()
