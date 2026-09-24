"""从当前源码生成互相独立的 Skill、Factors 和 Strategies 干净包。"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT.parent
SKILL_STAGING_NAME = "factor-backtest_upload"
FACTORS_STAGING_NAME = "factor-backtest_factors_upload"
STRATEGIES_STAGING_NAME = "factor-backtest_strategies_upload"

SKILL_MD = """---
name: factor-backtest
description: 运行 YAML 驱动的 A 股因子评价和指数增强策略回测。用于接入配套 Factors 或 Strategies 包，执行 PIT 股票池、因子后处理、超额收益分组、overall 评价和策略回测。
---

# Factor Backtest

本 Skill 只包含通用框架，不包含具体因子配置或策略。配套 Factors 包提供 Growth、Quality、Value、First Batch、Second Batch；配套 Strategies 包提供 yfd100 和 roadshow_indices。

## 五组因子实验

先确认数据根包含历史成份与中信行业文件：

- `index/members/000906.SH.csv`
- `index/members/000852.SH.csv`
- `stock/industry/industry_history.csv`

执行：

```bash
python3 scripts/run_all_factor_backtests.py \\
  --factors-root /absolute/path/to/factors \\
  --data-root /absolute/path/to/data \\
  --output-root /absolute/path/to/results \\
  --dry-run
```

去掉 `--dry-run` 后固定按 Growth、Quality、Value、First Batch、Second Batch 顺序运行。脚本先按五组字段并集刷新一次共享市场缓存，随后五组只读复用。因子实验只运行 factors、group return 和 overall evaluation；simple/account 回测与单因子绘图关闭。

`00_overall/` 输出因子相关性、IC 分布、因子收益分布、因子分布总图和四周分组收益总图。每个因子目录不生成 `figures/`。

每个因子公式只计算一次，随后先做 YAML 指定的截面 rank 或 1%–99% winsorize，再输出 `__raw` 和 `__industry_neutral`。行业中性版本按评价日 CITICS 历史行业去均值；收益目标先对个股原始未来收益做行业去均值，再减同期基准收益。

## 指数增强策略

在 Strategies 包根目录执行：

```bash
python3 scripts/run_strategy_backtests.py \\
  --framework-root /absolute/path/to/unpacked-skill \\
  --data-root /absolute/path/to/data \\
  --output-root /absolute/path/to/results \\
  --suite all \\
  --dry-run
```

`--suite` 可选 `all`、`yfd100`、`roadshow`。策略默认启用 simple 回测和策略图，account 回测关闭；不输出策略内部因子的研究图。

复用其他实验已经保存的 `factor.parquet` 时，将 `run.factors` 设为 `false`，并通过 `factors.result_root` 指向原实验输出根；策略结果仍写入当前 `output.root`。

## tmux 与日志

去掉 `--dry-run` 后，正式入口默认建立独立 tmux session。日志写入 `<output-root>/log/`；成功运行后删除本次日志，失败或中断时保留。启动输出会给出 session、日志路径和 attach 命令。

本机没有 tmux 时应明确失败。只有明确需要占用当前终端时才使用 `--foreground`。

## 直接运行任意配置

```bash
PYTHONPATH=/absolute/path/to/external-package \\
python3 scripts/run_factor_config.py --config /absolute/path/to/run.yaml
```

不要把数据、缓存、输出或具体因子配置写入 Skill 包。

## 增量更新市场缓存和因子值

多份配置指向同一个 `market_data.cache_root` 时，可以在一次任务中合并数据需求：

```bash
PYTHONPATH=/absolute/path/to/factor-library/code \
python3 scripts/update_factor_cache.py \
  /absolute/path/to/factor-library/code/configs/growth.yaml \
  /absolute/path/to/factor-library/code/configs/value.yaml \
  --dry-run
```

去掉 `--dry-run` 后，命令会识别原始文件新增和历史修订，先更新共享
MarketData，再更新每份配置的 `factor.parquet`。`--rebuild` 用于强制整套重建。
更新任务只管理市场缓存和因子值；IC、分组收益、overall 和回测仍由正式运行链路完整重算。
"""

OPENAI_YAML = """interface:
  display_name: "Factor Backtest"
  short_description: "运行外部 A 股因子和策略包的 PIT 评价与回测"
  default_prompt: "Use $factor-backtest with external factor or strategy packages to run PIT evaluation and backtests."
"""

REFERENCE_MD = """# Output reference

