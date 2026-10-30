"""Position accounting and full-revaluation scenarios for one underlying/currency.

The entry price is historical cost, never a model calibration target. A scenario
is a conditional mark of contracts still outstanding, not a forecast or ledger
of exercise/assignment. Dates have daily resolution and use ACT/365 Fixed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import math
import re
from typing import Any

import numpy as np

from . import __version__
from .pricing import implied_volatility, option_greeks, option_values, price_option

GREEKS = ("delta", "gamma", "theta", "vega", "rho")
MAX_LEGS = 32


def number(value: Any, label: str, lower: float = -1e12, upper: float = 1e12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: introduce un número, no texto ni booleanos.")
    result = float(value)
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{label}: debe ser finito y estar entre {lower:g} y {upper:g}.")
    return result


def iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label}: utiliza una fecha YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}: fecha no válida.") from exc


def text_field(value: Any, label: str, default: str, limit: int = 120) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label}: texto no vacío, máximo {limit} caracteres.")
    return value.strip()


def check_keys(data: Any, allowed: set[str], label: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"{label}: debe ser un objeto JSON.")
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{label}: campos no admitidos: {', '.join(sorted(unknown))}.")
    return data


@dataclass(frozen=True)
class Leg:
    id: str
    label: str
    kind: str
    quantity: float
    multiplier: float
    entry_price: float
    strike: float | None = None
    expiry: date | None = None
    volatility: float = 0.25
    style: str = "european"
    mark_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    quote_date: date | None = None

    @property
    def units(self) -> float:
        return self.quantity * self.multiplier

    @classmethod
    def from_dict(cls, data: dict, index: int, valuation_date: date) -> Leg:
        check_keys(data, set(cls.__dataclass_fields__), f"Pata {index + 1}")
        kind = data.get("kind")
        if kind not in ("call", "put", "stock"):
            raise ValueError(f"Pata {index + 1}: kind debe ser call, put o stock.")
        quantity = number(data.get("quantity"), "Cantidad", -1e6, 1e6)
        if quantity == 0 or (kind != "stock" and not quantity.is_integer()):
            raise ValueError("Cantidad: utiliza contratos enteros distintos de cero; el signo indica compra/venta.")
        multiplier = number(data.get("multiplier", 1 if kind == "stock" else 100), "Multiplicador", 1e-6, 1e6)
        if kind == "stock" and multiplier != 1:
            raise ValueError("Acciones: la cantidad son títulos y el multiplicador debe ser 1.")
        entry_price = number(data.get("entry_price"), "Precio de entrada", 0, 1e8)
        strike = None
        expiry = None
        if kind != "stock":
            strike = number(data.get("strike"), "Strike", 1e-6, 1e8)
            expiry = iso_date(data.get("expiry"), "Vencimiento")
            if expiry < valuation_date:
                raise ValueError("Hay una pata vencida: registra su liquidación y retírala antes de valorar.")
            if (expiry - valuation_date).days > 3650:
                raise ValueError("El alcance validado admite vencimientos de hasta diez años.")
        volatility = number(data.get("volatility", 0.25), "Volatilidad", 0, 3)
        style = data.get("style", "european")
        if style not in ("european", "american"):
            raise ValueError("Estilo de ejercicio: european o american.")
        quotes = {}
        for name in ("mark_price", "bid", "ask"):
            raw = data.get(name)
            quotes[name] = None if raw is None else number(raw, name, 0, 1e8)
        if quotes["bid"] is not None and quotes["ask"] is not None and quotes["bid"] > quotes["ask"]:
            raise ValueError("Cotización cruzada: bid no puede superar ask.")
        quote_date = iso_date(data["quote_date"], "Fecha cotización") if data.get("quote_date") else None
        return cls(
            id=text_field(data.get("id"), "ID", f"leg-{index + 1}", 60),
            label=text_field(data.get("label"), "Etiqueta", f"Pata {index + 1}"),
            kind=kind, quantity=quantity, multiplier=multiplier,
            entry_price=entry_price, strike=strike, expiry=expiry,
            volatility=volatility, style=style, **quotes,
            entry_fee=number(data.get("entry_fee", 0), "Coste entrada total pata", 0, 1e9),
            exit_fee=number(data.get("exit_fee", 0), "Coste salida total pata", 0, 1e9),
            quote_date=quote_date,
        )

    def to_dict(self) -> dict:
        result = asdict(self)
        result["expiry"] = self.expiry.isoformat() if self.expiry else None
        result["quote_date"] = self.quote_date.isoformat() if self.quote_date else None
        return result


@dataclass(frozen=True)
class Portfolio:
    name: str
    underlying: str
    currency: str
    valuation_date: date
    spot: float
    rate: float
    dividend_yield: float
    cash_adjustment: float
    cash_dividends: tuple[tuple[date, float], ...]
    legs: tuple[Leg, ...]
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> Portfolio:
        check_keys(data, set(cls.__dataclass_fields__), "Cartera")
        if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
            raise ValueError("schema_version debe ser 1.")
        valuation_date = iso_date(data.get("valuation_date"), "Fecha de valoración")
        currency = data.get("currency", "EUR")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Divisa: código de tres letras mayúsculas; una sola divisa por cartera.")
        raw_legs = data.get("legs")
        if not isinstance(raw_legs, list) or not 1 <= len(raw_legs) <= MAX_LEGS:
            raise ValueError(f"La cartera debe contener entre 1 y {MAX_LEGS} patas.")
        legs = tuple(Leg.from_dict(x, i, valuation_date) for i, x in enumerate(raw_legs))
        if len({leg.id for leg in legs}) != len(legs):
            raise ValueError("Cada pata necesita un ID único.")
        q = number(data.get("dividend_yield", 0), "Dividend yield", 0, 1)
        raw_dividends = data.get("cash_dividends", [])
        if not isinstance(raw_dividends, list) or len(raw_dividends) > 40:
            raise ValueError("Calendario: lista de hasta 40 dividendos.")
        by_date: dict[date, float] = {}
        for item in raw_dividends:
            check_keys(item, {"date", "amount"}, "Dividendo")
            d = iso_date(item.get("date"), "Fecha ex-dividendo")
            amount = number(item.get("amount"), "Dividendo por título", 1e-8, 1e7)
            if d <= valuation_date:
                raise ValueError("El calendario debe contener ex-fechas posteriores a la fecha base; el spot ya es ex-dividendo ese día.")
            by_date[d] = by_date.get(d, 0.0) + amount
        if q and by_date:
            raise ValueError("Utiliza yield continuo O dividendos discretos; combinarlos duplicaría dividendos.")
        return cls(
            name=text_field(data.get("name"), "Nombre", "Mi posición"),
            underlying=text_field(data.get("underlying"), "Subyacente", "DEMO", 40),
            currency=currency, valuation_date=valuation_date,
            spot=number(data.get("spot"), "Spot", 0, 1e8),
            rate=number(data.get("rate", 0), "Tipo continuo anual", -0.5, 1),
            dividend_yield=q,
            cash_adjustment=number(data.get("cash_adjustment", 0), "Ajuste de caja"),
            cash_dividends=tuple(sorted(by_date.items())), legs=legs,
        )

    @property
    def first_expiry(self) -> date | None:
        return min((leg.expiry for leg in self.legs if leg.expiry), default=None)

    @property
    def entry_cash(self) -> float:
        """Positive = net cost paid; negative = net credit received, fees included."""
        return sum(leg.units * leg.entry_price + leg.entry_fee for leg in self.legs)

    @property
    def exit_fees(self) -> float:
        return sum(leg.exit_fee for leg in self.legs)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["valuation_date"] = self.valuation_date.isoformat()
        result["cash_dividends"] = [{"date": d.isoformat(), "amount": a} for d, a in self.cash_dividends]
        result["legs"] = [leg.to_dict() for leg in self.legs]
        return result

    def parameters(self, leg: Leg, when: date, vol_shift: float = 0, rate_shift: float = 0) -> dict:
        sigma = leg.volatility + vol_shift
        if sigma < 0 or sigma > 3:
            raise ValueError(f"{leg.label}: el shock de volatilidad debe dejar IV entre 0% y 300%; no se recorta silenciosamente.")
        return dict(
            strike=leg.strike, time=(leg.expiry - when).days / 365,
            rate=self.rate + rate_shift, volatility=sigma,
            option_type=leg.kind, style=leg.style, dividend_yield=self.dividend_yield,
            dividends=tuple(((d - when).days / 365, a) for d, a in self.cash_dividends if when < d <= leg.expiry),
        )


def _sum_greeks(items: list[dict]) -> dict:
    return {name: None if any(x.get(name) is None for x in items) else sum(x[name] for x in items) for name in GREEKS}


def _leg_value(leg: Leg, portfolio: Portfolio, when: date, spots: np.ndarray, vol_shift: float = 0, rate_shift: float = 0) -> np.ndarray:
    if leg.kind == "stock":
        return spots * leg.units
    return np.asarray(option_values(spots=spots, **portfolio.parameters(leg, when, vol_shift, rate_shift)), dtype=float) * leg.units


def _position_greeks(leg: Leg, portfolio: Portfolio, when: date, spot: float, vol_shift: float = 0, rate_shift: float = 0) -> dict:
    if leg.kind == "stock":
        return dict(delta=leg.units, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)
    values = option_greeks(spot=spot, **portfolio.parameters(leg, when, vol_shift, rate_shift))
    return {name: None if values.get(name) is None else float(values[name]) * leg.units for name in GREEKS}


def _market_price(leg: Leg, spot: float, valuation_date: date | None = None) -> float | None:
    if leg.kind == "stock":
        return spot
    if valuation_date and leg.quote_date and leg.quote_date != valuation_date:
        return None
    if leg.mark_price is not None:
        return leg.mark_price
    if leg.bid is not None and leg.ask is not None:
        return (leg.bid + leg.ask) / 2
    return None


def portfolio_values(portfolio: Portfolio, when: date, spots: np.ndarray, vol_shift: float = 0, rate_shift: float = 0) -> np.ndarray:
    if when < portfolio.valuation_date or (portfolio.first_expiry and when > portfolio.first_expiry):
        raise ValueError("El horizonte debe estar entre fecha base y primer vencimiento. Después hacen falta liquidaciones y trayectoria.")
    total = np.zeros_like(np.asarray(spots, dtype=float))
    for leg in portfolio.legs:
        total += _leg_value(leg, portfolio, when, np.asarray(spots, dtype=float), vol_shift, rate_shift)
    return total


def terminal_risk(portfolio: Portfolio) -> dict:
    """Exact piecewise-linear terminal bounds, never extrema of a plotting grid.

    Conditional on outstanding contracts, no prior exercise/assignment and no
    additional dividends/funding cashflows. Cash already recorded is included.
    """
    expiries = {leg.expiry for leg in portfolio.legs if leg.expiry}
    if len(expiries) > 1:
        return dict(available=False, reason="Vencimientos distintos: no existe un payoff terminal único sin liquidaciones y trayectoria.", break_evens=[], zero_intervals=[], maximum_profit=None, maximum_loss=None, profit_unbounded=False, loss_unbounded=False)
    knots = sorted({0.0, *(leg.strike for leg in portfolio.legs if leg.strike is not None)})

    def payoff(spot: float) -> float:
        value = portfolio.cash_adjustment - portfolio.entry_cash - portfolio.exit_fees
        for leg in portfolio.legs:
            raw = spot if leg.kind == "stock" else max(spot - leg.strike, 0) if leg.kind == "call" else max(leg.strike - spot, 0)
            value += leg.units * raw
        return value

    ys = [payoff(x) for x in knots]
    slope = sum(leg.units for leg in portfolio.legs if leg.kind in ("stock", "call"))
    roots: list[float] = []
    intervals: list[list[float | None]] = []
    tolerance = 1e-8 * max(1.0, abs(portfolio.entry_cash), max(map(abs, ys)))
    for x, y in zip(knots, ys):
        if abs(y) <= tolerance:
            roots.append(x)
    for x1, x2, y1, y2 in zip(knots, knots[1:], ys, ys[1:]):
        if abs(y1) <= tolerance and abs(y2) <= tolerance:
            intervals.append([x1, x2])
        elif y1 * y2 < 0:
            roots.append(x1 - y1 * (x2 - x1) / (y2 - y1))
    if slope != 0:
        tail_root = knots[-1] - ys[-1] / slope
        if tail_root > knots[-1] + 1e-10:
            roots.append(tail_root)
    elif abs(ys[-1]) <= tolerance:
        intervals.append([knots[-1], None])
    profit_unbounded = slope > 0
    loss_unbounded = slope < 0
    return dict(
        available=True,
        reason="Payoff contractual a vencimiento común, sin ejercicio/asignación previos ni caja futura no registrada. No es margen del bróker.",
        break_evens=sorted(set(round(x, 10) for x in roots)), zero_intervals=intervals,
        maximum_profit=None if profit_unbounded else max(0.0, max(ys)),
        maximum_loss=None if loss_unbounded else max(0.0, -min(ys)),
        profit_unbounded=profit_unbounded, loss_unbounded=loss_unbounded,
    )


def analyze(portfolio_data: dict, scenario_data: dict | None = None) -> dict:
    portfolio = Portfolio.from_dict(portfolio_data)
    data = {} if scenario_data is None else scenario_data
    check_keys(data, {"date", "spot", "vol_shift", "rate_shift", "price_min", "price_max", "points", "cash_adjustment"}, "Escenario")
    when = iso_date(data.get("date", portfolio.valuation_date.isoformat()), "Fecha escenario")
    if when < portfolio.valuation_date or (portfolio.first_expiry and when > portfolio.first_expiry):
        raise ValueError("No se puede avanzar más allá del primer vencimiento ni retroceder antes de la fecha base; registra primero la liquidación de las patas vencidas.")
    if (when - portfolio.valuation_date).days > 3650:
        raise ValueError("El horizonte máximo es diez años.")
    scenario_spot = number(data.get("spot", portfolio.spot), "Spot escenario", 0, 1e8)
    vol_shift = number(data.get("vol_shift", 0), "Cambio absoluto IV", -3, 3)
    rate_shift = number(data.get("rate_shift", 0), "Cambio absoluto tipo", -1, 1)
    if not -0.5 <= portfolio.rate + rate_shift <= 1:
        raise ValueError("El tipo después del shock debe estar entre -50% y 100%.")
    scenario_cash = number(data.get("cash_adjustment", 0), "Caja adicional escenario")
    anchors = [portfolio.spot, scenario_spot, *(leg.strike for leg in portfolio.legs if leg.strike)]
    typical = max(max(anchors), 1.0)
    price_min = number(data.get("price_min", max(0.0, min(anchors) * 0.6)), "Spot mínimo gráfico", 0, 1e8)
    price_max = number(data.get("price_max", typical * 1.4), "Spot máximo gráfico", 0, 1e8)
    points = number(data.get("points", 81), "Puntos gráfico", 11, 201)
    if not points.is_integer() or price_max <= price_min:
        raise ValueError("Malla: puntos enteros entre 11 y 201 y máximo mayor que mínimo.")
    # Insert kinks and exact current/scenario spots into the grid, avoiding a
    # visually smoothed terminal payoff or a missing evaluated scenario marker.
    spots = np.unique(np.concatenate([np.linspace(price_min, price_max, int(points)), np.array([x for x in anchors if price_min <= x <= price_max])]))
    cost = portfolio.entry_cash + portfolio.exit_fees - portfolio.cash_adjustment
    warnings = [
        "Escenarios condicionales con IV por strike constante y shocks paralelos; no son una previsión ni una probabilidad de beneficio.",
        "P&L nominal neto de los costes introducidos. Financiación, impuestos y dividendos cobrados/pagados solo se incluyen si se registran como caja.",
        "Fechas diarias ACT/365: el día de vencimiento se usa el payoff; no se modelan intradía, fixing AM/PM ni calendarios de mercado.",
    ]
    has_options = any(leg.kind != "stock" for leg in portfolio.legs)
    if any(leg.kind == "stock" for leg in portfolio.legs) and (portfolio.dividend_yield or portfolio.cash_dividends):
        warnings.append("ACCIONES Y DIVIDENDOS: el calendario/yield valora opciones, pero no suma automáticamente ingresos futuros a las acciones. Registra dividendos pasados en caja de cartera y futuros en caja de escenario; con solo el spot final no se conoce la trayectoria de pagos.")
    if portfolio.cash_dividends:
        warnings.append("Dividendos discretos: modelo de salto de spot con responsabilidad limitada (dividendo efectivo min(D,S)); no equivale a restar simplemente su valor actual al spot.")
    if len({leg.volatility for leg in portfolio.legs if leg.kind != "stock"}) > 1:
        warnings.append("Las IV individuales no constituyen una superficie calibrada libre de arbitraje. Revisa coherencia entre strikes y vencimientos.")
    if any(leg.style == "american" and leg.kind != "stock" for leg in portfolio.legs):
        warnings.append("Opciones americanas: el valor incluye ejercicio óptimo bajo el modelo; los escenarios suponen que las patas siguen abiertas. La asignación real transforma opciones en acciones/caja y debe registrarse antes de seguir.")
    if any(leg.style == "american" and leg.quantity < 0 and leg.kind != "stock" for leg in portfolio.legs):
        warnings.append("Hay opciones americanas vendidas: existe riesgo de asignación anticipada, especialmente alrededor del ex-dividendo. La pata comprada no se ejerce automáticamente para cubrirla.")
    if portfolio.first_expiry and (portfolio.first_expiry - portfolio.valuation_date).days <= 2:
        warnings.append("Vencimiento próximo: las sensibilidades y la asignación pueden cambiar bruscamente; esta herramienta diaria no sirve como motor intradía 0DTE.")
    rows = []
    model_value = 0.0
    market_value: float | None = 0.0
    liquidation_value: float | None = 0.0
    scenario_greeks = []
    for leg in portfolio.legs:
        price = portfolio.spot if leg.kind == "stock" else float(price_option(spot=portfolio.spot, **portfolio.parameters(leg, portfolio.valuation_date)))
        model_value += leg.units * price
        mark = _market_price(leg, portfolio.spot, portfolio.valuation_date)
        if market_value is not None:
            market_value = None if mark is None else market_value + leg.units * mark
        # Closing bid/ask is deliberately not substituted with a model/mid.
        close_price = leg.bid if leg.quantity > 0 else leg.ask
        if leg.quote_date and leg.quote_date != portfolio.valuation_date:
            close_price = None
        if liquidation_value is not None:
            liquidation_value = None if close_price is None else liquidation_value + leg.units * close_price
        greek = _position_greeks(leg, portfolio, portfolio.valuation_date, portfolio.spot)
        scenario_greeks.append(_position_greeks(leg, portfolio, when, scenario_spot, vol_shift, rate_shift))
        fees = leg.entry_fee + leg.exit_fee
        rows.append(dict(id=leg.id, label=leg.label, model_price=price, mark_price=mark, model_pnl=leg.units * (price - leg.entry_price) - fees, market_pnl=None if mark is None else leg.units * (mark - leg.entry_price) - fees, **greek))
        if leg.quote_date and leg.quote_date != portfolio.valuation_date:
            warnings.append(f"{leg.label}: la cotización es de {leg.quote_date}, distinta de la fecha base; se excluye de P&L de mercado y cierre actuales.")
        if leg.mark_price is not None and leg.bid is not None and leg.ask is not None and not leg.bid <= leg.mark_price <= leg.ask:
            warnings.append(f"{leg.label}: la marca queda fuera del bid/ask introducido; revisa el snapshot.")
        if leg.kind != "stock" and (leg.expiry == when or leg.volatility + vol_shift == 0):
            warnings.append(f"{leg.label}: vencimiento o IV cero; las griegas pueden ser no suaves o no estar definidas.")
    if market_value is None:
        warnings.append("Faltan marcas de opciones: el P&L de mercado agregado queda sin calcular; no se mezclan marcas reales con precios teóricos.")
    if liquidation_value is None:
        warnings.append("Falta bid para alguna pata larga o ask para alguna corta: no hay estimación completa de cierre al bid/ask.")
    greeks = _sum_greeks(rows)
    today_curve = portfolio_values(portfolio, portfolio.valuation_date, spots) - cost
    horizon_curve = portfolio_values(portfolio, when, spots, vol_shift, rate_shift) - cost + scenario_cash
    scenario_value = float(portfolio_values(portfolio, when, np.array([scenario_spot]), vol_shift, rate_shift)[0])
    # Time slices at a fixed scenario spot. They are NOT a simulated price path.
    end = portfolio.first_expiry or when
    days = max(0, (end - portfolio.valuation_date).days)
    offset_set = {int(x) for x in np.linspace(0, days, min(9, days + 1))}
    offset_set.add((when - portfolio.valuation_date).days)
    # Keep event discontinuities and the selected scenario visible; connecting
    # only evenly spaced dates could hide an ex-dividend jump.
    for dividend_date, _ in portfolio.cash_dividends:
        day = (dividend_date - portfolio.valuation_date).days
        if 0 < day <= days:
            offset_set.update((day - 1, day))
    offsets = sorted(offset_set)
    dates = [portfolio.valuation_date + timedelta(days=x) for x in offsets]
    time_pnl = [float(portfolio_values(portfolio, d, np.array([scenario_spot]), vol_shift, rate_shift)[0]) - cost for d in dates]
    if scenario_cash:
        warnings.append("La caja adicional de escenario se aplica solo a la fecha elegida y a su curva; el gráfico temporal la excluye porque no se ha indicado el calendario de flujos.")
    risk = terminal_risk(portfolio)
    if has_options and any(leg.style == "american" for leg in portfolio.legs):
        risk["reason"] += " En americanas es condicional a que no haya habido ejercicio/asignación anticipados."
    return dict(
        summary=dict(entry_cash=portfolio.entry_cash, model_value=model_value, market_value=market_value,
                     model_pnl=model_value - cost, market_pnl=None if market_value is None else market_value - cost,
                     liquidation_pnl=None if liquidation_value is None else liquidation_value - cost,
                     greeks=greeks, delta_notional=None if greeks["delta"] is None else greeks["delta"] * portfolio.spot),
        legs=rows,
        scenario=dict(date=when.isoformat(), spot=scenario_spot, model_value=scenario_value, pnl=scenario_value - cost + scenario_cash,
                      change_from_model=scenario_value - model_value + scenario_cash,
                      change_from_market=None if market_value is None else scenario_value - market_value + scenario_cash,
                      greeks=_sum_greeks(scenario_greeks)),
        curve=dict(spots=spots.tolist(), today_pnl=today_curve.tolist(), horizon_pnl=horizon_curve.tolist()),
        time_evolution=dict(dates=[d.isoformat() for d in dates], pnl=time_pnl),
        risk=risk, warnings=warnings,
        meta=dict(first_expiry=portfolio.first_expiry.isoformat() if portfolio.first_expiry else None,
                  version=__version__, time_spot=scenario_spot, time_vol_shift=vol_shift, time_rate_shift=rate_shift,
                  time_cash_adjustment=0, numerical_model="BSM / finite differences", market_data="manual snapshot"),
    )


def infer_leg_iv(portfolio_data: dict, leg_id: str) -> dict:
    portfolio = Portfolio.from_dict(portfolio_data)
    leg = next((x for x in portfolio.legs if x.id == leg_id), None)
    if leg is None or leg.kind == "stock":
        raise ValueError("Selecciona una pata de opciones existente.")
    if leg.quote_date and leg.quote_date != portfolio.valuation_date:
        raise ValueError("La marca y el spot deben corresponder a la misma fecha para inferir IV.")
    mark = _market_price(leg, portfolio.spot, portfolio.valuation_date)
    if mark is None:
        raise ValueError("Introduce una marca actual o bid y ask actuales. La prima histórica de entrada no se usa para inferir IV.")
    params = portfolio.parameters(leg, portfolio.valuation_date)
    params.pop("volatility")
    iv = float(implied_volatility(price=mark, spot=portfolio.spot, **params))
    if iv > 3:
        raise ValueError("La IV inferida supera el alcance de 300% de esta aplicación.")
    return {"volatility": iv}
