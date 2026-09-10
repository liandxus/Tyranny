"""
IndeXar - 个人知识档案库
入口文件：启动图形界面
"""

import ctypes
import sys

import gui


def _set_app_user_model_id():
    """设置 AppUserModelID：让任务栏把本进程图标关联为应用自身图标。

    必须在任何窗口显示之前调用。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "IndeXar.Application")
    except Exception:
        pass


if __name__ == "__main__":
    if sys.platform == "win32":
        _set_app_user_model_id()
    app = gui.IndeXarApp()
    app.run()
