"""
IndeXar 图标渲染器
用 Pillow 在内存中绘制矢量图标，返回 Tkinter PhotoImage
完全不受系统 emoji 渲染影响
"""

import os
from PIL import Image, ImageDraw, ImageTk

SIZE = 24  # 图标像素尺寸


def _make_image() -> tuple:
    """创建透明底图 + 绘图对象"""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _photo(img: Image.Image) -> ImageTk.PhotoImage:
    """Image → PhotoImage（保持引用）"""
    return ImageTk.PhotoImage(img)


def folder_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """📁 风格的文件夹图标"""
    img, draw = _make_image()

    # 上方标签片（缩小凸起）
    draw.rectangle([4, 6, 9, 8], fill=color)

    # 主体
    draw.rectangle([3, 8, 21, 20], fill=color)

    return _photo(img)


def tag_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """书签图标（折角纸片，尖角朝右上）"""
    img, draw = _make_image()

    # 主体（右上角切掉一块的五边形）
    draw.polygon([
        (3, 3),     # 左上
        (12, 3),    # 折线起点（上边）
        (21, 12),   # 折线终点（右边）
        (21, 21),   # 右下
        (3, 21),    # 左下
    ], fill=color)

    # 折回来的三角（用稍亮的颜色模拟纸背）
    draw.polygon([
        (12, 3),    # 折线起点
        (21, 3),    # 原本的右上角
        (21, 12),   # 折线终点
    ], fill=_dim(color, 0.75))

    return _photo(img)


def files_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """多文件堆叠图标（可替代 📁）"""
    img, draw = _make_image()

    # 底层文件
    draw.rectangle([4, 5, 22, 21], fill=_dim(color, 0.7))
    # 顶层文件
    draw.polygon([
        (2, 8),
        (2, 20),
        (20, 20),
        (20, 4),
        (6, 4),
    ], fill=color)

    return _photo(img)


def trash_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """垃圾桶图标（应用内回收站）"""
    img, draw = _make_image()

    # 提手
    draw.rectangle([9, 2, 15, 4], fill=color)
    # 盖子
    draw.rectangle([4, 5, 20, 7], fill=color)
    # 桶身（竖直矩形）
    draw.rectangle([6, 8, 18, 21], fill=color)
    # 桶身竖纹
    for x in (10, 12, 14):
        draw.line([(x, 10), (x, 19)], fill=_dim(color, 0.55), width=1)

    return _photo(img)


def sun_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """太阳图标（实心圆 + 八方向短光芒线）"""
    img, draw = _make_image()

    # 中心圆
    draw.ellipse([9, 9, 15, 15], fill=color)

    # 八条短光芒（从圆边向外延伸 2px）
    rays = [
        (12, 5, 12, 3),    # N
        (12, 19, 12, 21),  # S
        (5, 12, 3, 12),    # W
        (19, 12, 21, 12),  # E
        (7, 7, 6, 5),      # NW
        (17, 7, 18, 5),    # NE
        (7, 17, 6, 19),    # SW
        (17, 17, 18, 19),  # SE
    ]
    for x1, y1, x2, y2 in rays:
        draw.line([(x1, y1), (x2, y2)], fill=color, width=2)

    return _photo(img)


def moon_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """月亮图标（月牙形）"""
    img, draw = _make_image()

    # 主圆
    draw.ellipse([7, 7, 17, 17], fill=color)
    # 切掉一块形成月牙
    draw.ellipse([11, 5, 19, 15], fill=(0, 0, 0, 0))

    return _photo(img)


# ── 内置 SVG 渲染引擎 ──

