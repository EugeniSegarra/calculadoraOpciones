# Historial de cambios

## 1.0.0 · 30 de octubre de 2026

El script de payoff se sustituye por un paquete Python con interfaz web local, API y CLI. La ruta original sigue funcionando como lanzador. Las posiciones se construyen con un único motor de patas, con modelos europeos y americanos, dividendos discretos, valoración temporal, griegas, marcas, bid/ask, costes, caja y persistencia JSON/CSV.

### Defectos comprobados del original

- Las opciones vendidas invertían el payoff y el prompt pedía además `position=-1`, provocando doble inversión de signo.
- Los spreads multiplicaban por la cantidad solo en el tramo central y omitían el tamaño en los extremos.
- El call spread vendido devolvía una pérdida con signo positivo por encima del strike superior.
- El menú ofrecía straddles/strangles sin lógica de inputs ni cálculo implementados.
- El rango del gráfico consideraba `strike1` y omitía el segundo strike.
- No existían vencimientos, valor temporal, IV, tipos, dividendos, ejercicio americano ni multiplicador contractual.

### Decisiones de diseño

Cantidad firmada y precios siempre positivos; prima histórica inmutable; marcas/modelo/cierre separados; datos ausentes como null; IV inferida solo de cotización contemporánea; horizonte limitado al primer vencimiento; extremos globales de payoff fuera de la ventana del gráfico; supuestos y limitaciones visibles en pantalla y exportaciones. Los detalles y los fallos detectados/corregidos durante la auditoría constan en `docs/VALIDATION.md`.
