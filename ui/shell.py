"""
IndeXar 外壳界面

活动栏（文件/标签切换）、标题栏菜单、状态栏、侧栏显隐、
字号缩放（视图菜单）与资源管理器打开等窗口级交互。
"""

import os
import subprocess
import tkinter as tk
from tkinter import ttk

import icon_renderer
from context_menu import ContextMenu
from ui.common import _add_hover_bg


class ShellMixin:
    """活动栏、菜单、状态栏与窗口级交互"""

    def _build_nav_widgets(self):
        """活动栏：文件 / 标签切换（自定义绘制图标）"""
        self._nav_files_img = icon_renderer.folder_icon(
            self.colors["nav_active_fg"]
        )
        self.nav_files_btn = tk.Label(
            self.nav, image=self._nav_files_img,
            bg=self.colors["nav_bg"],
            cursor="hand2",
        )
        self.nav_files_btn.pack(fill=tk.X, ipady=10, pady=(4, 0))
        self.nav_files_btn.bind("<Button-1>", lambda e: self._show_files())

        self._nav_tags_img = icon_renderer.tag_icon(
            self.colors["nav_fg"]
        )
        self.nav_tags_btn = tk.Label(
            self.nav, image=self._nav_tags_img,
            bg=self.colors["nav_bg"],
            cursor="hand2",
        )
        self.nav_tags_btn.pack(fill=tk.X, ipady=10, pady=(4, 0))
        self.nav_tags_btn.bind("<Button-1>", lambda e: self._show_tags())

        # 搜索按钮（位于标签与回收站之间）
        self._nav_search_img = icon_renderer.search_icon(
            self.colors["nav_fg"]
        )
        self.nav_search_btn = tk.Label(
            self.nav, image=self._nav_search_img,
            bg=self.colors["nav_bg"],
            cursor="hand2",
        )
        self.nav_search_btn.pack(fill=tk.X, ipady=10, pady=(4, 0))
        self.nav_search_btn.bind("<Button-1>", lambda e: self._show_search())

        self._nav_trash_img = icon_renderer.trash_icon(
            self.colors["nav_fg"]
        )
        self.nav_trash_btn = tk.Label(
            self.nav, image=self._nav_trash_img,
            bg=self.colors["nav_bg"],
            cursor="hand2",
        )
        self.nav_trash_btn.pack(fill=tk.X, ipady=10, pady=(4, 0))
        self.nav_trash_btn.bind("<Button-1>", lambda e: self._show_trash())

        # ── hover 效果 ──
        _add_hover_bg(self.nav_files_btn,
                      self.colors["nav_bg"], self.colors["nav_hover_bg"])
        _add_hover_bg(self.nav_tags_btn,
                      self.colors["nav_bg"], self.colors["nav_hover_bg"])
        _add_hover_bg(self.nav_search_btn,
                      self.colors["nav_bg"], self.colors["nav_hover_bg"])
        _add_hover_bg(self.nav_trash_btn,
                      self.colors["nav_bg"], self.colors["nav_hover_bg"])

    # ── 侧栏面板 ──


    def _show_title_menu(self, event, items):
        """标题栏菜单点击 → 下拉"""
        x = event.widget.winfo_rootx() - 4  # 略向左偏移
        y = event.widget.winfo_rooty() + event.widget.winfo_height() + 2
        menu = ContextMenu(self.root, colors=self._get_menu_colors())
        if callable(items):
            items = items()
        menu.show(x, y, items, use_grab=False)

    def _open_in_explorer(self):
        import subprocess
        from file_handler import DATA_DIR
        subprocess.run(["explorer", os.path.normpath(DATA_DIR)])

    def _get_menu_colors(self):
        return {
            "bg": self.colors["menu_bg"],
            "fg": self.colors["menu_fg"],
            "activebackground": self.colors["menu_hover"],
            "activeforeground": self.colors["menu_fg"],
            "separator": self.colors.get("separator", "#d0d0d0"),
        }






    # ── 状态栏 ──

    def _build_statusbar_widgets(self):
        """状态栏"""
        self.status_left = tk.Label(
            self.statusbar, text="   就绪",
            font=("Microsoft YaHei", 9), padx=10,
        )
        self.status_left.pack(side=tk.LEFT)

        self.status_right = tk.Label(
            self.statusbar, text=f"字号: {self._font_size}   ",
            font=("Microsoft YaHei", 9), padx=10,
        )
        self.status_right.pack(side=tk.RIGHT)

    # ══════════════════════════════════
    # 窗口操作
    # ══════════════════════════════════

    # ── 拖拽移动 ──

    # ══════════════════════════════════
    # 主题


    def _show_files(self, toggle=True):
        # 点击当前激活的文件图标 → 收起/展开侧栏（VSCode 风格）
        if (toggle and self.current_panel == "files"
                and self._sidebar_width > 0):
            self._toggle_sidebar()
            return
        self.current_panel = "files"
        self.tag_frame.grid_remove()
        self.trash_frame.grid_remove()
        self.search_frame.grid_remove()
        self.file_tree_frame.grid(row=0, column=0, sticky="nsew")
        self._restore_sidebar_if_collapsed()
        self._update_nav_icons()
        self._refresh_file_tree()
        self._apply_file_tags_visibility()
        self._refresh_file_tags()

    def _show_tags(self, toggle=True):
        # 点击当前激活的标签图标 → 收起/展开侧栏（VSCode 风格）
        if (toggle and self.current_panel == "tags"
                and self._sidebar_width > 0):
            self._toggle_sidebar()
            return
        self.current_panel = "tags"
        self.file_tree_frame.grid_remove()
        self.trash_frame.grid_remove()
        self.search_frame.grid_remove()
        self.tag_frame.grid(row=0, column=0, sticky="nsew")
        self._restore_sidebar_if_collapsed()
        self._update_nav_icons()
        self._refresh_tags()
        self._apply_file_tags_visibility()
        self._refresh_file_tags()

    def _show_search(self, toggle=True):
        """切换到搜索面板，焦点落到输入框"""
        if (toggle and self.current_panel == "search"
                and self._sidebar_width > 0):
            self._toggle_sidebar()
            return
        self.current_panel = "search"
        self.file_tree_frame.grid_remove()
        self.tag_frame.grid_remove()
        self.trash_frame.grid_remove()
        self.search_frame.grid(row=0, column=0, sticky="nsew")
        self._restore_sidebar_if_collapsed()
        self._update_nav_icons()
        try:
            self.panel_search_entry.focus_set()
        except tk.TclError:
            pass

    def _show_trash(self, toggle=True):
        """切换到回收站面板"""
        if (toggle and self.current_panel == "trash"
                and self._sidebar_width > 0):
            self._toggle_sidebar()
            return
        self.current_panel = "trash"
        self.file_tree_frame.grid_remove()
        self.tag_frame.grid_remove()
        self.search_frame.grid_remove()
        self.trash_frame.grid(row=0, column=0, sticky="nsew")
        self._restore_sidebar_if_collapsed()
        self._update_nav_icons()
        self._refresh_trash()

    def _restore_sidebar_if_collapsed(self):
        """如果侧栏被收起（拖拽或菜单隐藏），展开到记忆/默认宽度"""
        if self._sidebar_width < 50:
            self._sidebar_width = getattr(self, '_prev_sidebar_width', 240)
            self.side_frame.configure(width=self._sidebar_width)
            # 确保 grid 中可见（_toggle_sidebar 可能已 grid_remove）
            if not self.side_frame.winfo_ismapped():
                self.side_frame.grid(row=0, column=1, sticky="ns")
                self._grip.grid(row=0, column=2, sticky="ns")


    def _update_nav_icons(self):
        """根据当前主题色和活动面板刷新图标；侧栏收起时全部回到未激活态"""
        inactive = self.colors["nav_fg"]
        # 侧栏收起时面板不可见，活动栏不应保留任何高亮
        if self._sidebar_width <= 0:
            active = inactive
        else:
            active = self.colors["nav_active_fg"]
        self._nav_files_img = icon_renderer.folder_icon(
            active if self.current_panel == "files" else inactive
        )
        self.nav_files_btn.configure(image=self._nav_files_img)
        self._nav_tags_img = icon_renderer.tag_icon(
            active if self.current_panel == "tags" else inactive
        )
        self.nav_tags_btn.configure(image=self._nav_tags_img)
        self._nav_search_img = icon_renderer.search_icon(
            active if self.current_panel == "search" else inactive
        )
        self.nav_search_btn.configure(image=self._nav_search_img)
        self._nav_trash_img = icon_renderer.trash_icon(
            active if self.current_panel == "trash" else inactive
        )
        self.nav_trash_btn.configure(image=self._nav_trash_img)

    # ══════════════════════════════════
    # 文件树
    # ══════════════════════════════════


    # ══════════════════════════════════

    # ══════════════════════════════════

    # ══════════════════════════════════

    # ══════════════════════════════════

    def _get_view_menu_items(self):
        """动态生成视图菜单（带复选框状态）"""
        follow = self._follow_system_theme
        sidebar_visible = self._sidebar_width > 0
        sidebar_text = "隐藏侧栏" if sidebar_visible else "显示侧栏"
        fit = self._image_mode == "fit"
        return [
            ("字号…", self._open_font_dialog),
            ("切换主题", self._toggle_theme),
            (f"图片适应宽度  {'✓' if fit else ''}",
             lambda: self._set_image_mode("fit")),
            (f"图片原始尺寸  {'✓' if not fit else ''}",
             lambda: self._set_image_mode("original")),
            (sidebar_text, self._toggle_sidebar),
            None,
            (f"跟随系统主题  {'✓' if follow else ''}", self._toggle_follow_system_theme),
        ]

    def _set_image_mode(self, mode):
        """设置 Markdown 图片显示方式：fit=适应宽度 / original=原始尺寸"""
        if mode not in ("fit", "original") or mode == self._image_mode:
            return
        self._image_mode = mode
        self._save_settings()
        if getattr(self, "_current_note_path", None):
            self._display_note(self._current_note_path)
        self.status_left.configure(
            text="   图片显示: " + ("适应宽度" if mode == "fit" else "原始尺寸"))

    def _zoom_in(self):
        """放大字号"""
        self._font_size = min(24, self._font_size + self._font_step)
        self._apply_font_size()
        self._save_settings()
        self.status_right.configure(text=f"字号: {self._font_size}   ")
        self.status_left.configure(text=f"   字号: {self._font_size}")

    def _zoom_out(self):
        """缩小字号"""
        self._font_size = max(8, self._font_size - self._font_step)
        self._apply_font_size()
        self._save_settings()
        self.status_right.configure(text=f"字号: {self._font_size}   ")
        self.status_left.configure(text=f"   字号: {self._font_size}")

    def _zoom_reset(self):
        """重置字号"""
        self._font_size = 11
        self._apply_font_size()
        self._save_settings()
        self.status_right.configure(text=f"字号: {self._font_size}   ")
        self.status_left.configure(text=f"   字号: {self._font_size}")

    def _apply_font_size(self):
        """应用当前字号到内容区并重新渲染"""
        fs = self._font_size
        self.content_text.configure(font=("Microsoft YaHei", fs))
        # 如果有当前打开的文件，重新渲染
        if hasattr(self, '_current_note_path') and self._current_note_path:
            self._display_note(self._current_note_path)


    def _toggle_sidebar(self):
        """显示/隐藏侧栏"""
        if self._sidebar_width > 0:
            self._prev_sidebar_width = self._sidebar_width
            self.side_frame.grid_remove()
            self._grip.grid_remove()
            self._sidebar_width = 0
        else:
            self._sidebar_width = getattr(self, '_prev_sidebar_width', 240)
            self.side_frame.grid(row=0, column=1, sticky="ns")
            self.side_frame.configure(width=self._sidebar_width)
            self._grip.grid(row=0, column=2, sticky="ns")
        # 侧栏显隐变化后刷新活动栏高亮（收起时全部回到未激活态）
        self._update_nav_icons()
        self._save_settings()