- 每个因子目录：`factor.parquet` 与按保留设置保存的 `group_return.parquet`；不生成 `figures/`。
- `summaries/`：`factor_summary_daily.csv`、`factor_summary_weekly.csv`。
- `00_overall/`：三张 overall CSV、基础三图、因子分布总图与四周分组收益总图。
- 正式 group return 周期：1、2、4、8 周。
- 因子 simple/account 回测默认关闭；预留周期为 1、4 周。
- 指数增强策略 simple 回测默认开启并输出策略图；account 默认关闭。
- `scripts/update_factor_cache.py`：增量更新共享市场缓存和因子值。
- 更新状态：`market_data.cache_root/.state/market_update.json` 和 `output.root/.state/factor_update.json`。
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def _reset_directory(path: Path, expected_name: str) -> None:
    if path.name != expected_name:
        raise ValueError(f"拒绝清理非预期目录: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _ignore_artifacts(directory: str, names: list[str]) -> set[str]:
    del directory
    ignored_names = {
        ".DS_Store",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "docs",
        "examples",
        "tests",
    }
    return {
        name
        for name in names
        if name in ignored_names
        or name.endswith((".pyc", ".pyo"))
    }


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=_ignore_artifacts)


def _build_skill(staging: Path) -> None:
    (staging / "agents").mkdir()
    (staging / "scripts").mkdir()
    (staging / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (staging / "agents" / "openai.yaml").write_text(OPENAI_YAML, encoding="utf-8")
    (staging / "reference.md").write_text(REFERENCE_MD, encoding="utf-8")
    (staging / "requirements.txt").write_text(
        "matplotlib>=3.7\nnumpy>=1.24\npandas>=2.0\npyarrow>=12.0\n"
        "PyYAML>=6.0\nscipy>=1.11\ntqdm>=4.66\n",
        encoding="utf-8",
    )
    (staging / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools>=68\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        "[project]\nname = \"factor-backtest\"\nversion = \"0.1.0\"\n"
        "description = \"Config-driven factor evaluation and backtesting\"\n"
        "requires-python = \">=3.9\"\n"
        "dependencies = [\"matplotlib>=3.7\", \"numpy>=1.24\", "
        "\"pandas>=2.0\", \"pyarrow>=12.0\", \"PyYAML>=6.0\", "
        "\"scipy>=1.11\", \"tqdm>=4.66\"]\n\n"
        "[tool.setuptools.packages.find]\ninclude = [\"src*\"]\n",
        encoding="utf-8",
    )
    _copy_tree(PROJECT_ROOT / "src", staging / "code" / "src")
    (staging / "code" / "src" / "factors" / "PriceVolumeFactor.py").unlink()
    for script_name in (
        "run_all_factor_backtests.py",
        "run_factor_config.py",
        "update_factor_cache.py",
        "sync_index_members.py",
        "tmux_runner.py",
    ):
        shutil.copy2(
            PROJECT_ROOT / "scripts" / script_name,
            staging / "scripts" / script_name,
        )


def _build_factors(staging: Path) -> None:
    factors_destination = staging / "factors"
    factors_destination.mkdir()
    for file_name in ("__init__.py", "fundamental_utils.py"):
        shutil.copy2(
            PROJECT_ROOT / "factors" / file_name,
            factors_destination / file_name,
        )
    for group_name in (
        "growth_factors",
        "quality_factors",
        "value_factors",
        "first_batch_factors",
        "second_batch_factors",
    ):
        _copy_tree(
            PROJECT_ROOT / "factors" / group_name,
            factors_destination / group_name,
        )


def _build_strategies(staging: Path) -> None:
    _copy_tree(
        PROJECT_ROOT / "strategies",
        staging / "strategies",
    )
    factors_destination = staging / "factors"
    factors_destination.mkdir()
    for file_name in ("__init__.py", "fundamental_utils.py"):
        shutil.copy2(
            PROJECT_ROOT / "factors" / file_name,
            factors_destination / file_name,
        )
    (staging / "scripts").mkdir()
    for script_name in (
        "run_strategy_backtests.py",
        "run_yfd100.py",
        "tmux_runner.py",
    ):
        shutil.copy2(
            PROJECT_ROOT / "scripts" / script_name,
            staging / "scripts" / script_name,
        )


def _write_zip(staging: Path, zip_path: Path) -> None:
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging))


def main() -> None:
    """重建三个暂存目录并在同一输出根生成三个 ZIP。"""
    output_root = _arguments().output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    releases = (
        (SKILL_STAGING_NAME, "factor-backtest-skill.zip", _build_skill),
        (FACTORS_STAGING_NAME, "factor-backtest-factors.zip", _build_factors),
        (STRATEGIES_STAGING_NAME, "factor-backtest-strategies.zip", _build_strategies),
    )
    for staging_name, zip_name, builder in releases:
        staging = output_root / staging_name
        _reset_directory(staging, staging_name)
        builder(staging)
        _write_zip(staging, output_root / zip_name)
        print(f"built {output_root / zip_name}")


if __name__ == "__main__":
    main()
