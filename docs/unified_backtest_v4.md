# 中证1000统一策略回测 v4

## 1. 统一架构与定位

正式投资组合的唯一成交与账户逻辑为 `src.intraday.engine.MinuteBacktestEngine` +
`src.intraday.execution.ExecutionModel`。日频因子分析（IC、RankIC、分组未来收益）继续保留在
`src/group_return/`，用于筛选因子；**因子分层不再是正式回测的必要输入**。

正式回测支持三类目标输入：

1. `targets.mode: strategy`：按配置动态加载策略类（提供 `on_day_close()`），在每日行情完整后生成目标权重。适合独立编写、直接配置特定策略。
2. `targets.mode: strategy_output`：读取原有 `src.strategy.io` 输出的 `target_weights.parquet`（`date,stock_code,target_weight,rebalance_interval`），不改已有策略研究代码。
3. `targets.mode: factor_layers`：**可选**的因子分层模式；将每日中证1000成份按因子值分成G01…G10，每层各开一个独立资金账户，统一执行分钟撮合并保存日终净值曲线。

`targets.mode: file` 仍可读取标准目标长表 `signal_timestamp,code,target_weight`，其含义分别为信号生成时刻、标准A股代码和目标账户权重。

所有正式回测使用日频目标、次交易日配置时刻发单、分钟行情模拟成交、日终账户估值。
净值 `unit_nav = nav / initial_capital`；累计收益 `cumulative_return = unit_nav - 1`。
区间收益、年化、回撤与换手以同一现金账户数据计算，**不再累计相加不同调仓周期的收益**。

旧 `src/backtest/simple.py`、`src/backtest/account.py` 已删除。旧 `src.backtest.engine` 的失效函数名、旧 CLI 和配置阶段也已清理；保留 `group_return` 作为独立日频因子评价链路。正式策略账户仅由分钟执行引擎产生。

## 2. 运行示例

```bash
cd /home/qiye/zxy/backtest
python -m pip install -e .
# 自定义 strategy 类：默认只运行单个策略账户
python -m scripts.run_minute_backtest --config configs/unified_strategy_csi1000.example.yaml
# 已有策略输出结果：不必把策略改写成 on_day_close 类
python -m scripts.run_minute_backtest --config configs/unified_strategy_output_csi1000.example.yaml
# 仅在需要做因子分层时运行十个独立账户
python -m scripts.run_minute_backtest --config configs/unified_factor_layers_csi1000.example.yaml
# 保留原每日事后模拟账户入口（支持 file、strategy_output）：
python -m scripts.run_daily_paper --config configs/paper_csi1000.example.yaml --date 2026-11-12
```

上述v4配置中的 `/REPLACE/...` 路径须按工作站实际数据填写。
已有策略输出文件的示例是 `configs/unified_strategy_output_csi1000.example.yaml`。
`strategy` 配置的示例模块 `examples.intraday.daily_vwap_momentum.DailyVwapMomentumStrategy`
仅展示 `on_day_close(trading_date, bars, context) -> DataFrame` 接口，不是推荐的实盘策略。
返回值必须有 `code`（股票代码）与 `target_weight`（完整目标权重）；
`context.universe_codes` 代表当天有效的中证1000成份。T日信号从T+1交易日起生效。

**逐日 paper 入口目前接受策略输出文件，不会跨进程直接恢复策略类内部状态。**
要让指定策略接入逐日模拟，请先每天生成/追加其目标文件，再使用 `targets.mode: strategy_output`
或标准 `file` 模式。历史正式回测可直接使用 `targets.mode: strategy`。

## 3. 模拟成交规则与数量约束

账户当前仅覆盖沪深A股多头、现金交易。中证1000历史成份是唯一正式股票池
`000852.SH`，按纳入日起（含）至剔除日（不含）确定可选股票，调出成份的老仓位可继续估值和清仓。

买卖**委托数量**按股票所属板块分别确定，而不再套用一个全局100股数量规则：

