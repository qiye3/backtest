"""
从单个文件或配置目录动态构造具体因子实例。

本模块位于 Factor YAML 和计算引擎之间。``load_factor`` 根据模块名与类名构造一个
Factor，``load_factors`` 按文件名顺序加载配置目录中的一批 Factor；两者都把完整配置
交给具体类，不维护注册表、不展开窗口变体，也不参与因子计算。
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import yaml

from src.factors.base import Factor


# 按文件名顺序加载配置目录中的全部因子实例。
def load_factors(config_directory: str | Path) -> list[Factor]:
    """
    批量加载一个目录中的 Factor YAML。

    输入：
    - config_directory：Factor YAML 所在目录；只读取目录第一层的 ``*.yaml`` 文件。

    输出：
    - 返回按 YAML 文件名排序的 Factor 实例列表。

    功能和用途：
    - 批量运行入口通过本函数复用单文件动态导入逻辑，不需要知道具体 Factor 类。
    - 空配置目录和重复因子名称会直接报错，避免批量任务静默不运行或覆盖结果。
    """
    resolved_config_directory = Path(config_directory).expanduser().resolve()
    config_paths = sorted(resolved_config_directory.glob("*.yaml"))
    if not config_paths:
        raise FileNotFoundError(
            f"Factor 配置目录中没有 YAML: {resolved_config_directory}"
        )

    factors = [load_factor(config_path) for config_path in config_paths]
    factor_names = [factor.name for factor in factors]
    if len(factor_names) != len(set(factor_names)):
        raise ValueError("批量 Factor 配置中的 name 必须唯一")
    return factors


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
