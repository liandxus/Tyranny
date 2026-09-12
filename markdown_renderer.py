"""
IndeXar Markdown 渲染器
使用 markdown 库将 Markdown 转为 HTML，再解析 HTML 在 Tkinter Text 控件中渲染
"""

import os
import re
from collections import namedtuple
from html.parser import HTMLParser
from html import unescape

import tkinter as tk
from tkinter import ttk

import markdown

# 站内链接的判定、取名与代码区识别与反向索引共用（见 file_handler），
# 两处若各写一套，就会出现"能跳转却不进反链"这类不一致
from file_handler import (
    looks_like_note_target as _looks_like_note_target,
    note_name_from_href as _note_name_from_href,
    mask_code_regions as _mask_code_regions,
    DATA_DIR,
)

# ── 语法高亮（可选依赖）：缺失时代码块退化为纯文本，不影响其它渲染 ──
try:
    from pygments import lex as _pyg_lex
    from pygments.lexers import get_lexer_by_name as _pyg_lexer_by_name
    from pygments.lexers import guess_lexer as _pyg_guess_lexer
    from pygments.styles import get_style_by_name as _pyg_get_style
    from pygments.token import Token as _PygToken
    _HAS_PYGMENTS = True
except Exception:      # pragma: no cover - 依赖缺失时的降级路径
    _HAS_PYGMENTS = False
    _PygToken = None

# Pygments 配色风格：亮色用 VS 风格，暗色用 Monokai
_PYG_STYLE_LIGHT = "vs"
_PYG_STYLE_DARK = "monokai"
_pyg_style_cache = {}


def render_markdown(text_widget, md_text, link_callback=None, font_size=11,
                    base_dir=None, image_mode=None,
                    hover_callback=None, extlink_callback=None):
    """
    在 Tkinter Text 控件中渲染 Markdown 文本。

    参数:
        text_widget: tk.Text 控件（可编辑状态）
        md_text:     Markdown 原始文本
        link_callback: 点击 [[内部链接]] 时的回调，接受目标笔记名参数
        font_size:   基础字号
        base_dir:    当前笔记所在目录（绝对路径），用于解析图片相对路径
        image_mode:  "fit" 适应宽度（默认） / "original" 原始尺寸
        hover_callback:    鼠标悬浮提示回调，参数为提示文本；传 None 表示清除
        extlink_callback:  Ctrl+点击外部链接时的回调，接受 URL
    """
    text_widget.delete(1.0, "end")

    # 图片渲染上下文：基准目录、显示模式、PhotoImage 引用（防止被 GC 回收）
    text_widget._base_dir = base_dir
    if image_mode in ("fit", "original"):
        text_widget._image_mode = image_mode
    text_widget._md_images = []
    text_widget._hover_cb = hover_callback
    text_widget._extlink_cb = extlink_callback

    # 清理上一次渲染的代码块控件：Text.delete 只会摘除嵌入窗口，
    # 不会销毁它们，需手动 destroy 否则会随渲染次数累积
    for holder in getattr(text_widget, "_md_code_blocks", []):
        try:
            holder.destroy()
        except Exception:
            pass
    text_widget._md_code_blocks = []
    # 表格同理：delete 只摘除嵌入窗口，不销毁，需手动清理防止累积
    for ref in getattr(text_widget, "_md_tables", []):
        try:
            ref.tree.destroy()
        except Exception:
            pass
    text_widget._md_tables = []
    text_widget._code_last_width = -1
    _bind_code_resize(text_widget)

    # 清理上一次渲染留下的动态链接标签，防止颜色残留
    _cleanup_dynamic_tags(text_widget)
    # 重置链接映射，并依背景预计算外链颜色
    text_widget._extlink_map = {}
    text_widget._wikilink_map = {}
    try:
        _ext_dark = _is_dark_color(text_widget.cget("bg"))
    except Exception:
        _ext_dark = False
    text_widget._ext_fg = "#5aa2e8" if _ext_dark else "#0b5cad"

    # 跳过 YAML front matter
    if md_text.startswith("---"):
        end = md_text.find("---", 3)
        if end != -1:
            md_text = md_text[end + 3:]

    # [[wikilink]] 预处理 → 标准 markdown 链接（协议前缀标记内部链接）
    md_text = _preprocess_wikilinks(md_text)

    # GFM 任务列表 [ ] / [x] → 复选框占位符
    md_text = _preprocess_task_lists(md_text)

    # ~~删除线~~ → <del>（markdown 库的 extra 扩展不含 GFM 删除线语法）
    md_text = _preprocess_strikethrough(md_text)

    # 使用 markdown 库转换为 HTML：
    # extra 提供表格、围栏代码块、脚注等；sane_lists 让有序/无序列表按
    # 标准规则解析（缺省时紧邻的 ol 与 ul 会被合并成一个列表）
    html = markdown.markdown(md_text, extensions=['extra', 'sane_lists'])

    # 配置 Text 标签样式（自动适配亮/暗主题）
    _configure_tags_with_size(text_widget, font_size)

    # 解析 HTML 并渲染到 Text 控件
    renderer = _MarkdownHTMLRenderer(text_widget, link_callback, font_size)
    renderer.feed(html)
    renderer.close()

    # 末尾空行
    text_widget.insert("end", "\n")


# ══════════════════════════════════
# 内部链接预处理
# ══════════════════════════════════

def _preprocess_strikethrough(text):
    """把 GFM 删除线 ~~文字~~ 转成 <del>文字</del>。

    markdown 库的 extra 扩展不包含删除线语法，这里自行预处理；
    围栏代码块与行内代码内的 ~~ 保持原样。"""
    out = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        # 围栏判定与 _preprocess_task_lists、file_handler.mask_code_regions 一致：
        # ``` 与 ~~~ 都算围栏。此前只认 ```，导致 ~~~ 围栏里的代码正文
        # 被当作普通文本改写，显示与复制的内容一并失真。
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        # 按行内代码切分，只处理非代码段
        parts = re.split(r"(`+[^`]*`+)", line)
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~",
                              r"<del>\1</del>", parts[i])
        out.append("".join(parts))
    return "\n".join(out)


# GFM 任务列表：- [ ] / - [x]
# [ ]、[x] 保持原样会被当成普通文本（还可能被误判成引用式链接），
# 先换成控制字符包裹的占位符，渲染时再换成复选框
# 行首允许缩进与引用符号，以便覆盖「引用块里的任务列表」这类嵌套写法
_TASK_LINE_RE = re.compile(
    r'^([\t ]*(?:>[\t ]*)*)([-*+]|\d+[.)])([\t ]+)(\[[ xX]\])([ \t]*)')
_TASK_MARK_RE = re.compile('\u0001TASK([01])\u0001[ \t]*')
_TASK_PLAIN_RE = re.compile('\u0001TASK([01])\u0001')


