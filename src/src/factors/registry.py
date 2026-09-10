"""将配置中的 implementation 映射到对应因子实现。"""
from src.factors.growth import FinancialFactor, FinancialHistoryFactor
from src.factors.income import IncomeFactor, IncomeSurpriseFactor
from src.factors.consensus import ConsensusFactor, RatingFactor
from src.factors.residual_momentum import ResidualMomentum

REGISTRY = {
    'financial': FinancialFactor,
    'financial_history': FinancialHistoryFactor,
    'income': IncomeFactor,
    'income_surprise': IncomeSurpriseFactor,
    'consensus': ConsensusFactor,
    'rating': RatingFactor,
    'residual_momentum': ResidualMomentum,
}


def get_factor(implementation):
    if implementation not in REGISTRY:
        raise ValueError(f'unknown factor implementation: {implementation}')
    return REGISTRY[implementation]()
