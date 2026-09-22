# 质量因子构造表（2026-09-16）

本表逐项对应 config/*.yaml，公式依据 code/base_factors.py、code/utils.py 与 code/QualityFactor.py。字段名保留 Wind 原始口径，便于回查数据源。

## 统一口径

- 跨报表比率使用安全除法：分母非有限或绝对值不大于 1e-12 时返回缺失。
- 季度变体按 REPORT_PERIOD 的自然季度事件计算，并从公告日起延续到下一次公告。
- 名称含 stability 的因子当前输出滚动标准差，未反向；值越大表示波动越大。
- 当前 52 个 YAML 均配置为 rolling_mean_window=1、neutralize=false、不缩尾、reverse=false。

## 因子构造表

| factor_name | 核心构造逻辑（使用指标） | 处理方式 |
|---|---|---|
| <code>accounts_receivable_to_revenue</code> | 应收账款 ACCOUNTS_RECEIVABLE / 营业总收入 TOT_OPER_REV，仅在两表报告期一致时计算。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>accounts_receivable_to_revenue_yoy</code> | 应收账款 ACCOUNTS_RECEIVABLE / 营业总收入 TOT_OPER_REV，仅在两表报告期一致时计算。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>accruals_to_assets</code> | （归母净利润 NET_PROFIT_EXCL_MIN_INT_INC－经营现金流 NET_CASH_FLOWS_OPER_ACT）/ 总资产 TOT_ASSETS，三表报告期一致。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>accruals_to_assets_change</code> | （归母净利润 NET_PROFIT_EXCL_MIN_INT_INC－经营现金流 NET_CASH_FLOWS_OPER_ACT）/ 总资产 TOT_ASSETS，三表报告期一致。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage</code> | 分析师覆盖人数 prediction_number。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_forecast_revision</code> | 13 周一致预期净利润增速调整 con_npgrate_13w。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>asset_turnover</code> | Wind 总资产周转率 S_FA_ASSETSTURN。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>capex_to_ocf</code> | 购建长期资产现金支出 CASH_PAY_ACQ_CONST_FIOLTA / 经营现金流 NET_CASH_FLOWS_OPER_ACT。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>capex_to_ocf_3y_mean</code> | 购建长期资产现金支出 CASH_PAY_ACQ_CONST_FIOLTA / 经营现金流 NET_CASH_FLOWS_OPER_ACT。 | 季频 PIT 公告状态延续到下一次公告；连续 12 个自然季度均值；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>cash_realization_rate</code> | Wind 经营现金流/利润指标 S_FA_OCFTOPROFIT。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>current_ratio</code> | Wind 流动比率 S_FA_CURRENT。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>debt_to_assets</code> | Wind 资产负债率 S_FA_DEBTTOASSETS。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>debt_to_assets_yoy</code> | Wind 资产负债率 S_FA_DEBTTOASSETS。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>deducted_profit_to_profit</code> | Wind 扣非利润/利润指标 S_FA_DEDUCTEDPROFITTOPROFIT。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>deducted_profit_to_profit_stability_2y</code> | Wind 扣非利润/利润指标 S_FA_DEDUCTEDPROFITTOPROFIT。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>equity_multiplier</code> | Wind 权益乘数 S_FA_ASSETSTOEQUITY。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>fcf_turning_positive</code> | Wind 企业自由现金流 S_FA_FCFF。 | 季频 PIT 公告状态延续到下一次公告；本季度大于 0 且上季度小于等于 0 时记 1，否则记 0。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>fcf_yield</code> | 企业自由现金流 S_FA_FCFF /（总市值 S_VAL_MV×10000＋净债务 S_FA_NETDEBT）。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>goodwill_to_equity</code> | 商誉 GOODWILL / 归母股东权益 TOT_SHRHLDR_EQY_EXCL_MIN_INT。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>gross_margin</code> | Wind 销售毛利率 S_FA_GROSSPROFITMARGIN。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>gross_margin_stability_2y</code> | Wind 销售毛利率 S_FA_GROSSPROFITMARGIN。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>gross_margin_trend</code> | Wind 销售毛利率 S_FA_GROSSPROFITMARGIN。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>interest_debt_to_ocf</code> | 净债务 S_FA_NETDEBT / 经营现金流 NET_CASH_FLOWS_OPER_ACT，仅在报告期一致时计算。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>inventory_change_to_assets</code> | （本季度存货 INVENTORIES－上季度存货）/ 本季度总资产 TOT_ASSETS。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>net_margin</code> | Wind 销售净利率 S_FA_NETPROFITMARGIN。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>net_margin_stability</code> | Wind 销售净利率 S_FA_NETPROFITMARGIN。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ocf_to_net_profit</code> | 经营现金流 NET_CASH_FLOWS_OPER_ACT / 归母净利润 NET_PROFIT_EXCL_MIN_INT_INC，仅在报告期一致时计算。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ocf_to_net_profit_stability_2y</code> | 经营现金流 NET_CASH_FLOWS_OPER_ACT / 归母净利润 NET_PROFIT_EXCL_MIN_INT_INC，仅在报告期一致时计算。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ocf_to_revenue</code> | Wind 经营现金流/营业收入指标 S_FA_OCFTOOR。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ocf_to_revenue_stability_2y</code> | Wind 经营现金流/营业收入指标 S_FA_OCFTOOR。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>operating_margin</code> | Wind 营业利润率指标 S_FA_OPTOGR。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>operating_margin_stability_2y</code> | Wind 营业利润率指标 S_FA_OPTOGR。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pb_roe_composite</code> | 高 ROE 与低 PB 的每日截面百分位各占 1/2；两项都有效才保留。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quality_composite</code> | ROE、ROIC、经营现金流/收入取正向截面百分位，资产负债率取反向百分位，至少 3 项有效后等权平均。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quick_ratio</code> | Wind 速动比率 S_FA_QUICK。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roa</code> | Wind ROA S_FA_ROA。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roa_stability_3y</code> | Wind ROA S_FA_ROA。 | 季频 PIT 公告状态延续到下一次公告；连续 12 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_cv_3y</code> | Wind ROE S_FA_ROE。 | 季频 PIT 公告状态延续到下一次公告；连续 12 个自然季度样本标准差 / 均值绝对值；窗口缺季度或均值近零则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_deducted</code> | Wind 扣非 ROE S_FA_ROE_DEDUCTED。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_deducted_stability_2y</code> | Wind 扣非 ROE S_FA_ROE_DEDUCTED。 | 季频 PIT 公告状态延续到下一次公告；连续 8 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_expected</code> | 一致预期 ROE con_roe。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_expected_change</code> | 一致预期 ROE con_roe。 | 当前值减去 65 个交易日前的值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_level</code> | Wind ROE S_FA_ROE。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_q</code> | Wind 单季度 ROE S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_qoq</code> | Wind 单季度 ROE S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_stability_3y</code> | Wind ROE S_FA_ROE。 | 季频 PIT 公告状态延续到下一次公告；连续 12 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_stability_5y</code> | Wind ROE S_FA_ROE。 | 季频 PIT 公告状态延续到下一次公告；连续 20 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roe_yoy</code> | Wind 单季度 ROE S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roic</code> | Wind ROIC S_FA_ROIC。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>roic_stability_3y</code> | Wind ROIC S_FA_ROIC。 | 季频 PIT 公告状态延续到下一次公告；连续 12 个自然季度样本标准差；窗口缺季度则缺失。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>sales_cash_to_revenue</code> | Wind 销售收现/营业收入指标 S_FA_SALESCASHINTOOR。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>tangible_asset_ratio</code> | Wind 有形资产/总资产指标 S_FA_TANGIBLEASSETSTOASSETS。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
