正式工作中需要做成/Users/qiye/TK/factor-variant-backtest.zip 这样的skill包

1. 我现在有一批因子的计算py和config，需要批量进行回测
2. 我把因子的代码实现放在factor-backtest/factors/code，config实现放在/Users/qiye/TK/factor-backtest/factors/config（这些路径可自由变化），每个config可以找到它所对应的因子文件，可以一次批量运行一个路径下的所有config
3. 如果配置了因子计算，先计算所有因子，缓存在data/ 目录下
4. 并行回测各个因子，更新每个因子的指标到指定路径下的台账csv；
5. 是否画图可配置，默认不画图

