"""
独立布局测试文件 — 仅保留空间分配逻辑，无样式代码。
运行: python test_layout.py
"""
import tkinter as tk
from tkinter import ttk


class TestApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("布局测试")
        self.root.geometry("1100x680+200+100")
        self.root.minsize(800, 500)
        self.root.overrideredirect(True)

        self.current_panel = "files"

        # 共享状态: 两个页面共享这些变量
        self._file_tags_collapsed = False  # 折叠状态
        self._file_tags_height = 88        # 容器高度 (px)
        self._sidebar_width = 240          # 侧栏宽度 (px)

        # 配色 (仅用于区分区域, 无实际样式意义)
        self.c = {
            "toolbar_bg": "#ddd",
            "nav_bg": "#ccc",
            "sidebar_bg": "#eee",
            "sidebar_header_bg": "#ddd",
            "content_bg": "#fff",
            "content_header_bg": "#eee",
            "status_bg": "#ccc",
            "app_bg": "#f5f5f5",
        }

        self._build_layout()

    # ════════════════ 布局 ════════════════

    def _build_layout(self):
        """搭建完整布局框架。"""
        # Treeview 统一样式（去默认边框、统一背景色）
        style = ttk.Style()
        style.configure("Flat.Treeview", borderwidth=0, relief=tk.FLAT,
                        background=self.c["sidebar_bg"],
                        fieldbackground=self.c["sidebar_bg"])
        style.layout("Flat.Treeview", [
            ('Treeview.treearea', {'sticky': 'nswe'})])

        # Root: 3行, 1列
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # ── 标题栏 (row=0, sticky="ew", h=30) ──
        self._is_maximized = False
        self._normal_geometry = None

        bar = tk.Frame(self.root, height=30, bg=self.c["toolbar_bg"])
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)  # 空列把按钮推到右边

        # 关闭按钮 (col=1)
        cls_btn = tk.Label(bar, text=" ✕ ", cursor="hand2",
                           bg=self.c["toolbar_bg"])
        cls_btn.grid(row=0, column=1, sticky="e", padx=(0, 2))
        cls_btn.bind("<Button-1>", lambda e: self.root.destroy())

        # 最大化/还原按钮 (col=2)
        self.max_btn = tk.Label(bar, text=" □ ", cursor="hand2",
                                bg=self.c["toolbar_bg"])
        self.max_btn.grid(row=0, column=2, sticky="e", padx=(0, 4))
        self.max_btn.bind("<Button-1>", lambda e: self._toggle_maximize())

        # ── 主体 (row=1, sticky="nsew") ──
        self.body = tk.Frame(self.root, bg=self.c["app_bg"])
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(3, weight=1)  # content_body 列
        self.body.grid_rowconfigure(0, weight=1)

        # ── 活动栏 (col=0, sticky="ns", w=48) ──
        self.nav = tk.Frame(self.body, width=48, bg=self.c["nav_bg"])
        self.nav.grid(row=0, column=0, sticky="ns")
        self.nav.grid_propagate(False)

        # 两个切换按钮
        self.nav_files_btn = tk.Label(self.nav, text="📁", cursor="hand2",
                                      bg=self.c["nav_bg"])
        self.nav_files_btn.grid(row=0, column=0, pady=(8, 0))
        self.nav_files_btn.bind("<Button-1>", lambda e: self._show_files())
        self.nav_tags_btn = tk.Label(self.nav, text="🏷", cursor="hand2",
                                     bg=self.c["nav_bg"])
        self.nav_tags_btn.grid(row=1, column=0, pady=(8, 0))
        self.nav_tags_btn.bind("<Button-1>", lambda e: self._show_tags())

        # ── 侧栏 (col=1, sticky="ns", w=240) ──
        self.side_frame = tk.Frame(self.body, width=240, bg=self.c["sidebar_bg"])
        self.side_frame.grid(row=0, column=1, sticky="ns")
        self.side_frame.grid_propagate(False)
        self.side_frame.grid_rowconfigure(0, weight=1)
        self.side_frame.grid_columnconfigure(0, weight=1)

        # ══════ 文件树页 ══════
        # 内部用 pack 垂直堆叠：header → tree(expand) → tags_container(bottom)
        self.file_tree_frame = tk.Frame(self.side_frame, bg=self.c["sidebar_bg"])

        # 标题头
        th = tk.Frame(self.file_tree_frame, bg=self.c["sidebar_header_bg"])
        th.pack(fill=tk.X)
        tk.Label(th, text="  笔记列表", bg=self.c["sidebar_header_bg"],
                 anchor=tk.W).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 树区域 (expand, 填充中间)
        tc = tk.Frame(self.file_tree_frame, bd=0, highlightthickness=0,
                      bg=self.c["sidebar_bg"])
        tc.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tc, orient=tk.VERTICAL)
        sb.pack(side=tk.RIGHT, fill=tk.Y)        # 先 pack → 最右边
        sb_border = tk.Frame(tc, width=1, bg="#bbb")
        sb_border.pack(side=tk.RIGHT, fill=tk.Y) # 后 pack → 滚动条左边
        tree = ttk.Treeview(tc, show="tree", style="Flat.Treeview")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.configure(command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        for i in range(20):
            tree.insert("", "end", text=f"   note_{i}.md")

        # "当前文件标签" (pack_side=TOP 默认, 固定在 tree 下方)
        self._build_file_tags_section(self.file_tree_frame, "file_")

        # ══════ 标签页 ══════
        # 内部用 pack 垂直堆叠:
        #   header(top) → body(expand, 可隐藏) → container(bottom, 可变成 expand)
        # 收起 body 时 container 自动上移并填满空间
        self.tag_frame = tk.Frame(self.side_frame, bg=self.c["sidebar_bg"])

        # "所有标签" 标题头
        self.section_all_header = tk.Label(
            self.tag_frame, text="▼ 所有标签",
            bg=self.c["sidebar_header_bg"],
            anchor=tk.W, padx=4, pady=4, cursor="hand2",
            bd=0)
        self.section_all_header.pack(fill=tk.X)

        # "所有标签" 内容体 (expand, 填充中间)
        self.section_all_body = tk.Frame(self.tag_frame, bd=0, highlightthickness=0,
                                         bg=self.c["sidebar_bg"])
        self.section_all_body.pack(fill=tk.BOTH, expand=True)
        self.section_all_body._collapsed = False

        # 标签树
        ttc = tk.Frame(self.section_all_body, bd=0, highlightthickness=0,
                       bg=self.c["sidebar_bg"])
        ttc.pack(fill=tk.BOTH, expand=True)
        tsb = ttk.Scrollbar(ttc, orient=tk.VERTICAL)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)        # 先 pack → 最右边
        tsb_border = tk.Frame(ttc, width=1, bg="#bbb")
        tsb_border.pack(side=tk.RIGHT, fill=tk.Y) # 后 pack → 滚动条左边
        tag_tree = ttk.Treeview(ttc, show="tree", style="Flat.Treeview")
        tag_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tsb.configure(command=tag_tree.yview)
        tag_tree.configure(yscrollcommand=tsb.set)
        for i in range(15):
            tag_tree.insert("", "end", text=f"   tag_{i}  ({i+1})")

        # "当前文件标签" (固定在底部)
        self._build_file_tags_section(self.tag_frame, "tag_", pack_side=tk.BOTTOM)

        # 折叠/展开"所有标签" — body 隐藏时 container 切换为 expand 填满空间
        def _toggle_all_tags(e=None):
            body = self.section_all_body
            ctr = self.tag_tags_container
            if body._collapsed:
                # 展开: body 重新出现, container 回到底部固定高度
                body.pack(fill=tk.BOTH, expand=True,
                          before=ctr if ctr.winfo_ismapped() else None)
                ctr.pack_forget()
                ctr.pack(fill=tk.X, side=tk.BOTTOM)
                ctr.configure(height=self._file_tags_height if not self._file_tags_collapsed else 28)
                self.section_all_header.configure(
                    text=self.section_all_header.cget("text").replace("▶", "▼"))
                body._collapsed = False
            else:
                # 收起: body 隐藏, container 填满剩余空间
                body.pack_forget()
                ctr.pack_forget()
                if self._file_tags_collapsed:
                    ctr.pack(fill=tk.X)  # 仅标题栏
                else:
                    ctr.pack(fill=tk.BOTH, expand=True)  # 填满
                self.section_all_header.configure(
                    text=self.section_all_header.cget("text").replace("▼", "▶"))
                body._collapsed = True
            self._apply_file_tags_visibility()

        self.section_all_header.bind("<Button-1>", _toggle_all_tags)

        # ── 侧栏分隔条 (col=2, sticky="ns") ──
        self._grip = tk.Frame(self.body, width=1, bg="#bbb",
                              cursor="sb_h_double_arrow")
        self._grip.grid(row=0, column=2, sticky="ns")
        self._grip.grid_propagate(False)
        self._grip.bind("<Button-1>", self._start_sidebar_drag)
        self._grip.bind("<B1-Motion>", self._do_sidebar_drag)

        # ── 内容区 (col=3, sticky="nsew") ──
        self.content_body = tk.Frame(self.body, bg=self.c["content_bg"])
        self.content_body.grid(row=0, column=3, sticky="nsew")
        self.content_body.grid_rowconfigure(1, weight=1)
        self.content_body.grid_columnconfigure(0, weight=1)
        ch = tk.Frame(self.content_body, bg=self.c["content_header_bg"])
        ch.grid(row=0, column=0, sticky="new")
        ch.grid_columnconfigure(0, weight=1)
        tk.Label(ch, text="   内容区", bg=self.c["content_header_bg"],
                 anchor=tk.W).grid(row=0, column=0, sticky="nsew")
        txt = tk.Text(self.content_body, relief=tk.FLAT,
                      highlightthickness=0, borderwidth=0)
        txt.grid(row=1, column=0, sticky="nsew")
        txt.insert(tk.END, "  ← 侧栏  |  内容区 →")
        txt.configure(state=tk.DISABLED)

        # ── 状态栏 (row=2, sticky="ew", h=22) ──
        sb_frame = tk.Frame(self.root, height=22, bg=self.c["status_bg"])
        sb_frame.grid(row=2, column=0, sticky="ew")
        sb_frame.grid_propagate(False)

        self._show_files()

    # ════════════════ 共享组件: "当前文件标签" 工厂 ════════════════

    def _build_file_tags_section(self, parent, prefix, pack_side=None):
        """
        在 parent 中创建"当前文件标签"区块。
        内部使用 pack 垂直堆叠: sep → header → body(expand)
        pack_side: 容器在 parent 中的 side (BOTTOM 用于标签页)
        """
        # ★ 容器: propagate=False 锁定像素高度, 实现精确拖拽
        container = tk.Frame(parent, bd=0, highlightthickness=0,
                             height=self._file_tags_height,
                             bg=self.c["sidebar_bg"])
        container.pack(fill=tk.X, side=pack_side if pack_side else tk.TOP)
        container.pack_propagate(False)
        setattr(self, f"{prefix}tags_container", container)

        # 拖拽手柄 (4px)
        sep = tk.Frame(container, height=4, cursor="sb_v_double_arrow",
                       bg=self.c["sidebar_bg"])
        sep.pack(fill=tk.X)
        sep.bind("<Button-1>", lambda e: self._start_tags_drag(e, prefix))
        sep.bind("<B1-Motion>", lambda e: self._do_tags_drag(e, prefix))
        setattr(self, f"{prefix}tags_sep", sep)

        # 标题头 (点击折叠/展开) — 和"所有标签" 一致的颜色样式
        header = tk.Label(container, text="▼ 当前文件标签",
                          bg=self.c["sidebar_header_bg"],
                          anchor=tk.W, padx=4, pady=4, cursor="hand2",
                          bd=0)
        header.pack(fill=tk.X)
        header.bind("<Button-1>", lambda e: self._toggle_file_tags())
        setattr(self, f"{prefix}tags_header", header)

        # 内容体 (fill 容器剩余空间)
        body = tk.Frame(container, bd=0, highlightthickness=0,
                        bg=self.c["sidebar_bg"])
        body.pack(fill=tk.BOTH, expand=True)
        setattr(self, f"{prefix}tags_body", body)

        # 标签列表 (填充 body)
        lb = tk.Listbox(body, relief=tk.FLAT, highlightthickness=0,
                        borderwidth=0, activestyle="none", selectmode="browse")
        lb.pack(fill=tk.BOTH, expand=True)
        lb.insert(tk.END, "  tag_a")
        lb.insert(tk.END, "  tag_b")
        lb.insert(tk.END, "  tag_c")
        setattr(self, f"{prefix}tags_listbox", lb)

    # ════════════════ 拖拽逻辑 ════════════════

    def _start_tags_drag(self, event, prefix):
        """记录起始: y_root, 容器高度, 父容器高度"""
        ctr = getattr(self, f"{prefix}tags_container")
        self._tags_drag = {
            "y": event.y_root,
            "start_h": ctr.winfo_height(),
            "parent_h": ctr.master.winfo_height(),
        }

    def _do_tags_drag(self, event, prefix):
        """
        拖拽中: dy = y_start - y_current
        new_h = start_h + dy
        限制: [50, parent_h * 0.8]
        同步两页容器高度。
        """
        if self._file_tags_collapsed:
            return
        d = self._tags_drag
        dy = d["y"] - event.y_root
        new_h = d["start_h"] + dy
        new_h = max(50, min(int(d["parent_h"] * 0.8), new_h))
        self._file_tags_height = new_h
        for p in ("file_", "tag_"):
            ctr = getattr(self, f"{p}tags_container", None)
            if ctr:
                # 只在容器非 expand 模式时应用高度 (expand 模式由 pack 管理)
                info = ctr.pack_info()
                if not info.get("expand", False):
                    ctr.configure(height=new_h)

    # ════════════════ 折叠逻辑 ════════════════

    def _toggle_file_tags(self):
        """切换折叠状态"""
        self._file_tags_collapsed = not self._file_tags_collapsed
        self._apply_file_tags_visibility()

    def _apply_file_tags_visibility(self):
        """
        展开: body 显示, 容器高度 = _file_tags_height
        折叠: body 隐藏, 容器缩小到 28px (仅标题)
        标签页: 如果 body 已收起，container 需要 expand 填满
        """
        arrow = "▶" if self._file_tags_collapsed else "▼"
        all_tags_collapsed = self.section_all_body._collapsed
        for prefix in ("file_", "tag_"):
            header = getattr(self, f"{prefix}tags_header", None)
            body = getattr(self, f"{prefix}tags_body", None)
            ctr = getattr(self, f"{prefix}tags_container", None)
            if header:
                header.configure(text=f"{arrow} 当前文件标签")
            if body:
                if self._file_tags_collapsed:
                    body.pack_forget()
                else:
                    body.pack(fill=tk.BOTH, expand=True)
            if ctr:
                new_h = 28 if self._file_tags_collapsed else self._file_tags_height
                ctr.configure(height=new_h)
                # 标签页：如果所有标签已收起，重新调整 container 的 pack 模式
                if prefix == "tag_" and all_tags_collapsed:
                    ctr.pack_forget()
                    if self._file_tags_collapsed:
                        ctr.pack(fill=tk.X)
                    else:
                        ctr.pack(fill=tk.BOTH, expand=True)

    # ════════════════ 面板切换 ════════════════

    def _show_files(self):
        self.current_panel = "files"
        self.tag_frame.grid_remove()
        self.file_tree_frame.grid(row=0, column=0, sticky="nsew")
        self._apply_file_tags_visibility()

    def _show_tags(self):
        self.current_panel = "tags"
        self.file_tree_frame.grid_remove()
        self.tag_frame.grid(row=0, column=0, sticky="nsew")
        self._apply_file_tags_visibility()

    # ════════════════ 侧栏拖拽 ════════════════

    def _start_sidebar_drag(self, event):
        self._sidebar_drag_x = event.x_root

    SIDEBAR_MIN = 120          # 最小可见宽度
    SIDEBAR_COLLAPSE = 80      # 低于此值直接关闭（设置为 0）

    def _do_sidebar_drag(self, event):
        dx = event.x_root - self._sidebar_drag_x
        new_w = self._sidebar_width + dx
        max_w = max(300, self.root.winfo_width() // 2)
        # 低于 COLLAPSE 阈值 → 直接关闭；不低于 min 时正常显示
        if new_w < self.SIDEBAR_COLLAPSE:
            new_w = 0
        else:
            new_w = max(self.SIDEBAR_MIN, min(new_w, max_w))
        if new_w != self._sidebar_width:
            self._sidebar_width = new_w
            self.side_frame.configure(width=new_w)
            self._sidebar_drag_x = event.x_root

    def _toggle_maximize(self):
        """切换窗口最大化/还原"""
        if self._is_maximized:
            # 还原
            if self._normal_geometry:
                self.root.geometry(self._normal_geometry)
            self._is_maximized = False
            self.max_btn.configure(text=" □ ")
        else:
            # 最大化
            self._normal_geometry = self.root.geometry()  # 记住当前位置大小
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{sw}x{sh}+0+0")
            self._is_maximized = True
            self.max_btn.configure(text=" ❐ ")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TestApp().run()
