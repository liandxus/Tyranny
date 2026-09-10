"""
IndeXar 搜索交互

关键词搜索的结果渲染（文件树分组）、片段跳转与高亮、
命中计数与片段提取（依赖已渲染的 Text 控件，故留在界面层）。
"""

import tkinter as tk

import search_engine
from ui.common import _blend_hex, _readable_fg, SEARCH_HIT_ALPHA, \
    SEARCH_HIT_COLOR


class SearchMixin:
    """搜索框交互与结果渲染"""

    def _jump_to_search_match(self, idx):
        """在已渲染内容中查找第 idx 个关键词并滚动选中"""
        kw = getattr(self, '_cur_keyword', '')
        if not kw:
            return
        count = 0
        pos = "1.0"
        self.content_text.configure(state=tk.NORMAL)
        while True:
            pos = self.content_text.search(kw, pos, nocase=True,
                                           stopindex=tk.END)
            if not pos:
                break
            if count == idx:
                line = int(pos.split(".")[0])
                total = int(self.content_text.index("end-1c").split(".")[0])
                frac = (line - 1) / max(total, 1)
                self.content_text.yview_moveto(frac)
                end = f"{pos}+{len(kw)}c"
                # 使用自定义 tag 而非 tk.SEL：后者依赖控件焦点，
                # 失焦时选中高亮不会显示，故用自定义 tag；
                # 基色按 alpha 与内容区背景混合，等效半透明且自适应主题
                base_bg = self.content_text.cget("bg")
                hit_bg = _blend_hex(SEARCH_HIT_COLOR, base_bg,
                                    SEARCH_HIT_ALPHA)
                self.content_text.tag_configure(
                    "search_hit", background=hit_bg,
                    foreground=_readable_fg(hit_bg))
                self.content_text.tag_remove("search_hit", "1.0", tk.END)
                self.content_text.tag_add("search_hit", pos, end)
                self.content_text.see(pos)
                self.content_text.configure(state=tk.DISABLED)
                return
            count += 1
            pos = f"{pos}+1c"
        # 未命中（索引越界）：清除上一次的高亮，避免残留
        self.content_text.tag_remove("search_hit", "1.0", tk.END)
        self.content_text.configure(state=tk.DISABLED)

    # ══════════════════════════════════
    # 标签


    def _on_search_var_changed(self):
        """搜索框内容变化：有输入才显示清空按钮；清空则清空搜索结果"""
        try:
            if self.search_var.get().strip():
                self.search_clear_lbl.pack(side=tk.RIGHT, padx=(0, 2),
                                           after=self.search_btn)
            else:
                self.search_clear_lbl.pack_forget()
                self._refresh_search_results()
        except Exception:
            pass

    def _clear_search(self):
        """清空搜索框与结果，焦点回到输入框"""
        self.search_var.set("")
        try:
            if self.current_panel == "search":
                self.panel_search_entry.focus_set()
            else:
                self.search_entry.focus_set()
        except tk.TclError:
            pass

    def _do_search(self):
        keyword = self.search_var.get().strip()
        keyword_lower = keyword.lower()
        if not keyword:
            return

        if self.current_panel != "search":
            self._show_search()
        for item in self.search_tree.get_children():
            self.search_tree.delete(item)

        cur = self._current_note_path
        # 全库遍历匹配由 search_engine 负责
        name_matches, content_matches, cur_content_hit = \
            search_engine.search_notes(keyword, cur)
        # 命中数需在已渲染内容中统计，仍由 GUI 处理
        cur_hit_count = (self._count_matches(keyword_lower)
                         if (cur and cur_content_hit) else 0)

        total = len(name_matches) + len(content_matches)
        if total == 0 and cur_hit_count == 0:
            self.search_tree.insert("", "end", text=f"  未找到 \"{keyword}\"")
            self._set_content(f"未找到包含 \"{keyword}\" 的笔记。")
            self.status_left.configure(text="   未找到结果")
            return

        total += cur_hit_count
        self.search_tree.insert("", "end",
            text=f"  搜索结果 \"{keyword}\" ({total})",
            values=("__header__",), open=True)

        # ① 当前文件
        if cur_hit_count > 0 and cur:
            piid = self.search_tree.insert("", "end",
                text=f"  当前文件 ({cur_hit_count})", open=True,
                values=("__header__",))
            # 提取每个匹配位的小段摘要
            snippets = self._extract_text_snippets(keyword_lower)
            for i, snip_text in enumerate(snippets[:cur_hit_count]):
                self.search_tree.insert(piid, "end",
                    text=f"[{i+1}] {snip_text}",
                    values=(f"__snippet_{i}",))
            if cur in name_matches:
                name_matches.remove(cur)
            if cur in content_matches:
                content_matches.remove(cur)

        # ② 文件名匹配
        if name_matches:
            piid = self.search_tree.insert("", "end",
                text=f"  文件名匹配 ({len(name_matches)})", open=True,
                values=("__header__",))
            for p in name_matches:
                self.search_tree.insert(piid, "end", text=p.split("/")[-1],
                    values=(p, False))

        # ③ 内容匹配
        if content_matches:
            piid = self.search_tree.insert("", "end",
                text=f"  内容匹配 ({len(content_matches)})", open=True,
                values=("__header__",))
            for p in content_matches:
                self.search_tree.insert(piid, "end", text=p.split("/")[-1],
                    values=(p, False))

        self._cur_keyword = keyword_lower
        self._cur_hit_count = cur_hit_count
        self.status_left.configure(text=f"   结果 {total}")

    def _count_matches(self, keyword):
        """统计已渲染内容中关键词出现次数"""
        count = 0
        pos = "1.0"
        while True:
            pos = self.content_text.search(keyword, pos, nocase=True,
                                           stopindex=tk.END)
            if not pos:
                break
            count += 1
            pos = f"{pos}+1c"
        return count

    def _extract_text_snippets(self, keyword, max_count=10):
        """从已渲染内容中提取关键词短片段（前后各6字 + 省略号）"""
        results = []
        pos = "1.0"
        ctx = 6
        while True:
            pos = self.content_text.search(keyword, pos, nocase=True,
                                           stopindex=tk.END)
            if not pos:
                break
            # 提取前后各 ctx 字符
            start = f"{pos}-{ctx}c"
            end = f"{pos}+{len(keyword)+ctx}c"
            s = self.content_text.get(start, end).replace("\n", " ").strip()
            # 添加省略号
            if self.content_text.compare(start, ">", "1.0"):
                s = "..." + s
            if self.content_text.compare(end, "<", "end-1c"):
                s = s + "..."
            if s not in results:
                results.append(s)
            pos = f"{pos}+1c"
            if len(results) >= max_count:
                break
        return results

    # ══════════════════════════════════
    # 视图菜单
