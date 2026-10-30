# Fundamento financiero y criterios de validación

**Fecha de corte de la revisión: 30 de octubre de 2026.** Esta es una revisión dirigida de literatura académica, documentación de contratos y herramientas profesionales para una calculadora de opciones vanilla. No pretende ser una revisión exhaustiva de toda la literatura de derivados. El criterio de selección es que cada fuente cambie una decisión de modelización, una interpretación del resultado o una prueba de validación.

## 1. Qué puede calcularse y qué no puede deducirse

El valor de una opción antes del vencimiento depende del precio del subyacente, el tiempo restante, la volatilidad, los tipos, los dividendos y las condiciones del contrato. El resultado de una estrategia es la suma de sus patas, sus flujos y sus costes. Un gráfico de payoff a vencimiento elimina parte de esa información y resulta insuficiente para controlar una posición abierta. Black–Scholes y Merton proporcionan una valoración coherente bajo supuestos concretos; no proporcionan una predicción de la trayectoria futura de las cotizaciones [1, 2].

La aplicación debe distinguir cuatro cantidades. La **prima de entrada** es el precio histórico ejecutado y permanece fijo. La **marca actual** es una cotización introducida por el usuario, potencialmente con bid y ask. El **valor teórico** es el resultado del modelo con sus inputs. El **valor de escenario** es una revaloración condicional: cuánto valdría la posición si se cumplieran los supuestos seleccionados. Igualar estas cantidades por comodidad genera errores de P&L y una precisión engañosa.

Una marca midpoint no garantiza que se pueda cerrar la posición a ese precio. Cuando se introducen bid y ask, vender las patas largas al bid y recomprar las cortas al ask ofrece un escenario de liquidación por patas; incluso ese cálculo no reproduce necesariamente la ejecución de una orden de estructura completa. Deben conservarse las comisiones como un coste explícito. El tipo de descuento empleado para valorar la opción tampoco es automáticamente el coste de financiación que cobra el intermediario.

## 2. Valoración europea, americana y dividendos

Para opciones europeas con dividend yield continuo se utiliza Black–Scholes–Merton. El tiempo se expresa en años, y los tipos y la volatilidad son anuales. La convención de calendario y capitalización debe permanecer visible. ACT/365 es una elección de implementación, no una afirmación de que todos los mercados utilicen esa convención. Si solo se introducen fechas sin horas, no se está reproduciendo con precisión una opción 0DTE ni el fixing intradía de su contrato.

En este modelo, la paridad put–call es `C − P = S exp(−qT) − K exp(−rT)`. Es una identidad financiera que permite detectar fallos de signos, dividendos, descuento y tiempo [1, 2]. Una opción europea puede valer menos que el valor de ejercerla inmediatamente porque ese ejercicio no está permitido. Por tanto, imponer indiscriminadamente un suelo igual al intrínseco constituye un error.

En una opción americana, el titular puede ejercer antes del vencimiento. La valoración debe comparar en las fechas admisibles el ejercicio inmediato con el valor de continuación [3]. La americana vale al menos tanto como la europea equivalente y como su ejercicio inmediato, dentro de la precisión numérica. La igualdad entre call americana y europea sin dividendos requiere los supuestos habituales, incluidos tipos no negativos; no debe extenderse por defecto a tipos negativos.

Los dividendos de efectivo generan saltos en el precio ex-dividendo y alteran la frontera de ejercicio. No son equivalentes a distribuir el mismo importe como un yield continuo durante todo el intervalo. La aproximación de restar el valor actual de los dividendos al spot tampoco es un tratamiento exacto universal, especialmente para ejercicio americano alrededor de una fecha ex-dividendo. QuantLib distingue expresamente distintos modelos de dividendos y permite incorporar un calendario de pagos en el motor de diferencias finitas [6]. La investigación reciente continúa tratando esta dificultad: Itkin propone una alternativa semi-analítica con dividendos híbridos y frontera de ejercicio [15]. Su carácter reciente no justifica sustituir un método contrastado por un preprint sin validación independiente.

La convención concreta elegida aquí es *liquidator*: el spot pasa a `max(S − D, 0)` y el dividendo efectivo queda limitado a `min(D, S)`. Un dividendo en la fecha de vencimiento se aplica antes del payoff; una americana permite comparar con el ejercicio inmediatamente anterior. En los snapshots diarios de cartera, el spot introducido para una fecha ex-dividendo ya es ex-dividendo y ese evento no vuelve a aplicarse. Estas convenciones permiten un modelo definido, pero no sustituyen la revisión del contrato ni los detalles de una distribución corporativa real.

