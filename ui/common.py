"""
IndeXar 界面通用工具

与具体面板无关的共享工具：控件 hover 效果、颜色计算、资源路径，
以及无边框窗口的缩放与任务栏（Alt+Tab）集成。
"""

import ctypes
import os

import tkinter as tk
from tkinter import ttk

# 项目根目录与资源目录
# 各界面模块位于 ui/ 包内，不能再用自身 __file__ 推导资源位置，统一在此定义。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")

# 无边框窗口的边缘拖拽判定阈值（像素）
RESIZE_EDGE = 8

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


def enable_window_resize(win, edge=RESIZE_EDGE, titlebar=None):
    """为无边框窗口（overrideredirect）启用边缘与角落拖拽调整大小。

    去掉系统边框后，缩放不再由系统接管，只能自行判定鼠标落在哪条边或
    哪个角，再改写窗口几何。主窗口与各对话框用的是同一套规则，故抽到此处。

    参数:
        win:      无边框窗口（Toplevel / Tk）
        edge:     边缘判定阈值（像素）
        titlebar: 标题栏控件；其上的拖动用于移动窗口，不触发缩放
    """
    cursors = {
        "n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we",
        "ne": "size_ne_sw", "nw": "size_nw_se",
        "se": "size_nw_se", "sw": "size_ne_sw",
    }
    state = {"data": None}

    def _in_titlebar(widget):
        while widget is not None:
            if titlebar is not None and widget == titlebar:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _region(event):
        w, h = win.winfo_width(), win.winfo_height()
        x = event.x_root - win.winfo_rootx()
        y = event.y_root - win.winfo_rooty()
        on_l, on_r = x <= edge, x >= w - edge
        on_t, on_b = y <= edge, y >= h - edge
        # 先判角，再判边
        if on_t and on_l:
            return "nw"
        if on_t and on_r:
            return "ne"
        if on_b and on_l:
            return "sw"
        if on_b and on_r:
            return "se"
        if on_l:
            return "w"
        if on_r:
            return "e"
        if on_t:
            return "n"
        if on_b:
            return "s"
        return ""

    def _skip(event):
        # 标题栏拖动用于移动窗口；滚动条拖动也不应被当成缩放
        return (_in_titlebar(event.widget)
                or isinstance(event.widget, (tk.Scrollbar, ttk.Scrollbar)))

    def _on_motion(e):
        win.config(cursor=cursors.get("" if _skip(e) else _region(e), ""))

    def _on_press(e):
        if _skip(e):
            return
        r = _region(e)
        if not r:
            return
        state["data"] = {"mx": e.x_root, "my": e.y_root,
                         "x": win.winfo_x(), "y": win.winfo_y(),
                         "w": win.winfo_width(), "h": win.winfo_height(),
                         "region": r}

    def _on_drag(e):
        d = state["data"]
        if not d:
            return
        r = d["region"]
        dx, dy = e.x_root - d["mx"], e.y_root - d["my"]
        x, y, w, h = d["x"], d["y"], d["w"], d["h"]
        if "w" in r:
            x, w = x + dx, w - dx
        if "e" in r:
            w = w + dx
        if "n" in r:
            y, h = y + dy, h - dy
        if "s" in r:
            h = h + dy
        # 受最小尺寸约束；拖过界时固定在该侧，避免窗口反向跳走
        mw, mh = win.minsize()
        if w < mw:
            if "w" in r:
                x = d["x"] + d["w"] - mw
            w = mw
        if h < mh:
            if "n" in r:
                y = d["y"] + d["h"] - mh
            h = mh
        win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")

    def _on_release(_e):
        state["data"] = None

    win.bind("<Motion>", _on_motion, add="+")
    win.bind("<Button-1>", _on_press, add="+")
    win.bind("<B1-Motion>", _on_drag, add="+")
    win.bind("<ButtonRelease-1>", _on_release, add="+")
    win.bind("<Leave>", lambda e: win.config(cursor=""), add="+")


def set_appwindow_style(win, taskbar=True):
    """把无边框窗口从「工具窗口」改为参与窗口管理的普通窗口。

    Tk 的 overrideredirect 窗口不参与外壳的窗口管理：既不进 Alt+Tab，
    也没有任务栏按钮。taskbar=True 时一并加上 WS_EX_APPWINDOW，窗口获得
    独立的任务栏按钮（主窗口、帮助、设置一类常驻面板用这一档）；
    taskbar=False 只去掉工具窗口标记，使窗口能出现在 Alt+Tab 中但不占
    任务栏——一次性的输入提示框适合后者，免得任务栏被弹窗挤满。

    窗口尚未显示时调用最稳妥：样式在窗口映射前就已就绪，外壳建立任务栏
    按钮时直接带上，不必事后隐藏重建，也就不会闪烁。返回是否已确认生效。
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id())
        if not hwnd:
            return False
        current = user32.GetWindowLongW(hwnd, -20)      # GWL_EXSTYLE
        new_style = current & ~0x80                     # 去掉 WS_EX_TOOLWINDOW
        if taskbar:
            new_style |= 0x40000                        # 加上 WS_EX_APPWINDOW
        if new_style != current:
            user32.SetWindowLongW(hwnd, -20, new_style)
            user32.SetWindowPos(                      # 强制刷新窗口框架
                hwnd, 0, 0, 0, 0, 0,
                0x0002 | 0x0001 | 0x0020)             # NOMOVE|NOSIZE|FRAMECHANGED
        latest = user32.GetWindowLongW(hwnd, -20)
        if latest & 0x80:                             # 工具窗口标记没清掉
            return False
        return bool(latest & 0x40000) if taskbar else True
    except Exception:
        return False


def force_appwindow_style(win, taskbar=True):
    """兜底：窗口已显示后才发现未参与窗口管理时，强制外壳立即重建

    仅改扩展样式时，外壳往往要等窗口下一次被激活才补建任务栏按钮，
    表现为「窗口已出现、图标要点击或切焦点后才出现」。这里隐藏再显示
    一次，迫使外壳立刻重建，代价是闪一下，因此只在预设置未生效时使用；
    taskbar=False 的窗口不占任务栏按钮，也就无需这一下重建。
    """
    if set_appwindow_style(win, taskbar):
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id())
        if not hwnd:
            return
        current = user32.GetWindowLongW(hwnd, -20)
        style = (current & ~0x80) | (0x40000 if taskbar else 0)
        user32.SetWindowLongW(hwnd, -20, style)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                            0x0002 | 0x0001 | 0x0020)
        if taskbar:
            user32.ShowWindow(hwnd, 0)   # SW_HIDE
            user32.ShowWindow(hwnd, 5)   # SW_SHOW
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def ensure_alt_tab(win):
    """让提示框一类窗口进入 Alt+Tab，但不占任务栏按钮

    无边框窗口的 WS_EX_TOOLWINDOW 由 Tk 在空闲时补上：早于它去清理，
    标记随后会被重新加回来。故此处先让窗口实现出来再改样式，万一这次
    仍未改到，稍后再强制一次（不占任务栏的窗口无需隐藏重建，不会闪）。
    """
    try:
        win.update_idletasks()
    except tk.TclError:
        return
    if not set_appwindow_style(win, taskbar=False):
        win.after(60, lambda: force_appwindow_style(win, taskbar=False))


def show_and_focus(win):
    """把窗口从最小化恢复并置于前台，用于重复打开同一窗口时的「唤起」"""
    try:
        win.deiconify()
        win.lift()
    except tk.TclError:
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id())
        if hwnd:
            user32.ShowWindow(hwnd, 9)            # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


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
