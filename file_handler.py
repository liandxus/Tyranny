import os
import re
import json
import shutil
import sys
import time
import codecs
import frontmatter

# 打包（PyInstaller）后用户数据应跟随 exe 所在目录，而非临时解压目录
if getattr(sys, "frozen", False):
    APP_ROOT = os.path.dirname(sys.executable)
else:
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(APP_ROOT, "data")
INDEX_FILE = os.path.join(APP_ROOT, "index.json")
# 回收站目录（以 . 开头，不参与笔记枚举与文件树展示）
TRASH_DIR = os.path.join(DATA_DIR, ".trash")

# 首次运行（打包后 data/ 不随 exe 分发）时自动创建
os.makedirs(DATA_DIR, exist_ok=True)

# 各笔记最近一次读取时识别出的编码：{相对路径: (编码, 是否严格解码成功)}
NOTE_ENCODINGS = {}

# 编码的中文名称（用于状态栏提示）
_ENCODING_LABELS = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8（含 BOM）",
    "gb18030": "GB18030",
    "utf-16": "UTF-16",
    "utf-32": "UTF-32",
    "unknown": "未知编码",
}

# BOM 检测顺序：UTF-32 的前缀包含 UTF-16 的前缀，故必须先判 UTF-32
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _decode_text(raw):
    """把笔记文件的字节解码为文本。

    顺序为：BOM → UTF-8 → GB18030（GBK/GB2312 的超集）。后两级都做严格
    解码：若字节流存在非法序列，立即换下一种编码，而不是就地插入替换字符。
    返回 (text, encoding, exact)；exact 为 False 表示两种编码都无法严格解码，
    文本以替换字符呈现，调用方可据此提示用户。行尾统一为 "\\n"。"""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                break
            return _normalize_newlines(text), enc, True
    try:
        return _normalize_newlines(raw.decode("utf-8")), "utf-8", True
    except UnicodeDecodeError:
        pass
    try:
        return _normalize_newlines(raw.decode("gb18030")), "gb18030", True
    except UnicodeDecodeError:
        pass
    return _normalize_newlines(raw.decode("utf-8", errors="replace")), "unknown", False


def _normalize_newlines(text):
    """统一行尾为 "\\n"（等价于文本模式读取时的通用换行处理）"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_file(filepath):
    """按自动识别的编码读取文本文件，返回 (text, encoding, exact)。

    文件不存在或读取失败时返回 (None, None, False)。所有需要读取笔记正文
    或元数据的地方都应经由此函数，使显示、检索与索引对同一文件使用同一
    种编码——否则会出现"能显示却搜不到"这类不一致。"""
    if not os.path.exists(filepath):
        return None, None, False
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
    except OSError:
        return None, None, False
    return _decode_text(raw)


def note_encoding_label(rel_path):
    """返回该笔记的编码提示文字；UTF-8 或尚未读取过时返回 None。

    编码检测的结果只在读取后才有，故以最近一次读取的记录为准。"""
    info = NOTE_ENCODINGS.get(rel_path)
    if not info:
        return None
    enc, exact = info
    if enc == "utf-8" or enc == "utf-8-sig":
        return None
    if enc == "unknown" or not exact:
        return "未知编码，部分字符已用替换符号显示"
    return _ENCODING_LABELS.get(enc, enc.upper())


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


def invalidate_name_map():
    """失效笔记名映射缓存。

    程序内的新建/删除/重命名/移动会自行重置；此函数供外部文件变化
    （轮询检测到新增或改名）后调用，保证内部链接能解析到最新的笔记名。"""
    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None


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
    根据相对路径读取 .md 文件，返回正文文本（编码自动识别）。
    rel_path: "README" 或 "World_Archive/01_World_Overview/01_World_Overview"
    注意：不含 .md 后缀；文件不存在或读取失败返回 None
    """
    rel_path = rel_path.replace("\\", "/")
    filepath = os.path.join(DATA_DIR, f"{rel_path}.md")
    text, enc, exact = read_text_file(filepath)
    if text is None:
        return None
    NOTE_ENCODINGS[rel_path] = (enc, exact)
    return text


# ── 内部函数 ──

