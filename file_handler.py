import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def list_notes():
    """返回 data 文件夹下所有 .md 文件名（不含扩展名）"""
    if not os.path.exists(DATA_DIR):
        return []
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".md")]
    # 去掉 .md 后缀
    return [os.path.splitext(f)[0] for f in files]

def read_note(filename):
    """根据文件名（不含扩展名）读取 .md 文件的全部内容"""
    filepath = os.path.join(DATA_DIR, f"{filename}.md")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
