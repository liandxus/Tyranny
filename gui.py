"""
引入核心 tkinter import ttk
"""
import tkinter as tk
from tkinter import ttk


# 主要窗口结构
root  = tk.Tk()
root.title("IndeXar")
root.geometry("1200x800")

# 左右布局

# 主容器
paned_window = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
paned_window.pack(fill=tk.BOTH, expand=True)

# 左侧面板
left_frame = ttk.Frame(paned_window)
paned_window.add(left_frame, weight=1)

# 右侧面板




# 启动事件循环
root.mainloop()
