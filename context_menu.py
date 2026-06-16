"""
自定义右键菜单（Toplevel-based）
"""
import tkinter as tk


class ContextMenu:

    DEFAULTS = {
        "bg": "#e8e8e8",
        "fg": "#333333",
        "activebackground": "#d0d0d0",
        "activeforeground": "#333333",
        "separator": "#d0d0d0",
    }

    def __init__(self, master, colors=None):
        self.master = master
        self._colors = dict(self.DEFAULTS)
        if colors:
            self._colors.update(colors)
        self._window = None
        self._outside_bind_id = None

    def configure(self, **kwargs):
        self._colors.update(kwargs)

    def show(self, x, y, items, colors_override=None, use_grab=True):
        self.dismiss()

        c = dict(self._colors)
        if colors_override:
            c.update(colors_override)

        win = tk.Toplevel(self.master)
        win.overrideredirect(True)
        win.configure(bg=c["bg"], bd=0, highlightthickness=0)
        win.columnconfigure(0, weight=1, minsize=200)

        for i, item in enumerate(items):
            if item is None:
                f = tk.Frame(win, height=1, bg=c["separator"])
                f.grid(row=i, column=0, sticky="ew", padx=16, pady=2)
            else:
                text, command = item
                lbl = tk.Label(
                    win, text=text,
                    font=("Microsoft YaHei", 10),
                    bg=c["bg"], fg=c["fg"],
                    anchor=tk.W,
                    padx=28, pady=6,
                )
                lbl.grid(row=i, column=0, sticky="ew")
                lbl.bind("<Enter>", lambda e, l=lbl, ac=c: l.configure(
                    bg=ac["activebackground"], fg=ac["activeforeground"]))
                lbl.bind("<Leave>", lambda e, l=lbl, ac=c: l.configure(
                    bg=ac["bg"], fg=ac["fg"]))
                lbl.bind("<Button-1>",
                         lambda e, cmd=command: self._execute(cmd))

        self._window = win
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.lift()
        win.focus_set()

        if use_grab:
            win.grab_set()
        else:
            # 无 grab：外部点击通过 root 级绑定检测
            def _dismiss_outside(event):
                if self._window is None:
                    return
                try:
                    wx = self._window.winfo_rootx()
                    wy = self._window.winfo_rooty()
                    ww = self._window.winfo_width()
                    wh = self._window.winfo_height()
                    if not (wx <= event.x_root <= wx + ww and
                            wy <= event.y_root <= wy + wh):
                        self.dismiss()
                except tk.TclError:
                    self.dismiss()
            self._outside_bind_id = self.master.bind(
                "<Button-1>", _dismiss_outside, add="+")

        win.bind("<Escape>", lambda e: self.dismiss())
        win.bind("<Button-1>", self._on_outside)

    def _on_outside(self, event):
        if not self._window:
            return
        try:
            wx = self._window.winfo_rootx()
            wy = self._window.winfo_rooty()
            ww = self._window.winfo_width()
            wh = self._window.winfo_height()
            if not (wx <= event.x_root <= wx + ww and
                    wy <= event.y_root <= wy + wh):
                self.dismiss()
        except tk.TclError:
            self.dismiss()

    def _execute(self, command):
        self.dismiss()
        if callable(command):
            # 延迟执行：等待菜单窗口完全销毁（包括 grab 释放）后再执行命令，
            # 避免新旧 grab 冲突导致界面卡死（如重命名对话框）。
            # after_idle 不够可靠，用 50ms 显式延迟确保清理完成。
            self.master.after(50, command)

    def dismiss(self):
        if self._outside_bind_id is not None:
            try:
                self.master.unbind("<Button-1>", self._outside_bind_id)
            except tk.TclError:
                pass
            self._outside_bind_id = None
        if self._window is not None:
            try:
                self._window.grab_release()
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None

    @property
    def visible(self):
        return self._window is not None
