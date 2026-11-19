(function (global) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  const SYMBOLS = { EUR: "€", USD: "$", GBP: "£", CHF: "CHF", MXN: "MX$", ARS: "AR$", CLP: "CLP$", COP: "COL$" };
  const currencySymbol = c => SYMBOLS[c] || c;
  const CURRENCY = { codigo: "EUR", porEuro: 1, simbolo: "€" };
  let nfEur, nfEur0;
  function setCurrency(code, perEuro) {
    const ok = code && code !== "EUR" && perEuro > 0;
    CURRENCY.codigo = ok ? code : "EUR";
    CURRENCY.porEuro = ok ? perEuro : 1;
    CURRENCY.simbolo = currencySymbol(CURRENCY.codigo);
    if (!ok) {
      nfEur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
      nfEur0 = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
      return;
    }

    const dec = new Intl.NumberFormat("es-ES", { style: "currency", currency: CURRENCY.codigo }).resolvedOptions().maximumFractionDigits;
    const n = new Intl.NumberFormat("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    const n0 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
    nfEur = { format: v => n.format(v) + " " + CURRENCY.simbolo };
    nfEur0 = { format: v => n0.format(v) + " " + CURRENCY.simbolo };
  }
  setCurrency("EUR");
  const nfNum = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 });
  const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  const hidden = () => global.OCULTAR_IMPORTES === true;
  const unitsFormat = { format: v => hidden() ? "•••" : nfNum.format(v) };

  function fmtEur(v, dec) {
    if (hidden()) return "•••";
    if (v === null || v === undefined || isNaN(v)) return "—";
    v *= CURRENCY.porEuro;
    return dec === 0 ? nfEur0.format(v) : nfEur.format(v);
  }
  function formatShortEur(v) {
    if (hidden()) return "•••";
    if (v === null || v === undefined || isNaN(v)) return "—";
    v *= CURRENCY.porEuro;
    const a = Math.abs(v), s = CURRENCY.simbolo;
    if (a >= 1e9) return (v / 1e9).toLocaleString("es-ES", { maximumFractionDigits: 2 }) + " mil M" + s;
    if (a >= 1e6) return (v / 1e6).toLocaleString("es-ES", { maximumFractionDigits: 2 }) + " M" + s;
    if (a >= 1000) return (v / 1000).toLocaleString("es-ES", { maximumFractionDigits: 1 }) + "k " + s;
    return Math.round(v) + " " + s;
  }
  fmtEur.dinero = formatShortEur.dinero = true;

  const cash = fn => Object.assign(fn, { dinero: true });
  const axisFactor = fY => (fY && fY.dinero ? CURRENCY.porEuro : 1);
  function fmtPct(v, dec) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const d = dec === undefined ? 2 : dec;
    return (v * 100).toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d }) + " %";
  }
  function formatSignedPercent(v, dec) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + fmtPct(v, dec);
  }
  function formatSignedEur(v) {
    if (hidden()) return "•••";
    if (v === null || v === undefined || isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + fmtEur(v);
  }
  function formatDate(iso) {
    if (!iso) return "—";
    const p = iso.split("-");
    return `${+p[2]} ${MONTHS[+p[1] - 1]} ${p[0]}`;
  }
  function formatShortDate(iso) {
    const p = iso.split("-");
    return `${+p[2]}/${+p[1]}/${p[0].slice(2)}`;
  }
  function formatMonth(ym) {
    const p = ym.split("-");
    return `${MONTHS[+p[1] - 1]} ${p[0].slice(2)}`;
  }

  function el(tag, attrs, children) {
    const n = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) {
      if (attrs[k] === null || attrs[k] === undefined) continue;
      n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(h => n.appendChild(h));
    return n;
  }
  function txt(x, y, s, cls, extra) {
    const n = el("text", Object.assign({ x, y, class: cls || "" }, extra || {}));
    n.textContent = s;
    return n;
  }
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function niceScale(max, min, f) {
    f = f || 1;
    max *= f;
    min = (min || 0) * f;
    if (max <= min) max = min + 1;
    const raw = (max - min) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    return { max: Math.ceil(max / step) * step / f, min: Math.floor(min / step) * step / f, paso: step / f };
  }

  function xAxisIndices(n, count) {
    if (n <= 1) return [0];
    const k = Math.min(count, n);
    const out = [];
    for (let i = 0; i < k; i++) out.push(Math.round(i * (n - 1) / (k - 1)));
    return [...new Set(out)];
  }

  function xAxisLabel(dates, i, n) {
    const f = dates[i];
    const days = n;
    if (days > 400) return `${MONTHS[+f.split("-")[1] - 1]} ${f.split("-")[0].slice(2)}`;
    if (days > 70) return `${MONTHS[+f.split("-")[1] - 1]} ${f.split("-")[0].slice(2)}`;
    return `${+f.split("-")[2]} ${MONTHS[+f.split("-")[1] - 1]}`;
  }

  function createTooltip(cont) {
    let t = cont.querySelector(".gtt");
    if (!t) {
      t = document.createElement("div");
      t.className = "gtt";
      cont.appendChild(t);
    }
    return t;
  }
  function positionTooltip(tt, cont, x, y) {
    const cw = cont.clientWidth, tw = tt.offsetWidth || 200, th = tt.offsetHeight || 80;
    let px = x + 14;
    if (px + tw > cw - 4) px = x - tw - 14;
    if (px < 4) px = 4;
    let py = y - th - 12;
    if (py < 4) py = y + 18;
    tt.style.transform = `translate(${px}px, ${py}px)`;
  }

  function stackedArea(cont, cfg) {
    cont.innerHTML = "";
    const W = Math.max(cont.clientWidth, 320);
    const H = cfg.alto || 320;
    const P = { t: 14, r: 14, b: 26, l: 62 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const dates = cfg.fechas, n = dates.length;
    const series = cfg.series.filter(s => s.valores.some(v => v));
    if (!n || !series.length) { cont.innerHTML = '<p class="vacio">Sin datos en este rango.</p>'; return; }

    const accumulated = [];
    for (let s = 0; s < series.length; s++) {
      const prev = s === 0 ? new Array(n).fill(0) : accumulated[s - 1];
      accumulated.push(series[s].valores.map((v, i) => prev[i] + (v || 0)));
    }
    const totals = accumulated[accumulated.length - 1];
    let maxV = Math.max(...totals);
    if (cfg.overlay) maxV = Math.max(maxV, ...cfg.overlay.valores.filter(v => v != null));

    const fY = cfg.formatoY || formatShortEur;
    const fV = cfg.formatoValor || fmtEur;
    const esc = cfg.maxForzado
      ? { min: 0, max: cfg.maxForzado, paso: cfg.maxForzado / 4 }
      : niceScale(maxV, 0, axisFactor(fY));

    const x = i => P.l + (n === 1 ? iw / 2 : i * iw / (n - 1));
    const y = v => P.t + ih - ((v - esc.min) / (esc.max - esc.min)) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico", role: "img" });

    for (let v = esc.min; v <= esc.max + 1e-9; v += esc.paso) {
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: "rejilla" }));
      svg.appendChild(txt(P.l - 8, y(v) + 4, fY(v), "ejeY"));
    }

    for (let s = series.length - 1; s >= 0; s--) {
      const above = accumulated[s], below = s === 0 ? new Array(n).fill(0) : accumulated[s - 1];
      let dd = "";
      for (let i = 0; i < n; i++) dd += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(above[i]).toFixed(1) + " ";
      for (let i = n - 1; i >= 0; i--) dd += "L" + x(i).toFixed(1) + " " + y(below[i]).toFixed(1) + " ";
      svg.appendChild(el("path", { d: dd + "Z", fill: series[s].color, "fill-opacity": 0.9 }));
    }

    for (let s = 0; s < series.length - 1; s++) {
      let dd = "";
      for (let i = 0; i < n; i++) dd += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(accumulated[s][i]).toFixed(1) + " ";
      svg.appendChild(el("path", { d: dd, fill: "none", class: "separador" }));
    }

    if (cfg.overlay) {
      let dd = "", expanded = false;
      cfg.overlay.valores.forEach((v, i) => {
        if (v == null) { expanded = false; return; }
        dd += (expanded ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
        expanded = true;
      });
      svg.appendChild(el("path", { d: dd, fill: "none", class: "overlay" }));
    }

    svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: P.t + ih, y2: P.t + ih, class: "eje" }));
    xAxisIndices(n, W < 520 ? 4 : 7).forEach(i => {
      svg.appendChild(txt(x(i), H - 8, xAxisLabel(dates, i, n), "ejeX",
        { "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" }));
    });

    const g = el("g", { class: "cursor", opacity: 0 });
    const line = el("line", { y1: P.t, y2: P.t + ih, class: "crosshair" });
    g.appendChild(line);
    const points = series.map(s => el("circle", { r: 4.5, fill: s.color, class: "punto" }));
    points.forEach(p => g.appendChild(p));
    const totalPoint = el("circle", { r: 5.5, class: "puntoTotal" });
    g.appendChild(totalPoint);
    svg.appendChild(g);

    const hitArea = el("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent", style: "cursor:crosshair" });
    svg.appendChild(hitArea);
    cont.appendChild(svg);

    const tt = createTooltip(cont);
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      let i = Math.round((px - P.l) / (iw || 1) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      g.setAttribute("opacity", 1);
      line.setAttribute("x1", x(i)); line.setAttribute("x2", x(i));
      series.forEach((s, k) => {
        const vis = s.valores[i] ? 1 : 0;
        points[k].setAttribute("cx", x(i));
        points[k].setAttribute("cy", y(accumulated[k][i]));
        points[k].setAttribute("opacity", vis);
      });
      totalPoint.setAttribute("cx", x(i)); totalPoint.setAttribute("cy", y(totals[i]));
      let rows = series.map((s, k) => s.valores[i]
        ? `<tr><td><i style="background:${s.color}"></i>${s.nombre}</td><td>${fV(s.valores[i])}</td></tr>` : "")
        .reverse().join("");
      if (cfg.overlay && cfg.overlay.valores[i] != null)
        rows += `<tr class="sep"><td><i class="raya"></i>${cfg.overlay.nombre}</td><td>${fmtEur(cfg.overlay.valores[i])}</td></tr>`;
      tt.innerHTML = `<b>${formatDate(dates[i])}</b><div class="ttTotal">${fV(totals[i])}</div>
        <table>${rows}</table>`;
      tt.classList.add("on");
      positionTooltip(tt, cont, x(i) * (r.width / W), (ev.clientY - r.top));
      if (cfg.onHover) cfg.onHover(i);
    }
    hitArea.addEventListener("pointermove", move);
    hitArea.addEventListener("pointerdown", move);
    hitArea.addEventListener("pointerleave", () => {
      g.setAttribute("opacity", 0); tt.classList.remove("on");
      if (cfg.onHover) cfg.onHover(null);
    });
  }

  function lineWithEvents(cont, cfg) {
    cont.innerHTML = "";
    const W = Math.max(cont.clientWidth, 320);
    const H = cfg.alto || 240;
    const P = { t: 14, r: 14, b: 26, l: 62 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const dates = cfg.fechas, n = dates.length;
    const vals = cfg.valores;
    const valid = vals.filter(v => v != null);
    if (!n || !valid.length) { cont.innerHTML = '<p class="vacio">Sin datos en este rango.</p>'; return; }

    let maxV = Math.max(...valid), minV = Math.min(...valid);
    if (cfg.overlay) {
      const o = cfg.overlay.valores.filter(v => v != null);
      if (o.length) { maxV = Math.max(maxV, ...o); minV = Math.min(minV, ...o); }
    }
    const esc = niceScale(maxV, cfg.desdeCero === false ? minV - (maxV - minV) * 0.12 : 0,
      axisFactor(cfg.formatoY || formatShortEur));
    const x = i => P.l + (n === 1 ? iw / 2 : i * iw / (n - 1));
    const y = v => P.t + ih - ((v - esc.min) / (esc.max - esc.min)) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico" });
    for (let v = esc.min; v <= esc.max + 1e-9; v += esc.paso) {
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: "rejilla" }));
      svg.appendChild(txt(P.l - 8, y(v) + 4, cfg.formatoY ? cfg.formatoY(v) : formatShortEur(v), "ejeY"));
    }

    let dArea = "", dLin = "", expanded = false, firstX = null, lastX = null;
    vals.forEach((v, i) => {
      if (v == null) { expanded = false; return; }
      if (firstX === null) firstX = i;
      lastX = i;
      dLin += (expanded ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      expanded = true;
    });
    if (firstX !== null) {
      dArea = `M${x(firstX).toFixed(1)} ${(P.t + ih).toFixed(1)} ` +
        dLin.replace(/^M/, "L") + `L${x(lastX).toFixed(1)} ${(P.t + ih).toFixed(1)} Z`;
      svg.appendChild(el("path", { d: dArea, fill: cfg.color, "fill-opacity": 0.14 }));
    }
    if (cfg.overlay) {
      let dd = "", ab = false;
      cfg.overlay.valores.forEach((v, i) => {
        if (v == null) { ab = false; return; }
        dd += (ab ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
        ab = true;
      });
      svg.appendChild(el("path", { d: dd, fill: "none", class: "overlay" }));
    }
    svg.appendChild(el("path", { d: dLin, fill: "none", stroke: cfg.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

    if (cfg.referencia && cfg.referencia.valor >= esc.min && cfg.referencia.valor <= esc.max) {
      const yr = y(cfg.referencia.valor);
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: yr, y2: yr, class: "referencia" }));
      const t = txt(W - P.r - 6, yr - 7, cfg.referencia.etiqueta, "refEtiqueta", { "text-anchor": "end" });
      svg.appendChild(t);
    }

    const idx = {}; dates.forEach((f, i) => idx[f] = i);
    const inRange = f => { let i = idx[f]; if (i === undefined) i = dates.findIndex(x => x >= f); return i < 0 ? undefined : i; };

    const dots = [];
    (cfg.marcas || []).map(m => ({ m, i: inRange(m.fecha) })).filter(o => o.i !== undefined)
      .sort((a, b) => a.i - b.i).forEach(({ m, i }) => {
        svg.appendChild(el("line", { x1: x(i), x2: x(i), y1: P.t + 10, y2: P.t + ih, class: "marcaTraspaso" }));
        let cx = x(i);
        const previous = dots[dots.length - 1];
        if (previous && cx - previous.cx < 22) cx = previous.cx + 22;
        dots.push({ m, cx });
      });

    (cfg.eventos || []).forEach(ev => {
      const i = idx[ev.fecha];
      if (i === undefined || vals[i] == null) return;
      svg.appendChild(el("circle", {
        cx: x(i), cy: y(vals[i]), r: ev.r || 4.5,
        fill: ev.color || cfg.color, class: "marcador" + (ev.aro ? " aro" : "")
      }));
    });

    svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: P.t + ih, y2: P.t + ih, class: "eje" }));
    xAxisIndices(n, W < 520 ? 4 : 7).forEach(i => {
      svg.appendChild(txt(x(i), H - 8, xAxisLabel(dates, i, n), "ejeX",
        { "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" }));
    });

    const g = el("g", { class: "cursor", opacity: 0 });
    const line = el("line", { y1: P.t, y2: P.t + ih, class: "crosshair" });
    const point = el("circle", { r: 5.5, fill: cfg.color, class: "punto" });
    g.appendChild(line); g.appendChild(point);
    svg.appendChild(g);
    const hitArea = el("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent", style: "cursor:crosshair" });
    svg.appendChild(hitArea);
    const gBolas = dots.map(({ m, cx }) => {
      const g = el("g", { class: "marcaBola" + (m.aviso ? " aviso" : ""), tabindex: 0, role: "img", "aria-label": m.titulo || "" });
      g.appendChild(el("circle", { cx, cy: P.t + 10, r: 10 }));
      g.appendChild(txt(cx, P.t + 14.5, m.icono || "⇄", "marcaBolaIcono", { "text-anchor": "middle" }));
      if (m.aviso) g.appendChild(el("circle", { cx: cx + 8, cy: P.t + 2, r: 3.5, class: "marcaBolaPunto" }));
      svg.appendChild(g);
      return { g, m, cx };
    });
    cont.appendChild(svg);

    const byDate = {}; (cfg.eventos || []).concat(cfg.marcas || []).forEach(e => {
      const f = idx[e.fecha] !== undefined ? e.fecha : dates.find(x => x >= e.fecha);
      if (f) (byDate[f] = byDate[f] || []).push(e);
    });
    const tt = createTooltip(cont);
    gBolas.forEach(({ g, m, cx }) => {
      const sample = () => {
        const r = svg.getBoundingClientRect();
        g.classList.add("activa");
        tt.innerHTML = m.html;
        tt.classList.add("on", "ttMarca");
        positionTooltip(tt, cont, cx * (r.width / W), (P.t + 24) * (r.height / H));
      };
      const hide = () => { g.classList.remove("activa"); tt.classList.remove("on", "ttMarca"); };
      g.addEventListener("pointerenter", sample);
      g.addEventListener("pointerdown", sample);
      g.addEventListener("focus", sample);
      g.addEventListener("pointerleave", hide);
      g.addEventListener("blur", hide);
    });
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      let i = Math.max(0, Math.min(n - 1, Math.round((px - P.l) / (iw || 1) * (n - 1))));
      if (vals[i] == null) { tt.classList.remove("on"); g.setAttribute("opacity", 0); return; }
      g.setAttribute("opacity", 1);
      line.setAttribute("x1", x(i)); line.setAttribute("x2", x(i));
      point.setAttribute("cx", x(i)); point.setAttribute("cy", y(vals[i]));
      let extra = "";
      (byDate[dates[i]] || []).forEach(e => { extra += `<div class="ttEvento">${e.texto}</div>`; });
      if (cfg.overlay && cfg.overlay.valores[i] != null)
        extra += `<table><tr><td><i class="raya"></i>${cfg.overlay.nombre}</td><td>${fmtEur(cfg.overlay.valores[i])}</td></tr></table>`;
      tt.innerHTML = `<b>${formatDate(dates[i])}</b><div class="ttTotal">${cfg.formatoTT ? cfg.formatoTT(vals[i]) : fmtEur(vals[i])}</div>${extra}`;
      tt.classList.add("on");
      positionTooltip(tt, cont, x(i) * (r.width / W), ev.clientY - r.top);
    }
    hitArea.addEventListener("pointermove", move);
    hitArea.addEventListener("pointerdown", move);
    hitArea.addEventListener("pointerleave", () => { g.setAttribute("opacity", 0); tt.classList.remove("on"); });
  }

  function stackedBars(cont, cfg) {
    cont.innerHTML = "";
    const W = Math.max(cont.clientWidth, 320);
    const H = cfg.alto || 220;
    const P = { t: 14, r: 14, b: 30, l: 56 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const cats = cfg.categorias, n = cats.length;
    const series = cfg.series.filter(s => s.valores.some(v => v));
    if (!n || !series.length) { cont.innerHTML = '<p class="vacio">Sin aportaciones en este rango.</p>'; return; }

    const totals = cats.map((_, i) => series.reduce((a, s) => a + (s.valores[i] || 0), 0));
    const esc = niceScale(Math.max(...totals), 0, CURRENCY.porEuro);
    const step = iw / n;
    const width = Math.max(4, Math.min(step - 6, 46));
    const y = v => P.t + ih - (v / esc.max) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico" });
    for (let v = 0; v <= esc.max + 1e-9; v += esc.paso) {
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: "rejilla" }));
      svg.appendChild(txt(P.l - 8, y(v) + 4, formatShortEur(v), "ejeY"));
    }

    const groups = [];
    for (let i = 0; i < n; i++) {
      const cx = P.l + step * i + step / 2;
      const g = el("g", { class: "barraGrupo" });
      let base = 0;
      const portions = series.map((s, k) => ({ s, k, v: s.valores[i] || 0 })).filter(t => t.v > 0);
      portions.forEach((t, ord) => {
        const y0 = y(base + t.v), y1 = y(base);
        const height = Math.max(y1 - y0, 1);
        const last = ord === portions.length - 1;
        const r = Math.min(4, height / 2, width / 2);
        const d = last
          ? `M${cx - width / 2} ${y1} L${cx - width / 2} ${y0 + r} Q${cx - width / 2} ${y0} ${cx - width / 2 + r} ${y0} L${cx + width / 2 - r} ${y0} Q${cx + width / 2} ${y0} ${cx + width / 2} ${y0 + r} L${cx + width / 2} ${y1} Z`
          : `M${cx - width / 2} ${y1} L${cx - width / 2} ${y0} L${cx + width / 2} ${y0} L${cx + width / 2} ${y1} Z`;
        g.appendChild(el("path", { d, fill: t.s.color, class: ord ? "segSep" : "" }));
        base += t.v;
      });
      svg.appendChild(g);
      groups.push({ g, i, cx });
    }
    svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: P.t + ih, y2: P.t + ih, class: "eje" }));
    const cada = Math.max(1, Math.ceil(n / (W < 520 ? 5 : 12)));
    cats.forEach((c, i) => {
      if (i % cada) return;
      svg.appendChild(txt(P.l + step * i + step / 2, H - 10, formatMonth(c), "ejeX", { "text-anchor": "middle" }));
    });

    const highlight = el("rect", { class: "resalte", y: P.t, height: ih, width: step, opacity: 0 });
    svg.insertBefore(highlight, svg.firstChild.nextSibling);
    const hitArea = el("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent" });
    svg.appendChild(hitArea);
    cont.appendChild(svg);

    const tt = createTooltip(cont);
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      let i = Math.floor((px - P.l) / step);
      i = Math.max(0, Math.min(n - 1, i));
      highlight.setAttribute("x", P.l + step * i);
      highlight.setAttribute("opacity", 1);
      const rows = series.map(s => s.valores[i]
        ? `<tr><td><i style="background:${s.color}"></i>${s.nombre}</td><td>${fV(s.valores[i])}</td></tr>` : "")
        .reverse().join("");
      tt.innerHTML = `<b>${formatMonth(cats[i])}</b><div class="ttTotal">${fmtEur(totals[i])}</div><table>${rows}</table>`;
      tt.classList.add("on");
      positionTooltip(tt, cont, (P.l + step * i + step / 2) * (r.width / W), ev.clientY - r.top);
    }
    hitArea.addEventListener("pointermove", move);
    hitArea.addEventListener("pointerdown", move);
    hitArea.addEventListener("pointerleave", () => { tt.classList.remove("on"); highlight.setAttribute("opacity", 0); });
  }

  function donut(cont, cfg) {
    cont.innerHTML = "";
    const W = Math.max(cont.clientWidth, 200);
    const H = cfg.alto || 230;
    const R = Math.min(W, H) / 2 - 6;
    const r0 = R * 0.62;
    const cx = W / 2, cy = H / 2;
    const data = cfg.datos.filter(d => d.valor > 0);
    const total = data.reduce((a, d) => a + d.valor, 0);
    if (!total) { cont.innerHTML = '<p class="vacio">Sin datos.</p>'; return; }

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico donut" });
    let ang = -Math.PI / 2;
    const arcs = [];
    data.forEach((d, i) => {
      const sweep = (d.valor / total) * Math.PI * 2;
      const a0 = ang, a1 = ang + sweep;
      const large = sweep > Math.PI ? 1 : 0;
      const p = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
      const dd = `M${p(R, a0)} A${R} ${R} 0 ${large} 1 ${p(R, a1)} L${p(r0, a1)} A${r0} ${r0} 0 ${large} 0 ${p(r0, a0)} Z`;
      const arc = el("path", { d: dd, fill: d.color, class: "arco", "data-i": i });
      svg.appendChild(arc);
      arcs.push({ arco: arc, d, a: (a0 + a1) / 2 });
      ang = a1;
    });
    const center = el("g", { class: "donutCentro" });
    center.appendChild(txt(cx, cy - 4, cfg.tituloCentro || "", "donutEtiqueta", { "text-anchor": "middle" }));
    center.appendChild(txt(cx, cy + 20, cfg.valorCentro || formatShortEur(total), "donutValor", { "text-anchor": "middle" }));
    svg.appendChild(center);
    cont.appendChild(svg);

    const tt = createTooltip(cont);
    arcs.forEach(({ arco: arc, d }) => {
      arc.addEventListener("pointerenter", () => {
        arc.classList.add("act");
        tt.innerHTML = `<b>${d.nombre}</b><div class="ttTotal">${fmtEur(d.valor)}</div>
          <table><tr><td>Peso</td><td>${fmtPct(d.valor / total, 1)}</td></tr></table>`;
        tt.classList.add("on");
      });
      arc.addEventListener("pointermove", e => {
        const r = cont.getBoundingClientRect();
        positionTooltip(tt, cont, e.clientX - r.left, e.clientY - r.top);
      });
      arc.addEventListener("pointerleave", () => { arc.classList.remove("act"); tt.classList.remove("on"); });
      if (cfg.onClick) arc.addEventListener("click", () => cfg.onClick(d));
    });
  }

  function mini(cont, values, color) {
    cont.innerHTML = "";
    const W = Math.max(cont.clientWidth, 40), H = cont.clientHeight || 34;
    const v = values.filter(x => x != null);
    if (v.length < 2) return;
    const mx = Math.max(...v), mn = Math.min(...v);
    const range = (mx - mn) || 1;
    const n = values.length;
    let dd = "", ab = false;
    values.forEach((x, i) => {
      if (x == null) { ab = false; return; }
      const px = (i / (n - 1)) * (W - 2) + 1;
      const py = H - 2 - ((x - mn) / range) * (H - 4);
      dd += (ab ? "L" : "M") + px.toFixed(1) + " " + py.toFixed(1) + " ";
      ab = true;
    });
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "spark" });
    svg.appendChild(el("path", { d: dd, fill: "none", stroke: color, "stroke-width": 1.75, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    cont.appendChild(svg);
  }

  function horizontalBars(cont, cfg) {
    cont.innerHTML = "";
    const data = cfg.datos || [];
    if (!data.length) { cont.innerHTML = '<p class="vacio">Sin datos.</p>'; return; }
    const W = Math.max(cont.clientWidth, 260);
    const rowHeight = cfg.filaAlto || 26;
    const H = data.length * rowHeight + 6;
    const labelWidth = Math.min(Math.max(...data.map(d => String(d[0]).length)) * 7 + 10, W * 0.42);
    const valueWidth = 50;
    const iw = W - labelWidth - valueWidth;
    const max = cfg.max || Math.max(...data.map(d => d[1]));

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico" });
    data.forEach((dd, i) => {
      const yy = i * rowHeight + 3;
      const width = Math.max((dd[1] / max) * iw, 2);
      svg.appendChild(txt(labelWidth - 10, yy + rowHeight / 2 + 1, dd[0], "barEtq", { "text-anchor": "end" }));
      svg.appendChild(el("rect", {
        x: labelWidth, y: yy + 3, width: width, height: rowHeight - 10,
        rx: 3, fill: cfg.color, "fill-opacity": 0.85
      }));
      svg.appendChild(txt(W - 6, yy + rowHeight / 2 + 1,
        dd[1].toLocaleString("es-ES", { maximumFractionDigits: 2 }) + " %", "barVal", { "text-anchor": "end" }));
    });
    cont.appendChild(svg);
  }

  function simpleBars(cont, cfg) {
    cont.innerHTML = "";
    const cats = cfg.categorias, vals = cfg.valores, n = cats.length;
    if (!n) { cont.innerHTML = '<p class="vacio">Sin datos.</p>'; return; }
    const W = Math.max(cont.clientWidth, 280);
    const H = cfg.alto || 220;
    const P = { t: 20, r: 14, b: 30, l: 58 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const fY = cfg.formatoY || (v => fmtPct(v, 0));

    const valid = vals.filter(v => v != null);
    let max = Math.max(0, ...valid), min = Math.min(0, ...valid);
    const margin = (max - min) * 0.12 || 0.01;
    max += margin; min -= margin;
    const y = v => P.t + ih - ((v - min) / (max - min)) * ih;
    const step = iw / n;
    const width = Math.max(8, Math.min(step - 18, 64));

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico" });
    const esc = niceScale(max, min, axisFactor(fY));
    for (let v = esc.min; v <= esc.max + 1e-9; v += esc.paso) {
      if (v < min || v > max) continue;
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: "rejilla" }));
      svg.appendChild(txt(P.l - 8, y(v) + 4, fY(v), "ejeY"));
    }
    const y0 = y(0);
    svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y0, y2: y0, class: "eje" }));

    vals.forEach((v, i) => {
      if (v == null) return;
      const cx = P.l + step * i + step / 2;
      const yv = y(v);
      const height = Math.abs(yv - y0);
      const r = Math.min(4, height / 2, width / 2);
      const above = v >= 0;
      const yTop = above ? yv : y0;
      const d = above
        ? `M${cx - width / 2} ${y0} L${cx - width / 2} ${yTop + r} Q${cx - width / 2} ${yTop} ${cx - width / 2 + r} ${yTop} L${cx + width / 2 - r} ${yTop} Q${cx + width / 2} ${yTop} ${cx + width / 2} ${yTop + r} L${cx + width / 2} ${y0} Z`
        : `M${cx - width / 2} ${y0} L${cx - width / 2} ${y0 + height - r} Q${cx - width / 2} ${y0 + height} ${cx - width / 2 + r} ${y0 + height} L${cx + width / 2 - r} ${y0 + height} Q${cx + width / 2} ${y0 + height} ${cx + width / 2} ${y0 + height - r} L${cx + width / 2} ${y0} Z`;
      svg.appendChild(el("path", { d, fill: (cfg.colores && cfg.colores[i]) || cfg.color }));
      svg.appendChild(txt(cx, above ? yv - 7 : yv + 15,
        (cfg.formatoValor || (x => formatSignedPercent(x, 1)))(v), "barValArriba", { "text-anchor": "middle" }));
      svg.appendChild(txt(cx, H - 10, cats[i], "ejeX", { "text-anchor": "middle" }));
    });
    cont.appendChild(svg);
  }

  function multiLine(cont, cfg) {
    cont.innerHTML = "";
    const W = Math.max(cont.clientWidth, 320);
    const H = cfg.alto || 320;
    const P = { t: 14, r: 14, b: 26, l: 62 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const dates = cfg.fechas, n = dates.length;
    const series = (cfg.series || []).filter(s => s.valores.some(v => v != null));
    if (!n || !series.length) { cont.innerHTML = '<p class="vacio">Sin datos.</p>'; return; }
    const fY = cfg.formatoY || (v => Math.round(v));

    let max = -Infinity, min = Infinity;
    series.forEach(s => s.valores.forEach(v => {
      if (v == null) return;
      if (v > max) max = v;
      if (v < min) min = v;
    }));
    const margin = (max - min) * 0.08 || 1;
    const esc = niceScale(max + margin, cfg.desdeCero ? 0 : min - margin, axisFactor(fY));
    const x = i => P.l + (n === 1 ? iw / 2 : i * iw / (n - 1));
    const y = v => P.t + ih - ((v - esc.min) / (esc.max - esc.min)) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico" });
    for (let v = esc.min; v <= esc.max + 1e-9; v += esc.paso) {
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: "rejilla" }));
      svg.appendChild(txt(P.l - 8, y(v) + 4, fY(v), "ejeY"));
    }
    series.forEach(s => {
      let d = "", ab = false;
      s.valores.forEach((v, i) => {
        if (v == null) { ab = false; return; }
        d += (ab ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
        ab = true;
      });
      svg.appendChild(el("path", {
        d, fill: "none", stroke: s.color,
        "stroke-width": s.destacado ? 2.75 : 1.75,
        "stroke-opacity": s.destacado ? 1 : 0.72,
        "stroke-linejoin": "round", "stroke-linecap": "round",
      }));
    });
    svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: P.t + ih, y2: P.t + ih, class: "eje" }));
    xAxisIndices(n, W < 520 ? 4 : 7).forEach(i => {
      svg.appendChild(txt(x(i), H - 8, xAxisLabel(dates, i, n), "ejeX",
        { "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" }));
    });

    const g = el("g", { class: "cursor", opacity: 0 });
    const line = el("line", { y1: P.t, y2: P.t + ih, class: "crosshair" });
    g.appendChild(line);
    const points = series.map(s => el("circle", { r: 4.5, fill: s.color, class: "punto" }));
    points.forEach(p => g.appendChild(p));
    svg.appendChild(g);
    const hitArea = el("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent", style: "cursor:crosshair" });
    svg.appendChild(hitArea);
    cont.appendChild(svg);

    const tt = createTooltip(cont);
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      const i = Math.max(0, Math.min(n - 1, Math.round((px - P.l) / (iw || 1) * (n - 1))));
      g.setAttribute("opacity", 1);
      line.setAttribute("x1", x(i)); line.setAttribute("x2", x(i));
      const order = series.map((s, k) => ({ s, k, v: s.valores[i] }))
        .filter(o => o.v != null).sort((a, b) => b.v - a.v);
      series.forEach((s, k) => {
        const v = s.valores[i];
        points[k].setAttribute("opacity", v == null ? 0 : 1);
        if (v != null) { points[k].setAttribute("cx", x(i)); points[k].setAttribute("cy", y(v)); }
      });
      tt.innerHTML = `<b>${formatDate(dates[i])}</b><table>` + order.map(o =>
        `<tr${o.s.destacado ? ' class="sep"' : ""}><td><i style="background:${o.s.color}"></i>${o.s.nombre}</td>
         <td>${(cfg.formatoValor || (v => v.toFixed(1)))(o.v)}</td></tr>`).join("") + "</table>";
      tt.classList.add("on");
      positionTooltip(tt, cont, x(i) * (r.width / W), ev.clientY - r.top);
    }
    hitArea.addEventListener("pointermove", move);
    hitArea.addEventListener("pointerdown", move);
    hitArea.addEventListener("pointerleave", () => { g.setAttribute("opacity", 0); tt.classList.remove("on"); });
  }

  function groupedBars(cont, cfg) {
    cont.innerHTML = "";
    const cats = cfg.categorias, series = cfg.series, n = cats.length, m = series.length;
    if (!n || !m) { cont.innerHTML = '<p class="vacio">Sin datos.</p>'; return; }
    const W = Math.max(cont.clientWidth, 300);
    const H = cfg.alto || 240;
    const P = { t: 16, r: 14, b: 30, l: 58 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const fY = cfg.formatoY || formatShortEur;

    let max = 0, min = 0;
    series.forEach(s => s.valores.forEach(v => {
      if (v == null) return;
      if (v > max) max = v;
      if (v < min) min = v;
    }));
    const esc = niceScale(max, min, axisFactor(fY));
    const y = v => P.t + ih - ((v - esc.min) / (esc.max - esc.min)) * ih;
    const step = iw / n;
    const gap = 3;
    const width = Math.max(3, (Math.min(step - 8, 54) - gap * (m - 1)) / m);

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "grafico" });
    for (let v = esc.min; v <= esc.max + 1e-9; v += esc.paso) {
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: "rejilla" }));
      svg.appendChild(txt(P.l - 8, y(v) + 4, fY(v), "ejeY"));
    }
    const y0 = y(0);
    const groupWidth = width * m + gap * (m - 1);

    for (let i = 0; i < n; i++) {
      const x0 = P.l + step * i + (step - groupWidth) / 2;
      series.forEach((s, k) => {
        const v = s.valores[i];
        if (v == null || v === 0) return;
        const bx = x0 + k * (width + gap);
        const yv = y(v);
        const height = Math.abs(yv - y0);
        const r = Math.min(4, height / 2, width / 2);
        const arr = v >= 0;
        const d = arr
          ? `M${bx} ${y0} L${bx} ${yv + r} Q${bx} ${yv} ${bx + r} ${yv} L${bx + width - r} ${yv} Q${bx + width} ${yv} ${bx + width} ${yv + r} L${bx + width} ${y0} Z`
          : `M${bx} ${y0} L${bx} ${yv - r} Q${bx} ${yv} ${bx + r} ${yv} L${bx + width - r} ${yv} Q${bx + width} ${yv} ${bx + width} ${yv - r} L${bx + width} ${y0} Z`;
        svg.appendChild(el("path", { d, fill: s.color }));
      });
    }
    svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: y0, y2: y0, class: "eje" }));
    const cada = Math.max(1, Math.ceil(n / (W < 520 ? 5 : 12)));
    cats.forEach((c, i) => {
      if (i % cada) return;
      svg.appendChild(txt(P.l + step * i + step / 2, H - 10,
        cfg.formatoCat ? cfg.formatoCat(c) : c, "ejeX", { "text-anchor": "middle" }));
    });

    const highlight = el("rect", { class: "resalte", y: P.t, height: ih, width: step, opacity: 0 });
    svg.insertBefore(highlight, svg.firstChild);
    const hitArea = el("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent" });
    svg.appendChild(hitArea);
    cont.appendChild(svg);

    const tt = createTooltip(cont);
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      const i = Math.max(0, Math.min(n - 1, Math.floor((px - P.l) / step)));
      highlight.setAttribute("x", P.l + step * i);
      highlight.setAttribute("opacity", 1);
      const fV = cfg.formatoValor || fmtEur;
      const rows = series.map(s => s.valores[i] == null ? "" :
        `<tr><td><i style="background:${s.color}"></i>${s.nombre}</td><td>${fV(s.valores[i])}</td></tr>`).join("");
      const total = series.reduce((a, s) => a + (s.valores[i] || 0), 0);
      tt.innerHTML = `<b>${cfg.formatoCat ? cfg.formatoCat(cats[i]) : cats[i]}</b>` +
        `<div class="ttTotal">${fV(total)}</div><table>${rows}</table>`;
      tt.classList.add("on");
      positionTooltip(tt, cont, (P.l + step * i + step / 2) * (r.width / W), ev.clientY - r.top);
    }
    hitArea.addEventListener("pointermove", move);
    hitArea.addEventListener("pointerdown", move);
    hitArea.addEventListener("pointerleave", () => { tt.classList.remove("on"); highlight.setAttribute("opacity", 0); });
  }

  global.G = {
    fmtEur, fmtEurCorto: formatShortEur, fmtPct, fmtPctSigno: formatSignedPercent, fmtEurSigno: formatSignedEur, ponMoneda: setCurrency, moneda: CURRENCY, simboloMoneda: currencySymbol, dinero: cash, fmtFecha: formatDate, fmtFechaCorta: formatShortDate, fmtMes: formatMonth, nfNum: unitsFormat,
    areaApilada: stackedArea, lineaConEventos: lineWithEvents, barrasApiladas: stackedBars, donut, mini, escalaBonita: niceScale, css,
    barrasHorizontales: horizontalBars, barrasSimples: simpleBars, multiLinea: multiLine, barrasAgrupadas: groupedBars
  };
})(window);
