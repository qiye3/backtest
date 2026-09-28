"""验证统一目标仓位合同。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.intraday.targets import load_target_weights, normalize_stock_code


def test_target_weights_normalize_date_code_and_timezone(tmp_path) -> None:
    path = tmp_path / "targets.csv"
    pd.DataFrame(
        {
            "signal_timestamp": ["2025-04-01", "2025-04-01"],
            "code": ["600000", "sz000001"],
            "target_weight": [0.4, 0.5],
        }
    ).to_csv(path, index=False)

    result = load_target_weights(path, "14:55:00")

    assert result["code"].tolist() == ["000001.SZ", "600000.SH"]
    assert str(result.loc[0, "signal_timestamp"]) == "2025-04-01 14:55:00+08:00"


def test_target_weights_reject_leverage(tmp_path) -> None:
    path = tmp_path / "targets.csv"
    pd.DataFrame(
        {
            "signal_timestamp": ["2025-04-01", "2025-04-01"],
            "code": ["600000", "000001"],
            "target_weight": [0.6, 0.5],
        }
    ).to_csv(path, index=False)

    with pytest.raises(ValueError, match="超过 1"):
        load_target_weights(path, "14:55:00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("600000", "600000.SH"), ("000001", "000001.SZ"), ("920000", "920000.BJ")],
)
def test_normalize_stock_code(raw, expected) -> None:
    assert normalize_stock_code(raw) == expected
