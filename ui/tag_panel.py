"""
IndeXar 标签面板

左侧标签视图：全部标签聚合、当前文件标签编辑（增删）、标签搜索、
多选标签求交集，以及与标签相关的拖拽与悬停交互。
"""

import os
import tkinter as tk
from tkinter import ttk

from file_handler import (get_tag_index, build_tag_index, intersect_tags,
                          parse_front_matter_tags, set_note_tags)
from ui.common import _add_hover_bg


class TagPanelMixin:
    """标签面板与标签编辑"""

    def _build_tag_panel(self):
        """标签面板：可折叠的两个区块 —— 所有标签 + 当前文件标签"""
        self.tag_frame = tk.Frame(self.side_frame)

        # ── 辅助：创建可折叠区块 ──
        def _make_section(parent, title_text, expand=True):
            """返回 (header_label, body_frame)，header 点击折叠/展开 body"""
            header = tk.Label(
                parent,
                text=f"▼ {title_text}",
                font=("Microsoft YaHei", 9),
                anchor=tk.W, padx=4, pady=4,
                cursor="hand2",
            )
            header.pack(fill=tk.X)
            body = tk.Frame(parent, bd=0, highlightthickness=0)
            body.pack(fill=tk.BOTH, expand=expand)
            body._collapsed = False
            body._expand = expand

            def toggle():
                if body._collapsed:
                    body.pack(fill=tk.BOTH, expand=body._expand,
                              before=body._next_widget if hasattr(body, '_next_widget') else None)
                    header.configure(text=header.cget("text").replace("▶", "▼"))
                    body._collapsed = False
                else:
                    body.pack_forget()
                    header.configure(text=header.cget("text").replace("▼", "▶"))
                    body._collapsed = True

            header.bind("<Button-1>", lambda e: toggle())
            return header, body

        # ── 区块1：所有标签 ──
        self.section_all_header, self.section_all_body = _make_section(
            self.tag_frame, "所有标签", expand=True)

        # 搜索框
        self.tag_search_var = tk.StringVar()
        self.tag_search_var.trace_add("write", lambda *a: self._on_tag_search())
        self.tag_search_entry = tk.Entry(
            self.section_all_body,
            textvariable=self.tag_search_var,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
        )
        self.tag_search_entry.pack(fill=tk.X, padx=8, pady=(4, 2))
        self.tag_search_entry.bind("<Escape>", lambda e: (
            self.tag_search_var.set(""),
            self._refresh_tags(),
        ))
        self._tag_search_placeholder = "搜索标签..."
        self.tag_search_entry.insert(0, self._tag_search_placeholder)
        self.tag_search_entry.configure(fg="#999")
        self.tag_search_entry.bind("<FocusIn>", self._on_tag_search_focus_in)
        self.tag_search_entry.bind("<FocusOut>", self._on_tag_search_focus_out)

        # 交集提示
        self.tag_intersection_label = tk.Label(
            self.section_all_body,
            text="",
            font=("Microsoft YaHei", 8),
            anchor=tk.W, padx=10, pady=1,
        )
        self.tag_intersection_label.pack(fill=tk.X)

        # 标签/文件 Treeview
        self.tag_tree_container = tk.Frame(self.section_all_body,
                                           bd=0, highlightthickness=0)
        self.tag_tree_container.pack(fill=tk.BOTH, expand=True)

        self.tag_tree_scroll = ttk.Scrollbar(
            self.tag_tree_container, orient=tk.VERTICAL,
        )
        self.tag_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tag_tree = ttk.Treeview(
            self.tag_tree_container, show="tree",
            selectmode="extended",
        )
        self.tag_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tag_tree_scroll.configure(command=self.tag_tree.yview)
        self.tag_tree.configure(yscrollcommand=self.tag_tree_scroll.set)

        self.tag_tree.bind("<<TreeviewSelect>>", self._on_tag_tree_select)
        self.tag_tree.bind("<Double-Button-1>", self._on_tag_tree_double_click)
        self.tag_tree.bind("<ButtonPress-1>", self._on_tag_tree_press)
        self.tag_tree.bind("<ButtonRelease-1>", self._on_tag_tree_click)
        self.tag_tree.bind("<Motion>", self._on_tag_tree_motion)
        self.tag_tree.bind("<Leave>", self._on_tag_tree_leave)

        # ── 区块2：当前文件标签（共享组件，固定在底部）──
        self._build_file_tags_section(self.tag_frame, "tag_",
                                      pack_side=tk.BOTTOM)
        self.section_all_body._next_widget = self.tag_tags_container

        # 覆写"所有标签"的折叠行为：收起时将"当前文件标签"提上来贴着头
        self.section_all_header.unbind("<Button-1>")
        self.section_all_header.bind("<Button-1>",
                                     lambda e: self._toggle_all_tags_section())

    # ── 标签页"所有标签"折叠逻辑 ──

    def _toggle_all_tags_section(self):
        """展开/折叠'所有标签'区块，'当前文件标签'跟随移动"""
        body = self.section_all_body
        header = self.section_all_header
        if body._collapsed:
            self._expand_all_tags_section()
        else:
            body.pack_forget()
            # 收起时容器切换到 expand 模式，填满剩余空间
            ctr = self.tag_tags_container
            ctr.pack_forget()
            ctr.pack(fill=tk.BOTH, expand=True)
            header.configure(text=header.cget("text").replace("▼", "▶"))
            body._collapsed = True

    def _expand_all_tags_section(self):
        """展开'所有标签'，'当前文件标签'归位底部"""
        body = self.section_all_body
        header = self.section_all_header
        ctr = self.tag_tags_container
        if not body._collapsed:
            return
        body.pack(fill=tk.BOTH, expand=True, before=ctr)
        # 恢复容器为底部固定模式
        ctr.pack_forget()
        ctr.pack(fill=tk.X, side=tk.BOTTOM)
        header.configure(text=header.cget("text").replace("▶", "▼"))
        body._collapsed = False

    # ── 共享组件：当前文件标签区块 ──

    def _build_file_tags_section(self, parent, prefix, pack_side=None):
        """在 parent 中创建'当前文件标签'区块，设置 self.{prefix}_tags_* 属性。
        pack_side: 容器在 parent 中的 pack side（如 tk.BOTTOM 用于标签页）"""

        # ── 外层容器 ──
        container = tk.Frame(parent, bd=0, highlightthickness=0,
                             height=self._file_tags_height)
        container.pack(fill=tk.X, side=pack_side if pack_side else tk.TOP)
        container.pack_propagate(False)
        setattr(self, f"{prefix}tags_container", container)

        # ── 可拖动分隔条 ──
        sep = tk.Frame(container, height=4, cursor="sb_v_double_arrow")
        sep.pack(fill=tk.X)
        sep.bind("<Button-1>", lambda e: self._start_tags_drag(e, prefix))
        sep.bind("<B1-Motion>", lambda e: self._do_tags_drag(e, prefix))
        setattr(self, f"{prefix}tags_sep", sep)

        header = tk.Label(container,
                          text="▼ 当前文件标签",
                          font=("Microsoft YaHei", 9),
                          anchor=tk.W, padx=4, pady=3,
                          cursor="hand2")
        header.pack(fill=tk.X)

        body = tk.Frame(container, bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True)

        # 标签工具条：＋ 添加 / － 删除
        toolbar = tk.Frame(body, bd=0, highlightthickness=0)
        toolbar.pack(fill=tk.X, padx=8, pady=(2, 0))
        add_btn = tk.Label(toolbar, text="＋ 添加标签",
                           font=("Microsoft YaHei", 9),
                           cursor="hand2", padx=2)
        add_btn.pack(side=tk.LEFT)
        del_btn = tk.Label(toolbar, text="－ 删除所选",
                           font=("Microsoft YaHei", 9),
                           cursor="hand2", padx=6)
        del_btn.pack(side=tk.LEFT)
        add_btn.bind("<Button-1>",
                     lambda e, pf=prefix: self._add_current_file_tag(pf))
        del_btn.bind("<Button-1>",
                     lambda e, pf=prefix: self._remove_selected_file_tag(pf))

        listbox = tk.Listbox(body,
                             font=("Microsoft YaHei", 10),
                             relief=tk.FLAT, highlightthickness=0,
                             borderwidth=0, activestyle="none",
                             selectmode="browse")
        listbox.pack(fill=tk.BOTH, expand=True, padx=8)

        header.bind("<Button-1>", lambda e: self._toggle_file_tags())
        listbox.bind("<Double-Button-1>", self._on_file_tag_dclick)

        setattr(self, f"{prefix}tags_header", header)
        setattr(self, f"{prefix}tags_body", body)
        setattr(self, f"{prefix}tags_toolbar", toolbar)
        setattr(self, f"{prefix}tags_listbox", listbox)

    # ── 拖拽调整标签区块高度 ──

    def _start_tags_drag(self, event, prefix):
        ctr = getattr(self, f"{prefix}tags_container")
        parent = ctr.master
        self._tags_drag = {
            "y": event.y_root,
            "start_h": ctr.winfo_height(),
            "parent_h": parent.winfo_height(),
            "min_upper": 120 if prefix == "file_" else 160,
        }

    def _do_tags_drag(self, event, prefix):
        if self._file_tags_collapsed:
            return
        d = self._tags_drag
        dy = d["y"] - event.y_root
        new_h = d["start_h"] + dy
        lower_max = d["parent_h"] - d["min_upper"]
        new_h = max(60, min(lower_max, new_h))
        self._file_tags_height = new_h
        for p in ("file_", "tag_"):
            ctr = getattr(self, f"{p}tags_container", None)
            if ctr:
                ctr.configure(height=new_h)
        self._save_settings()

    def _toggle_file_tags(self):
        """折叠/展开所有'当前文件标签'区块"""
        self._file_tags_collapsed = not self._file_tags_collapsed
        self._apply_file_tags_visibility()
        self._save_settings()

    def _apply_file_tags_visibility(self):
        """根据共享折叠状态更新当前可见区块的外观"""
        arrow = "▶" if self._file_tags_collapsed else "▼"
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
            # 折叠时容器缩小到只够放标题，展开时恢复记忆高度
            if ctr:
                if self._file_tags_collapsed:
                    ctr.configure(height=28)
                else:
                    ctr.configure(height=self._file_tags_height)

    def _refresh_file_tags(self):
        """刷新两个页面的'当前文件标签'列表"""
        tags = []
        if self._current_note_path:
            from file_handler import parse_front_matter_tags, DATA_DIR
            filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
            tags = parse_front_matter_tags(filepath)

        for prefix in ("file_", "tag_"):
            lb = getattr(self, f"{prefix}tags_listbox", None)
            if not lb:
                continue
            lb.delete(0, tk.END)
            if not self._current_note_path:
                lb.insert(tk.END, "  未打开文件")
            elif not tags:
                lb.insert(tk.END, "  无标签")
            else:
                for t in tags:
                    lb.insert(tk.END, f"  {t}")
            # 恢复选中状态
            self._sync_file_tag_selection(lb)


    def _add_current_file_tag(self, prefix):
        """为当前文件添加标签"""
        if not self._current_note_path:
            self.status_left.configure(text="   请先打开一篇笔记")
            return
        tag = self._ask_single_line("添加标签", "输入新标签：")
        if not tag:
            return
        tag = tag.replace(",", " ").strip()
        if not tag:
            return
        from file_handler import (parse_front_matter_tags, set_note_tags,
                                  build_tag_index, DATA_DIR)
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        cur = parse_front_matter_tags(filepath)
        if tag in cur:
            self.status_left.configure(text=f"   标签「{tag}」已存在")
            return
        self._apply_tag_change(self._current_note_path, cur + [tag])

    def _remove_selected_file_tag(self, prefix):
        """删除当前文件被选中的标签"""
        if not self._current_note_path:
            self.status_left.configure(text="   请先打开一篇笔记")
            return
        lb = getattr(self, f"{prefix}tags_listbox", None)
        if not lb:
            return
        sel = lb.curselection()
        if not sel:
            self.status_left.configure(
                text="   请先在标签列表选中要删除的标签")
            return
        tag_text = lb.get(sel[0]).strip()
        if tag_text in ("未打开文件", "无标签"):
            return
        from file_handler import (parse_front_matter_tags, DATA_DIR)
        filepath = os.path.join(DATA_DIR, f"{self._current_note_path}.md")
        cur = parse_front_matter_tags(filepath)
        if tag_text not in cur:
            self.status_left.configure(text=f"   标签「{tag_text}」不在文件中")
            return
        new = [t for t in cur if t != tag_text]
        self._apply_tag_change(self._current_note_path, new)

    def _apply_tag_change(self, rel_path, tags):
        """写回标签 → 重建索引 → 刷新两处列表与标签树"""
        from file_handler import set_note_tags, build_tag_index
        new_tags = set_note_tags(rel_path, tags)
        if new_tags is None:
            self.status_left.configure(text="   写入标签失败")
            return
        build_tag_index()
        self._refresh_file_tags()
        self._refresh_tags()
        self._snapshot_files()  # 抑制轮询自触发
        summary = ", ".join(new_tags) if new_tags else "(无标签)"
        self.status_left.configure(text=f"   标签已更新：{summary}")


    def _on_file_tag_dclick(self, event):
        """双击标签 → 跳转标签页定位"""
        lb = event.widget
        sel = lb.curselection()
        if not sel:
            return
        tag_text = lb.get(sel[0]).strip()
        if not tag_text or tag_text in ("未打开文件", "无标签"):
            return

        self._selected_file_tag = tag_text
        for prefix in ("file_", "tag_"):
            other_lb = getattr(self, f"{prefix}tags_listbox", None)
            if other_lb:
                self._sync_file_tag_selection(other_lb)

        if self.current_panel != "tags":
            self._show_tags()
        self._expand_all_tags_section()
        iid = f"tag_{tag_text}"
        if self.tag_tree.exists(iid):
            self.tag_tree.selection_set(iid)
            self.tag_tree.see(iid)
            self.tag_tree.item(iid, open=True)

    def _sync_file_tag_selection(self, lb):
        """同步单个 listbox 的选中状态到 self._selected_file_tag"""
        lb.selection_clear(0, tk.END)
        if self._selected_file_tag:
            items = lb.get(0, tk.END)
            for i, item in enumerate(items):
                if item.strip() == self._selected_file_tag:
                    lb.selection_set(i)
                    break


    def _refresh_tags(self):
        """重建标签树（从 index.json 缓存读取，不重新扫描）"""
        self.tag_tree.delete(*self.tag_tree.get_children())
        self.tag_intersection_label.configure(text="")

        tag_index = get_tag_index()
        if not tag_index:
            self.tag_tree.insert("", "end",
                                 text="  暂无标签",
                                 iid="__notags__")
            self.tag_tree.item("__notags__", tags=())
            return

        search_text = self.tag_search_var.get().strip().lower()
        if search_text == self._tag_search_placeholder.lower():
            search_text = ""
        any_visible = False

        for tag, files in tag_index.items():
            if search_text and search_text not in tag.lower():
                continue
            any_visible = True
            count = len(files)
            iid = f"tag_{tag}"
            display = f" {tag}  ({count})"
            self.tag_tree.insert("", "end", iid=iid, text=display, open=False)

            for fpath in files:
                name = fpath.split("/")[-1]
                fid = f"file_{tag}_{fpath}"
                self.tag_tree.insert(iid, "end", iid=fid,
                                     text=f"  {name}",
                                     values=(fpath,))
                self.tag_tree.item(fid, tags=("file_node",))

        if not any_visible:
            if search_text:
                self.tag_tree.insert("", "end",
                                     text=f"  未找到 \"{search_text}\"",
                                     iid="__noresult__")
                self.tag_tree.item("__noresult__", tags=())
            else:
                self.tag_tree.insert("", "end",
                                     text="  暂无标签",
                                     iid="__notags__")
                self.tag_tree.item("__notags__", tags=())

    def _on_tag_search(self):
        """实时过滤标签列表（忽略占位文字）"""
        if self.tag_search_var.get() == self._tag_search_placeholder:
            return
        self._refresh_tags()

    def _on_tag_search_focus_in(self, event):
        """搜索框获得焦点时清除占位文字"""
        if self.tag_search_entry.get() == self._tag_search_placeholder:
            self.tag_search_entry.delete(0, tk.END)
            self.tag_search_entry.configure(fg=self.colors["search_fg"])

    def _on_tag_search_focus_out(self, event):
        """搜索框失去焦点时若为空则恢复占位文字"""
        if not self.tag_search_var.get().strip():
            self.tag_search_entry.delete(0, tk.END)
            self.tag_search_entry.insert(0, self._tag_search_placeholder)
            ph_color = "#777" if self.theme_mode == "dark" else "#999"
            self.tag_search_entry.configure(fg=ph_color)

    def _on_tag_tree_select(self, event):
        """标签树选中：单标签切换展开，多标签显示交集"""
        sel = self.tag_tree.selection()
        tag_iids = [i for i in sel if i.startswith("tag_")]

        # 点击交集分组或其内部文件时保持交集显示：
        # 否则选中状态变化会被误判为"标签不足 2 个"，刚算出的交集立刻被清掉
        if any(i.startswith(("__intersection__", "__intf_")) for i in sel):
            return

        if len(tag_iids) == 0:
            self.tag_intersection_label.configure(text="")
            self._clear_tag_intersection()
            return

        if len(tag_iids) == 1:
            self.tag_intersection_label.configure(text="")
            self._clear_tag_intersection()
        else:
            self._update_tag_intersection(tag_iids)

    def _on_tag_tree_press(self, event):
        """记录按下前的选中集合与修饰键，供 release 判断本次点击的意图"""
        self._tag_sel_before = [i for i in self.tag_tree.selection()
                                if i.startswith("tag_")]
        # Ctrl=0x0004、Shift=0x0001
        self._tag_press_mods = bool(event.state & (0x0004 | 0x0001))

    def _on_tag_tree_click(self, event):
        """单击标签节点 → 展开/折叠（与多选互不干扰）"""
        iid = self.tag_tree.identify_row(event.y)
        if not iid or not iid.startswith("tag_"):
            return

        # Ctrl / Shift 点击的用意是加选或减选，不应顺带展开或折叠列表
        if getattr(self, "_tag_press_mods", False):
            return

        before = getattr(self, "_tag_sel_before", [])
        # 多选状态下点击其中一个已展开的标签，本意是收起列表：
        # 折叠后恢复原有选中集合，否则选中改动会连带清掉交集结果
        if len(before) >= 2 and iid in before and self.tag_tree.item(iid, "open"):
            self.tag_tree.item(iid, open=False)
            self.tag_tree.selection_set(before)
            self._update_tag_intersection(before)
            return

        # 其余情况：只对单选的标签切换展开
        tag_iids = [i for i in self.tag_tree.selection()
                    if i.startswith("tag_")]
        if len(tag_iids) == 1 and tag_iids[0] == iid:
            self.tag_tree.item(iid,
                               open=not self.tag_tree.item(iid, "open"))

    def _on_tag_tree_double_click(self, event):
        """双击文件节点 → 打开笔记"""
        iid = self.tag_tree.identify_row(event.y)
        if not iid:
            return
        vals = self.tag_tree.item(iid, "values")
        if vals:
            fpath = vals[0]
            self._display_note(fpath)
            # 同步选中文件树节点
            try:
                self.tree.selection_set(f"f:{fpath}")
                self.tree.see(f"f:{fpath}")
            except Exception:
                pass

    def _clear_tag_intersection(self):
        """移除树中的交集分组节点，并清空交集状态"""
        self._tag_intersection = None
        try:
            if self.tag_tree.exists("__intersection__"):
                self.tag_tree.delete("__intersection__")
        except tk.TclError:
            pass

    def _update_tag_intersection(self, tag_iids):
        """多选标签时在树顶部展示交集文件列表（交集由 file_handler 计算）"""
        self._clear_tag_intersection()

        tag_names = [iid[4:] for iid in tag_iids]  # 去掉 "tag_" 前缀
        matched, files = intersect_tags(tag_names)

        if len(matched) < 2:
            self.tag_intersection_label.configure(text="")
            return

        self._tag_intersection = (matched, files)
        tag_str = " ∩ ".join(matched)
        count = len(files)
        if count == 0:
            self.tag_intersection_label.configure(
                text=f"  {tag_str} → 没有共同文件")
            return
        self.tag_intersection_label.configure(
            text=f"  {tag_str} → {count} 个文件"
        )

        # 在标签树顶部插入交集分组，双击文件可打开
        inter_iid = self.tag_tree.insert(
            "", "end", iid="__intersection__", open=True,
            text=f"  {tag_str} ({count})")
        self.tag_tree.item(inter_iid, tags=("tag_",))
        for idx, fpath in enumerate(files):
            name = fpath.split("/")[-1]
            fid = f"__intf_{idx}"
            self.tag_tree.insert(inter_iid, "end", iid=fid,
                                 text=f"  {name}", values=(fpath,))
            self.tag_tree.item(fid, tags=("file_node",))
        self.tag_tree.see(inter_iid)

    def _get_selected_tag_names(self):
        """返回当前选中的标签名列表"""
        sel = self.tag_tree.selection()
        return [i[4:] for i in sel if i.startswith("tag_")]

    def _on_tag_tree_motion(self, event):
        """标签树行鼠标悬停 → 高亮"""
        iid = self.tag_tree.identify_row(event.y)
        prev = getattr(self, '_tag_tree_hover_item', None)
        if prev and prev != iid:
            try:
                self.tag_tree.item(prev, tags=())
            except tk.TclError:
                pass
        if iid and iid.startswith("tag_"):
            self.tag_tree.item(iid, tags=('hover',))
            self._tag_tree_hover_item = iid
        else:
            self._tag_tree_hover_item = None

    def _on_tag_tree_leave(self, event):
        """鼠标离开标签树 → 清除悬停高亮"""
        prev = getattr(self, '_tag_tree_hover_item', None)
        if prev:
            try:
                self.tag_tree.item(prev, tags=())
            except tk.TclError:
                pass
            self._tag_tree_hover_item = None

    # ══════════════════════════════════
    # 内容
