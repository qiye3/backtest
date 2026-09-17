"""公开因子分组收益和全截面相关评价入口。"""

from src.group_return.evaluator import (
    evaluate,
    evaluate_factors,
    iter_factor_evaluations,
)
from src.group_return.grouping import validate_ranges
from src.group_return.overall import evaluate_overall

__all__ = [
    "evaluate",
    "evaluate_factors",
    "evaluate_overall",
    "iter_factor_evaluations",
    "validate_ranges",
]