def _restore_task_marks(text):
    """把没被列表项消费掉的占位符还原成 [ ] / [x]。

    写法不规范的列表（例如引用块里与前一段之间没有空行）不会被
    markdown 解析成列表，此时占位符就会流到正文，必须还原，
    否则控制字符会直接显示出来。"""
    if "\u0001" not in text:
        return text
    return _TASK_PLAIN_RE.sub(
        lambda m: "[x]" if m.group(1) == "1" else "[ ]", text)


def _preprocess_task_lists(text):
    """把任务列表的 [ ] / [x] 替换为占位符（围栏代码块内保持原样）"""
    out = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        m = _TASK_LINE_RE.match(line)
        if m:
            mark = ("\u0001TASK1\u0001" if m.group(4)[1].lower() == "x"
                    else "\u0001TASK0\u0001")
            line = line[:m.start(4)] + mark + m.group(5) + line[m.end():]
        out.append(line)
    return "\n".join(out)


def _preprocess_wikilinks(text):
    """将 [[target]] 和 [[target|display]] 转为标准 Markdown 链接，
       使用 wikilink: 协议前缀标记内部链接，供后续渲染时识别。

       行内代码与围栏代码块内的写法不作改写：那里的双括号多是语法示例，
       一并改写会连代码块的显示内容与复制结果一起破坏。"""
    def _replace(m):
        target = m.group(1).strip()
        display = m.group(2).strip() if m.group(2) else target
        return f'[{display}](wikilink:{target})'

    masked, restore = _mask_code_regions(text)
    return restore(re.sub(r'\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]',
                          _replace, masked))


# ══════════════════════════════════
# HTML → Text 渲染器
# ══════════════════════════════════

# 表格在主 Text 中的登记信息：控件、所在位置、各行 (iid, 单元格文本)
_TableRef = namedtuple("_TableRef", "tree position rows")


