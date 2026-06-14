import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


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
