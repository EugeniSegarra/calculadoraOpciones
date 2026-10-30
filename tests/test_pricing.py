"""Financial identities and independent numerical pricing checks (unittest)."""

import math
import unittest

import numpy as np
from scipy.integrate import quad

from optionslab.pricing import (
    implied_volatility,
    option_greeks,
    option_values,
    price_option,
)


def independent_crr(spot, strike, time, rate, vol, kind="put", q=0, steps=3000):
    """A separately implemented recombining tree; not the production PDE."""
    dt = time / steps
    u = math.exp(vol * math.sqrt(dt))
    probability = (math.exp((rate - q) * dt) - 1/u) / (u - 1/u)
    if not 0 <= probability <= 1:
        raise ValueError("Invalid CRR lattice parameters")
    sign = 1 if kind == "call" else -1
    j = np.arange(steps + 1)
    nodes = spot * np.exp((2*j - steps) * math.log(u))
    values = np.maximum(sign * (nodes - strike), 0)
    discount = math.exp(-rate * dt)
    for level in range(steps - 1, -1, -1):
        values = discount * ((1-probability)*values[:-1] + probability*values[1:])
        nodes = spot * np.exp((2*np.arange(level + 1)-level)*math.log(u))
        values = np.maximum(values, np.maximum(sign*(nodes-strike), 0))
    return float(values[0])


def single_dividend_integral(spot, strike, time, rate, vol, kind, dividend_time,
                             amount, american_call=False):
    """Conditional Gaussian integration, exact apart from quadrature.

    For a nonnegative-rate call with exactly one dividend, early exercise can
    be optimal only immediately before that dividend. This gives an independent
    American-call benchmark without reusing a lattice/PDE exercise algorithm.
    """
    def integrand(z):
        before = spot * math.exp((rate-.5*vol*vol)*dividend_time + vol*math.sqrt(dividend_time)*z)
        continuation = price_option(max(before-amount, 0), strike, time-dividend_time, rate, vol, kind)
        if american_call:
            continuation = max(continuation, before-strike)
        return continuation * math.exp(-rate*dividend_time - .5*z*z) / math.sqrt(2*math.pi)
    return quad(integrand, -12, 12, epsabs=1e-10, limit=300)[0]


