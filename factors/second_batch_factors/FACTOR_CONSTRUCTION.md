# 2026-09-21 第二批新数据因子实现说明

本目录实现分红、业绩快报、董监高交易、客户供应商与主营构成四类数据的 32 个因子。
每个 YAML 对应一个独立经济信号，不额外铺设窗口期或 Z-score 变体；框架仅统一输出
`raw` 与 `industry_neutral` 两个版本。

研究口径详见：

- `/Users/qiye/Desktop/docs/Work/TK/基本面/02_第二批_候选/20260921_分红因子构造表.md`
- `/Users/qiye/Desktop/docs/Work/TK/基本面/02_第二批_候选/20260921_业绩快报因子构造表.md`
- `/Users/qiye/Desktop/docs/Work/TK/基本面/02_第二批_候选/20260921_董监高交易因子构造表.md`
- `/Users/qiye/Desktop/docs/Work/TK/基本面/02_第二批_候选/20260921_客户供应商与主营构成因子构造表.md`

## 1. 时间口径

- 分红方案、董监高交易均从公告后的下一交易日生效。
- 业绩快报直接使用数据层的 PIT 面板，公告事件只在其有效状态首次出现或发生更正时生成。
- 正式财报修正只在正式财报已进入 PIT 面板后计算。
- 客户、供应商和主营构成明细没有独立公告日，因此以同公司、同报告期正式财报的首次
  PIT 公告日作为保守代理，再移动到下一交易日；匹配不到的记录直接丢弃，绝不按报告期回填。
- 分红收益率的价格基准使用公告日前最近交易日收盘价；内部人历史信号质量只在事件后
  60 个交易日完整走完时入账。

## 2. 因子清单与经济逻辑

### 2.1 分红

| 因子 | 核心构造 | 经济逻辑 |
|---|---|---|
| `announced_dividend_yield` | 每股现金分红 / 公告前收盘价 | 衡量新方案相对股价提供的现金回报 |
| `dividend_growth_yoy` | 本期普通 DPS / 上年同期 DPS - 1 | 捕捉管理层提高股东回报的增量信息 |
| `dividend_payout_ratio` | 现金分红总额 / 同期归母净利润 | 区分高分红与透支利润的分红 |
| `dividend_cash_coverage` | 经营现金流 / 现金分红总额 | 检验分红是否得到真实现金创造支持 |
| `dividend_cut_event` | DPS 同比下降至少 30%，或方案取消 | 识别现金回报恶化和潜在经营压力 |
| `realized_dividend_yield_ttm` | 过去 252 日已除息普通 DPS / 当日股价 | 只计已经兑现的股息，避免方案落空 |
| `dividend_stability_5y` | 五年 DPS 变异系数取负 | 奖励跨周期稳定、可预测的分红能力 |
| `dividend_sustainability_composite` | 收益、增长、覆盖、稳定性截面分位合成，并惩罚削减和极端支付率 | 综合识别高而可持续的分红，而非单纯追逐高股息 |

### 2.2 业绩快报

| 因子 | 核心构造 | 经济逻辑 |
|---|---|---|
| `express_consensus_surprise` | 快报利润相对公告前一致预期的偏离 | 衡量市场尚未定价的盈利信息 |
| `express_notice_surprise` | 快报利润相对同报告期预告区间中值的偏离 | 捕捉公司自己此前指引之外的变化 |
| `express_profit_growth` | 快报利润同比增长 | 提前刻画年度盈利景气度 |
| `express_revenue_growth` | 快报收入同比增长 | 区分利润增长是否有收入扩张支撑 |
| `express_net_margin_change` | 快报净利率同比变化 | 反映成本效率和盈利质量改善 |
| `express_profit_revenue_gap` | 利润增速 - 收入增速 | 衡量经营杠杆或利润质量背离 |
| `express_final_revision` | 正式财报利润相对快报利润的修正 | 识别快报高估或低估最终结果的偏差 |
| `historical_express_reliability` | 历次正式修正绝对值取负后的扩展均值 | 奖励历史快报与最终财报更一致的公司 |

### 2.3 董监高交易

| 因子 | 核心构造 | 经济逻辑 |
|---|---|---|
| `insider_net_buy_intensity_60d` | 60 日主动买卖流通股比例净和 | 用交易规模衡量内部人的净信心 |
| `clustered_insider_buying_60d` | 60 个自然日内不同主动买入主体数 | 多位内部人同时买入比单人交易信息更强 |
| `insider_buy_event` | 主动直接买入事件脉冲 | 捕捉内部人用真金白银表达的正面观点 |
| `insider_sell_event` | 主动直接卖出事件脉冲 | 识别潜在估值压力或基本面担忧 |
| `insider_trade_price_gap` | 买卖方向 ×（成交价 / 同期均价 - 1） | 衡量内部人是否愿意以更激进价格成交 |
| `insider_remaining_holding_ratio` | 交易后持股比例 | 区分象征性交易与仍有较高利益绑定的交易 |
| `insider_trade_reason_group` | 主动买卖赋正负分，被动原因归零，非本人折半 | 将交易动机和人与公司的关系纳入信号强弱 |
| `historical_insider_signal_quality` | 事件方向 × 后 60 日收益的成熟事件扩展均值 | 用只在事后可知时点入账的历史记录衡量内部人信息质量 |

### 2.4 客户供应商与主营构成

| 因子 | 核心构造 | 经济逻辑 |
|---|---|---|
| `top5_customer_share` | 前五大客户披露占比之和 | 衡量收入对大客户的依赖程度 |
| `customer_concentration_change` | 客户集中度同比变化 | 捕捉客户议价权和收入脆弱性的边际变化 |
| `customer_churn` | 相邻年度前五大客户集合的 Jaccard 距离 | 识别核心客户关系是否发生剧烈更替 |
| `top5_supplier_share` | 前五大供应商披露占比之和 | 衡量采购端集中和供应中断风险 |
| `supplier_concentration_change` | 供应商集中度同比变化 | 捕捉采购依赖程度的边际变化 |
| `customer_supplier_dependence` | 客户与供应商集中度截面分位均值 | 识别上下游两端同时受制于少数伙伴的公司 |
| `high_margin_segment_share_change` | 高于公司加权平均毛利率的产品收入占比同比变化 | 衡量收入结构是否向更高质量业务迁移 |
| `overseas_revenue_share_change` | 海外收入 / 同期营业收入的同比变化 | 衡量国际业务暴露和地域结构变化 |

## 3. 配置与运行

复制 `run_config.example.yaml`，把 `market_data.source_root` 替换为真实数据目录，然后在
项目根目录运行：

```bash
python -m src.cli --config factors/second_batch_factors/run_config.example.yaml
```

正式运行前仍需用真实 CSV 表头核对 Wind 字段名和业务枚举。当前实现使用数据字典字段，
本地缓存中没有第二批正式源文件，因此现阶段的验证覆盖合成数据、PIT 时点、公式接口和
32 份配置，不代表已经验证真实数据覆盖率。
