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
description: 运行 YAML 驱动的 A 股因子评价和策略回测框架。用于接入外部因子或策略包，计算因子后处理、行业中性化、基准超额收益分组、IC、整体评价、simple/account 回测和 PIT 指数成份股票池。
---

# Factor Backtest

本 Skill 只包含通用框架，不包含具体 factors 配置或策略。配套 Factors 包提供 Growth、Quality、Value 三组正式因子；配套 Strategies 包提供 yfd100。

## 三组因子实验

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

去掉 `--dry-run` 后固定按 Growth、Quality、Value 顺序运行。脚本先按三组字段并集刷新一次共享市场缓存，随后三组只读复用。正式默认运行 factors、group return、overall、simple 回测及对应绘图；account 回测关闭。

每个因子公式只计算一次，随后先做 YAML 指定的截面 rank 或 1%–99% winsorize，再输出 `__raw` 和 `__industry_neutral`。行业中性版本按评价日 CITICS 历史行业去均值；收益目标先对个股原始未来收益做行业去均值，再减同期基准收益。

## 单独运行 yfd100

在 Strategies 包根目录执行：

```bash
python3 scripts/run_yfd100.py \\
  --framework-root /absolute/path/to/unpacked-skill \\
  --data-root /absolute/path/to/data \\
  --output-root /absolute/path/to/results \\
  --dry-run
```

yfd100 默认启用策略 simple 回测，account 回测关闭。

复用其他实验已经保存的 `factor.parquet` 时，将 `run.factors` 设为 `false`，并通过 `factors.result_root` 指向原实验输出根；策略结果仍写入当前 `output.root`。

## 直接运行框架

```bash
PYTHONPATH=/absolute/path/to/skill/code:/absolute/path/to/external-package \\
python3 -m src.cli --config /absolute/path/to/run.yaml
```

不要把数据、缓存、输出或具体因子配置写入 Skill 包。
"""

OPENAI_YAML = """interface:
  display_name: "Factor Backtest"
  short_description: "运行外部 A 股因子和策略包的 PIT 评价与回测"
  default_prompt: "Use $factor-backtest with external factor or strategy packages to run PIT evaluation and backtests."
"""

REFERENCE_MD = """# Output reference

- 每个因子目录：`factor.parquet`、可选的 `group_return.parquet` 与 figures。
- 根目录汇总：`factor_summary_daily.csv`、`factor_summary_weekly.csv`。
- `00_overall/`：`factor_correlation.csv`、`factor_ic.csv`、`factor_return.csv` 及对应图。
- 正式 group return 周期：1、2、4、8 周。
- 预留回测周期：1、4 周；simple 股票数不足时持有现金。
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
    for script_name in ("run_all_factor_backtests.py", "sync_index_members.py"):
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
    for group_name in ("growth_factors", "quality_factors", "value_factors"):
        _copy_tree(
            PROJECT_ROOT / "factors" / group_name,
            factors_destination / group_name,
        )


def _build_strategies(staging: Path) -> None:
    _copy_tree(
        PROJECT_ROOT / "strategies",
        staging / "strategies",
    )
    (staging / "scripts").mkdir()
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "run_yfd100.py",
        staging / "scripts" / "run_yfd100.py",
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
