# Factor Backtest · 中证1000统一策略账户 v4

本项目保留日频因子计算、IC/RankIC和分组研究；正式策略回测统一使用分钟成交与持续现金账户，不再运行旧 `simple` 加法累计或旧 `account` 回测引擎。**普通策略是主入口，因子分层仅是可选的快速评估方式。**

- 直接配置策略类：`configs/unified_strategy_csi1000.example.yaml`，`targets.mode: strategy`。
- 使用既有策略目标文件：`targets.mode: strategy_output`（`target_weights.parquet`）。
- 可选因子分层：`configs/unified_factor_layers_csi1000.example.yaml`，`targets.mode: factor_layers`，各层独立现金账户和每日复利净值。
- 每日事后模拟盘：`configs/paper_csi1000.example.yaml`，支持按文件载入每天的目标、连续账户更新。

**完整v4架构、配置字段、交易约束和输出说明：[`docs/unified_backtest_v4.md`](docs/unified_backtest_v4.md)。**

## 运行入口

```bash
python -m pip install -e .
python -m scripts.run_minute_backtest --config configs/unified_strategy_csi1000.example.yaml
python -m scripts.run_minute_backtest --config configs/unified_factor_layers_csi1000.example.yaml
python -m scripts.run_daily_paper --config configs/paper_csi1000.example.yaml --date 2026-11-12
```

示例配置文件中的 `/REPLACE/` 路径需要按实际数据位置设置。股票池固定为当日有效中证1000成份（000852.SH），固定时间窗可以配置任何支持的有效交易分钟。交易委托股数按主板、创业板和科创板分别处理，成交数量允许发生零股部分成交。每个账户使用 `unit_nav = nav / initial_capital` 的复利净值累计方式。

## 数据和账户说明

分钟行情使用 `data/minute_bars/YYYY/YYYY-MM-DD.parquet`（每交易日一文件）的原始未复权价格和成交量，时间戳为北京时间每根分钟K线的结束时刻。日度涨跌停价格、停牌状态和公司行为由独立辅助数据提供。数据抓取沿用 `scripts.run_daily_paper` 的免费AKShare增量接口；原有日频因子研究与分组评价不依赖分钟撮合账户。

固定窗口成交的 `execution.order_time` 可以在有效交易时段中自定义，`execution.window_bars` 表示发单后可使用的已结束分钟根数。历史回测与逐日事后模拟均采用相同的 `src.intraday.execution` 撮合规则及 `src.intraday.engine` 现金持仓记账规则。

净值、订单和持仓等输出字段、历史指数成份格式、日频策略接口、所有配置字段详见 [`docs/unified_backtest_v4.md`](docs/unified_backtest_v4.md)，数据更新和每日账户字段也统一写在这份 v4 文档中。

## v4 变更

- 正式账户只保留固定成交时间窗，`execution.order_time` 自定义发单时间，`execution.window_bars` 指定随后撮合的分钟数；移除 `bar_delay` 等失效兼容参数。
- 09:31 发单从上日收盘价生成委托；若缺少必要的前日价格，明确报错，避免无订单也标记执行成功。
- 每日事后账户仅下载实际持仓、当前目标和待补单股票；日终只保存每日快照，避免重复生成无用分钟持仓明细。
- 持仓缺少可用估值价格时终止估值，不按零估值；关键股票的成交窗口行情缺失可被发现并补齐。
- 日频旧 `simple/account` 回测入口、阶段配置、无效包装脚本已清理；日频因子评价仍保留。

## 运行条件

项目依赖包含 pandas、numpy、PyYAML、pyarrow 等库。WSL工作站需提供真实中证1000历史成份区间文件和相应分钟行情数据。免费接口的短历史窗口不能用来恢复很久以前缺失的一分钟K线，也不能由分钟价量准确确定涨停板排队位置。


## 工作站自动分钟线更新

运行目录为 `/home/qiye/zxy/backtest`，Python 环境为 `zxy_py310`。
用户 crontab 在北京时间每日16:30启动中证1000一分钟行情下载，18:30和20:30重试。
脚本按周末与行情最近交易日期识别休市日，使用锁文件控制单实例，支持逐股票断点续传。
当日已发布文件中的空数据股票会通过 v4 增量逻辑重新抓取。

手动入口为 `bash /home/qiye/zxy/backtest/scripts/run_daily_minutes.sh`。
行情使用腾讯分钟K线与累计成交额差分，按每次请求间隔1.1秒限速。
股票池保存中证指数官网每日观测快照，行情清单逐股票记录来源和异常分钟缺口。
数据目录为 `/home/qiye/zxy/data/minute_bars`，股票覆盖率达到97%后发布日文件。

完成邮件发送至 `783829986@qq.com`，按交易日保存发送回执。
SMTP 授权文件位于 `/home/qiye/.config/backtest/qq_smtp_authorization`，权限为600。
日志和状态位于 `/home/qiye/zxy/logs/backtest/`，分别为 `daily_minutes.log` 和 `latest_minutes.json`。
工作站开机且WSL运行时执行定时更新。
