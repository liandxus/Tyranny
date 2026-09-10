"""
IndeXar 界面通用工具

与具体面板无关的共享工具：控件 hover 效果、颜色计算、资源路径。
"""

import os

# 项目根目录与资源目录
# 各界面模块位于 ui/ 包内，不能再用自身 __file__ 推导资源位置，统一在此定义。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")

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