def _svg_to_image(svg_text: str, color: str = "#888888", size: int = 24) -> Image.Image:
    """
    将 Tabler Icons 风格的 SVG 路径渲染为 Pillow Image。
    只支持 stroke-based 图标（fill=none, stroke=color）。
    """
    import xml.etree.ElementTree as ET
    from svg.path import parse_path, Line, CubicBezier, QuadraticBezier, Arc, Close, Move

    # 高分辨率渲染（2x）再降采样，获得更平滑的线条
    scale = 2
    render_size = size * scale

    img = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    root = ET.fromstring(svg_text)

    # 解析 viewBox
    ns = {"svg": "http://www.w3.org/2000/svg"}
    vb = root.get("viewBox", "0 0 24 24")
    vx, vy, vw, vh = [float(x) for x in vb.split()]
    sx = render_size / vw
    sy = render_size / vh

    # 解析继承属性
    def _inherit(el, attr, default):
        val = el.get(attr)
        if val is not None:
            return val
        parent = el
        while True:
            parent = None  # SVG 中继承来自父元素，简化：从 root 取
            val = root.get(attr)
            if val is not None:
                return val
            return default

    default_stroke_width = float(root.get("stroke-width", "2"))

    def _scale(pt):
        return (pt.real * sx, pt.imag * sy)

    for path_elem in root.findall(".//svg:path", ns) or root.findall(".//path"):
        d = path_elem.get("d", "")
        if not d:
            continue

        # 跳过背景裁剪路径
        if d.strip() in (
            f"M0 0h{int(vw)}v{int(vh)}H0z",
            f"M0 0h{int(vw):g}v{int(vh):g}H0z",
        ):
            continue

        fill = path_elem.get("fill", root.get("fill", "none"))
        stroke = path_elem.get("stroke", root.get("stroke", "currentColor"))
        sw = float(path_elem.get("stroke-width", str(default_stroke_width)))

        if stroke == "currentColor":
            stroke = color
        if fill == "currentColor":
            fill = color

        parsed = parse_path(d)

        stroke_px = max(1, int(round(sw * scale)))

        # 收集点序列
        points = []
        subpath_start = None

        for seg in parsed:
            if isinstance(seg, Move):
                # 画上一个子路径
                if stroke != "none" and len(points) > 1:
                    _draw_stroke_path(draw, points, color, stroke_px)
                points = []
                subpath_start = seg.end
                points.append(_scale(seg.end))
            elif isinstance(seg, Close):
                if subpath_start is not None:
                    points.append(_scale(subpath_start))
            elif isinstance(seg, Line):
                points.append(_scale(seg.end))
            elif isinstance(seg, CubicBezier):
                for t in [i / 20 for i in range(1, 21)]:
                    points.append(_scale(seg.point(t)))
            elif isinstance(seg, QuadraticBezier):
                for t in [i / 10 for i in range(1, 11)]:
                    points.append(_scale(seg.point(t)))
            elif isinstance(seg, Arc):
                for t in [i / 16 for i in range(1, 17)]:
                    points.append(_scale(seg.point(t)))

        # 剩余点
        if stroke != "none" and len(points) > 1:
            _draw_stroke_path(draw, points, color, stroke_px)

    # 降采样
    if scale > 1:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def _draw_stroke_path(draw, points, color, width):
    """在点之间画线段（连笔效果）"""
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=color, width=width)


# ── SVG 图标工厂 ──

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_SVG_CACHE = {}


def svg_icon(filename: str, color: str = "#888888", size: int = 24) -> ImageTk.PhotoImage:
    """加载 assets/ 下的 SVG 文件并渲染为 PhotoImage"""
    filepath = os.path.join(_ASSETS_DIR, filename)
    if not os.path.exists(filepath):
        # fallback: 返回一个空图标
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        return _photo(img)

    # 缓存 SVG 文本（不缓存渲染结果，因为颜色会变）
    if filepath not in _SVG_CACHE:
        with open(filepath, "r", encoding="utf-8") as f:
            _SVG_CACHE[filepath] = f.read()

    svg_text = _SVG_CACHE[filepath]
    img = _svg_to_image(svg_text, color, size)
    return _photo(img)


def file_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """新建笔记图标（Tabler file-plus）"""
    return svg_icon("file-plus.svg", color)


def folder_plus_icon(color: str = "#888888") -> ImageTk.PhotoImage:
    """新建文件夹图标（Tabler folder-plus）"""
    return svg_icon("folder-plus.svg", color)


_TREE_ARROW_SIZE = 11


def tree_arrow_right(color: str = "#888888", size: int = 11):
    """▶ 右指三角形箭头（树折叠态）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = size // 4  # margin
    x0, x1 = m, size - m - 1
    y0, y1 = m, size - m - 1
    cy = (y0 + y1) // 2
    draw.polygon([(x0, y0), (x1, cy), (x0, y1)], fill=color)
    return _photo(img)


def tree_arrow_down(color: str = "#888888", size: int = _TREE_ARROW_SIZE):
    """▼ 下指三角形箭头（树展开态）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = size // 4
    x0, x1 = m, size - m - 1
    y0, y1 = m, size - m - 1
    cx = (x0 + x1) // 2
    draw.polygon([(x0, y0), (cx, y1), (x1, y0)], fill=color)
    return _photo(img)


def _dim(hex_color: str, factor: float) -> str:
    """颜色变暗"""
    r = int(int(hex_color[1:3], 16) * factor)
    g = int(int(hex_color[3:5], 16) * factor)
    b = int(int(hex_color[5:7], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"
