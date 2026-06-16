import os
import re
import json

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INDEX_FILE = os.path.join(os.path.dirname(__file__), "index.json")


def list_notes():
    """
    返回 data 下所有 .md 文件的相对路径（扁平列表）
    示例: ["README", "World_Archive/01_World_Overview/01_World_Overview", ...]
    """
    return [item["path"] for item in _walk(DATA_DIR)]


def list_notes_tree():
    """
    返回树状结构，用于填充 Treeview
    每项: {"name": str, "path": str, "is_dir": bool, "children": [递归]}
    """
    return _build_tree(DATA_DIR)


NOTE_NAME_MAP = None  # 懒加载：{显示名: 相对路径}


def _build_name_map():
    """构建笔记名 → 相对路径的映射"""
    mapping = {}
    for item in _walk(DATA_DIR):
        mapping[item["name"]] = item["path"]
    return mapping


def find_note_by_name(name):
    """
    通过笔记显示名（不含路径和后缀）查找完整相对路径
    例: find_note_by_name("Dark Elves") → "World_Archive/03_Elven_Realms/05_Dark_Elves"
    """
    global NOTE_NAME_MAP
    if NOTE_NAME_MAP is None:
        NOTE_NAME_MAP = _build_name_map()
    return NOTE_NAME_MAP.get(name)


def read_note(rel_path):
    """
    根据相对路径读取 .md 文件
    rel_path: "README" 或 "World_Archive/01_World_Overview/01_World_Overview"
    注意：不含 .md 后缀
    """
    rel_path = rel_path.replace("\\", "/")
    filepath = os.path.join(DATA_DIR, f"{rel_path}.md")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ── 内部函数 ──

def _walk(base_dir, prefix=""):
    """递归遍历，返回扁平文件列表"""
    items = []
    if not os.path.exists(base_dir):
        return items
    try:
        entries = sorted(os.listdir(base_dir))
    except PermissionError:
        return items
    for entry in entries:
        full = os.path.join(base_dir, entry)
        rel = os.path.join(prefix, entry).replace("\\", "/") if prefix else entry
        if os.path.isdir(full):
            items.extend(_walk(full, rel))
        elif entry.endswith(".md"):
            name = os.path.splitext(entry)[0]
            file_rel = os.path.join(prefix, name).replace("\\", "/") if prefix else name
            items.append({"name": name, "path": file_rel, "is_dir": False})
    return items


def get_data_subdirs():
    """返回 data/ 下的一级子目录名列表（不含 '.' 开头）"""
    if not os.path.exists(DATA_DIR):
        return []
    return sorted([
        d for d in os.listdir(DATA_DIR)
        if os.path.isdir(os.path.join(DATA_DIR, d))
        and not d.startswith(".")
    ])


def get_all_subdirs():
    """返回 data/ 下所有子目录的路径（递归，相对路径）"""
    if not os.path.exists(DATA_DIR):
        return []
    result = []
    for root, dirs, _ in os.walk(DATA_DIR):
        for d in sorted(dirs):
            full = os.path.join(root, d)
            rel = os.path.relpath(full, DATA_DIR).replace("\\", "/")
            result.append(rel)
    return result


