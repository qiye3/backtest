# Factor Backtest

一个由 YAML 驱动的日频因子评价与分组回测项目。主入口按固定顺序运行 Factor、
group return、simple backtest、account backtest 和 plotter；是否执行每个阶段只由
主配置中的 `run` 布尔开关决定。

## 分钟目标仓位回测

`src.intraday` 是独立于原 TK 日频链路的通用账户回测入口。策略只需输出长表目标
仓位，必需字段为 `signal_timestamp,code,target_weight`。日期型信号会使用 YAML 中的
`date_only_signal_time`；时间统一按 `Asia/Shanghai` 解析。当前第一阶段只支持多头、
无杠杆，单个时间点的权重和不能超过 1；未出现在新目标中的已有持仓视为目标为 0。
长区间运行按交易日流式读取，不需要把整个历史分钟表一次性放入内存。

```bash
python -m scripts.run_minute_backtest --config configs/minute.example.yaml
```

示例配置直接读取 `/home/qiye/zxy/data/stock_minute` 的每日 ZIP/7z，只抽取股票池内
CSV，并在 `data.cache_root/minute/<universe_name>/` 生成按日 Parquet 缓存。支持
`sh/600000.csv` 和 `YYYYMMDD/sh/600000.csv` 两种包内路径；240 根 bar 按结束时刻
重建为 `09:31–11:30`、`13:01–15:00`。日线参考数据既可为散装 XLSX，也可位于 ZIP
内部，红利、送股、转增和配股字段按每十股口径换算后在开盘前入账。缓存绑定源归档
的大小和修改时间，写入采用原子替换；源归档或解析规则变化时会自动重建。

默认成交模型使用 bar VWAP 加 5 bps 不利滑点，并限制为 bar 成交量的 10%。订单可
跨 bar 部分成交但日终撤单；同时执行佣金（万三、最低 5 元）、卖出印花税（
2023-08-28 前千一、之后万五）、过户费、100 股整手、现金约束和 T+1。零成交量 bar
不成交；若行情提供 `limit_up/limit_down` 则按涨跌停方向阻断，当前原始分钟文件没有
涨跌停字段时对 `high == low` 的一字 bar 采取保守阻断。

每次运行在 `output_root/run_name/` 保存配置快照、运行环境、Git 与依赖信息、数据质量
问题、指标以及 orders、fills、positions、nav、daily_nav 六套 Parquet 账本。`run_name`
已存在时会拒绝覆盖；结果先写临时目录，成功后才发布。

### 用分钟数据生成日频信号

把目标配置改为 `targets.mode: daily_minute_strategy`，并提供固定研究股票池和策略类：

```yaml
targets:
  mode: daily_minute_strategy
  universe_path: ../examples/data/minute_universe.csv
  implementation:
    module: examples.intraday.daily_vwap_momentum
    class: DailyVwapMomentumStrategy
    params:
      selected_count: 2
```

策略实现 `on_day_close(trading_date, bars, context)`，返回 `code,target_weight`。D 日
完整分钟数据只会生成 D 日收盘信号，最早在 D+1 的首个可成交 bar 执行，避免把未来 bar
带入信号。`--validate-only` 可先检查数据截止日、股票数量和策略入口：

```bash
python -m scripts.run_minute_backtest \
  --config configs/minute_strategy.example.yaml \
  --validate-only
```

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

日常数据同步使用独立增量入口，可一次传入多份共享市场缓存的配置：

```bash
python -m scripts.update_factor_cache CONFIG_1.yaml CONFIG_2.yaml
```

`--dry-run` 只报告数据来源和因子的预计更新方式，`--rebuild` 强制整套重建。
命令以原始文件路径、大小和纳秒修改时间识别新增及历史修订，只刷新变化来源；
日频年度来源从最早变化年份替换尾部，具有有界历史窗口的因子同步尾部重算。
默认全历史的自定义因子会安全回退为全量重算。正式执行后，状态和报告保存在
`market_data.cache_root/.state/` 与 `output.root/.state/`。

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

## 直接回测已有因子 Parquet

框架可以跳过 Factor 计算，直接读取一个或多个由本框架生成的原生日频
`factor.parquet`。在主配置中关闭因子阶段，并显式声明最终因子名与文件路径：

```yaml
run:
  factors: false
  group_return: true
  simple_backtest: true

factors:
  parquet_files:
    momentum_20d: /data/factors/momentum_20d/factor.parquet
    value_score: ../factor_inputs/value_score.parquet
```

相对路径以主配置文件所在目录为基准。`parquet_files` 与 `result_root` 互斥；前者
直接列出文件，后者继续用于复用完整的框架因子结果目录。输入文件始终只读，不会被
复制、覆盖或受 `output.save_parquet.factor` 控制，下游结果仍保存到
`output.root/factors/<factor_name>/`。

输入必须是单因子宽表：索引为唯一、升序且无时区的 `DatetimeIndex`，列为唯一股票
代码，值只能是数值或 `NaN`。本入口不接受 `date/ts/code` 分钟长表，也不会自动做
日频聚合、缺失填充或因子变体计算。输入因子仍按各评价和回测阶段配置的
`factor_lag_days` 读取；因子历史可得性和 PIT 正确性由输入文件生产流程保证。

## 分域研究

主配置可通过 `factors.domain_config` 引用独立 domains YAML。文件中的
`factor_names` 只选择需要分域的基础因子，其余因子仍按原配置计算；每个域作为与
`raw`、`industry_neutral` 同级的 `domain_<name>` variant，从共享的截面处理结果
直接生成。完整配置示例见 `configs/domains.example.yaml`。

需要为选中的每个基础因子分别生成域对比 overall 大图时运行：

```bash
python -m scripts.run_domain_research \
  --config /absolute/path/to/run.yaml
```

脚本只遍历 domains YAML 的 `factor_names`，共享一次 MarketData，并在
`output.root/<base_factor_name>/00_overall/` 下输出因子分布和四周分组收益大图。
正式长任务默认进入 tmux；本地前台运行时增加 `--foreground`，只校验配置时使用
`--dry-run`。

## 测试与检查

```bash
python -m unittest discover -s tests -v
ruff check src examples scripts tests
```

运行静态检查前可通过 `python -m pip install '.[dev]'` 安装开发依赖。

`examples/data/` 中的 compact synthetic 数据仅作为自动化测试 fixture，不再是项目
默认数据源。端到端测试仍用它覆盖原始 CSV、市场缓存、动态 Factor、并行评价、两类
回测、结果恢复和四类图像输出，从而保证测试不依赖本机 Wind 数据。
