"""
IndeXar 对话框与模态面板

对话框基础设施（无边框窗口 + 标题栏 + 主题适配）与具体面板：
输入框、目录选择、新建笔记/文件夹、字号设置、集成设置面板、帮助面板。
"""

import ctypes
import os
import tkinter as tk
from tkinter import ttk, messagebox

import icon_renderer
from editor_detect import detect_editors
from file_handler import create_note, make_subdir, list_notes_tree
from theme_manager import VSCodeTheme
from ui.common import _add_hover_bg, enable_window_resize


class DialogsMixin:
    """各类对话框与模态面板"""

    def _ask_single_line(self, title, prompt, initial=""):
        """简易单行输入对话框（跟随主题），返回输入字符串或 None"""
        result = [None]
        dialog = self._make_dialog(self.root, title, 380, 150)
        self._theme_dialog_body(dialog)
        c = self.colors
        body = tk.Frame(dialog, bg=c["sidebar_bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        tk.Label(body, text=prompt, bg=c["sidebar_bg"],
                 fg=c["sidebar_fg"], font=("Microsoft YaHei", 10),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 8))
        var = tk.StringVar(value=initial)
        entry = tk.Entry(body, textvariable=var,
                         font=("Microsoft YaHei", 10),
                         relief=tk.SUNKEN,
                         bg=c["search_bg"], fg=c["search_fg"],
                         insertbackground=c["search_fg"])
        entry.pack(fill=tk.X, pady=(0, 14))
        entry.focus_set()
        entry.select_range(0, tk.END)
        btns = tk.Frame(body, bg=c["sidebar_bg"])
        btns.pack(fill=tk.X)

        def ok():
            result[0] = var.get().strip()
            dialog.destroy()

        tk.Button(btns, text="确定", font=("Microsoft YaHei", 9),
                  bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                  command=ok).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btns, text="取消", font=("Microsoft YaHei", 9),
                  bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                  command=dialog.destroy).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: ok())
        entry.bind("<Escape>", lambda e: dialog.destroy())
        dialog.wait_window()
        return result[0]


    def _create_note(self, default_dir=""):
        """弹出新建笔记对话框"""
        from file_handler import get_all_subdirs, create_note

        dialog = self._make_dialog(self.root, "新建笔记", 400, 240)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        # 笔记标题
        tk.Label(frame, text="笔记标题：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        title_var = tk.StringVar()
        title_entry = tk.Entry(frame, textvariable=title_var,
                                font=("Microsoft YaHei", 10), relief=tk.SUNKEN)
        title_entry.pack(fill=tk.X, pady=(0, 12))
        title_entry.focus_set()

        # 存放目录
        tk.Label(frame, text="存放目录：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        dir_frame = tk.Frame(frame)
        dir_frame.pack(fill=tk.X, pady=(0, 16))
        dir_var = tk.StringVar(value=default_dir if default_dir else "(根目录)")
        dir_label = tk.Label(dir_frame, textvariable=dir_var,
                             font=("Microsoft YaHei", 9),
                             bg="#fff", fg="#333",
                             anchor=tk.W, padx=8, pady=3,
                             relief=tk.SUNKEN)
        dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        browse_btn = tk.Button(dir_frame, text="浏览…",
                               font=("Microsoft YaHei", 9),
                               command=lambda: self._select_dir_dialog(
                                   dialog, dir_var, default_dir))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # 按钮行
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def do_create():
            title = title_var.get().strip()
            if not title:
                return
            subdir_raw = dir_var.get()
            subdir = "" if subdir_raw == "(根目录)" else subdir_raw
            rel_path = create_note(title, subdir)
            if rel_path:
                dialog.destroy()
                self._refresh_file_tree()
                self._snapshot_files()  # 抑制轮询自触发
                self._display_note(rel_path)

        tk.Button(btn_frame, text="取消",
                  font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="创建",
                  font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)

        title_entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)

    def _make_dialog(self, parent, title, width, height):
        """创建无边框对话框，带自定义标题栏"""
        win = tk.Toplevel(parent)
        win.overrideredirect(True)
        # 不在创建时 grab — 此时窗口在 (0,0) 默认位置，
        # grab 会锁死位置，后续 MoveWindow/geometry 全部无效
        win.configure(bg=self.colors["sidebar_bg"])
        win.resizable(False, False)

        # ── 自定义标题栏 ──
        bar = tk.Frame(win, height=28)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        lbl = tk.Label(bar, text=f"  {title}", font=("Microsoft YaHei", 10),
                       anchor=tk.W)
        lbl.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cls = tk.Button(bar, text="✕", font=("Segoe UI", 9),
                       relief=tk.FLAT, bd=0, padx=8,
                       command=win.destroy)
        cls.pack(side=tk.RIGHT, fill=tk.Y)

        # 拖拽
        def _start(e):
            win._dx = e.x_root
            win._dy = e.y_root
        def _drag(e):
            x = win.winfo_x() + e.x_root - win._dx
            y = win.winfo_y() + e.y_root - win._dy
            win.geometry(f"+{x}+{y}")
            win._dx = e.x_root
            win._dy = e.y_root
        for w in (bar, lbl):
            w.bind("<Button-1>", _start)
            w.bind("<B1-Motion>", _drag)

        # ── 主题着色（仅标题栏）──
        c = self.colors
        bar.configure(bg=c["toolbar_bg"])
        lbl.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"])
        cls.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                      activebackground="#e81123" if self.theme_mode == "light" else "#c03333")
        win._titlebar = bar
        win._dialog_width = width
        win._dialog_height = height

        return win

    def _theme_dialog_body(self, win):
        """对对话框内部所有控件应用主题色 + 定位（在所有控件添加完成后调用）"""
        c = self.colors

        def _recurse(widget):
            if widget is getattr(win, '_titlebar', None):
                return
            if isinstance(widget, tk.Frame):
                widget.configure(bg=c["sidebar_bg"], bd=0, highlightthickness=0,
                                 highlightbackground=c["sidebar_bg"])
            elif isinstance(widget, tk.Label):
                widget.configure(bg=c["sidebar_bg"], fg=c["sidebar_fg"])
            elif isinstance(widget, tk.Entry):
                widget.configure(
                    bg=c["content_bg"], fg=c["content_fg"],
                    insertbackground=c["content_fg"],
                    relief=tk.SUNKEN,
                )
            elif isinstance(widget, tk.Button):
                widget.configure(
                    bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                    activebackground=c["toolbar_btn_hover"],
                    activeforeground=c["toolbar_btn_fg"],
                    relief=tk.RIDGE, bd=1,
                    highlightthickness=0,
                    padx=12,
                )
            elif isinstance(widget, ttk.Treeview):
                # 对话框内 Treeview（目录选择器）需要可见细边框
                _style_key = f"dialog_treeview_{id(widget)}"
                s = ttk.Style()
                s.configure(_style_key,
                    background=c["sidebar_bg"], foreground=c["sidebar_fg"],
                    fieldbackground=c["sidebar_bg"],
                    borderwidth=1, lightcolor=c["separator"],
                    darkcolor=c["separator"], bordercolor=c["separator"],
                    font=("Microsoft YaHei", 10), rowheight=26, indent=14,
                )
                s.map(_style_key,
                    background=[("selected", c["sidebar_item_selected"])],
                    foreground=[("selected", c["sidebar_fg"])])
                widget.configure(style=_style_key)
            for child in widget.winfo_children():
                _recurse(child)

        for child in win.winfo_children():
            _recurse(child)

        # ── 窗口外边框 ──
        border_c = "#555555" if self.theme_mode == "dark" else "#777777"
        win.configure(highlightthickness=1, highlightbackground=border_c,
                      highlightcolor=border_c)

        # ── 屏幕居中：grab 后 geometry + MoveWindow 覆盖 ──
        w = getattr(win, '_dialog_width', 400)
        h = getattr(win, '_dialog_height', 300)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        win.attributes('-topmost', True)
        win.grab_set()
        win.update_idletasks()
        win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        try:
            hwnd = win.winfo_id()
            ctypes.windll.user32.MoveWindow(hwnd, x, y, w, h, True)
        except Exception:
            pass
        win.lift()
        win.focus_force()

        # ── Escape 关闭 ──
        win.bind("<Escape>", lambda e: win.destroy())

        # ── 点击外部关闭 ──
        _closed = []
        def _on_outside(event):
            if _closed or not win.winfo_exists():
                return
            try:
                wx = win.winfo_rootx()
                wy = win.winfo_rooty()
                ww = win.winfo_width()
                wh = win.winfo_height()
                if not (wx <= event.x_root <= wx + ww and
                        wy <= event.y_root <= wy + wh):
                    _closed.append(True)
                    win.destroy()
            except tk.TclError:
                pass

        _outside_id = self.root.bind("<Button-1>", _on_outside, add="+")
        def _cleanup():
            try:
                self.root.unbind("<Button-1>", _outside_id)
            except tk.TclError:
                pass
        win.bind("<Destroy>", lambda e: _cleanup(), add="+")

    def _offset_from_parent(self, win, parent, w, h):
        """将窗口放在父窗口右下方偏移位置"""
        self.root.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - w) // 2 + 40
        y = py + (ph - h) // 2 + 20
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _select_dir_dialog(self, parent_win, result_var, current_dir=""):
        """弹出树状目录选择对话框，完全手动构建避免 grab/position 冲突"""
        from file_handler import list_notes_tree

        c = self.colors
        W, H = 380, 450

        # 释放父对话框 grab + 关闭 topmost
        try:
            parent_win.grab_release()
            parent_win.attributes('-topmost', False)
        except tk.TclError:
            pass

        # ── 完全手动创建窗口（不用 _make_dialog，避免 grab 锁位置）──
        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        border_c = "#555555" if self.theme_mode == "dark" else "#777777"
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=border_c,
                         highlightcolor=border_c)
        dialog.resizable(False, False)

        # 标题栏
        bar = tk.Frame(dialog, height=28, bg=c["toolbar_bg"])
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  选择目录", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=c["toolbar_bg"], fg=c["toolbar_fg"]
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=dialog.destroy,
                  bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                  activebackground=("#e81123" if self.theme_mode == "light" else "#c03333")
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        # 拖拽
        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root
        def _drag_move(e):
            dialog.geometry(f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                            f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root
        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # 关闭恢复
        def _restore_parent():
            try:
                parent_win.attributes('-topmost', True)
                parent_win.grab_set()
            except tk.TclError:
                pass
        dialog.bind("<Destroy>", lambda e: _restore_parent(), add="+")

        # Treeview
        tree = ttk.Treeview(dialog, show="tree", selectmode="browse")
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(14, 0))
        tree.bind("<<TreeviewSelect>>", lambda e: _auto_open())
        def _auto_open():
            sel = tree.selection()
            if sel:
                tree.item(sel[0], open=not tree.item(sel[0], "open"))

        root_iid = tree.insert("", "end", text="(根目录)", open=True)
        def _populate(parent_iid, items):
            for item in items:
                if not item["is_dir"]:
                    continue
                node = tree.insert(parent_iid, "end",
                                   text=item["name"], values=(item["path"],))
                if item["children"]:
                    _populate(node, item["children"])

        tree_data = list_notes_tree()
        if tree_data:
            _populate(root_iid, tree_data)
        if current_dir:
            for item in tree.get_children(root_iid):
                vals = tree.item(item, "values")
                if vals and vals[0] == current_dir:
                    tree.selection_set(item)
                    tree.see(item)
                    break

        # 按钮
        btn_frame = tk.Frame(dialog, bg=c["sidebar_bg"], bd=0, highlightthickness=0)
        btn_frame.pack(fill=tk.X, padx=14, pady=14)
        def confirm():
            sel = tree.selection()
            if sel:
                vals = tree.item(sel[0], "values")
                result_var.set(vals[0] if vals else "(根目录)")
            else:
                result_var.set("(根目录)")
            dialog.destroy()
        tree.bind("<Double-Button-1>", lambda e: confirm())
        for text, cmd in [("确定", confirm), ("取消", dialog.destroy)]:
            btn = tk.Button(btn_frame, text=text, command=cmd,
                            font=("Microsoft YaHei", 9),
                            bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                            activebackground=c["toolbar_btn_hover"],
                            activeforeground=c["toolbar_btn_fg"],
                            relief=tk.RIDGE, bd=1, highlightthickness=0,
                            highlightbackground=c["toolbar_btn_bg"], padx=12)
            btn.pack(side=tk.RIGHT, padx=(10, 0) if text == "确定" else 0)

        # Treeview 样式（必须以 .Treeview 结尾）
        _sk = f"dir_{id(tree)}.Treeview"
        s = ttk.Style()
        s.configure(_sk, background=c["sidebar_bg"], foreground=c["sidebar_fg"],
                    fieldbackground=c["sidebar_bg"],
                    borderwidth=1, lightcolor="#555555" if self.theme_mode == "dark" else "#999999",
                    darkcolor="#555555" if self.theme_mode == "dark" else "#999999",
                    bordercolor="#555555" if self.theme_mode == "dark" else "#999999",
                    font=("Microsoft YaHei", 10), rowheight=26, indent=14)
        s.map(_sk, background=[("selected", c["sidebar_item_selected"])],
              foreground=[("selected", c["sidebar_fg"])])
        tree.configure(style=_sk)

        # ── 居中定位：geometry + MoveWindow 缺一不可 ──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{x}+{y}")
        hwnd = dialog.winfo_id()
        ctypes.windll.user32.MoveWindow(hwnd, x, y, W, H, True)
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _create_folder(self, default_dir=""):
        """弹出新建文件夹对话框（含目录选择）"""
        from file_handler import make_subdir, get_all_subdirs

        dialog = self._make_dialog(self.root, "新建文件夹", 400, 250)

        frame = tk.Frame(dialog, padx=20, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        # 父目录选择
        tk.Label(frame, text="所在目录：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        dir_frame = tk.Frame(frame)
        dir_frame.pack(fill=tk.X, pady=(0, 12))
        parent_var = tk.StringVar(value=default_dir if default_dir else "(根目录)")
        dir_label = tk.Label(dir_frame, textvariable=parent_var,
                             font=("Microsoft YaHei", 9),
                             bg="#fff", fg="#333",
                             anchor=tk.W, padx=8, pady=3,
                             relief=tk.SUNKEN)
        dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        browse_btn = tk.Button(dir_frame, text="浏览…",
                               font=("Microsoft YaHei", 9),
                               command=lambda: self._select_dir_dialog(
                                   dialog, parent_var, default_dir))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # 文件夹名称
        tk.Label(frame, text="文件夹名称：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        name_var = tk.StringVar(value="new_folder")
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10), relief=tk.SUNKEN)
        entry.pack(fill=tk.X, pady=(0, 14))
        entry.select_range(0, tk.END)
        entry.focus_set()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def do_create():
            name = name_var.get().strip()
            if name:
                raw = parent_var.get()
                parent = "" if raw == "(根目录)" else raw
                make_subdir(parent, name)
                dialog.destroy()
                self._refresh_file_tree()

        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="创建", font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)


    def _open_help(self, category=None):
        """打开帮助面板（左分类 + 右内容，可拖动分隔）"""
        # 两级结构：{分类: [(小节标题, [(类型, 文本), ...]), ...]}
        sections = {
            "操作指南": [
                ("界面与打开", [
                    ("p", "· 最左侧竖条是活动栏：文件 / 标签 / 搜索 / 回收站，点击切换侧栏；"),
                    ("p", "  再点当前图标可收起侧栏。侧栏与正文间的分隔条可拖拽调宽。"),
                    ("p", "· 顶部菜单依次为：文件 / 编辑 / 视图 / 帮助；"),
                    ("p", "  拖动标题栏空白处可移动窗口（无边框窗口）。"),
                    ("p", "· 底部状态栏左侧显示操作提示，右侧显示当前字号。"),
                    ("p", "· 打开笔记：文件树中单击文件名、标签面板中双击笔记名、"),
                    ("p", "  搜索结果中单击结果项、正文中单击内部链接。"),
                    ("p", "· 文件树中单击文件夹可展开 / 折叠。"),
                    ("p", "· 底部「被以下笔记引用」中的条目也可单击跳转；"),
                    ("p", "  打开后文件树会自动选中对应条目。"),
                    ("p", "· 本帮助面板：左栏点分类名折叠 / 展开，点小节名切换内容。"),
                ]),
                ("前进与后退", [
                    ("p", "· Alt + ← 返回上一篇，Alt + → 再前进一篇；"),
                    ("p", "  也可点击内容区左上角的 ← / → 箭头。"),
                    ("p", "· 适用于内部链接、反向链接、搜索结果等各类跳转，"),
                    ("p", "  误触跳转时可以快速回到原来的位置。"),
                    ("p", "· 箭头变灰表示该方向已没有可跳转的笔记。"),
                    ("p", "· 只有切换到不同笔记才计入历史，切主题、改字号等"),
                    ("p", "  刷新操作不会打乱历史。"),
                ]),
                ("搜索", [
                    ("p", "· 入口：活动栏第三个图标（放大镜）进入搜索面板；"),
                    ("p", "  或在内容区头部快捷搜索框输入后回车（自动切到面板）。"),
                    ("p", "· 面板顶部为输入框 + 清空，下方是结果列表，"),
                    ("p", "  底部为未来的高级搜索预留扩展区。"),
                    ("p", "· 大小写不敏感的子串匹配，只搜正文，不搜 YAML 元数据。"),
                    ("p", "· 结果分三组：当前文件 → 文件名匹配 → 内容匹配。"),
                    ("p", "· 「当前文件」逐条列出每处匹配的上下文片段，点击片段"),
                    ("p", "  滚动到对应位置；正文中的命中会高亮该关键词。"),
                    ("p", "· 代码块与表格的内容同样参与搜索，其片段前标有"),
                    ("p", "  [代码] / [表格]。这两处无法像正文那样高亮：代码块"),
                    ("p", "  按行定位，表格选中命中行，并在状态栏给出行列号。"),
                    ("p", "· 清空输入框即清空结果；切回文件 / 标签面板点活动栏图标。"),
                    ("p", "· 不支持模糊匹配、布尔查询与正则表达式。"),
                ]),
                ("标签与交集", [
                    ("p", "· 顶部搜索框可按名称过滤标签。"),
                    ("p", "· 单击标签展开其下的笔记列表，双击笔记名打开。"),
                    ("p", "· 选中多个标签即可求交集（同时含这些标签的笔记）："),
                    ("p", "    Ctrl  + 点击  →  逐个加选或取消，适合不相邻的标签"),
                    ("p", "    Shift + 点击  →  选中两次点击之间的连续范围"),
                    ("p", "· 顶部显示「标签A ∩ 标签B → N 个文件」，双击列表项打开。"),
                ]),
                ("当前文件标签", [
                    ("p", "· 面板底部区块列出当前笔记的标签（来自 YAML 的 tags）。"),
                    ("p", "· 「＋ 添加标签」弹窗输入，「－ 删除所选」删除选中项。"),
                    ("p", "· 双击列表中的标签 → 跳到「标签」面板并定位该标签。"),
                    ("p", "· 点区块标题可折叠 / 展开，上方分隔条可拖动调高度。"),
                    ("p", "· 写回时只改 tags 字段，不重排 front matter 的其它内容。"),
                ]),
                ("链接与图片", [
                    ("p", "· 站内链接单击即跳转，三种写法等价："),
                    ("code", "[[笔记名]]\n[[笔记名|显示的文字]]\n[显示的文字](笔记名)"),
                    ("p", "· 站外链接需 Ctrl + 单击，用默认浏览器打开。"),
                    ("p", "· 图片默认按「适应宽度」显示，视图菜单可切「原始尺寸」。"),
                    ("p", "· 鼠标移到图片上，状态栏会显示它的说明文字。"),
                    ("p", "· 图片也可以做成链接，从而支持点击跳转，"),
                    ("p", "  写法见「笔记格式 → 图片」。"),
                ]),
                ("代码块", [
                    ("p", "· 代码块以独立区域呈现，顶部左侧显示语言标签，"),
                    ("p", "  右上角为「复制」按钮，点击复制整块代码。"),
                    ("p", "· 需要复制其中一段时：用鼠标选中后按 Ctrl + C，"),
                    ("p", "  或右键 → 复制选中 / 复制全部。"),
                    ("p", "· 标注了语言的块按语法着色，亮 / 暗主题各用一套配色；"),
                    ("p", "  未标注语言时显示「纯文本」，不做着色。"),
                    ("p", "· 代码不自动折行：超长的行用块下方的水平滚动条查看，"),
                    ("p", "  也可按住 Shift 滚动滚轮横向移动。"),
                    ("p", "· 宽度随内容区变化，切换主题时按新配色重新渲染。"),
                ]),
                ("表格", [
                    ("p", "· 表格渲染为原生表格控件，列宽可拖拽调整。"),
                    ("p", "· Ctrl + C：有选中行时复制当前单元格，否则复制整行。"),
                    ("p", "· 右键表格 → 复制该单元格内容。"),
                    ("p", "· 单元格内不支持换行，也不能像文本那样拖选。"),
                    ("p", "· 表格内容可被搜索：跳转时选中命中的那一行，"),
                    ("p", "  状态栏给出「第几行第几列」。"),
                ]),
                ("回收站", [
                    ("p", "· 删除的笔记移入 data/.trash/，由活动栏第四个图标进入。"),
                    ("p", "· 双击条目或按 Enter 恢复；按 Del 彻底删除（不可恢复）。"),
                    ("p", "· 支持多选批量处理，右键菜单同样提供恢复与删除。"),
                    ("p", "· 「时间 ↑ / ↓」切换排序方向，「清空」清空回收站。"),
                ]),
                ("快捷键与设置", [
                    ("code", "Alt + ← / →   后退 / 前进（全局）\n"
                             "Del           删除选中项（文件树）\n"
                             "F2            重命名选中项（文件树）\n"
                             "Enter         恢复条目（回收站）\n"
                             "Del           彻底删除（回收站）\n"
                             "Ctrl + C      复制单元格 / 整行（表格）\n"
                             "Ctrl + C      复制选中的代码（代码块内）\n"
                             "Shift + 滚轮  横向滚动（代码块内）\n"
                             "Esc           关闭当前对话框"),
                    ("p", "· 「文件 → 设置…」：通用（字号 8~24）、外观（主题）、"),
                    ("p", "  编辑器（自动检测或手动指定 exe）。"),
                    ("p", "· 「视图」菜单：字号…、切换主题、图片适应宽度 / 原始尺寸、"),
                    ("p", "  隐藏或显示侧栏、跟随系统主题。"),
                    ("p", "· 设置保存在程序目录的 settings.json 中。"),
                ]),
                ("右键菜单", [
                    ("p", "· 文件树空白处：新建笔记、新建文件夹。"),
                    ("p", "· 文件夹：新建笔记 / 新建文件夹 / 重命名文件夹 / 移动到… /"),
                    ("p", "  删除文件夹 / 在资源管理器中打开。"),
                    ("p", "· 文件：新建笔记 / 新建文件夹 / 外部编辑器打开 / 移动到… /"),
                    ("p", "  重命名 / 删除 / 在资源管理器中打开。"),
                    ("p", "· 多选（Ctrl 点选 / Shift 范围选）时：删除这 N 个项目、"),
                    ("p", "  移动这 N 个项目到…。"),
                    ("p", "· 内容区右键：复制、全选；表格右键：复制单元格。"),
                ]),
            ],
            "笔记格式": [
                ("YAML 元数据", [
                    ("p", "写在 .md 文件开头，用 --- 包裹："),
                    ("code", "---\ntitle: 笔记标题\n"
                             "date: 2026-09-10\n"
                             "tags: [标签1, 标签2]\n---"),
                    ("p", "· tags 会被收集到左侧标签面板，用于聚合与交集筛选。"),
                    ("p", "· title 与 date 会被解析，但目前不参与界面展示。"),
                ]),
                ("内部链接", [
                    ("code", "[[笔记名]]\n[[笔记名|显示的文字]]\n[显示的文字](笔记名)"),
                    ("p", "· 三种写法都指向站内笔记，单击即可跳转。"),
                    ("p", "· 也可写相对路径，如 [文字](./目录/笔记.md)。"),
                    ("p", "· 被引用的笔记底部会自动显示「被以下笔记引用」列表。"),
                ]),
                ("外部链接", [
                    ("code", "[显示文字](https://example.com)\n"
                             "<https://example.com>"),
                    ("p", "· 两种写法都会被识别，Ctrl + 单击用浏览器打开。"),
                    ("p", "· 直接书写的裸网址不会被识别为链接。"),
                ]),
                ("图片", [
                    ("code", "![备用文字](图片文件名.png \"悬浮时显示的文字\")"),
                    ("p", "· 图片放在笔记所在目录即可直接写文件名；也支持 data/ 内"),
                    ("p", "  的相对路径（如 images/a.png）。"),
                    ("p", "· 默认「适应宽度」：比正文宽时等比缩小，比正文窄时保持"),
                    ("p", "  原样（不放大、不拉伸）。"),
                    ("p", "· 视图菜单可切到「原始尺寸」：按图片本身像素显示，超宽时"),
                    ("p", "  用内容区下方的水平滚动条查看。"),
                    ("p", "· 鼠标移到图片上，状态栏会显示 title；没有 title 时显示"),
                    ("p", "  方括号里的备用文字。"),
                    ("p", "· 用链接包住图片即可点击，状态栏会提示跳转目标："),
                    ("code", "[![图](a.png)](笔记名)\n"
                             "[![图](a.png)](https://example.com)"),
                    ("p", "· 站内链接单击跳转，站外链接 Ctrl + 单击用浏览器打开。"),
                    ("p", "· 图片缺失或写成网络地址时显示灰色占位文字，"),
                    ("p", "  网络图片不会被下载。"),
                ]),
                ("表格", [
                    ("code", "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |"),
                    ("p", "· 渲染为原生表格控件，列宽可拖拽调整。"),
                    ("p", "· Ctrl + C 复制单元格或整行，右键可复制单元格。"),
                    ("p", "· 单元格内不支持换行，也不能拖选。"),
                ]),
                ("代码块", [
                    ("code", "```python\nprint(\"标注语言后可语法着色\")\n```\n\n"
                             "~~~\n外层用 ~~~，块内就能写 ```\n~~~\n\n"
                             "    缩进 4 空格也是代码块（无着色）\n"),
                    ("p", "· 语言可写 python、javascript、json、sql、bash、html、"),
                    ("p", "  yaml、cpp、java、css、markdown 等，标签显示其名称；"),
                    ("p", "  未标注或无法识别时显示「纯文本」，不着色。"),
                    ("p", "· 代码中的 Markdown 符号（**粗体**、# 标题等）保持原样，"),
                    ("p", "  不会被当作格式解析。"),
                ]),
                ("支持的语法", [
                    ("p", "· 标题 # ~ ######（六级样式递进）"),
                    ("p", "· 粗体 **文字**、斜体 *文字*、粗斜体 ***文字***"),
                    ("p", "· 删除线 ~~文字~~（也支持 <del> 标签）"),
                    ("p", "· 行内代码 `code` 与围栏代码块 ```（可标注语言）"),
                    ("p", "· 任务列表 - [ ] / - [x]（显示为 ☐ / ☑）"),
                    ("p", "· 引用 >（连续多行合并为一个引用块）、分隔线 ---"),
                    ("p", "· 无序列表 -、有序列表 1.（嵌套需缩进 4 空格）"),
                    ("p", "· 表格、图片、链接、YAML 元数据"),
                    ("p", "· 段落内的单行换行会保留（便于逐行阅读）"),
                ]),
                ("不支持的写法", [
                    ("p", "· 脚注 [^1]：脚注正文会列出，但上标与回跳链接不渲染"),
                    ("p", "· 高亮 ==文字==：原样显示，不会变色"),
                    ("p", "· 其它 HTML 标签（如 <u>）：标签被忽略，只保留文字"),
                    ("p", "· 裸网址：必须写成链接语法才会被识别"),
                ]),
            ],
        }

        c = self.colors
        # 初始尺寸（窗口可拖拽调整，左栏内容溢出时可滚动）
        W, H = 660, 600
        is_dark = self.theme_mode == "dark"
        win_border = "#555555" if is_dark else "#777777"
        bar_bg, bar_fg = c["nav_bg"], c["nav_fg"]
        bar_btn_hover = "#e81123" if not is_dark else "#c03333"

        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)
        dialog.minsize(420, 300)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=bar_bg)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  帮助", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=bar_bg, fg=bar_fg
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=dialog.destroy,
                  bg=bar_bg, fg=bar_fg,
                  activebackground=bar_btn_hover, activeforeground="#ffffff"
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root

        def _drag_move(e):
            dialog.geometry(
                f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root

        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # ── 主体：PanedWindow 可分栏 ──
        pane = ttk.PanedWindow(dialog, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)
        st = ttk.Style()
        st.configure("TPanedwindow", background=c["sidebar_bg"])
        st.configure("sash.TPanedwindow", sashthickness=4,
                     sashrelief=tk.FLAT,
                     background="#999" if not is_dark else "#666")

        left_bg = "#dddddd" if not is_dark else "#1e1e1e"
        left = tk.Frame(pane, bg=left_bg, width=150)
        right = tk.Frame(pane, bg=c["sidebar_bg"], padx=6, pady=10)
        pane.add(left, weight=0)
        pane.add(right, weight=1)

        # ── 左栏：Canvas + 滚动条，内容超出高度时可滚动 ──
        nav_canvas = tk.Canvas(left, bg=left_bg, highlightthickness=0)
        nav_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL,
                                   command=nav_canvas.yview)
        nav_inner = tk.Frame(nav_canvas, bg=left_bg)
        _nav_win = nav_canvas.create_window((0, 0), window=nav_inner,
                                            anchor="nw")
        nav_canvas.configure(yscrollcommand=nav_scroll.set)
        # 左侧留 8px：既不压住窗口边缘（留给拖拽缩放），也不显得贴边
        nav_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                        padx=(8, 0))

        def _sync_nav_scroll(_event=None):
            nav_canvas.configure(scrollregion=nav_canvas.bbox("all"))
            need = nav_inner.winfo_reqheight() > nav_canvas.winfo_height() + 1
            if need and not nav_scroll.winfo_ismapped():
                nav_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            elif not need and nav_scroll.winfo_ismapped():
                nav_scroll.pack_forget()

        # 内容高度与可视高度任一方变化都要重算滚动区
        nav_inner.bind("<Configure>", _sync_nav_scroll)
        nav_canvas.bind("<Configure>", lambda e: (
            nav_canvas.itemconfigure(_nav_win, width=e.width),
            _sync_nav_scroll()))

        # 折叠分类会改变内容高度，一并刷新
        def _nav_wheel(e):
            nav_canvas.yview_scroll(-int(e.delta / 120) or -1, "units")
            return "break"

        for _w in (nav_canvas, nav_inner):
            _w.bind("<MouseWheel>", _nav_wheel)

        # ── 右侧只读文本区 ──
        text = tk.Text(right, wrap=tk.WORD, bd=0, highlightthickness=0,
                       bg=c["content_bg"], fg=c["content_fg"],
                       font=("Microsoft YaHei", 10),
                       spacing1=2, spacing3=4, padx=6, pady=8)
        scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        code_bg = "#1e1e1e" if is_dark else "#f0f0f0"
        code_fg = "#d4d4d4" if is_dark else "#333333"
        text.tag_configure("h", font=("Microsoft YaHei", 11, "bold"),
                           spacing1=12, foreground=c["content_fg"])
        text.tag_configure("p", spacing1=2)
        text.tag_configure("code", font=("Consolas", 9),
                           background=code_bg, foreground=code_fg,
                           spacing1=6, spacing3=6,
                           lmargin1=10, lmargin2=10)

        def _render(title, items):
            text.configure(state=tk.NORMAL)
            text.delete("1.0", "end")
            text.insert("end", title + "\n", "h")
            for kind, line in items:
                text.insert("end", line + "\n", kind)
            text.configure(state=tk.DISABLED)
            text.yview_moveto(0)

        # ── 左侧层级：分类（可折叠） → 小节 ──
        sub_labels = []    # [(小节标题, 内容, Label)]
        cat_rows = []      # [(分类名, 表头 Label, 小节容器 Frame)]
        folded = set()     # 已折叠的分类

        def _refresh_fold():
            for cat, head, sub in cat_rows:
                head.configure(
                    text="  " + ("▸ " if cat in folded else "▾ ") + cat)
                if cat in folded:
                    sub.pack_forget()
                else:
                    sub.pack(fill=tk.X)
            _sync_nav_scroll()      # 折叠会改变内容高度

        def _toggle(cat):
            if cat in folded:
                folded.discard(cat)
            else:
                folded.add(cat)
            _refresh_fold()

        def _select(title, items):
            for t, _i, lbl in sub_labels:
                lbl.configure(bg=c["toolbar_btn_hover"] if t == title
                              else left_bg)
            _render(title, items)

        for cat, subs in sections.items():
            holder = tk.Frame(nav_inner, bg=left_bg)
            holder.pack(fill=tk.X)
            head = tk.Label(holder, anchor=tk.W, cursor="hand2",
                            font=("Microsoft YaHei", 10, "bold"),
                            bg=left_bg, fg=c["sidebar_fg"], pady=6)
            head.pack(fill=tk.X)
            head.bind("<Button-1>", lambda e, cat=cat: _toggle(cat))
            sub = tk.Frame(holder, bg=left_bg)
            sub.pack(fill=tk.X)

            for title, items in subs:
                lbl = tk.Label(sub, text="      " + title, anchor=tk.W,
                               font=("Microsoft YaHei", 9),
                               bg=left_bg, fg=c["sidebar_fg"], pady=3,
                               cursor="hand2")
                lbl.pack(fill=tk.X)
                lbl.bind("<Button-1>",
                         lambda e, t=title, i=items: _select(t, i))
                sub_labels.append((title, items, lbl))

            cat_rows.append((cat, head, sub))

        _refresh_fold()

        # 初始定位：优先命中 category，否则第一个小节
        if sub_labels:
            pick = sub_labels[0]
            if category:
                for row in sub_labels:
                    if row[0] == category:
                        pick = row
                        break
            _select(pick[0], pick[1])

        # 无边框窗口需自行支持缩放：边缘与四角可拖拽
        enable_window_resize(dialog, titlebar=bar)

        # 居中于主窗口
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - W) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - H) // 2
        dialog.geometry(f"{W}x{H}+{max(x, 0)}+{max(y, 0)}")
        _sync_nav_scroll()

    def _open_settings(self):
        """打开集成设置面板（左分类 + 右内容，可拖动分隔）"""
        c = self.colors
        W, H = 600, 420
        is_dark = self.theme_mode == "dark"
        win_border = "#555555" if is_dark else "#777777"
        # 标题栏用活动栏配色
        bar_bg = c["nav_bg"]
        bar_fg = c["nav_fg"]
        bar_btn_hover = "#e81123" if not is_dark else "#c03333"

        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)
        dialog.minsize(400, 280)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=bar_bg)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  设置", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=bar_bg, fg=bar_fg
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=dialog.destroy,
                  bg=bar_bg, fg=bar_fg,
                  activebackground=bar_btn_hover, activeforeground="#ffffff"
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        # 拖拽
        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root
        def _drag_move(e):
            dialog.geometry(
                f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root
        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # ── 主体：PanedWindow 原生可分栏 ──
        pane = ttk.PanedWindow(dialog, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)
        # Sash 样式
        s = ttk.Style()
        s.configure("TPanedwindow", background=c["sidebar_bg"])
        s.configure("sash.TPanedwindow", sashthickness=4,
                    sashrelief=tk.FLAT, background="#999" if not is_dark else "#666")

        # 左侧略深，与右侧形成对比
        left_bg = "#dddddd" if not is_dark else "#1e1e1e"
        left = tk.Frame(pane, bg=left_bg, width=W // 2)
        right = tk.Frame(pane, bg=c["sidebar_bg"], padx=20, pady=12)
        pane.add(left, weight=1)
        pane.add(right, weight=3)

        # ── 右侧内容区（动态切换） ──
        self._settings_content = None
        editors = detect_editors()

        def _show_category(name):
            if self._settings_content:
                self._settings_content.destroy()
            self._settings_content = tk.Frame(right, bg=c["sidebar_bg"])
            self._settings_content.pack(fill=tk.BOTH, expand=True)
            ct = self._settings_content
            lf = ("Microsoft YaHei", 10)

            if name == "通用":
                tk.Label(ct, text="字号", anchor=tk.W, font=lf,
                         bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                         ).pack(fill=tk.X, pady=(0, 6))
                sz = tk.Frame(ct, bg=c["sidebar_bg"])
                sz.pack(fill=tk.X)
                sv = tk.StringVar(value=str(self._font_size))
                for txt, d in [("−", -1), ("+", 1)]:
                    b = tk.Button(sz, text=txt, font=("Microsoft YaHei", 9, "bold"),
                                  width=2, relief=tk.RIDGE, bd=1,
                                  command=lambda sv=sv, d=d: _delta_size(sv, d))
                    b.pack(side=tk.RIGHT, padx=(4, 0))
                    b.configure(bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                                activebackground=c["toolbar_btn_hover"])
                e = tk.Entry(sz, textvariable=sv, font=lf, width=6,
                             justify=tk.CENTER, relief=tk.FLAT, bd=0,
                             highlightthickness=1)
                e.pack(side=tk.RIGHT, padx=(0, 8))
                e.configure(bg=c["content_bg"], fg=c["content_fg"],
                            highlightbackground=c["search_border"])

            elif name == "外观":
                tk.Label(ct, text="主题模式", anchor=tk.W, font=lf,
                         bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                         ).pack(fill=tk.X, pady=(0, 8))
                themes = ["亮色", "暗色"]
                themes_map = {"亮色": "light", "暗色": "dark"}
                tv = tk.StringVar(value="亮色" if self.theme_mode == "light" else "暗色")
                cb = ttk.Combobox(ct, textvariable=tv, values=themes,
                                  state="readonly", font=lf, width=12)
                cb.pack(anchor=tk.W)
                cb.bind("<<ComboboxSelected>>", lambda e: (
                    setattr(self, 'theme_mode', themes_map[tv.get()]),
                    setattr(self, 'colors', VSCodeTheme.get(themes_map[tv.get()])),
                    self._apply_theme(),
                    self._save_settings(),
                ))

            elif name == "编辑器":
                tk.Label(ct, text="外部编辑器", anchor=tk.W, font=lf,
                         bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                         ).pack(fill=tk.X, pady=(0, 8))
                names = list(editors.keys())
                ev = tk.StringVar()

                # 裸命令名（如 notepad.exe）补全为已检测项的绝对路径
                if self._editor_path:
                    base = os.path.basename(self._editor_path).lower()
                    for n, p in editors.items():
                        if p and os.path.basename(p).lower() == base:
                            self._editor_path = p
                            break

                # 当前设置：命中已检测项则显示其名称，否则作为自定义项回显
                cur = None
                if self._editor_path:
                    for n, p in editors.items():
                        if p and os.path.normcase(p) == os.path.normcase(
                                self._editor_path):
                            cur = n
                            break
                if cur is None and self._editor_path:
                    cur = f"自定义：{os.path.basename(self._editor_path)}"
                    editors[cur] = self._editor_path
                    names.insert(0, cur)
                ev.set(cur if cur else (names[0] if names else ""))

                cb = ttk.Combobox(ct, textvariable=ev, values=names,
                                  state="readonly", font=lf, width=20)
                cb.pack(anchor=tk.W)

                # ── 当前路径与有效性提示 ──
                path_lbl = tk.Label(ct, text="", anchor=tk.W,
                                    font=("Microsoft YaHei", 8),
                                    bg=c["sidebar_bg"], fg=c["sidebar_fg"],
                                    wraplength=420, justify=tk.LEFT)
                path_lbl.pack(fill=tk.X, pady=(10, 0))

                def _editor_ok(p):
                    import shutil
                    return bool(p) and (os.path.isfile(p)
                                        or shutil.which(p) is not None)

                def _refresh_path_label():
                    p = self._editor_path or ""
                    if not p:
                        path_lbl.configure(text="(未指定，默认使用记事本)",
                                           fg=c["sidebar_fg"])
                    elif _editor_ok(p):
                        path_lbl.configure(text=p, fg=c["sidebar_fg"])
                    else:
                        path_lbl.configure(
                            text=f"{p}\n（路径无效，打开时将回退记事本）",
                            fg="#e81123")

                def _browse():
                    """手动指定任意 exe（覆盖便携版、绿色版等检测不到的程序）"""
                    from tkinter import filedialog
                    init = (os.path.dirname(self._editor_path)
                            if self._editor_path
                            and os.path.isfile(self._editor_path)
                            else os.environ.get("ProgramFiles", "C:\\"))
                    fp = filedialog.askopenfilename(
                        parent=ct.winfo_toplevel(),
                        title="选择编辑器程序",
                        initialdir=init,
                        filetypes=[("可执行程序", "*.exe"),
                                   ("所有文件", "*.*")])
                    if not fp:
                        return
                    self._editor_path = fp
                    custom = f"自定义：{os.path.basename(fp)}"
                    editors[custom] = fp
                    if custom not in names:
                        names.append(custom)
                        cb.configure(values=names)
                    ev.set(custom)
                    _refresh_path_label()
                    self._save_settings()

                cb.bind("<<ComboboxSelected>>",
                        lambda e: (
                            setattr(self, '_editor_path',
                                    editors.get(ev.get(), self._editor_path)),
                            _refresh_path_label(),
                            self._save_settings(),
                        ))

                bb = tk.Button(ct, text="选择编辑器...",
                               font=("Microsoft YaHei", 9),
                               width=14, relief=tk.RIDGE, bd=1, cursor="hand2",
                               command=_browse)
                bb.configure(bg=c["toolbar_btn_bg"], fg=c["toolbar_btn_fg"],
                             activebackground=c["toolbar_btn_hover"])
                bb.pack(anchor=tk.W, pady=(8, 0))
                _refresh_path_label()

        def _delta_size(sv, d):
            try:
                cur = int(sv.get())
            except ValueError:
                cur = self._font_size
            cur = max(8, min(24, cur + d))
            sv.set(str(cur))
            self._font_size = cur
            self._apply_font_size()
            self._save_settings()

        # ── 左侧分类列表 ──
        categories = ["通用", "外观", "编辑器"]
        self._settings_cat_labels = []
        for i, cat_name in enumerate(categories):
            lbl = tk.Label(left, text=f"  {cat_name}",
                           font=("Microsoft YaHei", 10),
                           bg=left_bg, fg=c["sidebar_fg"],
                           anchor=tk.W, padx=12, pady=8, cursor="hand2")
            lbl.pack(fill=tk.X)
            lbl.bind("<Button-1>", lambda e, n=cat_name, l=None: (
                _highlight_cat(n), _show_category(n)))
            self._settings_cat_labels.append((lbl, cat_name))

        def _highlight_cat(name):
            for lbl, cat in self._settings_cat_labels:
                is_sel = cat == name
                lbl.configure(
                    bg=c["sidebar_item_selected"] if is_sel else left_bg,
                    fg=c["sidebar_fg"],
                )

        # 默认选中第一个
        _highlight_cat("通用")
        _show_category("通用")



        # ── 窗口缩放（仅鼠标在对话框内生效）──
        def _in_dialog(e):
            x1, y1 = dialog.winfo_rootx(), dialog.winfo_rooty()
            return x1 <= e.x_root <= x1 + dialog.winfo_width() and \
                   y1 <= e.y_root <= y1 + dialog.winfo_height()

        def _edge_region(e):
            w, h = dialog.winfo_width(), dialog.winfo_height()
            rx, ry = dialog.winfo_rootx(), dialog.winfo_rooty()
            x, y = e.x_root - rx, e.y_root - ry
            L = x <= 6; R = x >= w - 6; T = y <= 6; B = y >= h - 6
            if T and L: return "nw"
            if T and R: return "ne"
            if B and L: return "sw"
            if B and R: return "se"
            if L: return "w"
            if R: return "e"
            if T: return "n"
            if B: return "s"
            return ""
        cursors = {"n":"size_ns","s":"size_ns","e":"size_we","w":"size_we",
                    "ne":"size_ne_sw","nw":"size_nw_se","se":"size_nw_se","sw":"size_ne_sw"}
        dialog.bind("<Motion>", lambda e: dialog.config(
            cursor=cursors.get(_edge_region(e), "") if _in_dialog(e) else ""), add="+")
        def _start(e):
            if not _in_dialog(e): return
            r = _edge_region(e)
            if not r: return
            dialog._rs = {"r":r, "mx":e.x_root, "my":e.y_root,
                          "wx":dialog.winfo_x(), "wy":dialog.winfo_y(),
                          "ww":dialog.winfo_width(), "wh":dialog.winfo_height()}
        def _do(e):
            rs = getattr(dialog, '_rs', None)
            if rs is None: return
            r = rs["r"]
            dx = e.x_root - rs["mx"]; dy = e.y_root - rs["my"]
            x, y, w, h = rs["wx"], rs["wy"], rs["ww"], rs["wh"]
            if "w" in r: x += dx; w -= dx
            if "e" in r: w += dx
            if "n" in r: y += dy; h -= dy
            if "s" in r: h += dy
            if w < 400: w = 400; x = rs["wx"] + rs["ww"] - 400 if "w" in r else x
            if h < 280: h = 280; y = rs["wy"] + rs["wh"] - 280 if "n" in r else y
            dialog.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        dialog.bind("<Button-1>", _start, add="+")
        dialog.bind("<B1-Motion>", _do, add="+")
        dialog.bind("<ButtonRelease-1>", lambda e: setattr(dialog, '_rs', None), add="+")

        # ── 居中（topmost → grab → update → geometry，与其他二级窗口一致）──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{int(x)}+{int(y)}")
        try:
            ctypes.windll.user32.MoveWindow(
                dialog.winfo_id(), x, y, W, H, True)
        except Exception:
            pass
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _open_font_dialog(self):
        """打开字号设置弹窗（+/- 按钮 + 输入 + 重置）"""
        c = self.colors
        W, H = 320, 210

        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        win_border = "#555555" if self.theme_mode == "dark" else "#777777"
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=c["toolbar_bg"])
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        tk.Label(bar, text="  字号设置", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=c["toolbar_bg"], fg=c["toolbar_fg"]
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8,
                  command=dialog.destroy,
                  bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                  activebackground="#e81123"
                  ).pack(side=tk.RIGHT, fill=tk.Y)

        # ── 拖拽 ──
        def _drag_start(e):
            dialog._dx, dialog._dy = e.x_root, e.y_root
        def _drag_move(e):
            dialog.geometry(
                f"+{dialog.winfo_x() + e.x_root - dialog._dx}"
                f"+{dialog.winfo_y() + e.y_root - dialog._dy}")
            dialog._dx, dialog._dy = e.x_root, e.y_root
        for w in (bar, bar.winfo_children()[0]):
            w.bind("<Button-1>", _drag_start)
            w.bind("<B1-Motion>", _drag_move)

        # ── 主体 ──
        body = tk.Frame(dialog, bg=c["sidebar_bg"], padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        # 字号显示变量（直接绑定 self._font_size）
        size_var = tk.StringVar(value=str(self._font_size))

        def apply_size():
            try:
                new_size = int(size_var.get())
                new_size = max(8, min(24, new_size))
                size_var.set(str(new_size))
                self._font_size = new_size
                self._apply_font_size()
                self._save_settings()
                self.status_right.configure(text=f"字号: {self._font_size}   ")
                self.status_left.configure(text=f"   字号: {self._font_size}")
            except ValueError:
                size_var.set(str(self._font_size))

        def delta(d):
            try:
                cur = int(size_var.get())
            except ValueError:
                cur = self._font_size
            cur = max(8, min(24, cur + d))
            size_var.set(str(cur))
            apply_size()

        # 字号调整行：− [数字] +
        row = tk.Frame(body, bg=c["sidebar_bg"])
        row.pack(pady=(4, 10))
        tk.Label(row, text="当前字号", font=("Microsoft YaHei", 9),
                 bg=c["sidebar_bg"], fg=c["sidebar_fg"]
                 ).pack(anchor=tk.W, pady=(0, 6))

        btn_row = tk.Frame(body, bg=c["sidebar_bg"])
        btn_row.pack()

        minus_btn = tk.Button(btn_row, text="−", font=("Microsoft YaHei", 11, "bold"),
                              width=3, relief=tk.RIDGE, bd=1,
                              command=lambda: delta(-1))
        minus_btn.pack(side=tk.LEFT, padx=(0, 8))

        size_entry = tk.Entry(btn_row, textvariable=size_var,
                              font=("Microsoft YaHei", 14),
                              width=4, justify=tk.CENTER,
                              relief=tk.FLAT, bd=0,
                              highlightthickness=1)
        size_entry.pack(side=tk.LEFT, padx=(0, 8))
        size_entry.bind("<Return>", lambda e: apply_size())
        size_entry.select_range(0, tk.END)
        size_entry.focus_set()

        plus_btn = tk.Button(btn_row, text="+", font=("Microsoft YaHei", 11, "bold"),
                             width=3, relief=tk.RIDGE, bd=1,
                             command=lambda: delta(1))
        plus_btn.pack(side=tk.LEFT)

        # 提示行
        tk.Label(body, text="8 − 24", font=("Microsoft YaHei", 8),
                 bg=c["sidebar_bg"], fg="#999"
                 ).pack(pady=(4, 14))

        # 底部：重置按钮
        def reset_size():
            self._font_size = 11
            size_var.set("11")
            self._apply_font_size()
            self._save_settings()
            self.status_right.configure(text="字号: 11   ")
            self.status_left.configure(text="   字号: 11")

        reset_btn = tk.Button(body, text="重置默认 (11)",
                              font=("Microsoft YaHei", 9),
                              relief=tk.RIDGE, bd=1,
                              padx=12, pady=4,
                              command=reset_size)
        reset_btn.pack()

        # ── 主题色 ──
        entry_bg = c["content_bg"]
        entry_fg = c["content_fg"]
        btn_bg = c["toolbar_btn_bg"]
        btn_fg = c["toolbar_btn_fg"]
        btn_hover = c["toolbar_btn_hover"]

        size_entry.configure(bg=entry_bg, fg=entry_fg,
                             highlightbackground=c["search_border"],
                             highlightcolor=c["search_border"],
                             insertbackground=entry_fg)

        for btn in (minus_btn, plus_btn):
            btn.configure(bg=btn_bg, fg=btn_fg, activebackground=btn_hover,
                          activeforeground=btn_fg)

        reset_btn.configure(bg=btn_bg, fg=btn_fg, activebackground=btn_hover,
                            activeforeground=btn_fg)

        # ── 定位 ──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{x}+{y}")
        try:
            hwnd = dialog.winfo_id()
            ctypes.windll.user32.MoveWindow(hwnd, x, y, W, H, True)
        except Exception:
            pass
        dialog.attributes('-topmost', True)
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())
