# 归档目录

存放**当前未被主程序引用、但可能需要复用**的文件。
这里的文件不参与运行，可安全删除；如需恢复，直接移回原路径即可。

## 内容

### assets/

从 `assets/` 移入的未引用资源（`icon_renderer.py` 与 `gui.py` 均未引用）：

| 文件 | 说明 |
| :--- | :--- |
| `chevron-down.svg`、`chevron-right.svg` | 早期的展开/折叠三角箭头图标，后改用 `icon_renderer.tree_arrow_*()` 以 Pillow 绘制 |
| `dark_system.svg`、`light_system.svg` | Logo 源文件 |
| `dark_*.png`、`light_*.png`（32 / 48 / 64 / 128 / 256 / 512 / 1024） | 应用图标的多尺寸版本，供打包工具生成 `.ico` 使用；代码中只引用了 16px（窗口图标） |

**恢复方式**：移回 `assets/` 目录，保持文件名不变即可
（`icon_renderer.svg_icon()` 按文件名读取，不做目录扫描）。

### test_layout.py

布局调试脚本，可独立运行：`python archive/test_layout.py`。
与入口 `main.py` 无关，未被任何模块引用。