class _MarkdownHTMLRenderer(HTMLParser):
    """将 markdown 库生成的 HTML 渲染到 Tkinter Text 控件。"""

    def __init__(self, text_widget, link_callback, font_size):
        super().__init__()
        self.w = text_widget
        self.link_cb = link_callback
        self.fs = font_size

        # 行内样式栈：元素为 'bold'|'italic'|'code_inline'|('wikilink', target)|('extlink', url)
        self._stack = []
        self._ext_idx = 0      # 外部链接动态 tag 计数器
        self._wikilink_idx = 0  # 内部链接动态 tag 计数器

        # ── 代码块状态 ──
        self._in_pre = False
        self._code_buf = []
        self._code_lang = None     # 围栏代码块的 language-xxx 标识

        # ── 列表状态 ──
        self._list_depth = 0      # 嵌套深度
        self._list_stack = []     # 每层 [类型('ul'/'ol'), 下一个编号]
        self._li_fresh = False    # 刚插入 li 项目符号，用于跳过随后的格式化空白
        self._li_pending = False  # 项目符号延后输出（任务列表项要换成复选框）

        # ── 链接状态 ──
        self._anchor_title = ""     # 当前 <a> 的 title，供图片悬浮提示使用

        # ── 表格状态 ──
        self._in_table = False
        self._in_thead = False
        self._table_rows = []       # [(is_header, [cell1, cell2, ...]), ...]
        self._table_cells = []      # 当前行已完成的单元格
        self._current_cell = ""     # 当前单元格累积文本

    # ── 开始标签 ──

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)

        # 代码块：<pre> 内所有内容原样保留
        if tag == 'pre':
            self._in_pre = True
            self._code_lang = None
            return
        if self._in_pre:
            # <pre><code class="language-python"> —— 只取语言标识，不建样式
            if tag == 'code':
                m = re.search(r'language-([\w+#.\-]+)', a.get('class', '') or '')
                if m:
                    self._code_lang = m.group(1)
            return

        # ── 表格 ──
        if tag == 'table':
            self._in_table = True
            self._table_rows = []
            self._table_cells = []
            return
        if not self._in_table:
            pass  # 非表格内，继续后续处理
        elif tag == 'thead':
            self._in_thead = True
            return
        elif tag == 'tbody':
            self._in_thead = False
            return
        elif tag == 'tr':
            self._table_cells = []
            return
        elif tag in ('th', 'td'):
            self._current_cell = ""  # 开始新单元格
            return
        elif tag == 'img':
            # 单元格里的图片不建嵌入控件，退化为文本占位。
            # 此前该分支落到下方行内处理，图片被直接 window_create 进主 Text，
            # 单元格只拿到空串，图片跑到表格之外，整张表的图文错位。
            alt = a.get('alt', '') or os.path.basename(a.get('src', ''))
            self._current_cell += f"[图片: {alt}]"
            return

        # ── 行内样式（压栈）──
        if tag in ('strong', 'b'):
            self._stack.append('bold')
        elif tag in ('em', 'i'):
            self._stack.append('italic')
        elif tag == 'code':
            self._stack.append('code_inline')
        elif tag in ('del', 's'):
            self._stack.append('strikethrough')
        elif tag == 'a':
            href = a.get('href', '')
            title = a.get('title', '')
            # 先清空再按分支回填：此前任何 <a> 都写入 _anchor_title，
            # 但只有 wikilink/extlink 会在 _pop_anchor 里清空。像 [x](foo.txt "T")
            # 这类不进栈的链接会让标题残留，被后续图片当作悬浮提示显示出来。
            self._anchor_title = ""
            if href.startswith('wikilink:'):
                self._anchor_title = title
                self._stack.append(('wikilink', href[9:]))
            elif href.startswith(('http://', 'https://')):
                self._anchor_title = title
                self._stack.append(('extlink', href))
            elif _looks_like_note_target(href):
                # 非协议链接：形如 [文字](笔记名) 或 [文字](./笔记.md)，
                # 与 [[笔记名]] 走同一套跳转逻辑
                self._anchor_title = title
                self._stack.append(('wikilink', _note_name_from_href(href)))

        # ── 块级元素 ──（先清栈确保无残留 tag）
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            # 只清行内样式与旧标题，保留 quote 这类外层块级样式。
            # 此前无条件 clear()，引用块里的标题会把 quote 一并清掉且不恢复，
            # 该引用块标题之后的内容全部失去引用样式。
            self._clear_inline_stack()
            level = int(tag[1])
            self._stack.append(f'heading{level}')
        elif tag == 'blockquote':
            self._stack.append('quote')
        elif tag == 'img':
            self._insert_image(a.get('src', ''), a.get('alt', ''),
                               a.get('title', ''))
        elif tag == 'hr':
            self.w.insert('end', '─' * 40 + '\n', 'hr')

        # ── 列表 ──
        elif tag in ('ul', 'ol'):
            self._flush_pending_bullet()        # 列表项里直接嵌套列表
            self._list_depth += 1
            # 起始编号取 start 属性：编号不从 1 开始（或列表被中间块打断）时
            # markdown 会写出 <ol start="3">，写死 1 会让编号与原文不符
            try:
                start = int(a.get('start') or 1)
            except (TypeError, ValueError):
                start = 1
            self._list_stack.append([tag, start])  # 每层独立记录类型与编号
        elif tag == 'li':
            # 符号推迟到第一段文本：任务列表项要用复选框替代圆点
            self._li_pending = True
            self._li_fresh = True

    def _flush_pending_bullet(self):
        """补插尚未输出的列表项符号（嵌套列表或空列表项时调用）"""
        if self._li_pending:
            self._li_pending = False
            self._insert(self._list_bullet())

    def _take_list_bullet(self, head):
        """输出列表项符号并返回剩余待渲染文本。

        任务列表项（占位符开头）用复选框代替圆点，并吃掉占位符本身。"""
        m = _TASK_MARK_RE.match(head)
        if m:
            indent = "  " * (self._list_depth - 1)
            box = "☑" if m.group(1) == "1" else "☐"
            self._insert(indent + box + " ")
            return head[m.end():]
        self._insert(self._list_bullet())
        return head

    def _list_bullet(self):
        """返回当前列表深度的项目符号（按该层自身的类型决定圆点或编号）"""
        indent = "  " * (self._list_depth - 1)
        if not self._list_stack:
            return f"{indent}• "
        kind, num = self._list_stack[-1]
        if kind == 'ol':
            self._list_stack[-1][1] = num + 1
            return f"{indent}{num}. "
        return f"{indent}• "

    # ── 结束标签 ──

    def handle_endtag(self, tag):
        tag = tag.lower()

        # 代码块结束
        if self._in_pre:
            if tag == 'pre':
                self._in_pre = False
                if self._code_buf:
                    # 直接拼接：HTML 实体（&lt; 等）会让 handle_data 分多次调用，
                    # 片段间本就连续，用 join('\n') 会多出换行
                    self._flush_code_block(''.join(self._code_buf))
                    self._code_buf = []
                    self._code_lang = None
            return

        # ── 表格结束 ──
        if tag == 'table':
            self._in_table = False
            self._stack.clear()  # 安全清栈，防止表格内残留样式泄露
            # 列表项以表格开头时，项目符号仍挂起，需在表格之前补插
            self._flush_pending_bullet()
            self._render_table()
            return
        if self._in_table:
            # 表格行/单元格结束
            if tag == 'tr':
                self._table_rows.append((self._in_thead, self._table_cells))
            elif tag in ('th', 'td'):
                self._table_cells.append(self._current_cell.strip())
                self._current_cell = ""
            # 表格内的行内样式也需要弹栈，防止泄露到后续元素
            elif tag in ('strong', 'b'):
                self._pop_str('bold')
            elif tag in ('em', 'i'):
                self._pop_str('italic')
            elif tag == 'code':
                self._pop_str('code_inline')
            elif tag in ('del', 's'):
                self._pop_str('strikethrough')
            elif tag == 'a':
                self._pop_anchor()
            return

        # ── 行内样式（弹栈）──
        if tag in ('strong', 'b'):
            self._pop_str('bold')
        elif tag in ('em', 'i'):
            self._pop_str('italic')
        elif tag == 'code':
            self._pop_str('code_inline')
        elif tag in ('del', 's'):
            self._pop_str('strikethrough')
        elif tag == 'a':
            self._pop_anchor()

        # ── 块级元素收尾 ──
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._pop_str(f'heading{tag[1]}')
            self._insert('\n')
        elif tag == 'blockquote':
            self._pop_str('quote')
            self._insert('\n')
        elif tag in ('p',):
            self._insert('\n')
        elif tag == 'br':
            self._insert('\n')

        # ── 列表收尾 ──
        elif tag == 'li':
            self._flush_pending_bullet()   # 空列表项：补上符号
            self._li_fresh = False
            self._insert('\n')
        elif tag in ('ul', 'ol'):
            self._list_depth = max(0, self._list_depth - 1)
            if self._list_stack:
                self._list_stack.pop()

    # ── 文本数据 ──

    def handle_data(self, data):
        # 代码块内：原样收集
        if self._in_pre:
            self._code_buf.append(data)
            return

        # 表格单元格内：累积文本（跨行内标签合并为一个单元格）
        # 不经 unescape：HTMLParser 默认 convert_charrefs=True，handle_data
        # 收到的文本已反转义一次。再转一次会把笔记里字面量写的 &lt;i&gt;
        # 显示成 <i>，与代码块路径（原样保留）不一致。
        if self._in_table:
            self._current_cell += _restore_task_marks(data)
            return

        # <li> 与内容之间的格式化空白（HTML 源码里的换行）不渲染，
        # 否则松散列表里项目符号会与文字被拆成两行
        if self._li_fresh:
            self._li_fresh = False
            if not data.strip():
                return

        # 列表项：符号延后到此处输出，任务列表项据此换成复选框
        if self._li_pending:
            self._li_pending = False
            data = self._take_list_bullet(data)

        # 普通文本：渲染（同样不再二次 unescape，理由见上）
        self._insert(data)

    # ── 辅助函数 ──

    def _insert(self, text, extra_tags=()):
        """向 Text 控件插入文本，应用当前样式栈中所有标签"""
        text = _restore_task_marks(text)
        tags = list(extra_tags)
        for s in self._stack:
            if isinstance(s, tuple) and s[0] == 'wikilink':
                # 用索引 tag + 映射表：Tk 的 tag 名不能含空格（会按空格分裂），
                # 而笔记名本身可能带空格，完整名字存映射供点击时还原
                tag_name = f'wikilink_{self._wikilink_idx}'
                self._wikilink_idx += 1
                tags.append(tag_name)
                self.w.tag_configure(tag_name,
                    foreground="#569cd6", underline=True,
                    font=("Microsoft YaHei", self.fs))
                if not hasattr(self.w, "_wikilink_map"):
                    self.w._wikilink_map = {}
                self.w._wikilink_map[tag_name] = s[1]
            elif isinstance(s, tuple) and s[0] == 'extlink':
                tag_name = f'extlink_{self._ext_idx}'
                self._ext_idx += 1
                tags.append(tag_name)
                self.w.tag_configure(
                    tag_name,
                    foreground=getattr(self.w, "_ext_fg", "#0b5cad"),
                    underline=True)
                # 记录 URL，供 GUI 点击时打开
                if not hasattr(self.w, "_extlink_map"):
                    self.w._extlink_map = {}
                self.w._extlink_map[tag_name] = s[1]
            else:
                tags.append(s)

        # ***粗斜体*** 会同时压入 bold 与 italic，而 Tk 同一字符上同优先级
        # 的 tag 只生效一个，必须换成专门的 bold_italic 样式
        if 'bold' in tags and 'italic' in tags:
            tags = [t for t in tags if t not in ('bold', 'italic')]
            tags.append('bold_italic')

        if tags:
            self.w.insert('end', text, tuple(tags))
        else:
            self.w.insert('end', text)

    # ── 代码块 ──

    def _flush_code_block(self, code):
        """渲染代码块：独立控件承载，带语言标签、复制按钮与语法高亮。

        之所以不用 Text tag 直接插入：主 Text 的 wrap 是全局的，
        无法只对代码块关闭折行，长代码行会被拆成多行难以阅读。"""
        # markdown 库会在 <pre> 内容末尾保留换行，先去掉尾随空行
        code = code.rstrip("\n")
        if not code.strip():
            return

        w = self.w
        try:
            base_bg = w.cget("bg")
        except tk.TclError:
            base_bg = "#ffffff"
        dark = _is_dark_color(base_bg)
        style = _pyg_style(dark)
        fs = max(8, self.fs - 1)

        # 'vs' 等亮色方案的背景是纯白，与正文同色会让代码块失去边界感
        style_bg = getattr(style, "background_color", None)
        if dark:
            code_bg = style_bg or "#272822"
        elif style_bg and style_bg.lower() != "#ffffff":
            code_bg = style_bg
        else:
            code_bg = "#f6f8fa"
        code_fg = self._pyg_text_fg(style) or ("#d4d4d4" if dark else "#333333")
        border = "#3f3f46" if dark else "#d8d8d8"
        bar_bg = "#2b2b2b" if dark else "#ececec"
        bar_fg = "#9c9c9c" if dark else "#666666"
        ok_fg = "#4ec9b0" if dark else "#0a7d3c"

        lexer = self._code_lexer(self._code_lang, code)
        label = lexer.name if lexer else (self._code_lang or "纯文本")
        if label == "Text only":        # Pygments 对 ```text 的显示名
            label = "纯文本"

        holder = tk.Frame(w, bg=border, bd=0, highlightthickness=1,
                          highlightbackground=border, highlightcolor=border)

        # ── 顶部栏：语言标签 + 复制按钮 ──
        bar = tk.Frame(holder, bg=bar_bg)
        bar.pack(side=tk.TOP, fill=tk.X)
        tk.Label(bar, text=label, font=("Microsoft YaHei", max(8, fs - 1)),
                 bg=bar_bg, fg=bar_fg, padx=10, pady=3).pack(side=tk.LEFT)
        copy_lbl = tk.Label(bar, text="复制",
                            font=("Microsoft YaHei", max(8, fs - 1)),
                            bg=bar_bg, fg=bar_fg, padx=10, pady=3,
                            cursor="hand2")
        copy_lbl.pack(side=tk.RIGHT)

        # ── 代码主体：wrap=NONE，代码按原样单行呈现 ──
        body = tk.Text(holder, wrap=tk.NONE, height=code.count("\n") + 1,
                       font=("Consolas", fs), bg=code_bg, fg=code_fg,
                       bd=0, highlightthickness=0, relief=tk.FLAT,
                       padx=12, pady=8, insertontime=0, cursor="arrow",
                       selectbackground="#264f78" if dark else "#cce8ff",
                       selectforeground="#ffffff" if dark else "#000000")
        body.pack(side=tk.TOP, fill=tk.X)

        hsb = tk.Scrollbar(holder, orient=tk.HORIZONTAL, command=body.xview,
                           bg=bar_bg, troughcolor=code_bg,
                           activebackground=border, bd=0,
                           highlightthickness=0, width=9)
        body.configure(xscrollcommand=hsb.set)

        self._render_code_body(body, code, lexer, style, fs)

        # ── 复制：按钮复制整块，右键可复制选中片段 ──
        def _put(text):
            try:
                w.clipboard_clear()
                w.clipboard_append(text)
            except Exception:
                pass

        def _restore_copy():
            try:
                if copy_lbl.winfo_exists():
                    copy_lbl.configure(text="复制", fg=bar_fg)
            except Exception:
                pass

        def _copy(event=None):
            _put(code)
            copy_lbl.configure(text="已复制", fg=ok_fg)
            w.after(1200, _restore_copy)

        copy_lbl.bind("<Button-1>", _copy)
        copy_lbl.bind("<Enter>", lambda e: copy_lbl.configure(fg=code_fg))
        copy_lbl.bind("<Leave>", lambda e: copy_lbl.configure(fg=bar_fg))

        # body 保持可编辑态才能用鼠标选中；输入在此拦截，Ctrl+C 等组合放行
        def _block_edit(e):
            if e.state & 0x4 or e.state & 0x8 or e.state & 0x20000:
                return None                      # Ctrl/Alt 组合：交给系统绑定
            if e.keysym == "Tab":                # Tab 用于移焦，别插进正文
                w.focus_set()
                return "break"
            if len(e.keysym) == 1 or e.keysym in (
                    "Return", "KP_Enter", "BackSpace", "Delete"):
                return "break"
            return None
        body.bind("<Key>", _block_edit)
        body.bind("<<Paste>>", lambda e: "break")

        def _popup(e):
            sel = body.tag_ranges(tk.SEL)
            menu = tk.Menu(body, tearoff=0)
            if sel:
                picked = body.get(sel[0], sel[1])
                menu.add_command(label="复制选中", command=lambda: _put(picked))
            menu.add_command(label="复制全部", command=lambda: _put(code))
            menu.post(e.x_root, e.y_root)
        body.bind("<Button-3>", _popup)

        # ── 滚轮：垂直交给主 Text，Shift+滚轮横向滚动代码块 ──
        self._bind_wheel_to_text(body)

        def _wheel_x(e):
            step = int(e.delta / 120) or (1 if e.delta > 0 else -1)
            body.xview_scroll(-step, "units")
            return "break"
        body.bind("<Shift-MouseWheel>", _wheel_x)

        # 登记：主 Text 宽度变化时重排（Text 的 width 以字符计）
        holder._code_body = body
        holder._code_text = code
        holder._code_resize = lambda avail: self._resize_code_block(
            holder, body, hsb, fs, avail)
        if not hasattr(w, "_md_code_blocks"):
            w._md_code_blocks = []
        w._md_code_blocks.append(holder)
        holder._code_resize(_available_width(w))

        # 嵌入：前一行非空时先换行，避免与正文挤在同一行
        try:
            if w.index("end-1c") != w.index("end-1c linestart"):
                w.insert("end", "\n")
        except tk.TclError:
            pass
        w.window_create("end", window=holder, pady=6)
        # 记录嵌入控件在主 Text 中的位置，供搜索时把代码块命中与正文命中
        # 按文档顺序排序、并据此滚动定位。
        # 注意：window_create 后窗口自身占一个字符位，end-1c 落在该窗口
        # 之后的一个字符上，比窗口索引多一列。现有消费方（find_all_hits、
        # ui.search._scroll_to_index）都只取行号，故无影响；若日后要按列
        # 比较嵌入命中与正文命中的先后，此处需改用 end-2c。
        holder._code_index = w.index("end-1c")
        w.insert("end", "\n")

    def _code_lexer(self, lang, code):
        """按语言标识取 lexer。

        无标识（缩进代码块）不猜语言：短片段猜测误判率高，
        反而会得到错误的高亮配色。"""
        if not _HAS_PYGMENTS or not lang:
            return None
        try:
            return _pyg_lexer_by_name(lang, stripnl=False, stripall=False)
        except Exception:
            pass
        try:
            return _pyg_guess_lexer(code, stripnl=False, stripall=False)
        except Exception:
            return None

    def _render_code_body(self, body, code, lexer, style, fs):
        """把代码按 Pygments token 分段插入，每段套对应颜色 tag"""
        body.configure(state=tk.NORMAL)
        try:
            if lexer is not None and _HAS_PYGMENTS:
                cache = {}
                for ttype, value in _pyg_lex(code, lexer):
                    if not value:
                        continue
                    color, bold, italic = _pyg_token_style(style, ttype, cache)
                    if color or bold or italic:
                        body.insert("end", value,
                                    self._pyg_tag(body, color, bold,
                                                  italic, fs))
                    else:
                        body.insert("end", value)
            else:
                body.insert("end", code)
        except Exception:
            # 高亮失败不应影响阅读，退回纯文本
            body.delete("1.0", "end")
            body.insert("end", code)
        # 不置 DISABLED：禁用态无法聚焦，选中后 Ctrl+C 复制会失效
        body.configure(state=tk.NORMAL)

    def _pyg_tag(self, body, color, bold, italic, fs):
        """按颜色/字形取（必要时创建）代码高亮 tag"""
        name = "pyg_" + (color.lstrip("#") if color else "d")
        if bold:
            name += "b"
        if italic:
            name += "i"
        if name not in body.tag_names():
            mods = " ".join(x for x in (("bold" if bold else ""),
                                        ("italic" if italic else "")) if x)
            cfg = {"font": ("Consolas", fs) + ((mods,) if mods else ())}
            if color:
                cfg["foreground"] = color
            body.tag_configure(name, **cfg)
        return name

    def _pyg_text_fg(self, style):
        """取配色方案中正文（Token.Text）的前景色"""
        if style is None or _PygToken is None:
            return None
        return _pyg_token_style(style, _PygToken.Text, {})[0]

    def _resize_code_block(self, holder, body, hsb, fs, avail):
        """按可用像素宽度换算字符列数；最长行超出可视宽度才显示横向滚动条。

        这里用字体测量而非 body.xview()：嵌入窗口在布局完成前 xview()
        恒为 (0.0, 1.0)，据此判断会永远不显示滚动条。"""
        try:
            from tkinter import font as tkfont
            f = tkfont.Font(font=("Consolas", fs))
            cw = max(1, f.measure("0"))
        except Exception:
            f, cw = None, 8

        # 扣除 body 的 padx(12×2) 与 holder 边框
        cols = max(20, int((avail - 26) / cw))
        try:
            body.configure(width=cols)
        except tk.TclError:
            return

        code = getattr(holder, "_code_text", "") or ""
        if f is not None and code:
            # 按像素量最长行：等宽字体下中英文宽度不同，不能只比字符数
            longest = max(code.split("\n"), key=f.measure)
            need = f.measure(longest) > cols * cw
        else:
            need = any(len(x) > cols for x in code.split("\n"))

        try:
            # 用 winfo_manager 而非 winfo_ismapped：嵌入窗口只有滚动到
            # 可视区才会被映射，未映射不代表没布局
            laid_out = bool(hsb.winfo_manager())
            if need and not laid_out:
                hsb.pack(side=tk.BOTTOM, fill=tk.X)
            elif not need and laid_out:
                hsb.pack_forget()
        except Exception:
            pass

    # ── 图片 ──

    def _insert_image(self, src, alt, title=""):
        """插入图片：按 _image_mode 决定「适应宽度」或「原始尺寸」"""
        # 列表项以图片开头时，项目符号仍挂在 _li_pending 上；此处不补插
        # 就会落到图片之后，形成一行孤立的符号。
        self._flush_pending_bullet()
        path = self._resolve_image_path(src)
        if not path:
            self._insert(f"[图片：{alt or src}]",
                         extra_tags=("img_placeholder",))
            self._insert("\n")
            return
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self._insert(f"[图片：{alt or src}]",
                         extra_tags=("img_placeholder",))
            self._insert("\n")
            return

        try:
            img = Image.open(path)
            img.load()
        except Exception:
            self._insert(f"[图片无法读取：{alt or src}]",
                         extra_tags=("img_placeholder",))
            self._insert("\n")
            return

        w, h = img.size
        target = w
        if getattr(self.w, "_image_mode", "fit") != "original":
            avail = self._available_width()
            if w > avail:
                target = avail
        if w > 0 and target != w:
            ratio = target / float(w)
            resample = getattr(Image, "Resampling", Image).LANCZOS
            try:
                img = img.convert("RGBA").resize(
                    (max(1, target), max(1, int(h * ratio))), resample)
            except Exception:
                pass

        try:
            photo = ImageTk.PhotoImage(img)
        except Exception:
            self._insert(f"[图片无法显示：{alt or src}]",
                         extra_tags=("img_placeholder",))
            self._insert("\n")
            return

        # 保持引用，防止 PhotoImage 被回收导致图片空白
        if not hasattr(self.w, "_md_images"):
            self.w._md_images = []
        self.w._md_images.append(photo)

        anchor = self._current_anchor()
        hint = self._image_hint(title or self._anchor_title, alt, anchor)

        # 用 Label 承载图片：Text 的嵌入图片无法接收鼠标事件，
        # 换成窗口部件后才能支持悬浮提示与点击跳转
        try:
            text_bg = self.w.cget("bg")
        except tk.TclError:
            text_bg = "#ffffff"
        holder = tk.Label(self.w, image=photo, bg=text_bg,
                          bd=0, highlightthickness=0, padx=0, pady=0)
        if anchor:
            holder.configure(cursor="hand2")
        hover_cb = getattr(self.w, "_hover_cb", None)
        if hint and hover_cb:
            holder.bind("<Enter>", lambda e, t=hint: hover_cb(t))
            holder.bind("<Leave>", lambda e: hover_cb(None))
        if anchor:
            holder.bind("<Button-1>",
                        lambda e, a=anchor: self._activate_anchor(e, a))
        # 图片会截获滚轮事件，需转发给 Text，否则鼠标停在图上无法滚动
        self._bind_wheel_to_text(holder)

        try:
            self.w.window_create("end", window=holder, pady=6, align="center")
        except tk.TclError:
            return
        # 行尾换行直接插入、不带样式栈标签：图片位于链接内时锚点仍在栈上，
        # 若让换行带上链接标签，其背景会从图片一直涂到行尾，悬浮高亮与
        # 点击热区随之外溢到图片右侧的空白处
        self.w.insert("end", "\n")

    def _bind_wheel_to_text(self, widget):
        """把嵌入控件（图片/表格）的滚轮事件转发给 Text，
        由内容区统一处理，避免各处滚动步长不一致"""
        def _wheel(e):
            self.w.event_generate("<MouseWheel>", delta=e.delta, x=1, y=1)
            return "break"

        def _up(e):
            self.w.event_generate("<Button-4>", x=1, y=1)
            return "break"

        def _down(e):
            self.w.event_generate("<Button-5>", x=1, y=1)
            return "break"

        widget.bind("<MouseWheel>", _wheel)
        widget.bind("<Button-4>", _up)      # Linux 向上
        widget.bind("<Button-5>", _down)    # Linux 向下

    def _current_anchor(self):
        """当前图片所处的链接：('wikilink', 笔记名) / ('extlink', url) / None"""
        for s in reversed(self._stack):
            if isinstance(s, tuple) and s[0] in ('wikilink', 'extlink'):
                return s
        return None

    def _image_hint(self, title, alt, anchor):
        """组装图片的悬浮提示文本，无内容时返回 None"""
        parts = []
        label = title or alt
        if label:
            parts.append(label)
        if anchor:
            kind, target = anchor
            if kind == 'extlink':
                parts.append(f"Ctrl+点击 打开：{target}")
            else:
                parts.append(f"点击跳转：{target}")
        return "　".join(parts) if parts else None

    def _activate_anchor(self, event, anchor):
        """点击带链接的图片：内部链接直接跳转，外部链接需 Ctrl+点击"""
        kind, target = anchor
        if kind == 'wikilink':
            if self.link_cb:
                self.link_cb(target)
        elif bool(event.state & 0x4):       # Ctrl 按下
            cb = getattr(self.w, "_extlink_cb", None)
            if cb:
                cb(target)

    def _resolve_image_path(self, src):
        """把 Markdown 中的图片地址解析为本地绝对路径，找不到返回 None"""
        if not src:
            return None
        src = unescape(src).strip().strip("\"'")
        # 网络图片不加载
        if not src or src.startswith(("http://", "https://",
                                     "data:", "ftp://")):
            return None
        # 去掉锚点与查询串
        for sep in ("#", "?"):
            if sep in src:
                src = src.split(sep)[0]
        if not src:
            return None
        raw = src.replace("\\", "/")
        rel = os.path.normpath(raw.lstrip("/")).replace("\\", os.sep)

        candidates = []
        base = getattr(self.w, "_base_dir", None)
        if base:
            candidates.append(os.path.join(base, rel))
        candidates.append(os.path.join(DATA_DIR, rel))
        if os.path.isabs(src):
            candidates.append(src)
        for path in candidates:
            try:
                if os.path.isfile(path):
                    return path
            except OSError:
                continue
        return None

    def _available_width(self):
        """Text 控件可用于图片/代码块的像素宽度（扣除内边距）"""
        return _available_width(self.w)

    def _pop_str(self, name):
        """从样式栈中移除指定名称的样式（最近一个）"""
        for i in range(len(self._stack) - 1, -1, -1):
            if isinstance(self._stack[i], str) and self._stack[i] == name:
                self._stack.pop(i)
                return

    def _clear_inline_stack(self):
        """清掉行内样式与旧标题样式，保留 quote 这类外层块级样式。

        块级元素相遇时用它代替 _stack.clear()：后者会把外层的 quote
        一并清掉且不恢复，使引用块中标题之后的内容失去引用样式。"""
        self._stack = [s for s in self._stack if s == 'quote']

    def _pop_anchor(self):
        """从样式栈中移除最近的 wikilink 或 extlink 样式"""
        for i in range(len(self._stack) - 1, -1, -1):
            s = self._stack[i]
            if (isinstance(s, tuple)
                    and s[0] in ('wikilink', 'extlink')):
                self._stack.pop(i)
                self._anchor_title = ""
                return

    def _render_table(self):
        """使用 ttk.Treeview 渲染图形化表格"""
        if not self._table_rows:
            return

        # 分离表头和数据行
        header_row = None
        data_rows = []
        for is_header, cells in self._table_rows:
            if is_header or header_row is None:
                header_row = cells
            else:
                data_rows.append(cells)

        if not header_row:
            self._table_rows = []
            return
        if not data_rows and len(self._table_rows) > 1:
            header_row = self._table_rows[0][1]
            data_rows = [r[1] for r in self._table_rows[1:]]

        col_count = len(header_row)

        # 列宽估算（上限 600，允许用户拖拽调整）
        def _pw(text):
            w = 0
            for ch in text:
                if ord(ch) < 128:
                    w += 9
                else:
                    w += 17
            return max(w, 40)

        col_widths = []
        all_cells = [header_row] + data_rows
        for i in range(col_count):
            max_w = 40
            for cells in all_cells:
                if i < len(cells):
                    max_w = max(max_w, _pw(cells[i]))
            col_widths.append(min(max_w + 24, 600))

        col_ids = [f"c{i}" for i in range(col_count)]
        row_count = len(data_rows) if data_rows else 1
        tree = ttk.Treeview(
            self.w, columns=col_ids, show="headings",
            height=min(row_count, 20),
        )

        for i, (col_id, title, width) in enumerate(zip(col_ids, header_row, col_widths)):
            tree.heading(col_id, text=title)
            # stretch=True 允许列宽随窗口调整，minwidth 保留拖拽缩小的下限
            tree.column(col_id, width=width, minwidth=60, anchor="w", stretch=True)

        rows = []           # [(行 iid, [单元格文本])]，供搜索使用
        for cells in data_rows:
            values = cells + [""] * (col_count - len(cells))
            iid = tree.insert("", "end", values=values[:col_count])
            rows.append((iid, values[:col_count]))

        if not data_rows:
            tree.insert("", "end", values=[""] * col_count)

        # Ctrl+C：鼠标所在格子精确复制（无选行时）或复制选中行
        def _copy_cell(e):
            sel = tree.selection()
            col = tree.identify_column(e.x)  # e.g. '#2'
            region = tree.identify_region(e.x, e.y)
            # 点在单元格上且该列有效 → 复制单格
            if region == "cell" and col and sel:
                col_idx = int(col.replace("#", "")) - 1
                values = tree.item(sel[0], "values")
                if col_idx < len(values):
                    tree.clipboard_clear()
                    tree.clipboard_append(str(values[col_idx]))
                    return
            # 否则复制整行
            if sel:
                values = tree.item(sel[0], "values")
                tree.clipboard_clear()
                tree.clipboard_append("\t".join(str(v) for v in values))
        tree.bind("<Control-c>", _copy_cell)
        tree.bind("<Control-C>", _copy_cell)

        # 右键菜单：复制当前单元格
        def _on_right_click(e):
            row = tree.identify_row(e.y)
            col = tree.identify_column(e.x)
            region = tree.identify_region(e.x, e.y)
            if row and col and region in ("cell", "heading"):
                # 选中该行并高亮
                tree.selection_set(row)
                tree.focus(row)
                tree.see(row)
                col_idx = int(col.replace("#", "")) - 1
                values = tree.item(row, "values")
                cell_text = str(values[col_idx]) if col_idx < len(values) else ""
                # 弹出菜单
                menu = tk.Menu(tree, tearoff=0)
                menu.add_command(
                    label=f"复制「{cell_text[:20]}{'…' if len(cell_text)>20 else ''}」",
                    command=lambda ct=cell_text: (
                        tree.clipboard_clear(),
                        tree.clipboard_append(ct)
                    ),
                )
                menu.post(e.x_root, e.y_root)
        tree.bind("<Button-3>", _on_right_click)
        # Linux 右键支持
        tree.bind("<Button-2>", _on_right_click)

        self._theme_treeview(tree)

        # 滚轮转发（与图片一致，交由内容区统一处理）
        self._bind_wheel_to_text(tree)

        self.w.insert("end", "\n")
        self.w.window_create("end", window=tree)
        # 记录表格窗口在主 Text 中的位置（end-1c 落在窗口后一个字符，
        # 比窗口索引多一列；消费方只取行号，详见代码块处的说明）
        pos = self.w.index("end-1c")
        self.w.insert("end", "\n")

        # 登记表格：Treeview 的文本同样不在主 Text 里，搜索时需单独查
        if not hasattr(self.w, "_md_tables"):
            self.w._md_tables = []
        self.w._md_tables.append(_TableRef(tree, pos, rows))

        self._table_rows = []

    def _theme_treeview(self, tree):
        """Treeview 配色与 Text 控件背景一致"""
        fs = max(9, self.fs - 1)
        try:
            text_bg = self.w.cget("bg")
            text_fg = self.w.cget("fg")
        except Exception:
            text_bg, text_fg = "#ffffff", "#212529"

        is_dark = _is_dark_color(text_bg)
        if is_dark:
            sel_bg, sel_fg = "#264f78", "#ffffff"
            head_bg, head_fg = "#3c3c3c", "#e0e0e0"
        else:
            sel_bg, sel_fg = "#cce8ff", "#333333"
            head_bg, head_fg = "#e8e8e8", "#333333"

        style = ttk.Style()
        sn = f"table_{id(tree)}.Treeview"
        style.configure(sn,
            background=text_bg, foreground=text_fg,
            fieldbackground=text_bg, borderwidth=0,
            lightcolor=text_bg, darkcolor=text_bg, bordercolor=text_bg,
            font=("Microsoft YaHei", fs), rowheight=28)
        style.map(sn,
            background=[("selected", sel_bg)],
            foreground=[("selected", sel_fg)])

        # 表头样式名必须与表格样式同源（X.Treeview → X.Treeview.Heading），
        # 否则 Tk 不会将其应用到该表格
        hn = f"table_{id(tree)}.Treeview.Heading"
        # clam 主题下表头立体边框由 lightcolor/darkcolor 绘制，
        # 只设 background 会让深色主题下仍残留浅色边框
        style.configure(hn,
            background=head_bg, foreground=head_fg,
            lightcolor=head_bg, darkcolor=head_bg, bordercolor=head_bg,
            font=("Microsoft YaHei", fs, "bold"),
            relief="flat", borderwidth=0, padding=(8, 4))
        style.map(hn,
            background=[("active", head_bg)],
            lightcolor=[("active", head_bg)],
            darkcolor=[("active", head_bg)])
        tree.configure(style=sn)



