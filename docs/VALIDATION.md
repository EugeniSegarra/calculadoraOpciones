# Validación y auditoría adversarial · 1.0.0

Fecha: 30 de octubre de 2026. La validación es reproducible con los comandos indicados y se refiere al alcance descrito en la metodología. No constituye una prueba de ausencia universal de errores ni una certificación de todos los contratos o inputs posibles.

## Resultado del núcleo

**PASS del árbitro independiente para el núcleo numérico, la contabilidad y las restricciones de escenario.** No quedaron hallazgos bloqueantes conocidos tras corregir y volver a probar los casos descritos abajo. La revisión adversarial fue realizada por un agente separado de los autores del motor y de la interfaz; no es una auditoría externa de una firma ni una certificación regulatoria.

La ejecución completa local terminó con **87 tests OK**, sin omisiones cuando QuantLib está instalado, en aproximadamente 12 segundos. El número cuenta métodos de prueba; muchos contienen varios subcasos de parámetros, identidades y plantillas.

| Bloque | Tests | Evidencia |
|---|---:|---|
| Motor de precio | 23 | BSM, paridad, límites, CRR, cuadratura independiente, ejercicio americano, dividendos, griegas, IV |
| Árbitro adversarial | 29 | Casos diseñados para invalidar precios, sensibilidades, signos, marcas, importes y horizontes |
| Contabilidad y estructuras | 25 | Entradas históricas, multiplicador, costes, bid/ask, caja, calendars, plantillas, datos inválidos |
| Referencia independiente QuantLib | 3 grupos | Ocho configuraciones numéricas, griegas analíticas y bumps independientes de vega/rho |
| API HTTP real | 7 | Carga, cálculo, importación estricta y fronteras de acceso local |

Entorno local: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 y QuantLib 1.44. QuantLib se utiliza únicamente para validación, no para ejecutar la aplicación. El flujo de GitHub Actions instala el paquete y ejecuta la suite con Python 3.10, 3.12 y 3.13; el resultado de cada ejecución debe consultarse en Actions, sin confundir una configuración de CI con una ejecución ya terminada.

```bash
python -m pip install . -r requirements-validation.txt
python -m unittest discover -s tests -v
node --check optionslab/static/app.js
python -m optionslab demo --output /tmp/portfolio.json
python -m optionslab analyze /tmp/portfolio.json --spot 110 --vol-shift 0.05 --output /tmp/resultados.json
```

Si no se instala QuantLib, sus tres grupos aparecen expresamente como `skipped`; no debe comunicarse ese resultado como si el contraste independiente se hubiera ejecutado. Las pruebas HTTP necesitan poder abrir sockets exclusivamente locales. El paquete instalado también se verificó fuera del checkout: incluye HTML/CSS/JS y ejecuta `demo` y `analyze` sin depender del directorio fuente.

## Contraste numérico

La referencia QuantLib utiliza 1.600 pasos temporales, 3.200 puntos espaciales y la misma convención Spot de dividendos. OptionsLab usa sus 400 pasos predeterminados. Los inputs completos, resultados y errores están guardados en [benchmark_reference.json](benchmark_reference.json).

| Caso | OptionsLab por unidad | QuantLib por unidad | Error absoluto |
|---|---:|---:|---:|
| Put americana ATM, 1 año | 6,090202942 | 6,089949409 | 0,000253533 |
| Call americana con yield continuo | 7,256553323 | 7,256509329 | 0,000043994 |
| Call americana con tipo negativo | 7,207135332 | 7,207114536 | 0,000020796 |
| Put americana ITM | 20,089127955 | 20,088907125 | 0,000220830 |
| Call americana con dos dividendos | 38,913949728 | 38,914032289 | 0,000082561 |
| Put americana con dividendo discreto | 8,441619559 | 8,441400234 | 0,000219325 |
| Call europea con dividendo discreto | 7,773325330 | 7,773345528 | 0,000020198 |
| Put americana, 4 días e IV 1% | 0,025276834 | 0,025275322 | 0,000001512 |

El mayor error de precio observado en estos ocho casos fue 0,000254 por unidad aproximadamente; por un contrato de multiplicador 100 equivale a unos 0,0254 monetarios. **Este máximo observado no es una cota universal del motor.** La tolerancia de los tests de referencia es 0,001 por unidad, delta 0,0002, gamma `max(0,00001; 0,1%)` y theta 0,00002 por día. Las cantidades y multiplicadores amplifican el error de precio de la misma manera que amplifican el valor.

