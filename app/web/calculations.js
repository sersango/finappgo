(function (root, create) {
  "use strict";
  const C = create();
  if (typeof module === "object" && module.exports) module.exports = C;
  else root.Calculos = C;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const defaultValue = p => p.valor || 0;

  function parseAmount(text) {
    let t = String(text == null ? "" : text).replace(/[€\s]/g, "");
    if (!t) return NaN;
    if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
    else if (/^-?\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "");
    return /^-?\d+(\.\d+)?$/.test(t) ? parseFloat(t) : NaN;
  }

  function xirr(cashFlows) {
    const f = cashFlows.filter(x => x.v);
    if (f.length < 2) return null;
    if (!(f.some(x => x.v < 0) && f.some(x => x.v > 0))) return null;
    const t0 = Math.min.apply(null, f.map(x => x.t));
    const ANO = 365 * 24 * 3600 * 1000;
    const van = rate => {
      let s = 0;
      const base = 1 + rate;
      if (base <= 1e-9) return Infinity;
      for (const x of f) s += x.v / Math.pow(base, (x.t - t0) / ANO);
      return s;
    };
    let lo = -0.9999, hi = 10, vlo = van(lo), vhi = van(hi);
    if (!isFinite(vlo) || !isFinite(vhi) || vlo * vhi > 0) return null;
    for (let i = 0; i < 200; i++) {
      const mid = (lo + hi) / 2, vm = van(mid);
      if (Math.abs(vm) < 1e-7) return mid;
      if (vlo * vm <= 0) hi = mid; else { lo = mid; vlo = vm; }
    }
    return (lo + hi) / 2;
  }

  function metrics(entries, D, valueOf = defaultValue) {
    const n = D.fechas.length;
    const timeSeries = new Array(n).fill(0);
    const contributionSeries = new Array(n).fill(0);
    let value = 0, contributions = 0, valueWithCost = 0, irrValue = 0, nAp = 0, realized = 0;
    const cashFlows = [];

    entries.forEach(p => {
      const s = p.serie || [], sa = p.serieAportado || [];
      for (let i = 0; i < n; i++) {
        if (s[i] != null) timeSeries[i] += s[i];
        if (sa[i] != null) contributionSeries[i] += sa[i];
      }
      value += valueOf(p);
      realized += p.realizado || 0;
      if (p.aportado != null && p.aportado > 0) {
        contributions += p.aportado;
        valueWithCost += valueOf(p);
        nAp += (p.aportaciones || []).filter(a => a.importe).length;
      }

      if (p.flujos && p.flujos.length) {
        p.flujos.forEach(([f, v]) => cashFlows.push({ t: Date.parse(f), v }));
        irrValue += valueOf(p);
      }
    });

    const gain = contributions ? valueWithCost - contributions : null;
    const tir = cashFlows.length
      ? xirr(cashFlows.concat([{ t: Date.parse(D.fechaExtracto), v: irrValue }]))
      : null;

    const am = D.aportacionesMensuales || { meses: [], porProducto: {} };
    const ids = new Set(entries.map(p => p.id));
    const byMonth = am.meses.map((_, i) => Object.keys(am.porProducto)
      .reduce((a, id) => a + (ids.has(id) ? (am.porProducto[id][i] || 0) : 0), 0));
    const contributionMonths = am.meses.filter((m, i) => byMonth[i] > 0);
    const ult12 = byMonth.slice(-12);
    const pace = ult12.length ? ult12.reduce((a, b) => a + b, 0) / ult12.length : 0;

    let streak = 0;
    if (contributionMonths.length) {
      const set = new Set(contributionMonths);
      const ult = contributionMonths[contributionMonths.length - 1].split("-");
      let y = +ult[0], mo = +ult[1];
      while (set.has(y + "-" + String(mo).padStart(2, "0"))) {
        streak++; mo--; if (mo === 0) { mo = 12; y--; }
      }
    }

    let peak = 0, drawdown = 0, drawdownDate = null;
    for (let i = 0; i < n; i++) {
      peak = Math.max(peak, timeSeries[i]);
      if (peak > 0) {
        const c = timeSeries[i] / peak - 1;
        if (c < drawdown) { drawdown = c; drawdownDate = D.fechas[i]; }
      }
    }

    return {
      valor: value, aportado: contributions, valorConCoste: valueWithCost, plusvalia: gain, realizado: realized,
      rentabilidad: contributions ? gain / contributions : null,
      tir, numAportaciones: nAp, ritmo: pace, racha: streak, caida: drawdown, caidaFecha: drawdownDate,
      serie: timeSeries, serieAportado: contributionSeries,
    };
  }

  const NON_EQUITY = ["efectivo", "cripto", "commodity", "inmueble", "bono", "p2p"];

  function aggregateExposure(entries, valueOf = defaultValue) {
    let equityShare = 0, outside = 0, noData = 0;
    const countries = new Map(), sectors = new Map(), unnamed = [];
    const sum = (m, n, v) => m.set(n, (m.get(n) || 0) + v);
    entries.forEach(p => {
      const v = valueOf(p);
      if (!(v > 0)) return;
      const e = p.exposicion;

      if (!e && NON_EQUITY.includes(p.tipoClave)) { outside += v; return; }
      if (!e) { noData += v; unnamed.push(p.corto || p.nombre); return; }
      const rv = e.rv == null ? 1 : e.rv, vb = v * rv;
      equityShare += vb;
      outside += v - vb;
      (e.paises || []).forEach(([n, pct]) => sum(countries, n === "Resto" ? "Otros" : n, vb * pct / 100));
      (e.sectores || []).forEach(([n, pct]) => sum(sectors, n === "Resto" ? "Otros" : n, vb * pct / 100));
    });
    const sortEntries = m => {
      if (!(equityShare > 0)) return [];
      const rows = [...m.entries()].filter(([n]) => n !== "Otros").sort((a, b) => b[1] - a[1]);
      const others = (m.get("Otros") || 0) + rows.slice(9).reduce((a, x) => a + x[1], 0);
      return rows.slice(0, 9).concat(others > 0 ? [["Otros", others]] : []).map(([n, v]) => [n, +(v / equityShare * 100).toFixed(1)]);
    };
    return { enBolsa: equityShare, fuera: outside, sinDatos: noData, sinNombre: unnamed, paises: sortEntries(countries), sectores: sortEntries(sectors) };
  }

  const isLiquid = p => p.liquidez != null ? !!p.liquidez
    : p.tipoClave === "efectivo" || /monetari/i.test([p.clase, p.nombre, p.tipo].join(" "));

  function liquiditySummary(entries, emergencyFund, valueOf = defaultValue) {
    const products = entries.filter(p => isLiquid(p) && valueOf(p) > 0).sort((a, b) => valueOf(b) - valueOf(a));
    const liquidity = products.reduce((a, p) => a + valueOf(p), 0);
    const r = { productos: products, liquidez: liquidity, objetivo: null, cubierto: null, sobra: null, meses: null, pct: null };
    if (!emergencyFund || !(emergencyFund.importe > 0)) return r;
    r.objetivo = emergencyFund.importe;
    r.cubierto = Math.min(liquidity, emergencyFund.importe);
    r.sobra = liquidity - emergencyFund.importe;
    r.meses = emergencyFund.modo === "meses" && emergencyFund.gastoMensual ? liquidity / emergencyFund.gastoMensual : null;
    r.pct = Math.min(1, liquidity / emergencyFund.importe);
    return r;
  }

  const TIPOS_REPARTO = ["Renta variable", "Renta fija", "Mixtos", "Monetario", "Efectivo", "Criptoactivos",
    "Materias primas", "Inmuebles", "P2P y crowdfunding", "Planes de pensiones", "Otros"];
  const POR_TEXTO = [
    [/monetari|money market|liquidez/i, "Monetario"],
    [/mixt|allocation|multiactivo/i, "Mixtos"],
    [/^rf\b|renta fija|bond|bonos|fixed income|deuda/i, "Renta fija"],
    [/^rv\b|renta variable|equity|acciones|bolsa|stock/i, "Renta variable"],
    [/inmobiliari|property|real estate|inmueble/i, "Inmuebles"],
    [/commodit|materias primas|metales|oro\b|gold/i, "Materias primas"],
    [/cripto|crypto/i, "Criptoactivos"],
    [/efectivo|^cuentas?\b/i, "Efectivo"],
    [/p2p|crowdfunding/i, "P2P y crowdfunding"],
    [/jubilaci|pensi/i, "Planes de pensiones"],
  ];
  const typeFromText = t => (TIPOS_REPARTO.includes(t) ? t : (POR_TEXTO.find(([re]) => re.test(t || "")) || [])[1]) || null;
  const POR_TIPO = { cripto: "Criptoactivos", efectivo: "Efectivo", inmueble: "Inmuebles", p2p: "P2P y crowdfunding",
    commodity: "Materias primas", bono: "Renta fija", accion: "Renta variable" };

  function allocationType(p) {
    return POR_TIPO[p.tipoClave] || typeFromText(p.clase) || typeFromText(p.tipo) ||
      { etf: "Renta variable", pension: "Planes de pensiones" }[p.tipoClave] || "Otros";
  }

  function normalizeAllocation(o) {
    if (!o || o.por === "producto") return o;
    const weights = {};
    Object.entries(o.pesos || {}).forEach(([k, v]) => {
      const t = typeFromText(k) || "Otros";
      weights[t] = Math.round(((weights[t] || 0) + Number(v || 0)) * 100) / 100;
    });
    return { ...o, por: "clase", pesos: weights, conEfectivo: !!o.conEfectivo || weights.Efectivo > 0 };
  }

  const allocationGroup = (p, o) => (o.por === "producto" ? (p.corto || p.nombre) : allocationType(p));

  function includedByDefault(p, o) {
    o = normalizeAllocation(o);
    if (p.tipoClave === "deuda") return false;
    if (o.conEfectivo) return true;
    if (p.tipoClave === "efectivo") return o.pesos[allocationGroup(p, o)] > 0;
    return p.largoPlazo !== false;
  }

  function includedInAllocation(p, o) {
    if (p.tipoClave === "deuda") return false;
    const selected = o && o.cuenta && p.id != null && Object.prototype.hasOwnProperty.call(o.cuenta, p.id) ? o.cuenta[p.id] : null;
    return selected == null ? includedByDefault(p, o) : !!selected;
  }

  function allocationGroups(entries, o, valueOf = defaultValue, colorOf = () => null) {
    o = normalizeAllocation(o);
    const acc = new Map();
    entries.forEach(p => {
      const v = valueOf(p);
      if (!(v > 0) || !includedInAllocation(p, o)) return;
      const k = allocationGroup(p, o);
      const g = acc.get(k) || { nombre: k, valor: 0, color: colorOf(p), productos: [] };
      g.valor += v;
      g.productos.push(p.corto || p.nombre);
      acc.set(k, g);
    });
    Object.keys(o.pesos).forEach(k => { if (!acc.has(k)) acc.set(k, { nombre: k, valor: 0, color: colorOf(null), productos: [] }); });
    return [...acc.values()];
  }

  function allocationRows(groups, o) {
    const total = groups.reduce((a, g) => a + g.valor, 0);
    const rows = groups.map(g => {
      const now = total ? g.valor / total * 100 : 0, obj = o.pesos[g.nombre] || 0, deviation = now - obj;
      const state = Math.abs(deviation) <= o.vigilar ? "ok" : Math.abs(deviation) <= o.rebalancear ? "vigilar" : "rebalancear";
      return { ...g, ahora: now, obj, desv: deviation, estado: state, cuadrar: obj / 100 * total - g.valor };
    }).sort((a, b) => b.obj - a.obj || b.valor - a.valor);
    const worst = rows.length ? rows.reduce((a, f) => Math.abs(f.desv) > Math.abs(a.desv) ? f : a, rows[0]) : null;
    return { total, filas: rows, peor: worst };
  }

  function distributeContribution(groups, weights, contribution) {
    if (!(contribution > 0)) return groups.map(() => 0);
    const total = groups.reduce((a, g) => a + g.valor, 0) + contribution;
    const missing = groups.map(g => Math.max(0, (weights[g.nombre] || 0) / 100 * total - g.valor));
    const totalShortfall = missing.reduce((a, b) => a + b, 0);
    if (totalShortfall <= contribution) {
      const surplus = contribution - totalShortfall;
      const totalWeight = groups.reduce((a, g) => a + (weights[g.nombre] || 0), 0) || 1;
      return groups.map((g, i) => missing[i] + surplus * (weights[g.nombre] || 0) / totalWeight);
    }
    return missing.map(f => contribution * f / totalShortfall);
  }

  function pendingContributions(recurring, productIds, hoy) {
    const dos = n => String(n).padStart(2, "0");
    const out = [];
    (Array.isArray(recurring) ? recurring : []).forEach(r => {
      if (!r || !productIds.includes(r.producto) || !/^\d{4}-\d{2}-\d{2}$/.test(r.ultima || "")) return;
      const dia = Math.min(Math.max(parseInt(r.dia, 10) || 1, 1), 31);
      let [a, m] = r.ultima.split("-").map(Number);
      let firstDate = null, count = 0;
      for (let i = 0; i < 600; i++) {
        m += 1;
        if (m > 12) { m = 1; a += 1; }
        const lastDay = new Date(Date.UTC(a, m, 0)).getUTCDate();
        const f = `${a}-${dos(m)}-${dos(Math.min(dia, lastDay))}`;
        if (f > hoy) break;
        firstDate = firstDate || f;
        count += 1;
      }
      if (count) out.push({ producto: r.producto, importe: Number(r.importe) || 0, dia, desde: firstDate, cuantas: count });
    });
    return out;
  }

  const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre"];
  function shareSummary(D, i) {
    const rm = (D && D.resumenMensual) || [];
    if (!rm.length) return null;
    if (i == null || !(i >= 0 && i < rm.length)) i = rm.length - 1;
    const r = rm[i];
    const [ano, mes] = r.mes.split("-").map(Number);
    const endOf = (a, m) => new Date(Date.UTC(a, m, 0)).toISOString().slice(0, 10);
    const last = i === rm.length - 1;
    const ongoing = last && String(D.fechaExtracto || "") < endOf(ano, mes);
    const F = D.fechas || [], I = D.indiceCartera || [];
    const indexAt = lim => {
      let v = null;
      for (let k = 0; k < F.length && F[k] <= lim; k++) if (I[k] != null) v = I[k];
      return v;
    };
    let base = indexAt(`${ano - 1}-12-31`), start = 1;
    if (base == null) {
      const k = F.findIndex((f, j) => f >= `${ano}-01-01` && I[j] != null);
      base = k >= 0 ? I[k] : null;
      start = k >= 0 ? +F[k].slice(5, 7) : mes;
    }
    const timeSeries = base == null ? [] : [base];
    for (let m = start; m <= mes; m++) {
      const v = indexAt(endOf(ano, m));
      if (v != null) timeSeries.push(v);
    }
    const first = I.find(v => v != null);
    const fin = timeSeries.length ? timeSeries[timeSeries.length - 1] : null;
    let k = i, streak = 0;
    if (ongoing && !(rm[k].aportado > 0)) k--;
    while (k >= 0 && rm[k].aportado > 0) { streak++; k--; }
    const newItem = r.nuevo || 0;
    const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
    return {
      mes: r.mes, ano, nombreMes: MONTHS[mes - 1], etiqueta: `${cap(MONTHS[mes - 1])} ${ano}`,
      enCurso: ongoing, ultimo: last,
      rentMes: r.rentabilidad,
      anoPct: base && fin ? fin / base - 1 : null,
      desdeInicio: first && fin ? fin / first - 1 : null,
      serieAno: timeSeries, etqIni: cap(MONTHS[start - 1]), etqFin: cap(MONTHS[mes - 1]),
      racha: streak,
      tir: last && D.total ? D.total.tir : null,
      patrimonio: r.fin, cambioEur: r.fin - r.inicio - newItem,
      aportadoEur: r.aportado, mercadoEur: r.mercado,
      crecimiento: r.inicio > 0 ? (r.fin - r.inicio - newItem) / r.inicio : null,
      porAportado: r.inicio > 0 ? r.aportado / r.inicio : null,
      porMercado: r.inicio > 0 ? r.mercado / r.inicio : null,
    };
  }

  return {
    leeImporte: parseAmount, xirr, metricas: metrics, agregaExposicion: aggregateExposure, esLiquidez: isLiquid, resumenLiquidez: liquiditySummary,
    gruposReparto: allocationGroups, filasReparto: allocationRows, repartirAportacion: distributeContribution, normalizaReparto: normalizeAllocation, tipoReparto: allocationType, TIPOS_REPARTO,
    cuentaPorDefecto: includedByDefault, cuentaEnReparto: includedInAllocation, FUERA_DE_BOLSA: NON_EQUITY, periodicasPendientes: pendingContributions,
    resumenParaCompartir: shareSummary,
  };
});
