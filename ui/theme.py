"""
IndeXar 主题应用

亮/暗主题切换、全界面配色刷新（控件、Treeview、内容区 tag 样式）、
跟随系统主题设置，以及主题切换图标的更新。
"""

import tkinter as tk
from tkinter import ttk

import icon_renderer
from theme_manager import VSCodeTheme


class ThemeMixin:
    """主题切换与应用"""

    def _toggle_theme(self):
        """切换亮/暗主题"""
        self.theme_mode = "dark" if self.theme_mode == "light" else "light"
        self._theme_overridden = True
        self._save_settings()
        self.colors = VSCodeTheme.get(self.theme_mode)

        # 保存展开状态
        expanded = set()
        def _collect(parent=""):
            for child in self.tree.get_children(parent):
                if self.tree.item(child, "open"):
                    vals = self.tree.item(child, "values")
                    if vals:
                        expanded.add(vals[0])
                _collect(child)
        _collect()

        self._apply_theme()

        if self.current_panel == "files":
            self._refresh_file_tree()
            # 恢复展开状态
            def _restore(parent=""):
                for child in self.tree.get_children(parent):
                    vals = self.tree.item(child, "values")
                    if vals and vals[0] in expanded:
                        self.tree.item(child, open=True)
                    _restore(child)
            _restore()

        # 重新渲染当前笔记（表格/图片等内嵌控件需要按新主题重建）
        if self._current_note_path:
            self._display_note(self._current_note_path)

    def _update_theme_toggle(self):
        """当前主题亮显，另一个灰显"""
        c = self.colors
        bright = c["toolbar_fg"]
        dimmed = "#666666" if self.theme_mode == "light" else "#555555"

        is_light = self.theme_mode == "light"
        self._theme_sun_img = icon_renderer.sun_icon(bright if is_light else dimmed)
        self._theme_moon_img = icon_renderer.moon_icon(bright if not is_light else dimmed)

        btn_bg = c["toolbar_btn_hover"]
        slider_bg = c["toolbar_bg"]

        self.theme_frame.configure(bg=btn_bg)
        self.theme_light_lbl.configure(
            image=self._theme_sun_img,
            bg=slider_bg if is_light else btn_bg,
        )
        self.theme_dark_lbl.configure(
            image=self._theme_moon_img,
            bg=slider_bg if not is_light else btn_bg,
        )

    def _apply_theme(self):
        """应用当前配色到全部控件"""
        c = self.colors

        # 根窗口
        self.root.configure(bg=c["app_bg"])

        # ── 标题栏 ──
        self.titlebar.configure(bg=c["toolbar_bg"])
        self.title_icon.configure(bg=c["toolbar_bg"])
        self._update_title_logo()
        for lbl in self._menu_labels:
            lbl.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"])
            lbl._nb_normal_bg = c["toolbar_bg"]
            lbl._nb_hover_bg = c["toolbar_btn_hover"]
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                          activebackground=c["toolbar_btn_hover"])

        # ── 内容头部（搜索 + 主题） ──
        self._header_right.configure(bg=c["content_header_bg"])
        self.search_entry.configure(
            bg=c["search_bg"], fg=c["search_fg"],
            highlightbackground=c["search_border"],
            highlightcolor=c["search_border"],
            insertbackground=c["toolbar_fg"],
        )
        self.search_clear_lbl.configure(
            bg=c["content_header_bg"], fg=c["toolbar_fg"])
        self.search_btn.configure(
            bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
            activebackground=c["toolbar_btn_hover"],
        )
        self.edit_btn.configure(
            bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
            activebackground=c["toolbar_btn_hover"],
        )
        self._update_theme_toggle()

        # ── 活动栏 ──
        self.nav.configure(bg=c["nav_bg"])
        self.nav_files_btn.configure(bg=c["nav_bg"])
        self.nav_tags_btn.configure(bg=c["nav_bg"])
        # 更新 hover 颜色引用
        self.nav_files_btn._nb_normal_bg = c["nav_bg"]
        self.nav_files_btn._nb_hover_bg = c["nav_hover_bg"]
        self.nav_tags_btn._nb_normal_bg = c["nav_bg"]
        self.nav_tags_btn._nb_hover_bg = c["nav_hover_bg"]
        self._update_nav_icons()

        # ── 侧栏 ──
        self.body.configure(bg=c["app_bg"], highlightbackground=c["app_bg"])
        self._grip.configure(bg=c["sidebar_bg"], highlightbackground=c["sidebar_bg"])
        self.side_frame.configure(bg=c["sidebar_bg"])
        self.file_tree_frame.configure(bg=c["sidebar_bg"])
        self.tree_container.configure(bg=c["sidebar_bg"], highlightbackground=c["sidebar_bg"])
        self.tag_frame.configure(bg=c["sidebar_bg"])
        # 回收站面板
        self.trash_frame.configure(bg=c["sidebar_bg"])
        self.trash_body.configure(bg=c["sidebar_bg"])
        self.trash_header.configure(bg=c["sidebar_header_bg"])
        for w in (self.trash_title, self.trash_sort_btn, self.trash_empty_btn):
            w.configure(bg=c["sidebar_header_bg"], fg=c["sidebar_header_fg"])
        for w in (self.trash_sort_btn, self.trash_empty_btn):
            w._nb_normal_bg = c["sidebar_header_bg"]
            w._nb_hover_bg = c["sidebar_item_selected"]
        self.side_header.configure(bg=c["sidebar_header_bg"], fg=c["sidebar_header_fg"])
        self._tree_header_frame.configure(bg=c["sidebar_header_bg"])
        # 刷新图标颜色
        self._new_folder_img = icon_renderer.folder_plus_icon(c["sidebar_header_fg"])
        self._new_note_img = icon_renderer.file_icon(c["sidebar_header_fg"])
        self.new_folder_btn.configure(
            image=self._new_folder_img,
            bg=c["sidebar_header_bg"],
            activebackground=c["sidebar_header_bg"],
        )
        self.new_note_btn.configure(
            image=self._new_note_img,
            bg=c["sidebar_header_bg"],
            activebackground=c["sidebar_header_bg"],
        )
        self._refresh_img = icon_renderer.svg_icon("refresh.svg", c["sidebar_header_fg"])
        self.refresh_btn.configure(
            image=self._refresh_img,
            bg=c["sidebar_header_bg"],
            activebackground=c["sidebar_header_bg"],
        )

        # 文件树（ttk）
        self.style.configure(
            "Treeview",
            background=c["tree_bg"], foreground=c["tree_fg"],
            fieldbackground=c["tree_bg"],
            borderwidth=0, lightcolor=c["tree_bg"], darkcolor=c["tree_bg"],
            bordercolor=c["tree_bg"],
            font=("Microsoft YaHei", 10), rowheight=26, indent=14,
        )
        self.style.map("Treeview",
                       background=[("selected", c["tree_sel_bg"])],
                       foreground=[("selected", c["tree_sel_fg"])])

        # 表头（回收站列表与 Markdown 表格共用，需单独配置才会跟随主题）
        self.style.configure(
            "Treeview.Heading",
            background=c["sidebar_header_bg"],
            foreground=c["sidebar_header_fg"],
            lightcolor=c["sidebar_header_bg"],
            darkcolor=c["sidebar_header_bg"],
            bordercolor=c["sidebar_header_bg"],
            relief=tk.FLAT, borderwidth=0,
            font=("Microsoft YaHei", 9),
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", c["tree_hover_bg"])],
            foreground=[("active", c["sidebar_header_fg"])],
            lightcolor=[("active", c["tree_hover_bg"])],
            darkcolor=[("active", c["tree_hover_bg"])],
        )

        # 文件树行悬停高亮
        self.tree.tag_configure('hover', background=c["tree_hover_bg"])

        # 标签树悬停高亮
        self.tag_tree.tag_configure('hover', background=c["tree_hover_bg"])

        # 滚动条 — VSCode 风格纯色块
        self.style.configure(
            "Vertical.TScrollbar",
            background=c["scroll_thumb"],
            troughcolor=c["scroll_trough"],
            bordercolor=c["scroll_trough"],
            lightcolor=c["scroll_thumb"],
            darkcolor=c["scroll_thumb"],
            arrowcolor=c["scroll_trough"],
            gripcount=0,
            width=16,
        )
        self.style.configure(
            "Horizontal.TScrollbar",
            background=c["scroll_thumb"],
            troughcolor=c["scroll_trough"],
            bordercolor=c["scroll_trough"],
            arrowcolor=c["scroll_trough"],
            gripcount=0,
            width=16,
        )

        # 右键菜单
        self.tree_menu.configure(
            bg=c["menu_bg"],
            fg=c["menu_fg"],
            activebackground=c["menu_hover"],
            activeforeground=c["menu_fg"],
            separator=c.get("separator", "#d0d0d0"),
        )
        # 内容区右键菜单
        self.content_menu.configure(
            bg=c["menu_bg"],
            fg=c["menu_fg"],
            activebackground=c["menu_hover"],
            activeforeground=c["menu_fg"],
            separator=c.get("separator", "#d0d0d0"),
        )

        # 标签面板
        self.section_all_header.configure(
            bg=c["sidebar_header_bg"], fg=c["sidebar_header_fg"])
        self.section_all_body.configure(bg=c["sidebar_bg"])
        self.tag_search_entry.configure(
            bg=c["search_bg"], fg=c["search_fg"],
            highlightbackground=c["search_border"],
            highlightcolor=c["search_border"],
            insertbackground=c["toolbar_fg"],
        )
        # 占位文字颜色：如果当前显示的是占位文字，用灰色
        if self.tag_search_entry.get() == self._tag_search_placeholder:
            self.tag_search_entry.configure(fg="#777" if self.theme_mode == "dark" else "#999")
        self.tag_intersection_label.configure(
            bg=c["sidebar_bg"], fg=c["sidebar_fg"],
        )
        self.tag_tree_container.configure(
            bg=c["sidebar_bg"], highlightbackground=c["sidebar_bg"],
        )

        listbox_style = {
            "bg": c["sidebar_bg"], "fg": c["sidebar_fg"],
            "selectbackground": c["sidebar_item_selected"],
            "selectforeground": c["sidebar_fg"],
        }
        for prefix in ("file_", "tag_"):
            hdr = getattr(self, f"{prefix}tags_header", None)
            lb = getattr(self, f"{prefix}tags_listbox", None)
            bd = getattr(self, f"{prefix}tags_body", None)
            sep = getattr(self, f"{prefix}tags_sep", None)
            ctr = getattr(self, f"{prefix}tags_container", None)
            if hdr:
                hdr.configure(bg=c["sidebar_header_bg"],
                              fg=c["sidebar_header_fg"])
            if lb:
                lb.configure(**listbox_style)
            if bd:
                bd.configure(bg=c["sidebar_bg"])
            if sep:
                sep.configure(bg=c["sidebar_bg"])
            if ctr:
                ctr.configure(bg=c["sidebar_bg"])
            tb = getattr(self, f"{prefix}tags_toolbar", None)
            if tb:
                tb.configure(bg=c["sidebar_bg"])
                for child in tb.winfo_children():
                    try:
                        child.configure(bg=c["sidebar_bg"],
                                        fg=c["sidebar_fg"])
                    except tk.TclError:
                        pass

        # ── 内容区 ──
        self.content_body.configure(bg=c["app_bg"], highlightbackground=c["app_bg"])
        self.content_header.configure(bg=c["content_header_bg"])
        self.content_title.configure(bg=c["content_header_bg"], fg=c["content_header_fg"])
        self._close_file_btn.configure(bg=c["content_header_bg"])
        self._header_sep.configure(bg=c["content_header_bg"], fg=c.get("border", "#ccc"))
        self.text_container.configure(bg=c["content_bg"], highlightbackground=c["content_bg"])
        self.content_text.configure(
            bg=c["content_bg"], fg=c["content_fg"],
            insertbackground=c["content_fg"],
            selectbackground=c["selection_bg"],
            selectforeground=c["selection_fg"],
        )

        # ── 状态栏 ──
        self.statusbar.configure(bg=c["status_bg"])
        self.status_left.configure(bg=c["status_bg"], fg=c["status_fg"])
        self.status_right.configure(bg=c["status_bg"], fg=c["status_fg"])

        # ── 关闭按钮特殊色（暗色模式更明显） ──
        if self.theme_mode == "dark":
            self.close_btn.configure(
                activebackground="#c03333",
            )

        # ── 更新 hover 颜色 ──
        for btn in (self.min_btn, self.max_btn):
            btn._nb_normal_bg = c["toolbar_bg"]
            btn._nb_hover_bg = c["toolbar_btn_hover"]
        self.close_btn._nb_normal_bg = c["toolbar_bg"]
        self.close_btn._nb_hover_bg = "#e81123" if self.theme_mode == "light" else "#c03333"

        self.new_folder_btn._nb_normal_bg = c["sidebar_header_bg"]
        self.new_folder_btn._nb_hover_bg = c["sidebar_item_selected"]
        self.new_note_btn._nb_normal_bg = c["sidebar_header_bg"]
        self.new_note_btn._nb_hover_bg = c["sidebar_item_selected"]
        self.refresh_btn._nb_normal_bg = c["sidebar_header_bg"]
        self.refresh_btn._nb_hover_bg = c["sidebar_item_selected"]

    # ══════════════════════════════════
    # 面板切换


    def _toggle_follow_system_theme(self):
        """切换跟随系统主题"""
        self._follow_system_theme = not self._follow_system_theme
        self._save_settings()
        if self._follow_system_theme:
            self._theme_overridden = False
            sys_theme = self._read_system_theme()
            if sys_theme != self.theme_mode:
                self.theme_mode = sys_theme
                self.colors = VSCodeTheme.get(self.theme_mode)
                self._apply_theme()
                if self.current_panel == "files":
                    self._refresh_file_tree()
            self.status_left.configure(text="   跟随系统主题: 开")
        else:
            self._theme_overridden = True
            self.status_left.configure(text="   跟随系统主题: 关")

    def _read_system_theme(self):
        """读取 Windows 注册表系统主题设置，返回 'light' 或 'dark'"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value != 0 else "dark"
        except Exception:
            return "light"

    # ══════════════════════════════════
    # 持久化设置
