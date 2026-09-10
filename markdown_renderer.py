"""
IndeXar Markdown 渲染器
使用 markdown 库将 Markdown 转为 HTML，再解析 HTML 在 Tkinter Text 控件中渲染
"""

import os
import re
from html.parser import HTMLParser
from html import unescape

import tkinter as tk
from tkinter import ttk

import markdown


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

    # 清理上一次渲染留下的动态链接标签，防止颜色残留
    _cleanup_dynamic_tags(text_widget)
    # 重置外链映射，并依背景预计算外链颜色
    text_widget._extlink_map = {}
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

    # 使用 markdown 库转换为 HTML（extra 扩展支持表格、脚注、围栏代码块等）
    html = markdown.markdown(md_text, extensions=['extra'])

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

def _looks_like_note_target(href):
    """判断非协议链接是否指向站内笔记：结尾为 .md，或整段没有扩展名"""
    h = (href or "").split("#")[0].split("?")[0].strip()
    if not h or h.startswith(("#", "mailto:", "javascript:", "data:")):
        return False
    tail = h.replace("\\", "/").rstrip("/").split("/")[-1]
    if not tail:
        return False
    if "." not in tail:
        return True
    return tail.lower().endswith(".md")


def _note_name_from_href(href):
    """从链接地址中取出笔记名：./a/b.md → b"""
    h = (href or "").split("#")[0].split("?")[0]
    tail = h.replace("\\", "/").rstrip("/").split("/")[-1]
    return re.sub(r"\.md$", "", tail, flags=re.I)


def _preprocess_wikilinks(text):
    """将 [[target]] 和 [[target|display]] 转为标准 Markdown 链接，
       使用 wikilink: 协议前缀标记内部链接，供后续渲染时识别。"""
    # 先保护已存在的标准链接和图片语法，避免误匹配
    def _replace(m):
        target = m.group(1).strip()
        display = m.group(2).strip() if m.group(2) else target
        return f'[{display}](wikilink:{target})'

    return re.sub(r'\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]', _replace, text)


# ══════════════════════════════════
# HTML → Text 渲染器
# ══════════════════════════════════

class _MarkdownHTMLRenderer(HTMLParser):
    """将 markdown 库生成的 HTML 渲染到 Tkinter Text 控件。"""

    def __init__(self, text_widget, link_callback, font_size):
        super().__init__()
        self.w = text_widget
        self.link_cb = link_callback
        self.fs = font_size

        # 行内样式栈：元素为 'bold'|'italic'|'code_inline'|('wikilink', target)|('extlink', url)
        self._stack = []
        self._ext_idx = 0  # 外部链接动态 tag 计数器

        # ── 代码块状态 ──
        self._in_pre = False
        self._code_buf = []

        # ── 列表状态 ──
        self._list_depth = 0      # 嵌套深度
        self._ol_counters = []    # 每层有序列表计数器

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
            return
        if self._in_pre:
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
            self._anchor_title = a.get('title', '')
            if href.startswith('wikilink:'):
                self._stack.append(('wikilink', href[9:]))
            elif href.startswith(('http://', 'https://')):
                self._stack.append(('extlink', href))
            elif _looks_like_note_target(href):
                # 非协议链接：形如 [文字](笔记名) 或 [文字](./笔记.md)，
                # 与 [[笔记名]] 走同一套跳转逻辑
                self._stack.append(('wikilink', _note_name_from_href(href)))

        # ── 块级元素 ──（先清栈确保无残留 tag）
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._stack.clear()
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
            self._list_depth += 1
            if tag == 'ol':
                if len(self._ol_counters) < self._list_depth:
                    self._ol_counters.append(1)
                else:
                    self._ol_counters[self._list_depth - 1] = 1
        elif tag == 'li':
            self._insert(self._list_bullet())

    def _list_bullet(self):
        """返回当前列表深度的项目符号"""
        indent = "  " * (self._list_depth - 1)
        # 检查当前最内层是否为有序列表
        if self._list_depth > 0 and len(self._ol_counters) >= self._list_depth:
            num = self._ol_counters[self._list_depth - 1]
            self._ol_counters[self._list_depth - 1] += 1
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
                    code = '\n'.join(self._code_buf)
                    self.w.insert('end', code, 'code_block')
                    # 换行不带 code_block 标签，防止背景色泄露到下行
                    self.w.insert('end', '\n')
                    self._code_buf = []
            return

        # ── 表格结束 ──
        if tag == 'table':
            self._in_table = False
            self._stack.clear()  # 安全清栈，防止表格内残留样式泄露
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
            self._insert('\n')
        elif tag in ('ul', 'ol'):
            self._list_depth = max(0, self._list_depth - 1)

    # ── 文本数据 ──

    def handle_data(self, data):
        # 代码块内：原样收集
        if self._in_pre:
            self._code_buf.append(data)
            return

        # 表格单元格内：累积文本（跨行内标签合并为一个单元格）
        if self._in_table:
            self._current_cell += unescape(data)
            return

        # 普通文本：渲染
        self._insert(unescape(data))

    # ── 辅助函数 ──

    def _insert(self, text, extra_tags=()):
        """向 Text 控件插入文本，应用当前样式栈中所有标签"""
        tags = list(extra_tags)
        for s in self._stack:
            if isinstance(s, tuple) and s[0] == 'wikilink':
                tag_name = f'wikilink_{s[1]}'
                tags.append(tag_name)
                # 确保 wikilink 标签已配置
                try:
                    self.w.tag_configure(tag_name)
                except Exception:
                    self.w.tag_configure(tag_name,
                        foreground="#569cd6", underline=True,
                        font=("Microsoft YaHei", self.fs))
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

        if tags:
            self.w.insert('end', text, tuple(tags))
        else:
            self.w.insert('end', text)

    # ── 图片 ──

    def _insert_image(self, src, alt, title=""):
        """插入图片：按 _image_mode 决定「适应宽度」或「原始尺寸」"""
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
        self._insert("\n")

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
        from file_handler import DATA_DIR
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
        """Text 控件可用于图片的像素宽度（扣除内边距）"""
        try:
            width = self.w.winfo_width()
        except tk.TclError:
            width = 0
        if width <= 1:          # 尚未完成布局，用近似值兜底
            return 720
        try:
            pad = int(self.w.cget("padx")) * 2
        except (tk.TclError, ValueError):
            pad = 40
        return max(120, width - pad - 8)

    def _pop_str(self, name):
        """从样式栈中移除指定名称的样式（最近一个）"""
        for i in range(len(self._stack) - 1, -1, -1):
            if isinstance(self._stack[i], str) and self._stack[i] == name:
                self._stack.pop(i)
                return

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

        for cells in data_rows:
            values = cells + [""] * (col_count - len(cells))
            tree.insert("", "end", values=values[:col_count])

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
        self.w.insert("end", "\n")

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
