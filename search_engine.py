"""
IndeXar 搜索模块
提供全文搜索功能
"""

from file_handler import list_notes, read_note, DATA_DIR
import os


def search_notes(keyword):
    """
    在所有笔记中搜索关键词
    返回 [(文件名, 上下文片段), ...]
    """
    results = []
    notes = list_notes()

    for note_name in notes:
        content = read_note(note_name)
        if content is None:
            continue

        # 忽略 YAML 前页（front matter）
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:]

        if keyword.lower() in content.lower():
            # 提取关键词附近的上下文片段
            snippet = _get_snippet(content, keyword)
            results.append((note_name, snippet))

    return results


def _get_snippet(text, keyword, context_chars=40):
    """提取关键词附近的一段上下文"""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return "..."

    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(keyword) + context_chars)

    snippet = ""
    if start > 0:
        snippet += "…"
    snippet += text[start:end]
    if end < len(text):
        snippet += "…"

    return snippet.strip()