Un motor de diferencias finitas debe resolver la ecuación de valoración entre fechas de eventos, aplicar el salto correspondiente al dividendo y permitir el ejercicio donde corresponda. Los resultados dependen de la malla espacial y temporal, de las condiciones de frontera, de la interpolación y del tratamiento de la discontinuidad del payoff. La comparación entre mallas y con una implementación independiente es parte del método, no una mejora opcional. QuantLib publica tanto el motor como casos de prueba de americanas [6, 7].

El árbol Cox–Ross–Rubinstein constituye otra referencia útil [3]. Si se utiliza, su probabilidad neutral al riesgo debe permanecer dentro de `[0, 1]`. Recortarla para evitar un error numérico cambia la distribución del modelo. La respuesta correcta es refinar la malla, tratar el límite de volatilidad cero o rechazar el dominio no resuelto. Las mallas pares e impares pueden oscilar alrededor del límite; un número de pasos arbitrario no garantiza convergencia.

## 3. Volatilidad implícita y escenarios de volatilidad

La volatilidad implícita invierte una función de precio: necesita una cotización y un conjunto coherente de spot, tiempo, tipos, dividendos y estilo de ejercicio. Debe inferirse de una **marca actual**, no de una prima histórica de entrada emparejada con el spot actual. Las cotas de no arbitraje se comprueban antes de buscar una raíz. Fuera de ellas no existe una solución económicamente admisible para ese modelo. En los límites puede no existir una volatilidad finita o no resultar identificable con precisión.

Jäckel muestra que la estabilidad de esta inversión depende tanto del procedimiento de búsqueda como de evaluar con precisión el propio precio Black en moneyness y plazos extremos [4]. Un método con intervalo acotado, tolerancia de precio declarada y control de iteraciones resulta defendible para esta aplicación. Newton sin protección puede salir del dominio o fallar cuando vega es muy pequeña. No se debe presentar la última iteración como solución si la repricing residual no cumple la tolerancia.

El modelo liquidator introduce una salvedad adicional: para puts con dividendos discretos, el precio no tiene por qué crecer monótonamente con la volatilidad. El operador de salto puede destruir la convexidad del payoff respecto al spot previo al dividendo. Por ejemplo, si el único dividendo `D` se paga justo antes del vencimiento, el payoff de una put es la diferencia entre una put europea de strike `K + D` y otra de strike `D`; su vega es la diferencia de dos vegas. Por eso la inversión automática de IV para estas puts se rechaza, en vez de devolver una raíz arbitraria. Su valoración con IV explícita sí permanece definida. En americanas cuyo precio coincide con la región de ejercicio, también puede faltar identificación única de la IV.

Una volatilidad por pata y shocks manuales permiten análisis útiles. Sin embargo, mantener fija la IV de cada strike cuando cambia el spot es una convención de escenario —habitualmente denominada *sticky strike*— y no una ley de mercado. La evidencia sobre dinámica de la sonrisa no respalda una regla universal que funcione en todos los regímenes [14]. La estructura temporal también importa: las IV de dos vencimientos pueden moverse de forma distinta.

Una colección de IV manuales no equivale a una superficie calibrada libre de arbitraje. Gatheral y Jacquier desarrollan restricciones específicas para impedir arbitrajes estáticos en SVI [5]. Si no se ajusta y valida una superficie, la aplicación debe describir los shocks como hipótesis por pata. Añadir Heston, volatilidad local, SABR o una red neuronal sin datos de calibración, diagnóstico de ajuste y pruebas de estabilidad produciría complejidad sin una mejora demostrada.

## 4. Tiempo, calendars y liquidación

Una estrategia con varios vencimientos no tiene un único payoff terminal que pueda calcularse a partir de un solo precio futuro. Al vencimiento de la pata corta de un calendar, esa pata pasa a payoff y la larga conserva tiempo y volatilidad. Después, el resultado depende de cómo se liquidó la pata vencida y de las acciones o la caja que quedaron. El precio observado al final del horizonte no sustituye retrospectivamente al precio observado en el primer vencimiento.

Por ello, un escenario definido únicamente por spot y fecha debe limitarse al primer vencimiento de las patas abiertas mientras no exista un motor explícito de trayectorias, liquidación y flujos. Para ir más allá se necesitan precios en las fechas intermedias y una política de cierre, ejercicio, entrega y financiación. OIC documenta además que la asignación anticipada de una pata corta en calendars puede crear obligaciones de entrega antes de que venza la cobertura [10]. Una opción americana comprada no se ejerce automáticamente para cubrir una asignación en otra pata.

