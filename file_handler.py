import os
import re
import json
import frontmatter

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


def collect_mtimes():
    """返回 {rel_path: mtime}，枚举 data 下所有 .md 的修改时间，
    用于文件监听轮询对比。"""
    result = {}
    for item in _walk(DATA_DIR):
        filepath = os.path.join(DATA_DIR, f"{item['path']}.md")
        try:
            result[item["path"]] = os.path.getmtime(filepath)
        except OSError:
            pass
    return result


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

def parse_note_metadata(filepath):
    """
    使用 python-frontmatter 解析 Markdown 文件的 YAML 元数据。
    返回 (metadata_dict, body_text)，解析失败返回 ({}, '')。
    """
    if not os.path.exists(filepath):
        return {}, ""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        return dict(post.metadata), post.content
    except Exception:
        return {}, ""


def parse_front_matter_tags(filepath):
    """
    从 Markdown 文件的 YAML front matter 中提取标签。
    返回标签列表（字符串列表）。
    """
    metadata, _ = parse_note_metadata(filepath)
    tags = metadata.get("tags", [])
    # 确保 tags 是列表类型
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        return []
    return [str(t) for t in tags if t]


def _yaml_tag(value):
    """把标签序列化为合法的 YAML 标量（含特殊字符时加双引号）"""
    s = str(value)
    if s and s == s.strip() and not re.search(r'[,\[\]{}:#&*!|>%@`"\'\n]', s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_note_tags(rel_path, tags):
    """
    设置笔记 front matter 的 tags 字段。

    只就地替换 tags 字段本身，front matter 中其它字段的顺序与写法保持不变
    （不整体重新序列化，避免改动用户手写的 YAML），并保证文件以换行结尾。
    返回写入后的标签列表；文件不存在或写入失败返回 None。
    """
    filepath = os.path.join(DATA_DIR, f"{rel_path}.md")
    if not os.path.exists(filepath):
        return None

    clean = [str(t).strip() for t in tags if str(t).strip()]
    # 去重但保持顺序
    seen = set()
    clean = [t for t in clean if not (t in seen or seen.add(t))]
    tag_line = "tags: [" + ", ".join(_yaml_tag(t) for t in clean) + "]"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
    except (IOError, OSError):
        return None

    lines = text.split("\n")

    if not lines or lines[0].strip() != "---":
        # 没有 front matter：在文件开头补一个
        new_text = f"---\n{tag_line}\n---\n\n{text.lstrip(chr(10))}"
    else:
        # 定位 front matter 结束行
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            return None

        # 在 front matter 内查找 tags 字段（兼容 `tags: [...]` 与块式 `- x`）
        start = stop = None
        for i in range(1, end):
            if lines[i].strip().startswith("tags:"):
                start = i
                stop = i + 1
                while stop < end and lines[stop].lstrip().startswith("- "):
                    stop += 1
                break

        if start is None:
            new_lines = lines[:end] + [tag_line] + lines[end:]
        else:
            new_lines = lines[:start] + [tag_line] + lines[stop:]
        new_text = "\n".join(new_lines)

    if not new_text.endswith("\n"):
        new_text += "\n"

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_text)
    except (IOError, OSError):
        return None
    return clean


def build_tag_index():
    """
    遍历 data/ 下所有 .md 文件，解析 front matter 的 tags，
    生成 {tag: [rel_path, ...]} 索引并写入 index.json。
    """
    tag_map = {}
    for item in _walk(DATA_DIR):
        filepath = os.path.join(DATA_DIR, f"{item['path']}.md")
        tags = parse_front_matter_tags(filepath)
        # 同一文件内重复标签只记一次，同一路径不重复收录
        for tag in dict.fromkeys(tags):
            paths = tag_map.setdefault(tag, [])
            if item["path"] not in paths:
                paths.append(item["path"])

    # 按文件数量降序排列
    sorted_map = dict(
        sorted(tag_map.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )
    # 读取现有索引，合并写入以保留 backlinks 等字段
    merged = {}
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                merged = json.load(f)
        except Exception:
            pass
    merged["tags"] = sorted_map
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return sorted_map


def load_tag_index():
    """从 index.json 加载标签索引，不存在则返回 None"""
    if not os.path.exists(INDEX_FILE):
        return None
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧格式（裸 JSON）和新格式（{"tags": {...}})
        return data.get("tags", data)
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


def intersect_tags(tag_names, tag_index=None):
    """
    求同时包含全部指定标签的笔记（标签聚合模块的交集运算）。

    参数:
        tag_names: 标签名列表
        tag_index: 可选，标签索引；缺省时自动加载

    返回 (matched_names, files):
        matched_names —— 实际参与求交的标签名（已排序）
        files         —— 同时含这些标签的笔记路径（已排序）；
                         有效标签不足 2 个时为空列表
    """
    if tag_index is None:
        tag_index = get_tag_index() or {}

    sets = []
    matched = []
    for name in (tag_names or []):
        if name in tag_index:
            sets.append(set(tag_index[name] or []))
            matched.append(name)

    if len(sets) < 2:
        return sorted(matched), []

    return sorted(matched), sorted(set.intersection(*sets))


# ══════════════════════════════════
# 反向链接系统
# ══════════════════════════════════

def parse_wikilinks(content):
    """从笔记正文中提取 [[目标]] 链接的目标名列表

    同一目标在单篇笔记中被重复引用时只记一次（保持首次出现的顺序），
    这样反向链接索引里每个来源笔记只会出现一条。
    """
    links = []
    seen = set()
    for m in re.finditer(r'\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]', content):
        target = m.group(1).strip().replace(".md", "")
        if target and target not in seen:
            seen.add(target)
            links.append(target)
    return links


def build_backlink_index():
    """
    扫描 data/ 下所有 .md 文件，构建反向链接索引并写入 index.json。
    返回 {被引用笔记名: [引用者路径, ...]}
    """
    backlinks = {}
    for item in _walk(DATA_DIR):
        filepath = os.path.join(DATA_DIR, f"{item['path']}.md")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        # 跳过 YAML front matter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:]
        for target in parse_wikilinks(content):
            refs = backlinks.setdefault(target, [])
            # 同一引用者只记录一次（防御路径重复/大小写差异）
            if item["path"] not in refs:
                refs.append(item["path"])

    # 合并写入 index.json，不覆盖 tags
    merged = {}
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                merged = json.load(f)
        except Exception:
            pass
    merged["backlinks"] = backlinks
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return backlinks


def get_backlinks(note_name):
    """
    获取指定笔记的反向链接列表。
    note_name: 笔记显示名（如 "README"），不含路径和 .md 后缀
    """
    if not os.path.exists(INDEX_FILE):
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        refs = data.get("backlinks", {}).get(note_name, [])
        # 防御性去重：兼容历史 index.json 中残留的重复条目
        return list(dict.fromkeys(refs))
    except Exception:
        return []