def _is_hidden(name):
    """以 . 开头的内部文件/目录（如回收站 .trash）不参与笔记枚举"""
    return name.startswith(".")


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
        if _is_hidden(entry):
            continue  # 跳过回收站等内部目录
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
        dirs[:] = [d for d in dirs if not _is_hidden(d)]  # 剪枝：跳过回收站
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

    # 清除名称缓存，使内部链接能解析到重命名后的笔记名
    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None

    return new_rel


def move_to_trash(rel_path, is_dir=False):
    """
    把笔记或文件夹移入回收站（data/.trash/<时间戳>/），保留原相对路径结构，
    便于整体恢复。同一秒内的多次删除会归入同一批次。

    返回回收站内的相对路径；源不存在或移动失败返回 None。
    """
    rel_path = rel_path.replace("\\", "/").strip("/")
    src = os.path.join(DATA_DIR, rel_path.replace("/", os.sep))
    if not is_dir:
        src += ".md"
    if not os.path.exists(src):
        return None

    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(TRASH_DIR, stamp, rel_path.replace("/", os.sep))
    if not is_dir:
        dest += ".md"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
    except (OSError, shutil.Error):
        return None

    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None
    return os.path.relpath(dest, TRASH_DIR).replace("\\", "/")


def list_trash(sort_desc=True):
    """
    列出回收站内容：[(时间戳, [顶层条目名, ...]), ...]。
    sort_desc=True 按删除时间倒序（新 → 旧），False 为正序。
    条目名即删除时的文件/文件夹名。
    """
    if not os.path.isdir(TRASH_DIR):
        return []
    result = []
    for stamp in sorted(os.listdir(TRASH_DIR), reverse=sort_desc):
        batch = os.path.join(TRASH_DIR, stamp)
        if not os.path.isdir(batch):
            continue
        entries = sorted(e for e in os.listdir(batch) if not _is_hidden(e))
        result.append((stamp, entries))
    return result


def restore_from_trash(stamp, entry):
    """
    从回收站恢复一个条目到原位置（目标已存在时自动改名，不覆盖）。
    stamp: 批次时间戳；entry: 条目名（如 "test1.md" 或 "myfolder"）
    返回恢复后的目标名，失败返回 None。
    """
    src = os.path.join(TRASH_DIR, stamp, entry)
    if not os.path.exists(src):
        return None

    dest = os.path.join(DATA_DIR, entry)
    if os.path.exists(dest):
        base, ext = os.path.splitext(entry)
        i = 1
        while os.path.exists(os.path.join(DATA_DIR, f"{base}_restored{i}{ext}")):
            i += 1
        dest = os.path.join(DATA_DIR, f"{base}_restored{i}{ext}")

    try:
        shutil.move(src, dest)
    except (OSError, shutil.Error):
        return None

    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None
    _cleanup_empty_batch(stamp)
    return os.path.basename(dest)


def delete_trash_entry(stamp, entry):
    """
    从回收站彻底删除一个条目（文件或文件夹）。
    返回是否成功；批次目录清空后一并移除。
    """
    target = os.path.join(TRASH_DIR, stamp, entry)
    if not os.path.exists(target):
        return False
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    except (OSError, shutil.Error):
        return False
    _cleanup_empty_batch(stamp)
    return True


def _cleanup_empty_batch(stamp):
    """批次目录已空则删除"""
    batch = os.path.join(TRASH_DIR, stamp)
    try:
        if os.path.isdir(batch) and not os.listdir(batch):
            os.rmdir(batch)
    except OSError:
        pass


def empty_trash():
    """清空回收站，返回是否成功"""
    if not os.path.isdir(TRASH_DIR):
        return True
    try:
        shutil.rmtree(TRASH_DIR)
        return True
    except (OSError, shutil.Error):
        return False


def delete_note(rel_path):
    """删除笔记 → 移入回收站（可恢复），返回是否成功"""
    return move_to_trash(rel_path, is_dir=False) is not None


def delete_folder(rel_path):
    """删除文件夹及其内容 → 移入回收站（可恢复），返回是否成功"""
    return move_to_trash(rel_path, is_dir=True) is not None


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