# ══════════════════════════════════
# 辅助函数
# ══════════════════════════════════

def _available_width(text_widget):
    """Text 控件可用于嵌入内容的像素宽度（扣除内边距）"""
    try:
        width = text_widget.winfo_width()
    except tk.TclError:
        width = 0
    if width <= 1:          # 尚未完成布局，用近似值兜底
        return 720
    try:
        pad = int(text_widget.cget("padx")) * 2
    except (tk.TclError, ValueError):
        pad = 40
    return max(120, width - pad - 8)


def _bind_code_resize(text_widget):
    """主 Text 宽度变化时同步所有代码块宽度（整个控件生命周期只绑一次）"""
    if getattr(text_widget, "_code_resize_bound", False):
        return

    def _on_configure(event=None):
        holders = getattr(text_widget, "_md_code_blocks", [])
        if not holders:
            return
        avail = _available_width(text_widget)
        # Configure 触发非常频繁，宽度没实质变化就直接跳过
        if abs(avail - getattr(text_widget, "_code_last_width", -1)) < 4:
            return
        text_widget._code_last_width = avail
        for holder in list(holders):
            try:
                holder._code_resize(avail)
            except Exception:
                pass

    text_widget.bind("<Configure>", _on_configure, add="+")
    text_widget._code_resize_bound = True


