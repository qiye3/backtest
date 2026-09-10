# 单因子评估与分组回测 v5

保留标准 Factor 构造与窗口变体，也可直接读取外部因子矩阵。每个因子独立完成多周期未来收益评估、简易累加回测、分组独立账户回测和绘图。支持多因子并行、按模块运行；三个计算模块分别定义日期、股票池、分位区间、采样或调仓周期。

## 安装与运行

需要 Python 3.10+。解压后在本项目根目录运行：

```bash
python -m pip install -r requirements.txt
python -m src.cli --config configs/experiment_v5.yaml
```

先修改配置中的数据路径、日期和待运行因子。默认运行 `run.modules`，也可以显式选择：

```bash
python -m src.cli --config configs/experiment_v5.yaml --modules factors
python -m src.cli --config configs/experiment_v5.yaml --modules group_return plotting
python -m src.cli --config configs/experiment_v5.yaml --modules simple_backtest account_backtest
python -m src.cli plotting --config configs/experiment_v5.yaml
```

仅运行下游模块时，事先生成因子文件，或配置 `factor_input.source: external`。`plotting` 可只读之前保存的结果，不需要原始行情和因子文件。选中多个模块时按 Factor → 评估 → 简易 → 账户 → 绘图的顺序执行；三个计算模块没有相互依赖。

## 不依赖真实数据的完整示例

```bash
python -m examples.make_demo --directory demo_workspace
python -m src.cli --config demo_workspace/demo.yaml
python -m unittest discover -s tests -v
```

示例会生成 100 只虚构股票，计算两个标准 Factor，并行输出每个因子的四张图。示例费用为单边 0.001，以便检查费前费后差异；正式模板默认费用为 0。图中明确标注 SYNTHETIC DATA。`examples/demo_output/` 是本次验证生成的图和指标摘录，不能解释为真实市场表现。

## 可选择的模块

| 模块 | 输入与计算 | 输出 |
|---|---|---|
| `factors` | 原始数据 → 固定公式 → 因子内部窗口变体 | 日期×股票因子矩阵、构造配置、文件摘要 |
| `group_return` | 最终因子值、历史股票池、固定时点价格 | 多个未来周期的分组收益、总体 IC/RankIC 序列与汇总 |
| `simple_backtest` | 本模块截面分组 → 目标权重 → 漂移与扣费 | 各调仓周期的收益累加曲线、换手和指标 |
| `account_backtest` | 本模块截面分组 → 每组一个独立账户 | 每日/调仓日净值、现金、持仓、成交、换手和指标 |
| `plotting` | 各模块保存的结果文件 | 分布图、评估图、简易回测图、账户回测图 |

分组示例可以分别写在各模块内：

```yaml
group_return:
  grouping:
    quantile_edges: [[0.9, 1], [0.99, 1]]
simple_backtest:
  grouping:
    quantile_edges: [[0, 0.5], [0.5, 1]]
account_backtest:
  grouping:
    quantile_edges: [[0, 0.1], [0.1, 0.9], [0.9, 1]]
```

每个区间独立选股，可以重叠。上例评估只观察最高 10% 与最高 1%，不会补出其他组。账户之间不共享资金；同一股票可同时进入两个重叠组。

## 代码位置

| 路径 | 职责 |
|---|---|
| `src/config.py` | 合并默认值，按运行模块校验配置 |
| `src/cli.py`、`src/pipeline.py` | 命令行、模块调度、按因子并行、结果保存 |
| `src/data/` | 行情、交易日历、历史成员、财务事件、外部因子和参考价格 |
| `src/factors/base.py`、`registry.py`、`builder.py` | 标准 Factor 接口、注册、构造及窗口变体保存 |
| `src/factors/operators.py` | 因子自己的固定变换和平滑 |
| `src/group_return/grouping.py` | 可复用的截面分组算法；分组配置由调用模块传入 |
| `src/group_return/evaluator.py` | 未来收益、两层聚合、IC/RankIC |
| `src/backtest/targets.py` | 按本模块配置生成目标权重 |
| `src/backtest/rebalance.py` | 漂移权重、精确费用计算及可选成交限制 |
| `src/backtest/simple.py`、`account.py` | 两种回测引擎 |
| `src/backtest/events.py`、`metrics.py` | 估值事件、输出频率和绩效定义 |
| `src/plotting/` | 四种图，仅消费计算结果 |
| `configs/factors/` | 14 个标准因子、20 个窗口变体 |
| `tests/` | 计算、边界、独立运行、并行和绘图的回归验证 |

## 重要计算约定

- 默认周五收盘使用当天因子值并按同一收盘价调仓。`execution.policy: ideal` 表示理想成交假设；含收盘信息的因子与同收盘成交具有同时性，这组配置适合约定口径的因子研究。可通过 `factor_lag_days`、`trade_price` 和调仓星期调整时序。
- 平滑只在 Factor 内发生。评估和回测均消费最终因子值，未来周期列表不会改变因子或账户调仓周期。
- `group_return` 不检查停牌、涨跌停或模拟退出；收益端点固定为交易日历中的 t 和 t+h。缺价策略显式配置，补价来源留档，不能据未来缺价删除当期股票。
- 简易曲线按调仓段的费后收益相加；账户按持仓价值自然复利。两者分别使用同口径的基准曲线。
- 每次扣费前先按价格变化计算持仓漂移，买卖金额都收费，默认成本为 0。详细数学定义见计算说明。
- 默认账户遇到必需价格缺失即报错。选择 `previous_close` 是显式的历史参考价估值假设，不能代表真实可成交价格；可限制陈旧交易日数，输出中记录实际补价。
- 数据中成员退出日期沿用现有源约定：退出日仍是成员。可用真实交易日历补齐全市场行情缺失日。示例日历仅为虚构的工作日序列。

## 配置与文档

- `configs/experiment_v5.yaml`：完整配置，包括全部标准 Factor。
- `configs/*_only.yaml`：五个模块的独立入口示例，默认指向同一实验输出。
- `configs/external_independent_groups.yaml`：外部 CSV/Parquet 因子、多模块不同分组示例。
- [全部配置字段](docs/config_reference.md)、[计算定义](docs/calculation_methods.md)、[输出文件与指标](docs/output_reference.md)。
- [标准因子构造表](docs/factor_catalog.md)、[原始数据说明](docs/data_sources_reference.md)、[验证记录](docs/validation.md)。

## Python 与后续策略接口

```python
from src.config import load_config
from src.pipeline import run_one_factor

cfg = load_config('configs/experiment_v5.yaml', ['group_return'])
run_one_factor(cfg, 'my_factor', panel)  # panel: DatetimeIndex × 股票代码的数值 DataFrame
```

后续指数增强策略可以生成日期×股票的目标权重表，直接调用 `run_account(targets, market_data, account_config)`。权重按股票代码对齐；未提供的股票列补 0，每行权重和≤1，剩余为现金，全 NaN 行表示保持实际持仓。该接口支持直接传入权重，当前版本没有接入指数增强组合构建或自动优化。

多个进程会分别加载所需行情，内存不足时减小 `parallel.workers`。一个因子失败会记录错误；默认继续其他因子，最终进程仍以失败退出，避免把部分成功误认为全部完成。
