"""
IndeXar 对话框与模态面板

对话框基础设施（无边框窗口 + 标题栏 + 主题适配）与具体面板：
输入框、目录选择、新建笔记/文件夹、字号设置、集成设置面板、帮助面板。
"""

import ctypes
import os
import tkinter as tk
from tkinter import ttk, messagebox

from editor_detect import detect_editors
from file_handler import (
    create_note,
    make_subdir,
    list_notes_tree,
)
from theme_manager import VSCodeTheme
from ui.common import (enable_window_resize,
                       set_appwindow_style, force_appwindow_style,
                       ensure_alt_tab, show_and_focus)


def _select_help_section(dialog, target):
    """已打开的帮助窗口按小节切换内容（重建面板后恢复位置时使用）

    target 可以是 (分类, 小节名) 元组，也可以只给小节名字符串。
    分类之间有小节同名（「表格」「代码块」在「操作指南」与「笔记格式」
    下各有一份），给出分类时才不会选错。"""
    picker = getattr(dialog, "_help_select", None)
    if not picker:
        return
    sections, select = picker
    cat, title = target if isinstance(target, tuple) else (None, target)
    if title is None:
        return
    for c_name, subs in sections.items():
        if cat is not None and c_name != cat:
            continue
        for name, items in subs:
            if name == title:
                select(c_name, name, items)
                return


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
        # 上面那次 _theme_dialog_body 是在 body 及其中控件创建之前调用的，
        # 其内部遍历看不到它们（按钮因此保持 Tk 默认外观）。控件齐了再着色
        # 一次；只着色不重复定位，避免 focus_force 把输入框的焦点抢走。
        self._paint_dialog(dialog)
        dialog.wait_window()
        return result[0]


    def _create_note(self, default_dir=""):
        """弹出新建笔记对话框"""

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
                               # 传当前值而非 default_dir，理由同 _create_folder
                               command=lambda: self._select_dir_dialog(
                                   dialog, dir_var, dir_var.get()))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # 按钮行
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def do_create():
            title = title_var.get().strip()
            if not title:
                return
            ok_name, err = self._check_note_name(title)
            if not ok_name:
                messagebox.showwarning("名称不可用", err, parent=dialog)
                return
            subdir_raw = dir_var.get()
            subdir = "" if subdir_raw == "(根目录)" else subdir_raw
            try:
                rel_path = create_note(title, subdir)
            except (OSError, ValueError) as exc:
                # create_note 内的 open() 没有兜底；异常若穿出 Tk 回调，
                # 只会打印到 stderr，打包后无控制台，用户看到的是「点了没反应」
                messagebox.showwarning("创建失败",
                                       f"无法创建笔记：{exc}", parent=dialog)
                return
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
        # 焦点必须晚于 _theme_dialog_body 的 focus_force 再设置，
        # 否则会被窗口抢走，用户还得点一下输入框才能输入
        title_entry.focus_set()

    def _check_note_name(self, title):
        """校验用户输入的笔记/文件夹名，返回 (是否可用, 原因)。

        file_handler 会把 \\/:*?"<>| 替换成下划线，但不会处理长度、纯点号
        这类情形：超长名会让 open() 抛 OSError，名字若只剩点号会生成
        「..md」这样的隐藏文件，被 _walk 过滤掉，笔记建了却永远不出现在
        文件树与索引里。这里提前拦住，给出可读的提示。"""
        if not title:
            return False, "名称不能为空。"
        # 名称里的非法字符会被替换掉，若替换后什么都不剩（如全由非法字符组成）
        import re as _re
        safe = _re.sub(r'[\\/:*?"<>|]', "_", title).strip(" .")
        if not safe:
            return False, "名称至少需要包含一个可用的字符。"
        # Windows 单个路径分量上限 255，留出 ".md" 与可能的去重编号空间
        if len(safe) > 120:
            return False, f"名称过长（{len(safe)} 个字符），请控制在 120 个字符以内。"
        if safe in (".", ".."):
            return False, "名称不能是“.”或“..”。"
        return True, ""

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

    def _paint_dialog(self, win):
        """按当前主题给对话框（标题栏 + 内部控件）上色，不含定位与 grab。

        与 _theme_dialog_body 分开，是为了主题切换时能只重着色、
        不重新居中、不重复 grab_set（后者会把已拖走的窗口拽回屏幕中央）。"""
        c = self.colors

        # ── 标题栏（其配色在 _make_dialog 里设过一次，需一并更新）──
        bar = getattr(win, '_titlebar', None)
        if bar is not None:
            try:
                bar.configure(bg=c["toolbar_bg"])
                for child in bar.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=c["toolbar_bg"], fg=c["toolbar_fg"])
                    elif isinstance(child, tk.Button):
                        child.configure(
                            bg=c["toolbar_bg"], fg=c["toolbar_fg"],
                            activebackground=("#e81123"
                                              if self.theme_mode == "light"
                                              else "#c03333"),
                            activeforeground="#ffffff")
            except tk.TclError:
                pass

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

    def _theme_dialog_body(self, win):
        """对对话框内部所有控件应用主题色 + 定位（在所有控件添加完成后调用）"""
        self._paint_dialog(win)
        # 主题切换时只重着色，不重新居中、不重复 grab
        self._register_recolor(win, lambda: self._paint_dialog(win))

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
        # 提示框也登记进 Alt+Tab（不加任务栏按钮，免得一次性弹窗把任务栏
        # 挤满），便于切到别的程序后还能切回来
        ensure_alt_tab(win)
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
            # 递归查找：此前只遍历根层的一级目录，A/B 这类子目录永远匹配不上，
            # 「预选上次目录」实际只在根层目录上生效。顺带展开沿途的父节点，
            # 否则 see() 只能滚到一个折叠中看不见的节点。
            found = [None]

            def _locate(parent_iid, trail):
                for item in tree.get_children(parent_iid):
                    vals = tree.item(item, "values")
                    if vals and vals[0] == current_dir:
                        found[0] = (item, trail)
                        return True
                    if _locate(item, trail + [item]):
                        return True
                return False

            if _locate(root_iid, []):
                node, trail = found[0]
                for anc in trail:
                    tree.item(anc, open=True)
                tree.selection_set(node)
                tree.see(node)

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
        ensure_alt_tab(dialog)                      # 进 Alt+Tab，不占任务栏
        dialog.geometry(f"{W}x{H}+{x}+{y}")
        hwnd = dialog.winfo_id()
        ctypes.windll.user32.MoveWindow(hwnd, x, y, W, H, True)
        dialog.lift()
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _create_folder(self, default_dir=""):
        """弹出新建文件夹对话框（含目录选择）"""

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
                               # 传当前值而非 default_dir：后者是对话框打开时的
                               # 初值，用户改过之后它不再代表当前选择，
                               # 再点「浏览…」就会预选错目录
                               command=lambda: self._select_dir_dialog(
                                   dialog, parent_var, parent_var.get()))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # 文件夹名称
        tk.Label(frame, text="文件夹名称：", anchor=tk.W,
                 font=("Microsoft YaHei", 10)).pack(fill=tk.X, pady=(0, 4))
        name_var = tk.StringVar(value="new_folder")
        entry = tk.Entry(frame, textvariable=name_var,
                          font=("Microsoft YaHei", 10), relief=tk.SUNKEN)
        entry.pack(fill=tk.X, pady=(0, 14))

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def do_create():
            name = name_var.get().strip()
            if name:
                ok_name, err = self._check_note_name(name)
                if not ok_name:
                    messagebox.showwarning("名称不可用", err, parent=dialog)
                    return
                raw = parent_var.get()
                parent = "" if raw == "(根目录)" else raw
                try:
                    make_subdir(parent, name)
                except (OSError, ValueError) as exc:
                    messagebox.showwarning("创建失败",
                                           f"无法创建文件夹：{exc}",
                                           parent=dialog)
                    return
                dialog.destroy()
                self._refresh_file_tree()

        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei", 9),
                  command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(btn_frame, text="创建", font=("Microsoft YaHei", 9),
                  command=do_create).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_create())
        self._theme_dialog_body(dialog)
        # 焦点与全选放在 _theme_dialog_body 之后，理由同 _create_note
        entry.focus_set()
        entry.select_range(0, tk.END)


    def _bring_to_front(self, attr):
        """按属性名取出已打开的单例面板并唤到前台；返回是否存在可用窗口

        面板若已被销毁（关闭按钮、任务栏关闭），顺带清空引用，
        使下次打开能够正常新建。"""
        dlg = getattr(self, attr, None)
        if dlg is None:
            return False
        try:
            if not dlg.winfo_exists():
                setattr(self, attr, None)
                return False
        except tk.TclError:
            setattr(self, attr, None)
            return False
        show_and_focus(dlg)          # 含从任务栏最小化状态下恢复
        return True

    def _register_dialog(self, attr, dialog):
        """登记单例面板并显示：先设任务栏样式再显示，销毁时自动清引用

        面板创建时先 withdraw，此处设完样式才 deiconify：外壳建立任务栏
        按钮时样式已正确，因此不闪烁。

        deiconify 之后必须再跑一轮 update()：Tk 在窗口未被映射时不计算子控件
        几何，所以 withdraw 期间的 update_idletasks() 只能定下窗口外框，内部
        控件仍是 1x1。若就此显示，用户看到的是左上角一小块，要拖动窗口才
        补全。映射后 update() 会立即完成布局，窗口一出现即完整。"""
        setattr(self, attr, dialog)

        def _on_destroy(event=None):
            # 子控件销毁时 Destroy 事件也会冒泡上来，只认窗口自身那一次
            if event is not None and event.widget is not dialog:
                return
            if getattr(self, attr, None) is dialog:
                setattr(self, attr, None)

        dialog.bind("<Destroy>", _on_destroy)
        ok = set_appwindow_style(dialog)
        dialog.deiconify()
        dialog.update()          # 映射后强制完成内部布局（见 docstring）
        dialog.lift()
        if not ok:
            # 句柄尚未就绪时的兜底：显示后强制重建（会闪一下）
            dialog.after(120, lambda: force_appwindow_style(dialog))

    # ── 对话框主题刷新 ──

    def _register_recolor(self, dialog, fn):
        """登记某个对话框的「按当前主题重新着色」回调。

        面板的控件都用构建期取的那一份 self.colors 上色，主题切换后
        不会自己更新。这里把重着色动作挂在窗口对象上，由 _apply_theme
        在切主题时统一调用（见 _recolor_dialogs）。"""
        try:
            dialog._recolor = fn
        except Exception:
            pass

    def _dialog_alive(self, attr):
        """取出仍存在的单例面板；已销毁则清引用并返回 None"""
        dlg = getattr(self, attr, None)
        if dlg is None:
            return None
        try:
            if not dlg.winfo_exists():
                setattr(self, attr, None)
                return None
        except tk.TclError:
            setattr(self, attr, None)
            return None
        return dlg

    def _recolor_dialogs(self):
        """主题切换后让仍打开的对话框跟上新配色（由 _apply_theme 调用）

        走 _theme_dialog_body 的小对话框已注册 _paint_dialog，可就地重着色。

        帮助/设置/字号三个面板不适用就地重着色：它们的配色写在各自的构建
        过程里（left_bg、code_bg、border 等按 is_dark 现算，并不是 colors
        字典里的键），逐控件还原容易画错。故改为按当前主题重建，并记住
        正在看的分类/小节。

        重建经 after_idle 推迟：设置面板里就有切换主题的控件，此刻正在执行
        的正是它自己的回调，不能当场把该控件销毁掉。
        """
        # 小对话框：就地重着色
        for attr in ("_tag_input_dialog", "_dir_dialog"):
            dlg = self._dialog_alive(attr)
            if dlg is None:
                continue
            fn = getattr(dlg, "_recolor", None)
            if fn is None:
                continue
            try:
                fn()
            except Exception:
                pass

        # 三个大面板：记录「重建后如何回到当前位置」，稍后重建
        plan = []
        dlg = self._dialog_alive("_help_dialog")
        if dlg is not None:
            section = getattr(dlg, "_section", None)
            plan.append(("_help_dialog", "_open_help",
                         (lambda d, s=section: _select_help_section(d, s))
                         if section else None))
        dlg = self._dialog_alive("_settings_dialog")
        if dlg is not None:
            cat = getattr(dlg, "_category", None)
            plan.append(("_settings_dialog", "_open_settings",
                         (lambda d, n=cat: d._select_category(n))
                         if cat else None))
        if self._dialog_alive("_font_dialog") is not None:
            plan.append(("_font_dialog", "_open_font_dialog", None))
        if not plan:
            return

        def _rebuild():
            for attr, opener_name, restore in plan:
                # 推迟期间用户可能已把它关掉；关掉就不再重开
                if self._dialog_alive(attr) is None:
                    continue
                try:
                    self._dialog_alive(attr).destroy()
                except (tk.TclError, AttributeError):
                    pass
                setattr(self, attr, None)
                opener = getattr(self, opener_name, None)
                if opener is None:
                    continue
                try:
                    opener()
                except Exception:
                    continue
                if restore is not None:
                    new = self._dialog_alive(attr)
                    if new is not None:
                        try:
                            restore(new)
                        except Exception:
                            pass

        try:
            self.root.after_idle(_rebuild)
        except Exception:
            pass

    def _open_help(self, category=None):
        """打开帮助面板（左分类 + 右内容，可拖动分隔）

        同一时刻只保留一个帮助窗口：已打开时不新建，而是把原窗口唤到前台，
        使重复点击不会堆出多个帮助窗口。"""
        if self._bring_to_front("_help_dialog"):
            if category:
                _select_help_section(self._help_dialog, category)
            return

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
                    ("p", "· 本帮助面板：左栏点分类名折叠 / 展开，点小节名切换内容；"),
                    ("p", "  再次点「帮助 → 使用帮助」只会把它唤到前台，不会重复开窗。"),
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
                    ("p", "· 带 Ctrl / Shift 的点击只调整选中，不会展开或折叠列表；"),
                    ("p", "  多选状态下收起某个列表，已选的标签与交集结果都会保留。"),
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
                    ("p", "· 帮助、设置、字号三类窗口各自只保留一个：重复打开时把"),
                    ("p", "  已打开的那个唤到前台，不会堆出多个窗口。"),
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
                    ("p", "· 三种写法都指向站内笔记，单击即可跳转，也都会被记入该笔记的反向链接。"),
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
        # 尺寸与左栏宽度沿用上次关闭时的取值（见下方 _close_help）
        W = max(420, min(1600, int(getattr(self, "_help_width", 660) or 660)))
        H = max(300, min(1200, int(getattr(self, "_help_height", 600) or 600)))
        left_w = max(90, min(400,
                             int(getattr(self, "_help_left_width", 150) or 150)))
        is_dark = self.theme_mode == "dark"
        win_border = "#555555" if is_dark else "#777777"
        bar_bg, bar_fg = c["nav_bg"], c["nav_fg"]
        bar_btn_hover = "#e81123" if not is_dark else "#c03333"

        dialog = tk.Toplevel(self.root)
        dialog.withdraw()            # 内容与样式齐备后再显示，避免出现过程闪动
        dialog.overrideredirect(True)
        dialog.configure(bg=c["sidebar_bg"], highlightthickness=1,
                         highlightbackground=win_border)
        dialog.minsize(420, 300)

        # ── 标题栏 ──
        bar = tk.Frame(dialog, height=28, bg=bar_bg)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)
        def _close_help():
            """关闭前记录窗口尺寸与左栏宽度，下次打开时沿用。

            记录的是画布宽度而非整个左栏：左栏还有边距与滚动条占位，
            若把左栏宽度当作画布宽度还原，每次开关都会再胖一圈。"""
            try:
                self._help_width = dialog.winfo_width()
                self._help_height = dialog.winfo_height()
                self._help_left_width = nav_canvas.winfo_width()
                self._save_settings()
            except Exception:
                pass
            dialog.destroy()

        tk.Label(bar, text="  帮助", font=("Microsoft YaHei", 10),
                 anchor=tk.W, bg=bar_bg, fg=bar_fg
                 ).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(bar, text="✕", font=("Segoe UI", 9),
                  relief=tk.FLAT, bd=0, padx=8, command=_close_help,
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
        # 左栏宽度由画布显式给出：Frame 自身的 width 会被子控件的请求宽度顶掉
        left = tk.Frame(pane, bg=left_bg)
        right = tk.Frame(pane, bg=c["sidebar_bg"], padx=6, pady=10)
        pane.add(left, weight=0)
        pane.add(right, weight=1)

        # ── 左栏：Canvas + 滚动条，内容超出高度时可滚动 ──
        nav_canvas = tk.Canvas(left, width=left_w, bg=left_bg,
                               highlightthickness=0)
        nav_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL,
                                   command=nav_canvas.yview)
        nav_inner = tk.Frame(nav_canvas, bg=left_bg)
        _nav_win = nav_canvas.create_window((0, 0), window=nav_inner,
                                            anchor="nw")
        nav_canvas.configure(yscrollcommand=nav_scroll.set)
        # 左栏用 grid 而非 pack：pack 下 canvas（先 pack、expand=True）
        # 会先占走份额，栏宽一收紧滚动条就只剩一条缝，看起来像被遮盖；
        # grid 中滚动条独占一个定宽列，canvas 只吃剩余宽度。
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)
        left.grid_columnconfigure(1, weight=0)
        # 左侧留 8px：既不压住窗口边缘（留给拖拽缩放），也不显得贴边
        nav_canvas.grid(row=0, column=0, sticky="nsew", padx=(8, 0))

        def _sync_nav_scroll(_event=None):
            nav_canvas.configure(scrollregion=nav_canvas.bbox("all"))
            need = nav_inner.winfo_reqheight() > nav_canvas.winfo_height() + 1
            if need and not nav_scroll.winfo_ismapped():
                nav_scroll.grid(row=0, column=1, sticky="ns")
            elif not need and nav_scroll.winfo_ismapped():
                nav_scroll.grid_remove()

        # 内容高度与可视高度任一方变化都要重算滚动区
        nav_inner.bind("<Configure>", _sync_nav_scroll)
        nav_canvas.bind("<Configure>", lambda e: (
            nav_canvas.itemconfigure(_nav_win, width=e.width),
            _sync_nav_scroll()))

        # 折叠分类会改变内容高度，一并刷新
        def _nav_wheel(e):
            nav_canvas.yview_scroll(-int(e.delta / 120) or -1, "units")
            return "break"

        # Tk 的事件只按 bindtags 派发（widget → class → toplevel → all），
        # 不会传给父控件。左栏的分类头与小节名都是铺满整栏的 Label，鼠标停在
        # 它们上面时事件落在 Label 上，只绑 nav_canvas / nav_inner 收不到，
        # 于是左栏滚不动。故在下面创建每个 Label 时一并绑定 _nav_wheel
        # （不用 bind_all：那是全局绑定，窗口销毁后仍会残留）。
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

        def _render(title, items, cat=None):
            # 记下当前分类与小节：主题切换后据此重建面板，回到同一节
            dialog._section = (cat, title) if cat else title
            text.configure(state=tk.NORMAL)
            text.delete("1.0", "end")
            text.insert("end", title + "\n", "h")
            for kind, line in items:
                text.insert("end", line + "\n", kind)
            text.configure(state=tk.DISABLED)
            text.yview_moveto(0)

        # ── 左侧层级：分类（可折叠） → 小节 ──
        sub_labels = []    # [(分类名, 小节标题, 内容, Label)]
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

        def _select(cat, title, items):
            # 用「分类 + 小节名」作键：分类之间有小节同名（「操作指南」与
            # 「笔记格式」下都有「表格」「代码块」），只按标题匹配会把两处
            # 同时点亮，也分不清当前内容属于哪个分类。
            for c_name, t, _i, lbl in sub_labels:
                lbl.configure(bg=c["toolbar_btn_hover"]
                              if (c_name, t) == (cat, title) else left_bg)
            _render(title, items, cat)

        # 供重复打开时按小节名切换内容（_select_help_section 取用）
        dialog._help_select = (sections, _select)

        for cat, subs in sections.items():
            holder = tk.Frame(nav_inner, bg=left_bg)
            holder.pack(fill=tk.X)
            head = tk.Label(holder, anchor=tk.W, cursor="hand2",
                            font=("Microsoft YaHei", 10, "bold"),
                            bg=left_bg, fg=c["sidebar_fg"], pady=6)
            head.pack(fill=tk.X)
            head.bind("<Button-1>", lambda e, cat=cat: _toggle(cat))
            head.bind("<MouseWheel>", _nav_wheel)
            sub = tk.Frame(holder, bg=left_bg)
            sub.pack(fill=tk.X)

            for title, items in subs:
                lbl = tk.Label(sub, text="      " + title, anchor=tk.W,
                               font=("Microsoft YaHei", 9),
                               bg=left_bg, fg=c["sidebar_fg"], pady=3,
                               cursor="hand2")
                lbl.pack(fill=tk.X)
                lbl.bind("<Button-1>",
                         lambda e, ct=cat, t=title, i=items: _select(ct, t, i))
                lbl.bind("<MouseWheel>", _nav_wheel)
                sub_labels.append((cat, title, items, lbl))

            cat_rows.append((cat, head, sub))

        _refresh_fold()

        # 初始定位：优先命中 category（按分类名），否则第一个小节
        if sub_labels:
            pick = sub_labels[0]
            if category:
                for row in sub_labels:
                    if row[0] == category:
                        pick = row
                        break
            _select(pick[0], pick[1], pick[2])

        # 无边框窗口需自行支持缩放：边缘与四角可拖拽
        enable_window_resize(dialog, titlebar=bar)

        # 居中于主窗口
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - W) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - H) // 2
        dialog.geometry(f"{W}x{H}+{max(x, 0)}+{max(y, 0)}")
        _sync_nav_scroll()

        # 任务栏右键关闭与 Alt+F4 都走同一套收尾（记录尺寸并清引用）
        dialog.protocol("WM_DELETE_WINDOW", _close_help)
        # 单例登记 + 任务栏/Alt+Tab 集成（内部先设样式再显示，不闪烁）
        self._register_dialog("_help_dialog", dialog)

    def _open_settings(self):
        """打开集成设置面板（左分类 + 右内容，可拖动分隔）

        与帮助窗口同样只保留一份：已打开时唤到前台，不再新建。"""
        if self._bring_to_front("_settings_dialog"):
            return

        c = self.colors
        W, H = 600, 420
        is_dark = self.theme_mode == "dark"
        win_border = "#555555" if is_dark else "#777777"
        # 标题栏用活动栏配色
        bar_bg = c["nav_bg"]
        bar_fg = c["nav_fg"]
        bar_btn_hover = "#e81123" if not is_dark else "#c03333"

        dialog = tk.Toplevel(self.root)
        dialog.withdraw()            # 内容与样式齐备后再显示，避免出现过程闪动
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
            # 记下当前分类：主题切换后据此重建面板，不把用户弹回默认分类
            dialog._category = name
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
                # 输入框本身没有提交路径（此前只有 ± 按钮生效），
                # 手输 18 再回车/移开焦点不会改变字号，框里却显示 18，
                # 界面与实际值长期不一致。这里补上回车与失焦提交，
                # 复用 _delta_size 的钳位与落盘逻辑（d=0 表示只提交不增减）。
                e.bind("<Return>", lambda ev, sv=sv: _delta_size(sv, 0))
                e.bind("<FocusOut>", lambda ev, sv=sv: _delta_size(sv, 0))

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

        # 供主题切换后重建面板时回到同一分类（见 _recolor_dialogs）
        def _select_category(name):
            _highlight_cat(name)
            _show_category(name)
        dialog._select_category = _select_category



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

        # ── 居中：先设样式再显示，最后 grab（grab 要求窗口已映射）──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - W) // 2, (sh - H) // 2
        dialog.attributes('-topmost', True)
        dialog.update_idletasks()
        dialog.geometry(f"{W}x{H}+{int(x)}+{int(y)}")
        set_appwindow_style(dialog)   # 显示前设好，任务栏按钮建立时即带上
        dialog.deiconify()
        dialog.update_idletasks()     # 等窗口真正映射
        try:
            dialog.grab_set()
        except tk.TclError:
            pass                      # 极端情况下退化为非模态，不影响使用
        try:
            ctypes.windll.user32.MoveWindow(
                dialog.winfo_id(), x, y, W, H, True)
        except Exception:
            pass
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        self._register_dialog("_settings_dialog", dialog)

    def _open_font_dialog(self):
        """打开字号设置弹窗（+/- 按钮 + 输入 + 重置）

        与帮助、设置同样只保留一份：已打开时唤到前台，不再新建。"""
        if self._bring_to_front("_font_dialog"):
            return

        c = self.colors
        W, H = 320, 210

        dialog = tk.Toplevel(self.root)
        dialog.withdraw()            # 内容与样式齐备后再显示，避免出现过程闪动
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
        dialog.focus_force()
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        self._register_dialog("_font_dialog", dialog)