Los contratos no son intercambiables. Las opciones estándar sobre acciones estadounidenses suelen representar 100 acciones y tener ejercicio americano con entrega física; las operaciones corporativas pueden alterar el entregable [11]. SPX utiliza ejercicio europeo y liquidación monetaria, y sus series pueden liquidarse con referencias de apertura o cierre diferentes [12]. Un multiplicador configurable evita asumir que todos los contratos son de 100, pero no reproduce por sí solo entregables ajustados que incluyan varias acciones o efectivo.

## 5. Sensibilidades, riesgo y P&L

Las sensibilidades deben declarar su unidad y agregarse con cantidad firmada y multiplicador. Delta mide el cambio de valor por una unidad de spot. Vega suele mostrarse por un punto porcentual de IV: pasar de 20% a 21%, no multiplicar la volatilidad por 1,01 [9]. Rho debe indicar si corresponde a un punto porcentual o a un punto básico de tipo. Theta se presenta habitualmente por día calendario [8].

El theta diferencial y la diferencia exacta entre la valoración de hoy y la de mañana no coinciden necesariamente, sobre todo cerca del vencimiento o de un dividendo. La aplicación debe declarar cuál calcula. Un evento puede producir un salto que no debe interpretarse como una derivada suave. Las sensibilidades de una americana también pueden perder suavidad cerca de la frontera de ejercicio; una cifra con muchos decimales no elimina ese problema.

En esta implementación, el P&L mostrado descuenta tanto costes de entrada como costes de cierre introducidos y suma la caja registrada. Los costes de cierre son una estimación si todavía no se ha cerrado la posición. Los dividendos del calendario afectan a la valoración de opciones, pero los cobros o pagos de las acciones no se incorporan automáticamente a la caja: los flujos ya realizados se registran en la cartera y los futuros asumidos en el ajuste del escenario. Es un P&L condicional por precios y caja especificada, no un libro contable automático ni una rentabilidad total que adivine los flujos ausentes.

A vencimiento, el payoff tiene quiebres en los strikes: gamma no es una función ordinaria en esos puntos y delta ATM no es única. Los casos `T = 0` y `sigma = 0` requieren tratamiento específico. Convertir una singularidad en cero sin explicarla inventa una certeza inexistente. Las comparaciones con bump-and-reprice deben probar varios tamaños de perturbación para distinguir una sensibilidad estable de un artefacto numérico.

Una pérdida máxima global no se obtiene tomando el mínimo de los puntos visibles en una gráfica. Para opciones vanilla sobre el mismo subyacente y con vencimiento común, el payoff es lineal por tramos: deben evaluarse cero, los strikes y la pendiente de la cola cuando el spot aumenta indefinidamente. Una call vendida sin cobertura tiene pérdida ilimitada aunque el gráfico termine en `+30%`. Los extremos de una malla de escenarios deben llamarse exactamente eso, sin confundirse con cotas globales.

La pérdida máxima a vencimiento tampoco es el margen exigido ni la liquidez necesaria durante la vida de la posición. La financiación, la asignación y los movimientos de valoración pueden requerir caja antes de alcanzar el payoff terminal. Un cálculo de margen necesita reproducir reglas específicas del mercado e intermediario; no debe deducirse automáticamente de una gráfica de payoff.

Las probabilidades neutrales al riesgo inferidas de opciones incorporan compensaciones por riesgo; no son probabilidades reales de beneficio. Malz explica explícitamente esa diferencia y la necesidad de respetar restricciones de arbitraje para no obtener densidades negativas [13]. Tampoco debe llamarse a delta una probabilidad exacta de terminar dentro del dinero. Esta calculadora debe ofrecer escenarios condicionales sin convertirlos en previsiones estadísticas no estimadas.

## 6. Casos mínimos de validación independiente

Los controles se orientan a errores capaces de cambiar una decisión económica. No basta con comprobar que una función devuelve la misma fórmula que contiene el test.

| Control | Criterio |
| --- | --- |
| BSM de referencia | Con `S=K=100`, `T=1`, `r=0.05`, `q=0`, `sigma=0.20`: call `10.4505835722`, put `5.5735260223`. Con `q=0.02`: call `9.2270055082`, put `6.3300806275`. |
| Identidades europeas | Paridad put–call, homogeneidad al escalar spot y strike, monotonicidad y convexidad en spot en el dominio regular. |
| Americanas | Valor al menos igual al europeo y al intrínseco; casos de ejercicio anticipado; comparación con QuantLib y refinamiento de malla. |
| Dividendos discretos | Fechas antes, dentro y después del horizonte; salto ex-dividendo; call próxima a ejercicio; ausencia de doble conteo de yield y pagos. |
| IV | Roundtrip precio→IV→precio, cotas imposibles, vega muy pequeña, plazos extremos y ausencia de convergencia. |
| Contabilidad | Cambiar spot, IV o fecha conserva coste histórico. Patas largas/cortas idénticas cancelan exposición y conservan la diferencia de precios de entrada y costes. |
| Unidades | Cambiar multiplicador 100→10 reduce exposición diez veces. Vega 20%→21% corresponde a un punto. |
| Estructuras | Suma de patas equivalente a cartera para verticales, butterflies, condors, straddles, covered calls y calendars. |
| Calendars | En 30/90 días, el día 30 deja 60 días en la larga y cero en la corta. El día 31 requiere información adicional o bloqueo. |
| Colas | Call corta reconoce pérdida ilimitada; no se presenta el extremo del rango dibujado como riesgo máximo. |
| Errores de dominio | Fechas pasadas, NaN/infinitos, primas inválidas, inputs incoherentes, cantidades y multiplicadores fuera del dominio producen errores legibles. |

