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

    def _note_body_range(self):
        """笔记正文在 Text 中的范围（不含反向链接框）。

        搜索按「文件原文」匹配，而高亮/计数/片段提取都在渲染后的 Text 里
        做。反向链接框（「被以下笔记引用」+ 可跳转的文件名）是程序生成的
        UI 文本，不是笔记内容——若不排除，会出现「搜 test 时命中了几个
        test，但文件里根本没有」的假命中。故以反向链接框起点 bl_top 作为
        正文结尾；无反向链接时退回全文。"""
        try:
            ranges = self.content_text.tag_ranges("bl_top")
        except tk.TclError:
            return "1.0", tk.END
        if ranges:
            return "1.0", str(ranges[0])
        return "1.0", tk.END

    def _jump_to_search_match(self, idx):
        """在已渲染的正文中查找第 idx 个关键词并滚动选中"""
        kw = getattr(self, '_cur_keyword', '')
        if not kw:
            return
        count = 0
        pos = "1.0"
        _, body_end = self._note_body_range()
        self.content_text.configure(state=tk.NORMAL)
        while True:
            pos = self.content_text.search(kw, pos, nocase=True,
                                           stopindex=body_end)
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

        # 命中文件数按「去重后的文件」统计：同一篇笔记可能同时命中
        # 文件名和正文（如 test3.md），两组相加会把同一篇算两次
        hit_files = set(name_matches) | set(content_matches)
        if cur and cur_hit_count:
            # 当前文件单独成组展示（片段列表），不计入上面的文件数
            hit_files.discard(cur)
        total = len(hit_files) + cur_hit_count
        if total == 0:
            # 只在搜索面板与状态栏提示，不改动内容区——当前笔记视图保持原样
            self.search_tree.insert("", "end", text=f"  未找到 \"{keyword}\"")
            self.status_left.configure(text=f"   未找到 \"{keyword}\"")
            return

        self.search_tree.insert("", "end",
            text=f"  搜索结果 \"{keyword}\" ({total})",
            values=("__header__",), open=True)

        # ① 当前文件
        if cur_hit_count > 0 and cur:
            piid = self.search_tree.insert("", "end",
                text=f"  当前文件 ({cur_hit_count})", open=True,
                values=("__header__",))
            # 提取每个匹配位的小段摘要：(出现序号, 文本)
            snippets = self._extract_text_snippets(keyword_lower)
            for idx, snip_text in snippets:
                self.search_tree.insert(piid, "end",
                    text=f"[{idx+1}] {snip_text}",
                    values=(f"__snippet_{idx}",))
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

    def _highlight_current_keyword(self):
        """为当前笔记正文中所有关键词命中加高亮标注。

        从搜索结果打开笔记时调用，使论文与帮助中描述的
        「点击结果后搜索词高亮」成立。"""
        kw = getattr(self, "_cur_keyword", "")
        if not kw:
            return
        start, body_end = self._note_body_range()
        try:
            self.content_text.configure(state=tk.NORMAL)
            base_bg = self.content_text.cget("bg")
            hit_bg = _blend_hex(SEARCH_HIT_COLOR, base_bg, SEARCH_HIT_ALPHA)
            self.content_text.tag_configure(
                "search_hit", background=hit_bg,
                foreground=_readable_fg(hit_bg))
            self.content_text.tag_remove("search_hit", "1.0", tk.END)
            pos = start
            while True:
                pos = self.content_text.search(kw, pos, nocase=True,
                                               stopindex=body_end)
                if not pos:
                    break
                end = f"{pos}+{len(kw)}c"
                self.content_text.tag_add("search_hit", pos, end)
                pos = f"{pos}+1c"
        except tk.TclError:
            pass
        finally:
            self.content_text.configure(state=tk.DISABLED)

    def _count_matches(self, keyword):
        """统计已渲染正文中关键词出现次数（不含反向链接框）"""
        count = 0
        pos, body_end = self._note_body_range()
        while True:
            pos = self.content_text.search(keyword, pos, nocase=True,
                                           stopindex=body_end)
            if not pos:
                break
            count += 1
            pos = f"{pos}+1c"
        return count

    def _extract_text_snippets(self, keyword, max_count=10):
        """从已渲染内容中提取关键词短片段（前后各6字 + 省略号）。

        返回 (出现序号, 文本) 列表：序号是关键词在正文中第几次出现，
        供 __snippet_N 精确定位。相同摘要去重但保留首次出现的序号，
        避免去重后列表序号与正文出现序号错位（点 [2] 跳到第 3 个）。"""
        results = []
        seen = set()
        pos, body_end = self._note_body_range()
        ctx = 6
        count = 0
        while True:
            pos = self.content_text.search(keyword, pos, nocase=True,
                                           stopindex=body_end)
            if not pos:
                break
            # 提取前后各 ctx 字符
            start = f"{pos}-{ctx}c"
            end = f"{pos}+{len(keyword)+ctx}c"
            s = self.content_text.get(start, end).replace("\n", " ").strip()
            # 添加省略号（末尾判断以正文结尾为准，不含反向链接框）
            tail = "end-1c" if body_end == tk.END else body_end
            if self.content_text.compare(start, ">", "1.0"):
                s = "..." + s
            if self.content_text.compare(end, "<", tail):
                s = s + "..."
            if s not in seen:
                seen.add(s)
                results.append((count, s))
            count += 1
            if len(results) >= max_count:
                break
        return results

    # ══════════════════════════════════
    # 视图菜单
