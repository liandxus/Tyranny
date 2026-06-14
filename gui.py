"""
IndeXar 图形界面
VS Code 风格 + 自定义无边框标题栏 + 亮/暗主题切换
"""

import tkinter as tk
from tkinter import ttk
import ctypes
import re
from ttkbootstrap import Style
from file_handler import list_notes, list_notes_tree, read_note
from theme_manager import VSCodeTheme
import icon_renderer

# ── 窗口拖拽 / 调整大小的阈值（像素） ──
RESIZE_EDGE = 10


class IndeXarApp:
    """IndeXar 主应用（无边框+自定义标题栏）"""

    ICONS = {"light": {"sun": "☀️", "moon": "🌙"},
             "dark": {"sun": "☀️", "moon": "🌙"}}

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("IndeXar")
        # 窗口居中启动
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        cx, cy = (sw - 1100) // 2, (sh - 680) // 2
        self.root.geometry(f"1100x680+{cx}+{cy}")
        self.root.minsize(800, 500)

        # ── 移除原生标题栏 ──
        self.root.overrideredirect(True)

        # 主题状态
        self.theme_mode = "light"
        self.colors = VSCodeTheme.get(self.theme_mode)
        self.style = Style(theme="journal")

        # 窗口状态
        self._drag_data = {"x": 0, "y": 0}
        self._is_maximized = False
        self._normal_geometry = None
        self._resize_region = ""
        self._resize_data = None

        # 当前面板
        self.current_panel = "files"

        # 构建界面
        self._build_layout()
        self._apply_theme()

        # ── 绑定窗口调整大小 ──
        self.root.bind("<Button-1>", self._start_resize, add="+")
        self.root.bind("<B1-Motion>", self._do_resize, add="+")
        self.root.bind("<ButtonRelease-1>", self._end_resize, add="+")
        self.root.bind("<Motion>", self._update_cursor, add="+")
        self.root.bind("<Leave>", lambda e: self.root.config(cursor=""), add="+")

        # Windows 原生窗口管理（Aero Snap + 双击最大化/还原）
        self.root.after(200, self._fix_alt_tab)
        self.root.after(300, self._setup_win32_window_management)

    # ══════════════════════════════════
    # 布局搭建
    # ══════════════════════════════════

    def _build_layout(self):
        """搭建整体布局"""
        # ─── 自定义标题栏 ───
        self._build_titlebar()

        # ─── 主体 ───
        body = tk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)

        # 活动栏（左侧窄条）
        self.nav = tk.Frame(body, width=48)
        self.nav.pack(side=tk.LEFT, fill=tk.Y)
        self.nav.pack_propagate(False)
        self._build_nav_widgets()

        # 侧栏面板
        self.side_frame = tk.Frame(body, width=210)
        self.side_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.side_frame.pack_propagate(False)
        self._build_file_tree_panel()
        self._build_tag_panel()

        # 内容区
        self._build_content_area(body)

        # ─── 状态栏 ───
        self.statusbar = tk.Frame(self.root, height=22)
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)
        self.statusbar.pack_propagate(False)
        self._build_statusbar_widgets()

        # 默认显示文件树
        self._show_files()

    # ── 自定义标题栏 ──

    def _build_titlebar(self):
        """自定义标题栏：拖拽移动 + 窗口控制按钮"""
        bar = tk.Frame(self.root, height=30)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        self.titlebar = bar

        # 应用图标 / 标题
        self.title_label = tk.Label(
            bar, text="📁  IndeXar",
            font=("Microsoft YaHei", 10),
            padx=12,
        )
        self.title_label.pack(side=tk.LEFT)

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
            self.root.destroy,
        )
        self.close_btn.pack(side=tk.LEFT, padx=0, fill=tk.Y)

        # ── 拖拽绑定 ──
        for widget in (bar, self.title_label):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)
            widget.bind("<Double-Button-1>",
                        lambda e: self._toggle_maximize())

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
        self.nav_files_btn.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))
        self.nav_files_btn.bind("<Button-1>", lambda e: self._show_files())

        self._nav_tags_img = icon_renderer.tag_icon(
            self.colors["nav_fg"]
        )
        self.nav_tags_btn = tk.Label(
            self.nav, image=self._nav_tags_img,
            bg=self.colors["nav_bg"],
            cursor="hand2",
        )
        self.nav_tags_btn.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))
        self.nav_tags_btn.bind("<Button-1>", lambda e: self._show_tags())

    # ── 侧栏面板 ──

    def _build_file_tree_panel(self):
        """文件树"""
        self.file_tree_frame = tk.Frame(self.side_frame)
        self.side_header = tk.Label(
            self.file_tree_frame,
            text="   笔记列表",
            font=("Microsoft YaHei", 10),
            anchor=tk.W, padx=8, pady=6,
        )
        self.side_header.pack(fill=tk.X)

        tree_frame = tk.Frame(self.file_tree_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_file_selected)

    def _build_tag_panel(self):
        """标签面板"""
        self.tag_frame = tk.Frame(self.side_frame)
        self.tag_header = tk.Label(
            self.tag_frame,
            text="   标签列表",
            font=("Microsoft YaHei", 10),
            anchor=tk.W, padx=8, pady=6,
        )
        self.tag_header.pack(fill=tk.X)

        tag_frame = tk.Frame(self.tag_frame)
        tag_frame.pack(fill=tk.BOTH, expand=True)

        self.tag_listbox = tk.Listbox(
            tag_frame,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT, highlightthickness=0,
            borderwidth=0, activestyle="none",
        )
        self.tag_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tag_scroll = ttk.Scrollbar(
            tag_frame, orient=tk.VERTICAL, command=self.tag_listbox.yview,
        )
        self.tag_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tag_listbox.configure(yscrollcommand=self.tag_scroll.set)
        self.tag_listbox.bind("<<ListboxSelect>>", self._on_tag_selected)

    # ── 内容区 ──

    def _build_content_area(self, parent):
        """内容展示区（头部含文件名+搜索+主题切换）"""
        right = tk.Frame(parent)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── 内容头部：文件名 | 搜索 + 主题切换 ──
        self.content_header = tk.Frame(right)
        self.content_header.pack(fill=tk.X)

        # 左侧：文件名/欢迎语
        self.content_title = tk.Label(
            self.content_header,
            text="   选择一篇笔记开始阅读",
            font=("Microsoft YaHei", 10),
            anchor=tk.W, padx=14, pady=6,
        )
        self.content_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 右侧：搜索 + 主题
        header_right = tk.Frame(self.content_header)
        header_right.pack(side=tk.RIGHT, padx=(0, 10))

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            header_right,
            textvariable=self.search_var,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            width=20,
        )
        self.search_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        self.search_btn = tk.Button(
            header_right, text="搜索",
            font=("Microsoft YaHei", 9),
            relief=tk.FLAT, padx=8, pady=1,
            cursor="hand2",
            command=self._do_search,
        )
        self.search_btn.pack(side=tk.LEFT, padx=(0, 8))

        # 主题切换
        self.theme_frame = tk.Frame(header_right, cursor="hand2")
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

        # ── 文本内容区 ──

        text_container = tk.Frame(right)
        text_container.pack(fill=tk.BOTH, expand=True)

        self.content_text = tk.Text(
            text_container,
            wrap=tk.WORD,
            font=("Microsoft YaHei", 11),
            padx=20, pady=16,
            relief=tk.FLAT, highlightthickness=0,
            borderwidth=0, insertwidth=2,
        )
        self.content_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.content_scroll = ttk.Scrollbar(
            text_container, orient=tk.VERTICAL,
            command=self.content_text.yview,
        )
        self.content_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_text.configure(yscrollcommand=self.content_scroll.set)
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
            self.statusbar, text="data/   ",
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
            BUTTON_AREA_WIDTH = 120  # 按钮区域大约宽度，用于排除

            @WindowProc
            def wndproc(hwnd, msg, wparam, lparam):
                # ── WM_NCHITTEST：告诉 Windows 点击区域的类型 ──
                if msg == 0x0084:
                    # 从 LPARAM 提取鼠标屏幕坐标
                    x = ctypes.c_int16(lparam & 0xFFFF).value
                    y = ctypes.c_int16((lparam >> 16) & 0xFFFF).value

                    # 获取窗口屏幕位置
                    rect = (ctypes.c_long * 4)()
                    ctypes.windll.user32.GetWindowRect(hwnd, rect)
                    rel_y = y - rect[1]

                    # 标题栏区域
                    if 0 <= rel_y < TITLEBAR_HEIGHT:
                        try:
                            btn_frame = self.titlebar.winfo_children()[-1]
                            btn_left = btn_frame.winfo_rootx()
                            if x >= btn_left:
                                return 1  # HTCLIENT → 让按钮正常点击
                        except Exception:
                            if x >= rect[2] - BUTTON_AREA_WIDTH:
                                return 1
                        # 最大化时：交给 tkinter 处理，用我们的手动拖拽逻辑
                        # （这样才能让还原后跟随鼠标位置）
                        if self._is_maximized:
                            return 1  # HTCLIENT
                        return 2  # HTCAPTION → Windows 接管拖拽/吸附

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
        self.colors = VSCodeTheme.get(self.theme_mode)
        self._apply_theme()
        if self.current_panel == "files":
            self._refresh_file_tree()

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
        self.title_label.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"])
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                          activebackground=c["toolbar_btn_hover"])

        # ── 内容头部（搜索 + 主题） ──
        header_right = self.content_header.winfo_children()[1]  # 右侧 Frame
        header_right.configure(bg=c["content_header_bg"])
        self.search_entry.configure(
            bg=c["search_bg"], fg=c["search_fg"],
            highlightbackground=c["search_border"],
            highlightcolor=c["search_border"],
            insertbackground=c["toolbar_fg"],
        )
        self.search_btn.configure(
            bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
            activebackground=c["toolbar_btn_hover"],
        )
        self._update_theme_toggle()

        # ── 活动栏 ──
        self.nav.configure(bg=c["nav_bg"])
        self.nav_files_btn.configure(bg=c["nav_bg"])
        self.nav_tags_btn.configure(bg=c["nav_bg"])
        self._update_nav_icons()

        # ── 侧栏 ──
        self.side_frame.configure(bg=c["sidebar_bg"])
        self.file_tree_frame.configure(bg=c["sidebar_bg"])
        self.tag_frame.configure(bg=c["sidebar_bg"])
        self.side_header.configure(bg=c["sidebar_header_bg"], fg=c["sidebar_header_fg"])
        self.tag_header.configure(bg=c["sidebar_header_bg"], fg=c["sidebar_header_fg"])

        # 文件树（ttk）
        tree_style = "vscode.Treeview"
        self.style.configure(
            tree_style,
            background=c["tree_bg"], foreground=c["tree_fg"],
            fieldbackground=c["tree_bg"],
            borderwidth=0, font=("Microsoft YaHei", 10), rowheight=26,
        )
        self.style.map(tree_style,
                       background=[("selected", c["tree_sel_bg"])],
                       foreground=[("selected", c["tree_sel_fg"])])
        self.tree.configure(style=tree_style)

        # 滚动条（ttk）
        scroll_style = "vscode.Vertical.TScrollbar"
        self.style.configure(
            scroll_style,
            background=c["scroll_thumb"], troughcolor=c["scroll_trough"],
            bordercolor=c["scroll_trough"], arrowcolor=c["scroll_thumb"],
            lightcolor=c["scroll_thumb"], darkcolor=c["scroll_thumb"],
        )
        for s in (self.tree_scroll, self.tag_scroll, self.content_scroll):
            s.configure(style=scroll_style)

        # 标签列表
        self.tag_listbox.configure(
            bg=c["sidebar_bg"], fg=c["sidebar_fg"],
            selectbackground=c["sidebar_item_selected"],
            selectforeground=c["sidebar_fg"],
        )

        # ── 内容区 ──
        self.content_header.configure(bg=c["content_header_bg"])
        self.content_title.configure(bg=c["content_header_bg"], fg=c["content_header_fg"])
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

    # ══════════════════════════════════
    # 面板切换
    # ══════════════════════════════════

    def _show_files(self):
        self.current_panel = "files"
        self.tag_frame.pack_forget()
        self.file_tree_frame.pack(fill=tk.BOTH, expand=True)
        self._update_nav_icons()
        self._refresh_file_tree()

    def _show_tags(self):
        self.current_panel = "tags"
        self.file_tree_frame.pack_forget()
        self.tag_frame.pack(fill=tk.BOTH, expand=True)
        self._update_nav_icons()
        self._refresh_tags()

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
                display = f"  📁 {item['name']}"
                node = self.tree.insert(
                    parent_iid, "end", iid=iid,
                    text=display, values=(iid, True),
                )
                if item["children"]:
                    file_count += self._populate_tree(node, item["children"])
                else:
                    # 插入空白子节点，让展开箭头显示
                    self.tree.insert(node, "end", text="")
            else:
                display = f"  📄 {item['name']}"
                self.tree.insert(
                    parent_iid, "end", iid=iid,
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
        # 搜索结果头部行
        if vals[0] == "__header__":
            return
        iid, is_dir = vals[0], vals[1]
        if is_dir == "True" or is_dir is True:
            # 点的是文件夹 — 切换展开/折叠
            if self.tree.item(selected[0], "open"):
                self.tree.item(selected[0], open=False)
            else:
                self.tree.item(selected[0], open=True)
            return
        self._display_note(iid)

    # ══════════════════════════════════
    # 标签
    # ══════════════════════════════════

    def _refresh_tags(self):
        self.tag_listbox.delete(0, tk.END)
        self.tag_listbox.insert(tk.END, "")
        self.tag_listbox.insert(tk.END, "   ⏳ 标签功能开发中")
        self.tag_listbox.insert(tk.END, "")
        self.tag_listbox.insert(tk.END, "   在 .md 文件头部添加：")
        self.tag_listbox.insert(tk.END, "   ---")
        self.tag_listbox.insert(tk.END, "   tags: [标记, 分类]")
        self.tag_listbox.insert(tk.END, "   ---")

    def _on_tag_selected(self, event):
        pass

    # ══════════════════════════════════
    # 内容
    # ══════════════════════════════════

    def _display_note(self, rel_path):
        content = read_note(rel_path)
        if content is None:
            self._set_content(f"⚠️  找不到文件：{rel_path}.md")
            return
        name = rel_path.split("/")[-1]
        self.content_title.configure(text=f"   📄 {name}.md")
        self._render_markdown(content)

    def _render_markdown(self, md_text):
        from markdown_renderer import render_markdown
        self.content_text.configure(state=tk.NORMAL)
        render_markdown(self.content_text, md_text)
        self.content_text.configure(state=tk.DISABLED)

    def _set_content(self, text):
        self.content_text.configure(state=tk.NORMAL)
        self.content_text.delete(1.0, tk.END)
        self.content_text.insert(tk.END, text)
        self.content_text.configure(state=tk.DISABLED)

    # ══════════════════════════════════
    # 搜索
    # ══════════════════════════════════

    def _do_search(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            return
        from search_engine import search_notes
        results = search_notes(keyword)

        # 如果当前不是文件面板，切过去并刷新
        if self.current_panel != "files":
            self._show_files()
        # 清空树
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not results:
            self.tree.insert("", "end", text=f"   🔍 未找到 \"{keyword}\"")
            self._set_content(f"未找到包含 \"{keyword}\" 的笔记。")
            self.status_left.configure(text="   未找到结果")
            return

        self.tree.insert("", "end",
                         text=f"   🔍 \"{keyword}\" ({len(results)} 条)",
                         values=("__header__",))
        for rel_path, _ in results:
            name = rel_path.split("/")[-1]
            self.tree.insert("", "end", text=f"  📄 {name}",
                             values=(rel_path, False))
        self._set_content(f"🔍 搜索 \"{keyword}\" 找到 {len(results)} 条结果")
        self.status_left.configure(text=f"   {len(results)} 条结果")

    # ══════════════════════════════════
    # 启动
    # ══════════════════════════════════

    def run(self):
        self.root.mainloop()