class PricingTests(unittest.TestCase):
    def test_textbook_bsm_prices(self):
        self.assertAlmostEqual(price_option(100, 100, 1, .05, .2), 10.4505835721856, places=10)
        self.assertAlmostEqual(price_option(100, 100, 1, .05, .2, "put"), 5.5735260222570, places=10)

    def test_put_call_parity_across_rates_yields_moneyness(self):
        for spot in [0, 40, 100, 180]:
            for rate in [-.04, 0, .08]:
                for q in [0, .03, -.01]:
                    call = price_option(spot, 100, 1.3, rate, .27, dividend_yield=q)
                    put = price_option(spot, 100, 1.3, rate, .27, "put", dividend_yield=q)
                    self.assertAlmostEqual(call-put, spot*math.exp(-q*1.3)-100*math.exp(-rate*1.3), places=10)

    def test_expiry_and_signed_payoff_is_external(self):
        np.testing.assert_array_equal(option_values([80, 100, 120], 100, 0, .03, .2), [0, 0, 20])
        np.testing.assert_array_equal(option_values([80, 100, 120], 100, 0, .03, .2, "put"), [20, 0, 0])

    def test_zero_volatility_european_forward_payoff(self):
        for kind, sign in [("call", 1), ("put", -1)]:
            expected = math.exp(-.05) * max(sign*(100*math.exp(.02)-100), 0)
            self.assertAlmostEqual(price_option(100, 100, 1, .05, 0, kind, dividend_yield=.03), expected, places=10)

    def test_zero_volatility_exercise_before_discrete_dividend(self):
        value = price_option(100, 100, 1, .05, 0, "call", "american", dividends=((.5, 20),))
        self.assertAlmostEqual(value, 100-100*math.exp(-.05*.5), places=10)

    def test_negative_rate_put_not_artificially_capped_at_strike(self):
        value = price_option(0, 100, 1, -.05, .2, "put", "american")
        self.assertAlmostEqual(value, 100*math.exp(.05), places=10)
        self.assertGreater(value, 100)

    def test_no_exercise_cases_use_exact_european_value(self):
        for kind, rate, q in [("call", .05, 0), ("call", .05, -.02), ("put", -.03, 0), ("put", -.03, .02)]:
            self.assertEqual(price_option(100, 100, 1, rate, .3, kind, "american", q), price_option(100, 100, 1, rate, .3, kind, "european", q))

    def test_american_dominates_european_and_intrinsic(self):
        for kind in ["put", "call"]:
            for rate, q in [(.06, 0), (-.02, 0), (.02, .07)]:
                spots = np.array([60., 90., 100., 110., 160.])
                european = option_values(spots, 100, .7, rate, .25, kind, "european", q)
                american = option_values(spots, 100, .7, rate, .25, kind, "american", q)
                intrinsic = np.maximum((1 if kind == "call" else -1)*(spots-100), 0)
                self.assertTrue(np.all(american >= european - 1e-10))
                self.assertTrue(np.all(american >= intrinsic - 1e-10))

    def test_independent_crr_american_put(self):
        expected = independent_crr(100, 100, 1, .05, .2)
        self.assertAlmostEqual(price_option(100, 100, 1, .05, .2, "put", "american"), expected, delta=.001)

    def test_adaptive_grid_low_total_variance(self):
        expected = independent_crr(100, 100, .01, .05, .01, steps=3000)
        actual = price_option(100, 100, .01, .05, .01, "put", "american")
        self.assertAlmostEqual(actual, expected, delta=5e-6)
        high = price_option(100, 100, .01, .05, .01, "put", "american", steps=800)
        self.assertAlmostEqual(actual, high, delta=3e-6)

    def test_single_cash_dividend_european_against_quadrature(self):
        for kind in ["call", "put"]:
            expected = single_dividend_integral(100, 100, 1, .05, .2, kind, .5, 5)
            actual = price_option(100, 100, 1, .05, .2, kind, dividends=((.5, 5),))
            self.assertAlmostEqual(actual, expected, delta=.0001)

    def test_single_cash_dividend_american_call_against_quadrature(self):
        expected = single_dividend_integral(100, 100, 1, .05, .2, "call", .5, 5, american_call=True)
        actual = price_option(100, 100, 1, .05, .2, "call", "american", dividends=((.5, 5),))
        self.assertAlmostEqual(actual, expected, delta=.0002)

    def test_expiry_dividend_ordering(self):
        # A cash dividend immediately BEFORE payoff raises the effective call
        # strike; this is not a dividend after settlement.
        expected = price_option(100, 105, 1, .05, .2)
        actual = price_option(100, 100, 1, .05, .2, dividends=((1, 5),))
        self.assertAlmostEqual(actual, expected, delta=.0002)

    def test_dividend_floor_liquidator(self):
        # The share cannot become negative, and a European put cannot receive
        # more than K at expiry, even if the advertised dividend exceeds S.
        actual = price_option(1, 100, 1, .05, 0, "put", dividends=((.5, 20),))
        self.assertAlmostEqual(actual, 100*math.exp(-.05), places=10)

    def test_numerical_scalar_and_vector_consistency(self):
        spots = [20, 80, 100, 120, 200]
        vector = option_values(spots, 100, 1, .05, .25, "put", "american", dividends=((.5, 3),))
        scalar = [price_option(s, 100, 1, .05, .25, "put", "american", dividends=((.5, 3),)) for s in spots]
        np.testing.assert_allclose(vector, scalar, atol=.001, rtol=0)

    def test_analytic_greeks_match_independent_bumps(self):
        g = option_greeks(105, 100, .8, .03, .24, "put", dividend_yield=.02)
        def p(s=105, t=.8, r=.03, v=.24):
            return price_option(s, 100, t, r, v, "put", dividend_yield=.02)
        h, dv, dr, dt = .01, .00001, .00001, .00001
        self.assertAlmostEqual(g["delta"], (p(s=105+h)-p(s=105-h))/(2*h), delta=1e-7)
        self.assertAlmostEqual(g["gamma"], (p(s=105+h)-2*p()+p(s=105-h))/h**2, delta=1e-7)
        self.assertAlmostEqual(g["vega"], (p(v=.24+dv)-p(v=.24-dv))/(2*dv)*.01, delta=1e-7)
        self.assertAlmostEqual(g["rho"], (p(r=.03+dr)-p(r=.03-dr))/(2*dr)*.01, delta=1e-7)
        self.assertAlmostEqual(g["theta"], (p(t=.8-dt)-p(t=.8+dt))/(2*dt*365), delta=1e-7)

    def test_numerical_greeks_low_variance_converge(self):
        g = option_greeks(100, 100, .01, .05, .01, "put", "american")
        refined = option_greeks(100, 100, .01, .05, .01, "put", "american", steps=800)
        self.assertAlmostEqual(g["delta"], refined["delta"], delta=2e-5)
        self.assertAlmostEqual(g["gamma"], refined["gamma"], delta=.002)
        self.assertGreater(g["gamma"], 5)

    def test_greeks_at_expiry_and_zero_vol_are_not_fictitious(self):
        expiry = option_greeks(100, 100, 0, .05, .2)
        self.assertIsNone(expiry["delta"])
        self.assertIsNone(expiry["gamma"])
        self.assertIsNone(expiry["theta"])
        zero = option_greeks(100, 100, 1, 0, 0)
        self.assertTrue(all(zero[key] is None for key in ["delta", "gamma", "theta", "vega", "rho"]))
        self.assertEqual(option_greeks(120, 100, 0, .05, .2)["delta"], 1)

    def test_zero_spot_greeks_have_analytic_limits(self):
        g = option_greeks(0, 100, 1, .05, .2, "put", dividend_yield=.02)
        self.assertEqual(g["gamma"], 0)
        self.assertAlmostEqual(g["delta"], -math.exp(-.02), places=12)
        self.assertIsNone(option_greeks(0, 100, 1, .05, .2, "put", "american")["gamma"])

    def test_greeks_respect_parameter_domain_boundaries(self):
        g = option_greeks(100, 100, 1, 1, .2, "put", "american")
        self.assertTrue(math.isfinite(g["rho"]))
        self.assertEqual(option_greeks(60, 100, 1, .05, .2, "put", "american")["theta"], 0)

    def test_implied_vol_roundtrips(self):
        for kind, style, div in [("call", "european", ()), ("put", "european", ()), ("put", "american", ()), ("call", "american", ((.5, 5),))]:
            price = price_option(100, 105, 1, .03, .27, kind, style, dividends=div)
            self.assertAlmostEqual(implied_volatility(price, 100, 105, 1, .03, kind, style, dividends=div), .27, delta=2e-7)

    def test_implied_vol_rejects_unidentified_or_invalid_quotes(self):
        for kwargs in [dict(price=-1), dict(price=1000), dict(price=1, time=0), dict(price=1, spot=0), dict(price=50, option_type="put", style="american", spot=50), dict(price=5, option_type="put", dividends=((.5, 2),))]:
            params = dict(price=10, spot=100, strike=100, time=1, rate=.05)
            params.update(kwargs)
            with self.assertRaises(ValueError, msg=str(params)):
                implied_volatility(**params)

    def test_reject_nonfinite_negative_and_ambiguous_inputs(self):
        cases = [dict(spot=-1), dict(spot=float("nan")), dict(strike=0), dict(time=-1), dict(volatility=-.2), dict(rate=float("inf")), dict(steps=20), dict(steps=True), dict(spot=True), dict(option_type="straddle"), dict(dividends=((0, 2),)), dict(dividends=((2, 2),)), dict(dividends=((.5, 2),), dividend_yield=.03), dict(dividends=((.5, -1),))]
        for case in cases:
            params = dict(spot=100, strike=100, time=1, rate=.05, volatility=.2)
            params.update(case)
            with self.assertRaises(ValueError, msg=str(case)):
                price_option(**params)


if __name__ == "__main__":
    unittest.main()
