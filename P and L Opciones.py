"""Compatibilidad de arranque con el nombre original del repositorio.

La implementación vive en optionslab. Importar este archivo no pide datos,
no abre ventanas ni ejecuta cálculos. Para usar la API, importa optionslab.
"""
from optionslab.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
