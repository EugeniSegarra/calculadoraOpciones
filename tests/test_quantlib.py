"""Optional independent cross-library validation; pip install -r requirements-validation.txt.

QuantLib is a validation dependency, not used by the application at runtime.
Dates use ACT/365 and the Spot cash-dividend convention on both sides.
"""

import unittest

try:
    import QuantLib as ql
except ImportError:
    ql = None

from optionslab.pricing import option_greeks, price_option


def reference(spot, strike, days, rate, volatility, kind, style, q=0.0, dividends=()):
    today = ql.Date(1, 1, 2026)
    ql.Settings.instance().evaluationDate = today
    dc = ql.Actual365Fixed()
    process = ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(spot)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, q, dc)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, rate, dc)),
        ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, ql.NullCalendar(), volatility, dc)),
    )
    exercise = ql.AmericanExercise(today, today+days) if style == "american" else ql.EuropeanExercise(today+days)
    option = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call if kind == "call" else ql.Option.Put, strike), exercise)
    if style == "european" and not dividends:
        engine = ql.AnalyticEuropeanEngine(process)
    else:
        engine = ql.FdBlackScholesVanillaEngine(process, [ql.FixedDividend(cash, today+day) for day, cash in dividends], 1600, 3200, 4, ql.FdmSchemeDesc.CrankNicolson())
    option.setPricingEngine(engine)
    price, delta, gamma = option.NPV(), option.delta(), option.gamma()
    # QuantLib FD theta uses a finite-time snapshot; here we compare the local
    # PDE theta using INDEPENDENT QuantLib spatial Greeks. This distinction is
    # material for very short-dated options. In the exercise region theta=0.
    intrinsic = max((1 if kind == "call" else -1)*(spot-strike), 0)
    theta = 0.0 if style == "american" and price-intrinsic < 1e-8 else -(.5*volatility**2*spot**2*gamma + (rate-q)*spot*delta-rate*price)/365
    return dict(price=price, delta=delta, gamma=gamma, theta=theta)


@unittest.skipIf(ql is None, "Optional QuantLib validation dependency is not installed")
class QuantLibCrossChecks(unittest.TestCase):
    def test_bsm_matches_quantlib_analytic(self):
        for kind in ["call", "put"]:
            expected = reference(103, 100, 274, .04, .28, kind, "european", .02)
            actual = option_greeks(103, 100, 274/365, .04, .28, kind, dividend_yield=.02)
            for key in expected:
                self.assertAlmostEqual(actual[key], expected[key], delta=1e-10)

    def test_numerical_prices_and_local_greeks(self):
        cases = [
            (100, 100, 365, .05, .2, "put", "american", 0, ()),
            (100, 100, 365, .05, .2, "call", "american", .06, ()),
            (100, 100, 365, -.02, .2, "call", "american", 0, ()),
            (80, 100, 90, .07, .35, "put", "american", 0, ()),
            (120, 100, 730, .03, .5, "call", "american", 0, ((180, 5), (545, 5))),
            (100, 100, 365, .05, .2, "put", "american", 0, ((182, 5),)),
            (100, 100, 365, .05, .2, "call", "european", 0, ((182, 5),)),
            (100, 100, 4, .05, .01, "put", "american", 0, ()),
        ]
        for case in cases:
            with self.subTest(case=case):
                expected = reference(*case)
                spot, strike, days, rate, vol, kind, style, q, dividends = case
                actual = option_greeks(spot, strike, days/365, rate, vol, kind, style, q, tuple((day/365, cash) for day, cash in dividends))
                self.assertAlmostEqual(actual["price"], expected["price"], delta=.001)
                self.assertAlmostEqual(actual["delta"], expected["delta"], delta=.0002)
                self.assertAlmostEqual(actual["gamma"], expected["gamma"], delta=max(.00001, abs(expected["gamma"])*.001))
                self.assertAlmostEqual(actual["theta"], expected["theta"], delta=.00002)

    def test_vega_rho_against_independent_quantlib_bumps(self):
        args = (100, 100, 365, .05, .2, "put", "american")
        actual = option_greeks(100, 100, 1, .05, .2, "put", "american")
        v_up = reference(*args[:4], .201, *args[5:])["price"]
        v_down = reference(*args[:4], .199, *args[5:])["price"]
        r_up = reference(*args[:3], .0501, *args[4:])["price"]
        r_down = reference(*args[:3], .0499, *args[4:])["price"]
        self.assertAlmostEqual(actual["vega"], (v_up-v_down)/.002*.01, delta=.0002)
        self.assertAlmostEqual(actual["rho"], (r_up-r_down)/.0002*.01, delta=.001)


if __name__ == "__main__":
    unittest.main()
