"""
IndeXar 标题栏与窗口管理

无边框标题栏绘制、窗口拖拽/缩放、最大化还原，以及 Win32 集成
（Aero Snap、Alt+Tab 修复）。以 Mixin 形式组合进主应用，
通过 self 共享控件引用与状态。
"""

import ctypes
import os
import re
import tkinter as tk
from tkinter import ttk

import icon_renderer
from ui.common import (_add_hover_bg, ASSETS_DIR,
                       set_appwindow_style, force_appwindow_style)

# 窗口边缘拖拽判定阈值（像素）
RESIZE_EDGE = 8

# 标题栏高度（像素）：界面绘制与 Win32 命中测试共用同一取值，
# 两处若各写各的，会出现"看着是标题栏、点下去却不是"的错位
TITLEBAR_HEIGHT = 42
# 标题栏图标尺寸
TITLEBAR_LOGO_SIZE = 24


class TitleBarMixin:
    """标题栏绘制与无边框窗口管理"""

    # ── 自定义标题栏 ──

    def _build_titlebar(self):
        """自定义标题栏：拖拽移动 + 窗口控制按钮"""
        bar = tk.Frame(self.root, height=TITLEBAR_HEIGHT)
        bar.grid(row=0, column=0, sticky="ew")
        # 子控件用的是 pack，故须关闭 pack 传播；若误用 grid_propagate，
        # frame 的请求高度会一直由子控件决定，height 设置形同虚设
        bar.pack_propagate(False)
        self.titlebar = bar

        # ── 应用图标（亮/暗主题 PNG，24px）──
        # 左侧留白比其余区域稍大：logo 紧贴窗口边缘会显得局促
        self._logo_img = None
        self.title_icon = tk.Label(bar, text="",
                                   padx=8, pady=4)
        self.title_icon.pack(side=tk.LEFT, padx=(12, 24))
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
                          font=("Microsoft YaHei", 11),
                          padx=14, pady=3,
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

        self.min_btn = self._make_title_btn(
            btn_frame, "─", self._minimize_window,
        )
        self.min_btn.pack(side=tk.LEFT, padx=0, fill=tk.Y)

        self.max_btn = self._make_title_btn(
            btn_frame, "□", self._toggle_maximize,
        )
        self.max_btn.pack(side=tk.LEFT, padx=0, fill=tk.Y)

        self.close_btn = self._make_title_btn(
            btn_frame, "✕", self._on_close,
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

        # ── 供 Win32 命中测试使用的布局缓存 ──
        # WM_NCHITTEST 在每次鼠标移动时都会进入窗口过程；若在其中现场调
        # winfo_*（Tcl 调用），Tcl 繁忙时会拖慢消息处理，拖动窗口就发顿。
        # 故只在标题栏尺寸变化时缓存一次交互控件的横向范围。
        self._bar_regions = None       # (按钮区左边界, [(菜单左, 菜单右), ...])
        # Configure 覆盖尺寸变化；<Map> 覆盖“启动时窗口未映射、首次 Configure
        # 阶段子控件尚无真实几何”的情形——映射完成后必须再取一次
        bar.bind("<Configure>", lambda e: self._cache_bar_regions(), add="+")
        bar.bind("<Map>", lambda e: self._cache_bar_regions(), add="+")

        # ── 拖拽绑定（菜单项本身不参与拖拽，避免和点击菜单冲突）──
        for widget in (bar, self.title_icon):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)
            widget.bind("<Double-Button-1>",
                        lambda e: self._toggle_maximize())

    def _cache_bar_regions(self):
        """缓存标题栏内交互控件（菜单、窗口按钮）的横向范围

        用 winfo_x()（相对标题栏）而非 winfo_rootx()（相对屏幕）：后者
        在窗口尚未映射时（如启动时的 withdraw 阶段）取到 0，与根窗口的
        屏幕坐标相减会得到错误范围，命中测试随之全部失准。"""
        try:
            btn_frame = self.titlebar.winfo_children()[-1]
            btn_left = btn_frame.winfo_x()
            menus = [(lbl.winfo_x(), lbl.winfo_x() + lbl.winfo_width())
                     for lbl in self._menu_labels]
            # 合理性校验：控件尚未布局时 winfo_x/width 会给出 0/1，
            # 这种缓存比没有更糟，直接置空走命中测试的兜底分支
            if (btn_left <= 1 or self.titlebar.winfo_width() <= 1
                    or any(b - a <= 1 for a, b in menus)):
                self._bar_regions = None
                return
            self._bar_regions = (btn_left, menus)
        except Exception:
            self._bar_regions = None

    def _update_title_logo(self):
        """加载当前主题对应的应用图标 PNG"""
        import os
        fname = ("light_24.png" if self.theme_mode == "light"
                 else "dark_24.png")
        path = os.path.join(ASSETS_DIR, fname)
        if not os.path.exists(path):
            return
        try:
            self._logo_img = tk.PhotoImage(file=path)
            self.title_icon.configure(image=self._logo_img)
        except tk.TclError:
            pass

    def _make_title_btn(self, parent, text, cmd, font_size=12, width=4):
        """创建标题栏按钮（宽度以字符计，随字号放大而加宽）"""
        btn = tk.Button(
            parent, text=text,
            font=("Segoe UI", font_size),
            width=width, height=0,
            relief=tk.FLAT, bd=0,
            cursor="hand2",
            command=cmd,
        )
        return btn


    def _start_drag(self, event):
        self._dragging = True          # 拖动期间后台轮询暂停（见 _watch_data_dir）
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

    def _end_drag(self, _event=None):
        """拖动结束：恢复后台轮询（拖动期间轮询暂停，见 _watch_data_dir）"""
        self._dragging = False

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

    def _set_appwindow_style(self):
        """把主窗口标为 WS_EX_APPWINDOW，使其进入任务栏与 Alt+Tab（见 ui.common）"""
        return set_appwindow_style(self.root)

    def _fix_alt_tab(self):
        """兜底：窗口已显示才发现任务栏缺按钮时，强制外壳重建（会闪一下）"""
        force_appwindow_style(self.root)

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

            # 标题栏高度取自模块常量，与界面绘制保持一致
            BUTTON_AREA_WIDTH = 150     # 取不到按钮实际位置时的兜底宽度
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

                    # 四角与四边优先于标题栏：窗口边缘在整条高度上
                    # （含标题栏一段）都要能缩放
                    if on_left and on_top:
                        return 13   # HTTOPLEFT
                    if on_right and on_top:
                        return 14   # HTTOPRIGHT
                    if on_left and on_bottom:
                        return 16   # HTBOTTOMLEFT
                    if on_right and on_bottom:
                        return 17   # HTBOTTOMRIGHT
                    if on_left:
                        return 10   # HTLEFT
                    if on_right:
                        return 11   # HTRIGHT
                    if on_top:
                        return 12   # HTTOP
                    if on_bottom:
                        return 15   # HTBOTTOM

                    # 标题栏区域：空白处交给 Windows 原生拖动（流畅），
                    # 菜单与窗口按钮保持客户区，让 Tk 正常响应点击
                    if rel_y < TITLEBAR_HEIGHT:
                        regions = self._bar_regions
                        if regions is not None:
                            btn_left, menus = regions
                            if rel_x >= btn_left:
                                return 1  # HTCLIENT（窗口按钮）
                            if any(a <= rel_x < b for a, b in menus):
                                return 1  # HTCLIENT（菜单项）
                        elif x >= rect[2] - BUTTON_AREA_WIDTH:
                            return 1  # 布局未就绪时的兜底
                        if self._is_maximized:
                            return 1  # 最大化时交给 Tk 的下拉还原逻辑
                        return 2  # HTCAPTION：原生拖动 + Aero Snap

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
            self._cache_bar_regions()     # 钩子生效时布局已就绪，先取一次
        except Exception:
            pass  # 失败则回退到手动拖拽

