# Metodología de cálculo y decisiones explícitas

## Arquitectura

`pricing.py` valora un contrato por unidad de subyacente. `portfolio.py` aplica cantidades con signo, multiplicadores, costes y caja, valida fechas y construye escenarios. `strategies.py` únicamente genera patas editables; no tiene fórmulas financieras independientes. La interfaz web usa esos mismos métodos por una API local. El lanzador original se conserva, pero se han retirado sus fórmulas de payoff y su ejecución interactiva al importar.

Esta separación evita que un spread se calcule de una manera al construirlo como plantilla y de otra al introducir sus dos opciones por separado. También permite probar la matemática sin abrir un navegador y comprobar la contabilidad sin depender de una representación gráfica.

## Modelo de precio

Entre eventos se supone una difusión lognormal neutral al riesgo con volatilidad, tipo y yield constantes. Black–Scholes–Merton se utiliza analíticamente para europeas sin dividendos discretos. La call americana sin dividendos y con tipo no negativo comparte esa valoración dentro de los supuestos del modelo. Con tipos negativos no se utiliza ese atajo.

Los restantes casos se resuelven mediante diferencias finitas sobre una malla espacial no uniforme: Crank–Nicolson con amortiguación de Rannacher cerca de discontinuidades, coeficientes monotónicos en el régimen en que la aproximación central no los garantiza, y resolución de la condición de ejercicio americano mediante iteración de políticas. La malla se adapta a la varianza total para resolver contratos muy próximos al vencimiento y de volatilidad baja. Los controles de no convergencia generan errores; no se publica una última iteración no validada.

Los dividendos discretos son eventos de salto `S+ = max(S− − D, 0)`. Esto corresponde a la convención *liquidator*, donde el dividendo efectivo es `min(D,S−)`. Su interpretación importa en escenarios extremos: no se promete que una compañía pague un dividendo superior a su valor. La expectativa de ese pago deja de ser exactamente el importe nominal, por lo que la paridad simple con PV de dividendos fijos no es una identidad universal de este modelo. Las opciones americanas pueden ejercerse inmediatamente antes del evento; las europeas reciben el payoff sobre el spot posterior si evento y vencimiento coinciden.

En IV cero se evalúa la trayectoria determinista y, para americanas, el mejor ejercicio admisible, incluidos tipos negativos y puntos críticos interiores. En vencimiento se aplica directamente el payoff. El spot cero se trata como frontera absorbente. No se añade un suelo de intrínseco a europeas que no pueden ejercerse inmediatamente.

## Precisión, sensibilidades e inversión de IV

Las europeas regulares tienen griegas analíticas. En casos numéricos se utilizan perturbaciones y revaloración con pasos adaptados a la escala del problema. Los cambios de spot comparten una resolución numérica para evitar derivar entre mallas incompatibles. La aproximación debe interpretarse con tolerancia económica: un error por unidad se multiplica por contratos y multiplicador. Refinar `steps` desde Python permite estudiar convergencia; el valor por defecto es 400 y el parámetro acepta 50–2000.

Theta representa una derivada local por día calendario. En el motor numérico se obtiene de la ecuación de valoración usando precio, delta y gamma, y vale cero en la región de ejercicio inmediato. Equivale al paso local del calendario a spot fijo, sin cruzar un salto de dividendo; el valor exacto de un escenario al día siguiente es una revaloración distinta. Las sensibilidades en puntos no suaves no se inventan: la API puede devolver `None`, que la interfaz representa como no disponible.

La IV utiliza una búsqueda con intervalo y control de cotas, no Newton sin protección. La prima debe corresponder al mismo snapshot que el spot y la fecha. La raíz describe el modelo elegido y la malla utilizada, no una precisión real de cotización mejor que el bid/ask. Los casos no identificables se rechazan. Se bloquea la inversión de puts con pagos discretos porque, bajo responsabilidad limitada, la relación precio/volatilidad no tiene garantizada la monotonía necesaria para comunicar una sola raíz.

