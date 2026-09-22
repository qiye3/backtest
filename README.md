# Factor Backtest

一个由 YAML 驱动的日频因子评价与分组回测项目。主入口按固定顺序运行 Factor、
group return、simple backtest、account backtest 和 plotter；是否执行每个阶段只由
主配置中的 `run` 布尔开关决定。

## 安装

需要 Python 3.9 及以上版本。在项目根目录执行：

```bash
python -m pip install .
```

## 准备 Wind 正式数据

原始 Wind Parquet 先整理成框架原生的年度 CSV 和指数成员目录：

```bash
python -m scripts.prepare_wind_formal_data \
  --wind-cache-root /Users/qiye/Desktop/wind_cache \
  --output-root /Users/qiye/Desktop/wind_cache/formal_factor_backtest \
  --start 2024-01-02 \
  --end 2026-09-09
```

整理后的目录完全遵循 `src.data.load_data` 的正式输入契约：

```text
formal_factor_backtest/
├── data_quality.json
├── index/
│   ├── members/{000906.SH,000852.SH}.csv
│   └── prices/000906.SH_YYYY.csv
└── stock/daily_quote/quote_YYYY.csv
```

当前源数据只提供 2026-09-08 成份快照，因此成员 CSV 明确使用静态股票池，历史结果
存在生存者偏差；详细口径记录在整理目录的 `data_quality.json`。

### 同步历史指数成份

`scripts.sync_index_members` 把成份数据源与正式回测文件解耦。真实数据根遵循参考数据
字典的 `index/members/<code>.csv` 布局；同步后统一校验日期、重复和重叠区间，并输出
正式五字段成员文件：

```bash
python -m scripts.sync_index_members \
  --source filesystem \
  --source-root /path/to/【指数增强策略】数据获取/data \
  --output-root /Users/qiye/Desktop/wind_cache/formal_factor_backtest \
  --index-code 000906.SH \
  --index-code 000852.SH
```

本机没有外部数据根时，可用 deterministic synthetic 后端验证接口和 PIT 展开链路：

```bash
python -m scripts.sync_index_members \
  --source synthetic \
  --output-root /Users/qiye/Desktop/wind_cache/synthetic_index_members_formal \
  --index-code 000906.SH \
  --index-code 000852.SH \
  --start 2010-01-01 \
  --end 2026-09-09
```

synthetic 文件包含定期调入和调出区间，只用于接口、PIT 股票池和自动化测试，不能
替代真实历史成份数据得出研究结论。未来接入 taidb 时实现同一个
`IndexMemberSource.read()` 合同即可，正式框架无需修改。

## 运行正式框架链路

`configs/base_config.yaml` 已指向整理后的 Wind 数据。因子计算、分组收益、IC、两类
回测和绘图全部由正式 CLI 编排：

```bash
python -m src.cli --config configs/base_config.yaml
```

正式结果按用途分开保存：

```text
outputs_wind/
├── config_snapshot.yaml
├── factors/<factor_name>/
├── strategies/<strategy_name>/
└── summaries/
```

因子目录包含 `factor.parquet`、按保留开关生成的评价或回测 Parquet，以及因子图；
策略目录包含 `target_weights.parquet`、按保留开关生成的策略回测 Parquet，以及策略图。
跨因子和跨策略汇总表统一放在 `summaries/`。

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

`examples/data/` 中的 compact synthetic 数据仅作为自动化测试 fixture，不再是项目
默认数据源。端到端测试仍用它覆盖原始 CSV、市场缓存、动态 Factor、并行评价、两类
回测、结果恢复和四类图像输出，从而保证测试不依赖本机 Wind 数据。
