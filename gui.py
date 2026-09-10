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
                          build_tag_index, build_backlink_index, intersect_tags)
from theme_manager import VSCodeTheme
from editor_detect import detect_editors
import search_engine
import icon_renderer
from context_menu import ContextMenu

import config
from config import SETTINGS_FILE  # 路径由 config 模块统一持有

# 搜索命中高亮：基色 + 不透明度
# Tk 的 tag 背景不支持 alpha，故用「基色与内容区背景混色」等效实现，
# 好处是能自动适配亮/暗主题。alpha 越小越淡，1.0 为纯色。
SEARCH_HIT_COLOR = "#ffd54a"
SEARCH_HIT_ALPHA = 0.55


def _hex_to_rgb(value):
    """'#rrggbb' → (r, g, b)，非法值按白色处理"""
    h = (value or "").lstrip("#")
    if len(h) != 6:
        return (255, 255, 255)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def _blend_hex(fg_hex, bg_hex, alpha):
    """将前景色按 alpha 叠加到背景色上，等效于半透明效果"""
    r1, g1, b1 = _hex_to_rgb(fg_hex)
    r2, g2, b2 = _hex_to_rgb(bg_hex)
    mix = lambda a, b: int(round(a * alpha + b * (1 - alpha)))
    return "#%02x%02x%02x" % (mix(r1, r2), mix(g1, g2), mix(b1, b2))


def _readable_fg(bg_hex):
    """按背景亮度选择黑字或白字，保证高亮处文字可读"""
    r, g, b = _hex_to_rgb(bg_hex)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 140 else "#ffffff"


def _add_hover_bg(widget, normal_bg, hover_bg, debug=False):
    """为 tk.Button/Label 添加 hover 背景色效果。
    主题切换时直接更新 widget._nb_normal_bg / widget._nb_hover_bg 即可。
    """
    widget._nb_hover_bg = hover_bg
    widget._nb_normal_bg = normal_bg
    if debug:
        widget.bind("<Enter>", lambda e: (
            print(f"[HOVER ENTER] {widget}, bg={e.widget._nb_hover_bg}"),
            e.widget.configure(bg=e.widget._nb_hover_bg)))
        widget.bind("<Leave>", lambda e: (
            print(f"[HOVER LEAVE] {widget}"),
            e.widget.configure(bg=e.widget._nb_normal_bg)))
    else:
        widget.bind("<Enter>", lambda e: e.widget.configure(bg=e.widget._nb_hover_bg))
        widget.bind("<Leave>", lambda e: e.widget.configure(bg=e.widget._nb_normal_bg))


# ── 窗口拖拽 / 调整大小的阈值（像素） ──
RESIZE_EDGE = 8