El benchmark analítico S=K=100, T=1, r=5%, q=0 y sigma=20% produce call 10,4505835722 y put 5,5735260223. Las comparaciones BSM con el motor analítico de QuantLib usan tolerancia 1e-10 en los casos elegidos. La theta local se contrasta mediante la ecuación de valoración con precio/delta/gamma independientes de QuantLib; su `theta()` por instantánea temporal puede representar un horizonte finito distinto, especialmente cerca de vencimiento.

## Hallazgos detectados y corregidos

La primera malla numérica tenía poca resolución para una put americana ATM con T=0,01 años e IV=1%: daba 0,0214948 frente a aproximadamente 0,0246397 del CRR independiente, un error cercano al 13%. Se adaptó la concentración de la malla a la volatilidad total y se añadió una regresión de convergencia.

En ese mismo régimen, un bump fijo de spot de 0,5 era demasiado grande para medir una derivada local. Generaba delta cercana a −0,50 y gamma de 2,09 frente a valores locales cercanos a −0,414 y 5,53. Se adaptaron las perturbaciones y se sustituyó la interpolación final lineal por una interpolación cúbica adecuada para obtener sensibilidades. También se corrigieron perturbaciones que salían del dominio de tipos, cancelación numérica en S=0 y griegas artificialmente suaves en IV cero.

El árbitro detectó cotizaciones antiguas incluidas en paneles de P&L actual. Ahora se conservan los inputs pero se excluye la marca/cierre afectados del agregado actual. La inversión de IV exige igualmente un snapshot contemporáneo. Otros tests impiden usar primas históricas como marcas, invertir el signo dos veces, omitir contratos en extremos de spreads o mostrar como finita la pérdida de una call vendida sin cobertura.

La revisión de interfaz detectó importaciones que descartaban campos no soportados antes de llegar a la validación estricta, respuestas asíncronas de IV que podían sobrescribir cambios del usuario y resultados anteriores visibles después de cambiar de cartera. Se corrigieron con validación del esquema original en el servidor, control de revisión de inputs, limpieza de resultados y avisos visibles de recálculo. El texto de límites globales se muestra junto a los importes y se conserva al exportar.

El gráfico temporal incorpora fecha elegida, ex-fechas y día anterior al evento; una malla de fechas exclusivamente equidistantes podía ocultar un salto relevante. La prueba correspondiente comprueba además que el punto de la fecha elegida coincide con el escenario cuando no se introduce caja adicional sin calendario.

## Interfaz real en navegador

**PASS en 13 recorridos de Playwright con Chromium 153**, contra el servidor HTTP real en loopback, con datos exclusivamente DEMO. Se verificaron la carga inicial, gráficos de precio y tiempo con teclado, shocks de spot/IV/tipos, calendar limitado al primer vencimiento, covered call, añadir/eliminar patas, IV desde marca, cambios durante una petición de IV, rechazo y corrección de bid/ask cruzados, descargas JSON/CSV, importación estricta y recálculo, escritorio y móvil.

La inspección encontró un desbordamiento horizontal real en móvil: el documento tenía 1.153 píxeles para una ventana de 390. Se corrigió el contexto de posicionamiento de una etiqueta accesible dentro de la tabla desplazable y se repitieron los recorridos. También se adaptaron el tamaño y el número de marcas de los ejes SVG al ancho móvil. El resultado final no desborda en escritorio 1.440 × 1.000 ni en móvil 390 × 844. Hubo cero excepciones JavaScript, cero violaciones CSP y cero errores inesperados; los dos HTTP 422 observados correspondían a entradas inválidas deliberadas.

Las capturas [escritorio](ui-preview.png) y [móvil](ui-mobile.png) proceden del navegador real después de las correcciones. No son diseños simulados. Para esta ejecución se utilizó un Chromium temporal distribuido mediante `@sparticuz/chromium`, porque el navegador conectado no podía acceder al entorno local y el CDN del instalador estándar no estaba disponible; no se añadió ese navegador como dependencia del producto. Safari y Firefox no fueron comprobados visualmente en esta sesión.

## Límites del dictamen

Las pruebas cubren escenarios representativos y regresiones de los defectos encontrados. Los modelos son flat-vol, con la convención de dividendos y ejercicio documentada, datos manuales y un subyacente/moneda. No se certifica una superficie de mercado, un sistema de ejecución, reglas de margen, contabilidad automática de asignaciones, fixing intradía ni entrega de contratos ajustados. Las entradas no soportadas deben rechazarse de forma visible; los datos ausentes o las sensibilidades indefinidas no se sustituyen por ceros.