| 交易板块 | 买入申报 | 卖出申报 | 限价单笔最大数量 |
|---|---|---|---|
| 沪深主板 | 100股及其整数倍 | 整手卖出，剩余零股按交易所规则一次性申报 | 1,000,000股 |
| 创业板 | 100股及其整数倍 | 整手卖出，剩余零股按规则一次性申报 | 300,000股 |
| 科创板 | 不少于200股，之后可逐股递增 | 不少于200股，余额不足200股时一次性卖出 | 100,000股 |

*以上适用于本模拟约定的限价申报；不同类型申报、风险警示股票额外限制、券商权限仍需进一步处理。*
交易所允许合法委托形成任意整数股的部分成交；**不能把每笔成交再按100股取整**。
现金和持仓使用整数股，买入不足资金时允许发生部分成交；卖单受可卖数量和T+1限制。
单笔委托上限通过拆单处理，且同一股票同一分钟的容量不会因拆单重复使用。

价格使用分钟 `vwap` 加方向不利滑点，再转为A股0.01元合法报价网格。
`execution.require_daily_limit_data: true` 时，分钟撮合必须有有效的当日涨跌停价；
价限数据缺失则该分钟不成交。涨停买入、跌停卖出采用保守不成交逻辑；
停牌、零成交量亦不成交。分钟 `max_participation_rate` 控制同一股票模拟成交股数上限。
现金分配按照各订单报价需求分摊，卖出款从下一分钟起允许用于买入。

分钟行情无法重建委托簿、排队位置与实际对手盘，故逐笔真实成交仍存在误差。
本版是**接入实盘前的交易模拟模型**，不包含券商下单协议、风控审批、撤改单确认、板块权限和实时行情订阅；不能直接作为生产实盘交易网关。

交易规则参考：
- 上海证券交易所2026年《交易规则》 https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml
- 上交所科创板规则 https://edu.sse.com.cn/tib/qa/
- 深圳证券交易所2026年《交易规则》 https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf

## 4. 重要配置字段

| 字段 | 含义 |
|---|---|
| `run_name` | 本次运行输出目录名 |
| `output_root` | 运行产物的根目录 |
| `universe.index_code` | 中证1000固定值 `000852.SH` |
| `universe.members_root` | 历史成份区间CSV所在目录，内含`000852.SH.csv` |
| `data.minute_root` | 按交易日存储分钟Parquet的目录 |
| `data.daily_root` | 公司行为日线参考数据目录，可为空 |
| `data.cache_root` | 分钟数据可重建缓存目录 |
| `data.universe_name` | 缓存子目录命名标识 |
| `data.start_date` / `data.end_date` | 历史回测行情起止日期 |
| `data.daily_status_path` | `date,code,limit_up,limit_down,is_suspended`等日度交易状态文件 |
| `targets.mode` | 目标生成模式：`strategy`、`strategy_output`、`file`或可选的`factor_layers` |
| `targets.implementation.module` | 策略类所在的Python模块导入路径 |
| `targets.implementation.class` | 策略类名，该类要有`on_day_close()` |
| `targets.implementation.params` | 初始化策略类时传入的参数 |
| `targets.path` | 文件型目标或因子值来源的CSV/Parquet路径 |
| `targets.rebalance_interval` | `strategy_output`选用的调仓周期标识 |
| `targets.date_only_signal_time` | 仅有日期的信号映射到该时间，例如15:00:00 |
| `targets.layer_count` | 分层数量，默认10，仅分层模式使用 |
| `targets.factor_column` | 因子长表的数值列名，默认`factor_value`，仅分层使用 |
| `targets.descending` | `true`表示G01是最高因子组，否则最低组 |
| `account.initial_capital` | 每个独立账户的初始现金，单位人民币元 |
| `account.rights_issue_policy` | 配股资金处理规则：`subscribe_or_fail`或`ignore` |
| `execution.order_time` | 模拟发单时间，自定义，如13:20:00 |
| `execution.window_bars` | 发单后可撮合的完整1分钟K线数量 |
| `execution.retry_unfilled_days` | 未成交目标在后续交易日继续尝试的次数 |
| `execution.slippage_bps` | 模拟VWAP不利滑点，1 bps=0.01% |
| `execution.max_participation_rate` | 模拟成交最多占对应股票分钟市场成交量的比例 |
| `execution.block_one_price_limit` | 没有有效价格限制信息时阻止一字分钟撮合 |
| `execution.enforce_t_plus_one` | 约束A股当天买入不能当天卖出 |
| `execution.require_daily_limit_data` | 要求提供有效日度涨跌停价，否则不允许模拟成交 |
| `costs.commission_rate` | 佣金费率 |
| `costs.minimum_commission` | 每笔委托最低累计佣金，人民币元 |
| `costs.transfer_fee_rate` | 过户费率 |
| `costs.stamp_duty_rate_before_20230828` | 2023-08-28之前卖出印花税费率 |
| `costs.stamp_duty_rate_from_20230828` | 2023-08-28起卖出印花税费率 |