def find_all_hits(text_widget, keyword, start="1.0", stop=None):
    """在正文与代码块中查找关键词，返回按文档顺序排列的命中列表。

    代码块文本位于嵌入的子 Text 中，主 Text 的 search() 覆盖不到
    （表格同理），必须单独查询后再按位置合并排序。

    每项为：
        ('text', index)                      —— 正文命中
        ('code', body, body_index, position) —— 代码块命中
        ('table', tree, iid, row, col, position) —— 表格命中
        （position 是该嵌入控件在主 Text 中的位置，供排序与滚动定位）
    """
    if not keyword:
        return []
    if stop is None:
        stop = tk.END

    kw = keyword.lower()
    hits = []

    # ① 正文
    pos = start
    while True:
        try:
            pos = text_widget.search(keyword, pos, nocase=True,
                                     stopindex=stop)
        except tk.TclError:
            break
        if not pos:
            break
        hits.append(('text', pos))
        pos = f"{pos}+1c"

    # ② 代码块（块内按出现顺序追加，排序是稳定排序）
    for holder in list(getattr(text_widget, "_md_code_blocks", [])):
        body = getattr(holder, "_code_body", None)
        if body is None:
            continue
        bpos = "1.0"
        while True:
            try:
                bpos = body.search(keyword, bpos, nocase=True,
                                   stopindex="end")
            except tk.TclError:
                break
            if not bpos:
                break
            hits.append(('code', body, bpos,
                         getattr(holder, "_code_index", "1.0")))
            bpos = f"{bpos}+1c"

    # ③ 表格（Treeview 的单元格文本搜不到，只能逐格匹配）
    for ref in list(getattr(text_widget, "_md_tables", [])):
        for row_no, (iid, cells) in enumerate(ref.rows, 1):
            for col_no, cell in enumerate(cells, 1):
                text = str(cell)
                if not text:
                    continue
                cells_l = text.lower()
                at = cells_l.find(kw)
                while at != -1:
                    hits.append(('table', ref.tree, iid, row_no, col_no,
                                 ref.position))
                    at = cells_l.find(kw, at + 1)

    def _order(item):
        """排序键：(主 Text 行, 列, 类型序, 控件内位置)"""
        if item[0] == 'text':
            idx, sub = item[1], (0, 0)
        elif item[0] == 'code':
            idx = item[3]
            bl, _, bc = str(item[2]).partition(".")
            try:
                sub = (1, int(bl) * 100000 + int(bc))
            except ValueError:
                sub = (1, 0)
        else:
            idx = item[5]
            sub = (2, item[3] * 1000 + item[4])
        line, _, col = str(idx).partition(".")
        try:
            return (int(line), int(col)) + sub
        except ValueError:
            return (0, 0) + sub

    hits.sort(key=_order)
    return hits


