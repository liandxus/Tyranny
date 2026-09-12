"""
IndeXar 界面通用工具

与具体面板无关的共享工具：控件 hover 效果、颜色计算、资源路径。
"""

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
