import re

# 匹配 http(s):// 链接和裸 www. 域名，索引/检索前先剥离，
# 避免域名后缀（如 .vip）里的子串被当成关键词误命中。
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def strip_urls(text: str) -> str:
    """移除文本中的 URL，返回剩余正文。"""
    return URL_RE.sub(" ", text)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """按重叠窗口切分文本，供向量化使用。"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # 优先在句号或换行处截断，减少语义被切开。
        if end < len(text):
            last_period = chunk.rfind("。")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)
            if break_point > chunk_size // 2:
                end = start + break_point + 1
        chunks.append(text[start:end].strip())
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def extract_keywords(text: str) -> list[str]:
    """提取检索关键词：英文词、中文短语和长中文片段的 2-4 字 n-gram。"""
    keywords = []

    # 先剥离 URL，避免域名/路径里的字符串污染关键词。
    text = strip_urls(text)

    # 英文关键词保留原词，但要求至少 3 个字符，过滤掉
    # VIP/ID 这类太短、极易在长正文里误命中的词。
    english_words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text)
    keywords.extend(english_words)

    # 先提取连续中文片段。
    chinese_spans = re.findall(r"[一-鿿]{2,}", text)

    # 长中文片段直接匹配效果差，拆成 2-4 字 n-gram。
    for span in chinese_spans:
        if len(span) <= 4:
            keywords.append(span)
        else:
            # 补充 2-4 字子串提升中文召回率。
            for n in range(2, 5):
                for i in range(len(span) - n + 1):
                    keywords.append(span[i:i + n])

    # 去重后优先保留 2-3 字关键词，限制最多 20 个。
    result = []
    # 第一轮保留更像中文词语的 2-3 字关键词。
    for kw in sorted(set(keywords), key=lambda x: len(x)):
        if 2 <= len(kw) <= 3 and kw not in result:
            result.append(kw)
        if len(result) >= 15:
            break
    # 第二轮补充 4 字以上短语。
    for kw in sorted(set(keywords), key=lambda x: -len(x)):
        if len(kw) >= 4 and kw not in result:
            result.append(kw)
        if len(result) >= 20:
            break
    return result