def _pyg_style(dark):
    """取 Pygments 配色方案（亮/暗各一套，取不到返回 None → 不高亮）"""
    key = "dark" if dark else "light"
    if key not in _pyg_style_cache:
        st = None
        if _HAS_PYGMENTS:
            try:
                st = _pyg_get_style(
                    _PYG_STYLE_DARK if dark else _PYG_STYLE_LIGHT)
            except Exception:
                st = None
        _pyg_style_cache[key] = st
    return _pyg_style_cache[key]


def _pyg_token_style(style, ttype, cache):
    """取 token 的（颜色, 粗体, 斜体）；只接受 #rrggbb 形式的颜色"""
    if style is None:
        return (None, False, False)
    if ttype in cache:
        return cache[ttype]
    color, bold, italic = None, False, False
    try:
        d = style.style_for_token(ttype) or {}
        c = d.get("color")
        # Pygments 返回的颜色不带 #（如 '0000ff'），统一补成 #rrggbb
        if isinstance(c, str):
            c = c.strip()
            if len(c) == 7 and c.startswith("#"):
                color = c
            elif len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c):
                color = "#" + c
        bold = bool(d.get("bold"))
        italic = bool(d.get("italic"))
    except Exception:
        pass
    cache[ttype] = (color, bold, italic)
    return cache[ttype]