数据下载与每日账户续跑的具体字段见下方第7节。

## 5. 输出文件

一次普通策略回测写入 `output_root/run_name/`：
`orders.parquet`（订单）、`fills.parquet`（实际成交）、`positions.parquet`（持仓快照）、
`nav.parquet`（账户逐日现金、市值、总权益）、`daily_nav.parquet`（日终净值和收益）、
`metrics.json`（绩效指标）及数据源快照元数据。输出文件随具体版本的保存器而变化。

因子分层模式在该目录下分别产生 `G01/`…`G10/` 的完整独立账户产物，
此外保存 `layer_daily_nav.parquet`（各层日期、账户权益、单位净值、复利累计收益与日收益率）
和 `layer_metrics.parquet`（各层绩效指标）。可以用 `layer_daily_nav.parquet`
的 `date/timestamp, group, unit_nav` 直接绘制每一层及汇总曲线。

日报 `run_daily_paper` 仍按 `days/YYYY-MM-DD/snapshot.json` 存储跨交易日可恢复账户状态，
`daily_nav.csv` 新增 `unit_nav`（净值除初始资金）和 `cumulative_return`（单位净值减1）。

## 6. 数据条件与运行边界

- 股票池历史成份、每日价格限制信息和分钟行情必须通过实际文件配置；本源码包不包含工作站约50GB行情。
- AKShare免费分钟数据只有较短的历史覆盖窗口，需要每天持续抓取；下载和账户推进使用现有脚本，不需要券商模拟盘API。
- 本地仅对独立撮合/账户模块进行了合成行情单元测试。全量历史Parquet读取与远端交易日增量链路需在具备`pyarrow`及真实分钟数据的WSL环境运行。

## 7. v4 清理、变更与每日账户字段

### 固定时间窗口和估值

正式回测只有固定窗口执行模式，配置 `execution.order_time`（策略发单时刻）和 `execution.window_bars`（随后用于成交的1分钟K线数量），运行时推导 `window_start/window_end`。已删除旧 `bar_delay`、`execution_delay_bars`、`lot_size`、`time_in_force`、`liquidate_at_end` 和手工 `window_start/window_end` 等配置；已有 YAML 如包含上述字段，需要删除后使用新字段。

09:31 发单允许从上一交易日已经取得的收盘价估算目标股数，不会读取09:31尚未结束的分钟价；缺少必要的前日参考价时明确报错。其他发单时刻要求当天发单前已取得的股票参考价，没有新价格的目标保留为待处理，后续交易日重新尝试。账户持仓缺少可信的历史价格时不会直接计为零。订单和成交始终是整数股，完整委托按股票板块的最小/最大申报股数检查，真实部分成交可以为不足100股的整数股。

### 分钟数据覆盖

每日账户只请求已有持仓、当前新目标以及允许补单的股票。下载时先读取既有日文件的股票集合，已经存在的股票无需重抓；对关键股票检查固定成交窗口内应有的分钟时间戳，若缺少则重新请求并补齐。日度状态已明确停牌的股票由调用方剔除该窗口检查。空接口结果不会留下永久无行情的缓存；真实数据写入前检查必需代码和窗口覆盖。

