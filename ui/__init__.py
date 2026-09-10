"""
IndeXar 界面层

各面板以 Mixin 形式拆分，由 gui.IndeXarApp 组合成一个完整主窗口。
Mixin 之间通过 self 共享控件引用与状态，避免交叉导入。
"""
