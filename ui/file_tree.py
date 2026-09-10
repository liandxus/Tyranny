"""
IndeXar 文件树面板

左侧文件树的构建与刷新、展开折叠、悬停高亮、右键菜单
（新建笔记/新建文件夹/重命名/删除/资源管理器打开/外部编辑器），
以及笔记的打开入口。
"""

import os
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

import icon_renderer
from context_menu import ContextMenu
from file_handler import (list_notes_tree, create_note, make_subdir,
                          rename_note, rename_folder, delete_note,
                          delete_folder)
from ui.common import _add_hover_bg


class FileTreeMixin:
    """文件树面板与文件操作"""

    def _build_file_tree_panel(self):
        """文件树"""
        self.file_tree_frame = tk.Frame(self.side_frame)
        # 头部行：笔记列表标题 + 并排新建按钮
        self._tree_header_frame = tk.Frame(self.file_tree_frame)
        self._tree_header_frame.pack(fill=tk.X)
        self.side_header = tk.Label(
            self._tree_header_frame,
            text="   笔记列表",
            font=("Microsoft YaHei", 10),
            anchor=tk.W, padx=8, pady=6,
        )
        self.side_header.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 新建文件夹 + 新建笔记，并排放在右侧（如 VS Code）
        self._new_folder_img = icon_renderer.folder_plus_icon(
            self.colors["sidebar_header_fg"]
        )
        self.new_folder_btn = tk.Button(
            self._tree_header_frame,
            image=self._new_folder_img,
            cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            padx=4, pady=0,
        )
        self.new_folder_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self.new_folder_btn.config(
            command=lambda: self._create_folder(
                default_dir=self._get_tree_context_dir()))

        self._new_note_img = icon_renderer.file_icon(
            self.colors["sidebar_header_fg"]
        )
        self.new_note_btn = tk.Button(
            self._tree_header_frame,
            image=self._new_note_img,
            cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            padx=4, pady=0,
        )
        self.new_note_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.new_note_btn.config(
            command=lambda: self._create_note(
                default_dir=self._get_tree_context_dir()))

        # 刷新文件树按钮
        self._refresh_img = icon_renderer.svg_icon(
            "refresh.svg", self.colors["sidebar_header_fg"])
        self.refresh_btn = tk.Button(
            self._tree_header_frame,
            image=self._refresh_img,
            cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
            padx=4, pady=0,
            command=self._refresh_file_tree,
        )
        self.refresh_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ── hover 效果 ──
        _add_hover_bg(self.new_folder_btn,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])
        _add_hover_bg(self.new_note_btn,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])
        _add_hover_bg(self.refresh_btn,
                      self.colors["sidebar_header_bg"],
                      self.colors["sidebar_item_selected"])

        self.tree_container = tk.Frame(self.file_tree_frame)
        self.tree_container.pack(fill=tk.BOTH, expand=True)

        self.tree_scroll = ttk.Scrollbar(
            self.tree_container, orient=tk.VERTICAL,
        )
        self.tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(self.tree_container, show="tree",
                                 selectmode="extended")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_scroll.configure(command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_file_selected)
        # 快捷键：Del 删除、F2 重命名（仅文件树获得焦点时生效）
        self.tree.bind("<Delete>", lambda e: self._tree_context_delete())
        self.tree.bind("<F2>", lambda e: self._rename_selected())

        # ── 文件树行悬停高亮 ──
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)

        # ── 当前文件标签（共享组件）──
        self._build_file_tags_section(self.file_tree_frame, "file_")

        # 右键菜单
        self._build_tree_context_menu()

    def _build_tree_context_menu(self):
        """文件树右键菜单（自定义无边框菜单）"""
        self.tree_menu = ContextMenu(self.root, colors={
            "bg": self.colors["sidebar_bg"],
            "fg": self.colors["sidebar_fg"],
            "activebackground": self.colors["sidebar_item_selected"],
            "activeforeground": self.colors["sidebar_fg"],
            "separator": self.colors.get("separator", "#d0d0d0"),
        })
        self._tree_menu_items = [
            ("新建笔记", self._tree_context_new),
            ("新建文件夹", self._tree_context_new_folder),
            None,  # separator
            ("重命名", self._tree_context_rename),
            ("删除", self._tree_context_delete),
            None,  # separator
            ("在资源管理器中打开", self._tree_context_reveal),
        ]
        self.tree.bind("<Button-3>", self._show_tree_menu)

    def _on_tree_motion(self, event):
        """文件树行鼠标悬停 → 高亮"""
        iid = self.tree.identify_row(event.y)
        prev = getattr(self, '_tree_hover_item', None)
        if prev and prev != iid:
            try:
                self.tree.item(prev, tags=())
            except tk.TclError:
                pass
        if iid:
            self.tree.item(iid, tags=('hover',))
            self._tree_hover_item = iid
        else:
            self._tree_hover_item = None

    def _on_tree_leave(self, event):
        """鼠标离开文件树 → 清除悬停高亮"""
        prev = getattr(self, '_tree_hover_item', None)
        if prev:
            try:
                self.tree.item(prev, tags=())
            except tk.TclError:
                pass
            self._tree_hover_item = None


    def _show_tree_menu(self, event):
        """右键点击树节点时显示自定义菜单（根据文件/文件夹动态切换）"""
        iid = self.tree.identify_row(event.y)
        # 设置标志防止 _on_file_selected 误触发文件夹 toggle
        self._right_clicking = True

        if iid:
            # 右键点的项不在当前选中集合内 → 选择切换到该项；
            # 已在集合内 → 保留多选，供批量操作使用
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            vals = self.tree.item(iid, "values")
            is_dir = vals and (vals[1] == "True" or vals[1] is True)
            selected = self._selected_tree_items()

            if len(selected) > 1:
                n = len(selected)
                items = [
                    (f"删除这 {n} 个项目", self._tree_context_delete),
                    (f"移动这 {n} 个项目到…", self._tree_context_move),
                ]
            elif is_dir:
                items = [
                    ("新建笔记", self._tree_context_new),
                    ("新建文件夹", self._tree_context_new_folder),
                    None,
                    ("重命名文件夹", self._rename_selected),
                    ("移动到…", self._tree_context_move),
                    ("删除文件夹", self._tree_context_delete),
                    None,
                    ("在资源管理器中打开", self._tree_context_reveal),
                ]
            else:
                items = [
                    ("新建笔记", self._tree_context_new),
                    ("新建文件夹", self._tree_context_new_folder),
                    None,
                    ("外部编辑器打开", self._open_in_editor),
                    ("移动到…", self._tree_context_move),
                    None,
                    ("重命名", self._rename_selected),
                    ("删除", self._tree_context_delete),
                    None,
                    ("在资源管理器中打开", self._tree_context_reveal),
                ]
        else:
            # 点在空白区域 → 清空选中，仅提供新建
            self.tree.selection_set(())
            items = [
                ("新建笔记", self._tree_context_new),
                ("新建文件夹", self._tree_context_new_folder),
            ]

        # 每次显示菜单都传入当前主题色（保证主题切换后颜色即时更新）
        # use_grab=False 避免和新创建对话框的 grab 冲突导致卡死
        self.tree_menu.show(
            event.x_root, event.y_root, items,
            colors_override={
                "bg": self.colors["menu_bg"],
                "fg": self.colors["menu_fg"],
                "activebackground": self.colors["menu_hover"],
                "activeforeground": self.colors["menu_fg"],
                "separator": self.colors.get("separator", "#d0d0d0"),
            },
            use_grab=False)

    def _get_tree_context_dir(self):
        """返回右键选中项所在的目录路径（相对路径）"""
        sel = self.tree.selection()
        if not sel:
            return ""
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return ""
        iid, is_dir = vals[0], vals[1]
        if is_dir == "True" or is_dir is True:
            return iid  # 选中了文件夹，直接用它
        else:
            # 选中了文件，取其所在目录
            parts = iid.rsplit("/", 1)
            return parts[0] if len(parts) > 1 else ""

    def _tree_context_new(self):
        """右键 → 新建笔记"""
        self._create_note(default_dir=self._get_tree_context_dir())

    def _tree_context_new_folder(self):
        """右键 → 新建文件夹"""
        from file_handler import make_subdir
        parent = self._get_tree_context_dir()

        dialog = self._make_dialog(self.root, "新建文件夹", 380, 180)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        hint = f"在 {(parent or '根目录')} 下新建："
        tk.Label(frame, text=hint, anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 8))
        name_var = tk.StringVar(value="new_folder")
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10))
        entry.pack(fill=tk.X, pady=(0, 12))
        entry.select_range(0, tk.END)
        entry.focus_set()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))

        def do_create():
            name = name_var.get().strip()
            if name:
                make_subdir(parent, name)
                dialog.destroy()
                self._refresh_file_tree()

        tk.Button(btn_frame, text="创建", font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)

    def _tree_context_rename(self):
        """右键 → 重命名（文件/文件夹）"""
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        iid, is_dir = vals[0], vals[1]
        is_dir = (is_dir == "True" or is_dir is True)
        from file_handler import rename_note, rename_folder

        old_name = os.path.basename(iid)
        item_type = "文件夹" if is_dir else "笔记"

        dialog = self._make_dialog(self.root, f"重命名{item_type}", 380, 180)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text=f"重命名 {item_type}：{old_name}", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 8))
        name_var = tk.StringVar(value=old_name)
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10))
        entry.pack(fill=tk.X, pady=(0, 12))
        entry.select_range(0, tk.END)
        entry.focus_set()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))

        def do_rename():
            new_name = name_var.get().strip()
            if new_name and new_name != old_name:
                if is_dir:
                    rename_folder(iid, new_name)
                else:
                    rename_note(iid, new_name)
                dialog.destroy()
                self._refresh_file_tree()
                self._snapshot_files()  # 抑制轮询自触发

        tk.Button(btn_frame, text="确认", font=("Microsoft YaHei", 9),
                  command=do_rename).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_rename())
        self._theme_dialog_body(dialog)

    def _selected_tree_items(self):
        """
        返回选中的 [(相对路径, is_dir), ...]。
        已被选中文件夹包含的子项会被剔除，避免重复处理。
        """
        raw = []
        for sel in self.tree.selection():
            vals = self.tree.item(sel, "values")
            if not vals:
                continue
            path = vals[0]
            if not isinstance(path, str):
                continue
            if path == "__header__" or path.startswith("__snippet_"):
                continue
            is_dir = (vals[1] == "True" or vals[1] is True)
            raw.append((path, is_dir))

        paths = {p for p, _ in raw}
        result = []
        for path, is_dir in raw:
            if any(other != path and path.startswith(other + "/")
                   for other in paths):
                continue          # 该路径位于另一个被选中的文件夹内
            result.append((path, is_dir))
        return result

    def _rename_selected(self):
        """F2 / 右键重命名：仅支持单个文件或文件夹"""
        if len(self.tree.selection()) != 1:
            self.status_left.configure(text="   重命名仅支持单个文件或文件夹")
            return
        self._tree_context_rename()

    def _tree_context_delete(self):
        """右键 / Del → 删除（支持多选，移入回收站）"""
        items = self._selected_tree_items()
        if not items:
            return

        if len(items) == 1:
            path, is_dir = items[0]
            name = os.path.basename(path)
            if is_dir:
                title = "删除文件夹"
                msg = f"确实要将此文件夹及其内容放入回收站吗？\n\n{name}"
            else:
                title = "删除文件"
                msg = f"确实要将此文件放入回收站吗？\n\n{name}"
        else:
            names = "\n".join(os.path.basename(p) for p, _ in items[:8])
            more = f"\n…等共 {len(items)} 个项目" if len(items) > 8 else ""
            title = "删除多个项目"
            msg = (f"确实要将这 {len(items)} 个项目放入回收站吗？\n\n"
                   f"{names}{more}")

        if not messagebox.askyesno(title, msg):
            return

        from file_handler import delete_folder, delete_note
        for path, is_dir in items:
            if is_dir:
                delete_folder(path)
            else:
                delete_note(path)

        # 当前打开的笔记被删除 → 清空内容区
        cur = self._current_note_path
        if cur and any(p == cur or cur.startswith(p + "/") for p, _ in items):
            self._set_content("")
            self._current_note_path = None

        self._refresh_file_tree()
        self._snapshot_files()      # 抑制轮询自触发
        self._rebuild_indexes()
        self.status_left.configure(text=f"   已移入回收站 {len(items)} 项")

    def _tree_context_move(self):
        """右键 → 移动到…（支持多选）"""
        items = self._selected_tree_items()
        if not items:
            return

        from tkinter import filedialog
        from file_handler import DATA_DIR, move_item

        abs_dir = filedialog.askdirectory(
            parent=self.root, title="选择目标文件夹",
            initialdir=DATA_DIR, mustexist=True)
        if not abs_dir:
            return

        rel = os.path.relpath(abs_dir, DATA_DIR).replace("\\", "/")
        if rel.startswith(".."):
            messagebox.showwarning("无法移动",
                                   "目标文件夹必须位于笔记库（data）内。")
            return
        target = "" if rel == "." else rel

        moved, failed = 0, []
        for path, is_dir in items:
            if move_item(path, target, is_dir):
                moved += 1
            else:
                failed.append(os.path.basename(path))

        self._refresh_file_tree()
        self._snapshot_files()
        self._rebuild_indexes()

        msg = f"已移动 {moved} 项到「{target or '根目录'}」"
        if failed:
            msg += f"，{len(failed)} 项失败（重名或不可移动）"
        self.status_left.configure(text=f"   {msg}")

    def _tree_context_reveal(self):
        """右键 → 在资源管理器中打开"""
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        iid, is_dir = vals[0], vals[1]
        from file_handler import DATA_DIR
        if is_dir == "True" or is_dir is True:
            target = os.path.join(DATA_DIR, iid)
        else:
            target = os.path.join(DATA_DIR, f"{iid}.md")
        if os.path.exists(target):
            import subprocess
            subprocess.run(["explorer", "/select,", os.path.normpath(target)])

    def _open_current_in_editor(self):
        """顶部'编辑'按钮：打开当前正在浏览的笔记"""
        if not self._current_note_path:
            self.status_left.configure(text="   请先打开一篇笔记")
            return
        from file_handler import DATA_DIR
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        if not os.path.exists(filepath):
            self.status_left.configure(text="   找不到笔记文件")
            return
        self._open_in_editor(filepath)

    def _open_in_editor(self, filepath=None):
        """用外部编辑器打开文件"""
        import subprocess
        if filepath is None:
            sel = self.tree.selection()
            if not sel:
                return
            vals = self.tree.item(sel[0], "values")
            if not vals or vals[1] == "True" or vals[1] is True:
                return  # 跳过文件夹
            iid = vals[0]
            from file_handler import DATA_DIR
            filepath = os.path.join(DATA_DIR, f"{iid}.md")
            if not os.path.exists(filepath):
                return
        import shutil
        editor = self._editor_path or "notepad.exe"
        # 路径失效（软件被卸载或迁移）时回退系统记事本
        if not (os.path.isfile(editor) or shutil.which(editor)):
            editor = "notepad.exe"
        try:
            # 不使用 shell=True：路径含空格时会被二次解析，导致启动失败
            subprocess.Popen([editor, filepath])
        except Exception:
            subprocess.Popen(["notepad.exe", filepath])


    def _collect_expanded_dirs(self):
        """收集当前处于展开状态的目录相对路径（刷新前调用）"""
        expanded = set()

        def walk(parent):
            for iid in self.tree.get_children(parent):
                vals = self.tree.item(iid, "values")
                if vals and (vals[1] == "True" or vals[1] is True):
                    if self.tree.item(iid, "open"):
                        expanded.add(vals[0])
                    walk(iid)

        walk("")
        return expanded

    def _restore_expanded_dirs(self, expanded):
        """按路径恢复目录的展开状态（刷新后调用）"""
        def walk(parent):
            for iid in self.tree.get_children(parent):
                vals = self.tree.item(iid, "values")
                if vals and (vals[1] == "True" or vals[1] is True):
                    if vals[0] in expanded:
                        self.tree.item(iid, open=True)
                    walk(iid)

        walk("")

    def _refresh_file_tree(self):
        # 整树重建会丢失展开状态，先记下来，重建后恢复
        expanded = self._collect_expanded_dirs()
        for item in self.tree.get_children():
            self.tree.delete(item)
        tree = list_notes_tree()
        if not tree:
            self.tree.insert("", "end", text="   暂无笔记")
            self.status_left.configure(text="   0 个笔记")
            return
        count = self._populate_tree("", tree)
        self._restore_expanded_dirs(expanded)
        self.status_left.configure(text=f"   {count} 个笔记")

    def _populate_tree(self, parent_iid, items):
        """递归填充树节点，返回文件数"""
        file_count = 0
        for item in items:
            iid = item["path"]
            if item["is_dir"]:
                display = f" 📁 {item['name']}"
                node = self.tree.insert(
                    parent_iid, "end", iid=iid,
                    text=display, values=(iid, True),
                )
                if item["children"]:
                    file_count += self._populate_tree(node, item["children"])
                else:
                    self.tree.insert(node, "end", text="")
            else:
                display = f" 📄 {item['name']}"
                file_iid = f"f:{iid}"  # 前缀区分，避免与同名文件夹冲突
                self.tree.insert(
                    parent_iid, "end", iid=file_iid,
                    text=display, values=(iid, False),
                )
                file_count += 1
        return file_count

    def _on_file_selected(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        # 多选时不触发打开/展开，交给批量操作处理
        if len(selected) > 1:
            return
        vals = self.tree.item(selected[0], "values")
        if not vals:
            return
        if vals[0] == "__header__":
            return
        # 搜索片段点击 → 跳转到内容中的关键词位置
        if isinstance(vals[0], str) and vals[0].startswith("__snippet_"):
            idx = int(vals[0].split("_")[-1])
            self._jump_to_search_match(idx)
            return
        iid, is_dir = vals[0], vals[1]
        if getattr(self, '_right_clicking', False):
            self._right_clicking = False
            return
        if is_dir == "True" or is_dir is True:
            if self.tree.item(selected[0], "open"):
                self.tree.item(selected[0], open=False)
            else:
                self.tree.item(selected[0], open=True)
            return
        self._display_note(iid)
