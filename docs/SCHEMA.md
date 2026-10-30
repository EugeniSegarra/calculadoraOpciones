# Esquema de posiciones v1

Todas las cantidades monetarias pertenecen a la única divisa de la cartera. Las primas, strikes y spots se expresan por unidad de subyacente; `quantity × multiplier` determina la exposición. Los tipos y la volatilidad son decimales anuales, con capitalización continua para el tipo y el yield.

| Campo de cartera | Significado |
|---|---|
| `schema_version` | Siempre `1` |
| `name`, `underlying`, `currency` | Etiquetas y código de moneda de tres letras; todas las patas pertenecen al mismo subyacente |
| `valuation_date` | Fecha del snapshot `YYYY-MM-DD`, después del evento ex-dividendo de ese día |
| `spot` | Spot observado, no negativo |
| `rate` | Tipo continuo anual del modelo |
| `dividend_yield` | Yield continuo anual; debe ser cero si se introducen dividendos discretos |
| `cash_adjustment` | Caja neta ya registrada desde las entradas; positiva cobros, negativa pagos |
| `cash_dividends` | Lista de `{date, amount}` con ex-fechas futuras e importes por acción; fechas repetidas se suman |
| `legs` | Lista de entre 1 y 32 patas |

| Campo de pata | Significado |
|---|---|
| `id`, `label` | ID único y etiqueta visible |
| `kind` | `call`, `put` o `stock` |
| `quantity` | Positiva compra, negativa venta; contratos enteros en opciones y títulos en acciones |
| `multiplier` | Unidades por contrato; 100 por defecto en opciones, exactamente 1 en acciones |
| `entry_price` | Precio histórico por unidad, siempre no negativo; el signo está en quantity |
| `strike`, `expiry` | Strike positivo y vencimiento diario para opciones; en acciones no se utilizan |
| `volatility` | IV anual decimal por pata |
| `style` | `european` o `american` |
| `mark_price` | Marca actual por unidad; `null` significa desconocida |
| `bid`, `ask` | Cotizaciones por unidad; bid no puede superar ask |
| `quote_date` | Fecha de la marca/bid/ask; `null` declara que pertenece a fecha base. Si es distinta se excluye de los agregados actuales |
| `entry_fee`, `exit_fee` | Costes monetarios **totales de la pata**, no por contrato; positivos |

Un cero es un dato válido en primas/cotizaciones/costes. Un dato ausente se expresa como `null`, nunca como cero. Si no hay marca pero sí bid y ask, el midpoint sirve como marca, sin garantía de ejecución. El cierre de una posición larga utiliza bid y el de una corta ask. El spot actual sirve como marca de las acciones; para un cierre al bid/ask también se necesita su cotización del lado correspondiente.

## Escenarios y salida

`analyze(portfolio, scenario)` admite `date`, `spot`, `vol_shift`, `rate_shift`, `price_min`, `price_max`, `points` y `cash_adjustment`. Los cambios de IV y tipo son absolutos en decimal, no porcentajes relativos. La caja adicional se incorpora solo al escenario, no retrospectivamente al snapshot ni al gráfico temporal. El horizonte no puede superar el primer vencimiento.

La salida contiene `summary`, `legs`, `scenario`, `curve`, `time_evolution`, `risk`, `warnings` y `meta`. Los números indefinidos o no disponibles son `null`; no se emiten NaN ni infinitos JSON. Los límites ilimitados se indican con `profit_unbounded`/`loss_unbounded`. `maximum_profit` y `maximum_loss` son magnitudes no negativas; los puntos de equilibrio también pueden incluir intervalos completos (`zero_intervals`, extremo superior null significa infinito). Los resultados por pata excluyen la caja común; el agregado la añade una sola vez.

`POST /api/validate` recibe `{portfolio}` y devuelve el esquema normalizado sin valorar. La importación usa esta validación antes de sustituir la cartera. Los campos desconocidos se rechazan, evitando que un archivo con términos no soportados parezca una posición vanilla válida.

## Límites de entrada

La UI admite hasta diez años, IV de 0% a 300%, tipo de −50% a 100% y yield de 0% a 100%; el dominio numérico puede ser más estrecho para combinaciones extremas (véase metodología). Hay hasta 40 dividendos y 201 puntos regulares por curva, además de los strikes y spots que se insertan para representar quiebros y escenarios exactos. Los importes deben ser finitos. Cantidades nulas se eliminan retirando la pata; no se interpretan como compras o ventas.

No se aceptan campos por pata de otro subyacente/divisa, ni entregables no lineales, opciones sobre futuros, barreras o condiciones de ejercicio distintas a los dos estilos soportados. La etiqueta es informativa; no consulta ni verifica un contrato en el mercado.
