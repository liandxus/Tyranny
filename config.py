"""
IndeXar 配置管理模块

负责 settings.json 的读取、写入、默认值与类型校验。
本模块只处理数据，不涉及任何界面操作（应用配置到控件由 GUI 负责）。
"""

import json
import os

# 配置文件路径（项目根目录下）
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "settings.json")

# 默认配置：文件缺失或字段缺失时使用
DEFAULTS = {
    "font_size": 11,
    "theme_mode": "light",
    "follow_system_theme": False,
    "sidebar_width": 240,
    "file_tags_collapsed": False,
    "file_tags_height": 88,
    "editor_path": "notepad.exe",
    "image_mode": "fit",
}

# 类型校验器：读取时按此转换，转换失败则保留默认值
_CONVERTERS = {
    "font_size": int,
    "theme_mode": str,
    "follow_system_theme": bool,
    "sidebar_width": int,
    "file_tags_collapsed": bool,
    "file_tags_height": int,
    "editor_path": str,
    "image_mode": str,
}

_VALID_THEMES = ("light", "dark")
_VALID_IMAGE_MODES = ("fit", "original")


def load():
    """
    读取配置，返回包含全部字段的字典。

    文件不存在、内容损坏或单个字段非法时，对应字段回退到默认值，
    保证调用方拿到的字典始终是完整的。
    """
    data = dict(DEFAULTS)
    if not os.path.exists(SETTINGS_FILE):
        return data
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, IOError, ValueError, OSError):
        return data
    if not isinstance(raw, dict):
        return data

    for key, conv in _CONVERTERS.items():
        if key in raw:
            try:
                data[key] = conv(raw[key])
            except (TypeError, ValueError):
                pass  # 单个字段非法时保留默认值

    if data["theme_mode"] not in _VALID_THEMES:
        data["theme_mode"] = DEFAULTS["theme_mode"]
    if data["image_mode"] not in _VALID_IMAGE_MODES:
        data["image_mode"] = DEFAULTS["image_mode"]
    return data


def save(data):
    """
    写入配置。只保存已知字段，缺失的用默认值补齐。
    返回是否写入成功。
    """
    out = {key: data.get(key, DEFAULTS[key]) for key in DEFAULTS}
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False