def _is_dark_color(hex_color):
    """判断一个颜色是否为暗色（用于自动检测深色主题）"""
    if not hex_color or not hex_color.startswith("#"):
        return False
    try:
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        # 亮度公式 (YIQ)
        return (r * 299 + g * 587 + b * 114) / 1000 < 128
    except Exception:
        return False


def _cleanup_dynamic_tags(text_widget):
    """删除上一次渲染残留的动态 wikilink/extlink 标签，防止主题切换后颜色错乱"""
    for tag in list(text_widget.tag_names()):
        if tag.startswith("wikilink_") or tag.startswith("extlink_"):
            text_widget.tag_delete(tag)
    text_widget._extlink_map = {}
    text_widget._wikilink_map = {}


# ══════════════════════════════════
# Text 标签样式配置
# ══════════════════════════════════

def _configure_tags_with_size(text_widget, base_size=11):
    """配置 Text 控件中使用的各种格式标签（自动适配亮/暗主题）"""
    try:
        bg = text_widget.cget("bg")
        fg = text_widget.cget("fg")
    except Exception:
        bg, fg = "#ffffff", "#212529"

    dark = _is_dark_color(bg)

    if dark:
        # ── 暗色主题 ──
        h1_fg, h2_fg, h3_fg = "#e8e8e8", "#dcdcdc", "#d0d0d0"
        h4_fg = "#c0c0c0"
        code_bg, code_fg = "#2d2d2d", "#d4d4d4"
        quote_bg, quote_fg = "#252526", "#999999"
        hr_fg = "#555555"
        inline_code_bg, inline_code_fg = "#3c3c3c", "#f48771"
    else:
        # ── 亮色主题 ──
        h1_fg, h2_fg, h3_fg = "#1a1a2e", "#16213e", "#0f3460"
        h4_fg = "#333333"
        code_bg, code_fg = "#f0f0f0", "#333333"
        quote_bg, quote_fg = "#f8f8f8", "#666666"
        hr_fg = "#cccccc"
        inline_code_bg, inline_code_fg = "#f0f0f0", "#c7254e"

    # ── 标题（不加前景色，继承 Text 默认 fg 与主题一致）──
    text_widget.tag_configure("heading1",
        font=("Microsoft YaHei", base_size + 7, "bold"),
        foreground=h1_fg, spacing1=12, spacing3=6)
    text_widget.tag_configure("heading2",
        font=("Microsoft YaHei", base_size + 4, "bold"),
        foreground=h2_fg, spacing1=10, spacing3=4)
    text_widget.tag_configure("heading3",
        font=("Microsoft YaHei", base_size + 2, "bold"),
        foreground=h3_fg, spacing1=8, spacing3=4)
    text_widget.tag_configure("heading4",
        font=("Microsoft YaHei", base_size + 1, "bold"),
        foreground=h4_fg, spacing1=6, spacing3=2)
    text_widget.tag_configure("heading5",
        font=("Microsoft YaHei", base_size, "bold"),
        foreground=h4_fg, spacing1=4, spacing3=2)
    text_widget.tag_configure("heading6",
        font=("Microsoft YaHei", base_size, "bold"),
        foreground=h4_fg, spacing1=4, spacing3=2)

    # 代码块
    text_widget.tag_configure("code_block",
        font=("Consolas", base_size - 1),
        background=code_bg, foreground=code_fg,
        spacing1=4, spacing3=4,
        lmargin1=16, lmargin2=16)

    # 引用
    text_widget.tag_configure("quote",
        font=("Microsoft YaHei", base_size, "italic"),
        foreground=quote_fg, background=quote_bg,
        lmargin1=16, lmargin2=16,
        spacing1=2, spacing3=2)

    # 分隔线
    text_widget.tag_configure("hr", foreground=hr_fg)

    # 行内格式（显式设前景色，防止继承意外颜色）
    text_widget.tag_configure("bold",
        font=("Microsoft YaHei", base_size, "bold"),
        foreground=fg)
    text_widget.tag_configure("italic",
        font=("Microsoft YaHei", base_size, "italic"),
        foreground=fg)
    text_widget.tag_configure("bold_italic",
        font=("Microsoft YaHei", base_size, "bold italic"),
        foreground=fg)
    text_widget.tag_configure("code_inline",
        font=("Consolas", base_size - 1),
        background=inline_code_bg, foreground=inline_code_fg)
    text_widget.tag_configure("strikethrough",
        font=("Microsoft YaHei", base_size, "overstrike"),
        foreground=fg)

    # 图片占位提示（图片缺失或无法读取时显示）
    text_widget.tag_configure("img_placeholder",
        font=("Microsoft YaHei", max(9, base_size - 1), "italic"),
        foreground="#888888" if dark else "#999999",
        lmargin1=4, lmargin2=4)
