"""
IndeXar 内容区

笔记正文的渲染与交互：Markdown 渲染、内部/外部链接点击、正文悬停高亮、
反向链接面板、内容区右键菜单、标题栏文件名与关闭按钮。
"""

import os
import tkinter as tk
from tkinter import ttk

import icon_renderer
from context_menu import ContextMenu
from file_handler import get_backlinks, find_note_by_name, read_note
from markdown_renderer import render_markdown
from ui.common import _blend_hex, _readable_fg, SEARCH_HIT_ALPHA, \
    SEARCH_HIT_COLOR


class ContentViewMixin:
    """内容区渲染与交互"""

    def _render_backlinks(self, rel_path):
        """在内容底部使用 Text tag 渲染百科风格反向链接框"""
        from file_handler import get_backlinks

        name = rel_path.split("/")[-1]
        backlinks = get_backlinks(name)
        if not backlinks:
            return

        c = self.colors
        is_dark = self.theme_mode == "dark"
        fs = max(9, self._font_size - 1)

        # ── 配色 ──
        border = "#b8d4ec" if not is_dark else "#3a5068"
        header_bg = "#d4e8f8" if not is_dark else "#203a50"
        header_fg = "#1a5276" if not is_dark else "#7ab8f5"
        box_bg = "#eaf4fb" if not is_dark else "#1a2d40"
        link_fg = "#2a6e9e" if not is_dark else "#5ba4d6"
        content_fg = c["content_fg"]

        # ── 配置 tag ──
        self.content_text.tag_configure("bl_top",
            foreground=border, font=("Microsoft YaHei", 1),
            spacing1=10, spacing3=0)
        self.content_text.tag_configure("bl_header",
            background=header_bg, foreground=header_fg,
            font=("Microsoft YaHei", fs, "bold"),
            lmargin1=14, lmargin2=14, spacing1=5, spacing3=4)
        self.content_text.tag_configure("bl_body",
            background=box_bg, foreground=content_fg,
            font=("Microsoft YaHei", fs),
            lmargin1=14, lmargin2=14)
        self.content_text.tag_configure("bl_bottom",
            background=box_bg, font=("Microsoft YaHei", 1),
            lmargin1=14, lmargin2=14, spacing3=6)

        self.content_text.configure(state=tk.NORMAL)

        # ── 顶部边框线 ──
        self.content_text.insert("end", "\n", "bl_top")

        # ── 标题行 ──
        count = len(backlinks)
        self.content_text.insert("end", f"  被以下笔记引用 ({count})\n",
                                 "bl_header")

        # ── 链接项横向排列 ──
        # 先插入前缀和第一个链接
        self.content_text.insert("end", "  ", "bl_body")
        for i, source_path in enumerate(backlinks):
            source_name = source_path.split("/")[-1]
            click_tag = f"bl_{source_path}"

            # 分隔符（除第一个外）
            if i > 0:
                self.content_text.insert("end", " │ ", "bl_body")

            # 链接文字
            start = self.content_text.index("end-1c")
            self.content_text.insert("end", source_name, "bl_body")
            end = self.content_text.index("end-1c")

            # 打上点击标签
            self.content_text.tag_add(click_tag, start, end)
            self.content_text.tag_configure(click_tag,
                foreground=link_fg, underline=True,
                font=("Microsoft YaHei", fs))
            self.content_text.tag_bind(click_tag, "<Button-1>",
                lambda e, p=source_path: self._display_note(p))

        self.content_text.insert("end", "\n", "bl_body")

        # ── 底部收尾 ──
        self.content_text.insert("end", "\n", "bl_bottom")


    # ── 内容区 ──

    def _build_content_area(self, parent):
        """内容展示区（头部含文件名+搜索+主题切换）"""
        self.content_body = tk.Frame(parent)
        self.content_body.grid(row=0, column=3, sticky="nsew")

        # ── 内容头部：文件名 | 搜索 + 主题切换 ──
        self.content_header = tk.Frame(self.content_body)
        self.content_header.pack(fill=tk.X)

        # 左侧：文件名/欢迎语
        self.content_title = tk.Label(
            self.content_header,
            text="   选择一篇笔记开始阅读",
            font=("Microsoft YaHei", 10),
            anchor=tk.W, padx=14, pady=6,
        )
        self.content_title.pack(side=tk.LEFT)

        # 关闭按钮（浏览文件时出现）
        self._close_file_btn = tk.Label(
            self.content_header, text="✕",
            font=("Microsoft YaHei", 11),
            cursor="hand2", padx=2,
        )
        self._close_file_btn.bind("<Button-1>", lambda e: self._close_file())
        self._close_file_btn.bind("<Enter>", lambda e: e.widget.configure(fg="#e81123"))
        self._close_file_btn.bind("<Leave>", lambda e: e.widget.configure(fg="#888"))
        self._close_file_btn.configure(fg="#888")

        # 右侧：搜索 + 主题（先 pack RIGHT 确保不被推出）
        self._header_right = tk.Frame(self.content_header)
        self._header_right.pack(side=tk.RIGHT, padx=(0, 10))

        # 分隔线（紧贴搜索区左侧）
        self._header_sep = tk.Label(
            self.content_header, text="│",
            font=("Microsoft YaHei", 10),
            padx=6, pady=6,
        )
        self._header_sep.pack(side=tk.RIGHT)

        self.search_var = tk.StringVar()
        # 内容变化时：控制清空按钮显隐；清空则恢复文件树
        self.search_var.trace_add("write",
                                  lambda *a: self._on_search_var_changed())
        self.search_entry = tk.Entry(
            self._header_right,
            textvariable=self.search_var,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            width=20,
        )
        self.search_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        # 清空按钮：仅在有输入时显示，位于搜索按钮左侧
        self.search_clear_lbl = tk.Label(
            self._header_right, text="✕",
            font=("Microsoft YaHei", 9),
            cursor="hand2", padx=3,
        )
        self.search_clear_lbl.bind("<Button-1>",
                                   lambda e: self._clear_search())
        self.search_clear_lbl.bind("<Enter>", lambda e: (
            self.search_clear_lbl.configure(fg="#e81123")))
        self.search_clear_lbl.bind("<Leave>", lambda e: (
            self.search_clear_lbl.configure(fg=self.colors["toolbar_fg"])))

        self.search_btn = tk.Button(
            self._header_right, text="搜索",
            font=("Microsoft YaHei", 9),
            relief=tk.RIDGE, bd=1, highlightthickness=0,
            padx=8, pady=1, cursor="hand2",
            command=self._do_search,
        )
        self.search_btn.pack(side=tk.LEFT, padx=(0, 4))

        # 外部编辑器按钮
        self.edit_btn = tk.Button(
            self._header_right, text="编辑",
            font=("Microsoft YaHei", 9),
            relief=tk.RIDGE, bd=1, highlightthickness=0,
            padx=6, pady=1, cursor="hand2",
            command=self._open_current_in_editor,
        )
        self.edit_btn.pack(side=tk.LEFT, padx=(0, 8))

        # 主题切换
        self.theme_frame = tk.Frame(self._header_right, cursor="hand2")
        self.theme_frame.pack(side=tk.LEFT)

        self._theme_sun_img = icon_renderer.sun_icon(self.colors["toolbar_fg"])
        self._theme_moon_img = icon_renderer.moon_icon(self.colors["nav_fg"])

        self.theme_light_lbl = tk.Label(
            self.theme_frame, image=self._theme_sun_img,
            cursor="hand2", padx=4, pady=2,
        )
        self.theme_light_lbl.pack(side=tk.LEFT)

        self.theme_dark_lbl = tk.Label(
            self.theme_frame, image=self._theme_moon_img,
            cursor="hand2", padx=4, pady=2,
        )
        self.theme_dark_lbl.pack(side=tk.LEFT)

        self.theme_frame.bind("<Button-1>", lambda e: self._toggle_theme())
        self.theme_light_lbl.bind("<Button-1>", lambda e: self._toggle_theme())
        self.theme_dark_lbl.bind("<Button-1>", lambda e: self._toggle_theme())

        # ── header 宽度变化时自动截断文件名 ──
        self.content_header.bind("<Configure>", self._on_header_resize)

        # ── 文本内容区 ──

        self.text_container = tk.Frame(self.content_body)
        self.text_container.pack(fill=tk.BOTH, expand=True)

        # 垂直滚动条固定在右侧
        self.content_scroll = ttk.Scrollbar(
            self.text_container, orient=tk.VERTICAL,
        )
        self.content_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 文本与水平滚动条的容器（让水平条只占文本宽度，
        # 不延伸到垂直滚动条下方）
        self.text_area = tk.Frame(self.text_container)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.content_text = tk.Text(
            self.text_area,
            wrap=tk.WORD,
            font=("Microsoft YaHei", 11),
            padx=20, pady=16,
            relief=tk.FLAT, highlightthickness=0,
            borderwidth=0, insertwidth=2,
            cursor="",  # 只读内容区默认箭头，链接处才变手型
        )
        self.content_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 水平滚动条：仅当内容（表格/图片）超出可视宽度时显示
        self.content_hscroll = ttk.Scrollbar(
            self.text_area, orient=tk.HORIZONTAL)

        self.content_scroll.configure(command=self.content_text.yview)
        self.content_text.configure(yscrollcommand=self.content_scroll.set)
        self.content_hscroll.configure(command=self.content_text.xview)
        self.content_text.configure(xscrollcommand=self.content_hscroll.set)
        self.content_text.configure(state=tk.DISABLED)

        # 滚轮：按像素滚动。Text 默认按「行」滚动，而图片所在行的高度
        # 等于图片高度，滚一格会直接跳过整张图，观感像“突然加速”
        self._wheel_accum = 0
        self.content_text.bind("<MouseWheel>", self._on_content_wheel)
        self.content_text.bind("<Button-4>", self._on_content_wheel_up)
        self.content_text.bind("<Button-5>", self._on_content_wheel_down)

        # 尺寸变化时同步水平滚动条显隐
        self.content_text.bind("<Configure>",
                               lambda e: self._sync_hscroll())

        # 内容区右键菜单
        self._build_content_context_menu()

    def _on_content_wheel(self, event):
        """内容区滚轮：按像素滚动，跨越大图片时不会突然跳跃"""
        # 高精度滚轮（触控板）单次 delta 可能小于 120，先累加再滚动
        self._wheel_accum += event.delta
        steps = int(self._wheel_accum / 120)
        if steps:
            self._wheel_accum -= steps * 120
            self.content_text.yview_scroll(-steps * 60, "pixels")
        return "break"

    def _on_content_wheel_up(self, event):
        """Linux 滚轮向上"""
        self.content_text.yview_scroll(-60, "pixels")
        return "break"

    def _on_content_wheel_down(self, event):
        """Linux 滚轮向下"""
        self.content_text.yview_scroll(60, "pixels")
        return "break"

    def _sync_hscroll(self):
        """内容（表格/图片）超出可视宽度时才显示水平滚动条"""
        try:
            if self.content_text.xview()[1] < 1.0:
                self.content_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
            else:
                self.content_hscroll.pack_forget()
        except tk.TclError:
            pass

    # ── 内容区右键菜单 ──

    def _build_content_context_menu(self):
        """内容区右键菜单"""
        self.content_menu = ContextMenu(self.root, colors=self._get_menu_colors())
        self.content_text.bind("<Button-3>", self._show_content_context_menu)

    def _show_content_context_menu(self, event):
        """内容区右键 → 显示菜单"""
        items = [
            ("复制", self._copy_selected_text),
            ("全选", self._select_all_text),
        ]
        self.content_menu.show(
            event.x_root, event.y_root, items,
            colors_override=self._get_menu_colors(),
            use_grab=False)

    def _copy_selected_text(self):
        """复制选中文本到剪贴板"""
        try:
            text = self.content_text.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass  # 无选中内容

    def _select_all_text(self):
        """全选内容区文本（临时启用编辑）"""
        self.content_text.configure(state=tk.NORMAL)
        self.content_text.tag_add(tk.SEL, "1.0", tk.END)
        self.content_text.mark_set(tk.INSERT, tk.END)
        self.content_text.see(tk.INSERT)
        self.content_text.configure(state=tk.DISABLED)


    def _display_note(self, rel_path):
        content = read_note(rel_path)
        if content is None:
            self._set_content(f"⚠️  找不到文件：{rel_path}.md")
            return
        self._current_note_path = rel_path
        name = rel_path.split("/")[-1]
        self._full_display_name = f"   📄 {name}.md"
        self._update_title_display()
        self._close_file_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._render_markdown(content)
        self._render_backlinks(rel_path)
        self.content_text.configure(state=tk.DISABLED)
        self.status_left.configure(text=f"   当前：{rel_path}.md")
        self._refresh_file_tags()
        # 布局完成后判断内容是否超宽（表格/图片）
        self.root.after_idle(self._sync_hscroll)

    def _render_markdown(self, md_text):
        from markdown_renderer import render_markdown
        self.content_text.configure(state=tk.NORMAL)
        # 先让控件完成布局，图片「适应宽度」才能按实际宽度计算
        try:
            self.content_text.update_idletasks()
        except tk.TclError:
            pass
        render_markdown(self.content_text, md_text,
                         link_callback=self._navigate_to_link,
                         font_size=self._font_size,
                         base_dir=self._current_note_dir(),
                         image_mode=getattr(self, "_image_mode", "fit"),
                         hover_callback=self._show_status_hint,
                         extlink_callback=self._open_external_url)

    def _current_note_dir(self):
        """当前笔记所在目录的绝对路径（供图片相对路径解析）"""
        from file_handler import DATA_DIR
        rel = getattr(self, "_current_note_path", None)
        if not rel:
            return DATA_DIR
        parent = os.path.dirname(rel)
        if not parent:
            return DATA_DIR
        return os.path.join(DATA_DIR, parent.replace("/", os.sep))

    def _on_content_click(self, event):
        """内容区点击——内部链接直接跳转；外部链接需 Ctrl+点击"""
        try:
            pos = self.content_text.index(f"@{event.x},{event.y}")
            ctrl_down = bool(event.state & 0x4)
            for tag in self.content_text.tag_names(pos):
                if tag.startswith("wikilink_"):
                    self._navigate_to_link(tag[9:])
                    return
                if tag.startswith("extlink_") and ctrl_down:
                    url = getattr(self.content_text,
                                  "_extlink_map", {}).get(tag)
                    if url:
                        self._open_external_url(url)
                    return
        except Exception:
            pass

    def _open_external_url(self, url):
        """用系统默认浏览器打开外部网址"""
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def _show_status_hint(self, text):
        """在状态栏显示临时提示；text 为 None 时恢复原文本"""
        if text is None:
            self._clear_extlink_hint()
            return
        if not getattr(self, '_hint_saved_status', False):
            self._hint_saved_status = True
            self._hint_prev_text = self.status_left.cget("text")
        self.status_left.configure(text=f"   {text}")

    def _set_extlink_hint(self, url):
        """进入外部链接时在状态栏显示操作提示"""
        self._show_status_hint(f"Ctrl+点击 打开：{url}")

    def _clear_extlink_hint(self):
        """离开外部链接时恢复状态栏"""
        if getattr(self, '_hint_saved_status', False):
            self._hint_saved_status = False
            self.status_left.configure(text=self._hint_prev_text)

    def _on_content_motion(self, event):
        """内容区鼠标移动——链接上手型光标 + 高亮（仅当前 tag）"""
        try:
            pos = self.content_text.index(f"@{event.x},{event.y}")
            tags = self.content_text.tag_names(pos)
            link_tags = [t for t in tags
                         if t.startswith(("wikilink_", "extlink_"))]

            hover_bg = "#d6e4f0" if self.theme_mode == "light" else "#2a4a6b"

            # 离开上一个链接 → 还原其背景与状态栏
            prev = getattr(self, '_hovered_tag', None)
            if prev and prev != (link_tags[0] if link_tags else None):
                try:
                    self.content_text.tag_configure(prev, background="")
                except Exception:
                    pass
                self._hovered_tag = None
                self._clear_extlink_hint()

            # 进入新链接
            if link_tags:
                tag = link_tags[0]
                if not getattr(self, '_link_hover', False):
                    self._link_hover = True
                    self.content_text.config(cursor="hand2")
                self.content_text.tag_configure(tag, background=hover_bg)
                self._hovered_tag = tag
                if tag.startswith("extlink_"):
                    url = getattr(self.content_text,
                                  "_extlink_map", {}).get(tag)
                    if url:
                        self._set_extlink_hint(url)
                    else:
                        self._clear_extlink_hint()
            else:
                if getattr(self, '_link_hover', False):
                    self._link_hover = False
                    self.content_text.config(cursor="")
                self._clear_extlink_hint()
        except Exception:
            pass

    def _navigate_to_link(self, target_name):
        """点击 [[内部链接]] 时跳转到对应笔记"""
        from file_handler import find_note_by_name
        # 兼容 [[文件.md]] 和 [[文件]] 两种写法
        target_name = target_name.replace(".md", "")
        path = find_note_by_name(target_name)
        if path:
            self._display_note(path)
            # 同步选中文件树对应节点
            try:
                self.tree.selection_set(f"f:{path}")
                self.tree.see(f"f:{path}")
            except Exception:
                pass
        else:
            self.status_left.configure(
                text=f"  未找到笔记：{target_name}")
            self._set_content(
                f"⚠️  未找到笔记「{target_name}」\n\n"
                f"请确认 data/ 目录下是否存在该名称的 .md 文件。"
            )

    def _update_title_display(self, event=None):
        """根据 header 可用宽度动态截断文件名"""
        full = getattr(self, '_full_display_name', None)
        if not full:
            return
        # 估算可用宽度：header 宽度 - 右侧搜索区 (~380px) - 间距
        avail = self.content_header.winfo_width() - 400
        ch_w = 9  # 中文约 17px, 英文约 9px, 粗略取 10
        max_ch = max(10, avail // ch_w)
        if len(full) <= max_ch:
            self.content_title.configure(text=full)
        else:
            self.content_title.configure(text=full[:max_ch-3] + "...")

    def _on_header_resize(self, event):
        self._update_title_display()

    def _close_file(self):
        """关闭当前浏览的文件，回到欢迎页"""
        self._current_note_path = None
        self._full_display_name = None
        self._close_file_btn.pack_forget()
        self._refresh_file_tags()
        self.content_title.configure(text="   选择一篇笔记开始阅读")
        self.content_text.configure(state=tk.NORMAL)
        self.content_text.delete(1.0, tk.END)
        self.content_text.configure(state=tk.DISABLED)
        self.status_left.configure(text="   就绪")

    def _set_content(self, text):
        self._current_note_path = None
        self._close_file_btn.pack_forget()
        self._refresh_file_tags()
        self.content_title.configure(text="   选择一篇笔记开始阅读")
        self.content_text.configure(state=tk.NORMAL)
        self.content_text.delete(1.0, tk.END)
        self.content_text.insert(tk.END, text)
        self.content_text.configure(state=tk.DISABLED)
        self.root.after_idle(self._sync_hscroll)

    # ══════════════════════════════════
    # 搜索