def move_item(rel_path, target_dir, is_dir=False):
    """
    把笔记或文件夹移动到 data/ 下的另一个目录。

    target_dir: 目标目录的相对路径，"" 表示 data 根目录
    返回新的相对路径（不含 .md）；以下情况返回 None：
      - 源不存在 / 目标目录不在 data 下
      - 目标已存在同名项
      - 移动到原目录（无需移动）
      - 文件夹被移入自身或自身的子目录
    """
    rel_path = (rel_path or "").replace("\\", "/").strip("/")
    target_dir = (target_dir or "").replace("\\", "/").strip("/")

    src = os.path.join(DATA_DIR, rel_path.replace("/", os.sep))
    if not is_dir:
        src += ".md"
    if not rel_path or not os.path.exists(src):
        return None

    name = rel_path.rsplit("/", 1)[-1]
    parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    if parent == target_dir:
        return None  # 已在目标目录
    if is_dir and (target_dir == rel_path
                   or target_dir.startswith(rel_path + "/")):
        return None  # 不能移入自身或其子目录

    dest_dir = (os.path.join(DATA_DIR, target_dir.replace("/", os.sep))
                if target_dir else DATA_DIR)
    if not os.path.isdir(dest_dir):
        return None

    dest = os.path.join(dest_dir, name + ("" if is_dir else ".md"))
    if os.path.exists(dest):
        return None  # 重名

    try:
        shutil.move(src, dest)
    except (OSError, shutil.Error):
        return None

    global NOTE_NAME_MAP
    NOTE_NAME_MAP = None
    return f"{target_dir}/{name}" if target_dir else name


def _build_tree(base_dir, prefix=""):
    """递归构建树结构"""
    items = []
    if not os.path.exists(base_dir):
        return items
    try:
        entries = sorted(os.listdir(base_dir))
    except PermissionError:
        return items
    # 跳过回收站等内部目录
    entries = [e for e in entries if not _is_hidden(e)]
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
    text, _enc, _exact = read_text_file(filepath)
    if text is None:
        return {}, ""
    try:
        post = frontmatter.loads(text)
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
        with open(filepath, "rb") as f:
            raw = f.read()
    except (IOError, OSError):
        return None
    text, enc, exact = _decode_text(raw)

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

    # 按原编码写回：用户可能用 GBK 编辑器写作，此处只改 tags 字段，
    # 不应借机把整篇笔记的编码换掉；无法识别编码时才退用 UTF-8。
    write_enc = enc if (exact and enc not in (None, "unknown")) else "utf-8"
    if b"\r\n" in raw:                      # 行尾风格沿用原文件
        new_text = new_text.replace("\n", "\r\n")
    try:
        with open(filepath, "w", encoding=write_enc, newline="") as f:
            f.write(new_text)
    except (ValueError, IOError, OSError):
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
    # 只保留已知字段，丢弃历史版本遗留的未知键
    merged = {k: merged[k] for k in ("tags", "backlinks") if k in merged}
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

# 站内链接的两种写法放在一个正则里，使匹配结果天然按出现顺序排列：
#   [[目标]] / [[目标|显示文字]]，以及标准链接 [显示文字](目标 "标题")
# 标准链接分支用 (?<!!) 排除图片 ![替代文字](图片)
_NOTE_LINK_RE = re.compile(
    r'\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]'
    r'|(?<!!)\[([^\[\]]*)\]\(\s*<?([^()<>\s]+)>?(?:\s+["\'][^"\']*["\'])?\s*\)'
)


def looks_like_note_target(href):
    """判断非协议链接是否指向站内笔记：结尾为 .md，或整段没有扩展名

    渲染时的跳转判定与反向索引共用此函数，使"能跳转但不进反链"
    这类两处规则不一致的情况不会出现。"""
    h = (href or "").split("#")[0].split("?")[0].strip()
    if not h or h.startswith(("#", "mailto:", "javascript:", "data:")):
        return False
    tail = h.replace("\\", "/").rstrip("/").split("/")[-1]
    if not tail:
        return False
    if "." not in tail:
        return True
    return tail.lower().endswith(".md")


