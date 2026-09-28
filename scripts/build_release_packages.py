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
SEARCH_SKILL_STAGING_NAME = "factor-search-skill"

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

## 失败恢复

正式流水线按因子和策略逐项记录完成状态。运行失败或中断后，保持配置、代码和输入文件不变，重新执行同一命令即可复用 `<output-root>/.pipeline_cache/` 中已经完整落盘的项目。成功发布全部结果后，框架会自动删除该缓存。

恢复前会比较结构化配置、代码文件及输入文件的路径、大小和修改时间；任何一项变化都会保留原缓存并拒绝混用。确认需要放弃旧进度时，在原命令后添加 `--fresh`，它只清空当前实验的 `.pipeline_cache` 后从头运行。不要手工改写 `.pipeline_cache/run_state.json`。

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
- weekly 汇总包含 1/2/4/8 周 RankIC、ICIR、G10-G1 多空 IR、十组单调性和风格确认字段，可直接交给 `factor-scoring-skill`。
- `00_overall/`：三张 overall CSV、基础三图、因子分布总图与四周分组收益总图。
- 正式 group return 周期：1、2、4、8 周。
- 因子 simple/account 回测默认关闭；预留周期为 1、4 周。
- 指数增强策略 simple 回测默认开启并输出策略图；account 默认关闭。
- `scripts/update_factor_cache.py`：增量更新共享市场缓存和因子值。
- 更新状态：`market_data.cache_root/.state/market_update.json` 和 `output.root/.state/factor_update.json`。
- 失败恢复状态：`output.root/.pipeline_cache/run_state.json`；同签名重跑自动续跑，`--fresh` 明确放弃旧进度。
"""

SEARCH_SKILL_MD = """---
name: factor-search-skill
description: 使用 TK factor-backtest 正式框架从 Factor YAML 或标准因子 Parquet 生成频率感知的时序算子变体。用于批量构造 core 或 all 搜索因子并输出可直接回测的独立 Parquet；不执行截面处理、回测、评分、筛选或正式入库。
---

# 因子时序搜索

读取搜索 YAML，使用包内 factor-backtest 框架和外部正式因子代码生成时序变体。配置字段、算子范围和输出约定见[配置与算子说明](references/configuration.md)。

## 执行

先进行不写结果的预演：

```bash
python3 scripts/run_factor_search.py \\
  --config /absolute/path/to/search.yaml \\
  --dry-run
```

确认基础因子、频率、变体数和输出目录后去掉 `--dry-run`。中断后使用相同配置重跑可恢复已完成变体；只有明确放弃当前进度时才增加 `--fresh`。

## 约束

- Factor YAML 是首选输入，并通过 `factor_code_root` 动态导入正式实现。
- 外部 Parquet 必须是日期乘股票的数值宽表，并显式声明原生频率。
- 季度非 raw 搜索必须由正式 Factor 提供真实公告事件；不得从日频填充值猜测季度历史。
- 输出写入配置指定的独立目录，不写 Skill 自身，也不写长期 `factors_data`。
- 本 Skill 只生成时序面板，不调用 YAML 的截面 postprocess 或 raw/industry-neutral variants。

完成后汇报基础因子数、生成与恢复的变体数、manifest 和输出根目录。
"""

SEARCH_OPENAI_YAML = """interface:
  display_name: "Factor Search"
  short_description: "在正式因子框架中生成可回测的时序算子变体"
  default_prompt: "Use $factor-search-skill to generate temporal factor variants with the TK factor framework."
"""

SEARCH_CONFIGURATION_MD = """# 配置与算子说明

## 搜索配置

```yaml
market_config: /absolute/path/to/run.yaml
factor_code_root: /absolute/path/to/formal/code
inputs:
  - factor_config: factors/growth_factors/config/analyst_coverage.yaml
    frequency: daily
  - name: external_factor
    parquet: /absolute/path/to/external_factor.parquet
    frequency: daily
operators:
  mode: all
  include_average_growth: true
output_root: /absolute/path/to/factor_search_results/run_name
```

- 相对 `market_config`、`parquet` 和 `output_root` 以搜索 YAML 所在目录解析。
- 相对 `factor_config` 以 `factor_code_root` 解析；YAML 中的 `name` 是基础因子名。
- `frequency` 可选 `daily/weekly/monthly/quarterly/annual`，程序不会从已日频化面板猜测原生频率。
- `mode` 默认 `core`，也可为 `raw` 或 `all`；需要参考列表中的全部适用算子时使用 `all`。
- `include_average_growth` 在 `all` 中默认开启，使三套算子完整生效；比率类因子应显式设为 `false`。该字段不允许在 `raw/core` 中开启。

## 算子

