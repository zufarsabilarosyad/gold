"""Forecasting the cost to complete, which is where the WIP report gets its
opinion.

Three methods, in ascending order of how much they trust the past:

``remaining_budget``
    Cost to complete is whatever is left in the budget.  The forecast never
    moves until someone moves it, which makes a job look fine right up until
    the last month.
``trend``
    Cost to complete is the cost incurred so far, scaled by the work left, so
    a line running twenty percent over budget is forecast to keep running
    twenty percent over.  Harsh, early, and usually right.
``manual``
    Somebody typed a number.  Recorded as such, because a manual forecast that
    is silently indistinguishable from a computed one is how a job hides.

The methods disagree most at exactly the moment the answer matters, which is
about a third of the way through a line that is running over.
"""

from decimal import Decimal

from ..core.ids import normalise_code
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..errors import DataError, InputError

__all__ = ["FORECAST_METHODS", "Forecast", "forecast_cost", "ForecastRegister"]

FORECAST_METHODS = ("remaining_budget", "trend", "manual")


def forecast_cost(budget, incurred, complete, method="remaining_budget", manual=None):
    """Return the forecast final cost of a line.

    >>> from ..core.money import money
    >>> str(forecast_cost(money("100000"), money("40000"), Rate("0.3")))
    '$100,000.00'
    >>> str(forecast_cost(money("100000"), money("40000"), Rate("0.3"), "trend"))
    '$133,333.33'
    >>> str(forecast_cost(money("100000"), money("40000"), Rate("0.3"), "manual",
    ...                   money("115000")))
    '$115,000.00'
    """
    method = str(method)
    if method not in FORECAST_METHODS:
        raise InputError("unknown forecast method %r; known: %s" % (method, ", ".join(FORECAST_METHODS)))
    if not isinstance(budget, Money) or not isinstance(incurred, Money):
        raise InputError("a forecast needs Money amounts")
    if method == "manual":
        if manual is None:
            raise InputError("a manual forecast needs a figure")
        return manual
    if method == "remaining_budget":
        if incurred > budget:
            return incurred
        return budget
    fraction = complete.value if isinstance(complete, Rate) else Rate.parse(complete).value
    if fraction <= 0:
        return budget
    if fraction >= 1:
        return incurred
    return (incurred / fraction).rounded()


class Forecast:
    """One cost code's forecast at a point in the job.

    >>> from ..core.money import money
    >>> forecast = Forecast("03300", money("250000"), money("120000"), Rate("0.4"),
    ...                     method="trend")
    >>> str(forecast.final_cost())
    '$300,000.00'
    >>> str(forecast.variance())
    '-$50,000.00'
    >>> forecast.is_overrunning()
    True
    """

    __slots__ = ("code", "budget", "incurred", "complete", "method", "manual", "note")

    def __init__(self, code, budget, incurred, complete, method="remaining_budget", manual=None, note=""):
        self.code = normalise_code(code)
        self.budget = budget
        self.incurred = incurred
        self.complete = complete if isinstance(complete, Rate) else Rate.parse(complete)
        if str(method) not in FORECAST_METHODS:
            raise InputError("unknown forecast method %r" % (method,))
        self.method = str(method)
        self.manual = manual
        self.note = str(note)

    def final_cost(self):
        """Return the forecast cost at completion."""
        return forecast_cost(self.budget, self.incurred, self.complete, self.method, self.manual)

    def to_complete(self):
        """Return the cost still to be spent, never below zero."""
        remaining = self.final_cost() - self.incurred
        if remaining.is_negative():
            return zero(self.budget.currency)
        return remaining

    def variance(self):
        """Return budget less forecast; negative means an overrun."""
        return self.budget - self.final_cost()

    def is_overrunning(self):
        """Return True when the forecast exceeds the budget."""
        return self.variance().is_negative()

    def to_dict(self):
        """Return the forecast as plain data."""
        return {
            "code": self.code,
            "budget": str(self.budget.amount),
            "incurred": str(self.incurred.amount),
            "complete": rate_text(self.complete),
            "method": self.method,
            "manual": str(self.manual.amount) if self.manual else None,
            "final_cost": str(self.final_cost().amount),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a forecast from :meth:`to_dict` output."""
        return cls(
            data["code"],
            money(data["budget"], currency),
            money(data["incurred"], currency),
            data.get("complete", "0"),
            data.get("method", "remaining_budget"),
            money(data["manual"], currency) if data.get("manual") else None,
            data.get("note", ""),
        )

    def __repr__(self):
        return "Forecast(%r, %s)" % (self.code, self.final_cost())


class ForecastRegister:
    """The forecasts across a job's cost codes.

    >>> from ..core.money import money
    >>> register = ForecastRegister()
    >>> register.add(Forecast("03300", money("250000"), money("120000"), Rate("0.4"),
    ...                       method="trend"))
    >>> register.add(Forecast("09900", money("40000"), money("10000"), Rate("0.5")))
    >>> str(register.total_forecast())
    '$340,000.00'
    >>> [item.code for item in register.overrunning()]
    ['03300']
    """

    def __init__(self, forecasts=(), currency="USD"):
        self.currency = currency
        self.forecasts = {}
        for forecast in forecasts:
            self.add(forecast)

    def add(self, forecast):
        """Add a forecast, refusing a duplicate code."""
        if forecast.code in self.forecasts:
            raise DataError("forecast for %s appears twice" % (forecast.code,))
        self.forecasts[forecast.code] = forecast

    def get(self, code, default=None):
        """Return a forecast, or ``default``."""
        return self.forecasts.get(normalise_code(code), default)

    def ordered(self):
        """Return the forecasts in code order."""
        return [self.forecasts[key] for key in sorted(self.forecasts)]

    def total_budget(self):
        """Return the total budget across the register."""
        running = zero(self.currency)
        for forecast in self.ordered():
            running = running + forecast.budget
        return running

    def total_forecast(self):
        """Return the total forecast cost at completion."""
        running = zero(self.currency)
        for forecast in self.ordered():
            running = running + forecast.final_cost()
        return running

    def total_to_complete(self):
        """Return the total cost still to be spent."""
        running = zero(self.currency)
        for forecast in self.ordered():
            running = running + forecast.to_complete()
        return running

    def overrunning(self):
        """Return the codes forecast to finish over budget."""
        return [forecast for forecast in self.ordered() if forecast.is_overrunning()]

    def to_list(self):
        """Return the register as plain data."""
        return [forecast.to_dict() for forecast in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a register from :meth:`to_list` output."""
        return cls([Forecast.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.forecasts)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "ForecastRegister(%d codes)" % (len(self.forecasts),)
