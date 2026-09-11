"""
IndeXar 搜索面板

独立搜索界面：搜索输入框 + 结果列表（当前文件片段 / 文件名匹配 / 内容匹配），
为未来的高级搜索（按标签、时间、正则等）预留扩展区。

与内容区头部的「快捷搜索框」共享同一个 search_var，双向同步：
在头部输入回车会切到此面板显示结果；在此面板修改输入也会同步到头部。
"""

import tkinter as tk
from tkinter import ttk

from ui.common import _add_hover_bg


class SearchPanelMixin:
    """搜索面板"""

    def _build_search_panel(self):
        """构建搜索面板：输入框 + 结果列表 + 预留扩展区"""
        self.search_frame = tk.Frame(self.side_frame)

        # ── 头部：搜索输入框 + 清空 ──
        self.search_header = tk.Frame(self.search_frame)
        self.search_header.pack(fill=tk.X)

        # 复用内容区头部的 search_var（若已创建），实现双向同步
        if not isinstance(getattr(self, "search_var", None), tk.StringVar):
            self.search_var = tk.StringVar()

        self.panel_search_entry = tk.Entry(
            self.search_header, textvariable=self.search_var,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT, bd=0,
            highlightthickness=1, width=20,
        )
        self.panel_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                     padx=(8, 4), pady=6)
        self.panel_search_entry.bind("<Return>", lambda e: self._do_search())

        self.panel_search_clear = tk.Label(
            self.search_header, text="✕", font=("Microsoft YaHei", 9),
            cursor="hand2", padx=6)
        self.panel_search_clear.pack(side=tk.RIGHT, padx=(0, 8))
        self.panel_search_clear.bind("<Button-1>", lambda e: self._clear_search())
        _add_hover_bg(self.panel_search_clear,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])

        # ── 结果列表 ──
        body = tk.Frame(self.search_frame)
        body.pack(fill=tk.BOTH, expand=True)
        self.search_body = body

        self.search_scroll = ttk.Scrollbar(body, orient=tk.VERTICAL)
        self.search_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # selectmode=browse：单选（搜索结果一次打开一篇）
        self.search_tree = ttk.Treeview(body, show="tree", selectmode="browse")
        self.search_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.search_scroll.configure(command=self.search_tree.yview)
        self.search_tree.configure(yscrollcommand=self.search_scroll.set)

        # 行悬停高亮（与文件树一致）
        self.search_tree.tag_configure("hover",
            background=self.colors["tree_hover_bg"])

        # 点击结果项 → 打开笔记 / 跳转片段
        self.search_tree.bind("<<TreeviewSelect>>", self._on_search_result_select)
        self.search_tree.bind("<Motion>", self._on_search_tree_motion)
        self.search_tree.bind("<Leave>", self._on_search_tree_leave)

        # ── 预留扩展区（未来：按标签 / 时间 / 正则等高级搜索）──
        # 暂不构建控件，留作扩展点
        # self.search_advanced = tk.Frame(self.search_frame)
        # self.search_advanced.pack(fill=tk.X)

    def _on_search_result_select(self, event):
        """点击搜索结果项：__snippet_N 跳正文，其它当作笔记路径打开"""
        sel = self.search_tree.selection()
        if not sel:
            return
        vals = self.search_tree.item(sel[0], "values")
        if not vals:
            return
        kind = vals[0]
        if not isinstance(kind, str) or kind == "__header__":
            return
        if kind.startswith("__snippet_"):
            idx = int(kind.split("_")[-1])
            self._jump_to_search_match(idx)
            return
        # 从搜索结果打开笔记 → 高亮正文中所有关键词命中
        self._display_note(kind)
        self._highlight_current_keyword()

    def _on_search_tree_motion(self, event):
        iid = self.search_tree.identify_row(event.y)
        prev = getattr(self, "_search_hover_item", None)
        if prev and prev != iid:
            try:
                self.search_tree.item(prev, tags=())
            except tk.TclError:
                pass
        if iid:
            self.search_tree.item(iid, tags=("hover",))
            self._search_hover_item = iid
        else:
            self._search_hover_item = None

    def _on_search_tree_leave(self, event):
        prev = getattr(self, "_search_hover_item", None)
        if prev:
            try:
                self.search_tree.item(prev, tags=())
            except tk.TclError:
                pass
            self._search_hover_item = None

    def _refresh_search_results(self):
        """清空搜索结果树（清空搜索框或切换主题时调用）"""
        try:
            for item in self.search_tree.get_children():
                self.search_tree.delete(item)
        except tk.TclError:
            pass