`core` 在日频和周频使用：`raw`、`qtile_M12`、`qtile_M24`、`zscore_K12`、`zscore_K24`、`chg_K1`、`qtilechg_K24_K1`、`zchg_K24_K1`。季频使用 `raw/qoq/yoy/qtile8`；月频和年频 core 只输出 raw。

`all` 包含全部三套算子：

- 第一套 43 个多年统计、差分、趋势和历史分位算子；
- 第二套日频/周频 64 个分位、偏离、Z-score 和变化算子；
- 第三套 5 个 OLS 平均增长率算子。

第一套完整 ID 为 `mean_N1...N5`、`std_N1...N5`、`zscore_N1...N5`、`cv_N1...N5`、`qoq_diff/qoq_pct`、`yoy_diff/yoy_pct`、`trend_slope_N1...N5`、`trend_improve_N1...N5`、`quantile_N1...N5` 和 `quantile_K1/K3/K6/K12`。

第二套完整 ID 为 `raw`、`qtile_M6/M12/M24/M60`、`dev_K{1,2,3}_K{3,6,12,24,60}`、`zscore_K6/K12/K24/K36/K60`、`chg_K1/K2/K3/K6`、`pctchg_K1/K2/K3/K6`、`qtilechg_K{6,12,24,60}_K{1,2,3,6}` 和 `zchg_K{6,12,24,36,60}_K{1,2,3}`。季频使用 `raw/qoq/yoy/qtile8`，月频和年频不套用日频/周频月窗算子。

第三套完整 ID 为 `avg_growth_N1...N5`。只适合绝对数值类指标；比率类输入通过 `include_average_growth: false` 排除。

日频 all 同时生成日频、过去 5 个交易日均值的周频分支和过去 20 个交易日均值的月频分支；周频 all 同时生成周频和过去 4 周均值的月频分支。所有采样使用市场配置中的真实交易日历。

## 输出

```text
<output_root>/
├── config_snapshot.yaml
├── factor_search_manifest.csv
└── factors/<base>__<frequency>__<operator>/factor.parquet
```

每个 Parquet 都是日期乘股票的 `float32` 宽表，可直接作为 factor-backtest 的 `factors.result_root` 输入。搜索阶段只做时间序列变换和成员范围对齐，不做 rank、winsorize 或行业中性化。
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
    for file_name in (
        "__init__.py",
        "fundamental_utils.py",
        "quarterly_history.py",
    ):
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


def _build_search_skill(staging: Path) -> None:
    """从当前项目源码构建可独立运行的因子搜索 Skill。"""
    (staging / "agents").mkdir()
    (staging / "references").mkdir()
    (staging / "scripts").mkdir()
    (staging / "SKILL.md").write_text(SEARCH_SKILL_MD, encoding="utf-8")
    (staging / "agents" / "openai.yaml").write_text(
        SEARCH_OPENAI_YAML,
        encoding="utf-8",
    )
    (staging / "references" / "configuration.md").write_text(
        SEARCH_CONFIGURATION_MD,
        encoding="utf-8",
    )
    (staging / "requirements.txt").write_text(
        "numpy>=1.24\npandas>=2.0\npyarrow>=12.0\nPyYAML>=6.0\n",
        encoding="utf-8",
    )
    (staging / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools>=68\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        "[project]\nname = \"factor-search-skill\"\nversion = \"0.1.0\"\n"
        "description = \"Frequency-aware factor variant generation\"\n"
        "requires-python = \">=3.9\"\n"
        "dependencies = [\"numpy>=1.24\", \"pandas>=2.0\", "
        "\"pyarrow>=12.0\", \"PyYAML>=6.0\"]\n\n"
        "[tool.setuptools.packages.find]\ninclude = [\"src*\"]\n",
        encoding="utf-8",
    )
    _copy_tree(PROJECT_ROOT / "src", staging / "code" / "src")
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "run_factor_search.py",
        staging / "scripts" / "run_factor_search.py",
    )


def _write_zip(staging: Path, zip_path: Path) -> None:
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging))


def main() -> None:
    """重建四个暂存目录并在同一输出根生成四个 ZIP。"""
    output_root = _arguments().output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    releases = (
        (SKILL_STAGING_NAME, "factor-backtest-skill.zip", _build_skill),
        (FACTORS_STAGING_NAME, "factor-backtest-factors.zip", _build_factors),
        (STRATEGIES_STAGING_NAME, "factor-backtest-strategies.zip", _build_strategies),
        (SEARCH_SKILL_STAGING_NAME, "factor-search-skill.zip", _build_search_skill),
    )
    for staging_name, zip_name, builder in releases:
        staging = output_root / staging_name
        _reset_directory(staging, staging_name)
        builder(staging)
        _write_zip(staging, output_root / zip_name)
        print(f"built {output_root / zip_name}")


if __name__ == "__main__":
    main()
