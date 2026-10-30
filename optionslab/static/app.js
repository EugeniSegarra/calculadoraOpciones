"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const state = { portfolio: null, result: null, resultPortfolio: null, resultScenario: null, tab: "price", revision: 0, positionGeneration: 0, busy: false };
  let legControls = [];
  let dividendControls = [];
  let nextId = 1;

  function node(tag, attrs = {}, children = []) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null) continue;
      if (key === "class") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (key === "value") element.value = value;
      else if (key === "disabled" || key === "required") element[key] = Boolean(value);
      else element.setAttribute(key, value);
    }
    for (const child of children) element.append(child);
    return element;
  }
  function svg(tag, attrs = {}, text) {
    const element = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function numeric(value, digits = 2) {
    return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value) : "—";
  }
  function compact(value) {
    return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1, notation: Math.abs(value) >= 10000 ? "compact" : "standard" }).format(value);
  }
  function money(value) {
    const currency = state.resultPortfolio ? state.resultPortfolio.currency : state.portfolio?.currency || "EUR";
    return typeof value === "number" && Number.isFinite(value) ? `${numeric(value)} ${currency}` : "—";
  }
  const signClass = (value) => typeof value !== "number" ? "muted" : value > 1e-8 ? "positive" : value < -1e-8 ? "negative" : "";
  const clone = (value) => JSON.parse(JSON.stringify(value));
  function dateNumber(value) { return Date.parse(`${value}T00:00:00Z`); }
  function addDays(value, days) { return new Date(dateNumber(value) + days * DAY).toISOString().slice(0, 10); }
  function dateLabel(value) {
    const date = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(date.getTime()) ? String(value || "—") : new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(date);
  }
  function error(message) { $("error-banner").textContent = message; $("error-banner").hidden = false; }
  function clearError() { $("error-banner").hidden = true; $("error-banner").textContent = ""; }
  function info(message) { $("status-message").textContent = message; $("status-message").hidden = !message; }
  function markDirty() {
    state.revision += 1;
    $("dirty-indicator").textContent = state.result ? "Cambios pendientes de recalcular" : "Pendiente de calcular";
    $("dirty-indicator").classList.remove("clean");
    if (state.result) $("results-stale").hidden = false;
  }
  function setBusy(value, label = "Calculando…") {
    state.busy = value;
    document.querySelectorAll(".analyze-button").forEach((button) => { button.disabled = value; button.textContent = value ? label : "Calcular posición"; });
    $("template-button").disabled = value;
    $("import-button").disabled = value;
    $("results").setAttribute("aria-busy", value ? "true" : "false");
  }
  async function api(url, body) {
    const response = await fetch(url, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
    const text = await response.text();
    let value;
    try { value = JSON.parse(text); } catch (_) { throw new Error(`El servidor no devolvió una respuesta válida (${response.status}).`); }
    if (!response.ok || value.error) {
      const detail = value.error || value.message || `Error HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return value;
  }
  function inputControl(field, value, attrs = {}) {
    return node("input", { type: "number", step: "any", value: value ?? "", "data-field": field, ...attrs });
  }
  function selectControl(field, value, options, attrs = {}) {
    const select = node("select", { "data-field": field, ...attrs });
    options.forEach(([key, label]) => select.append(node("option", { value: key, text: label })));
    select.value = value;
    return select;
  }
  function advancedField(label, control) { return node("label", { class: "advanced-field" }, [node("span", { text: label }), control]); }

  function renderLegs() {
    const body = $("legs-body");
    body.replaceChildren();
    legControls = [];
    for (const [index, leg] of state.portfolio.legs.entries()) {
      const stock = leg.kind === "stock";
      const controls = {
        label: inputControl("label", leg.label || `Pata ${index + 1}`, { type: "text", maxlength: 100, "aria-label": `Nombre de la pata ${index + 1}`, required: true }),
        kind: selectControl("kind", leg.kind, [["call", "Call"], ["put", "Put"], ["stock", "Acciones"]], { "aria-label": `Tipo de la pata ${index + 1}` }),
        quantity: inputControl("quantity", leg.quantity, { step: stock ? "any" : "1", "aria-label": `Cantidad firmada de la pata ${index + 1}`, required: true, class: `quantity-input ${leg.quantity < 0 ? "negative-quantity" : "positive-quantity"}` }),
        multiplier: inputControl("multiplier", stock ? 1 : leg.multiplier, { min: "0.000001", "aria-label": `Multiplicador de la pata ${index + 1}`, required: true, disabled: stock }),
        strike: inputControl("strike", stock ? "" : leg.strike, { min: "0.00000001", "aria-label": `Strike de la pata ${index + 1}`, required: !stock, disabled: stock }),
        expiry: inputControl("expiry", stock ? "" : leg.expiry, { type: "date", min: state.portfolio.valuation_date, "aria-label": `Vencimiento de la pata ${index + 1}`, required: !stock, disabled: stock }),
        volatility: inputControl("volatility", stock ? "" : roundPercent(leg.volatility), { min: "0", max: "300", "aria-label": `Volatilidad en porcentaje de la pata ${index + 1}`, required: !stock, disabled: stock }),
        entry_price: inputControl("entry_price", leg.entry_price, { min: "0", "aria-label": `Prima o precio de entrada de la pata ${index + 1}`, required: true }),
        mark_price: inputControl("mark_price", stock ? "" : leg.mark_price, { min: "0", placeholder: stock ? "Spot" : "Sin marca", disabled: stock, "aria-label": `Marca actual de la pata ${index + 1}` }),
        style: selectControl("style", leg.style || "european", [["european", "Europea"], ["american", "Americana"]], { disabled: stock, "aria-label": `Estilo de ejercicio de la pata ${index + 1}` }),
        bid: inputControl("bid", leg.bid, { min: "0", placeholder: "—", "aria-label": `Bid de la pata ${index + 1}` }),
        ask: inputControl("ask", leg.ask, { min: "0", placeholder: "—", "aria-label": `Ask de la pata ${index + 1}` }),
        quote_date: inputControl("quote_date", leg.quote_date, { type: "date", "aria-label": `Fecha de cotización de la pata ${index + 1}` }),
        entry_fee: inputControl("entry_fee", leg.entry_fee ?? 0, { min: "0", required: true, "aria-label": `Coste total de entrada de la pata ${index + 1}` }),
        exit_fee: inputControl("exit_fee", leg.exit_fee ?? 0, { min: "0", required: true, "aria-label": `Coste total de cierre de la pata ${index + 1}` }),
      };
      const record = { id: leg.id, controls };
      legControls.push(record);
      const row = node("tr", { class: "leg-main" });
      ["label", "kind", "quantity", "multiplier", "strike", "expiry", "volatility", "entry_price", "mark_price"].forEach((field) => {
        const cls = field === "label" ? "label-cell" : field === "kind" ? "kind-cell" : field === "expiry" ? "date-cell" : "number-cell";
        row.append(node("td", { class: cls }, [controls[field]]));
      });
      const remove = node("button", { type: "button", class: "icon-button", text: "×", title: "Eliminar pata", "aria-label": `Eliminar pata ${index + 1}` });
      remove.addEventListener("click", () => {
        collectPortfolio();
        state.portfolio.legs = state.portfolio.legs.filter((item) => item.id !== leg.id);
        renderLegs(); adjustHorizon(); markDirty();
      });
      row.append(node("td", {}, [remove]));
      const infer = node("button", { type: "button", class: "button secondary", text: "Inferir IV de marca", disabled: stock, title: "Ajustar IV a una marca actual o al punto medio bid/ask. La prima histórica no se usa." });
      infer.addEventListener("click", async () => {
        if (state.busy || !$("workspace").reportValidity()) return;
        clearError(); collectPortfolio();
        const requestedRevision = state.revision;
        infer.disabled = true; infer.textContent = "Resolviendo IV…";
        try {
          const value = await api("/api/iv", { portfolio: state.portfolio, leg_id: leg.id });
          const target = state.portfolio.legs.find((item) => item.id === leg.id);
          if (requestedRevision !== state.revision || !target) { info("Los datos cambiaron durante el cálculo de IV. Se ha descartado la respuesta; vuelve a inferir la IV con los datos actuales."); return; }
          if (target) { target.volatility = value.volatility; renderLegs(); markDirty(); info("IV ajustada a la cotización actual de esa pata. Recalcula la posición para actualizar sus riesgos."); }
        } catch (exception) { error(exception.message); }
        finally { infer.disabled = false; infer.textContent = "Inferir IV de marca"; }
      });
      const advanced = node("div", { class: "advanced-row" }, [
        advancedField("Ejercicio", controls.style), node("span", { class: "details-separator", "aria-hidden": "true" }),
        advancedField("Bid", controls.bid), advancedField("Ask", controls.ask), advancedField("Fecha marca", controls.quote_date),
        node("span", { class: "details-separator", "aria-hidden": "true" }),
        advancedField("Coste entrada total", controls.entry_fee), advancedField("Coste cierre total", controls.exit_fee), infer,
      ]);
      body.append(row, node("tr", { class: "leg-details" }, [node("td", { colspan: 10 }, [advanced])]));
      controls.kind.addEventListener("change", () => {
        collectPortfolio();
        const target = state.portfolio.legs.find((item) => item.id === leg.id);
        if (target.kind === "stock") { target.multiplier = 1; target.entry_price = state.portfolio.spot; target.mark_price = null; }
        else {
          target.strike = target.strike || state.portfolio.spot || 100;
          target.expiry = target.expiry || addDays(state.portfolio.valuation_date, 90);
          target.volatility = Number.isFinite(target.volatility) && target.volatility > 0 ? target.volatility : 0.25;
          target.style = target.style || "european";
          if (stock) { target.multiplier = 100; target.entry_price = 0; }
        }
        renderLegs(); adjustHorizon(); markDirty();
      });
      controls.expiry.addEventListener("change", () => { collectPortfolio(); adjustHorizon(); });
      controls.quantity.addEventListener("input", () => { controls.quantity.classList.toggle("negative-quantity", Number(controls.quantity.value) < 0); controls.quantity.classList.toggle("positive-quantity", Number(controls.quantity.value) >= 0); });
    }
    $("leg-count").textContent = String(state.portfolio.legs.length);
    $("add-leg").disabled = state.portfolio.legs.length >= 32;
    if (!state.portfolio.legs.length) body.append(node("tr", {}, [node("td", { colspan: 10, class: "muted", text: "Añade una pata o carga una estructura para comenzar." })]));
  }

  function roundPercent(value) { return typeof value === "number" ? Number((value * 100).toPrecision(12)) : ""; }
  function renderDividends() {
    const container = $("dividend-rows");
    container.replaceChildren(); dividendControls = [];
    for (const [index, dividend] of (state.portfolio.cash_dividends || []).entries()) {
      const date = node("input", { type: "date", value: dividend.date, required: true });
      const amount = node("input", { type: "number", step: "any", min: "0.00000001", value: dividend.amount, required: true });
      const remove = node("button", { type: "button", class: "icon-button", text: "×", "aria-label": `Eliminar dividendo ${index + 1}` });
      remove.addEventListener("click", () => { collectPortfolio(); state.portfolio.cash_dividends.splice(index, 1); renderDividends(); markDirty(); });
      dividendControls.push({ date, amount });
      container.append(node("div", { class: "dividend-row" }, [node("label", { class: "field" }, [node("span", { text: "Fecha ex-dividendo" }), date]), node("label", { class: "field" }, [node("span", { text: "Efectivo por acción" }), amount]), remove]));
    }
    if (!dividendControls.length) container.append(node("p", { class: "empty-dividends", text: "Sin dividendos discretos registrados." }));
  }
  function collectPortfolio() {
    if (!state.portfolio) return null;
    const portfolio = state.portfolio;
    for (const [field, id] of [["name", "portfolio-name"], ["underlying", "underlying"], ["currency", "currency"], ["valuation_date", "valuation-date"]]) portfolio[field] = $(id).value.trim();
    portfolio.currency = portfolio.currency.toUpperCase();
    portfolio.spot = Number($("spot").value); portfolio.rate = Number($("rate").value) / 100; portfolio.dividend_yield = Number($("dividend-yield").value) / 100;
    portfolio.cash_adjustment = Number($("cash-adjustment").value);
    portfolio.cash_dividends = dividendControls.map(({ date, amount }) => ({ date: date.value, amount: Number(amount.value) }));
    portfolio.legs = legControls.map(({ id, controls: c }) => {
      const leg = { id, label: c.label.value.trim(), kind: c.kind.value, quantity: Number(c.quantity.value), multiplier: c.kind.value === "stock" ? 1 : Number(c.multiplier.value), entry_price: Number(c.entry_price.value), mark_price: c.kind.value === "stock" || c.mark_price.value.trim() === "" ? null : Number(c.mark_price.value), bid: c.bid.value.trim() === "" ? null : Number(c.bid.value), ask: c.ask.value.trim() === "" ? null : Number(c.ask.value), quote_date: c.quote_date.value || null, entry_fee: Number(c.entry_fee.value), exit_fee: Number(c.exit_fee.value) };
      if (leg.kind !== "stock") Object.assign(leg, { strike: Number(c.strike.value), expiry: c.expiry.value, volatility: Number(c.volatility.value) / 100, style: c.style.value });
      return leg;
    });
    return portfolio;
  }
  function collectScenario() {
    return { date: $("scenario-date").value, spot: Number($("scenario-spot").value), vol_shift: Number($("vol-shift").value) / 100, rate_shift: Number($("rate-shift").value) / 10000, price_min: Number($("price-min").value), price_max: Number($("price-max").value), points: 81, cash_adjustment: Number($("scenario-cash").value) };
  }
  function firstExpiry() {
    const expiries = state.portfolio.legs.filter((leg) => leg.kind !== "stock" && leg.expiry).map((leg) => leg.expiry).sort();
    return expiries[0] || null;
  }
  function adjustHorizon() {
    if (!state.portfolio || !state.portfolio.valuation_date || !Number.isFinite(dateNumber(state.portfolio.valuation_date))) return;
    const base = state.portfolio.valuation_date;
    const first = firstExpiry();
    const max = first || addDays(base, 365);
    const days = Math.max(0, Math.round((dateNumber(max) - dateNumber(base)) / DAY));
    $("scenario-date").min = base; $("scenario-date").max = max;
    if (!$("scenario-date").value || $("scenario-date").value > max) $("scenario-date").value = max;
    if ($("scenario-date").value < base) $("scenario-date").value = base;
    $("days-slider").max = String(days);
    $("horizon-limit").textContent = first ? `Primer vencimiento: ${dateLabel(first)}` : "Sin opciones: ventana de un año";
    syncSlider();
    for (const { controls } of legControls) controls.expiry.min = base;
  }
  function syncSlider() {
    const days = Math.round((dateNumber($("scenario-date").value) - dateNumber($("valuation-date").value)) / DAY);
    if (Number.isFinite(days)) { $("days-slider").value = String(Math.max(0, days)); $("days-label").textContent = String(Math.max(0, days)); }
  }
  function setPortfolio(portfolio, resetScenario = true) {
    state.positionGeneration += 1;
    state.result = null; state.resultPortfolio = null; state.resultScenario = null;
    $("results").hidden = true;
    state.portfolio = clone(portfolio);
    for (const [field, id] of [["name", "portfolio-name"], ["underlying", "underlying"], ["currency", "currency"], ["valuation_date", "valuation-date"], ["spot", "spot"], ["cash_adjustment", "cash-adjustment"]]) $(id).value = portfolio[field] ?? (field === "cash_adjustment" ? 0 : "");
    $("rate").value = roundPercent(portfolio.rate); $("dividend-yield").value = roundPercent(portfolio.dividend_yield);
    renderLegs(); renderDividends();
    if (resetScenario) {
      $("scenario-date").value = addDays(portfolio.valuation_date, 30);
      $("scenario-spot").value = portfolio.spot;
      $("price-min").value = Number((portfolio.spot * 0.65).toPrecision(10));
      $("price-max").value = Number((Math.max(portfolio.spot * 1.35, 1)).toPrecision(10));
      $("vol-shift").value = 0; $("rate-shift").value = 0; $("scenario-cash").value = 0;
    }
    adjustHorizon(); markDirty();
  }

  async function analyze() {
    if (state.busy || !$("workspace").reportValidity()) return;
    clearError(); collectPortfolio(); adjustHorizon();
    if (!state.portfolio.legs.length) { error("La posición necesita al menos una pata."); return; }
    const portfolio = clone(state.portfolio); const scenario = collectScenario(); const revision = state.revision; const generation = state.positionGeneration;
    setBusy(true);
    try {
      const result = await api("/api/analyze", { portfolio, scenario });
      if (generation !== state.positionGeneration) return;
      state.result = result; state.resultPortfolio = portfolio; state.resultScenario = scenario;
      renderResults();
      $("results-stale").hidden = state.revision === revision;
      if (state.revision === revision) { $("dirty-indicator").textContent = "Resultados actualizados"; $("dirty-indicator").classList.add("clean"); }
      info("");
    } catch (exception) { error(exception.message); }
    finally { setBusy(false); }
  }
  function metric(label, value, description, highlighted = false) {
    return node("article", { class: `summary-card${highlighted ? " highlight" : ""}` }, [node("p", { class: "metric-label", text: label }), node("p", { class: `metric-number ${signClass(value)}`, text: money(value) }), node("p", { class: "metric-description", text: description })]);
  }
  function renderResults() {
    const result = state.result; const s = result.summary || {}; const scenario = result.scenario || {};
    $("results").hidden = false;
    $("results-asof").textContent = `${state.resultPortfolio.name} · ${state.resultPortfolio.underlying} · Base ${dateLabel(state.resultPortfolio.valuation_date)} · ${state.resultPortfolio.currency}`;
    $("summary-cards").replaceChildren(
      metric("P&L según modelo · hoy", s.model_pnl, `Valor ${money(s.model_value)} · desembolso ${money(s.entry_cash)} · cierre estimado y caja registrada incluidos`),
      metric("P&L observado · hoy", s.market_pnl, s.market_pnl == null ? "No disponible: faltan marcas actuales válidas para completar la posición." : `Valor observado ${money(s.market_value)} · neto de entrada y cierre estimado; caja registrada incluida`),
      metric("P&L del escenario", scenario.pnl, `${dateLabel(scenario.date)} · spot ${numeric(scenario.spot)} · cambio vs. modelo hoy ${money(scenario.change_from_model)} · costes y caja incorporados`, true),
      metric("P&L de liquidación · hoy", s.liquidation_pnl, s.liquidation_pnl == null ? "No disponible: hacen falta precios de salida bid/ask para las patas." : "Largos a bid y cortos a ask · costes de cierre incluidos"),
    );
    renderGreeks(); renderRisk(); renderWarnings(); renderLegResults(); renderChart();
    $("version").textContent = result.meta?.version ? `v${result.meta.version}` : "";
  }
  function renderGreeks() {
    const table = node("table", { class: "greek-table" });
    table.append(node("thead", {}, [node("tr", {}, [node("th", { scope: "col", text: "Sensibilidad" }), node("th", { scope: "col", text: "Hoy" }), node("th", { scope: "col", text: "Escenario" })])]));
    const body = node("tbody");
    const labels = [["delta", "Delta", "unidades subyacente", 2], ["gamma", "Gamma", "por unidad de spot", 4], ["theta", "Theta", "divisa / día natural", 2], ["vega", "Vega", "divisa / +1 pp de IV", 2], ["rho", "Rho", "divisa / +1 pp de tipo", 2]];
    labels.forEach(([key, label, unit, digits]) => body.append(node("tr", {}, [node("td", {}, [node("span", { text: label }), node("span", { class: "greek-unit", text: unit })]), node("td", { text: numeric(state.result.summary?.greeks?.[key], digits) }), node("td", { text: numeric(state.result.scenario?.greeks?.[key], digits) })])));
    table.append(body);
    $("greeks-table").replaceChildren(table, node("p", { class: "help", text: `Exposición delta × spot hoy: ${money(state.result.summary?.delta_notional)}` }));
  }
  function renderRisk() {
    const risk = state.result.risk || {};
    const box = $("risk-content"); box.replaceChildren();
    if (!risk.available) { box.append(node("p", { class: "unavailable", text: risk.reason || "El payoff global requiere opciones con un vencimiento común. Para vencimientos distintos, utiliza escenarios hasta el primer vencimiento." })); return; }
    const metricBox = (label, value, unlimited, isLoss) => node("div", {}, [node("p", { class: "risk-metric-label", text: label }), node("p", { class: `risk-metric-value ${isLoss ? "negative" : "positive"}`, text: unlimited ? "Ilimitada" : value == null ? "—" : money(isLoss ? Math.abs(value) : value) })]);
    box.append(node("div", { class: "risk-metrics" }, [metricBox("Ganancia máxima", risk.maximum_profit, risk.profit_unbounded, false), metricBox("Pérdida máxima", risk.maximum_loss, risk.loss_unbounded, true)]));
    const zeros = (risk.break_evens || []).map((value) => numeric(value)).join(" · ");
    const intervals = (risk.zero_intervals || []).map(([a, b]) => `${numeric(a)}–${b == null ? "∞" : numeric(b)}`).join("; ");
    box.append(node("p", { class: "risk-breaks" }, [node("strong", { text: "Puntos de equilibrio: " }), document.createTextNode(zeros || (intervals ? "" : "No hay cruces con P&L = 0.")), document.createTextNode(intervals ? `${zeros ? " · " : ""}Intervalos neutros: ${intervals}` : "")]));
    box.append(node("p", { class: "help", text: risk.reason || "Payoff contractual con primas y costes registrados, sin ejercicio o asignación anticipados ni caja futura no registrada. No equivale al máximo riesgo operativo o de margen." }));
  }
  function renderWarnings() {
    const list = node("ul", { class: "warning-list" });
    const warnings = state.result.warnings || [];
    for (const warning of warnings) list.append(node("li", { text: String(warning) }));
    if (!warnings.length) list.append(node("li", { class: "information", text: "Sin alertas adicionales para estos datos. La valoración sigue dependiendo de IV, tipos, dividendos y convenciones introducidos." }));
    $("warnings-content").replaceChildren(list);
  }
  function renderLegResults() {
    const body = $("results-legs"); body.replaceChildren();
    for (const leg of state.result.legs || []) {
      const row = node("tr", {}, [node("td", { text: leg.label || leg.id })]);
      for (const field of ["model_price", "mark_price", "model_pnl", "market_pnl", "delta", "gamma", "theta", "vega", "rho"]) row.append(node("td", { text: numeric(leg[field], field === "gamma" ? 4 : 2), class: field.endsWith("pnl") ? signClass(leg[field]) : "" }));
      body.append(row);
    }
  }
  function legend(text, dashed) { return node("span", { class: "legend-item" }, [node("span", { class: `legend-swatch${dashed ? " dashed" : ""}`, "aria-hidden": "true" }), document.createTextNode(text)]); }
  function renderChart() {
    if (!state.result) return;
    const timeMode = state.tab === "time";
    $("tab-price").classList.toggle("active", !timeMode); $("tab-time").classList.toggle("active", timeMode);
    $("tab-price").setAttribute("aria-selected", String(!timeMode)); $("tab-time").setAttribute("aria-selected", String(timeMode));
    $("chart-heading").textContent = timeMode ? "P&L al avanzar el calendario" : "P&L por precio del subyacente";
    $("chart-subtitle").textContent = timeMode ? `Spot e IV del escenario constantes en cada fecha; no es una trayectoria simulada.${state.resultScenario.cash_adjustment ? " Caja adicional excluida: falta calendario de cobros." : ""}` : `Hoy y ${dateLabel(state.result.scenario?.date)} · IV desplazada ${numeric(state.resultScenario.vol_shift * 100)} pp en el escenario`;
    const curve = state.result.curve || {}; const evolution = state.result.time_evolution || {};
    const rawX = timeMode ? (evolution.dates || []).map(dateNumber) : curve.spots || [];
    const series = timeMode ? [{ label: "P&L a spot del escenario", values: evolution.pnl || [], color: "#087f7b" }] : [{ label: `Hoy · ${dateLabel(state.resultPortfolio.valuation_date)}`, values: curve.today_pnl || [], color: "#748ca5", dashed: true }, { label: `Escenario · ${dateLabel(state.result.scenario?.date)}`, values: curve.horizon_pnl || [], color: "#087f7b" }];
    $("chart-legend").replaceChildren(...series.map((item) => legend(item.label, item.dashed)));
    const container = $("chart-container"); container.replaceChildren();
    if (!rawX.length || series.some((item) => item.values.length !== rawX.length) || rawX.some((value) => !Number.isFinite(value)) || series.some((item) => item.values.some((value) => !Number.isFinite(value)))) { container.append(node("p", { class: "unavailable", text: "No hay una malla válida disponible para este gráfico." })); return; }
    const width = Math.max(360, Math.min(1000, container.clientWidth || 1000));
    const narrow = width < 600;
    const height = narrow ? 280 : 355;
    const pad = { left: narrow ? 58 : 83, right: narrow ? 12 : 27, top: 22, bottom: 48 };
    let minX = Math.min(...rawX), maxX = Math.max(...rawX);
    let minY = Math.min(0, ...series.flatMap((item) => item.values)), maxY = Math.max(0, ...series.flatMap((item) => item.values));
    const yRange = maxY - minY || Math.max(Math.abs(maxY) * 0.1, 1);
    minY -= yRange * 0.1; maxY += yRange * 0.1;
    if (minX === maxX) { minX -= timeMode ? DAY / 2 : 0.5; maxX += timeMode ? DAY / 2 : 0.5; }
    const xScale = (value) => pad.left + (value - minX) / (maxX - minX) * (width - pad.left - pad.right);
    const yScale = (value) => height - pad.bottom - (value - minY) / (maxY - minY) * (height - pad.top - pad.bottom);
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-labelledby": "chart-title chart-description", tabindex: "0" });
    root.append(svg("title", { id: "chart-title" }, $("chart-heading").textContent), svg("desc", { id: "chart-description" }, `${timeMode ? "Evolución por fecha a spot fijo" : "Curvas de P&L hoy y en la fecha del escenario"}. Los resultados detallados se pueden exportar en CSV. Usa las flechas izquierda y derecha para recorrer los puntos.`));
    const tickCount = narrow ? 3 : 5;
    for (let i = 0; i <= tickCount; i += 1) {
      const y = minY + (maxY - minY) * i / tickCount;
      root.append(svg("line", { x1: pad.left, x2: width - pad.right, y1: yScale(y), y2: yScale(y), stroke: "#e9eef1", "stroke-width": "1" }));
      root.append(svg("text", { x: pad.left - 13, y: yScale(y) + 4, "text-anchor": "end", fill: "#718493", "font-size": "12", "font-family": "inherit" }, compact(y)));
      const x = minX + (maxX - minX) * i / tickCount;
      const label = timeMode ? new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", timeZone: "UTC" }).format(new Date(x)) : compact(x);
      root.append(svg("text", { x: xScale(x), y: height - pad.bottom + 24, "text-anchor": "middle", fill: "#718493", "font-size": "12", "font-family": "inherit" }, label));
    }
    root.append(svg("text", { x: 5, y: 12, fill: "#7c8c97", "font-size": "11", "font-family": "inherit" }, `P&L · ${state.resultPortfolio.currency}`));
    root.append(svg("line", { x1: pad.left, x2: width - pad.right, y1: yScale(0), y2: yScale(0), stroke: "#b7c5cf", "stroke-width": "1", "stroke-dasharray": "4 4" }));
    if (!timeMode && state.resultPortfolio.spot >= minX && state.resultPortfolio.spot <= maxX) root.append(svg("line", { x1: xScale(state.resultPortfolio.spot), x2: xScale(state.resultPortfolio.spot), y1: pad.top, y2: height - pad.bottom, stroke: "#d5dee4", "stroke-width": "1", "stroke-dasharray": "3 5" }));
    for (const item of series) {
      const path = rawX.map((x, i) => `${i ? "L" : "M"}${xScale(x).toFixed(3)},${yScale(item.values[i]).toFixed(3)}`).join(" ");
      root.append(svg("path", { d: path, fill: "none", stroke: item.color, "stroke-width": item.dashed ? "2.3" : "3", "stroke-dasharray": item.dashed ? "7 5" : "none", "stroke-linejoin": "round", "stroke-linecap": "round" }));
    }
    const marker = svg("line", { x1: pad.left, x2: pad.left, y1: pad.top, y2: height - pad.bottom, stroke: "#7c8d99", "stroke-width": "1", "stroke-dasharray": "2 4", visibility: "hidden" });
    const dots = series.map((item) => svg("circle", { r: "4", fill: item.color, stroke: "#fff", "stroke-width": "2", visibility: "hidden" }));
    root.append(marker, ...dots);
    let selected = 0;
    function showPoint(index) {
      selected = Math.max(0, Math.min(index, rawX.length - 1));
      const x = xScale(rawX[selected]); marker.setAttribute("x1", x); marker.setAttribute("x2", x); marker.setAttribute("visibility", "visible");
      dots.forEach((dot, i) => { dot.setAttribute("cx", x); dot.setAttribute("cy", yScale(series[i].values[selected])); dot.setAttribute("visibility", "visible"); });
      const first = timeMode ? dateLabel(evolution.dates[selected]) : `Spot ${numeric(rawX[selected])}`;
      $("chart-readout").textContent = `${first}  ·  ${series.map((item) => `${item.label}: ${money(item.values[selected])}`).join("  ·  ")}`;
    }
    root.addEventListener("pointermove", (event) => {
      const bounds = root.getBoundingClientRect(); const x = (event.clientX - bounds.left) / bounds.width * width;
      const actual = minX + (x - pad.left) / (width - pad.left - pad.right) * (maxX - minX);
      let nearest = 0;
      rawX.forEach((value, index) => { if (Math.abs(value - actual) < Math.abs(rawX[nearest] - actual)) nearest = index; });
      showPoint(nearest);
    });
    root.addEventListener("keydown", (event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); showPoint(selected + (event.key === "ArrowRight" ? 1 : -1)); } });
    root.addEventListener("focus", () => showPoint(selected));
    container.append(root);
    $("chart-readout").textContent = "Consulta valores con el cursor o con las flechas al enfocar el gráfico.";
  }

  function download(filename, text, type) {
    const blob = new Blob([text], { type }); const url = URL.createObjectURL(blob);
    const link = node("a", { href: url, download: filename }); document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function safeFilename(name) { return String(name || "posicion").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80); }
  function csvCell(value) {
    if (value == null) return "";
    if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
    let text = String(value);
    if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  }
  function exportCsv() {
    if (!state.result) return;
    const r = state.result; const p = state.resultPortfolio;
    const rows = [["OptionsLab", "Resultados de valoración y escenarios"], ["Posición", p.name], ["Subyacente", p.underlying], ["Divisa", p.currency], ["Fecha base", p.valuation_date], ["Spot base", p.spot], ["Tipo base decimal", p.rate], ["Yield continuo decimal", p.dividend_yield], ["Caja registrada", p.cash_adjustment], ["Fecha escenario", r.scenario?.date], ["Spot escenario", r.scenario?.spot], ["Shock IV decimal", state.resultScenario.vol_shift], ["Shock tipo decimal", state.resultScenario.rate_shift], ["Caja adicional escenario", state.resultScenario.cash_adjustment], ["P&L modelo hoy", r.summary?.model_pnl], ["P&L observado hoy", r.summary?.market_pnl], ["P&L liquidación hoy", r.summary?.liquidation_pnl], ["P&L escenario", r.scenario?.pnl], ["Convención P&L", "Entrada y cierre estimado descontados; caja registrada incluida"], [], ["Riesgo payoff", r.risk?.reason], ["Ganancia máxima", r.risk?.profit_unbounded ? "Ilimitada" : r.risk?.maximum_profit], ["Pérdida máxima", r.risk?.loss_unbounded ? "Ilimitada" : r.risk?.maximum_loss], ["Puntos de equilibrio", (r.risk?.break_evens || []).join("; ")], [], ["Pata", "Modelo por unidad", "Marca por unidad", "P&L modelo", "P&L observado", "Delta", "Gamma", "Theta/día", "Vega/pp", "Rho/pp"]];
    (r.legs || []).forEach((leg) => rows.push([leg.label || leg.id, ...["model_price", "mark_price", "model_pnl", "market_pnl", "delta", "gamma", "theta", "vega", "rho"].map((key) => leg[key])]));
    rows.push([], ["Spot", "P&L hoy", "P&L escenario"]);
    (r.curve?.spots || []).forEach((spot, index) => rows.push([spot, r.curve.today_pnl[index], r.curve.horizon_pnl[index]]));
    rows.push([], ["Fecha", "P&L a spot de escenario fijo"]);
    (r.time_evolution?.dates || []).forEach((date, index) => rows.push([date, r.time_evolution.pnl[index]]));
    rows.push([], ["Advertencias"]); (r.warnings || []).forEach((warning) => rows.push([warning]));
    download(`${safeFilename(p.name)}_resultados.csv`, "\uFEFF" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n"), "text/csv;charset=utf-8");
  }
  function validImport(portfolio) {
    if (!portfolio || typeof portfolio !== "object" || Array.isArray(portfolio) || portfolio.schema_version !== 1 || !Array.isArray(portfolio.legs) || portfolio.legs.length > 32) throw new Error("El archivo debe contener una posición OptionsLab con schema_version 1 y un máximo de 32 patas.");
    if (typeof portfolio.valuation_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(portfolio.valuation_date) || !Number.isFinite(dateNumber(portfolio.valuation_date)) || typeof portfolio.spot !== "number" || !Number.isFinite(portfolio.spot)) throw new Error("Faltan una fecha base y un spot válidos en el archivo.");
    if (portfolio.legs.some((leg) => !leg || typeof leg !== "object" || !["call", "put", "stock"].includes(leg.kind) || typeof leg.id !== "string")) throw new Error("Cada pata necesita un identificador y un tipo call, put o stock.");
    if (portfolio.cash_dividends != null && (!Array.isArray(portfolio.cash_dividends) || portfolio.cash_dividends.some((item) => !item || typeof item !== "object"))) throw new Error("El calendario de dividendos debe ser una lista de fechas e importes.");
    return portfolio;
  }

  $("workspace").addEventListener("submit", (event) => { event.preventDefault(); analyze(); });
  $("workspace").addEventListener("input", () => markDirty());
  $("valuation-date").addEventListener("change", () => { collectPortfolio(); adjustHorizon(); });
  $("scenario-date").addEventListener("input", syncSlider);
  $("days-slider").addEventListener("input", () => { const days = Number($("days-slider").value); $("scenario-date").value = addDays($("valuation-date").value, days); $("days-label").textContent = String(days); });
  $("add-leg").addEventListener("click", () => {
    collectPortfolio();
    if (state.portfolio.legs.length >= 32) return;
    state.portfolio.legs.push({ id: `manual-${Date.now()}-${nextId++}`, label: "Nueva pata", kind: "call", quantity: 1, multiplier: 100, strike: state.portfolio.spot || 100, expiry: firstExpiry() || addDays(state.portfolio.valuation_date, 90), volatility: 0.25, style: "european", entry_price: 0, mark_price: null, bid: null, ask: null, entry_fee: 0, exit_fee: 0 });
    renderLegs(); adjustHorizon(); markDirty(); info("Nueva pata con prima de entrada 0. Introduce el precio de ejecución real o una prima hipotética deliberada antes de interpretar el P&L.");
  });
  $("add-dividend").addEventListener("click", () => { collectPortfolio(); state.portfolio.cash_dividends.push({ date: addDays(state.portfolio.valuation_date, 15), amount: 1 }); renderDividends(); markDirty(); });
  $("template-button").addEventListener("click", async () => {
    const id = $("template-select").value;
    if (!id || state.busy) return;
    clearError(); collectPortfolio(); setBusy(true, "Preparando estructura…");
    try { const portfolio = await api("/api/template", { id, portfolio: state.portfolio }); setPortfolio(portfolio); info("Estructura de ejemplo cargada con primas teóricas. Sustituye primas, contratos, fechas y marcas por los datos reales de tu posición."); }
    catch (exception) { error(exception.message); }
    finally { setBusy(false); }
  });
  $("save-button").addEventListener("click", () => { if (!state.portfolio || !$("workspace").reportValidity()) return; collectPortfolio(); download(`${safeFilename(state.portfolio.name)}.json`, JSON.stringify(state.portfolio, null, 2) + "\n", "application/json"); info("Posición guardada como JSON. Los resultados se recalculan al importar; el fichero contiene tus datos de entrada."); });
  $("import-button").addEventListener("click", () => $("import-file").click());
  $("import-file").addEventListener("change", async (event) => {
    const file = event.target.files[0]; if (!file) return;
    clearError();
    setBusy(true, "Validando posición…");
    try { if (file.size > 512000) throw new Error("El archivo supera el límite de 500 KB para una posición."); const parsed = validImport(JSON.parse(await file.text())); const portfolio = await api("/api/validate", { portfolio: parsed }); setPortfolio(portfolio); info("Posición importada y validada. Revisa los datos y pulsa Calcular posición para actualizar los resultados."); }
    catch (exception) { error(`No se pudo importar el archivo: ${exception.message}`); }
    finally { event.target.value = ""; setBusy(false); }
  });
  $("csv-button").addEventListener("click", exportCsv);
  $("tab-price").addEventListener("click", () => { state.tab = "price"; renderChart(); });
  $("tab-time").addEventListener("click", () => { state.tab = "time"; renderChart(); });
  let resizeTimer;
  window.addEventListener("resize", () => { window.clearTimeout(resizeTimer); resizeTimer = window.setTimeout(renderChart, 100); });

  async function start() {
    try {
      const [portfolio, templates] = await Promise.all([api("/api/demo"), api("/api/templates")]);
      templates.forEach((template) => $("template-select").append(node("option", { value: template.id, text: template.label })));
      setPortfolio(portfolio);
      $("workspace").hidden = false; $("loading").hidden = true;
      info("La posición inicial es un ejemplo hipotético. No son cotizaciones de mercado.");
      await analyze();
    } catch (exception) { $("loading").hidden = true; error(`No se pudo iniciar la calculadora: ${exception.message}`); }
  }
  start();
})();