当天需要交易的所有股票都应使用真实未复权分钟行情；没有盘口委托队列时，涨停买不到、跌停卖不出仍按保守模型处理。免费接口约五个交易日的历史窗口无法补齐久远缺口。现阶段的每日账户需要提前生成策略目标文件；并未实现券商实盘接口。

### 逐日状态 `days/YYYY-MM-DD/snapshot.json`

| 字段 | 含义 |
|---|---|
| `date` | 模拟账户处理完的交易日期 |
| `configuration` | 影响成交计算的配置摘要，同一账户续跑时保持一致 |
| `universe_history_digest` | 已生效中证1000历史成员的内容摘要 |
| `previous_nav` | 上一交易日结束时的账户权益金额，元 |
| `end_nav` | 本交易日结束时的账户权益金额，元 |
| `daily_return` | `end_nav/previous_nav-1`，当日收益率 |
| `stale_price_positions` | 这一天未得到新价格、沿用此前已知价格估值的持仓列表 |
| `state.version` | 持续账户快照结构版本 |
| `state.previous_date` | 账户最后完成的日期 |
| `state.cash` | 日终可用现金，元 |
| `state.positions` | 各代码的整数股持仓和买入日期批次 |
| `state.last_prices` | 各代码最近一次已知的价格，元/股 |
| `state.last_price_dates` | 最新已知价格对应的交易日期 |
| `state.active_target_weights` | 最新有效目标组合的各股票权重 |
| `state.pending_target_codes` | 仍需尝试补单的股票代码 |
| `state.retry_days_used` | 已使用的补单交易日数量 |
| `state.last_applied_signal_timestamp` | 最后激活的信号时刻，用来避免重复激活 |
| `state.next_order_id` | 下次订单的递增编号 |

账户根目录 `daily_nav.csv` 还包含：`date`（交易日）、`previous_nav`（前日权益）、`nav`（日终权益）、`return`（日收益率）、`cash`（日终现金）、`position_count`（非零持仓股票数）、`stale_price_count`（沿用旧价格持仓数）、`unit_nav`（单位净值）和 `cumulative_return`（复利累计收益）。

逐日 Parquet 存档：`orders.parquet` 为委托及其成交状态，`fills.parquet` 为成交和交易成本，`positions.parquet` 为日终股份，`daily_nav.parquet` 为单日日终账户权益。公司行为和行情来源需按照实际数据文件配置。

### 免费分钟行情和来源清单

| 行情列 | 含义 |
|---|---|
| `timestamp` | Asia/Shanghai 时区的分钟K线结束时间 |
| `code` | 股票代码，例如 `000001.SZ` |
| `open` | 本分钟开盘价，元/股；数据源开盘价无效时可使用前根收盘价作格式补值 |
| `high` | 本分钟最高价，元/股 |
| `low` | 本分钟最低价，元/股 |
| `close` | 本分钟收盘价，元/股 |
| `amount` | 本分钟市场成交金额，元 |
| `volume` | 本分钟成交量，已从手转换为股 |
| `vwap` | 本分钟成交额除以股数得到的成交量加权均价，元/股 |

相邻 `.source.json` 字段：`source`（原始行情接口）、`date`（交易日）、`requested_codes`（本轮请求代码）、`present_codes`（已保存代码）、`empty_codes`（空响应代码）、`exempt_codes`（已知停牌而不要求窗口行情的代码）、`rows`（保存行数）、`timezone`（时区）、`price_adjustment`（复权方式）、`volume_unit`（成交量单位）、`amount_unit`（成交额单位）、`bar_timestamp`（K线时间语义）和 `min_coverage`（股票数量最低覆盖比例）。

### 验证范围

v4 源码保留了固定成交、订单有效股数、账户恢复、历史成份、免费接口异常恢复的合成行情测试。`pyarrow` 和远端真实行情文件仍是 Parquet 实际端到端运行的必要条件。
