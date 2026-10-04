"""catmodel — Meteorium catastrophe-loss engine (frequency × severity × vulnerability).

Replaces "one heuristic score + fixed noise" with four auditable questions:
how often (frequency), how intense (severity), how much damage (vulnerability),
and how correlated across a portfolio (copula). Every parameter lives in
`priors.py` and is labelled a PLACEHOLDER until fitted by `validation.py`
against hindcasts. Nothing here is presented as calibrated.
"""
from .engine import AnnualResult, annual_losses, portfolio_annual          # noqa: F401
from .metrics import risk_metrics, ep_curve, var, tvar                    # noqa: F401
from .priors import PRIORS, HazardPrior, norm_rcp, trend                  # noqa: F401
