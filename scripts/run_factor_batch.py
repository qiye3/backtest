"""
从配置目录批量计算 Factor，并把日频面板保存为 Parquet。

本脚本是项目的命令行运行入口。``run_factor_batch`` 组合 MarketData 缓存、动态 Factor
加载和批量计算，``main`` 提供参数入口，``_save_factor_panels`` 写出最终结果；脚本不
实现数据加工或因子公式，默认使用 ``examples`` 下的完整示例配置。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from src.data.market_data import MarketData
from src.factors import calc_factors, load_factors


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKET_DATA_CONFIG = PROJECT_ROOT / "examples" / "config" / "market_data.yaml"
DEFAULT_FACTOR_CONFIG_DIRECTORY = (
    PROJECT_ROOT / "examples" / "config" / "factors"
)
DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "examples" / "output"


# 构建共享市场数据，批量计算配置目录中的因子并保存结果。
def run_factor_batch(
    market_data_config: str | Path,
    factor_config_directory: str | Path,
    output_directory: str | Path,
    max_workers: int = 1,
    refresh_market_data: bool = False,
) -> dict[str, Path]:
    """
    运行一批 YAML 定义的 Factor。

    输入：
    - market_data_config：包含 ``market_data`` 分区的 YAML 文件路径。
    - factor_config_directory：Factor YAML 所在目录，只读取第一层 ``*.yaml``。
    - output_directory：每个因子面板的 Parquet 输出目录。
    - max_workers：传给 ``calc_factors`` 的线程数，默认1表示串行。
    - refresh_market_data：为真时从原始 CSV 重建并覆盖同名市场数据缓存。

    输出：
    - 返回 ``{因子名称: Parquet 路径}``，顺序与配置文件顺序一致。

    功能和用途：
    - 整个批次只构建一个 ``MarketData``，所有 Factor 共享已经物化的只读面板。
    - Factor 类由 YAML 动态导入，计算结果使用固定文件名保存，重复运行直接覆盖。
    """
    market_data = MarketData.from_yaml(
        market_data_config,
        refresh=refresh_market_data,
    )
    factors = load_factors(factor_config_directory)
    factor_panels = calc_factors(
        factors=factors,
        market_data=market_data,
        max_workers=max_workers,
    )
    return _save_factor_panels(factor_panels, output_directory)


# 解析命令行参数并报告每个因子面板的保存位置。
def main() -> None:
    """
    执行批量 Factor 命令行入口。

    输入：
    - 从命令行读取市场配置、Factor 配置目录、输出目录、线程数和缓存刷新开关。
    - 未显式传参时使用 ``examples/config`` 与 ``examples/output``。

    输出：
    - 无返回值；计算完成后逐行打印因子名称和 Parquet 绝对路径。

    功能和用途：
    - 把命令行参数转换为 ``run_factor_batch`` 调用，不包含数据处理或因子计算逻辑。
    - 使用 ``python -m scripts.run_factor_batch`` 即可运行项目内置示例批次。
    """
    parser = argparse.ArgumentParser(
        description="批量运行 YAML 定义的 Factor",
    )
    parser.add_argument(
        "--market-data-config",
        type=Path,
        default=DEFAULT_MARKET_DATA_CONFIG,
    )
    parser.add_argument(
        "--factor-config-dir",
        type=Path,
        default=DEFAULT_FACTOR_CONFIG_DIRECTORY,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--refresh-market-data", action="store_true")
    arguments = parser.parse_args()

    output_paths = run_factor_batch(
        market_data_config=arguments.market_data_config,
        factor_config_directory=arguments.factor_config_dir,
        output_directory=arguments.output_dir,
        max_workers=arguments.max_workers,
        refresh_market_data=arguments.refresh_market_data,
    )
    for factor_name, output_path in output_paths.items():
        print(f"{factor_name}: {output_path}")


# 将批量计算得到的每个因子面板写入固定名称的 Parquet。
def _save_factor_panels(
    factor_panels: Mapping[str, pd.DataFrame],
    output_directory: str | Path,
) -> dict[str, Path]:
    """
    保存批量 Factor 的日频面板。

    输入：
    - factor_panels：因子名称到日期乘股票 DataFrame 的映射。
    - output_directory：结果目录；首次保存时由本函数创建。

    输出：
    - 返回因子名称到实际 Parquet 路径的映射。

    功能和用途：
    - 每个因子独立保存为 ``<factor_name>.parquet``，便于下游按需读取。
    - 文件名不加入时间戳或哈希，同名结果在重复运行时直接刷新。
    """
    resolved_output_directory = Path(output_directory).expanduser().resolve()
    resolved_output_directory.mkdir(parents=True, exist_ok=True)

    output_paths: dict[str, Path] = {}
    for factor_name, factor_panel in factor_panels.items():
        output_path = resolved_output_directory / f"{factor_name}.parquet"
        factor_panel.to_parquet(output_path)
        output_paths[factor_name] = output_path
    return output_paths


if __name__ == "__main__":
    main()
