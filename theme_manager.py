"""
IndeXar 主题管理
VS Code 风格：亮色/暗色两套配色
"""


class VSCodeTheme:
    """VS Code 风格配色方案"""

    LIGHT = {
        "app_bg": "#f3f3f3",
        "toolbar_bg": "#ececec",
        "toolbar_fg": "#333333",
        "toolbar_btn_bg": "#ececec",
        "toolbar_btn_fg": "#333333",
        "toolbar_btn_hover": "#dadada",
        "search_bg": "#ffffff",
        "search_fg": "#333333",
        "search_border": "#cecece",

        "nav_bg": "#d8d8d8",
        "nav_fg": "#6a6a6a",
        "nav_active_fg": "#1f4e79",
        "nav_hover_bg": "#cccccc",

        "sidebar_bg": "#e8e8e8",
        "sidebar_fg": "#333333",
        "sidebar_header_bg": "#e0e0e0",
        "sidebar_header_fg": "#555555",
        "sidebar_item_selected": "#d0d0d0",
        "sidebar_item_hover": "#dadada",

        "menu_bg": "#ffffff",
        "menu_fg": "#333333",
        "menu_hover": "#e8e8e8",

        "content_bg": "#ffffff",
        "content_fg": "#212529",
        "content_header_bg": "#f0f0f0",
        "content_header_fg": "#555555",

        "status_bg": "#007acc",
        "status_fg": "#ffffff",

        "border": "#e0e0e0",
        "separator": "#e0e0e0",

        "tree_bg": "#e8e8e8",
        "tree_fg": "#333333",
        "tree_sel_bg": "#d0d0d0",
        "tree_sel_fg": "#333333",
        "tree_hover_bg": "#dcdcdc",

        "scroll_bg": "#e8e8e8",
        "scroll_trough": "#e8e8e8",
        "scroll_thumb": "#808080",
        "scroll_arrow": "#666666",

        "selection_bg": "#cce8ff",
        "selection_fg": "#212529",
    }

    DARK = {
        # 整体更暗，对比更强烈
        "app_bg": "#1e1e1e",

        "toolbar_bg": "#2d2d2d",
        "toolbar_fg": "#e0e0e0",
        "toolbar_btn_bg": "#2d2d2d",
        "toolbar_btn_fg": "#cccccc",
        "toolbar_btn_hover": "#404040",
        "search_bg": "#3c3c3c",
        "search_fg": "#e0e0e0",
        "search_border": "#5a5a5a",

        "nav_bg": "#333333",
        "nav_fg": "#858585",
        "nav_active_fg": "#ffffff",
        "nav_hover_bg": "#505050",

        "sidebar_bg": "#252526",
        "sidebar_fg": "#cccccc",
        "sidebar_header_bg": "#2d2d2d",
        "sidebar_header_fg": "#999999",
        "sidebar_item_selected": "#37373d",

        "menu_bg": "#333333",
        "menu_fg": "#cccccc",
        "menu_hover": "#3c3c3c",
        "sidebar_item_hover": "#2a2d2e",

        "content_bg": "#1e1e1e",
        "content_fg": "#d4d4d4",
        "content_header_bg": "#252526",
        "content_header_fg": "#aaaaaa",

        "status_bg": "#007acc",
        "status_fg": "#ffffff",

        "border": "#3c3c3c",
        "separator": "#3c3c3c",

        "tree_bg": "#252526",
        "tree_fg": "#cccccc",
        "tree_sel_bg": "#37373d",
        "tree_sel_fg": "#ffffff",
        "tree_hover_bg": "#2e2e30",

        "scroll_bg": "#252526",
        "scroll_trough": "#252526",
        "scroll_thumb": "#666666",
        "scroll_arrow": "#aaaaaa",

        "selection_bg": "#264f78",
        "selection_fg": "#ffffff",
    }

    @staticmethod
    def get(mode: str):
        """获取指定模式的配色"""
        if mode == "dark":
            return VSCodeTheme.DARK
        return VSCodeTheme.LIGHT
