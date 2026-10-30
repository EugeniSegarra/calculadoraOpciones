"""Independent financial challenges, not snapshots of implementation output.

The reference American solver is a CRR lattice, independent of the production
finite-difference solver. Expiry-dividend identities are algebraic payoffs,
and accounting checks retain arbitrary historical fills rather than fitting
those fills to the pricing model. See docs/RESEARCH.md for primary references.
"""

import copy
import math
import unittest
from datetime import date

import numpy as np

from optionslab.portfolio import (
    Portfolio,
    analyze,
    infer_leg_iv,
    portfolio_values,
    terminal_risk,
)
from optionslab.pricing import (
    implied_volatility,
    option_greeks,
    option_values,
    price_option,
)


def independent_bsm(spot, strike, time, rate, vol, kind="call", q=0):
    """Direct textbook expression, using erf rather than production ndtr."""
    phi = lambda x: (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    d1 = (math.log(spot / strike) + (rate - q + vol * vol / 2) * time) / (vol * math.sqrt(time))
    d2 = d1 - vol * math.sqrt(time)
    sign = 1 if kind == "call" else -1
    return sign * (spot * math.exp(-q * time) * phi(sign * d1)
                   - strike * math.exp(-rate * time) * phi(sign * d2))


def independent_american_crr(spot, strike, time, rate, vol, kind, q=0, steps=1800):
    """American CRR, no interpolation and no shared production helpers."""
    dt = time / steps
    up = math.exp(vol * math.sqrt(dt))
    down = 1 / up
    probability = (math.exp((rate - q) * dt) - down) / (up - down)
    if not 0 <= probability <= 1:
        raise ValueError("Reference lattice needs more steps.")
    discount = math.exp(-rate * dt)
    nodes = spot * np.exp((2 * np.arange(steps + 1) - steps) * math.log(up))
    sign = 1 if kind == "call" else -1
    value = np.maximum(sign * (nodes - strike), 0)
    for _ in range(steps, 0, -1):
        value = discount * ((1 - probability) * value[:-1] + probability * value[1:])
        nodes = nodes[:-1] / down
        value = np.maximum(value, np.maximum(sign * (nodes - strike), 0))
    return float(value[0])


def leg(kind="call", **changes):
    result = dict(id="a", label="Prueba", kind=kind, quantity=1,
                  multiplier=100, entry_price=5, strike=100,
                  expiry="2027-10-30", volatility=0.2, style="european")
    if kind == "stock":
        result.update(quantity=100, multiplier=1, entry_price=95)
        result.pop("strike")
        result.pop("expiry")
    result.update(changes)
    return result


def book(legs=None, **changes):
    result = dict(schema_version=1, name="Auditoría", underlying="TEST",
                  currency="EUR", valuation_date="2026-10-30", spot=100,
                  rate=0.05, dividend_yield=0, cash_adjustment=0,
                  cash_dividends=[], legs=legs if legs is not None else [leg()])
    result.update(changes)
    return result


class AdversarialPricingTests(unittest.TestCase):
    def test_reference_prices_and_homogeneity(self):
        for q, call, put in [(0, 10.450583572185565, 5.573526022256971),
                             (0.02, 9.227005508154036, 6.330080627549918)]:
            for kind, expected in [("call", call), ("put", put)]:
                with self.subTest(q=q, kind=kind):
                    actual = price_option(100, 100, 1, 0.05, 0.2, kind, dividend_yield=q)
                    self.assertAlmostEqual(actual, expected, places=10)
                    scaled = price_option(730, 730, 1, 0.05, 0.2, kind, dividend_yield=q)
                    self.assertAlmostEqual(scaled, 7.3 * actual, places=9)

    def test_put_call_parity_including_negative_rates_and_zero_spot(self):
        for spot in [0, 1, 80, 100, 170]:
            for rate, q in [(-0.03, 0.04), (0.07, 0), (0, 0.1)]:
                with self.subTest(spot=spot, rate=rate, q=q):
                    call = price_option(spot, 100, 1.7, rate, 0.37, "call", dividend_yield=q)
                    put = price_option(spot, 100, 1.7, rate, 0.37, "put", dividend_yield=q)
                    rhs = spot * math.exp(-q * 1.7) - 100 * math.exp(-rate * 1.7)
                    self.assertAlmostEqual(call - put, rhs, places=10)

    def test_european_value_must_not_be_floored_at_immediate_exercise(self):
        put = price_option(20, 100, 2, 0.08, 0.05, "put")
        self.assertLess(put, 80)
        self.assertAlmostEqual(put, 100 * math.exp(-0.16) - 20, places=8)

    def test_american_prices_against_independent_lattice(self):
        cases = [(100, 100, 1, 0.05, 0.2, "put", 0),
                 (60, 100, 1, 0.05, 0.2, "put", 0),
                 (100, 100, 2, -0.04, 0.3, "call", 0),
                 (100, 100, 1, 0.05, 0.2, "call", 0.1)]
        for spot, strike, time, rate, vol, kind, q in cases:
            with self.subTest(case=(spot, time, rate, kind, q)):
                ref = independent_american_crr(spot, strike, time, rate, vol, kind, q)
                actual = price_option(spot, strike, time, rate, vol, kind, "american", q)
                euro = price_option(spot, strike, time, rate, vol, kind, "european", q)
                intrinsic = max((spot - strike) if kind == "call" else (strike - spot), 0)
                self.assertLess(abs(actual - ref), 0.006)
                self.assertGreaterEqual(actual + 0.002, euro)
                self.assertGreaterEqual(actual + 1e-9, intrinsic)

    def test_negative_rates_invalidate_universal_american_call_shortcut(self):
        american = price_option(100, 100, 2, -0.04, 0.3, "call", "american")
        european = price_option(100, 100, 2, -0.04, 0.3, "call", "european")
        self.assertGreater(american - european, 0.25)

    def test_short_maturity_low_volatility_lattice_resolution(self):
        ref = independent_american_crr(100, 100, 0.01, 0.05, 0.01, "put")
        actual = price_option(100, 100, 0.01, 0.05, 0.01, "put", "american")
        self.assertLess(abs(actual - ref), 0.0001)

    def test_low_variance_greeks_remain_local(self):
        # Lattice verification gives delta about -0.414 and gamma about 5.54.
        # The former fixed 0.5 spot bump yielded -0.5 and 2.09 instead.
        value = option_greeks(100, 100, 0.01, 0.05, 0.01, "put", "american")
        self.assertIsNotNone(value["delta"])
        self.assertIsNotNone(value["gamma"])
        self.assertLess(abs(value["delta"] + 0.414), 0.015)
        self.assertLess(abs(value["gamma"] - 5.54), 0.25)

    def test_finite_difference_convergence_with_dividends(self):
        args = dict(spot=100, strike=100, time=1, rate=0.05,
                    volatility=0.2, option_type="put", style="american",
                    dividends=[(0.5, 5)])
        coarse = price_option(**args, steps=200)
        fine = price_option(**args, steps=400)
        finer = price_option(**args, steps=800)
        self.assertLess(abs(fine - finer), 0.002)
        self.assertLess(abs(fine - finer), abs(coarse - finer))

    def test_expiry_cash_dividend_has_exact_european_payoff_identity(self):
        # Liquidator dividend: call payoff is call(K+D); put payoff is
        # put(K+D)-put(D), since dividends cannot make stock negative.
        for dividend in [5, 150]:
            for kind in ["call", "put"]:
                with self.subTest(dividend=dividend, kind=kind):
                    expected = independent_bsm(100, 100 + dividend, 1, 0.05, 0.3, kind)
                    if kind == "put":
                        expected -= independent_bsm(100, dividend, 1, 0.05, 0.3, "put")
                    actual = price_option(100, 100, 1, 0.05, 0.3, kind,
                                          dividends=[(1, dividend)])
                    self.assertLess(abs(actual - expected), 0.005)

    def test_american_call_can_exercise_before_expiry_dividend(self):
        expected = independent_bsm(100, 100, 1, 0.05, 0.2)
        actual = price_option(100, 100, 1, 0.05, 0.2, "call", "american",
                              dividends=[(1, 20)])
        self.assertLess(abs(actual - expected), 0.005)

    def test_zero_volatility_american_optimal_stopping(self):
        # Independent dense deterministic time maximisation, including an
        # interior optimum possible when both rate and yield are negative.
        for rate, q, spot, kind in [(0.05, 0.1, 100, "call"),
                                     (-0.03, -0.08, 50, "put"),
                                     (-0.04, 0, 100, "call")]:
            timeline = np.linspace(0, 3, 50001)
            sign = 1 if kind == "call" else -1
            expected = np.max(np.exp(-rate * timeline)
                              * np.maximum(sign * (spot * np.exp((rate - q) * timeline) - 100), 0))
            actual = price_option(spot, 100, 3, rate, 0, kind, "american", q)
            self.assertAlmostEqual(actual, float(expected), places=6)

    def test_undefined_zero_variance_and_expiry_greeks_not_fabricated(self):
        for time, vol in [(1, 0), (0, 0.2)]:
            result = option_greeks(100, 100, time, 0, vol)
            self.assertIsNone(result["delta"])
            self.assertIsNone(result["gamma"])

    def test_supported_rate_boundary_does_not_crash_greek_bumps(self):
        result = option_greeks(100, 100, 1, 1, 0.2, "put", "american")
        self.assertTrue(math.isfinite(result["price"]))
        self.assertTrue(result["rho"] is None or math.isfinite(result["rho"]))

    def test_zero_spot_gamma_does_not_report_subtraction_noise(self):
        european = option_greeks(0, 100, 1, 0.05, 0.2, "put", dividend_yield=0.02)
        self.assertAlmostEqual(european["gamma"], 0, places=8)
        self.assertAlmostEqual(european["delta"], -math.exp(-0.02), places=8)
        american = option_greeks(0, 100, 1, 0.05, 0.2, "put", "american")
        self.assertTrue(american["gamma"] is None or abs(american["gamma"]) < 1e-8)

    def test_iv_roundtrip_and_impossible_prices(self):
        for kind in ["call", "put"]:
            for q in [0, 0.035]:
                expected = independent_bsm(107, 100, 0.7, -0.01, 0.43, kind, q)
                actual = implied_volatility(expected, 107, 100, 0.7, -0.01,
                                            kind, dividend_yield=q)
                self.assertAlmostEqual(actual, 0.43, places=7)
        for invalid in [-1, 101, float("nan"), float("inf")]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                implied_volatility(invalid, 100, 100, 1, 0.05)
        with self.assertRaises(ValueError):
            implied_volatility(0, 200, 100, 1, 0.05)
        with self.assertRaises(ValueError):
            implied_volatility(10, 100, 100, 0, 0.05)

    def test_cash_put_iv_is_not_falsely_asserted_unique(self):
        mark = price_option(100, 100, 1, 0.05, 0.2, "put", dividends=[(0.5, 100)])
        with self.assertRaises(ValueError):
            implied_volatility(mark, 100, 100, 1, 0.05, "put", dividends=[(0.5, 100)])

    def test_numerical_scalar_batch_consistency(self):
        args = dict(strike=100, time=1, rate=0.05, volatility=0.2,
                    option_type="put", style="american", dividends=[(0.5, 5)])
        scalar = price_option(100, **args)
        batched = option_values([0, 100, 200], **args)[1]
        self.assertLess(abs(scalar - batched), 0.002)


class AdversarialPositionTests(unittest.TestCase):
    def test_long_short_cancel_risk_but_preserve_fill_difference_and_fees(self):
        data = book([leg(quantity=2, entry_price=7, entry_fee=3, exit_fee=4),
                     leg(id="b", quantity=-2, entry_price=9, entry_fee=5, exit_fee=6)])
        initial = copy.deepcopy(data)
        result = analyze(data, dict(date="2027-01-15", spot=130, vol_shift=0.1))
        self.assertEqual(data, initial)
        self.assertAlmostEqual(result["summary"]["model_pnl"], 382, places=8)
        self.assertAlmostEqual(result["scenario"]["pnl"], 382, places=8)
        for greek in result["summary"]["greeks"].values():
            self.assertAlmostEqual(greek, 0, places=8)
        self.assertTrue(all(abs(value - 382) < 1e-8 for value in result["curve"]["horizon_pnl"]))

    def test_market_marks_are_not_substituted_with_models(self):
        result = analyze(book([leg(mark_price=99), leg(id="b", kind="put")]))
        self.assertIsNone(result["summary"]["market_value"])
        self.assertIsNone(result["summary"]["market_pnl"])
        self.assertIsNone(result["scenario"]["change_from_market"])

    def test_known_stale_quotes_are_not_reported_as_current_market_pnl(self):
        result = analyze(book([leg(mark_price=8, bid=7, ask=9, quote_date="2026-10-29")]))
        self.assertIsNone(result["summary"]["market_value"])
        self.assertIsNone(result["summary"]["market_pnl"])
        self.assertIsNone(result["summary"]["liquidation_pnl"])
        self.assertIsNone(result["scenario"]["change_from_market"])

    def test_liquidation_uses_bid_long_ask_short_and_total_fees(self):
        data = book([leg(quantity=2, entry_price=5, bid=7, ask=8, entry_fee=3, exit_fee=4),
                     leg(id="b", kind="put", quantity=-1, entry_price=3,
                         bid=4, ask=6, entry_fee=5, exit_fee=6)])
        result = analyze(data)
        expected = 200 * (7 - 5) - 100 * (6 - 3) - 18
        self.assertAlmostEqual(result["summary"]["liquidation_pnl"], expected)

    def test_contract_multiplier_scales_exposure(self):
        base = analyze(book([leg(multiplier=100)]))
        small = analyze(book([leg(multiplier=10)]))
        self.assertAlmostEqual(small["summary"]["model_pnl"], base["summary"]["model_pnl"] / 10)
        for name, value in base["summary"]["greeks"].items():
            self.assertAlmostEqual(small["summary"]["greeks"][name], value / 10)

    def test_naked_short_call_has_unbounded_loss_regardless_plot_range(self):
        data = book([leg(quantity=-1, entry_price=5, entry_fee=1, exit_fee=1)])
        result = analyze(data, dict(price_min=99, price_max=101))
        risk = result["risk"]
        self.assertTrue(risk["loss_unbounded"])
        self.assertIsNone(risk["maximum_loss"])
        self.assertAlmostEqual(risk["maximum_profit"], 498)
        self.assertEqual(risk["break_evens"], [104.98])

    def test_vertical_payoff_bounds_scale_every_region(self):
        data = book([leg(quantity=2, entry_price=6),
                     leg(id="b", quantity=-2, strike=110, entry_price=2)])
        portfolio = Portfolio.from_dict(data)
        risk = terminal_risk(portfolio)
        self.assertAlmostEqual(risk["maximum_profit"], 1200)
        self.assertAlmostEqual(risk["maximum_loss"], 800)
        self.assertEqual(risk["break_evens"], [104])
        value = portfolio_values(portfolio, date(2027, 10, 30), np.array([0, 100, 105, 110, 1000]))
        np.testing.assert_allclose(value - portfolio.entry_cash, [-800, -800, 200, 1200, 1200])

    def test_calendar_retains_long_time_value_and_blocks_later_date(self):
        data = book([leg(quantity=-1, expiry="2026-11-29", entry_price=3),
                     leg(id="b", quantity=1, expiry="2027-01-28", entry_price=5)])
        portfolio = Portfolio.from_dict(data)
        actual = portfolio_values(portfolio, date(2026, 11, 29), np.array([100]))[0]
        expected = 100 * independent_bsm(100, 100, 60 / 365, 0.05, 0.2)
        self.assertAlmostEqual(actual, expected, places=8)
        self.assertFalse(terminal_risk(portfolio)["available"])
        with self.assertRaises(ValueError):
            portfolio_values(portfolio, date(2026, 11, 30), np.array([100]))

    def test_entry_fill_never_becomes_iv_calibration_target(self):
        without_mark = book([leg(entry_price=50)])
        with self.assertRaises(ValueError):
            infer_leg_iv(without_mark, "a")
        mark = independent_bsm(100, 100, 1, 0.05, 0.4)
        current = book([leg(entry_price=50, mark_price=mark, quote_date="2026-10-30")])
        self.assertAlmostEqual(infer_leg_iv(current, "a")["volatility"], 0.4, places=7)
        current["legs"][0]["quote_date"] = "2026-10-29"
        with self.assertRaises(ValueError):
            infer_leg_iv(current, "a")

    def test_dividend_stock_cash_is_manual_and_warning_is_material(self):
        data = book([leg("stock")], cash_dividends=[dict(date="2026-11-10", amount=5)])
        result = analyze(data, dict(date="2026-11-11", spot=95, cash_adjustment=500))
        self.assertAlmostEqual(result["scenario"]["pnl"], 500)
        self.assertTrue(any("ACCIONES Y DIVIDENDOS" in item for item in result["warnings"]))
        self.assertTrue(any("caja adicional" in item for item in result["warnings"]))

    def test_time_plot_preserves_selected_date_and_dividend_event(self):
        data = book([leg(expiry="2027-01-28")],
                    cash_dividends=[dict(date="2026-11-09", amount=3)])
        result = analyze(data, dict(date="2026-11-16", spot=103))
        dates = result["time_evolution"]["dates"]
        self.assertIn("2026-11-08", dates)
        self.assertIn("2026-11-09", dates)
        self.assertIn("2026-11-16", dates)
        index = dates.index("2026-11-16")
        self.assertAlmostEqual(result["time_evolution"]["pnl"][index], result["scenario"]["pnl"], places=7)

    def test_invalid_inputs_cannot_silently_change_strategy(self):
        for field, value in [("quantity", True), ("quantity", 0.5),
                             ("quantity", 0), ("multiplier", 0),
                             ("entry_price", float("nan"))]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Portfolio.from_dict(book([leg(**{field: value})]))
        with self.assertRaises(ValueError):
            analyze(book(), dict(vol_shift=-0.3))
        with self.assertRaises(ValueError):
            Portfolio.from_dict(book(cash_dividends=[dict(date="2026-11-10", amount=5)], dividend_yield=0.01))
        with self.assertRaises(ValueError):
            Portfolio.from_dict(book([leg(underlying="DIFFERENT")]))


if __name__ == "__main__":
    unittest.main()
