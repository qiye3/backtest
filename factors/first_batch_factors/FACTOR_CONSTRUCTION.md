# 2026-09-21 第一批新数据因子实现说明

本目录实现业绩预告、回购和企业价值三个数据域的 24 个因子。详细经济逻辑见：

- `/Users/qiye/Desktop/docs/Work/TK/基本面/20260921_业绩预告因子构造表.md`
- `/Users/qiye/Desktop/docs/Work/TK/基本面/20260921_回购因子构造表.md`
- `/Users/qiye/Desktop/docs/Work/TK/基本面/20260921_企业价值因子构造表.md`

## 1. 时间口径

- 业绩预告由数据层按公告后的下一交易日生效。
- 回购使用 `ANN_DT` 与 `OPDATE` 中较晚日期，再移动到下一交易日；实际执行状态不会回填到首次公告日。
- 企业价值使用当日原始日频值，不跨交易日前向填充。
- 所有结果最后按中证800与中证1000历史成员并集掩码。

## 2. 回购口径

回购金额单位在数据字典中尚未确认，因此计划强度和执行强度优先使用股数口径。总股本由
`S_VAL_MV × 10000 / S_DQ_CLOSE` 还原。完成率优先使用 Wind 的资金或股数完成率，缺失时
才使用 `QTY / EXP_QTY`。

## 3. 配置与运行

`config/` 下每个 YAML 对应一个固定公式，并输出 raw 与行业中性两个标准变体。先复制
`run_config.example.yaml` 并填写真实 `source_root`，再从项目根目录运行：

```bash
python -m src.cli --config factors/first_batch_factors/run_config.example.yaml
```

正式运行前必须核对回购 `STATUS`、`STOCK_REPO_OBJECTIVE_CODE` 和 `OPDATE` 的真实取值，
以及一致预期 `con_np` 与预告报告期的年度匹配覆盖率。