class IndeXarApp:
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

        # 字号
        self._font_size = 11
        self._font_step = 1

        # 跟随系统主题
        self._follow_system_theme = False
        self._theme_overridden = False

        # 当前文件标签共享状态
        self._file_tags_collapsed = False
        self._selected_file_tag = None
        self._file_tags_height = 88
        # 标签交集状态：(标签名列表, 文件列表)；None 表示当前无交集
        self._tag_intersection = None

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

    # ── 自定义标题栏 ──

    def _build_titlebar(self):
        """自定义标题栏：拖拽移动 + 窗口控制按钮"""
        bar = tk.Frame(self.root, height=30)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.titlebar = bar

        # ── 应用图标（亮/暗主题 PNG）──
        self._logo_img = None
        self.title_icon = tk.Label(bar, text="",
                                   padx=6, pady=2)
        self.title_icon.pack(side=tk.LEFT, padx=(2, 20))
        self._update_title_logo()

        # ── 菜单栏 ──
        self._menu_labels = []  # 用于拖拽绑定
        self._menu_defs = [
            ("文件", [
                ("新建笔记", self._create_note),
                ("新建文件夹", self._create_folder),
                None,
                ("设置…", self._open_settings),
                None,
                ("退出", self._on_close),
            ]),
            ("编辑", [
                ("刷新文件树", self._refresh_file_tree),
                ("在资源管理器中打开", self._open_in_explorer),
            ]),
            ("视图", self._get_view_menu_items),
            ("帮助", [
                ("使用帮助", lambda: self._open_help()),
            ]),
        ]
        for name, items in self._menu_defs:
            lbl = tk.Label(bar, text=name,
                          font=("Segoe UI", 10),
                          padx=10, pady=1,
                          fg=self.colors["toolbar_fg"],
                          cursor="hand2")
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda e, i=items: self._show_title_menu(e, i))
            _add_hover_bg(lbl, self.colors["toolbar_bg"],
                         self.colors["toolbar_btn_hover"])
            self._menu_labels.append(lbl)

        # 窗口控制按钮
        btn_frame = tk.Frame(bar)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y)

        btn_size = 20

        self.min_btn = self._make_title_btn(
            btn_frame, "─", btn_size,
            self._minimize_window,
        )
        self.min_btn.pack(side=tk.LEFT, padx=0, fill=tk.Y)

        self.max_btn = self._make_title_btn(
            btn_frame, "□", btn_size,
            self._toggle_maximize,
        )
        self.max_btn.pack(side=tk.LEFT, padx=0, fill=tk.Y)

        self.close_btn = self._make_title_btn(
            btn_frame, "✕", btn_size,
            self._on_close,
        )
        self.close_btn.pack(side=tk.LEFT, padx=0, fill=tk.Y)

        # ── 按钮 hover 效果 ──
        _add_hover_bg(self.min_btn,
                      self.colors["toolbar_bg"], self.colors["toolbar_btn_hover"])
        _add_hover_bg(self.max_btn,
                      self.colors["toolbar_bg"], self.colors["toolbar_btn_hover"])
        _close_hover = "#e81123" if self.theme_mode == "light" else "#c03333"
        _add_hover_bg(self.close_btn,
                      self.colors["toolbar_bg"], _close_hover)

        # ── 拖拽绑定（菜单项本身不参与拖拽，避免和点击菜单冲突）──
        for widget in (bar, self.title_icon):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)
            widget.bind("<Double-Button-1>",
                        lambda e: self._toggle_maximize())

    def _update_title_logo(self):
        """加载当前主题对应的应用图标 PNG"""
        import os
        fname = ("light_16.png" if self.theme_mode == "light"
                 else "dark_16.png")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", fname)
        if not os.path.exists(path):
            return
        try:
            self._logo_img = tk.PhotoImage(file=path)
            self.title_icon.configure(image=self._logo_img)
        except tk.TclError:
            pass

    def _make_title_btn(self, parent, text, size, cmd):
        """创建标题栏按钮"""
        btn = tk.Button(
            parent, text=text,
            font=("Segoe UI", 10),
            width=3, height=0,
            relief=tk.FLAT, bd=0,
            cursor="hand2",
            command=cmd,
        )
        return btn



    # ── 活动栏 ──

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

        # ── hover 效果 ──
        _add_hover_bg(self.nav_files_btn,
                      self.colors["nav_bg"], self.colors["nav_hover_bg"])
        _add_hover_bg(self.nav_tags_btn,
                      self.colors["nav_bg"], self.colors["nav_hover_bg"])

    # ── 侧栏面板 ──

    def _build_file_tree_panel(self):
        """文件树"""
        self.file_tree_frame = tk.Frame(self.side_frame)
        # 头部行：笔记列表标题 + 并排新建按钮
        self._tree_header_frame = tk.Frame(self.file_tree_frame)
        self._tree_header_frame.pack(fill=tk.X)
        self.side_header = tk.Label(
            self._tree_header_frame,
            text="   笔记列表",
            font=("Microsoft YaHei", 10),
            anchor=tk.W, padx=8, pady=6,
        )
        self.side_header.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 新建文件夹 + 新建笔记，并排放在右侧（如 VS Code）
        self._new_folder_img = icon_renderer.folder_plus_icon(
            self.colors["sidebar_header_fg"]
        )
        self.new_folder_btn = tk.Button(
            self._tree_header_frame,
            image=self._new_folder_img,
            cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            padx=4, pady=0,
        )
        self.new_folder_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self.new_folder_btn.config(
            command=lambda: self._create_folder(
                default_dir=self._get_tree_context_dir()))

        self._new_note_img = icon_renderer.file_icon(
            self.colors["sidebar_header_fg"]
        )
        self.new_note_btn = tk.Button(
            self._tree_header_frame,
            image=self._new_note_img,
            cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            padx=4, pady=0,
        )
        self.new_note_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.new_note_btn.config(
            command=lambda: self._create_note(
                default_dir=self._get_tree_context_dir()))

        # 刷新文件树按钮
        self._refresh_img = icon_renderer.svg_icon(
            "refresh.svg", self.colors["sidebar_header_fg"])
        self.refresh_btn = tk.Button(
            self._tree_header_frame,
            image=self._refresh_img,
            cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            padx=4, pady=0,
            command=self._refresh_file_tree,
        )
        self.refresh_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ── hover 效果 ──
        _add_hover_bg(self.new_folder_btn,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])
        _add_hover_bg(self.new_note_btn,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])
        _add_hover_bg(self.refresh_btn,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])

        self.tree_container = tk.Frame(self.file_tree_frame)
        self.tree_container.pack(fill=tk.BOTH, expand=True)

        self.tree_scroll = ttk.Scrollbar(
            self.tree_container, orient=tk.VERTICAL,
        )
        self.tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(self.tree_container, show="tree", selectmode="browse")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_scroll.configure(command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_file_selected)

        # ── 文件树行悬停高亮 ──
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)

        # ── 当前文件标签（共享组件）──
        self._build_file_tags_section(self.file_tree_frame, "file_")

        # 右键菜单
        self._build_tree_context_menu()

    def _build_tree_context_menu(self):
        """文件树右键菜单（自定义无边框菜单）"""
        self.tree_menu = ContextMenu(self.root, colors={
            "bg": self.colors["sidebar_bg"],
            "fg": self.colors["sidebar_fg"],
            "activebackground": self.colors["sidebar_item_selected"],
            "activeforeground": self.colors["sidebar_fg"],
            "separator": self.colors.get("separator", "#d0d0d0"),
        })
        self._tree_menu_items = [
            ("新建笔记", self._tree_context_new),
            ("新建文件夹", self._tree_context_new_folder),
            None,  # separator
            ("重命名", self._tree_context_rename),
            ("删除", self._tree_context_delete),
            None,  # separator
            ("在资源管理器中打开", self._tree_context_reveal),
        ]
        self.tree.bind("<Button-3>", self._show_tree_menu)

    def _on_tree_motion(self, event):
        """文件树行鼠标悬停 → 高亮"""
        iid = self.tree.identify_row(event.y)
        prev = getattr(self, '_tree_hover_item', None)
        if prev and prev != iid:
            try:
                self.tree.item(prev, tags=())
            except tk.TclError:
                pass
        if iid:
            self.tree.item(iid, tags=('hover',))
            self._tree_hover_item = iid
        else:
            self._tree_hover_item = None

    def _on_tree_leave(self, event):
        """鼠标离开文件树 → 清除悬停高亮"""
        prev = getattr(self, '_tree_hover_item', None)
        if prev:
            try:
                self.tree.item(prev, tags=())
            except tk.TclError:
                pass
            self._tree_hover_item = None

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

    def _show_tree_menu(self, event):
        """右键点击树节点时显示自定义菜单（根据文件/文件夹动态切换）"""
        iid = self.tree.identify_row(event.y)
        # 设置标志防止 _on_file_selected 误触发文件夹 toggle
        self._right_clicking = True

        if iid:
            self.tree.selection_set(iid)
            vals = self.tree.item(iid, "values")
            is_dir = vals and (vals[1] == "True" or vals[1] is True)
            if is_dir:
                items = [
                    ("新建笔记", self._tree_context_new),
                    ("新建文件夹", self._tree_context_new_folder),
                    None,
                    ("重命名文件夹", self._tree_context_rename),
                    ("删除文件夹", self._tree_context_delete),
                    None,
                    ("在资源管理器中打开", self._tree_context_reveal),
                ]
            else:
                items = [
                    ("新建笔记", self._tree_context_new),
                    ("新建文件夹", self._tree_context_new_folder),
                    None,
                    ("外部编辑器打开", self._open_in_editor),
                    None,
                    ("重命名", self._tree_context_rename),
                    ("删除", self._tree_context_delete),
                    None,
                    ("在资源管理器中打开", self._tree_context_reveal),
                ]
        else:
            # 点在空白区域 → 清空选中，仅提供新建
            self.tree.selection_set(())
            items = [
                ("新建笔记", self._tree_context_new),
                ("新建文件夹", self._tree_context_new_folder),
            ]

        # 每次显示菜单都传入当前主题色（保证主题切换后颜色即时更新）
        # use_grab=False 避免和新创建对话框的 grab 冲突导致卡死
        self.tree_menu.show(
            event.x_root, event.y_root, items,
            colors_override={
                "bg": self.colors["menu_bg"],
                "fg": self.colors["menu_fg"],
                "activebackground": self.colors["menu_hover"],
                "activeforeground": self.colors["menu_fg"],
                "separator": self.colors.get("separator", "#d0d0d0"),
            },
            use_grab=False)

    def _get_tree_context_dir(self):
        """返回右键选中项所在的目录路径（相对路径）"""
        sel = self.tree.selection()
        if not sel:
            return ""
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return ""
        iid, is_dir = vals[0], vals[1]
        if is_dir == "True" or is_dir is True:
            return iid  # 选中了文件夹，直接用它
        else:
            # 选中了文件，取其所在目录
            parts = iid.rsplit("/", 1)
            return parts[0] if len(parts) > 1 else ""

    def _tree_context_new(self):
        """右键 → 新建笔记"""
        self._create_note(default_dir=self._get_tree_context_dir())

    def _tree_context_new_folder(self):
        """右键 → 新建文件夹"""
        from file_handler import make_subdir
        parent = self._get_tree_context_dir()

        dialog = self._make_dialog(self.root, "新建文件夹", 380, 180)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        hint = f"在 {(parent or '根目录')} 下新建："
        tk.Label(frame, text=hint, anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 8))
        name_var = tk.StringVar(value="new_folder")
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10))
        entry.pack(fill=tk.X, pady=(0, 12))
        entry.select_range(0, tk.END)
        entry.focus_set()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))

        def do_create():
            name = name_var.get().strip()
            if name:
                make_subdir(parent, name)
                dialog.destroy()
                self._refresh_file_tree()

        tk.Button(btn_frame, text="创建", font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)

    def _tree_context_rename(self):
        """右键 → 重命名（文件/文件夹）"""
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        iid, is_dir = vals[0], vals[1]
        is_dir = (is_dir == "True" or is_dir is True)
        from file_handler import rename_note, rename_folder

        old_name = os.path.basename(iid)
        item_type = "文件夹" if is_dir else "笔记"

        dialog = self._make_dialog(self.root, f"重命名{item_type}", 380, 180)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text=f"重命名 {item_type}：{old_name}", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 8))
        name_var = tk.StringVar(value=old_name)
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10))
        entry.pack(fill=tk.X, pady=(0, 12))
        entry.select_range(0, tk.END)
        entry.focus_set()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))

        def do_rename():
            new_name = name_var.get().strip()
            if new_name and new_name != old_name:
                if is_dir:
                    rename_folder(iid, new_name)
                else:
                    rename_note(iid, new_name)
                dialog.destroy()
                self._refresh_file_tree()
                self._snapshot_files()  # 抑制轮询自触发

        tk.Button(btn_frame, text="确认", font=("Microsoft YaHei", 9),
                  command=do_rename).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_rename())
        self._theme_dialog_body(dialog)

    def _tree_context_delete(self):
        """右键 → 删除（文件/文件夹）"""
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        iid, is_dir = vals[0], vals[1]
        is_dir = (is_dir == "True" or is_dir is True)

        name = os.path.basename(iid)
        item_type = "文件夹" if is_dir else "笔记"
        if is_dir:
            msg = f"确定删除文件夹「{name}」及其所有内容？\n此操作不可撤销。"
        else:
            msg = f"确定删除笔记「{name}」？\n此操作不可撤销。"

        confirm = messagebox.askyesno(f"确认删除{item_type}", msg)
        if confirm:
            if is_dir:
                from file_handler import delete_folder
                delete_folder(iid)
            else:
                from file_handler import delete_note
                delete_note(iid)
            self._refresh_file_tree()
            self._snapshot_files()  # 抑制轮询自触发
            self._set_content("")

    def _tree_context_reveal(self):
        """右键 → 在资源管理器中打开"""
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        iid, is_dir = vals[0], vals[1]
        from file_handler import DATA_DIR
        if is_dir == "True" or is_dir is True:
            target = os.path.join(DATA_DIR, iid)
        else:
            target = os.path.join(DATA_DIR, f"{iid}.md")
        if os.path.exists(target):
            import subprocess
            subprocess.run(["explorer", "/select,", os.path.normpath(target)])

    def _open_current_in_editor(self):
        """顶部'编辑'按钮：打开当前正在浏览的笔记"""
        if not self._current_note_path:
            self.status_left.configure(text="   请先打开一篇笔记")
            return
        from file_handler import DATA_DIR
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        if not os.path.exists(filepath):
            self.status_left.configure(text="   找不到笔记文件")
            return
        self._open_in_editor(filepath)

    def _open_in_editor(self, filepath=None):
        """用外部编辑器打开文件"""
        import subprocess
        if filepath is None:
            sel = self.tree.selection()
            if not sel:
                return
            vals = self.tree.item(sel[0], "values")
            if not vals or vals[1] == "True" or vals[1] is True:
                return  # 跳过文件夹
            iid = vals[0]
            from file_handler import DATA_DIR
            filepath = os.path.join(DATA_DIR, f"{iid}.md")
            if not os.path.exists(filepath):
                return
        import shutil
        editor = self._editor_path or "notepad.exe"
        # 路径失效（软件被卸载或迁移）时回退系统记事本
        if not (os.path.isfile(editor) or shutil.which(editor)):
            editor = "notepad.exe"
        try:
            # 不使用 shell=True：路径含空格时会被二次解析，导致启动失败
            subprocess.Popen([editor, filepath])
        except Exception:
            subprocess.Popen(["notepad.exe", filepath])

    def _build_tag_panel(self):
        """标签面板：可折叠的两个区块 —— 所有标签 + 当前文件标签"""
        self.tag_frame = tk.Frame(self.side_frame)

        # ── 辅助：创建可折叠区块 ──
        def _make_section(parent, title_text, expand=True):
            """返回 (header_label, body_frame)，header 点击折叠/展开 body"""
            header = tk.Label(
                parent,
                text=f"▼ {title_text}",
                font=("Microsoft YaHei", 9),
                anchor=tk.W, padx=4, pady=4,
                cursor="hand2",
            )
            header.pack(fill=tk.X)
            body = tk.Frame(parent, bd=0, highlightthickness=0)
            body.pack(fill=tk.BOTH, expand=expand)
            body._collapsed = False
            body._expand = expand

            def toggle():
                if body._collapsed:
                    body.pack(fill=tk.BOTH, expand=body._expand,
                              before=body._next_widget if hasattr(body, '_next_widget') else None)
                    header.configure(text=header.cget("text").replace("▶", "▼"))
                    body._collapsed = False
                else:
                    body.pack_forget()
                    header.configure(text=header.cget("text").replace("▼", "▶"))
                    body._collapsed = True

            header.bind("<Button-1>", lambda e: toggle())
            return header, body

        # ── 区块1：所有标签 ──
        self.section_all_header, self.section_all_body = _make_section(
            self.tag_frame, "所有标签", expand=True)

        # 搜索框
        self.tag_search_var = tk.StringVar()
        self.tag_search_var.trace_add("write", lambda *a: self._on_tag_search())
        self.tag_search_entry = tk.Entry(
            self.section_all_body,
            textvariable=self.tag_search_var,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
        )
        self.tag_search_entry.pack(fill=tk.X, padx=8, pady=(4, 2))
        self.tag_search_entry.bind("<Escape>", lambda e: (
            self.tag_search_var.set(""),
            self._refresh_tags(),
        ))
        self._tag_search_placeholder = "搜索标签..."
        self.tag_search_entry.insert(0, self._tag_search_placeholder)
        self.tag_search_entry.configure(fg="#999")
        self.tag_search_entry.bind("<FocusIn>", self._on_tag_search_focus_in)
        self.tag_search_entry.bind("<FocusOut>", self._on_tag_search_focus_out)

        # 交集提示
        self.tag_intersection_label = tk.Label(
            self.section_all_body,
            text="",
            font=("Microsoft YaHei", 8),
            anchor=tk.W, padx=10, pady=1,
        )
        self.tag_intersection_label.pack(fill=tk.X)

        # 标签/文件 Treeview
        self.tag_tree_container = tk.Frame(self.section_all_body,
                                           bd=0, highlightthickness=0)
        self.tag_tree_container.pack(fill=tk.BOTH, expand=True)

        self.tag_tree_scroll = ttk.Scrollbar(
            self.tag_tree_container, orient=tk.VERTICAL,
        )
        self.tag_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tag_tree = ttk.Treeview(
            self.tag_tree_container, show="tree",
            selectmode="extended",
        )
        self.tag_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tag_tree_scroll.configure(command=self.tag_tree.yview)
        self.tag_tree.configure(yscrollcommand=self.tag_tree_scroll.set)

        self.tag_tree.bind("<<TreeviewSelect>>", self._on_tag_tree_select)
        self.tag_tree.bind("<Double-Button-1>", self._on_tag_tree_double_click)
        self.tag_tree.bind("<ButtonRelease-1>", self._on_tag_tree_click)
        self.tag_tree.bind("<Motion>", self._on_tag_tree_motion)
        self.tag_tree.bind("<Leave>", self._on_tag_tree_leave)

        # ── 区块2：当前文件标签（共享组件，固定在底部）──
        self._build_file_tags_section(self.tag_frame, "tag_",
                                      pack_side=tk.BOTTOM)
        self.section_all_body._next_widget = self.tag_tags_container

        # 覆写"所有标签"的折叠行为：收起时将"当前文件标签"提上来贴着头
        self.section_all_header.unbind("<Button-1>")
        self.section_all_header.bind("<Button-1>",
                                     lambda e: self._toggle_all_tags_section())

    # ── 标签页"所有标签"折叠逻辑 ──

    def _toggle_all_tags_section(self):
        """展开/折叠'所有标签'区块，'当前文件标签'跟随移动"""
        body = self.section_all_body
        header = self.section_all_header
        if body._collapsed:
            self._expand_all_tags_section()
        else:
            body.pack_forget()
            # 收起时容器切换到 expand 模式，填满剩余空间
            ctr = self.tag_tags_container
            ctr.pack_forget()
            ctr.pack(fill=tk.BOTH, expand=True)
            header.configure(text=header.cget("text").replace("▼", "▶"))
            body._collapsed = True

    def _expand_all_tags_section(self):
        """展开'所有标签'，'当前文件标签'归位底部"""
        body = self.section_all_body
        header = self.section_all_header
        ctr = self.tag_tags_container
        if not body._collapsed:
            return
        body.pack(fill=tk.BOTH, expand=True, before=ctr)
        # 恢复容器为底部固定模式
        ctr.pack_forget()
        ctr.pack(fill=tk.X, side=tk.BOTTOM)
        header.configure(text=header.cget("text").replace("▶", "▼"))
        body._collapsed = False

    # ── 共享组件：当前文件标签区块 ──

    def _build_file_tags_section(self, parent, prefix, pack_side=None):
        """在 parent 中创建'当前文件标签'区块，设置 self.{prefix}_tags_* 属性。
        pack_side: 容器在 parent 中的 pack side（如 tk.BOTTOM 用于标签页）"""

        # ── 外层容器 ──
        container = tk.Frame(parent, bd=0, highlightthickness=0,
                             height=self._file_tags_height)
        container.pack(fill=tk.X, side=pack_side if pack_side else tk.TOP)
        container.pack_propagate(False)
        setattr(self, f"{prefix}tags_container", container)

        # ── 可拖动分隔条 ──
        sep = tk.Frame(container, height=4, cursor="sb_v_double_arrow")
        sep.pack(fill=tk.X)
        sep.bind("<Button-1>", lambda e: self._start_tags_drag(e, prefix))
        sep.bind("<B1-Motion>", lambda e: self._do_tags_drag(e, prefix))
        setattr(self, f"{prefix}tags_sep", sep)

        header = tk.Label(container,
                          text="▼ 当前文件标签",
                          font=("Microsoft YaHei", 9),
                          anchor=tk.W, padx=4, pady=3,
                          cursor="hand2")
        header.pack(fill=tk.X)

        body = tk.Frame(container, bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True)

        # 标签工具条：＋ 添加 / － 删除
        toolbar = tk.Frame(body, bd=0, highlightthickness=0)
        toolbar.pack(fill=tk.X, padx=8, pady=(2, 0))
        add_btn = tk.Label(toolbar, text="＋ 添加标签",
                           font=("Microsoft YaHei", 9),
                           cursor="hand2", padx=2)
        add_btn.pack(side=tk.LEFT)
        del_btn = tk.Label(toolbar, text="－ 删除所选",
                           font=("Microsoft YaHei", 9),
                           cursor="hand2", padx=6)
        del_btn.pack(side=tk.LEFT)
        add_btn.bind("<Button-1>",
                     lambda e, pf=prefix: self._add_current_file_tag(pf))
        del_btn.bind("<Button-1>",
                     lambda e, pf=prefix: self._remove_selected_file_tag(pf))

        listbox = tk.Listbox(body,
                             font=("Microsoft YaHei", 10),
                             relief=tk.FLAT, highlightthickness=0,
                             borderwidth=0, activestyle="none",
                             selectmode="browse")
        listbox.pack(fill=tk.BOTH, expand=True, padx=8)

        header.bind("<Button-1>", lambda e: self._toggle_file_tags())
        listbox.bind("<Double-Button-1>", self._on_file_tag_dclick)

        setattr(self, f"{prefix}tags_header", header)
        setattr(self, f"{prefix}tags_body", body)
        setattr(self, f"{prefix}tags_toolbar", toolbar)
        setattr(self, f"{prefix}tags_listbox", listbox)

    # ── 拖拽调整标签区块高度 ──

    def _start_tags_drag(self, event, prefix):
        ctr = getattr(self, f"{prefix}tags_container")
        parent = ctr.master
        self._tags_drag = {
            "y": event.y_root,
            "start_h": ctr.winfo_height(),
            "parent_h": parent.winfo_height(),
            "min_upper": 120 if prefix == "file_" else 160,
        }

    def _do_tags_drag(self, event, prefix):
        if self._file_tags_collapsed:
            return
        d = self._tags_drag
        dy = d["y"] - event.y_root
        new_h = d["start_h"] + dy
        lower_max = d["parent_h"] - d["min_upper"]
        new_h = max(60, min(lower_max, new_h))
        self._file_tags_height = new_h
        for p in ("file_", "tag_"):
            ctr = getattr(self, f"{p}tags_container", None)
            if ctr:
                ctr.configure(height=new_h)
        self._save_settings()

    def _toggle_file_tags(self):
        """折叠/展开所有'当前文件标签'区块"""
        self._file_tags_collapsed = not self._file_tags_collapsed
        self._apply_file_tags_visibility()
        self._save_settings()

    def _apply_file_tags_visibility(self):
        """根据共享折叠状态更新当前可见区块的外观"""
        arrow = "▶" if self._file_tags_collapsed else "▼"
        for prefix in ("file_", "tag_"):
            header = getattr(self, f"{prefix}tags_header", None)
            body = getattr(self, f"{prefix}tags_body", None)
            ctr = getattr(self, f"{prefix}tags_container", None)
            if header:
                header.configure(text=f"{arrow} 当前文件标签")
            if body:
                if self._file_tags_collapsed:
                    body.pack_forget()
                else:
                    body.pack(fill=tk.BOTH, expand=True)
            # 折叠时容器缩小到只够放标题，展开时恢复记忆高度
            if ctr:
                if self._file_tags_collapsed:
                    ctr.configure(height=28)
                else:
                    ctr.configure(height=self._file_tags_height)

    def _refresh_file_tags(self):
        """刷新两个页面的'当前文件标签'列表"""
        tags = []
        if self._current_note_path:
            from file_handler import parse_front_matter_tags, DATA_DIR
            filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
            tags = parse_front_matter_tags(filepath)

        for prefix in ("file_", "tag_"):
            lb = getattr(self, f"{prefix}tags_listbox", None)
            if not lb:
                continue
            lb.delete(0, tk.END)
            if not self._current_note_path:
                lb.insert(tk.END, "  未打开文件")
            elif not tags:
                lb.insert(tk.END, "  无标签")
            else:
                for t in tags:
                    lb.insert(tk.END, f"  {t}")
            # 恢复选中状态
            self._sync_file_tag_selection(lb)

    def _ask_single_line(self, title, prompt, initial=""):
        """简易单行输入对话框（跟随主题），返回输入字符串或 None"""
        result = [None]
        dialog = self._make_dialog(self.root, title, 380, 150)
        self._theme_dialog_body(dialog)
        c = self.colors
        body = tk.Frame(dialog, bg=c["sidebar_bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        tk.Label(body, text=prompt, bg=c["sidebar_bg"],
                 fg=c["sidebar_fg"], font=("Microsoft YaHei", 10),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 8))
        var = tk.StringVar(value=initial)
        entry = tk.Entry(body, textvariable=var,
                         font=("Microsoft YaHei", 10),
                         relief=tk.SUNKEN,
                         bg=c["search_bg"], fg=c["search_fg"],
                         insertbackground=c["search_fg"])
        entry.pack(fill=tk.X, pady=(0, 14))
        entry.focus_set()
        entry.select_range(0, tk.END)
        btns = tk.Frame(body, bg=c["sidebar_bg"])
        btns.pack(fill=tk.X)

        def ok():
            result[0] = var.get().strip()
            dialog.destroy()

        tk.Button(btns, text="确定", font=("Microsoft YaHei", 9),
                  bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                  command=ok).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btns, text="取消", font=("Microsoft YaHei", 9),
                  bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                  command=dialog.destroy).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: ok())
        entry.bind("<Escape>", lambda e: dialog.destroy())
        dialog.wait_window()
        return result[0]

    def _add_current_file_tag(self, prefix):
        """为当前文件添加标签"""
        if not self._current_note_path:
            self.status_left.configure(text="   请先打开一篇笔记")
            return
        tag = self._ask_single_line("添加标签", "输入新标签：")
        if not tag:
            return
        tag = tag.replace(",", " ").strip()
        if not tag:
            return
        from file_handler import (parse_front_matter_tags, set_note_tags,
                                  build_tag_index, DATA_DIR)
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        cur = parse_front_matter_tags(filepath)
        if tag in cur:
            self.status_left.configure(text=f"   标签「{tag}」已存在")
            return
        self._apply_tag_change(self._current_note_path, cur + [tag])

    def _remove_selected_file_tag(self, prefix):
        """删除当前文件被选中的标签"""
        if not self._current_note_path:
            self.status_left.configure(text="   请先打开一篇笔记")
            return
        lb = getattr(self, f"{prefix}tags_listbox", None)
        if not lb:
            return
        sel = lb.curselection()
        if not sel:
            self.status_left.configure(
                text="   请先在标签列表选中要删除的标签")
            return
        tag_text = lb.get(sel[0]).strip()
        if tag_text in ("未打开文件", "无标签"):
            return
        from file_handler import (parse_front_matter_tags, DATA_DIR)
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        cur = parse_front_matter_tags(filepath)
        if tag_text not in cur:
            self.status_left.configure(text=f"   标签「{tag_text}」不在文件中")
            return
        new = [t for t in cur if t != tag_text]
        self._apply_tag_change(self._current_note_path, new)

    def _apply_tag_change(self, rel_path, tags):
        """写回标签 → 重建索引 → 刷新两处列表与标签树"""
        from file_handler import set_note_tags, build_tag_index
        new_tags = set_note_tags(rel_path, tags)
        if new_tags is None:
            self.status_left.configure(text="   写入标签失败")
            return
        build_tag_index()
        self._refresh_file_tags()
        self._refresh_tags()
        self._snapshot_files()  # 抑制轮询自触发
        summary = ", ".join(new_tags) if new_tags else "(无标签)"
        self.status_left.configure(text=f"   标签已更新：{summary}")

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

    def _on_file_tag_dclick(self, event):
        """双击标签 → 跳转标签页定位"""
        lb = event.widget
        sel = lb.curselection()
        if not sel:
            return
        tag_text = lb.get(sel[0]).strip()
        if not tag_text or tag_text in ("未打开文件", "无标签"):
            return

        self._selected_file_tag = tag_text
        for prefix in ("file_", "tag_"):
            other_lb = getattr(self, f"{prefix}tags_listbox", None)
            if other_lb:
                self._sync_file_tag_selection(other_lb)

        if self.current_panel != "tags":
            self._show_tags()
        self._expand_all_tags_section()
        iid = f"tag_{tag_text}"
        if self.tag_tree.exists(iid):
            self.tag_tree.selection_set(iid)
            self.tag_tree.see(iid)
            self.tag_tree.item(iid, open=True)

    def _sync_file_tag_selection(self, lb):
        """同步单个 listbox 的选中状态到 self._selected_file_tag"""
        lb.selection_clear(0, tk.END)
        if self._selected_file_tag:
            items = lb.get(0, tk.END)
            for i, item in enumerate(items):
                if item.strip() == self._selected_file_tag:
                    lb.selection_set(i)
                    break

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

        self.content_text = tk.Text(
            self.text_container,
            wrap=tk.WORD,
            font=("Microsoft YaHei", 11),
            padx=20, pady=16,
            relief=tk.FLAT, highlightthickness=0,
            borderwidth=0, insertwidth=2,
            cursor="",  # 只读内容区默认箭头，链接处才变手型
        )
        self.content_scroll = ttk.Scrollbar(
            self.text_container, orient=tk.VERTICAL,
        )
        self.content_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.content_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.content_scroll.configure(command=self.content_text.yview)
        self.content_text.configure(yscrollcommand=self.content_scroll.set)
        self.content_text.configure(state=tk.DISABLED)

        # 内容区右键菜单
        self._build_content_context_menu()

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

    def _start_drag(self, event):
        self._drag_data["x"] = event.x_root
        self._drag_data["y"] = event.y_root
        if self._is_maximized:
            # 用比例记录点击位置（比绝对像素更准）
            win_w = self.root.winfo_width()
            click_x = event.x_root - self.root.winfo_rootx()
            ratio = click_x / win_w if win_w > 0 else 0.5
            # 对称限制，避免还原后鼠标落在边缘/按钮区域
            self._drag_data["title_ratio"] = max(0.12, min(ratio, 0.85))
            # 保存正常窗口尺寸
            if self._normal_geometry:
                m = re.search(r"(\d+)x(\d+)", self._normal_geometry)
                if m:
                    self._drag_data["normal_w"] = int(m.group(1))
                    self._drag_data["normal_h"] = int(m.group(2))
            # fallback
            self._drag_data.setdefault("normal_w", 1100)
            self._drag_data.setdefault("normal_h", 680)

    def _do_drag(self, event):
        if self._is_maximized:
            # 最大化状态下拉 → 还原并跟随鼠标
            if event.y_root > self._drag_data["y"] + 5:
                ratio = self._drag_data.get("title_ratio", 0.5)
                nw = self._drag_data.get("normal_w", 1100)
                nh = self._drag_data.get("normal_h", 680)
                new_x = event.x_root - int(nw * ratio)
                new_y = event.y_root - 5
                self.root.geometry(f"{nw}x{nh}+{int(new_x)}+{int(new_y)}")
                self._is_maximized = False
                self.max_btn.configure(text="□")
                self._drag_data["x"] = event.x_root
                self._drag_data["y"] = event.y_root
            return

        dx = event.x_root - self._drag_data["x"]
        dy = event.y_root - self._drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        # 限制不能拖出屏幕上方
        x = max(x, 0)
        y = max(y, 0)
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self._drag_data["x"] = event.x_root
        self._drag_data["y"] = event.y_root

        # 拖到屏幕顶端 → 自动最大化
        if y <= 0:
            self._maximize_window()
            self._drag_data["x"] = event.x_root
            self._drag_data["y"] = event.y_root

    # ── 最大化 / 还原 ──

    def _toggle_maximize(self):
        if self._is_maximized:
            self._restore_window()
        else:
            self._maximize_window()

    def _maximize_window(self):
        self._normal_geometry = self.root.geometry()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 用 0,0 到 sw x sh 铺满（保留任务栏的空间）
        # 简化：直接铺满屏幕
        self.root.geometry(f"{sw}x{sh}+0+0")
        self._is_maximized = True
        self.max_btn.configure(text="❐")

    def _minimize_window(self):
        """最小化窗口（overrideredirect 下 iconify 无效，用 ShowWindow）"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        except Exception:
            self.root.iconify()

    def _restore_window(self):
        if self._normal_geometry:
            self.root.geometry(self._normal_geometry)
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"1100x680+{sw//2-550}+{sh//2-340}")
        self._is_maximized = False
        self.max_btn.configure(text="□")

    # ── 调整窗口大小 ──

    def _get_resize_region(self, event):
        """判断鼠标在窗口哪个边缘/角（用屏幕绝对坐标）"""
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        x = event.x_root - rx
        y = event.y_root - ry

        on_left = x <= RESIZE_EDGE
        on_right = x >= w - RESIZE_EDGE
        on_top = y <= RESIZE_EDGE
        on_bottom = y >= h - RESIZE_EDGE

        # 优先检查角
        if on_top and on_left:
            return "nw"
        if on_top and on_right:
            return "ne"
        if on_bottom and on_left:
            return "sw"
        if on_bottom and on_right:
            return "se"
        # 再检查边
        if on_left:
            return "w"
        if on_right:
            return "e"
        if on_top:
            return "n"
        if on_bottom:
            return "s"
        return None

    def _update_cursor(self, event):
        """鼠标形状随边缘位置变化"""
        if self._is_maximized:
            return
        region = self._get_resize_region(event)
        cursors = {
            "n": "size_ns", "s": "size_ns",
            "e": "size_we", "w": "size_we",
            "ne": "size_ne_sw", "nw": "size_nw_se",
            "se": "size_nw_se", "sw": "size_ne_sw",
        }
        self.root.config(cursor=cursors.get(region, ""))
        self._resize_region = region

    def _start_resize(self, event):
        """记录初始窗口几何和鼠标位置"""
        if self._is_maximized:
            return
        region = self._get_resize_region(event)
        if not region:
            return
        self._resize_data = {
            "mouse_x": event.x_root,
            "mouse_y": event.y_root,
            "win_x": self.root.winfo_x(),
            "win_y": self.root.winfo_y(),
            "win_w": self.root.winfo_width(),
            "win_h": self.root.winfo_height(),
            "region": region,
        }

    def _do_resize(self, event):
        if not self._resize_data or self._is_maximized:
            return
        r = self._resize_data["region"]
        if not r:
            return

        # 获取初始值
        dx = event.x_root - self._resize_data["mouse_x"]
        dy = event.y_root - self._resize_data["mouse_y"]
        x0 = self._resize_data["win_x"]
        y0 = self._resize_data["win_y"]
        w0 = self._resize_data["win_w"]
        h0 = self._resize_data["win_h"]

        x, y, w, h = x0, y0, w0, h0

        # 对每个方向做判断（角包含两个方向）
        if "w" in r:
            x = x0 + dx
            w = w0 - dx
        if "e" in r:
            w = w0 + dx
        if "n" in r:
            y = y0 + dy
            h = h0 - dy
        if "s" in r:
            h = h0 + dy

        # 限制最小尺寸（同时防止翻转）
        mw, mh = self.root.minsize()
        if w < mw:
            if "w" in r:
                x = x0 + w0 - mw
            w = mw
        if h < mh:
            if "n" in r:
                y = y0 + h0 - mh
            h = mh

        self.root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")

    def _end_resize(self, event):
        self._resize_region = ""
        self._resize_data = None

    # ── 侧栏拖动调整宽度 ──

    def _start_sidebar_drag(self, event):
        self._sidebar_drag_x = event.x_root

    def _do_sidebar_drag(self, event):
        dx = event.x_root - self._sidebar_drag_x
        new_w = self._sidebar_width + dx
        max_w = max(300, self.root.winfo_width() // 2)
        new_w = max(0, min(new_w, max_w))

        # 拖到 <60 收起，收起后拖出 >20 弹开到 180
        MIN_OPEN = 180
        COLLAPSE_THRESHOLD = 60
        if self._sidebar_width > 0 and new_w < COLLAPSE_THRESHOLD:
            new_w = 0
        elif self._sidebar_width == 0 and new_w > 20:
            new_w = MIN_OPEN
        elif 0 < new_w < MIN_OPEN:
            new_w = MIN_OPEN

        if new_w != self._sidebar_width:
            self._sidebar_width = new_w
            self.side_frame.configure(width=new_w)
            self._sidebar_drag_x = event.x_root

    def _end_sidebar_drag(self, event):
        """侧栏拖动结束 → 持久化宽度"""
        self._save_settings()

    # ── Alt+Tab 修复 ──

    def _fix_alt_tab(self):
        """让 overrideredirect 窗口出现在 Alt+Tab 和任务栏"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            # GWL_EXSTYLE = -20
            current = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            # 移除 WS_EX_TOOLWINDOW (0x80)，添加 WS_EX_APPWINDOW (0x40000)
            new_style = (current & ~0x80) | 0x40000
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, new_style)
            # 强制刷新窗口框架，让任务栏识别
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                0x0002 | 0x0001 | 0x0020,  # NOMOVE | NOSIZE | FRAMECHANGED
            )
        except Exception:
            pass

    # ── Windows 原生窗口管理（Aero Snap） ──

    def _setup_win32_window_management(self):
        """
        通过拦截 WM_NCHITTEST 让 Windows 接管标题栏交互。
        返回 HTCAPTION → Windows 处理：
          - 拖拽移动 + 拖到顶部最大化
          - 双击最大化/还原
          - Win+↑/↓ 窗口管理
        按钮区域则放行（HTCLIENT），让 tkinter 正常响应。
        """
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

            # 窗口过程类型
            WindowProc = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t,  # LRESULT
                ctypes.c_ssize_t,  # HWND
                ctypes.c_uint32,   # UINT
                ctypes.c_ssize_t,  # WPARAM
                ctypes.c_ssize_t,  # LPARAM
            )

            # 存储原始窗口过程地址
            self._win32_original_proc = None

            TITLEBAR_HEIGHT = 30
            BUTTON_AREA_WIDTH = 120
            EDGE = 8       # 上/下/左边框
            EDGE_R = 5     # 右边框稍窄，避免和滚动条冲突

            @WindowProc
            def wndproc(hwnd, msg, wparam, lparam):
                # ── WM_NCHITTEST：Windows 原生边框拖拽 + 标题栏 ──
                if msg == 0x0084:
                    x = ctypes.c_int16(lparam & 0xFFFF).value
                    y = ctypes.c_int16((lparam >> 16) & 0xFFFF).value

                    rect = (ctypes.c_long * 4)()
                    ctypes.windll.user32.GetWindowRect(hwnd, rect)
                    rel_x = x - rect[0]
                    rel_y = y - rect[1]
                    win_w = rect[2] - rect[0]
                    win_h = rect[3] - rect[1]

                    on_left = rel_x < EDGE
                    on_right = rel_x > win_w - EDGE_R
                    on_top = rel_y < EDGE
                    on_bottom = rel_y > win_h - EDGE

                    # 标题栏区域（按钮排除在外）
                    if on_top and rel_y < TITLEBAR_HEIGHT:
                        try:
                            btn_frame = self.titlebar.winfo_children()[-1]
                            btn_left = btn_frame.winfo_rootx()
                            if x >= btn_left:
                                return 1  # HTCLIENT
                        except Exception:
                            if x >= rect[2] - BUTTON_AREA_WIDTH:
                                return 1
                        if self._is_maximized:
                            return 1  # HTCLIENT
                        return 2  # HTCAPTION

                    # 四角
                    if on_left and on_top:
                        return 13   # HTTOPLEFT
                    if on_right and on_top:
                        return 14   # HTTOPRIGHT
                    if on_left and on_bottom:
                        return 16   # HTBOTTOMLEFT
                    if on_right and on_bottom:
                        return 17   # HTBOTTOMRIGHT
                    # 四边
                    if on_left:
                        return 10   # HTLEFT
                    if on_right:
                        return 11   # HTRIGHT
                    if on_top:
                        return 12   # HTTOP
                    if on_bottom:
                        return 15   # HTBOTTOM

                # ── WM_ERASEBKGND：阻止闪烁 ──
                if msg == 0x0014:
                    return 1  # 已自行处理背景，禁止系统擦除

                # ── WM_SIZE：同步窗口状态 ──
                if msg == 0x0005:
                    if wparam == 2:  # SIZE_MAXIMIZED
                        if not self._is_maximized:
                            self._is_maximized = True
                            self.root.after_idle(
                                lambda: self.max_btn.configure(text="❐")
                            )
                    elif wparam == 1:  # SIZE_RESTORED
                        if self._is_maximized:
                            self._is_maximized = False
                            self._normal_geometry = self.root.geometry()
                            self.root.after_idle(
                                lambda: self.max_btn.configure(text="□")
                            )

                # 链式调用原始窗口过程
                if self._win32_original_proc is not None:
                    return ctypes.windll.user32.CallWindowProcW(
                        ctypes.c_void_p(self._win32_original_proc),
                        hwnd, msg, wparam, lparam,
                    )
                return 0

            # 保存引用以防 Python GC 回收
            self._win32_wndproc = wndproc

            # 设置新窗口过程
            ctypes.windll.user32.SetWindowLongPtrW.argtypes = [
                ctypes.c_ssize_t,   # HWND
                ctypes.c_int,       # nIndex
                ctypes.c_void_p,    # dwNewLong
            ]
            ctypes.windll.user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            ctypes.windll.user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p,    # lpPrevWndFunc
                ctypes.c_ssize_t,   # hWnd
                ctypes.c_uint32,    # Msg
                ctypes.c_ssize_t,   # wParam
                ctypes.c_ssize_t,   # lParam
            ]
            ctypes.windll.user32.CallWindowProcW.restype = ctypes.c_ssize_t

            self._win32_original_proc = ctypes.windll.user32.SetWindowLongPtrW(
                hwnd, -4,  # GWLP_WNDPROC
                ctypes.cast(wndproc, ctypes.c_void_p).value,
            )
        except Exception:
            pass  # 失败则回退到手动拖拽

    # ══════════════════════════════════
    # 主题
    # ══════════════════════════════════

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
            # 重新渲染当前笔记（使用新主题色 + 正确的字号）
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
    # ══════════════════════════════════

    def _show_files(self, toggle=True):
        # 点击当前激活的文件图标 → 收起/展开侧栏（VSCode 风格）
        if (toggle and self.current_panel == "files"
                and self._sidebar_width > 0):
            self._toggle_sidebar()
            return
        self.current_panel = "files"
        self.tag_frame.grid_remove()
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
        self.tag_frame.grid(row=0, column=0, sticky="nsew")
        self._restore_sidebar_if_collapsed()
        self._update_nav_icons()
        self._refresh_tags()
        self._apply_file_tags_visibility()
        self._refresh_file_tags()

    def _restore_sidebar_if_collapsed(self):
        """如果侧栏被收起（拖拽或菜单隐藏），展开到记忆/默认宽度"""
        if self._sidebar_width < 50:
            self._sidebar_width = getattr(self, '_prev_sidebar_width', 240)
            self.side_frame.configure(width=self._sidebar_width)
            # 确保 grid 中可见（_toggle_sidebar 可能已 grid_remove）
            if not self.side_frame.winfo_ismapped():
                self.side_frame.grid(row=0, column=1, sticky="ns")
                self._grip.grid(row=0, column=2, sticky="ns")

    def _create_note(self, default_dir=""):
        """弹出新建笔记对话框"""
        from file_handler import get_all_subdirs, create_note

        dialog = self._make_dialog(self.root, "新建笔记", 400, 240)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        # 笔记标题
        tk.Label(frame, text="笔记标题：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        title_var = tk.StringVar()
        title_entry = tk.Entry(frame, textvariable=title_var,
                                font=("Microsoft YaHei", 10), relief=tk.SUNKEN)
        title_entry.pack(fill=tk.X, pady=(0, 12))
        title_entry.focus_set()

        # 存放目录
        tk.Label(frame, text="存放目录：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        dir_frame = tk.Frame(frame)
        dir_frame.pack(fill=tk.X, pady=(0, 16))
        dir_var = tk.StringVar(value=default_dir if default_dir else "(根目录)")
        dir_label = tk.Label(dir_frame, textvariable=dir_var,
                             font=("Microsoft YaHei", 9),
                             bg="#fff", fg="#333",
                             anchor=tk.W, padx=8, pady=3,
                             relief=tk.SUNKEN)
        dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        browse_btn = tk.Button(dir_frame, text="浏览…",
                               font=("Microsoft YaHei", 9),
                               command=lambda: self._select_dir_dialog(
                                   dialog, dir_var, default_dir))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # 按钮行
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def do_create():
            title = title_var.get().strip()
            if not title:
                return
            subdir_raw = dir_var.get()
            subdir = "" if subdir_raw == "(根目录)" else subdir_raw
            rel_path = create_note(title, subdir)
            if rel_path:
                dialog.destroy()
                self._refresh_file_tree()
                self._snapshot_files()  # 抑制轮询自触发
                self._display_note(rel_path)

        tk.Button(btn_frame, text="取消",
                  font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="创建",
                  font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)

        title_entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)

    def _make_dialog(self, parent, title, width, height):
        """创建无边框对话框，带自定义标题栏"""
        win = tk.Toplevel(parent)
        win.overrideredirect(True)
        # 不在创建时 grab — 此时窗口在 (0,0) 默认位置，
        # grab 会锁死位置，后续 MoveWindow/geometry 全部无效
        win.configure(bg=self.colors["sidebar_bg"])
        win.resizable(False, False)

        # ── 自定义标题栏 ──
        bar = tk.Frame(win, height=28)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        lbl = tk.Label(bar, text=f"  {title}", font=("Microsoft YaHei", 10),
                       anchor=tk.W)
        lbl.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cls = tk.Button(bar, text="✕", font=("Segoe UI", 9),
                       relief=tk.FLAT, bd=0, padx=8,
                       command=win.destroy)
        cls.pack(side=tk.RIGHT, fill=tk.Y)

        # 拖拽
        def _start(e):
            win._dx = e.x_root
            win._dy = e.y_root
        def _drag(e):
            x = win.winfo_x() + e.x_root - win._dx
            y = win.winfo_y() + e.y_root - win._dy
            win.geometry(f"+{x}+{y}")
            win._dx = e.x_root
            win._dy = e.y_root
        for w in (bar, lbl):
            w.bind("<Button-1>", _start)
            w.bind("<B1-Motion>", _drag)

        # ── 主题着色（仅标题栏）──
        c = self.colors
        bar.configure(bg=c["toolbar_bg"])
        lbl.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"])
        cls.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                      activebackground="#e81123" if self.theme_mode == "light" else "#c03333")
        win._titlebar = bar
        win._dialog_width = width
        win._dialog_height = height

        return win

    def _theme_dialog_body(self, win):
        """对对话框内部所有控件应用主题色 + 定位（在所有控件添加完成后调用）"""
        c = self.colors

        def _recurse(widget):
            if widget is getattr(win, '_titlebar', None):
                return
            if isinstance(widget, tk.Frame):
                widget.configure(bg=c["sidebar_bg"], bd=0, highlightthickness=0,
                                 highlightbackground=c["sidebar_bg"])
            elif isinstance(widget, tk.Label):
                widget.configure(bg=c["sidebar_bg"], fg=c["sidebar_fg"])
            elif isinstance(widget, tk.Entry):
                widget.configure(
                    bg=c["content_bg"], fg=c["content_fg"],
                    insertbackground=c["content_fg"],
                    relief=tk.SUNKEN,
                )
            elif isinstance(widget, tk.Button):
                widget.configure(
                    bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                    activebackground=c["toolbar_btn_hover"],
                    activeforeground=c["toolbar_btn_fg"],
                    relief=tk.RIDGE, bd=1,
                    highlightthickness=0,
                    padx=12,
                )
            elif isinstance(widget, ttk.Treeview):
                # 对话框内 Treeview（目录选择器）需要可见细边框
                _style_key = f"dialog_treeview_{id(widget)}"
                s = ttk.Style()
                s.configure(_style_key,
                    background=c["sidebar_bg"], foreground=c["sidebar_fg"],
                    fieldbackground=c["sidebar_bg"],
                    borderwidth=1, lightcolor=c["separator"],
                    darkcolor=c["separator"], bordercolor=c["separator"],
                    font=("Microsoft YaHei", 10), rowheight=26, indent=14,
                )
                s.map(_style_key,
                    background=[("selected", c["sidebar_item_selected"])],
                    foreground=[("selected", c["sidebar_fg"])])
                widget.configure(style=_style_key)
            for child in widget.winfo_children():
                _recurse(child)

        for child in win.winfo_children():
            _recurse(child)

        # ── 窗口外边框 ──
        border_c = "#555555" if self.theme_mode == "dark" else "#777777"
        win.configure(highlightthickness=1, highlightbackground=border_c,
                      highlightcolor=border_c)

        # ── 屏幕居中：grab 后 geometry + MoveWindow 覆盖 ──
        w = getattr(win, '_dialog_width', 400)
        h = getattr(win, '_dialog_height', 300)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        win.attributes('-topmost', True)
        win.grab_set()
        win.update_idletasks()
        win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        try:
            hwnd = win.winfo_id()
            ctypes.windll.user32.MoveWindow(hwnd, x, y, w, h, True)
        except Exception:
            pass
        win.lift()
        win.focus_force()

        # ── Escape 关闭 ──
        win.bind("<Escape>", lambda e: win.destroy())

        # ── 点击外部关闭 ──
        _closed = []
        def _on_outside(event):
            if _closed or not win.winfo_exists():
                return
            try:
                wx = win.winfo_rootx()
                wy = win.winfo_rooty()
                ww = win.winfo_width()
                wh = win.winfo_height()
                if not (wx <= event.x_root <= wx + ww and
                        wy <= event.y_root <= wy + wh):
                    _closed.append(True)
                    win.destroy()
            except tk.TclError:
                pass

        _outside_id = self.root.bind("<Button-1>", _on_outside, add="+")
        def _cleanup():
            try:
                self.root.unbind("<Button-1>", _outside_id)
            except tk.TclError:
                pass
        win.bind("<Destroy>", lambda e: _cleanup(), add="+")

    def _offset_from_parent(self, win, parent, w, h):
        """将窗口放在父窗口右下方偏移位置"""
        self.root.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - w) // 2 + 40
        y = py + (ph - h) // 2 + 20
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _select_dir_dialog(self, parent_win, result_var, current_dir=""):
        """弹出树状目录选择对话框，完全手动构建避免 grab/position 冲突"""
        from file_handler import list_notes_tree

        c = self.colors
        W, H = 380, 450

        # 释放父对话框 grab + 关闭 topmost
        try:
            parent_win.grab_release()
            parent_win.attributes('-topmost', False)
        except tk.TclError:
            pass

        # ── 完全手动创建窗口（不用 _make_dialog，避免 grab 锁位置）──
        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        border_c = "#555555" if self.theme_mode == "dark" else "#777777"
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=border_c,
                         highlightcolor=border_c)
        dialog.resizable(False, False)

        # 标题栏
        bar = tk.Frame(dialog, height=28, bg=c["toolbar_bg"])
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  选择目录", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=c["toolbar_bg"], fg=c["toolbar_fg"]
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=dialog.destroy,
                  bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                  activebackground=("#e81123" if self.theme_mode == "light" else "#c03333")
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        # 拖拽
        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root
        def _drag_move(e):
            dialog.geometry(f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                            f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root
        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # 关闭恢复
        def _restore_parent():
            try:
                parent_win.attributes('-topmost', True)
                parent_win.grab_set()
            except tk.TclError:
                pass
        dialog.bind("<Destroy>", lambda e: _restore_parent(), add="+")

        # Treeview
        tree = ttk.Treeview(dialog, show="tree", selectmode="browse")
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(14, 0))
        tree.bind("<<TreeviewSelect>>", lambda e: _auto_open())
        def _auto_open():
            sel = tree.selection()
            if sel:
                tree.item(sel[0], open=not tree.item(sel[0], "open"))

        root_iid = tree.insert("", "end", text="(根目录)", open=True)
        def _populate(parent_iid, items):
            for item in items:
                if not item["is_dir"]:
                    continue
                node = tree.insert(parent_iid, "end",
                                   text=item["name"], values=(item["path"],))
                if item["children"]:
                    _populate(node, item["children"])

        tree_data = list_notes_tree()
        if tree_data:
            _populate(root_iid, tree_data)
        if current_dir:
            for item in tree.get_children(root_iid):
                vals = tree.item(item, "values")
                if vals and vals[0] == current_dir:
                    tree.selection_set(item)
                    tree.see(item)
                    break

        # 按钮
        btn_frame = tk.Frame(dialog, bg=c["sidebar_bg"], bd=0, highlightthickness=0)
        btn_frame.pack(fill=tk.X, padx=14, pady=14)
        def confirm():
            sel = tree.selection()
            if sel:
                vals = tree.item(sel[0], "values")
                result_var.set(vals[0] if vals else "(根目录)")
            else:
                result_var.set("(根目录)")
            dialog.destroy()
        tree.bind("<Double-Button-1>", lambda e: confirm())
        for text, cmd in [("确定", confirm), ("取消", dialog.destroy)]:
            btn = tk.Button(btn_frame, text=text, command=cmd,
                            font=("Microsoft YaHei", 9),
                            bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                            activebackground=c["toolbar_btn_hover"],
                            activeforeground=c["toolbar_btn_fg"],
                            relief=tk.RIDGE, bd=1, highlightthickness=0,
                            highlightbackground=c["toolbar_btn_bg"], padx=12)
            btn.pack(side=tk.RIGHT, padx=(10, 0) if text == "确定" else 0)

        # Treeview 样式（必须以 .Treeview 结尾）
        _sk = f"dir_{id(tree)}.Treeview"
        s = ttk.Style()
        s.configure(_sk, background=c["sidebar_bg"], foreground=c["sidebar_fg"],
                    fieldbackground=c["sidebar_bg"],
                    borderwidth=1, lightcolor="#555555" if self.theme_mode == "dark" else "#999999",
                    darkcolor="#555555" if self.theme_mode == "dark" else "#999999",
                    bordercolor="#555555" if self.theme_mode == "dark" else "#999999",
                    font=("Microsoft YaHei", 10), rowheight=26, indent=14)
        s.map(_sk, background=[("selected", c["sidebar_item_selected"])],
              foreground=[("selected", c["sidebar_fg"])])
        tree.configure(style=_sk)

        # ── 居中定位：geometry + MoveWindow 缺一不可 ──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{x}+{y}")
        hwnd = dialog.winfo_id()
        ctypes.windll.user32.MoveWindow(hwnd, x, y, W, H, True)
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _create_folder(self, default_dir=""):
        """弹出新建文件夹对话框（含目录选择）"""
        from file_handler import make_subdir, get_all_subdirs

        dialog = self._make_dialog(self.root, "新建文件夹", 400, 250)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        # 父目录选择
        tk.Label(frame, text="所在目录：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        dir_frame = tk.Frame(frame)
        dir_frame.pack(fill=tk.X, pady=(0, 12))
        parent_var = tk.StringVar(value=default_dir if default_dir else "(根目录)")
        dir_label = tk.Label(dir_frame, textvariable=parent_var,
                             font=("Microsoft YaHei", 9),
                             bg="#fff", fg="#333",
                             anchor=tk.W, padx=8, pady=3,
                             relief=tk.SUNKEN)
        dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        browse_btn = tk.Button(dir_frame, text="浏览…",
                               font=("Microsoft YaHei", 9),
                               command=lambda: self._select_dir_dialog(
                                   dialog, parent_var, default_dir))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # 文件夹名称
        tk.Label(frame, text="文件夹名称：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        name_var = tk.StringVar(value="new_folder")
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10), relief=tk.SUNKEN)
        entry.pack(fill=tk.X, pady=(0, 14))
        entry.select_range(0, tk.END)
        entry.focus_set()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def do_create():
            name = name_var.get().strip()
            if name:
                raw = parent_var.get()
                parent = "" if raw == "(根目录)" else raw
                make_subdir(parent, name)
                dialog.destroy()
                self._refresh_file_tree()

        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="创建", font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)

    def _update_nav_icons(self):
        """根据当前主题色和活动面板刷新图标"""
        active = self.colors["nav_active_fg"]
        inactive = self.colors["nav_fg"]
        self._nav_files_img = icon_renderer.folder_icon(
            active if self.current_panel == "files" else inactive
        )
        self.nav_files_btn.configure(image=self._nav_files_img)
        self._nav_tags_img = icon_renderer.tag_icon(
            active if self.current_panel == "tags" else inactive
        )
        self.nav_tags_btn.configure(image=self._nav_tags_img)

    # ══════════════════════════════════
    # 文件树
    # ══════════════════════════════════

    def _refresh_file_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        tree = list_notes_tree()
        if not tree:
            self.tree.insert("", "end", text="   暂无笔记")
            self.status_left.configure(text="   0 个笔记")
            return
        count = self._populate_tree("", tree)
        self.status_left.configure(text=f"   {count} 个笔记")

    def _populate_tree(self, parent_iid, items):
        """递归填充树节点，返回文件数"""
        file_count = 0
        for item in items:
            iid = item["path"]
            if item["is_dir"]:
                display = f" 📁 {item['name']}"
                node = self.tree.insert(
                    parent_iid, "end", iid=iid,
                    text=display, values=(iid, True),
                )
                if item["children"]:
                    file_count += self._populate_tree(node, item["children"])
                else:
                    self.tree.insert(node, "end", text="")
            else:
                display = f" 📄 {item['name']}"
                file_iid = f"f:{iid}"  # 前缀区分，避免与同名文件夹冲突
                self.tree.insert(
                    parent_iid, "end", iid=file_iid,
                    text=display, values=(iid, False),
                )
                file_count += 1
        return file_count

    def _on_file_selected(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        vals = self.tree.item(selected[0], "values")
        if not vals:
            return
        if vals[0] == "__header__":
            return
        # 搜索片段点击 → 跳转到内容中的关键词位置
        if isinstance(vals[0], str) and vals[0].startswith("__snippet_"):
            idx = int(vals[0].split("_")[-1])
            self._jump_to_search_match(idx)
            return
        iid, is_dir = vals[0], vals[1]
        if getattr(self, '_right_clicking', False):
            self._right_clicking = False
            return
        if is_dir == "True" or is_dir is True:
            if self.tree.item(selected[0], "open"):
                self.tree.item(selected[0], open=False)
            else:
                self.tree.item(selected[0], open=True)
            return
        self._display_note(iid)

    def _jump_to_search_match(self, idx):
        """在已渲染内容中查找第 idx 个关键词并滚动选中"""
        kw = getattr(self, '_cur_keyword', '')
        if not kw:
            return
        count = 0
        pos = "1.0"
        self.content_text.configure(state=tk.NORMAL)
        while True:
            pos = self.content_text.search(kw, pos, nocase=True,
                                           stopindex=tk.END)
            if not pos:
                break
            if count == idx:
                line = int(pos.split(".")[0])
                total = int(self.content_text.index("end-1c").split(".")[0])
                frac = (line - 1) / max(total, 1)
                self.content_text.yview_moveto(frac)
                end = f"{pos}+{len(kw)}c"
                # 使用自定义 tag 而非 tk.SEL：后者依赖控件焦点，
                # 失焦时选中高亮不会显示，故用自定义 tag；
                # 基色按 alpha 与内容区背景混合，等效半透明且自适应主题
                base_bg = self.content_text.cget("bg")
                hit_bg = _blend_hex(SEARCH_HIT_COLOR, base_bg,
                                    SEARCH_HIT_ALPHA)
                self.content_text.tag_configure(
                    "search_hit", background=hit_bg,
                    foreground=_readable_fg(hit_bg))
                self.content_text.tag_remove("search_hit", "1.0", tk.END)
                self.content_text.tag_add("search_hit", pos, end)
                self.content_text.see(pos)
                self.content_text.configure(state=tk.DISABLED)
                return
            count += 1
            pos = f"{pos}+1c"
        # 未命中（索引越界）：清除上一次的高亮，避免残留
        self.content_text.tag_remove("search_hit", "1.0", tk.END)
        self.content_text.configure(state=tk.DISABLED)

    # ══════════════════════════════════
    # 标签
    # ══════════════════════════════════

    def _refresh_tags(self):
        """重建标签树（从 index.json 缓存读取，不重新扫描）"""
        self.tag_tree.delete(*self.tag_tree.get_children())
        self.tag_intersection_label.configure(text="")

        tag_index = get_tag_index()
        if not tag_index:
            self.tag_tree.insert("", "end",
                                 text="  暂无标签",
                                 iid="__notags__")
            self.tag_tree.item("__notags__", tags=())
            return

        search_text = self.tag_search_var.get().strip().lower()
        if search_text == self._tag_search_placeholder.lower():
            search_text = ""
        any_visible = False

        for tag, files in tag_index.items():
            if search_text and search_text not in tag.lower():
                continue
            any_visible = True
            count = len(files)
            iid = f"tag_{tag}"
            display = f" {tag}  ({count})"
            self.tag_tree.insert("", "end", iid=iid, text=display, open=False)

            for fpath in files:
                name = fpath.split("/")[-1]
                fid = f"file_{tag}_{fpath}"
                self.tag_tree.insert(iid, "end", iid=fid,
                                     text=f"  {name}",
                                     values=(fpath,))
                self.tag_tree.item(fid, tags=("file_node",))

        if not any_visible:
            if search_text:
                self.tag_tree.insert("", "end",
                                     text=f"  未找到 \"{search_text}\"",
                                     iid="__noresult__")
                self.tag_tree.item("__noresult__", tags=())
            else:
                self.tag_tree.insert("", "end",
                                     text="  暂无标签",
                                     iid="__notags__")
                self.tag_tree.item("__notags__", tags=())

    def _on_tag_search(self):
        """实时过滤标签列表（忽略占位文字）"""
        if self.tag_search_var.get() == self._tag_search_placeholder:
            return
        self._refresh_tags()

    def _on_tag_search_focus_in(self, event):
        """搜索框获得焦点时清除占位文字"""
        if self.tag_search_entry.get() == self._tag_search_placeholder:
            self.tag_search_entry.delete(0, tk.END)
            self.tag_search_entry.configure(fg=self.colors["search_fg"])

    def _on_tag_search_focus_out(self, event):
        """搜索框失去焦点时若为空则恢复占位文字"""
        if not self.tag_search_var.get().strip():
            self.tag_search_entry.delete(0, tk.END)
            self.tag_search_entry.insert(0, self._tag_search_placeholder)
            ph_color = "#777" if self.theme_mode == "dark" else "#999"
            self.tag_search_entry.configure(fg=ph_color)

    def _on_tag_tree_select(self, event):
        """标签树选中：单标签切换展开，多标签显示交集"""
        sel = self.tag_tree.selection()
        tag_iids = [i for i in sel if i.startswith("tag_")]

        # 点击交集分组或其内部文件时保持交集显示：
        # 否则选中状态变化会被误判为"标签不足 2 个"，刚算出的交集立刻被清掉
        if any(i.startswith(("__intersection__", "__intf_")) for i in sel):
            return

        if len(tag_iids) == 0:
            self.tag_intersection_label.configure(text="")
            self._clear_tag_intersection()
            return

        if len(tag_iids) == 1:
            self.tag_intersection_label.configure(text="")
            self._clear_tag_intersection()
        else:
            self._update_tag_intersection(tag_iids)

    def _on_tag_tree_click(self, event):
        """单击标签节点 → 展开/折叠"""
        iid = self.tag_tree.identify_row(event.y)
        if not iid or not iid.startswith("tag_"):
            return

        # 只对单选的标签切换展开
        sel = self.tag_tree.selection()
        tag_iids = [i for i in sel if i.startswith("tag_")]
        if len(tag_iids) == 1 and tag_iids[0] == iid:
            current = self.tag_tree.item(iid, "open")
            self.tag_tree.item(iid, open=not current)

    def _on_tag_tree_double_click(self, event):
        """双击文件节点 → 打开笔记"""
        iid = self.tag_tree.identify_row(event.y)
        if not iid:
            return
        vals = self.tag_tree.item(iid, "values")
        if vals:
            fpath = vals[0]
            self._display_note(fpath)
            # 同步选中文件树节点
            try:
                self.tree.selection_set(f"f:{fpath}")
                self.tree.see(f"f:{fpath}")
            except Exception:
                pass

    def _clear_tag_intersection(self):
        """移除树中的交集分组节点，并清空交集状态"""
        self._tag_intersection = None
        try:
            if self.tag_tree.exists("__intersection__"):
                self.tag_tree.delete("__intersection__")
        except tk.TclError:
            pass

    def _update_tag_intersection(self, tag_iids):
        """多选标签时在树顶部展示交集文件列表（交集由 file_handler 计算）"""
        self._clear_tag_intersection()

        tag_names = [iid[4:] for iid in tag_iids]  # 去掉 "tag_" 前缀
        matched, files = intersect_tags(tag_names)

        if len(matched) < 2:
            self.tag_intersection_label.configure(text="")
            return

        self._tag_intersection = (matched, files)
        tag_str = " ∩ ".join(matched)
        count = len(files)
        if count == 0:
            self.tag_intersection_label.configure(
                text=f"  {tag_str} → 没有共同文件")
            return
        self.tag_intersection_label.configure(
            text=f"  {tag_str} → {count} 个文件"
        )

        # 在标签树顶部插入交集分组，双击文件可打开
        inter_iid = self.tag_tree.insert(
            "", "end", iid="__intersection__", open=True,
            text=f"  {tag_str} ({count})")
        self.tag_tree.item(inter_iid, tags=("tag_",))
        for idx, fpath in enumerate(files):
            name = fpath.split("/")[-1]
            fid = f"__intf_{idx}"
            self.tag_tree.insert(inter_iid, "end", iid=fid,
                                 text=f"  {name}", values=(fpath,))
            self.tag_tree.item(fid, tags=("file_node",))
        self.tag_tree.see(inter_iid)

    def _get_selected_tag_names(self):
        """返回当前选中的标签名列表"""
        sel = self.tag_tree.selection()
        return [i[4:] for i in sel if i.startswith("tag_")]

    def _on_tag_tree_motion(self, event):
        """标签树行鼠标悬停 → 高亮"""
        iid = self.tag_tree.identify_row(event.y)
        prev = getattr(self, '_tag_tree_hover_item', None)
        if prev and prev != iid:
            try:
                self.tag_tree.item(prev, tags=())
            except tk.TclError:
                pass
        if iid and iid.startswith("tag_"):
            self.tag_tree.item(iid, tags=('hover',))
            self._tag_tree_hover_item = iid
        else:
            self._tag_tree_hover_item = None

    def _on_tag_tree_leave(self, event):
        """鼠标离开标签树 → 清除悬停高亮"""
        prev = getattr(self, '_tag_tree_hover_item', None)
        if prev:
            try:
                self.tag_tree.item(prev, tags=())
            except tk.TclError:
                pass
            self._tag_tree_hover_item = None

    # ══════════════════════════════════
    # 内容
    # ══════════════════════════════════

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

    def _render_markdown(self, md_text):
        from markdown_renderer import render_markdown
        self.content_text.configure(state=tk.NORMAL)
        render_markdown(self.content_text, md_text,
                         link_callback=self._navigate_to_link,
                         font_size=self._font_size)

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
                        import webbrowser
                        webbrowser.open(url)
                    return
        except Exception:
            pass

    def _set_extlink_hint(self, url):
        """进入外部链接时在状态栏显示操作提示"""
        if not getattr(self, '_hint_saved_status', False):
            self._hint_saved_status = True
            self._hint_prev_text = self.status_left.cget("text")
        self.status_left.configure(text=f"   Ctrl+点击 打开：{url}")

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

    # ══════════════════════════════════
    # 搜索
    # ══════════════════════════════════

    def _on_search_var_changed(self):
        """搜索框内容变化：有输入才显示清空按钮；清空则恢复文件树"""
        try:
            if self.search_var.get().strip():
                self.search_clear_lbl.pack(side=tk.LEFT, padx=(0, 2),
                                           before=self.search_btn)
            else:
                self.search_clear_lbl.pack_forget()
                if self.current_panel == "files":
                    self._refresh_file_tree()
        except Exception:
            pass

    def _clear_search(self):
        """清空搜索框并恢复文件树，焦点回到输入框"""
        self.search_var.set("")
        self.search_entry.focus_set()

    def _do_search(self):
        keyword = self.search_var.get().strip()
        keyword_lower = keyword.lower()
        if not keyword:
            return

        if self.current_panel != "files":
            self._show_files()
        for item in self.tree.get_children():
            self.tree.delete(item)

        cur = self._current_note_path
        # 全库遍历匹配由 search_engine 负责
        name_matches, content_matches, cur_content_hit = \
            search_engine.search_notes(keyword, cur)
        # 命中数需在已渲染内容中统计，仍由 GUI 处理
        cur_hit_count = (self._count_matches(keyword_lower)
                         if (cur and cur_content_hit) else 0)

        total = len(name_matches) + len(content_matches)
        if total == 0 and cur_hit_count == 0:
            self.tree.insert("", "end", text=f"  未找到 \"{keyword}\"")
            self._set_content(f"未找到包含 \"{keyword}\" 的笔记。")
            self.status_left.configure(text="   未找到结果")
            return

        total += cur_hit_count
        self.tree.insert("", "end",
            text=f"  搜索结果 \"{keyword}\" ({total})",
            values=("__header__",), open=True)

        # ① 当前文件
        if cur_hit_count > 0 and cur:
            piid = self.tree.insert("", "end",
                text=f"  当前文件 ({cur_hit_count})", open=True,
                values=("__header__",))
            # 提取每个匹配位的小段摘要
            snippets = self._extract_text_snippets(keyword_lower)
            for i, snip_text in enumerate(snippets[:cur_hit_count]):
                self.tree.insert(piid, "end",
                    text=f"[{i+1}] {snip_text}",
                    values=(f"__snippet_{i}",))
            if cur in name_matches:
                name_matches.remove(cur)
            if cur in content_matches:
                content_matches.remove(cur)

        # ② 文件名匹配
        if name_matches:
            piid = self.tree.insert("", "end",
                text=f"  文件名匹配 ({len(name_matches)})", open=True,
                values=("__header__",))
            for p in name_matches:
                self.tree.insert(piid, "end", text=p.split("/")[-1],
                    values=(p, False))

        # ③ 内容匹配
        if content_matches:
            piid = self.tree.insert("", "end",
                text=f"  内容匹配 ({len(content_matches)})", open=True,
                values=("__header__",))
            for p in content_matches:
                self.tree.insert(piid, "end", text=p.split("/")[-1],
                    values=(p, False))

        self._cur_keyword = keyword_lower
        self._cur_hit_count = cur_hit_count
        self.status_left.configure(text=f"   结果 {total}")

    def _count_matches(self, keyword):
        """统计已渲染内容中关键词出现次数"""
        count = 0
        pos = "1.0"
        while True:
            pos = self.content_text.search(keyword, pos, nocase=True,
                                           stopindex=tk.END)
            if not pos:
                break
            count += 1
            pos = f"{pos}+1c"
        return count

    def _extract_text_snippets(self, keyword, max_count=10):
        """从已渲染内容中提取关键词短片段（前后各6字 + 省略号）"""
        results = []
        pos = "1.0"
        ctx = 6
        while True:
            pos = self.content_text.search(keyword, pos, nocase=True,
                                           stopindex=tk.END)
            if not pos:
                break
            # 提取前后各 ctx 字符
            start = f"{pos}-{ctx}c"
            end = f"{pos}+{len(keyword)+ctx}c"
            s = self.content_text.get(start, end).replace("\n", " ").strip()
            # 添加省略号
            if self.content_text.compare(start, ">", "1.0"):
                s = "..." + s
            if self.content_text.compare(end, "<", "end-1c"):
                s = s + "..."
            if s not in results:
                results.append(s)
            pos = f"{pos}+1c"
            if len(results) >= max_count:
                break
        return results

    # ══════════════════════════════════
    # 视图菜单
    # ══════════════════════════════════

    def _get_view_menu_items(self):
        """动态生成视图菜单（带复选框状态）"""
        follow = self._follow_system_theme
        sidebar_visible = self._sidebar_width > 0
        sidebar_text = "隐藏侧栏" if sidebar_visible else "显示侧栏"
        return [
            ("字号…", self._open_font_dialog),
            ("切换主题", self._toggle_theme),
            (sidebar_text, self._toggle_sidebar),
            None,
            (f"跟随系统主题  {'✓' if follow else ''}", self._toggle_follow_system_theme),
        ]

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

    def _open_help(self, category=None):
        """打开帮助面板（左分类 + 右内容，可拖动分隔）"""
        # 两级结构：{分类: [(小节标题, [(类型, 文本), ...]), ...]}
        sections = {
            "操作指南": [
                ("打开与浏览", [
                    ("p", "· 单击左侧文件树中的文件名，即可在右侧打开笔记。"),
                    ("p", "· 内容区右上角 ☀ / 🌙 图标切换亮色 / 暗色主题。"),
                    ("p", "· 拖拽面板之间的分隔条可调整侧栏宽度。"),
                ]),
                ("搜索", [
                    ("p", "· 在顶部搜索框输入关键词后回车；清空搜索框会自动返回文件树。"),
                    ("p", "· 结果分三组，依次是：当前文件 → 文件名匹配 → 内容匹配。"),
                    ("p", "· 当前文件会列出每处匹配的上下文片段，点击片段可滚动到"),
                    ("p", "  正文对应位置并选中该关键词。"),
                    ("p", "· 检索为关键词遍历匹配，不支持模糊匹配与布尔查询。"),
                ]),
                ("标签与交集", [
                    ("p", "· 单击标签展开其下的笔记列表，双击笔记名打开。"),
                    ("p", "· 选中多个标签，即可求同时含这些标签的笔记（交集）："),
                    ("p", "    Ctrl  + 点击  →  逐个加选或取消，适合不相邻的标签"),
                    ("p", "    Shift + 点击  →  选中两次点击之间的连续范围"),
                    ("p", "· 顶部显示「标签A ∩ 标签B → N 个文件」，双击列表项打开笔记。"),
                ]),
                ("链接跳转", [
                    ("p", "· 点击正文中的 [[笔记名]] 可跳转到对应笔记。"),
                    ("p", "· Ctrl + 点击正文中的网址，用默认浏览器打开。"),
                    ("p", "  注意：直接书写的裸网址不会被识别，需按「笔记格式」中的写法。"),
                ]),
                ("右键菜单", [
                    ("p", "· 文件树右键：新建笔记 / 新建文件夹 / 重命名 / 删除 /"),
                    ("p", "  在资源管理器中显示 / 用外部编辑器打开。"),
                    ("p", "· 表格单元格右键：复制单元格内容。"),
                ]),
            ],
            "笔记格式": [
                ("YAML 元数据", [
                    ("p", "写在 .md 文件开头，用 --- 包裹："),
                    ("code", "---\ntitle: 笔记标题\n"
                             "date: 2026-09-10\n"
                             "tags: [标签1, 标签2]\n---"),
                    ("p", "· tags 字段会被收集到左侧标签面板，用于聚合与交集筛选。"),
                ]),
                ("内部链接", [
                    ("code", "[[笔记名]]\n[[笔记名|显示的文字]]"),
                    ("p", "· 点击即可跳转到对应笔记。"),
                    ("p", "· 被引用的笔记底部会自动显示「被以下笔记引用」列表。"),
                ]),
                ("外部链接", [
                    ("code", "[显示文字](https://example.com)"),
                    ("p", "· 必须写成上面的 Markdown 链接语法，Ctrl + 点击可用浏览器打开。"),
                    ("p", "· 直接书写 https://example.com 这样的裸网址不会被识别为链接。"),
                ]),
                ("支持的 Markdown 语法", [
                    ("p", "· 标题 # / ## / ###、粗体 **文字**、斜体 *文字*、删除线 ~~文字~~"),
                    ("p", "· 无序列表 -、有序列表 1.、引用 >、分隔线 ---"),
                    ("p", "· 行内代码 `code` 与围栏代码块 ```"),
                    ("p", "· 表格以原生表格控件渲染（单元格不支持拖选与换行）"),
                ]),
            ],
        }

        c = self.colors
        W, H = 640, 480
        is_dark = self.theme_mode == "dark"
        win_border = "#555555" if is_dark else "#777777"
        bar_bg, bar_fg = c["nav_bg"], c["nav_fg"]
        bar_btn_hover = "#e81123" if not is_dark else "#c03333"

        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)
        dialog.minsize(420, 300)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=bar_bg)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  帮助", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=bar_bg, fg=bar_fg
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=dialog.destroy,
                  bg=bar_bg, fg=bar_fg,
                  activebackground=bar_btn_hover, activeforeground="#ffffff"
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root

        def _drag_move(e):
            dialog.geometry(
                f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root

        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # ── 主体：PanedWindow 可分栏 ──
        pane = ttk.PanedWindow(dialog, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)
        st = ttk.Style()
        st.configure("TPanedwindow", background=c["sidebar_bg"])
        st.configure("sash.TPanedwindow", sashthickness=4,
                     sashrelief=tk.FLAT,
                     background="#999" if not is_dark else "#666")

        left_bg = "#dddddd" if not is_dark else "#1e1e1e"
        left = tk.Frame(pane, bg=left_bg, width=140)
        right = tk.Frame(pane, bg=c["sidebar_bg"], padx=6, pady=10)
        pane.add(left, weight=0)
        pane.add(right, weight=1)

        # ── 右侧只读文本区 ──
        text = tk.Text(right, wrap=tk.WORD, bd=0, highlightthickness=0,
                       bg=c["content_bg"], fg=c["content_fg"],
                       font=("Microsoft YaHei", 10),
                       spacing1=2, spacing3=4, padx=6, pady=8)
        scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        code_bg = "#1e1e1e" if is_dark else "#f0f0f0"
        code_fg = "#d4d4d4" if is_dark else "#333333"
        text.tag_configure("h", font=("Microsoft YaHei", 11, "bold"),
                           spacing1=12, foreground=c["content_fg"])
        text.tag_configure("p", spacing1=2)
        text.tag_configure("code", font=("Consolas", 9),
                           background=code_bg, foreground=code_fg,
                           spacing1=6, spacing3=6,
                           lmargin1=10, lmargin2=10)

        def _render(title, items):
            text.configure(state=tk.NORMAL)
            text.delete("1.0", "end")
            text.insert("end", title + "\n", "h")
            for kind, line in items:
                text.insert("end", line + "\n", kind)
            text.configure(state=tk.DISABLED)
            text.yview_moveto(0)

        # ── 左侧层级：分类（可折叠） → 小节 ──
        sub_labels = []    # [(小节标题, 内容, Label)]
        cat_rows = []      # [(分类名, 表头 Label, 小节容器 Frame)]
        folded = set()     # 已折叠的分类

        def _refresh_fold():
            for cat, head, sub in cat_rows:
                head.configure(
                    text="  " + ("▸ " if cat in folded else "▾ ") + cat)
                if cat in folded:
                    sub.pack_forget()
                else:
                    sub.pack(fill=tk.X)

        def _toggle(cat):
            if cat in folded:
                folded.discard(cat)
            else:
                folded.add(cat)
            _refresh_fold()

        def _select(title, items):
            for t, _i, lbl in sub_labels:
                lbl.configure(bg=c["toolbar_btn_hover"] if t == title
                              else left_bg)
            _render(title, items)

        for cat, subs in sections.items():
            holder = tk.Frame(left, bg=left_bg)
            holder.pack(fill=tk.X)
            head = tk.Label(holder, anchor=tk.W, cursor="hand2",
                            font=("Microsoft YaHei", 10, "bold"),
                            bg=left_bg, fg=c["sidebar_fg"], pady=6)
            head.pack(fill=tk.X)
            head.bind("<Button-1>", lambda e, cat=cat: _toggle(cat))
            sub = tk.Frame(holder, bg=left_bg)
            sub.pack(fill=tk.X)

            for title, items in subs:
                lbl = tk.Label(sub, text="      " + title, anchor=tk.W,
                               font=("Microsoft YaHei", 9),
                               bg=left_bg, fg=c["sidebar_fg"], pady=4,
                               cursor="hand2")
                lbl.pack(fill=tk.X)
                lbl.bind("<Button-1>",
                         lambda e, t=title, i=items: _select(t, i))
                sub_labels.append((title, items, lbl))

            cat_rows.append((cat, head, sub))

        _refresh_fold()

        # 初始定位：优先命中 category，否则第一个小节
        if sub_labels:
            pick = sub_labels[0]
            if category:
                for row in sub_labels:
                    if row[0] == category:
                        pick = row
                        break
            _select(pick[0], pick[1])

        # 居中于主窗口
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - W) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - H) // 2
        dialog.geometry(f"{W}x{H}+{max(x, 0)}+{max(y, 0)}")

    def _open_settings(self):
        """打开集成设置面板（左分类 + 右内容，可拖动分隔）"""
        c = self.colors
        W, H = 600, 420
        is_dark = self.theme_mode == "dark"
        win_border = "#555555" if is_dark else "#777777"
        # 标题栏用活动栏配色
        bar_bg = c["nav_bg"]
        bar_fg = c["nav_fg"]
        bar_btn_hover = "#e81123" if not is_dark else "#c03333"

        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)
        dialog.minsize(400, 280)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=bar_bg)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  设置", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=bar_bg, fg=bar_fg
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=dialog.destroy,
                  bg=bar_bg, fg=bar_fg,
                  activebackground=bar_btn_hover, activeforeground="#ffffff"
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        # 拖拽
        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root
        def _drag_move(e):
            dialog.geometry(
                f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root
        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # ── 主体：PanedWindow 原生可分栏 ──
        pane = ttk.PanedWindow(dialog, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)
        # Sash 样式
        s = ttk.Style()
        s.configure("TPanedwindow", background=c["sidebar_bg"])
        s.configure("sash.TPanedwindow", sashthickness=4,
                    sashrelief=tk.FLAT, background="#999" if not is_dark else "#666")

        # 左侧略深，与右侧形成对比
        left_bg = "#dddddd" if not is_dark else "#1e1e1e"
        left = tk.Frame(pane, bg=left_bg, width=W // 2)
        right = tk.Frame(pane, bg=c["sidebar_bg"], padx=20, pady=12)
        pane.add(left, weight=1)
        pane.add(right, weight=3)

        # ── 右侧内容区（动态切换） ──
        self._settings_content = None
        editors = detect_editors()

        def _show_category(name):
            if self._settings_content:
                self._settings_content.destroy()
            self._settings_content = tk.Frame(right, bg=c["sidebar_bg"])
            self._settings_content.pack(fill=tk.BOTH, expand=True)
            ct = self._settings_content
            lf = ("Microsoft YaHei", 10)

            if name == "通用":
                tk.Label(ct, text="字号", anchor=tk.W, font=lf,
                         bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                         ).pack(fill=tk.X, pady=(0, 6))
                sz = tk.Frame(ct, bg=c["sidebar_bg"])
                sz.pack(fill=tk.X)
                sv = tk.StringVar(value=str(self._font_size))
                for txt, d in [("−", -1), ("+", 1)]:
                    b = tk.Button(sz, text=txt, font=("Microsoft YaHei", 9, "bold"),
                                  width=2, relief=tk.RIDGE, bd=1,
                                  command=lambda sv=sv, d=d: _delta_size(sv, d))
                    b.pack(side=tk.RIGHT, padx=(4, 0))
                    b.configure(bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                                activebackground=c["toolbar_btn_hover"])
                e = tk.Entry(sz, textvariable=sv, font=lf, width=6,
                             justify=tk.CENTER, relief=tk.FLAT, bd=0,
                             highlightthickness=1)
                e.pack(side=tk.RIGHT, padx=(0, 8))
                e.configure(bg=c["content_bg"], fg=c["content_fg"],
                            highlightbackground=c["search_border"])

            elif name == "外观":
                tk.Label(ct, text="主题模式", anchor=tk.W, font=lf,
                         bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                         ).pack(fill=tk.X, pady=(0, 8))
                themes = ["亮色", "暗色"]
                themes_map = {"亮色": "light", "暗色": "dark"}
                tv = tk.StringVar(value="亮色" if self.theme_mode == "light" else "暗色")
                cb = ttk.Combobox(ct, textvariable=tv, values=themes,
                                  state="readonly", font=lf, width=12)
                cb.pack(anchor=tk.W)
                cb.bind("<<ComboboxSelected>>", lambda e: (
                    setattr(self, 'theme_mode', themes_map[tv.get()]),
                    setattr(self, 'colors', VSCodeTheme.get(themes_map[tv.get()])),
                    self._apply_theme(),
                    self._save_settings(),
                ))

            elif name == "编辑器":
                tk.Label(ct, text="外部编辑器", anchor=tk.W, font=lf,
                         bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                         ).pack(fill=tk.X, pady=(0, 8))
                names = list(editors.keys())
                ev = tk.StringVar()

                # 裸命令名（如 notepad.exe）补全为已检测项的绝对路径
                if self._editor_path:
                    base = os.path.basename(self._editor_path).lower()
                    for n, p in editors.items():
                        if p and os.path.basename(p).lower() == base:
                            self._editor_path = p
                            break

                # 当前设置：命中已检测项则显示其名称，否则作为自定义项回显
                cur = None
                if self._editor_path:
                    for n, p in editors.items():
                        if p and os.path.normcase(p) == os.path.normcase(
                                self._editor_path):
                            cur = n
                            break
                if cur is None and self._editor_path:
                    cur = f"自定义：{os.path.basename(self._editor_path)}"
                    editors[cur] = self._editor_path
                    names.insert(0, cur)
                ev.set(cur if cur else (names[0] if names else ""))

                cb = ttk.Combobox(ct, textvariable=ev, values=names,
                                  state="readonly", font=lf, width=20)
                cb.pack(anchor=tk.W)

                # ── 当前路径与有效性提示 ──
                path_lbl = tk.Label(ct, text="", anchor=tk.W,
                                    font=("Microsoft YaHei", 8),
                                    bg=c["sidebar_bg"], fg=c["sidebar_fg"],
                                    wraplength=420, justify=tk.LEFT)
                path_lbl.pack(fill=tk.X, pady=(10, 0))

                def _editor_ok(p):
                    import shutil
                    return bool(p) and (os.path.isfile(p)
                                        or shutil.which(p) is not None)

                def _refresh_path_label():
                    p = self._editor_path or ""
                    if not p:
                        path_lbl.configure(text="(未指定，默认使用记事本)",
                                           fg=c["sidebar_fg"])
                    elif _editor_ok(p):
                        path_lbl.configure(text=p, fg=c["sidebar_fg"])
                    else:
                        path_lbl.configure(
                            text=f"{p}\n（路径无效，打开时将回退记事本）",
                            fg="#e81123")

                def _browse():
                    """手动指定任意 exe（覆盖便携版、绿色版等检测不到的程序）"""
                    from tkinter import filedialog
                    init = (os.path.dirname(self._editor_path)
                            if self._editor_path
                            and os.path.isfile(self._editor_path)
                            else os.environ.get("ProgramFiles", "C:\\"))
                    fp = filedialog.askopenfilename(
                        parent=ct.winfo_toplevel(),
                        title="选择编辑器程序",
                        initialdir=init,
                        filetypes=[("可执行程序", "*.exe"),
                                   ("所有文件", "*.*")])
                    if not fp:
                        return
                    self._editor_path = fp
                    custom = f"自定义：{os.path.basename(fp)}"
                    editors[custom] = fp
                    if custom not in names:
                        names.append(custom)
                        cb.configure(values=names)
                    ev.set(custom)
                    _refresh_path_label()
                    self._save_settings()

                cb.bind("<<ComboboxSelected>>",
                        lambda e: (
                            setattr(self, '_editor_path',
                                    editors.get(ev.get(), self._editor_path)),
                            _refresh_path_label(),
                            self._save_settings(),
                        ))

                bb = tk.Button(ct, text="选择编辑器...",
                               font=("Microsoft YaHei", 9),
                               width=14, relief=tk.RIDGE, bd=1, cursor="hand2",
                               command=_browse)
                bb.configure(bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                             activebackground=c["toolbar_btn_hover"])
                bb.pack(anchor=tk.W, pady=(8, 0))
                _refresh_path_label()

        def _delta_size(sv, d):
            try:
                cur = int(sv.get())
            except ValueError:
                cur = self._font_size
            cur = max(8, min(24, cur + d))
            sv.set(str(cur))
            self._font_size = cur
            self._apply_font_size()
            self._save_settings()

        # ── 左侧分类列表 ──
        categories = ["通用", "外观", "编辑器"]
        self._settings_cat_labels = []
        for i, cat_name in enumerate(categories):
            lbl = tk.Label(left, text=f"  {cat_name}",
                           font=("Microsoft YaHei", 10),
                           bg=left_bg, fg=c["sidebar_fg"],
                           anchor=tk.W, padx=12, pady=8, cursor="hand2")
            lbl.pack(fill=tk.X)
            lbl.bind("<Button-1>", lambda e, n=cat_name, l=None: (
                _highlight_cat(n), _show_category(n)))
            self._settings_cat_labels.append((lbl, cat_name))

        def _highlight_cat(name):
            for lbl, cat in self._settings_cat_labels:
                is_sel = cat == name
                lbl.configure(
                    bg=c["sidebar_item_selected"] if is_sel else left_bg,
                    fg=c["sidebar_fg"],
                )

        # 默认选中第一个
        _highlight_cat("通用")
        _show_category("通用")



        # ── 窗口缩放（仅鼠标在对话框内生效）──
        def _in_dialog(e):
            x1, y1 = dialog.winfo_rootx(), dialog.winfo_rooty()
            return x1 <= e.x_root <= x1 + dialog.winfo_width() and \
                   y1 <= e.y_root <= y1 + dialog.winfo_height()

        def _edge_region(e):
            w, h = dialog.winfo_width(), dialog.winfo_height()
            rx, ry = dialog.winfo_rootx(), dialog.winfo_rooty()
            x, y = e.x_root - rx, e.y_root - ry
            L = x <= 6; R = x >= w - 6; T = y <= 6; B = y >= h - 6
            if T and L: return "nw"
            if T and R: return "ne"
            if B and L: return "sw"
            if B and R: return "se"
            if L: return "w"
            if R: return "e"
            if T: return "n"
            if B: return "s"
            return ""
        cursors = {"n":"size_ns","s":"size_ns","e":"size_we","w":"size_we",
                    "ne":"size_ne_sw","nw":"size_nw_se","se":"size_nw_se","sw":"size_ne_sw"}
        dialog.bind("<Motion>", lambda e: dialog.config(
            cursor=cursors.get(_edge_region(e), "") if _in_dialog(e) else ""), add="+")
        def _start(e):
            if not _in_dialog(e): return
            r = _edge_region(e)
            if not r: return
            dialog._rs = {"r":r, "mx":e.x_root, "my":e.y_root,
                          "wx":dialog.winfo_x(), "wy":dialog.winfo_y(),
                          "ww":dialog.winfo_width(), "wh":dialog.winfo_height()}
        def _do(e):
            rs = getattr(dialog, '_rs', None)
            if rs is None: return
            r = rs["r"]
            dx = e.x_root - rs["mx"]; dy = e.y_root - rs["my"]
            x, y, w, h = rs["wx"], rs["wy"], rs["ww"], rs["wh"]
            if "w" in r: x += dx; w -= dx
            if "e" in r: w += dx
            if "n" in r: y += dy; h -= dy
            if "s" in r: h += dy
            if w < 400: w = 400; x = rs["wx"] + rs["ww"] - 400 if "w" in r else x
            if h < 280: h = 280; y = rs["wy"] + rs["wh"] - 280 if "n" in r else y
            dialog.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        dialog.bind("<Button-1>", _start, add="+")
        dialog.bind("<B1-Motion>", _do, add="+")
        dialog.bind("<ButtonRelease-1>", lambda e: setattr(dialog, '_rs', None), add="+")

        # ── 居中（topmost → grab → update → geometry，与其他二级窗口一致）──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{int(x)}+{int(y)}")
        try:
            ctypes.windll.user32.MoveWindow(
                dialog.winfo_id(), x, y, W, H, True)
        except Exception:
            pass
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _open_font_dialog(self):
        """打开字号设置弹窗（+/- 按钮 + 输入 + 重置）"""
        c = self.colors
        W, H = 320, 210

        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        win_border = "#555555" if self.theme_mode == "dark" else "#777777"
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=c["toolbar_bg"])
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  字号设置", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=c["toolbar_bg"], fg=c["toolbar_fg"]
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8,
                  command=dialog.destroy,
                  bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                  activebackground="#e81123"
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        # ── 拖拽 ──
        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root
        def _drag_move(e):
            dialog.geometry(
                f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root
        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # ── 主体 ──
        body = tk.Frame(dialog, bg=c["sidebar_bg"], padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        # 字号显示变量（直接绑定 self._font_size）
        size_var = tk.StringVar(value=str(self._font_size))

        def apply_size():
            try:
                new_size = int(size_var.get())
                new_size = max(8, min(24, new_size))
                size_var.set(str(new_size))
                self._font_size = new_size
                self._apply_font_size()
                self._save_settings()
                self.status_right.configure(text=f"字号: {self._font_size}   ")
                self.status_left.configure(text=f"   字号: {self._font_size}")
            except ValueError:
                size_var.set(str(self._font_size))

        def delta(d):
            try:
                cur = int(size_var.get())
            except ValueError:
                cur = self._font_size
            cur = max(8, min(24, cur + d))
            size_var.set(str(cur))
            apply_size()

        # 字号调整行：− [数字] +
        row = tk.Frame(body, bg=c["sidebar_bg"])
        row.pack(pady=(4, 10))
        tk.Label(row, text="当前字号", font=("Microsoft YaHei", 9),
                 bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                 ).pack(anchor=tk.W, pady=(0, 6))

        btn_row = tk.Frame(body, bg=c["sidebar_bg"])
        btn_row.pack()

        minus_btn = tk.Button(btn_row, text="−", font=("Microsoft YaHei", 11, "bold"),
                              width=3, relief=tk.RIDGE, bd=1,
                              command=lambda: delta(-1))
        minus_btn.pack(side=tk.LEFT, padx=(0, 8))

        size_entry = tk.Entry(btn_row, textvariable=size_var,
                              font=("Microsoft YaHei", 14),
                              width=4, justify=tk.CENTER,
                              relief=tk.FLAT, bd=0,
                              highlightthickness=1)
        size_entry.pack(side=tk.LEFT, padx=(0, 8))
        size_entry.bind("<Return>", lambda e: apply_size())
        size_entry.select_range(0, tk.END)
        size_entry.focus_set()

        plus_btn = tk.Button(btn_row, text="+", font=("Microsoft YaHei", 11, "bold"),
                             width=3, relief=tk.RIDGE, bd=1,
                             command=lambda: delta(1))
        plus_btn.pack(side=tk.LEFT)

        # 提示行
        tk.Label(body, text="8 − 24", font=("Microsoft YaHei", 8),
                 bg=c["sidebar_bg"], fg="#999"
                 ).pack(pady=(4, 14))

        # 底部：重置按钮
        def reset_size():
            self._font_size = 11
            size_var.set("11")
            self._apply_font_size()
            self._save_settings()
            self.status_right.configure(text="字号: 11   ")
            self.status_left.configure(text="   字号: 11")

        reset_btn = tk.Button(body, text="重置默认 (11)",
                              font=("Microsoft YaHei", 9),
                              relief=tk.RIDGE, bd=1,
                              padx=12, pady=4,
                              command=reset_size)
        reset_btn.pack()

        # ── 主题色 ──
        entry_bg = c["content_bg"]
        entry_fg = c["content_fg"]
        btn_bg = c["toolbar_btn_bg"]
        btn_fg = c["toolbar_btn_fg"]
        btn_hover = c["toolbar_btn_hover"]

        size_entry.configure(bg=entry_bg, fg=entry_fg,
                             highlightbackground=c["search_border"],
                             highlightcolor=c["search_border"],
                             insertbackground=entry_fg)

        for btn in (minus_btn, plus_btn):
            btn.configure(bg=btn_bg, fg=btn_fg, activebackground=btn_hover,
                          activeforeground=btn_fg)

        reset_btn.configure(bg=btn_bg, fg=btn_fg, activebackground=btn_hover,
                            activeforeground=btn_fg)

        # ── 定位 ──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{x}+{y}")
        try:
            hwnd = dialog.winfo_id()
            ctypes.windll.user32.MoveWindow(hwnd, x, y, W, H, True)
        except Exception:
            pass
        dialog.attributes('-topmost', True)
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

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
        self._save_settings()

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
