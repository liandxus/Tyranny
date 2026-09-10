"""
IndeXar 标题栏与窗口管理

无边框标题栏绘制、窗口拖拽/缩放、最大化还原，以及 Win32 集成
（Aero Snap、Alt+Tab 修复）。以 Mixin 形式组合进主应用，
通过 self 共享控件引用与状态。
"""

import ctypes
import os
import tkinter as tk
from tkinter import ttk

import icon_renderer
from ui.common import _add_hover_bg

# 窗口边缘拖拽判定阈值（像素）
RESIZE_EDGE = 8


class TitleBarMixin:
    """标题栏绘制与无边框窗口管理"""

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