El motor numérico exige `sigma × sqrt(T) <= 3` y `max(|r|, |q|) × T <= 3`; las combinaciones fuera de este alcance se rechazan. La validación cubre un dominio práctico con casos de estrés y límites explícitos; no certifica todos los posibles valores del dominio formal. La amplitud de un parámetro admitido no implica idéntica precisión relativa en una opción de precio diminuto.

## Contabilidad de posición

Los precios de entrada permanecen fijos al variar inputs de mercado. El coste de entrada firmado es la suma de cantidad × multiplicador × precio de entrada más comisiones de entrada. Una posición corta tiene valor negativo y un crédito inicial; la multiplicación por cantidad con signo ocurre una sola vez. El P&L resta además los costes de salida introducidos y añade la caja registrada.

La marca total se calcula solo si todas las opciones tienen marca contemporánea o bid/ask contemporáneos suficientes para formar midpoint. Si una falta, no se construye un agregado híbrido con precios del modelo. La estimación de cierre exige bid para cada largo y ask para cada corto, incluidas acciones. La marca individual de opciones y el cierre se desactivan si la fecha de cotización es distinta de la base; en acciones el spot actual sigue sirviendo como marca, pero se excluye su bid/ask obsoleto. Sin fecha explícita el dato se interpreta como declarado contemporáneo por el usuario.

Los dividendos sobre acciones no se añaden automáticamente: el motor de precio de opciones y un ledger de caja son cosas distintas. La caja pasada y la caja futura deben registrarse expresamente. Esto evita asignar a todos los puntos de una curva un dividendo realizado que depende de eventos, posición viva y, en la convención liquidator, de la trayectoria. La interfaz avisa cuando hay acciones y dividendos/yield.

## Escenarios y límites de payoff

El tiempo puede avanzar hasta el primer vencimiento inclusive. En ese instante las opciones que vencen valen su payoff y las restantes conservan el tiempo residual. Después se necesita un estado nuevo con la liquidación/asignación observada y las acciones/caja resultantes. No se rellena retrospectivamente la pata vencida usando el spot final de otro día.

El gráfico temporal son cortes a spot fijo, con IV por pata y shocks constantes. Incluye la fecha seleccionada, ex-fechas y el día anterior a cada ex-fecha dentro del horizonte. No constituye una trayectoria simulada ni una predicción. La caja adicional del escenario se excluye de esos cortes porque carece de calendario. Las primas históricas, costes y caja base sí permanecen constantes.

Para opciones de vencimiento común, los extremos del payoff se calculan analíticamente por tramos: S=0, strikes y signo de la pendiente de cola. Los intervalos completos con P&L cero se conservan. Los límites son magnitudes de beneficio/pérdida y excluyen cualquier caja futura no registrada. En americanas se condicionan a ausencia de ejercicio/asignación anteriores. Para varios vencimientos no se presentan límites terminales artificiales a partir del gráfico.

## Alcance operativo

Una cartera tiene un subyacente y una moneda. No hay conversión FX implícita. Las fechas son diarias ACT/365; no se pretende resolver liquidaciones AM/PM, intradía ni una especificación de bolsa que no se haya introducido. El multiplicador es configurable, pero un entregable corporativo compuesto por acciones de varios emisores y efectivo no se reduce a cambiar ese número.

La aplicación es un motor local de escenarios, sin órdenes, feeds ni garantía de ejecución a midpoint. La ausencia de una superficie calibrada obliga a mostrar la hipótesis de IV por strike; no se incorporan modelos adicionales sin datos de calibración ni se presenta una probabilidad real de beneficio a partir de precios neutrales al riesgo.

La elección de iteración de políticas para el problema de ejercicio se apoya específicamente en Reisinger y Witte (2012), [On the Use of Policy Iteration as an Easy Way of Pricing American Options](https://epubs.siam.org/doi/10.1137/110823328), SIAM Journal on Financial Mathematics 3(1), 459–478. No se describe como un método de penalización ni se confunde el algoritmo con una nueva hipótesis económica.
