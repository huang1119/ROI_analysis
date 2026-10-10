"""pytest 共享 fixtures。"""
import os
import sys

# 保证 tests/ 运行时能 import src.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from src.data.synthetic import build_demo_config, generate  # noqa: E402


@pytest.fixture(scope="session")
def demo_df():
    """带已知异常的演示合成数据（seed 固定，可复现）。"""
    cfg = build_demo_config()
    data, _ = generate(cfg)
    return data


@pytest.fixture(scope="session")
def demo_log():
    """注入异常日志（ground truth）。"""
    cfg = build_demo_config()
    _, log = generate(cfg)
    return log
