# -*- mode: python ; coding: utf-8 -*-
# IndeXar 打包配置（onedir：用户数据 data/、settings.json 与 exe 同级，升级不丢数据）
# 打包命令：python -m PyInstaller IndeXar.spec --noconfirm

# Pygments 的 lexer/style 是按语言名动态 import 的，静态分析收集不到；
# 老版本 PyInstaller 没有内置 hook，这里显式收集（缺失则只有语法高亮失效）
try:
    from PyInstaller.utils.hooks import collect_submodules
    _hiddenimports = (collect_submodules('pygments.lexers')
                      + collect_submodules('pygments.styles'))
except Exception:
    _hiddenimports = []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # numpy/psutil 等并非本应用依赖，是 Anaconda 环境下依赖分析误收集
    excludes=['numpy', 'psutil'],
    noarchive=False,
)

# 过滤误收集的二进制：mkl 系列 DLL 占 350MB+，应用完全用不到
a.binaries = [b for b in a.binaries
              if 'mkl' not in b[0].lower()
              and 'numpy' not in b[0].lower()
              and 'psutil' not in b[0].lower()
              and 'tbb12' not in b[0].lower()]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='IndeXar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='IndeXar',
)
