"""
IndeXar 图形界面
VS Code 风格 + 自定义无边框标题栏 + 亮/暗主题切换
"""

import tkinter as tk
from tkinter import ttk, messagebox
import ctypes
import json
import os
import re
from file_handler import (list_notes, list_notes_tree, read_note, get_tag_index,
                          build_tag_index, build_backlink_index, intersect_tags,
                          invalidate_name_map)
from theme_manager import VSCodeTheme
from editor_detect import detect_editors
import search_engine
import icon_renderer
from context_menu import ContextMenu

import config
from config import SETTINGS_FILE  # 路径由 config 模块统一持有

from ui.common import (SEARCH_HIT_COLOR, SEARCH_HIT_ALPHA, _add_hover_bg,
                       _blend_hex, _readable_fg)
from ui.content_view import ContentViewMixin
from ui.dialogs import DialogsMixin
from ui.file_tree import FileTreeMixin
from ui.search import SearchMixin
from ui.search_panel import SearchPanelMixin
from ui.shell import ShellMixin
from ui.tag_panel import TagPanelMixin
from ui.theme import ThemeMixin
from ui.titlebar import TitleBarMixin
from ui.trash_panel import TrashPanelMixin


class IndeXarApp(TitleBarMixin, FileTreeMixin, TagPanelMixin,
                 ContentViewMixin, SearchMixin, SearchPanelMixin,
                 DialogsMixin, ThemeMixin, ShellMixin, TrashPanelMixin):
    """IndeXar 主应用（无边框+自定义标题栏）"""

    ICONS = {"light": {"sun": "☀️", "moon": "🌙"},
             "dark": {"sun": "☀️", "moon": "🌙"}}
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("IndeXar")

        # ── 移除任务栏图标（默认 Tk 图标比黑块好，暂保留）──

        # ── 移除原生标题栏（必须先设，否则位置会偏移）──
        self.root.overrideredirect(True)

        # 窗口居中
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        cx, cy = (sw - 1100) // 2, (sh - 680) // 2
        self.root.geometry(f"1100x680+{cx}+{cy}")
        self.root.minsize(800, 500)

        # 主题状态
        self.theme_mode = "light"
        self.colors = VSCodeTheme.get(self.theme_mode)
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # 窗口状态
        self._drag_data = {"x": 0, "y": 0}
        self._is_maximized = False
        self._normal_geometry = None
        self._resize_region = ""
        self._resize_data = None

        # 当前面板
        self.current_panel = "files"
        self._current_note_path = None

        # 导航历史（Alt + ←/→）
        self._nav_history = []
        self._nav_index = -1

        # 字号
        self._font_size = 11
        self._font_step = 1

        # 图片显示方式："fit" 适应宽度 / "original" 原始尺寸
        self._image_mode = "fit"

        # 跟随系统主题
        self._follow_system_theme = False
        self._theme_overridden = False

        # 当前文件标签共享状态
        self._file_tags_collapsed = False
        self._selected_file_tag = None
        self._file_tags_height = 88
        # 标签交集状态：(标签名列表, 文件列表)；None 表示当前无交集
        self._tag_intersection = None

        # 回收站排序方向：True = 按删除时间倒序（新 → 旧）
        self._trash_sort_desc = True

        # 外部编辑器路径
        self._editor_path = "notepad.exe"

        # 构建界面
        self._build_layout()

        # 加载持久化设置（覆盖默认值，必须在 _build_layout 之后，因为侧栏宽度需要 side_frame 存在）
        self._load_settings()

        # 如果开启了跟随系统主题，以系统主题覆盖上次手动设置的主题
        if self._follow_system_theme:
            sys_theme = self._read_system_theme()
            if sys_theme != self.theme_mode:
                self.theme_mode = sys_theme

        self.colors = VSCodeTheme.get(self.theme_mode)
        self._apply_theme()

        # 强制刷新布局，确保折叠状态等设置生效
        self.root.update_idletasks()

        # overrideredirect 窗口首次设置 geometry 可能不生效，延迟再设一次
        self.root.after(50, lambda: self.root.geometry(
            f"1100x680+{cx}+{cy}"))

        # ── 绑定窗口调整大小 ──
        self.root.bind("<Button-1>", self._start_resize, add="+")
        self.root.bind("<B1-Motion>", self._do_resize, add="+")
        self.root.bind("<ButtonRelease-1>", self._end_resize, add="+")
        self.root.bind("<Motion>", self._update_cursor, add="+")
        self.root.bind("<Leave>", lambda e: self.root.config(cursor=""), add="+")

        # 导航快捷键：Alt + ← 后退 / Alt + → 前进
        self.root.bind("<Alt-Left>", lambda e: self._go_back(), add="+")
        self.root.bind("<Alt-Right>", lambda e: self._go_forward(), add="+")

        # 内容区鼠标事件（检测 wikilink 交互）
        self.content_text.bind("<ButtonRelease-1>", self._on_content_click)
        self.content_text.bind("<Motion>", self._on_content_motion)

        # Windows 原生窗口管理（Aero Snap + 双击最大化/还原）
        self.root.after(200, self._fix_alt_tab)
        self.root.after(300, self._setup_win32_window_management)

    # ══════════════════════════════════
    # 布局搭建
    # ══════════════════════════════════

    def _build_layout(self):
        """搭建整体布局。外层用 grid 控制列分布，内层面板保持 pack 垂直堆叠。"""
        # Root: 3行, 1列
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # ─── 自定义标题栏 ───
        self._build_titlebar()

        # ─── 主体 (row=1, sticky="nsew") ───
        self.body = tk.Frame(self.root)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, minsize=56)  # 活动栏固定宽度
        self.body.grid_columnconfigure(3, weight=1)     # 内容区列
        self.body.grid_rowconfigure(0, weight=1)

        # 活动栏（col=0, sticky="nsew"）
        self.nav = tk.Frame(self.body, width=56)
        self.nav.grid(row=0, column=0, sticky="nsew")
        self._build_nav_widgets()

        # 侧栏面板（col=1, sticky="ns", w=240）
        self._sidebar_width = 240
        self.side_frame = tk.Frame(self.body, width=240)
        self.side_frame.grid(row=0, column=1, sticky="ns")
        self.side_frame.grid_propagate(False)
        self.side_frame.grid_rowconfigure(0, weight=1)
        self.side_frame.grid_columnconfigure(0, weight=1)
        self._build_file_tree_panel()
        self._build_tag_panel()
        self._build_trash_panel()
        self._build_search_panel()

        # ── 可拖动分隔条（col=2, sticky="ns", w=4）──
        self._grip = tk.Frame(self.body, width=4, cursor="sb_h_double_arrow")
        self._grip.grid(row=0, column=2, sticky="ns")
        self._grip.grid_propagate(False)
        self._grip.bind("<Button-1>", self._start_sidebar_drag)
        self._grip.bind("<B1-Motion>", self._do_sidebar_drag)
        self._grip.bind("<ButtonRelease-1>", self._end_sidebar_drag)

        # 内容区（col=3, sticky="nsew"）
        self._build_content_area(self.body)

        # ─── 状态栏（row=2, sticky="ew", h=22）───
        self.statusbar = tk.Frame(self.root, height=22)
        self.statusbar.grid(row=2, column=0, sticky="ew")
        self.statusbar.grid_propagate(False)
        self._build_statusbar_widgets()

        # 默认显示文件树（toggle=False 防止误收起侧栏）
        self._show_files(toggle=False)

    # ── 活动栏 ──

    # ══════════════════════════════════

    # ══════════════════════════════════


    # ══════════════════════════════════

    def _load_settings(self):
        """从 settings.json 加载配置并应用到界面（读取与校验由 config 负责）"""
        s = config.load()
        self._font_size = s["font_size"]
        self.status_right.configure(text=f"字号: {self._font_size}   ")
        self.theme_mode = s["theme_mode"]
        self._follow_system_theme = s["follow_system_theme"]
        self._sidebar_width = s["sidebar_width"]
        self.side_frame.configure(width=self._sidebar_width)
        self._file_tags_collapsed = s["file_tags_collapsed"]
        self._apply_file_tags_visibility()
        self._file_tags_height = s["file_tags_height"]
        # 折叠状态下不覆盖容器高度（保持 28px）
        if not self._file_tags_collapsed:
            for p in ("file_", "tag_"):
                ctr = getattr(self, f"{p}tags_container", None)
                if ctr:
                    ctr.configure(height=self._file_tags_height)
        self._editor_path = s["editor_path"]
        self._image_mode = s["image_mode"]

    def _save_settings(self):
        """将当前配置写入 settings.json（写入与兜底由 config 负责）"""
        config.save({
            "font_size": self._font_size,
            "theme_mode": self.theme_mode,
            "follow_system_theme": self._follow_system_theme,
            "sidebar_width": self._sidebar_width,
            "file_tags_collapsed": self._file_tags_collapsed,
            "file_tags_height": self._file_tags_height,
            "editor_path": self._editor_path,
            "image_mode": self._image_mode,
        })

    # ══════════════════════════════════
    # 启动
    # ══════════════════════════════════

    def _on_close(self):
        """关闭窗口前保存设置"""
        self._save_settings()
        self.root.destroy()

    def run(self):
        # 启动：后台构建索引 → 随后开始文件轮询监听
        self._file_snapshots = {}
        self.root.after(100, self._start_background_watch)
        self.root.mainloop()

    def _start_background_watch(self):
        """启动时构建索引并建立 mtime 快照，随后启动轮询"""
        try:
            build_tag_index()
            build_backlink_index()
        except Exception:
            pass
        self._snapshot_files()
        self.root.after(1500, self._watch_data_dir)

    def _snapshot_files(self):
        """重建 mtime 快照（程序自身写文件后调用，抑制自触发）"""
        try:
            from file_handler import collect_mtimes
            self._file_snapshots = collect_mtimes()
        except Exception:
            pass

    def _watch_data_dir(self):
        """轮询 data 目录，响应外部编辑/文件增删"""
        try:
            from file_handler import collect_mtimes
            current = collect_mtimes()
        except Exception:
            self.root.after(1500, self._watch_data_dir)
            return
        old = getattr(self, "_file_snapshots", None) or {}
        added = [p for p in current if p not in old]
        removed = [p for p in old if p not in current]
        modified = [p for p in current
                    if p in old and current[p] != old[p]]
        self._file_snapshots = current

        if added or removed:
            if self.current_panel == "files":
                self._refresh_file_tree()
            if self._current_note_path in removed:
                self._close_file()
        if added or modified:
            self._rebuild_indexes()
            if (self._current_note_path and
                    self._current_note_path in (added + modified)):
                self._rerender_current_note()
        self.root.after(1500, self._watch_data_dir)

    def _rebuild_indexes(self):
        """节流重建标签与反向链接索引并刷新标签区"""
        import time
        now = time.time()
        if now - getattr(self, "_last_index_build", 0.0) < 0.8:
            return
        self._last_index_build = now
        try:
            build_tag_index()
            build_backlink_index()
            invalidate_name_map()
        except Exception:
            pass
        self._refresh_tags()
        self._refresh_file_tags()

    def _rerender_current_note(self):
        """当前浏览的笔记被外部修改 → 重渲染并保持滚动位置"""
        rel = self._current_note_path
        if not rel:
            return
        content = read_note(rel)
        if content is None:
            return
        try:
            top = self.content_text.yview()[0]
        except Exception:
            top = 0.0
        self._render_markdown(content)
        self._render_backlinks(rel)
        self.content_text.configure(state=tk.DISABLED)
        self._refresh_file_tags()
        try:
            self.root.update_idletasks()
            self.content_text.yview_moveto(top)
        except Exception:
            pass
