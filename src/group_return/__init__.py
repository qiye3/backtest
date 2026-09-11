"""公开因子分组收益和全截面相关评价入口。"""

from src.group_return.evaluator import evaluate, evaluate_factors
from src.group_return.grouping import validate_ranges

__all__ = ["evaluate", "evaluate_factors", "validate_ranges"]
