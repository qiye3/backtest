# Factor Backtest

一个由 YAML 驱动的日频因子评价与分组回测项目。主入口按固定顺序运行 Factor、
group return、simple backtest、account backtest 和 plotter；是否执行每个阶段只由
主配置中的 `run` 布尔开关决定。

## 安装

需要 Python 3.9 及以上版本。在项目根目录执行：

```bash
python -m pip install .
```

## 运行内置示例

`configs/base_config.yaml` 使用仓库中的 synthetic 数据，可直接验证完整链路：

```bash
python -m src.cli --config configs/base_config.yaml
```

输出位于 `outputs/<factor_name>/`。每个因子固定保存四个结果文件：

```text
factor.parquet
group_return.parquet
simple_backtest.parquet
account_backtest.parquet
```

图像保存在同一因子目录的 `figures/`。回测结果默认只保存分组定义和汇总指标，
不保存回测曲线、调仓动作、逐股成交和换手明细，从而避免明细文件占用大量空间。
重复运行会覆盖同名结果，不产生带时间戳的新缓存。

如需在后续运行中恢复完整回测结果，将主配置中的开关设为：

```yaml
output:
  save_backtest_details: true
```

设为 `false` 时仍会正常生成本次运行的汇总 CSV 和图像，因为绘图直接使用内存中的
完整回测结果。

## 使用真实数据

复制或修改 `configs/base_config.yaml`：

- 将 `market_data.source_root` 指向符合数据说明目录结构的原始数据根；
- 将 `market_data.cache_root` 指向需要复用的市场面板缓存根目录；
- 按研究区间修改各阶段日期；
- 将 `factors.config_directory` 指向需要批量运行的 Factor YAML 目录；
- 用 `run` 下的五个布尔值选择阶段；
- 用 `output.save_backtest_details` 选择是否将完整回测明细写入 Parquet，默认关闭；
- 原始数据或字段配置改变后，将 `run.refresh_market_data` 设为 `true` 刷新缓存。

市场面板缓存保存在 `data/<主配置文件名>/`。关闭 Factor 阶段时，下游会从输出目录
恢复 `factor.parquet`。只有启用 `output.save_backtest_details` 后，plotter-only 才能从
回测 Parquet 恢复曲线并重新绘图；默认的汇总结果仍可用于读取和比较回测指标。

## Factor YAML

每个 YAML 显式声明可导入模块、类名和构造参数：

```yaml
name: return_20d
implementation:
  module: src.factors.ExampleFactor
  class: ExampleFactor
params:
  lookback_days: 20
```

配置目录中的所有 `*.yaml` 会按文件名排序后动态导入并批量计算。

## 测试与检查

```bash
python -m unittest discover -s tests -v
ruff check src examples scripts tests
```

运行静态检查前可通过 `python -m pip install '.[dev]'` 安装开发依赖。

内置端到端测试覆盖原始 CSV、市场缓存、动态 Factor、并行评价、两类回测、结果恢复和
四类图像输出。