def create_note(title, subdir=""):
    """
    创建新笔记，返回相对路径（不含 .md）或 None
    title: 笔记标题（用作文件名 + 标题栏）
    subdir: 子目录名（空 = data 根目录）
    """
    import datetime
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    # 生成文件名：将标题中的非法字符替换为下划线
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", title.strip())
    safe_name = safe_name.replace(" ", "_") if safe_name else "untitled"

    target_dir = os.path.join(DATA_DIR, subdir) if subdir else DATA_DIR
    os.makedirs(target_dir, exist_ok=True)

    # 避免重名
    filepath = os.path.join(target_dir, f"{safe_name}.md")
    counter = 1
    while os.path.exists(filepath):
        filepath = os.path.join(target_dir, f"{safe_name}_{counter}.md")
        counter += 1

    rel_path = os.path.join(subdir, os.path.splitext(os.path.basename(filepath))[0])
    rel_path = rel_path.replace("\\", "/").lstrip("/")

    # YAML 模板
    template = f"""---
title: {title}
date: {date_str}
tags: []
---

# {title}


"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(template.lstrip())

    # 清除名称缓存，使新笔记可被 find_note_by_name 查找
    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None

    return rel_path


def rename_note(rel_path, new_title):
    """
    重命名笔记
    rel_path: 当前相对路径（不含 .md）
    new_title: 新标题（不含路径和后缀）
    返回新相对路径，或 None（失败）
    """
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", new_title.strip())
    safe_name = safe_name.replace(" ", "_") if safe_name else "untitled"

    old_full = os.path.join(DATA_DIR, f"{rel_path}.md")
    if not os.path.exists(old_full):
        return None

    # 计算新路径
    parent = os.path.dirname(rel_path)
    new_rel = os.path.join(parent, safe_name).replace("\\", "/").lstrip("/")
    new_full = os.path.join(DATA_DIR, f"{new_rel}.md")

    # 避免重名
    counter = 1
    while os.path.exists(new_full):
        new_rel = os.path.join(parent, f"{safe_name}_{counter}").replace("\\", "/").lstrip("/")
        new_full = os.path.join(DATA_DIR, f"{new_rel}.md")
        counter += 1

    os.rename(old_full, new_full)
    return new_rel


def delete_note(rel_path):
    """删除笔记文件，返回是否成功"""
    full = os.path.join(DATA_DIR, f"{rel_path}.md")
    if os.path.exists(full):
        os.remove(full)
        global NOTE_NAME_MAP
        NOTE_NAME_MAP = None
        return True
    return False


def delete_folder(rel_path):
    """删除文件夹及其所有内容，返回是否成功"""
    full = os.path.join(DATA_DIR, rel_path)
    if os.path.exists(full) and os.path.isdir(full):
        import shutil
        shutil.rmtree(full)
        global NOTE_NAME_MAP
        NOTE_NAME_MAP = None
        return True
    return False


def rename_folder(rel_path, new_name):
    """
    重命名文件夹，返回新相对路径，或 None（失败）
    """
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", new_name.strip())
    safe_name = safe_name.replace(" ", "_") if safe_name else "new_folder"
    old_full = os.path.join(DATA_DIR, rel_path)
    if not os.path.exists(old_full) or not os.path.isdir(old_full):
        return None
    parent = os.path.dirname(rel_path)
    new_rel = os.path.join(parent, safe_name).replace("\\", "/").lstrip("/")
    new_full = os.path.join(DATA_DIR, new_rel)
    # 避免重名
    counter = 1
    while os.path.exists(new_full):
        new_rel = os.path.join(parent, f"{safe_name}_{counter}").replace("\\", "/").lstrip("/")
        new_full = os.path.join(DATA_DIR, new_rel)
        counter += 1
    os.rename(old_full, new_full)
    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None
    return new_rel


def make_subdir(parent_rel, dir_name):
    """在 data/ 下创建子目录"""
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", dir_name.strip())
    safe_name = safe_name.replace(" ", "_") if safe_name else "new_folder"
    target = os.path.join(DATA_DIR, parent_rel, safe_name)
    os.makedirs(target, exist_ok=True)
    return safe_name


def _build_tree(base_dir, prefix=""):
    """递归构建树结构"""
    items = []
    if not os.path.exists(base_dir):
        return items
    try:
        entries = sorted(os.listdir(base_dir))
    except PermissionError:
        return items
    # 文件夹排前，文件排后，各自按字母序
    dirs = [e for e in entries if os.path.isdir(os.path.join(base_dir, e))]
    files = [e for e in entries if not os.path.isdir(os.path.join(base_dir, e))]
    for entry in dirs + files:
        full = os.path.join(base_dir, entry)
        rel = os.path.join(prefix, entry).replace("\\", "/") if prefix else entry
        if os.path.isdir(full):
            children = _build_tree(full, rel)
            items.append({
                "name": entry,
                "path": rel,
                "is_dir": True,
                "children": children,
            })
        elif entry.endswith(".md"):
            name = os.path.splitext(entry)[0]
            file_rel = os.path.join(prefix, name).replace("\\", "/") if prefix else name
            items.append({
                "name": name,
                "path": file_rel,
                "is_dir": False,
                "children": [],
            })
    return items


# ══════════════════════════════════
# 标签系统
# ══════════════════════════════════

def parse_front_matter_tags(filepath):
    """
    从 Markdown 文件的 YAML front matter 中提取标签。
    支持两种格式：
      tags: [标签1, 标签2, 标签3]
      tags:
        - 标签1
        - 标签2
    返回标签列表（字符串列表）
    """
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.startswith("---"):
        return []
    end = content.find("---", 3)
    if end == -1:
        return []
    front_matter = content[3:end]

    # 格式1: tags: [tag1, tag2, tag3]
    m = re.search(r'^tags:\s*\[(.+?)\]', front_matter, re.MULTILINE)
    if m:
        raw = m.group(1)
        tags = [t.strip().strip('"\'') for t in raw.split(",")]
        return [t for t in tags if t]

    # 格式2: tags:\n  - tag1\n  - tag2
    m = re.search(r'^tags:\s*$', front_matter, re.MULTILINE)
    if m:
        start = m.end()
        tags = []
        for line in front_matter[start:].split("\n"):
            stripped = line.strip()
            if stripped.startswith("- "):
                tag = stripped[2:].strip().strip('"\'')
                if tag:
                    tags.append(tag)
            elif stripped and not stripped.startswith("-"):
                break  # 遇到其他字段停止
        return tags
    return []


def build_tag_index():
    """
    遍历 data/ 下所有 .md 文件，解析 front matter 的 tags，
    生成 {tag: [rel_path, ...]} 索引并写入 index.json。
    """
    tag_map = {}
    for item in _walk(DATA_DIR):
        filepath = os.path.join(DATA_DIR, f"{item['path']}.md")
        tags = parse_front_matter_tags(filepath)
        for tag in tags:
            tag_map.setdefault(tag, []).append(item["path"])

    # 按文件数量降序排列
    sorted_map = dict(
        sorted(tag_map.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_map, f, ensure_ascii=False, indent=2)
    return sorted_map


def load_tag_index():
    """从 index.json 加载标签索引，不存在则返回 None"""
    if not os.path.exists(INDEX_FILE):
        return None
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_tag_index(force_rebuild=False):
    """
    获取标签索引。
    force_rebuild=True 时重建；否则优先读缓存。
    """
    if force_rebuild:
        return build_tag_index()
    cached = load_tag_index()
    if cached is not None:
        return cached
    return build_tag_index()