## Bibliografía y documentación primaria

1. Black, F. y Scholes, M. (1973). *The Pricing of Options and Corporate Liabilities*. Journal of Political Economy, 81(3), 637–654. [DOI: 10.1086/260062](https://doi.org/10.1086/260062).
2. Merton, R. C. (1973). *Theory of Rational Option Pricing*. Bell Journal of Economics and Management Science, 4(1), 141–183. [DOI: 10.2307/3003143](https://doi.org/10.2307/3003143). [Working paper de MIT, versión de 1971](https://dspace.mit.edu/entities/publication/6e05a2fa-478f-41e6-9e69-a06532002236).
3. Cox, J. C., Ross, S. A. y Rubinstein, M. (1979). *Option pricing: A simplified approach*. Journal of Financial Economics, 7(3), 229–263. [Artículo del editor](https://www.sciencedirect.com/science/article/pii/0304405X79900151). DOI: 10.1016/0304-405X(79)90015-1.
4. Jäckel, P. (2015). *Let's Be Rational*. Wilmott, 2015(75), 40–53. [Artículo del editor](https://onlinelibrary.wiley.com/doi/10.1002/wilm.10395). DOI: 10.1002/wilm.10395.
5. Gatheral, J. y Jacquier, A. (2014). *Arbitrage-free SVI volatility surfaces*. Quantitative Finance, 14(1), 59–71. [DOI: 10.1080/14697688.2013.819986](https://doi.org/10.1080/14697688.2013.819986).
6. QuantLib. *FdBlackScholesVanillaEngine*, código oficial: [interfaz](https://github.com/lballabio/QuantLib/blob/master/ql/pricingengines/vanilla/fdblackscholesvanillaengine.hpp) e [implementación](https://github.com/lballabio/QuantLib/blob/master/ql/pricingengines/vanilla/fdblackscholesvanillaengine.cpp). Los enlaces apuntan a la rama de desarrollo; una validación reproducible debe registrar la versión de QuantLib utilizada.
7. QuantLib. [Test suite de opciones americanas](https://github.com/lballabio/QuantLib/blob/master/test-suite/americanoption.cpp).
8. Options Industry Council. [Theta](https://www.optionseducation.org/advancedconcepts/theta).
9. Options Industry Council. [Vega](https://www.optionseducation.org/advancedconcepts/vega).
10. Options Industry Council. [Strategies FAQ: ejercicio/asignación y calendars](https://www.optionseducation.org/referencelibrary/faq/strategies).
11. Options Clearing Corporation. [Equity Options Product Specifications](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications).
12. Cboe. [SPX fact sheet y especificaciones](https://res-certification.cboe.com/resources/spx/spx-fact-sheet.pdf) y [SPX Weeklys](https://www.cboe.com/tradable_products/sp_500/spx_weekly_options/specifications).
13. Malz, A. M. (2014). *A Simple and Reliable Way to Compute Option-Based Risk-Neutral Distributions*. Federal Reserve Bank of New York, Staff Report 677. [Publicación y PDF](https://www.newyorkfed.org/research/staff_reports/sr677.html).
14. Ciliberti, S., Bouchaud, J.-P. y Potters, M. (2008). *Smile dynamics — a theory of the implied leverage effect*. [Trabajo de los autores](https://arxiv.org/abs/0809.3375).
15. Itkin, A. (2025; versión 2, 5 de enero de 2026). *Semi-analytical pricing of American options with hybrid dividends via integral equations and the GIT method*. [Preprint, arXiv:2510.18159](https://arxiv.org/abs/2510.18159). No se presenta como una implementación validada de esta aplicación.
16. CME Group. [QuikStrike: Pricing, Volatility & Strategy Tools](https://www.cmegroup.com/tools-information/quikstrike/pricing-volatility-strategy-tools.html). Referencia funcional profesional para distinguir valoración, escenarios y análisis de volatilidad.