def note_name_from_href(href):
    """从链接地址中取出笔记名：./a/b.md → b

    索引与跳转都以笔记名为准（见 find_note_by_name），故带路径的写法
    在此统一归到末段名称上。"""
    h = (href or "").split("#")[0].split("?")[0]
    tail = h.replace("\\", "/").rstrip("/").split("/")[-1]
    return re.sub(r"\.md$", "", tail, flags=re.I)


# 行内代码：`...`（含以多个反引号包裹的情形）
_INLINE_CODE_RE = re.compile(r'`+[^`\n]*`+')


def _placeholder(parts, segment):
    """把一段原文换成一个占位符，并将原文存入 parts 供之后还原"""
    parts.append(segment)
    return f"\x00{len(parts) - 1}\x00"


def _mask_fences(text):
    """按行扫描围栏代码块，整体换成占位符；未闭合时其后全部视为代码

    围栏规则与 Markdown 一致：以 ``` 或 ~~~ 起止。返回 (替换后的文本, 片段表)。
    """
    parts, out, buf, in_fence = [], [], [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            if in_fence:
                buf.append(line)
                out.append(_placeholder(parts, "".join(buf)))
                buf, in_fence = [], False
            else:
                in_fence = True
                buf.append(line)
            continue
        (buf if in_fence else out).append(line)
    if buf:                       # 未闭合的围栏：其后内容按 Markdown 规则同属代码
        out.append(_placeholder(parts, "".join(buf)))
    return "".join(out), parts


def mask_code_regions(text):
    """把代码区（围栏代码块与行内代码）换成占位符，返回 (文本, 还原函数)

    供渲染前的文本改写使用：代码示例中的 [[...]] 不应被改写成链接，
    否则代码块的显示内容与复制结果都会被破坏。"""
    masked, parts = _mask_fences(text or "")
    masked = _INLINE_CODE_RE.sub(
        lambda m: _placeholder(parts, m.group(0)), masked)

    def restore(s):
        for i, seg in enumerate(parts):
            s = s.replace(f"\x00{i}\x00", seg)
        return s

    return masked, restore


def strip_code_regions(text):
    """去掉代码区，只留正文，供反向索引判断哪些链接是真引用

    笔记中常以行内代码举出链接写法（如 `[文字](笔记名)`），这类示例
    若一并计入，会给目标笔记带来并不存在的反向链接。"""
    masked, _parts = mask_code_regions(text)
    return re.sub(r"\x00\d+\x00", " ", masked)


def parse_note_links(content):
    """提取正文中全部站内链接的目标笔记名（去重，保持首次出现的顺序）

    两种写法一并计入：双括号 [[目标]] / [[目标|显示文字]]，以及标准链接
    [显示文字](目标.md)。后者需与网页链接区分，判定规则与渲染跳转所用
    的 looks_like_note_target 相同，故"点得进去的"与"进得了反链的"一致。
    """
    links = []
    seen = set()
    content = strip_code_regions(content)      # 代码区中的写法多为示例，不计入

    def _add(name):
        name = note_name_from_href((name or "").strip())
        if name and name not in seen:
            seen.add(name)
            links.append(name)

    for m in _NOTE_LINK_RE.finditer(content):
        if m.group(1) is not None:            # 双括号写法：目标在 group(1)
            _add(m.group(1))
            continue
        href = m.group(4)                     # 标准链接：目标在 group(4)
        if href.startswith(("http://", "https://", "wikilink:", "mailto:")):
            continue
        if looks_like_note_target(href):
            _add(href)
    return links


def build_backlink_index():
    """
    扫描 data/ 下所有 .md 文件，构建反向链接索引并写入 index.json。
    返回 {被引用笔记名: [引用者路径, ...]}
    """
    backlinks = {}
    for item in _walk(DATA_DIR):
        filepath = os.path.join(DATA_DIR, f"{item['path']}.md")
        content, _enc, _exact = read_text_file(filepath)
        if content is None:
            continue
        # 跳过 YAML front matter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:]
        for target in parse_note_links(content):
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
    # 只保留已知字段，丢弃历史版本遗留的未知键
    merged = {k: merged[k] for k in ("tags", "backlinks") if k in merged}
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
