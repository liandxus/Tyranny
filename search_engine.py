"""
IndeXar 全文检索模块

采用关键词遍历匹配（个人笔记库规模下足够快，无需倒排索引）。
本模块只负责数据检索，不涉及任何界面操作。
"""

from file_handler import list_notes, read_note


def strip_front_matter(content):
    """去掉开头的 YAML front matter，返回正文部分"""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:]
    return content


def search_notes(keyword, current_note=None):
    """
    遍历所有笔记匹配关键词。

    参数:
        keyword:       搜索关键词（大小写不敏感）
        current_note:  当前正在浏览的笔记相对路径（可选）

    返回 (name_matches, content_matches, current_hit):
        name_matches     —— 文件名命中关键词的笔记路径列表
        content_matches  —— 正文命中但文件名未命中的笔记路径列表
        current_hit      —— current_note 的正文是否命中（供命中数统计使用）
    """
    keyword_lower = (keyword or "").strip().lower()
    name_matches = []
    content_matches = []
    current_hit = False

    if not keyword_lower:
        return name_matches, content_matches, current_hit

    for rel_path in list_notes():
        name = rel_path.split("/")[-1].lower()
        content = strip_front_matter(read_note(rel_path) or "")

        name_hit = keyword_lower in name
        content_hit = keyword_lower in content.lower()

        if name_hit:
            name_matches.append(rel_path)
        elif content_hit:
            content_matches.append(rel_path)

        if current_note and rel_path == current_note and content_hit:
            current_hit = True

    return name_matches, content_matches, current_hit
