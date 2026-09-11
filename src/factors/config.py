"""
从单个 Factor YAML 动态构造具体因子实例。

本模块位于 YAML 文件和 Factor 对象之间，只包含 ``load_factor``。配置通过
``implementation.module`` 和 ``implementation.class`` 指向一个可导入的具体因子类，
完整配置原样传入该类；本模块不维护注册表、不展开窗口变体，也不扫描配置目录。
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import yaml

from src.factors.base import Factor


# 读取一个因子 YAML，并按模块名和类名构造对应实例。
def load_factor(config_path: str | Path) -> Factor:
    """
    加载单个 YAML 定义的因子实例。

    输入：
    - config_path：因子 YAML 文件路径；配置必须包含 ``name``、
      ``implementation.module``、``implementation.class`` 和具体类需要的参数分区。

    输出：
    - 返回 YAML 指定类构造出的 Factor 实例，实例保存完整配置。

    功能和用途：
    - 读取完整 YAML，通过标准 Python 模块名导入具体因子类，再执行
      ``factor_class(config)``。
    - 一个 YAML 只生成一个实例；不兼容短名称注册表、文件路径加载或 variants 展开。
    """
    resolved_config_path = Path(config_path).expanduser().resolve()
    factor_config = yaml.safe_load(
        resolved_config_path.read_text(encoding="utf-8")
    )
    implementation = factor_config["implementation"]
    factor_module = import_module(implementation["module"])
    factor_class = getattr(factor_module, implementation["class"])
    return factor_class(factor_config)
