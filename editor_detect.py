"""
IndeXar 编辑器检测模块
自动检测系统中已安装的 Markdown 编辑器路径

检测优先级（命中即停）：
    1. 注册表 App Paths —— 该项默认值就是 exe 完整路径，最可靠，
       且能覆盖装在非标准位置（如 D:\\tools）的程序
    2. 常见安装路径
    3. 注册表 Uninstall —— 同时匹配子键名与 DisplayName
"""

import os
import winreg

# 应用检测配置：(显示名, [可能的 exe 名], [常见安装路径])
_APP_SPECS = [
    ("Typora", ["Typora.exe"], [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Typora\Typora.exe"),
        r"C:\Program Files\Typora\Typora.exe",
    ]),
    ("VS Code", ["Code.exe"], [
        os.path.expandvars(
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ]),
    ("Notepad++", ["notepad++.exe"], [
        r"C:\Program Files\Notepad++\notepad++.exe",
        os.path.expandvars(r"%ProgramFiles(x86)%\Notepad++\notepad++.exe"),
    ]),
]

# 卸载/辅助程序关键字：在目录中挑选主程序时应跳过
_JUNK_EXE_HINTS = ("unins", "uninstall", "setup", "update", "crash",
                   "report", "activation", "卸载")


def detect_editors():
    """
    返回可用编辑器字典 {显示名: 完整路径}。

    三方编辑器按以下顺序检测（命中即停）：
        注册表 App Paths → 常见安装路径 → 注册表 Uninstall
    之后无条件加入系统记事本，使返回值至少含一项。
    """
    editors = {}

    for name, exes, candidates in _APP_SPECS:
        path = _find_in_app_paths(exes)
        if not path:
            path = next((c for c in candidates if os.path.exists(c)), None)
        if not path:
            path = _find_in_registry(name, prefer_names=exes)
        if path:
            editors[name] = path

    # ── 系统记事本：不参与检测，直接计入候选，保证列表非空 ──
    notepad = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32",
                           "notepad.exe")
    if os.path.exists(notepad):
        editors["记事本"] = notepad

    return editors


def _find_in_app_paths(exe_names):
    """在注册表 App Paths 中查找程序：该项默认值即 exe 完整路径"""
    if isinstance(exe_names, str):
        exe_names = [exe_names]
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for exe in exe_names:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, f"{sub}\\{exe}") as key:
                    val = winreg.QueryValueEx(key, "")[0]
            except OSError:
                continue
            val = str(val or "").strip().strip('"')
            if val and os.path.exists(val):
                return val
    return None


def _find_in_registry(app_name, prefer_names=()):
    """在注册表 Uninstall 中查找应用主程序

    同时匹配子键名与 DisplayName —— Inno Setup 常以 GUID 命名子键，
    只比对键名会漏检（例如 Typora 的键名形如 {xxxxxxxx-xxxx-...}_is1）。
    """
    needle = app_name.lower()
    reg_paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for reg_path in reg_paths:
            try:
                with winreg.OpenKey(root_key, reg_path) as key:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(key, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(key, sub) as sk:
                                try:
                                    display = winreg.QueryValueEx(
                                        sk, "DisplayName")[0]
                                except OSError:
                                    display = ""
                                if (needle not in sub.lower()
                                        and needle not in str(display).lower()):
                                    continue
                                # 依次尝试从安装位置/图标/卸载命令反推主程序
                                for value_name in ("InstallLocation",
                                                   "DisplayIcon",
                                                   "UninstallString"):
                                    try:
                                        raw = winreg.QueryValueEx(
                                            sk, value_name)[0]
                                    except OSError:
                                        continue
                                    exe = _exe_from_value(raw, prefer_names)
                                    if exe:
                                        return exe
                        except OSError:
                            continue
            except OSError:
                continue
    return None


def _exe_from_value(raw, prefer_names=()):
    """从注册表取值中解析出存在的 exe（兼容 DisplayIcon 的 "路径,0" 形式）"""
    if not raw:
        return None
    raw = str(raw).split(",")[0].strip().strip('"')
    if raw.lower().endswith(".exe") and os.path.exists(raw):
        return raw
    directory = raw if os.path.isdir(raw) else os.path.dirname(raw)
    return _find_exe_in_dir(directory, prefer_names)


def _find_exe_in_dir(directory, prefer_names=()):
    """在目录下查找主程序 exe：优先匹配指定名称，跳过卸载/更新程序"""
    if not os.path.isdir(directory):
        return None
    exes = [f for f in os.listdir(directory) if f.lower().endswith(".exe")]
    if not exes:
        return None
    for want in prefer_names:
        for f in exes:
            if f.lower() == str(want).lower():
                return os.path.join(directory, f)
    for f in exes:
        if not any(h in f.lower() for h in _JUNK_EXE_HINTS):
            return os.path.join(directory, f)
    return os.path.join(directory, exes[0])
