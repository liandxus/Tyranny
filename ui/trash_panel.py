"""
IndeXar 回收站面板

应用内回收站（data/.trash/）的浏览与管理：按删除时间分批展示、
排序方向切换、条目恢复与彻底删除（支持多选与快捷键）。
"""

import tkinter as tk
from tkinter import ttk, messagebox

from context_menu import ContextMenu
from file_handler import (list_trash, restore_from_trash, delete_trash_entry,
                          empty_trash)
from ui.common import _add_hover_bg


def _format_stamp(stamp):
    """20260911_022945 → 2026-09-11 02:29:45"""
    try:
        d, t = stamp.split("_")
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]} {t[0:2]}:{t[2:4]}:{t[4:6]}"
    except (ValueError, IndexError):
        return stamp


class TrashPanelMixin:
    """回收站面板"""

    def _build_trash_panel(self):
        """回收站面板：按删除批次列出条目，支持排序、恢复与彻底删除"""
        self.trash_frame = tk.Frame(self.side_frame)

        # ── 头部：标题 + 排序 + 清空 ──
        self.trash_header = tk.Frame(self.trash_frame)
        self.trash_header.pack(fill=tk.X)

        self.trash_title = tk.Label(
            self.trash_header, text="  回收站", anchor=tk.W,
            font=("Microsoft YaHei", 9), padx=4, pady=4)
        self.trash_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.trash_sort_btn = tk.Label(
            self.trash_header, text="", font=("Microsoft YaHei", 8),
            padx=6, pady=4, cursor="hand2")
        self.trash_sort_btn.pack(side=tk.RIGHT)
        self.trash_sort_btn.bind("<Button-1>",
                                 lambda e: self._toggle_trash_sort())
        _add_hover_bg(self.trash_sort_btn, self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])

        self.trash_empty_btn = tk.Label(
            self.trash_header, text="清空", font=("Microsoft YaHei", 8),
            padx=6, pady=4, cursor="hand2")
        self.trash_empty_btn.pack(side=tk.RIGHT)
        self.trash_empty_btn.bind("<Button-1>",
                                  lambda e: self._empty_trash_confirm())
        _add_hover_bg(self.trash_empty_btn, self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])

        # ── 列表 ──
        body = tk.Frame(self.trash_frame)
        body.pack(fill=tk.BOTH, expand=True)
        self.trash_body = body

        self.trash_scroll = ttk.Scrollbar(body, orient=tk.VERTICAL)
        self.trash_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.trash_tree = ttk.Treeview(
            body, columns=("name", "time"), show="headings",
            selectmode="extended")
        self.trash_tree.heading("name", text="名称", anchor=tk.W)
        self.trash_tree.heading("time", text="删除时间", anchor=tk.W)
        self.trash_tree.column("name", width=110, anchor=tk.W, stretch=True)
        self.trash_tree.column("time", width=132, anchor=tk.W, stretch=False)
        self.trash_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.trash_scroll.configure(command=self.trash_tree.yview)
        self.trash_tree.configure(yscrollcommand=self.trash_scroll.set)

        # ── 交互：双击恢复、Del 彻底删除、右键菜单 ──
        self.trash_tree.bind("<Double-Button-1>",
                             self._restore_trash_selected)
        self.trash_tree.bind("<Return>", self._restore_trash_selected)
        self.trash_tree.bind("<Delete>",
                             lambda e: self._delete_trash_selected())
        self.trash_tree.bind("<Button-3>", self._show_trash_menu)
        self.trash_tree.bind("<Button-2>", self._show_trash_menu)

        self._refresh_trash_sort_label()

    # ── 渲染 ──

    def _refresh_trash(self):
        """重建回收站列表：每行一个条目，删除时间单独成列"""
        self.trash_tree.delete(*self.trash_tree.get_children())
        batches = list_trash(self._trash_sort_desc)
        if not batches:
            self.trash_tree.insert("", "end", iid="__trash_empty__",
                                   values=("（回收站为空）", ""))
            return
        for stamp, entries in batches:
            label = _format_stamp(stamp)
            for entry in entries:
                self.trash_tree.insert(
                    "", "end", iid=f"t:{stamp}\t{entry}",
                    values=(entry, label))

    def _refresh_trash_sort_label(self):
        self.trash_sort_btn.configure(
            text="时间 ↓" if self._trash_sort_desc else "时间 ↑")

    def _toggle_trash_sort(self):
        """切换删除时间排序方向（新 → 旧 / 旧 → 新）"""
        self._trash_sort_desc = not self._trash_sort_desc
        self._refresh_trash_sort_label()
        self._refresh_trash()

    # ── 选中项 ──

    def _trash_selected_pairs(self):
        """从 iid（t:<时间戳>\t<条目名>）解析当前选中的 [(stamp, entry), ...]"""
        pairs = []
        for iid in self.trash_tree.selection():
            if not iid.startswith("t:"):
                continue
            stamp, _, entry = iid[2:].partition("\t")
            if stamp and entry:
                pairs.append((stamp, entry))
        return pairs

    # ── 恢复 / 删除 ──

    def _restore_trash_selected(self, event=None):
        """把选中的条目恢复到原位置（双击 / Enter / 右键菜单）"""
        pairs = self._trash_selected_pairs()
        if not pairs:
            return
        restored, failed = [], []
        for stamp, entry in pairs:
            name = restore_from_trash(stamp, entry)
            (restored if name else failed).append(entry)

        self._refresh_trash()
        self._refresh_file_tree()
        self._snapshot_files()      # 抑制轮询自触发
        self._rebuild_indexes()

        msg = f"已恢复 {len(restored)} 项"
        if failed:
            msg += f"，{len(failed)} 项失败"
        self.status_left.configure(text=f"   {msg}")

    def _delete_trash_selected(self):
        """彻底删除选中的条目（不可恢复，需确认）"""
        pairs = self._trash_selected_pairs()
        if not pairs:
            return
        names = "\n".join(e for _s, e in pairs[:8])
        more = f"\n…等共 {len(pairs)} 个项目" if len(pairs) > 8 else ""
        if len(pairs) == 1:
            title = "永久删除文件"
            msg = f"确实要永久删除此项目吗？\n\n{names}"
        else:
            title = "永久删除多个项目"
            msg = f"确实要永久删除这 {len(pairs)} 个项目吗？\n\n{names}{more}"
        if not messagebox.askyesno(title, msg):
            return
        done = 0
        for stamp, entry in pairs:
            if delete_trash_entry(stamp, entry):
                done += 1
        self._refresh_trash()
        self.status_left.configure(text=f"   已彻底删除 {done} 项")

    def _empty_trash_confirm(self):
        """清空回收站（需确认）"""
        batches = list_trash()
        total = sum(len(e) for _s, e in batches)
        if total == 0:
            self.status_left.configure(text="   回收站已经是空的")
            return
        if not messagebox.askyesno(
                "删除多个项目",
                f"确实要永久删除这 {total} 个项目吗？"):
            return
        empty_trash()
        self._refresh_trash()
        self.status_left.configure(text="   回收站已清空")

    # ── 右键菜单 ──

    def _show_trash_menu(self, event):
        iid = self.trash_tree.identify_row(event.y)
        if iid and iid not in self.trash_tree.selection():
            self.trash_tree.selection_set(iid)
        pairs = self._trash_selected_pairs()
        if not pairs:
            return
        count = len(pairs)
        suffix = f"选中 {count} 项" if count > 1 else ""
        items = [
            (f"恢复  {suffix}".rstrip(), self._restore_trash_selected),
            (f"彻底删除  {suffix}".rstrip(), self._delete_trash_selected),
            None,
            ("清空回收站", self._empty_trash_confirm),
        ]
        menu = ContextMenu(self.root, colors=self._get_menu_colors())
        menu.show(event.x_root, event.y_root, items, use_grab=False)
