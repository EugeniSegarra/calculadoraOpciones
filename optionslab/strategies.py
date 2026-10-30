"""Templates are editable collections of legs, never separate payoff formulas."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .portfolio import Portfolio
from .pricing import price_option

TEMPLATES = {
    "long_call": "Compra de call", "short_call": "Venta de call",
    "long_put": "Compra de put", "short_put": "Venta de put",
    "bull_call_spread": "Bull call spread (débito)", "bear_call_spread": "Bear call spread (crédito)",
    "bear_put_spread": "Bear put spread (débito)", "bull_put_spread": "Bull put spread (crédito)",
    "long_straddle": "Compra de straddle", "short_straddle": "Venta de straddle",
    "long_strangle": "Compra de strangle", "short_strangle": "Venta de strangle",
    "butterfly": "Butterfly de calls 1 : −2 : 1", "iron_condor": "Iron condor de crédito",
    "covered_call": "Covered call", "protective_put": "Protective put", "collar": "Collar",
    "call_calendar": "Calendar de calls (compra largo plazo)",
    "put_calendar": "Calendar de puts (compra largo plazo)",
    "call_diagonal": "Diagonal de calls (compra largo plazo)",
}


def template_list() -> list[dict]:
    return [{"id": key, "label": value} for key, value in TEMPLATES.items()]


def default_portfolio(as_of: date | None = None) -> dict:
    when = as_of or datetime.now(ZoneInfo("Europe/Madrid")).date()
    raw = dict(schema_version=1, name="Ejemplo hipotético · bull call spread", underlying="DEMO", currency="EUR",
               valuation_date=when.isoformat(), spot=100.0, rate=0.03, dividend_yield=0.0,
               cash_adjustment=0.0, cash_dividends=[], legs=[dict(id="seed", label="Call", kind="call", quantity=1,
               multiplier=100, strike=100, expiry=(when + timedelta(days=90)).isoformat(), volatility=0.25,
               style="european", entry_price=0)])
    return build_template("bull_call_spread", raw)


def build_template(template_id: str, portfolio_data: dict) -> dict:
    if template_id not in TEMPLATES:
        raise ValueError("Plantilla no reconocida.")
    portfolio = Portfolio.from_dict(portfolio_data)
    if portfolio.spot <= 0:
        raise ValueError("Una plantilla necesita spot positivo para construir sus strikes.")
    # Deliberately examples, not exchange-listed strikes/expiries or trade ideas.
    spot = portfolio.spot
    near = portfolio.valuation_date + timedelta(days=30)
    far = portfolio.valuation_date + timedelta(days=90)
    reference = next((x for x in portfolio.legs if x.kind != "stock"), None)
    volatility = reference.volatility if reference else 0.25
    style = reference.style if reference else "european"
    multiplier = reference.multiplier if reference else 100.0
    low, mid, high = spot * 0.95, spot, spot * 1.05
    outer_low, outer_high = spot * 0.9, spot * 1.1
    definitions = {
        "long_call": [("call", 1, mid, far)], "short_call": [("call", -1, mid, far)],
        "long_put": [("put", 1, mid, far)], "short_put": [("put", -1, mid, far)],
        "bull_call_spread": [("call", 1, mid, far), ("call", -1, high, far)],
        "bear_call_spread": [("call", -1, mid, far), ("call", 1, high, far)],
        "bear_put_spread": [("put", 1, mid, far), ("put", -1, low, far)],
        "bull_put_spread": [("put", -1, mid, far), ("put", 1, low, far)],
        "long_straddle": [("call", 1, mid, far), ("put", 1, mid, far)],
        "short_straddle": [("call", -1, mid, far), ("put", -1, mid, far)],
        "long_strangle": [("put", 1, low, far), ("call", 1, high, far)],
        "short_strangle": [("put", -1, low, far), ("call", -1, high, far)],
        "butterfly": [("call", 1, low, far), ("call", -2, mid, far), ("call", 1, high, far)],
        "iron_condor": [("put", 1, outer_low, far), ("put", -1, low, far), ("call", -1, high, far), ("call", 1, outer_high, far)],
        "covered_call": [("stock", multiplier, None, None), ("call", -1, high, far)],
        "protective_put": [("stock", multiplier, None, None), ("put", 1, low, far)],
        "collar": [("stock", multiplier, None, None), ("put", 1, low, far), ("call", -1, high, far)],
        "call_calendar": [("call", -1, mid, near), ("call", 1, mid, far)],
        "put_calendar": [("put", -1, mid, near), ("put", 1, mid, far)],
        "call_diagonal": [("call", -1, high, near), ("call", 1, mid, far)],
    }
    result = portfolio.to_dict()
    result["name"] = "Ejemplo hipotético · " + TEMPLATES[template_id]
    result["cash_adjustment"] = 0.0
    legs = []
    for i, (kind, quantity, strike, expiry) in enumerate(definitions[template_id]):
        leg = dict(id=f"leg-{i + 1}", label=("Compra " if quantity > 0 else "Venta ") + ("acciones" if kind == "stock" else f"{kind} {strike:g}"),
                   kind=kind, quantity=quantity, multiplier=1 if kind == "stock" else multiplier,
                   strike=strike, expiry=expiry.isoformat() if expiry else None,
                   volatility=volatility, style=style, mark_price=None, bid=None, ask=None,
                   entry_fee=0.0, exit_fee=0.0, quote_date=None)
        if kind == "stock":
            leg["entry_price"] = spot
        else:
            dividends = tuple(((d - portfolio.valuation_date).days / 365, a) for d, a in portfolio.cash_dividends if d <= expiry)
            leg["entry_price"] = float(price_option(spot=spot, strike=strike, time=(expiry - portfolio.valuation_date).days / 365,
                rate=portfolio.rate, volatility=volatility, option_type=kind, style=style, dividend_yield=portfolio.dividend_yield, dividends=dividends))
        legs.append(leg)
    result["legs"] = legs
    return result
