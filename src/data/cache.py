"""
管理 MarketData 的来源级 Parquet 缓存。

本模块位于面板构造与 ``MarketData`` 编排之间，负责根据 YAML 文件名和显式缓存根
目录确定固定缓存位置，并按数据来源读取或保存一个 Parquet 文件；本模块不判断原始
CSV 是否更新，也不参与面板计算。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# 根据 YAML 文件名确定可重复覆盖的固定缓存目录。
def resolve_market_cache_directory(
    config_path: Path,
    cache_root: str | Path,
) -> Path:
    """
    解析本次 MarketData 使用的缓存目录。

    输入：
    - config_path：构建市场数据所使用的 YAML 文件路径。
    - cache_root：绝对路径或相对 YAML 所在目录的市场缓存根目录。

    输出：
    - 返回 ``<缓存根>/<配置名>`` 路径，不主动创建目录。

    功能和用途：
    - 同一 YAML 始终使用同一个目录，``refresh=True`` 时直接覆盖其中的来源缓存。
    - YAML 内容修改后由调用方显式刷新，不再为每次配置变化生成新目录。
    """
    resolved_cache_root = Path(cache_root).expanduser()
    if not resolved_cache_root.is_absolute():
        resolved_cache_root = config_path.parent / resolved_cache_root
    return resolved_cache_root.resolve() / config_path.stem


# 缓存存在时读取完整来源面板，不存在时通知编排层重新构建。
def load_source_cache(
    cache_directory: Path,
    source_name: str,
) -> pd.DataFrame | None:
    """
    读取单个数据来源的 Parquet 缓存。

    输入：
    - cache_directory：``resolve_market_cache_directory`` 返回的配置缓存目录。
    - source_name：缓存对应的标准数据来源名，例如 ``stock_quote``。

    输出：
    - ``<source_name>.parquet`` 存在时返回完整 DataFrame，不存在时返回 ``None``。

    功能和用途：
    - ``None`` 是正常的缓存未命中状态，由 ``MarketData`` 继续读取原始数据并构建。
    - Parquet 中保存的日期索引、MultiIndex 列和字段 dtype 原样交给上层使用。
    """
    cache_path = cache_directory / f"{source_name}.parquet"
    if not cache_path.exists():
        return None
    return pd.read_parquet(cache_path)


# 把一个来源的完整日频面板保存为可复用 Parquet。
def save_source_cache(
    cache_directory: Path,
    source_name: str,
    source_panel: pd.DataFrame,
) -> Path:
    """
    保存单个数据来源的面板缓存。

    输入：
    - cache_directory：当前配置的缓存目录。
    - source_name：作为 Parquet 文件名的标准来源名。
    - source_panel：已经完成日历和列结构对齐的来源级 DataFrame。

    输出：
    - 返回实际写入的 Parquet 文件路径。

    功能和用途：
    - 首次写入时创建配置缓存目录，每个来源独立保存一个文件。
    - ``refresh=True`` 时上层会再次调用本函数并覆盖同名来源缓存。
    """
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_directory / f"{source_name}.parquet"
    source_panel.to_parquet(cache_path)
    return cache_path
