"""固定时间窗口下的信号时序、公司行动及跨日补单。"""
from pathlib import Path

import pandas as pd

from src.intraday.config import AccountConfig, CostConfig, ExecutionConfig, MinuteBacktestConfig, MinuteDataConfig, TargetConfig
from src.intraday.engine import MinuteBacktestEngine


def _config() -> MinuteBacktestConfig:
    return MinuteBacktestConfig(
        path=Path('config.yaml'), run_name='test', output_root=Path('runs'),
        data=MinuteDataConfig(Path('data'), None, Path('cache'), 'test',pd.Timestamp('2025-04-01'), pd.Timestamp('2025-04-03')),
        targets=TargetConfig(Path('targets.csv'), '15:00:00'),
        account=AccountConfig(100_000),
        execution=ExecutionConfig(0, 1, False, True, order_time='10:00:00',
                                  window_start='10:01:00', window_end='10:05:00'),
        costs=CostConfig(0, 0, 0, 0, 0), raw={},
    )


def _day(date: str, price: float, buy_volume: int = 100_000) -> pd.DataFrame:
    records = []
    for clock in ('09:59', '10:00', '10:01', '15:00'):
        records.append({
            'timestamp':pd.Timestamp(f'{date} {clock}',tz='Asia/Shanghai'),
            'code':'600000.SH','open':price,'high':price+0.2,'low':price-0.2,
            'close':price,'volume':buy_volume if clock=='10:01' else 100_000,
            'vwap':price,
        })
    return pd.DataFrame(records)


def _target(weight: float) -> pd.DataFrame:
    return pd.DataFrame([{'signal_timestamp':pd.Timestamp('2025-04-01 15:00',tz='Asia/Shanghai'),
                          'code':'600000.SH','target_weight':weight}])


def test_signal_executes_on_next_day_window():
    result = MinuteBacktestEngine(_config()).run_stream([_day('2025-04-01',10),_day('2025-04-02',10)],_target(0.5))
    assert len(result.fills)==1
    assert result.fills.iloc[0]['timestamp']==pd.Timestamp('2025-04-02 10:01',tz='Asia/Shanghai')
    assert result.fills.iloc[0]['shares']==5000


def test_share_distribution_preserves_equity_when_price_adjusts():
    actions = pd.DataFrame([{'date':pd.Timestamp('2025-04-03'),'code':'600000.SH',
                              'cash_dividend_per_share':0.0,'share_ratio':1.0}])
    result = MinuteBacktestEngine(_config()).run_stream([
        _day('2025-04-01',10),_day('2025-04-02',10),_day('2025-04-03',5),
    ], _target(1), actions, record_frequency='daily')
    assert result.nav.iloc[-2]['nav']==100000
    assert result.nav.iloc[-1]['nav']==100000
    assert result.positions.iloc[-1]['shares']==20000


def test_unfilled_day_order_is_resubmitted_next_trading_day():
    result = MinuteBacktestEngine(_config()).run_stream([
        _day('2025-04-01',10),_day('2025-04-02',10,0),_day('2025-04-03',10),
    ], _target(1), record_frequency='daily')
    assert len(result.fills)==1
    assert result.fills.iloc[0]['timestamp']==pd.Timestamp('2025-04-03 10:01',tz='Asia/Shanghai')
