"""pytest 配置：将仓库根目录加入 sys.path，使 tests/ 能导入顶层模块。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
