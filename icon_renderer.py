"""
IndeXar 图标渲染器
用 Pillow 在内存中绘制矢量图标，返回 Tkinter PhotoImage
完全不受系统 emoji 渲染影响
"""

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

    # 上方标签片
    draw.rectangle([2, 4, 9, 8], fill=color)

    # 主体
    draw.rectangle([2, 8, 22, 20], fill=color)

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


def _dim(hex_color: str, factor: float) -> str:
    """颜色变暗"""
    r = int(int(hex_color[1:3], 16) * factor)
    g = int(int(hex_color[3:5], 16) * factor)
    b = int(int(hex_color[5:7], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"
