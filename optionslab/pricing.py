"""Vanilla equity/index options under a flat, risk-neutral diffusion.

European options without cash dividends use Black--Scholes--Merton. Other
contracts use a nonuniform-grid Crank--Nicolson finite-difference solver,
Rannacher damping and policy iteration for the American exercise obstacle.
Discrete dividends are jumps S_after = max(S_before - D, 0) (the liquidator
convention: the actual dividend cannot exceed the stock). A dividend at expiry
is paid immediately before the payoff. All rates/volatilities are decimals.

The numerical model is deliberately explicit: it is not a calibrated volatility
surface, an assignment simulator or a real-world return model. See methodology.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.linalg import solve_banded
from scipy.interpolate import CubicSpline
from scipy.optimize import brentq
from scipy.special import ndtr

YEAR_DAYS = 365.0


def _european_equivalent(option_type, style, rate, dividend_yield):
    return style == "european" or (
        (option_type == "call" and dividend_yield <= 0 and rate >= 0)
        or (option_type == "put" and dividend_yield >= 0 and rate <= 0)
    )


def _inputs(strike, time, rate, volatility, option_type, style, dividend_yield,
            dividends, steps):
    values = (strike, time, rate, volatility, dividend_yield)
    if any(isinstance(x, (bool, np.bool_)) for x in values):
        raise ValueError("Los parámetros financieros deben ser números, no booleanos.")
    try:
        strike, time, rate, volatility, dividend_yield = map(float, values)
    except (TypeError, ValueError) as exc:
        raise ValueError("Parámetros numéricos no válidos.") from exc
    if not all(math.isfinite(x) for x in (strike, time, rate, volatility, dividend_yield)):
        raise ValueError("Todos los parámetros deben ser finitos.")
    if strike <= 0 or time < 0 or volatility < 0:
        raise ValueError("Strike > 0; tiempo y volatilidad >= 0.")
    if time > 50 or volatility > 5 or abs(rate) > 1 or abs(dividend_yield) > 1:
        raise ValueError("Fuera de rango: T <= 50 años, volatilidad <= 500%, |r| y |q| <= 100%.")
    if option_type not in ("call", "put") or style not in ("european", "american"):
        raise ValueError("Tipo call/put y ejercicio european/american requeridos.")
    if isinstance(steps, (bool, np.bool_)) or not isinstance(steps, (int, np.integer)) or not 50 <= steps <= 2000:
        raise ValueError("steps debe ser un entero entre 50 y 2000.")
    schedule = {}
    if not isinstance(dividends, (tuple, list)) or len(dividends) > 100:
        raise ValueError("Dividendos: lista de como máximo 100 pares (tiempo, importe).")
    for item in dividends:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("Cada dividendo debe contener (tiempo, importe).")
        if any(isinstance(x, (bool, np.bool_)) for x in item):
            raise ValueError("Dividendos: use números, no booleanos.")
        try:
            dt, amount = map(float, item)
        except (TypeError, ValueError) as exc:
            raise ValueError("Dividendo no numérico.") from exc
        if not math.isfinite(dt) or not math.isfinite(amount) or not 0 < dt <= time or amount < 0:
            raise ValueError("Dividendos: 0 < tiempo <= vencimiento e importe finito >= 0.")
        if amount:
            schedule[dt] = schedule.get(dt, 0.0) + amount
    dividends = tuple(sorted(schedule.items()))
    if dividends and dividend_yield != 0:
        raise ValueError("Use dividendos discretos o yield continuo, no ambos.")
    return strike, time, rate, volatility, option_type, style, dividend_yield, dividends, int(steps)


def _spots(spots):
    if isinstance(spots, (bool, np.bool_)) or any(isinstance(x, (bool, np.bool_)) for x in np.asarray(spots, dtype=object).flat):
        raise ValueError("Spot debe ser numérico, no booleano.")
    try:
        array = np.asarray(spots, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Los precios del subyacente deben ser numéricos.") from exc
    if array.ndim > 1 or array.size > 10000 or not np.all(np.isfinite(array)) or np.any(array < 0):
        raise ValueError("Se requiere un vector de hasta 10000 precios finitos >= 0.")
    return array


def _intrinsic(spots, strike, option_type):
    return np.maximum((1 if option_type == "call" else -1) * (spots - strike), 0.0)


def _bsm(spots, strike, time, rate, volatility, option_type, dividend_yield):
    if time == 0:
        return _intrinsic(spots, strike, option_type)
    dr, dq = math.exp(-rate * time), math.exp(-dividend_yield * time)
    if volatility == 0:
        return _intrinsic(spots * dq, strike * dr, option_type)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(spots / strike) + (rate - dividend_yield + volatility * volatility / 2) * time) / (volatility * math.sqrt(time))
    d2 = d1 - volatility * math.sqrt(time)
    # Evaluate the out-of-the-money option first and recover ITM by parity.
    # This avoids subtracting nearly equal large terms in a deep ITM option.
    call = spots * dq * ndtr(d1) - strike * dr * ndtr(d2)
    put = strike * dr * ndtr(-d2) - spots * dq * ndtr(-d1)
    forward_diff = spots * dq - strike * dr
    if option_type == "call":
        result = np.where(forward_diff > 0, put + forward_diff, call)
    else:
        result = np.where(forward_diff < 0, call - forward_diff, put)
    return np.maximum(result, 0.0)


def _deterministic(spots, strike, time, rate, option_type, style,
                   dividend_yield, dividends):
    """Exact zero-volatility optimal stopping, including negative rates."""
    initial = np.asarray(spots, dtype=float)
    current = initial.copy()
    best = _intrinsic(current, strike, option_type)
    previous = 0.0
    carry = rate - dividend_yield
    for end, amount in (*dividends, (time, 0.0)):
        duration = end - previous
        if style == "american" and carry and dividend_yield and rate / dividend_yield > 0:
            target = rate * strike / dividend_yield
            with np.errstate(divide="ignore", invalid="ignore"):
                critical = np.log(target / current) / carry
            inside = (critical > 0) & (critical < duration)
            safe = np.where(inside, critical, 0.0)
            payoff = math.exp(-rate * previous) * np.exp(-rate * safe) * _intrinsic(current * np.exp(carry * safe), strike, option_type)
            best = np.maximum(best, np.where(inside, payoff, 0.0))
        current = current * math.exp(carry * duration)
        if style == "american":
            best = np.maximum(best, math.exp(-rate * end) * _intrinsic(current, strike, option_type))
        current = np.maximum(current - amount, 0.0)
        if style == "american":
            best = np.maximum(best, math.exp(-rate * end) * _intrinsic(current, strike, option_type))
        previous = end
    if style == "american":
        return best
    return math.exp(-rate * time) * _intrinsic(current, strike, option_type)


def _policy_solve(lower, diagonal, upper, rhs, obstacle, initial):
    """Solve min(Ax-b, x-payoff)=0 by Howard policy iteration."""
    x = initial.copy()
    prior = None
    for _ in range(100):
        residual = diagonal * x - rhs
        residual[1:] += lower[1:] * x[:-1]
        residual[:-1] += upper[:-1] * x[1:]
        exercise = (x - obstacle) < residual
        if prior is not None and np.array_equal(exercise, prior):
            return x
        d = np.where(exercise, 1.0, diagonal)
        lo = np.where(exercise, 0.0, lower)
        up = np.where(exercise, 0.0, upper)
        b = np.where(exercise, obstacle, rhs)
        bands = np.zeros((3, len(d)))
        bands[0, 1:] = up[:-1]
        bands[1] = d
        bands[2, :-1] = lo[1:]
        x = solve_banded((1, 1), bands, b, check_finite=False)
        prior = exercise
    raise ArithmeticError("El solver de ejercicio americano no ha convergido.")


def _fd_values(spots, strike, time, rate, volatility, option_type, style,
               dividend_yield, dividends, steps):
    """Price all requested spots on one grid; no interpolation across expiries."""
    if volatility * math.sqrt(time) > 3*(1+1e-12) or max(abs(rate), abs(dividend_yield)) * time > 3*(1+1e-12):
        raise ValueError("Régimen extremo fuera del dominio validado del motor numérico (sigma*sqrt(T) <= 3 y |rT|,|qT| <= 3).")
    # The sinh mesh resolves the exercise kink while keeping far boundaries out
    # in the tails. Include the exact strike to avoid payoff-grid alignment bias.
    scale = max(strike, float(np.max(spots)), sum(d for _, d in dividends))
    tail = max(math.log(4.0), 7 * volatility * math.sqrt(time) + max(0.0, (rate - dividend_yield) * time))
    upper_spot = scale * math.exp(tail)
    concentration = strike * max(1e-8, min(.2, volatility * math.sqrt(time)))
    n = max(250, min(6000, steps * 3))
    transformed = np.linspace(math.asinh(-strike / concentration), math.asinh((upper_spot - strike) / concentration), n + 1)
    grid = strike + concentration * np.sinh(transformed)
    grid[0], grid[-1] = 0.0, upper_spot
    grid = np.unique(np.append(grid, strike))
    s = grid[1:-1]
    hm, hp = s - grid[:-2], grid[2:] - s
    diffusion = .5 * volatility * volatility * s * s
    drift = (rate - dividend_yield) * s
    lower = 2 * diffusion / (hm * (hm + hp)) - drift * hp / (hm * (hm + hp))
    upper = 2 * diffusion / (hp * (hm + hp)) + drift * hm / (hp * (hm + hp))
    # A positive-coefficient generator is required by policy iteration. Switch
    # to one-sided drift only where central differencing violates that condition.
    bad = (lower < 0) | (upper < 0)
    lower = np.where(bad, 2 * diffusion / (hm * (hm + hp)) + np.maximum(-drift, 0) / hm, lower)
    upper = np.where(bad, 2 * diffusion / (hp * (hm + hp)) + np.maximum(drift, 0) / hp, upper)
    middle = -lower - upper - rate
    payoff = _intrinsic(grid, strike, option_type)
    values = payoff.copy()
    event_map = dict(dividends)
    times = np.unique(np.r_[np.linspace(0.0, time, steps + 1), [d for d, _ in dividends]])[::-1]
    damping = True

    def boundary(calendar_time):
        remaining = time - calendar_time
        future = tuple((dt - calendar_time, cash) for dt, cash in dividends if dt > calendar_time + 1e-14)
        return _deterministic(np.array([0.0, upper_spot]), strike, remaining, rate, option_type, style, dividend_yield, future)

    def advance(old, old_time, new_time, weight):
        dt = old_time - new_time
        new_boundary = boundary(new_time)
        lo, di, up = -weight * dt * lower, 1 - weight * dt * middle, -weight * dt * upper
        rhs = old[1:-1] + (1 - weight) * dt * (lower * old[:-2] + middle * old[1:-1] + upper * old[2:])
        rhs[0] -= lo[0] * new_boundary[0]
        rhs[-1] -= up[-1] * new_boundary[1]
        lo, up = lo.copy(), up.copy()
        lo[0], up[-1] = 0.0, 0.0
        if style == "american":
            interior = _policy_solve(lo, di, up, rhs, payoff[1:-1], old[1:-1])
        else:
            bands = np.zeros((3, len(di)))
            bands[0, 1:], bands[1], bands[2, :-1] = up[:-1], di, lo[1:]
            interior = solve_banded((1, 1), bands, rhs, check_finite=False)
        result = np.empty_like(old)
        result[0], result[-1], result[1:-1] = new_boundary[0], new_boundary[1], interior
        return result

    for old_time, new_time in zip(times[:-1], times[1:]):
        if old_time in event_map:
            values = np.interp(np.maximum(grid - event_map[old_time], 0.0), grid, values)
            if style == "american":
                values = np.maximum(values, payoff)
            damping = True
        if damping:
            half = (old_time + new_time) / 2
            values = advance(values, old_time, half, 1.0)
            values = advance(values, half, new_time, 1.0)
            damping = False
        else:
            values = advance(values, old_time, new_time, .5)
    if not np.all(np.isfinite(values)) or np.min(values) < -1e-7 * max(strike, 1.0):
        raise ArithmeticError("Solución numérica no finita o negativa; aumente la resolución o revise los parámetros.")
    # Smooth interpolation is required for local Greeks. Linear interpolation
    # produces artificial zero-curvature pieces and grid-dependent gamma.
    result = np.maximum(CubicSpline(grid, np.maximum(values, 0.0), bc_type="natural", extrapolate=False)(spots), 0.0)
    if style == "american":
        result = np.maximum(result, _intrinsic(spots, strike, option_type))
    return result


def option_values(spots: Sequence[float], strike: float, time: float, rate: float,
                  volatility: float, option_type: str = "call", style: str = "european",
                  dividend_yield: float = 0.0, dividends=(), steps: int = 400) -> np.ndarray:
    """Price a vector of spots, per underlying unit (multiply at position level).

    ``time`` and dividend times are remaining ACT/365 year fractions. For
    cash dividends the input spot is before every supplied future event. A
    continuous yield and cash dividends cannot be supplied together.
    """
    strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps = _inputs(strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)
    spots = _spots(spots)
    if spots.size == 0:
        return np.array([], dtype=float)
    if time == 0:
        return _intrinsic(spots, strike, option_type)
    if volatility == 0:
        return _deterministic(spots, strike, time, rate, option_type, style, dividend_yield, dividends)
    european_equivalent = _european_equivalent(option_type, style, rate, dividend_yield)
    if not dividends and european_equivalent:
        return _bsm(spots, strike, time, rate, volatility, option_type, dividend_yield)
    result = _fd_values(spots, strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)
    if style == "american" and not dividends:
        # Enforce the known European lower bound against finite-grid error.
        result = np.maximum(result, _bsm(spots, strike, time, rate, volatility, option_type, dividend_yield))
    return result


def price_option(spot: float, strike: float, time: float, rate: float,
                 volatility: float, option_type: str = "call", style: str = "european",
                 dividend_yield: float = 0.0, dividends=(), steps: int = 400) -> float:
    """Scalar wrapper for :func:`option_values`."""
    if isinstance(spot, (bool, np.bool_)):
        raise ValueError("Spot debe ser un número, no un booleano.")
    return float(option_values([spot], strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)[0])


def option_greeks(spot: float, strike: float, time: float, rate: float,
                  volatility: float, option_type: str = "call", style: str = "european",
                  dividend_yield: float = 0.0, dividends=(), steps: int = 400) -> dict:
    """Local sensitivities per unit, holding each leg's IV fixed.

    delta = dV/dS; gamma = d²V/dS²; theta = dV/d(calendar day);
    vega = dV/d(sigma percentage point); rho = dV/d(rate percentage point).
    At expiry time sensitivities are undefined (None), with payoff delta and
    gamma provided only away from the strike. At sigma=0, Greeks are not
    reported for the degenerate deterministic model; a positive volatility is
    required for smooth, comparable local risk.
    Numerical American/dividend spatial/parameter Greeks are finite-difference
    approximations; local theta uses the pricing PDE in continuation and is
    zero in the immediate exercise region. Vega/rho use maximum bumps of 0.1
    volatility percentage points / 0.01 rate percentage points respectively.
    """
    strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps = _inputs(strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)
    spot = float(_spots([spot])[0])
    price = price_option(spot, strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)
    if time == 0:
        kink = abs(spot - strike) <= 1e-12 * max(1.0, strike)
        delta = None if kink else (float(spot > strike) if option_type == "call" else -float(spot < strike))
        return dict(price=price, delta=delta, gamma=None if kink else 0.0, theta=None, vega=None, rho=None)
    if volatility == 0:
        return dict(price=price, delta=None, gamma=None, theta=None, vega=None, rho=None)
    analytical = not dividends and _european_equivalent(option_type, style, rate, dividend_yield)
    if spot == 0:
        if analytical:
            if option_type == "call":
                return dict(price=price, delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)
            return dict(price=price, delta=-math.exp(-dividend_yield*time), gamma=0.0, theta=rate*price/YEAR_DAYS, vega=0.0, rho=-time*price*.01)
        # The degenerate absorbing boundary can coincide with a change of the
        # optimal exercise policy. Do not differentiate roundoff-sized prices.
        return dict(price=price, delta=None, gamma=None, theta=None, vega=None, rho=None)
    if analytical and volatility > 0 and spot > 0:
        sqrt_t = math.sqrt(time)
        dr, dq = math.exp(-rate * time), math.exp(-dividend_yield * time)
        d1 = (math.log(spot / strike) + (rate - dividend_yield + .5 * volatility ** 2) * time) / (volatility * sqrt_t)
        d2 = d1 - volatility * sqrt_t
        density = math.exp(-.5 * d1 * d1) / math.sqrt(2 * math.pi)
        sign = 1 if option_type == "call" else -1
        delta = sign * dq * ndtr(sign * d1)
        gamma = dq * density / (spot * volatility * sqrt_t)
        theta = (-spot * dq * density * volatility / (2 * sqrt_t) + sign * dividend_yield * spot * dq * ndtr(sign * d1) - sign * rate * strike * dr * ndtr(sign * d2)) / YEAR_DAYS
        vega = spot * dq * density * sqrt_t * .01
        rho = sign * strike * time * dr * ndtr(sign * d2) * .01
        return {k: float(v) for k, v in dict(price=price, delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho).items()}
    # A wider spot bump than machine epsilon is essential for stable Greeks of
    # an interpolated numerical grid. All spot bumps share the same PDE solve.
    h = max(spot * min(.005, .1 * volatility * math.sqrt(time)), strike * 1e-8)
    if spot >= 2 * h:
        nodes = np.array([spot - 2*h, spot - h, spot, spot + h, spot + 2*h])
        p = option_values(nodes, strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)
        delta = (p[0] - 8*p[1] + 8*p[3] - p[4]) / (12*h)
        gamma = (-p[0] + 16*p[1] - 30*p[2] + 16*p[3] - p[4]) / (12*h*h)
    else:
        nodes = np.array([spot, spot+h, spot+2*h, spot+3*h])
        p = option_values(nodes, strike, time, rate, volatility, option_type, style, dividend_yield, dividends, steps)
        delta = (-3*p[0]+4*p[1]-p[2])/(2*h)
        gamma = (2*p[0]-5*p[1]+4*p[2]-p[3])/(h*h)

    def value(t=time, r=rate, vol=volatility, schedule=dividends):
        return price_option(spot, strike, t, r, vol, option_type, style, dividend_yield, schedule, steps)

    def derivative(x, h, lower, upper, function):
        if x - h >= lower and x + h <= upper:
            return (function(x + h) - function(x - h)) / (2 * h)
        if x + 2 * h <= upper:
            return (-3 * price + 4 * function(x + h) - function(x + 2 * h)) / (2 * h)
        if x - 2 * h >= lower:
            return (3 * price - 4 * function(x - h) + function(x - 2 * h)) / (2 * h)
        return None

    numerical = not analytical
    vol_cap = min(5.0, 3/math.sqrt(time)) if numerical else 5.0
    rate_cap = min(1.0, 3/time) if numerical else 1.0
    dv = min(.001, max(volatility / 20, 1e-5))
    raw_vega = derivative(volatility, dv, 0.0, vol_cap, lambda x: value(vol=x))
    raw_rho = derivative(rate, .0001, -rate_cap, rate_cap, lambda x: value(r=x))
    vega = None if raw_vega is None else raw_vega * .01
    rho = None if raw_rho is None else raw_rho * .01
    # The local PDE gives calendar-time theta in the continuation region. This
    # avoids replacing an instantaneous derivative by a one-day price change
    # near expiry, and naturally keeps every future dividend on its calendar.
    # Between exercise and expiry, an exercised intrinsic payoff has theta 0.
    intrinsic = float(_intrinsic(np.asarray(spot), strike, option_type))
    if style == "american" and price - intrinsic <= 1e-10 * max(strike, 1.0):
        theta = 0.0
    else:
        theta = -(0.5*volatility*volatility*spot*spot*gamma + (rate-dividend_yield)*spot*delta - rate*price)/YEAR_DAYS
    return {k: None if v is None else float(v) for k, v in dict(price=price, delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho).items()}


def implied_volatility(price: float, spot: float, strike: float, time: float,
                       rate: float, option_type: str = "call", style: str = "european",
                       dividend_yield: float = 0.0, dividends=(), steps: int = 400,
                       max_volatility: float = 5.0, tolerance: float = 1e-8) -> float:
    """Invert the selected model with a bracketed root; never clip bad quotes.

    At expiry IV is unidentified. In an American exercise region many low
    volatilities can give intrinsic value: a quote at the zero-volatility bound
    is rejected there instead of presenting an arbitrary unique IV of zero.
    Numerical-model inversion requires a price tolerance compatible with mesh
    error; the reported root is not a market calibration accuracy guarantee.
    """
    strike, time, rate, _, option_type, style, dividend_yield, dividends, steps = _inputs(strike, time, rate, 0.0, option_type, style, dividend_yield, dividends, steps)
    spot = float(_spots([spot])[0])
    try:
        price, max_volatility, tolerance = float(price), float(max_volatility), float(tolerance)
    except (TypeError, ValueError) as exc:
        raise ValueError("Precio, volatilidad máxima y tolerancia deben ser numéricos.") from exc
    if not all(math.isfinite(x) for x in (price, max_volatility, tolerance)) or price < 0 or not 0 < max_volatility <= 5 or not 0 < tolerance <= .01:
        raise ValueError("Precio >= 0, 0 < max_volatility <= 5 y 0 < tolerance <= .01 requeridos.")
    if time == 0 or spot == 0:
        raise ValueError("La volatilidad implícita no está identificada con T=0 o S=0.")
    if dividends and option_type == "put":
        raise ValueError("IV de puts con dividendos discretos no soportada: el modelo liquidator puede tener vega negativa y raíces no únicas. Introduzca una IV explícita.")
    numerical = bool(dividends) or not _european_equivalent(option_type, style, rate, dividend_yield)
    cap = min(max_volatility, 3/math.sqrt(time)) if numerical else max_volatility
    def f(vol):
        return price_option(spot, strike, time, rate, vol, option_type, style, dividend_yield, dividends, steps)-price
    low = f(0.0)
    quote_tol = tolerance * max(1.0, price)
    if low > quote_tol:
        raise ValueError("La prima está por debajo de la cota de precio del modelo.")
    if abs(low) <= quote_tol:
        if style == "american":
            raise ValueError("IV no identificada: precio en la cota de ejercicio/volatilidad cero.")
        return 0.0
    # Grow the bracket: avoid starting a numerical PDE at a needlessly extreme
    # sigma, and reject a quote for which no finite root exists in the domain.
    high = min(.5, cap)
    while f(high) < 0 and high < cap:
        high = min(high * 2, cap)
    if f(high) < -quote_tol:
        raise ValueError("La prima no tiene una IV dentro del rango permitido del modelo.")
    root = brentq(f, 0.0, high, xtol=max(1e-10, tolerance), rtol=1e-10, maxiter=100)
    return float(root)
