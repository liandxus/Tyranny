"""
IndeXar Markdown 渲染器
将 Markdown 文本格式化显示在 Tkinter Text 控件中
"""

import re


def render_markdown(text_widget, md_text, link_callback=None, font_size=11):
    """
    在 Tkinter Text 控件中渲染 Markdown 文本
    text_widget: tk.Text 控件（已启用状态）
    md_text: Markdown 原始文本
    link_callback: 点击 [[内部链接]] 时的回调，接受笔记名参数
    font_size: 基础字号
    """
    text_widget.delete(1.0, "end")

    # 如果存在 YAML front matter（--- 包裹的元数据），跳过
    if md_text.startswith("---"):
        end = md_text.find("---", 3)
        if end != -1:
            md_text = md_text[end + 3:]

    # 配置标签样式
    _configure_tags_with_size(text_widget, font_size)

    # 逐行渲染
    lines = md_text.split("\n")
    i = 0
    in_code_block = False
    code_lines = []

    while i < len(lines):
        line = lines[i]

        # ── 代码块 ──
        if line.strip().startswith("```"):
            if in_code_block:
                # 结束代码块
                _render_code_block(text_widget, code_lines)
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
                code_lines = []
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # ── 空行 ──
        if not line.strip():
            text_widget.insert("end", "\n")
            i += 1
            continue

        # ── 分隔线 ──
        if re.match(r"^[-*_]{3,}\s*$", line.strip()):
            text_widget.insert("end", "─" * 40 + "\n", "hr")
            i += 1
            continue

        # ── 标题 ──
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            tag = f"heading{level}"
            text_widget.insert("end", text + "\n", tag)
            i += 1
            continue

        # ── 引用 ──
        if line.startswith(">"):
            quote_text = line.lstrip("> ").strip()
            text_widget.insert("end", "  " + quote_text + "\n", "quote")
            i += 1
            continue

        # ── 无序列表 ──
        list_match = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if list_match:
            indent = len(list_match.group(1))
            text = list_match.group(2)
            prefix = "  " * (indent // 2) + "• "
            text_widget.insert("end", prefix)
            _insert_inline(text_widget, text + "\n", link_callback)
            i += 1
            continue

        # ── 有序列表 ──
        olist_match = re.match(r"^(\s*)\d+[.)]\s+(.+)$", line)
        if olist_match:
            indent = len(olist_match.group(1))
            text = olist_match.group(2)
            prefix = "  " * (indent // 2) + "  "
            text_widget.insert("end", prefix)
            _insert_inline(text_widget, text + "\n", link_callback)
            i += 1
            continue

        # ── 普通段落 ──
        _insert_inline(text_widget, line + "\n", link_callback)
        i += 1

    # 确保末尾有一个空行
    text_widget.insert("end", "\n")


def _configure_tags_with_size(text_widget, base_size=11):
    """配置 Text 控件中使用的各种格式标签（可指定基础字号）"""
    # 标题
    text_widget.tag_configure("heading1", font=("Microsoft YaHei", base_size + 7, "bold"),
                               foreground="#1a1a2e", spacing1=12, spacing3=6)
    text_widget.tag_configure("heading2", font=("Microsoft YaHei", base_size + 4, "bold"),
                               foreground="#16213e", spacing1=10, spacing3=4)
    text_widget.tag_configure("heading3", font=("Microsoft YaHei", base_size + 2, "bold"),
                               foreground="#0f3460", spacing1=8, spacing3=4)
    text_widget.tag_configure("heading4", font=("Microsoft YaHei", base_size + 1, "bold"),
                               foreground="#333", spacing1=6, spacing3=2)
    text_widget.tag_configure("heading5", font=("Microsoft YaHei", base_size, "bold"),
                               spacing1=4, spacing3=2)
    text_widget.tag_configure("heading6", font=("Microsoft YaHei", base_size, "bold"),
                               spacing1=4, spacing3=2)

    # 代码块
    text_widget.tag_configure("code_block",
                               font=("Consolas", base_size - 1),
                               background="#f0f0f0",
                               foreground="#333",
                               spacing1=4, spacing3=4,
                               lmargin1=16, lmargin2=16)

    # 引用
    text_widget.tag_configure("quote",
                               font=("Microsoft YaHei", base_size, "italic"),
                               foreground="#666",
                               background="#f9f9f9",
                               lmargin1=16, lmargin2=16,
                               spacing1=2, spacing3=2)

    # 分隔线
    text_widget.tag_configure("hr", foreground="#ccc")

    # 行内格式
    text_widget.tag_configure("bold", font=("Microsoft YaHei", base_size, "bold"))
    text_widget.tag_configure("italic", font=("Microsoft YaHei", base_size, "italic"))
    text_widget.tag_configure("bold_italic", font=("Microsoft YaHei", base_size, "bold italic"))
    text_widget.tag_configure("code_inline",
                               font=("Consolas", base_size - 1),
                               background="#eee",
                               foreground="#c7254e")


def _configure_tags(text_widget):
    """配置 Text 控件中使用的各种格式标签"""
    # 标题
    text_widget.tag_configure("heading1", font=("Microsoft YaHei", 18, "bold"),
                               foreground="#1a1a2e", spacing1=12, spacing3=6)
    text_widget.tag_configure("heading2", font=("Microsoft YaHei", 15, "bold"),
                               foreground="#16213e", spacing1=10, spacing3=4)
    text_widget.tag_configure("heading3", font=("Microsoft YaHei", 13, "bold"),
                               foreground="#0f3460", spacing1=8, spacing3=4)
    text_widget.tag_configure("heading4", font=("Microsoft YaHei", 12, "bold"),
                               foreground="#333", spacing1=6, spacing3=2)
    text_widget.tag_configure("heading5", font=("Microsoft YaHei", 11, "bold"),
                               spacing1=4, spacing3=2)
    text_widget.tag_configure("heading6", font=("Microsoft YaHei", 11, "bold"),
                               spacing1=4, spacing3=2)

    # 代码块
    text_widget.tag_configure("code_block",
                               font=("Consolas", 10),
                               background="#f0f0f0",
                               foreground="#333",
                               spacing1=4, spacing3=4,
                               lmargin1=16, lmargin2=16)

    # 引用
    text_widget.tag_configure("quote",
                               font=("Microsoft YaHei", 11, "italic"),
                               foreground="#666",
                               background="#f9f9f9",
                               lmargin1=16, lmargin2=16,
                               spacing1=2, spacing3=2)

    # 列表
    text_widget.tag_configure("list",
                               font=("Microsoft YaHei", 11),
                               lmargin1=16, lmargin2=16,
                               spacing1=2)

    # 分隔线
    text_widget.tag_configure("hr", foreground="#ccc")

    # 行内格式
    text_widget.tag_configure("bold", font=("Microsoft YaHei", 11, "bold"))
    text_widget.tag_configure("italic", font=("Microsoft YaHei", 11, "italic"))
    text_widget.tag_configure("bold_italic", font=("Microsoft YaHei", 11, "bold italic"))
    text_widget.tag_configure("code_inline",
                               font=("Consolas", 10),
                               background="#eee",
                               foreground="#c7254e")


def _insert_inline(text_widget, line, link_callback=None):
    """
    逐段插入行内格式化文本：**粗体** *斜体* `代码` [[内部链接]]
    每段用对应 tag 标记，支持点击跳转。
    """
    # 顺序：wikilink > 行内代码 > 粗斜体 > 粗体 > 斜体
    import re
    inline_pat = re.compile(
        r"\[\[([^\[\]]+)(?:\|([^\[\]]+))?\]\]"  # [[链接]] 或 [[链接|显示]]
        r"|`([^`]+)`"                                  # `行内代码`
        r"|\*\*\*(.+?)\*\*\*"                      # ***粗斜体***
        r"|\*\*(.+?)\*\*"                            # **粗体**
        r"|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"    # *斜体*
    )
    pos = 0
    while pos < len(line):
        m = inline_pat.search(line, pos)
        if not m:
            text_widget.insert("end", line[pos:])
            break

        # 匹配前的纯文本
        if m.start() > pos:
            text_widget.insert("end", line[pos:m.start()])

        if m.group(1):  # [[wikilink]]
            target = m.group(1).strip()
            display = m.group(2).strip() if m.group(2) else target
            tag = f"wikilink_{target}"
            text_widget.insert("end", display)
            # 标记这一段为可点击链接（+1 补偿隐式换行符）
            text_widget.tag_add(tag,
                                f"end-{len(display)+1}c", "end-1c")
            text_widget.tag_configure(tag,
                foreground="#569cd6", underline=True,
                font=("Microsoft YaHei", 11))

        elif m.group(3):  # `行内代码`
            text_widget.insert("end", m.group(3), "code_inline")
        elif m.group(4):  # ***粗斜体***
            text_widget.insert("end", m.group(4), "bold_italic")
        elif m.group(5):  # **粗体**
            text_widget.insert("end", m.group(5), "bold")
        elif m.group(6):  # *斜体*
            text_widget.insert("end", m.group(6), "italic")

        pos = m.end()


def _render_code_block(text_widget, code_lines):
    """渲染代码块"""
    if not code_lines:
        return
    code_text = "\n".join(code_lines)
    text_widget.insert("end", code_text + "\n", "code_block")
