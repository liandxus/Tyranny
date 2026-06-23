"""
IndeXar 编辑器检测模块
自动检测系统中已安装的 Markdown 编辑器路径
"""

import os
import winreg


def detect_editors():
    """
    返回已安装编辑器字典 {显示名: 完整路径}。
    检测顺序：常见安装路径 → 注册表
    """
    editors = {}

    # ── Typora ──
    for p in [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Typora\Typora.exe"),
        r"C:\Program Files\Typora\Typora.exe",
    ]:
        if os.path.exists(p):
            editors["Typora"] = p
            break
    if "Typora" not in editors:
        p = _find_in_registry("Typora")
        if p:
            editors["Typora"] = p

    # ── VS Code ──
    for p in [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ]:
        if os.path.exists(p):
            editors["VS Code"] = p
            break
    if "VS Code" not in editors:
        p = _find_in_registry("Microsoft VS Code")
        if p:
            editors["VS Code"] = p

    # ── Notepad++ ──
    for p in [
        r"C:\Program Files\Notepad++\notepad++.exe",
        os.path.expandvars(r"%ProgramFiles(x86)%\Notepad++\notepad++.exe"),
    ]:
        if os.path.exists(p):
            editors["Notepad++"] = p
            break

    # ── 系统记事本（兜底） ──
    notepad = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32",
                           "notepad.exe")
    if os.path.exists(notepad):
        editors["记事本"] = notepad

    return editors


def _find_in_registry(app_name):
    """在注册表 Uninstall 中查找应用安装目录下的主程序"""
    for root_key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        for reg_path in [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]:
            try:
                with winreg.OpenKey(root_key, reg_path) as key:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(key, i)
                            if app_name.lower() in sub.lower():
                                with winreg.OpenKey(key, sub) as sk:
                                    try:
                                        loc = winreg.QueryValueEx(
                                            sk, "InstallLocation")[0]
                                        exe = _find_exe_in_dir(loc)
                                        if exe:
                                            return exe
                                    except OSError:
                                        pass
                            i += 1
                        except OSError:
                            break
            except OSError:
                pass
    return None


def _find_exe_in_dir(directory):
    """在目录下查找第一个 .exe 文件"""
    if not os.path.isdir(directory):
        return None
    for f in os.listdir(directory):
        if f.lower().endswith(".exe"):
            return os.path.join(directory, f)
    return None
