"""
IndeXar 文件树面板

左侧文件树的构建与刷新、展开折叠、悬停高亮、右键菜单
（新建笔记/新建文件夹/重命名/删除/资源管理器打开/外部编辑器），
以及笔记的打开入口。
"""

import ctypes
import os
import shutil
import subprocess
import tempfile
import time
import tkinter as tk
from tkinter import ttk, messagebox

import icon_renderer
from context_menu import ContextMenu
from file_handler import (
    list_notes_tree,
    make_subdir,
    rename_note,
    rename_folder,
    delete_note,
    delete_folder,
    DATA_DIR,
    move_item,
)
from ui.common import _add_hover_bg


def _shell_exec(exe_path, filepath, workdir=None):
    """Windows：用 ShellExecute 启动程序，返回 (返回码, 是否成功)。

    与用户在资源管理器里双击等价：不创建管道、不继承本进程的句柄，
    工作目录可单独指定。Electron 类编辑器（Typora、VS Code 等）在
    CreateProcess 下偶发"进程起来了却不出窗口"，换用 ShellExecute 更稳。
    返回值 >32 表示成功（<=32 是 Windows 的错误码，如 2=找不到文件、
    5=拒绝访问）。"""
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "open", str(exe_path), f'"{filepath}"',
            str(workdir) if workdir else None, 1)
        return rc, rc > 32
    except Exception as exc:
        return 0, False


