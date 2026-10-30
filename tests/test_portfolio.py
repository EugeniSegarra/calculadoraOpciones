"""Economic invariants and position accounting, independent terminal examples."""
import copy
from datetime import date
import json
import unittest

from optionslab.portfolio import Portfolio, analyze, infer_leg_iv, terminal_risk
from optionslab.pricing import price_option
from optionslab.strategies import TEMPLATES, build_template, default_portfolio


def position(kind="call", quantity=1, strike=100, entry=5, **kwargs):
    leg = dict(id="one", label="Prueba", kind=kind, quantity=quantity,
               multiplier=1 if kind == "stock" else 100, entry_price=entry,
               strike=strike, expiry="2027-01-28", volatility=.2, style="european")
    leg.update(kwargs)
    return dict(schema_version=1, name="Test", underlying="TEST", currency="EUR", valuation_date="2026-10-30",
                spot=100, rate=.03, dividend_yield=0, cash_adjustment=0, cash_dividends=[], legs=[leg])


class PortfolioTests(unittest.TestCase):
    def test_long_call_terminal_accounting(self):
        result = analyze(position(entry=6, quantity=3), {"date": "2027-01-28", "spot": 120})
        self.assertAlmostEqual(result["scenario"]["pnl"], 4200)
        self.assertEqual(result["risk"]["maximum_loss"], 1800)
        self.assertTrue(result["risk"]["profit_unbounded"])
        self.assertEqual(result["risk"]["break_evens"], [106])

    def test_short_call_loss_is_unlimited_not_plot_minimum(self):
        result = analyze(position(quantity=-2, entry=4), {"date": "2027-01-28", "spot": 130, "price_min": 90, "price_max": 110})
        self.assertAlmostEqual(result["scenario"]["pnl"], -5200)
        self.assertTrue(result["risk"]["loss_unbounded"])
        self.assertIsNone(result["risk"]["maximum_loss"])
        self.assertEqual(result["risk"]["maximum_profit"], 800)

    def test_short_put_downside_uses_zero_spot(self):
        risk = terminal_risk(Portfolio.from_dict(position("put", quantity=-2, entry=4)))
        self.assertFalse(risk["loss_unbounded"])
        self.assertEqual(risk["maximum_loss"], 19200)
        self.assertEqual(risk["maximum_profit"], 800)
        self.assertEqual(risk["break_evens"], [96])

    def test_spread_quantity_scales_entire_curve(self):
        data = position(entry=6, quantity=3)
        data["legs"].append(dict(data["legs"][0], id="two", strike=110, quantity=-3, entry_price=2))
        for spot, expected in [(80, -1200), (105, 300), (130, 1800)]:
            with self.subTest(spot=spot):
                self.assertAlmostEqual(analyze(data, {"date": "2027-01-28", "spot": spot})["scenario"]["pnl"], expected)

    def test_short_spread_loss_has_negative_sign(self):
        data = position(entry=6, quantity=-2)
        data["legs"].append(dict(data["legs"][0], id="two", strike=110, quantity=2, entry_price=2))
        result = analyze(data, {"date": "2027-01-28", "spot": 120})
        self.assertEqual(result["scenario"]["pnl"], -1200)
        self.assertEqual(result["risk"]["maximum_loss"], 1200)
        self.assertEqual(result["risk"]["maximum_profit"], 800)

    def test_offsetting_contracts_retain_cost_difference(self):
        data = position(entry=6, quantity=2, entry_fee=2, exit_fee=3)
        data["legs"].append(dict(data["legs"][0], id="two", quantity=-2, entry_price=7))
        result = analyze(data, {"spot": 135, "vol_shift": .1})
        self.assertAlmostEqual(result["summary"]["model_pnl"], 190)
        self.assertAlmostEqual(result["scenario"]["pnl"], 190)
        for greek in result["summary"]["greeks"].values():
            self.assertAlmostEqual(greek, 0)

    def test_entry_prices_not_mutated_by_revaluation(self):
        data = position(entry=7.123)
        before = copy.deepcopy(data)
        analyze(data, {"spot": 120, "date": "2026-11-20", "vol_shift": .1, "rate_shift": .02})
        self.assertEqual(data, before)

    def test_market_and_model_are_not_mixed(self):
        data = position(entry=5, mark_price=7)
        result = analyze(data)
        self.assertAlmostEqual(result["summary"]["market_pnl"], 200)
        self.assertNotAlmostEqual(result["summary"]["model_pnl"], 200)
        data["legs"].append(dict(data["legs"][0], id="two", mark_price=None))
        self.assertIsNone(analyze(data)["summary"]["market_pnl"])

    def test_mid_and_liquidation_use_correct_sides(self):
        data = position(entry=5, quantity=2, bid=6, ask=8)
        result = analyze(data)
        self.assertEqual(result["summary"]["market_pnl"], 400)
        self.assertEqual(result["summary"]["liquidation_pnl"], 200)
        data["legs"][0]["quantity"] = -2
        result = analyze(data)
        self.assertEqual(result["summary"]["market_pnl"], -400)
        self.assertEqual(result["summary"]["liquidation_pnl"], -600)

    def test_fees_are_total_per_leg_not_multiplied_again(self):
        self.assertEqual(analyze(position(entry=5, quantity=-3, mark_price=4, entry_fee=7, exit_fee=11))["summary"]["market_pnl"], 282)

    def test_cash_adjustments_applied_once_and_separately(self):
        data = position(entry=5, mark_price=6)
        data["cash_adjustment"] = 12
        result = analyze(data, {"cash_adjustment": -8})
        self.assertEqual(result["summary"]["market_pnl"], 112)
        self.assertAlmostEqual(result["scenario"]["pnl"], result["summary"]["model_pnl"] - 8)
        self.assertEqual(result["meta"]["time_cash_adjustment"], 0)

    def test_calendar_at_first_expiry_has_residual_option_value(self):
        data = position(quantity=-1, entry=3)
        data["legs"][0]["expiry"] = "2026-11-29"
        data["legs"].append(dict(data["legs"][0], id="two", quantity=1, entry_price=5, expiry="2027-01-28"))
        result = analyze(data, {"date": "2026-11-29", "spot": 100})
        residual = 100 * price_option(100, 100, 60/365, .03, .2)
        self.assertAlmostEqual(result["scenario"]["pnl"], residual - 200)
        self.assertFalse(result["risk"]["available"])
        with self.assertRaises(ValueError):
            analyze(data, {"date": "2026-11-30"})

    def test_multiplier_scales_prices_and_greeks(self):
        data = position()
        before = analyze(data)
        data["legs"][0]["multiplier"] = 10
        after = analyze(data)
        self.assertAlmostEqual(before["summary"]["model_pnl"], 10 * after["summary"]["model_pnl"])
        for greek in before["summary"]["greeks"]:
            self.assertAlmostEqual(before["summary"]["greeks"][greek], 10 * after["summary"]["greeks"][greek])

    def test_stock_quantity_represents_shares(self):
        result = analyze(position("stock", quantity=100, entry=95), {"spot": 110})
        self.assertEqual(result["summary"]["market_pnl"], 500)
        self.assertEqual(result["scenario"]["pnl"], 1500)
        self.assertEqual(result["summary"]["greeks"]["delta"], 100)

    def test_stock_dividend_income_needs_explicit_cash(self):
        data = position("stock", quantity=100, entry=100)
        data["cash_dividends"] = [{"date": "2026-11-10", "amount": 2}]
        result = analyze(data, {"date": "2026-11-10", "spot": 98})
        self.assertEqual(result["scenario"]["pnl"], -200)
        self.assertTrue(any("ACCIONES Y DIVIDENDOS" in x for x in result["warnings"]))
        self.assertEqual(analyze(data, {"date": "2026-11-10", "spot": 98, "cash_adjustment": 200})["scenario"]["pnl"], 0)

    def test_no_iv_from_historical_premium(self):
        data = position(entry=9)
        with self.assertRaises(ValueError):
            infer_leg_iv(data, "one")
        data["legs"][0]["mark_price"] = price_option(100, 100, 90/365, .03, .37)
        self.assertAlmostEqual(infer_leg_iv(data, "one")["volatility"], .37, places=7)
        data["legs"][0]["quote_date"] = "2026-10-29"
        with self.assertRaises(ValueError):
            infer_leg_iv(data, "one")

    def test_expiry_kink_not_a_normal_greek(self):
        result = analyze(position(), {"date": "2027-01-28", "spot": 100})
        self.assertIsNone(result["scenario"]["greeks"]["gamma"])

    def test_round_trip_json(self):
        first = Portfolio.from_dict(position())
        self.assertEqual(first, Portfolio.from_dict(json.loads(json.dumps(first.to_dict()))))

    def test_unknown_inputs_fail_instead_of_ignored(self):
        raw = position()
        raw["fx_rate"] = 1.2
        with self.assertRaises(ValueError):
            Portfolio.from_dict(raw)

    def test_invalid_inputs(self):
        cases = [("quantity", 0), ("quantity", 1.5), ("quantity", True), ("multiplier", 0),
                 ("entry_price", -1), ("strike", 0), ("volatility", -1), ("volatility", float("nan")),
                 ("expiry", "2026-01-01"), ("expiry", "2027-02-30"), ("style", "bermudan")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                raw = position()
                raw["legs"][0][key] = value
                with self.assertRaises(ValueError):
                    Portfolio.from_dict(raw)

    def test_crossed_quotes_and_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            Portfolio.from_dict(position(bid=7, ask=6))
        data = position()
        data["legs"].append(copy.deepcopy(data["legs"][0]))
        with self.assertRaises(ValueError):
            Portfolio.from_dict(data)

    def test_dividend_modes_cannot_double_count(self):
        data = position()
        data["dividend_yield"] = .02
        data["cash_dividends"] = [{"date": "2026-11-10", "amount": 1}]
        with self.assertRaises(ValueError):
            Portfolio.from_dict(data)

    def test_volatility_shocks_not_silently_clipped(self):
        with self.assertRaises(ValueError):
            analyze(position(), {"vol_shift": -.21})

    def test_templates_all_execute_and_preserve_one_underlying(self):
        base = default_portfolio(date(2026, 10, 30))
        for name in TEMPLATES:
            with self.subTest(template=name):
                data = build_template(name, base)
                result = analyze(data)
                self.assertAlmostEqual(result["summary"]["model_pnl"], 0, places=7)
                self.assertEqual(data["underlying"], "DEMO")
                json.dumps(result, allow_nan=False)

    def test_butterfly_ratio_and_covered_stock_size(self):
        base = default_portfolio(date(2026, 10, 30))
        butterfly = build_template("butterfly", base)
        self.assertEqual([x["quantity"] for x in butterfly["legs"]], [1, -2, 1])
        covered = build_template("covered_call", base)
        self.assertEqual(covered["legs"][0]["quantity"], covered["legs"][1]["multiplier"])
        self.assertFalse(analyze(covered)["risk"]["profit_unbounded"])


if __name__ == "__main__":
    unittest.main()
