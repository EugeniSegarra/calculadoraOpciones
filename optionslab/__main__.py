"""CLI: python -m optionslab [serve|demo|analyze]."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .portfolio import analyze
from .server import serve
from .strategies import default_portfolio


def _write(value: dict, output: str | None) -> None:
    contents = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if output:
        Path(output).write_text(contents, encoding="utf-8")
    else:
        print(contents, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OptionsLab · posiciones, valoración y escenarios de opciones vanilla.")
    subparsers = parser.add_subparsers(dest="command")
    server = subparsers.add_parser("serve", help="Abrir interfaz local")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--no-browser", action="store_true")
    demo = subparsers.add_parser("demo", help="Generar cartera de ejemplo con fechas actuales y primas hipotéticas")
    demo.add_argument("--output")
    calculate = subparsers.add_parser("analyze", help="Valorar una cartera JSON; no descarga cotizaciones")
    calculate.add_argument("portfolio")
    calculate.add_argument("--date", help="Fecha escenario YYYY-MM-DD")
    calculate.add_argument("--spot", type=float)
    calculate.add_argument("--vol-shift", type=float, help="Cambio absoluto de IV en decimal: .05 = +5 pp")
    calculate.add_argument("--rate-shift", type=float, help="Cambio absoluto del tipo: .01 = +100 pb")
    calculate.add_argument("--cash-adjustment", type=float, help="Caja futura adicional en la fecha del escenario")
    calculate.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "serve"):
            serve(getattr(args, "port", 8765), not getattr(args, "no_browser", False))
        elif args.command == "demo":
            _write(default_portfolio(), args.output)
        elif args.command == "analyze":
            path = Path(args.portfolio)
            if path.stat().st_size > 512 * 1024:
                raise ValueError("Archivo demasiado grande; máximo 512 KiB.")
            data = json.loads(path.read_text(encoding="utf-8"))
            scenario = {name: getattr(args, name) for name in ("date", "spot", "vol_shift", "rate_shift", "cash_adjustment") if getattr(args, name) is not None}
            _write(analyze(data, scenario), args.output)
        return 0
    except (ValueError, OSError, ArithmeticError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