def _editor_log(msg):
    """记录外部编辑器的启动过程，供排查"点了没反应"类问题。

    写到 %TEMP%/indexar_editor.log；文件超过 64KB 时清空重来，
    避免长期使用无限增长。"""
    try:
        path = os.path.join(tempfile.gettempdir(), "indexar_editor.log")
        if os.path.exists(path) and os.path.getsize(path) > 64 * 1024:
            os.remove(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _vscode_cli(editor):
    """若 editor 是 VS Code 的 Code.exe，返回其自带的命令行包装脚本路径。

    VS Code 的 GUI 程序需要配合 resources 下的 cli.js 才能把待打开的文件
    转交给已运行的实例；在部分安装形态下（例如应用资源位于版本子目录、
    根目录只有 Code.exe 与 bin/），直接启动 Code.exe 会因找不到自身资源
    而立即退出，文件既不会打开、也不会有任何提示。bin/code.cmd 正是官方
    为此提供的入口，故优先使用它。
    返回命令行的完整路径，没有则返回 None。"""
    base = os.path.basename(editor or "").lower()
    if base not in ("code.exe", "code - insiders.exe"):
        return None
    name = ("code-insiders.cmd" if "insider" in base else "code.cmd")
    candidate = os.path.join(os.path.dirname(editor), "bin", name)
    return candidate if os.path.isfile(candidate) else None


def _process_running(exe_path):
    """判断某程序是否已在运行（按 exe 名查进程列表）。

    用于区分"冷启动"与"交给已有实例"：Typora 一类程序在已有实例
    运行时，新进程把文件交给它后立即退出，窗口是否前置由它自己决定，
    用户可能因此误以为没有反应。"""
    name = os.path.basename(exe_path or "")
    if not name:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                             capture_output=True, text=True, timeout=3).stdout
        return name.lower() in out.lower()
    except Exception:
        return False


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
                self._snapshot_files()      # 抑制轮询自触发
                self._rebuild_indexes()     # 名称映射与索引随路径变更重建

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
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        if not os.path.exists(filepath):
            self.status_left.configure(text="   找不到笔记文件")
            return
        self._open_in_editor(filepath)

    def _open_in_editor(self, filepath=None):
        """用外部编辑器打开文件"""
        if filepath is None:
            sel = self.tree.selection()
            if not sel:
                self.status_left.configure(text="   请先在文件树中选中一篇笔记")
                return
            vals = self.tree.item(sel[0], "values")
            if not vals or vals[1] == "True" or vals[1] is True:
                self.status_left.configure(text="   文件夹不能用编辑器打开")
                return  # 跳过文件夹
            iid = vals[0]
            filepath = os.path.join(DATA_DIR, f"{iid}.md")
            if not os.path.exists(filepath):
                self.status_left.configure(text="   找不到笔记文件")
                return
        # 配置里可能是正斜杠，统一成当前系统的写法
        editor = os.path.normpath(self._editor_path or "notepad.exe")
        fallback = False
        # 路径失效（软件被卸载或迁移）时回退系统记事本
        if not (os.path.isfile(editor) or shutil.which(editor)):
            editor, fallback = "notepad.exe", True
        reused = (not fallback) and _process_running(editor)
        workdir = os.path.dirname(editor) if os.path.isfile(editor) else None
        _editor_log("open: editor=%r exists=%s which=%s reused=%s file=%r"
                    % (editor, os.path.isfile(editor),
                       shutil.which(editor), reused, filepath))

        # VS Code 优先走自带 CLI：其 GUI 程序在部分安装形态下无法自行
        # 把文件交接给已运行的实例，且 ShellExecute 的返回码不能反映结果
        cli = None if fallback else _vscode_cli(editor)
        if cli:
            self._open_with_cli(cli, filepath)
            return

        # ① 首选 ShellExecute：与双击等价，不继承本进程的句柄
        # ② 失败再用 Popen（shell=True 不能用：路径含空格会被二次解析）
        # ③ 仍失败才回退记事本
        rc, ok = _shell_exec(editor, filepath, workdir)
        _editor_log("  ShellExecute rc=%s ok=%s" % (rc, ok))
        if not ok:
            try:
                subprocess.Popen(
                    [editor, filepath], cwd=workdir,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                _editor_log("  Popen 已发起")
            except Exception as exc:
                _editor_log("  Popen 异常: %r" % (exc,))
                try:
                    subprocess.Popen(["notepad.exe", filepath],
                                     stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    fallback = True
                    _editor_log("  已回退记事本")
                except Exception as exc2:
                    _editor_log("  记事本也失败: %r" % (exc2,))
                    self.status_left.configure(
                        text=f"   无法启动外部编辑器：{editor}")
                    return

        # 启动结果一律反馈到状态栏：成功时不提示，用户无从判断
        # 程序到底执行了没有（还是根本没触发）
        app_name = os.path.splitext(os.path.basename(editor))[0]
        if fallback:
            self.status_left.configure(
                text=f"   编辑器不可用，已改用记事本打开：{editor}")
        else:
            self.status_left.configure(
                text=f"   正在用 {app_name} 打开：{os.path.basename(filepath)}")
        # 稍后回查进程是否真的起来了，把"完成/失败"落定到状态栏
        self.root.after(
            1500, lambda e=editor, f=filepath, r=reused:
            self._report_editor_result(e, f, r, 0))

    def _open_with_cli(self, cli, filepath):
        """用编辑器自带的命令行包装脚本打开笔记。

        命令行脚本会等待并把文件交给已运行的实例，返回码即真实结果，
        因此不必再用"进程中是否存在该程序"来推测是否打开成功。脚本在
        后台执行，界面按固定间隔回查它的返回码。"""
        try:
            proc = subprocess.Popen(
                [os.environ.get("COMSPEC", "cmd.exe"), "/c", cli,
                 "--reuse-window", filepath],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as exc:
            _editor_log("  CLI 启动异常: %r" % (exc,))
            self.status_left.configure(
                text="   无法启动 VS Code，请确认安装是否完整")
            return
        _editor_log("  CLI 已发起: %r file=%r" % (cli, filepath))
        self.status_left.configure(
            text=f"   正在用 VS Code 打开：{os.path.basename(filepath)}")
        self.root.after(
            900, lambda: self._poll_cli_result(proc, filepath, 0))

    def _poll_cli_result(self, proc, filepath, attempt):
        """回查命令行脚本的返回码：0 表示文件已交给编辑器"""
        note = os.path.basename(filepath)
        rc = proc.poll()
        if rc is None:
            if attempt < 16:                # 最多等待约 15 秒
                self.root.after(900, lambda: self._poll_cli_result(
                    proc, filepath, attempt + 1))
                return
            self.status_left.configure(
                text=f"   已请求 VS Code 打开：{note}（等待较久，请查看编辑器）")
            return
        _editor_log("  CLI rc=%s" % rc)
        if rc == 0:
            self.status_left.configure(text=f"   已在 VS Code 中打开：{note}")
        else:
            self.status_left.configure(
                text=f"   VS Code 未能打开该笔记（返回码 {rc}）")

    def _report_editor_result(self, editor, filepath, reused, attempt=0):
        """回查进程是否真的起来了。

        Electron 类编辑器（Typora 等）冷启动要数秒，单次查询容易在
        进程尚未建立时就判定失败，故分几次轮询，任一次命中即算成功。"""
        name = os.path.splitext(os.path.basename(editor))[0]
        note = os.path.basename(filepath)
        running = _process_running(editor)
        _editor_log("  check#%d running=%s" % (attempt, running))
        if running:
            if reused:
                # 进程本就存在，只能说明"请求已发出"，不能据此断言已打开
                self.status_left.configure(
                    text=f"   已请求在 {name} 中打开：{note}"
                         f"（窗口未出现请查看托盘）")
            else:
                self.status_left.configure(text=f"   已用 {name} 打开：{note}")
            return
        if attempt < 4:                     # 最多再查 4 次，共约 6 秒
            self.root.after(
                1200, lambda: self._report_editor_result(
                    editor, filepath, reused, attempt + 1))
            return
        self.status_left.configure(
            text=f"   {name} 未能启动（已等待约 6 秒），"
                 f"请确认它单独打开是否正常")


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
        # 已在浏览同一篇时不再重复加载：搜索/标签/历史跳转等会同步树选中，
        # 若不拦截会多渲染一遍，还会把滚动位置归零
        if iid == getattr(self, "_current_note_path", None):
            return
        if is_dir == "True" or is_dir is True:
            if self.tree.item(selected[0], "open"):
                self.tree.item(selected[0], open=False)
            else:
                self.tree.item(selected[0], open=True)
            return
        self._display_note(iid)
