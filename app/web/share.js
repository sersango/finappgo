(function (root, create) {
  const M = create();
  if (typeof module === "object" && module.exports) module.exports = M;
  else root.Compartir = M;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FORMATS = {
    mini: { w: 1080, h: 1080, nombre: "Mini" },
    resumen: { w: 1080, h: 1350, nombre: "Resumen" },
    story: { w: 1080, h: 1920, nombre: "Story" },
  };

  const THEMES = {
    oscuro: {
      nombre: "Oscuro", fondo: "#0e0e0d", tinta: "#ffffff", sub: "#a8a69c", linea: "#2c2c29", caja: "#181816",
      pista: "#232320", sube: "#3fcf7e", baja: "#f28b82", curva: "#3fcf7e", aporte: "#3987e5", aporteTxt: "#6aa6f0",
      logoFondo: "#2a78d6", logoTinta: "#ffffff", borde: null,
    },
    claro: {
      nombre: "Claro", fondo: "#f7f6f1", tinta: "#121211", sub: "#5b5a55", linea: "#dedcd3", caja: "#ffffff",
      pista: "#e8e6de", sube: "#0b7a3b", baja: "#c43d35", curva: "#0b7a3b", aporte: "#2a78d6", aporteTxt: "#1d5fb4",
      logoFondo: "#2a78d6", logoTinta: "#ffffff", borde: "#dedcd3",
    },
    azul: {
      nombre: "Azul", fondo: "#1d5fb4", tinta: "#ffffff", sub: "#dbe7f7", linea: "rgba(255,255,255,0.28)",
      caja: "rgba(255,255,255,0.10)", pista: "rgba(255,255,255,0.18)", sube: "#ffffff", baja: "#ffd0cc",
      curva: "#ffffff", aporte: "#ffd166", aporteTxt: "#ffd166", logoFondo: "#ffffff", logoTinta: "#1d5fb4", borde: null,
    },
  };
  let T = THEMES.oscuro;
  const FONT = '"Segoe UI Variable Display", "Segoe UI", "SF Pro Display", "Helvetica Neue", system-ui, sans-serif';
  const MONO = '"Cascadia Mono", "SF Mono", Consolas, "Liberation Mono", ui-monospace, monospace';

  const QR = {
    repo: { n: 29, texto: "Descárgala", d: "M0 0h7v1h-7zM8 0h2v1h-2zM12 0h1v1h-1zM14 0h1v1h-1zM22 0h7v1h-7zM0 1h1v1h-1zM6 1h1v1h-1zM9 1h2v1h-2zM12 1h1v1h-1zM16 1h5v1h-5zM22 1h1v1h-1zM28 1h1v1h-1zM0 2h1v1h-1zM2 2h3v1h-3zM6 2h1v1h-1zM9 2h2v1h-2zM13 2h1v1h-1zM17 2h3v1h-3zM22 2h1v1h-1zM24 2h3v1h-3zM28 2h1v1h-1zM0 3h1v1h-1zM2 3h3v1h-3zM6 3h1v1h-1zM8 3h1v1h-1zM10 3h2v1h-2zM14 3h1v1h-1zM16 3h1v1h-1zM18 3h1v1h-1zM20 3h1v1h-1zM22 3h1v1h-1zM24 3h3v1h-3zM28 3h1v1h-1zM0 4h1v1h-1zM2 4h3v1h-3zM6 4h1v1h-1zM8 4h9v1h-9zM18 4h1v1h-1zM22 4h1v1h-1zM24 4h3v1h-3zM28 4h1v1h-1zM0 5h1v1h-1zM6 5h1v1h-1zM8 5h2v1h-2zM12 5h3v1h-3zM16 5h1v1h-1zM18 5h2v1h-2zM22 5h1v1h-1zM28 5h1v1h-1zM0 6h7v1h-7zM8 6h1v1h-1zM10 6h1v1h-1zM12 6h1v1h-1zM14 6h1v1h-1zM16 6h1v1h-1zM18 6h1v1h-1zM20 6h1v1h-1zM22 6h7v1h-7zM8 7h1v1h-1zM10 7h1v1h-1zM14 7h1v1h-1zM17 7h2v1h-2zM20 7h1v1h-1zM0 8h1v1h-1zM4 8h1v1h-1zM6 8h6v1h-6zM13 8h2v1h-2zM17 8h1v1h-1zM19 8h7v1h-7zM28 8h1v1h-1zM3 9h2v1h-2zM7 9h1v1h-1zM9 9h2v1h-2zM15 9h4v1h-4zM21 9h8v1h-8zM0 10h2v1h-2zM6 10h2v1h-2zM9 10h1v1h-1zM12 10h5v1h-5zM18 10h1v1h-1zM20 10h1v1h-1zM22 10h2v1h-2zM28 10h1v1h-1zM0 11h2v1h-2zM4 11h2v1h-2zM8 11h4v1h-4zM13 11h1v1h-1zM15 11h3v1h-3zM19 11h1v1h-1zM22 11h4v1h-4zM27 11h2v1h-2zM0 12h2v1h-2zM4 12h6v1h-6zM11 12h1v1h-1zM13 12h1v1h-1zM16 12h2v1h-2zM19 12h1v1h-1zM21 12h1v1h-1zM27 12h1v1h-1zM0 13h6v1h-6zM11 13h6v1h-6zM18 13h1v1h-1zM22 13h7v1h-7zM0 14h1v1h-1zM2 14h2v1h-2zM6 14h3v1h-3zM10 14h2v1h-2zM15 14h2v1h-2zM18 14h1v1h-1zM20 14h4v1h-4zM25 14h2v1h-2zM28 14h1v1h-1zM1 15h1v1h-1zM3 15h2v1h-2zM8 15h2v1h-2zM11 15h2v1h-2zM14 15h8v1h-8zM27 15h2v1h-2zM3 16h2v1h-2zM6 16h1v1h-1zM9 16h2v1h-2zM12 16h3v1h-3zM16 16h2v1h-2zM20 16h1v1h-1zM23 16h1v1h-1zM27 16h1v1h-1zM0 17h2v1h-2zM5 17h1v1h-1zM9 17h1v1h-1zM11 17h2v1h-2zM15 17h4v1h-4zM20 17h1v1h-1zM22 17h4v1h-4zM27 17h2v1h-2zM2 18h1v1h-1zM4 18h1v1h-1zM6 18h2v1h-2zM11 18h5v1h-5zM18 18h1v1h-1zM20 18h1v1h-1zM26 18h1v1h-1zM28 18h1v1h-1zM3 19h1v1h-1zM5 19h1v1h-1zM7 19h1v1h-1zM9 19h1v1h-1zM12 19h2v1h-2zM15 19h4v1h-4zM20 19h2v1h-2zM23 19h2v1h-2zM27 19h2v1h-2zM0 20h3v1h-3zM6 20h8v1h-8zM17 20h2v1h-2zM20 20h6v1h-6zM28 20h1v1h-1zM8 21h1v1h-1zM10 21h11v1h-11zM24 21h1v1h-1zM28 21h1v1h-1zM0 22h7v1h-7zM8 22h1v1h-1zM11 22h1v1h-1zM15 22h2v1h-2zM18 22h3v1h-3zM22 22h1v1h-1zM24 22h3v1h-3zM28 22h1v1h-1zM0 23h1v1h-1zM6 23h1v1h-1zM11 23h1v1h-1zM14 23h1v1h-1zM17 23h4v1h-4zM24 23h1v1h-1zM27 23h2v1h-2zM0 24h1v1h-1zM2 24h3v1h-3zM6 24h1v1h-1zM8 24h1v1h-1zM11 24h5v1h-5zM17 24h1v1h-1zM19 24h7v1h-7zM27 24h1v1h-1zM0 25h1v1h-1zM2 25h3v1h-3zM6 25h1v1h-1zM9 25h2v1h-2zM12 25h1v1h-1zM15 25h2v1h-2zM18 25h1v1h-1zM21 25h1v1h-1zM28 25h1v1h-1zM0 26h1v1h-1zM2 26h3v1h-3zM6 26h1v1h-1zM9 26h1v1h-1zM13 26h1v1h-1zM15 26h1v1h-1zM18 26h4v1h-4zM25 26h4v1h-4zM0 27h1v1h-1zM6 27h1v1h-1zM9 27h4v1h-4zM14 27h4v1h-4zM20 27h3v1h-3zM24 27h2v1h-2zM27 27h2v1h-2zM0 28h7v1h-7zM8 28h1v1h-1zM11 28h2v1h-2zM14 28h2v1h-2zM17 28h1v1h-1zM20 28h6v1h-6zM27 28h1v1h-1z" },
  };

  const pct = (v, dec = 1) => v == null ? "—"
    : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(dec).replace(".", ",") + " %";
  const eur = (v, sign = false) => v == null ? "—"
    : (sign && v > 0 ? "+" : v < 0 ? "−" : "") +
      Math.abs(Math.round(v)).toLocaleString("es-ES", { maximumFractionDigits: 0, useGrouping: true }) + " €";
  const color = v => v != null && v < 0 ? T.baja : T.sube;

  function text(ctx, s, x, y, o) {
    ctx.save();
    ctx.font = `${o.peso || 400} ${o.tam}px ${o.mono ? MONO : FONT}`;
    ctx.fillStyle = o.color || T.tinta;
    ctx.textAlign = o.alin || "left";
    ctx.textBaseline = "alphabetic";
    if ("letterSpacing" in ctx) ctx.letterSpacing = (o.esp || 0) + "px";
    let tam = o.tam;
    if (o.max) {
      while (tam > 10 && ctx.measureText(s).width > o.max) {
        tam = Math.floor(tam * 0.94);
        ctx.font = `${o.peso || 400} ${tam}px ${o.mono ? MONO : FONT}`;
      }
    }
    ctx.fillText(s, x, y);
    const width = ctx.measureText(s).width;
    ctx.restore();
    return width;
  }

  function box(ctx, x, y, w, h, r, fill, border, thickness) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (border) { ctx.strokeStyle = border; ctx.lineWidth = thickness || 2; ctx.stroke(); }
  }

  function line(ctx, x1, y1, x2, y2, col, thickness) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = col;
    ctx.lineWidth = thickness || 2;
    ctx.stroke();
  }

  function logo(ctx, x, y, tam, background, ink) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(tam / 512, tam / 512);
    box(ctx, 0, 0, 512, 512, 112, background);
    ctx.beginPath();
    ctx.arc(256, 256, 132, 0, Math.PI * 2);
    ctx.strokeStyle = ink;
    ctx.lineWidth = 34;
    ctx.stroke();
    ctx.fillStyle = ink;
    ctx.fill(new Path2D("M256 78l22 40h-44z M256 434l22-40h-44z M78 256l40-22v44z M434 256l-40-22v44z"));
    ctx.fill(new Path2D("M176 336L236 236L336 176L276 276Z"));
    ctx.beginPath();
    ctx.arc(256, 256, 17, 0, Math.PI * 2);
    ctx.fillStyle = background;
    ctx.fill();
    ctx.restore();
  }

  function qr(ctx, x, y, tam, selected, ink, border) {
    const q = QR[selected] || QR.repo;
    box(ctx, x, y, tam, tam, tam * 0.11, "#ffffff", border, 2);
    const margin = tam * 0.09, step = (tam - 2 * margin) / q.n;
    ctx.save();
    ctx.translate(x + margin, y + margin);
    ctx.scale(step, step);
    ctx.fillStyle = ink || "#0e0e0d";
    ctx.fill(new Path2D(q.d));
    ctx.restore();
  }

  function curve(ctx, vals, x, y, w, h, col, thickness) {
    if (!vals || vals.length < 2) return;
    const min = Math.min(...vals), max = Math.max(...vals), pad = thickness * 2;
    const px = i => x + pad + i * (w - 2 * pad) / (vals.length - 1);
    const py = v => y + pad + (h - 2 * pad) * (1 - (v - min) / ((max - min) || 1));
    ctx.beginPath();
    vals.forEach((v, i) => (i ? ctx.lineTo(px(i), py(v)) : ctx.moveTo(px(i), py(v))));
    ctx.save();
    ctx.lineTo(px(vals.length - 1), y + h);
    ctx.lineTo(px(0), y + h);
    ctx.closePath();
    ctx.globalAlpha = 0.13;
    ctx.fillStyle = col;
    ctx.fill();
    ctx.restore();
    ctx.beginPath();
    vals.forEach((v, i) => (i ? ctx.lineTo(px(i), py(v)) : ctx.moveTo(px(i), py(v))));
    ctx.strokeStyle = col;
    ctx.lineWidth = thickness;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(px(vals.length - 1), py(vals[vals.length - 1]), thickness * 2, 0, Math.PI * 2);
    ctx.fillStyle = col;
    ctx.fill();
  }

  function lock(ctx, x, y, col) {
    ctx.save();
    ctx.strokeStyle = col;
    ctx.lineWidth = 3;
    box(ctx, x, y + 16, 30, 22, 4, null, col, 3);
    ctx.beginPath();
    ctx.moveTo(x + 7, y + 16);
    ctx.lineTo(x + 7, y + 10);
    ctx.arc(x + 15, y + 10, 8, Math.PI, 0);
    ctx.lineTo(x + 23, y + 16);
    ctx.stroke();
    ctx.restore();
  }

  const monthLabel = d => d.enCurso ? "EN LO QUE VA DE MES" : "MI CARTERA ESTE MES";
  const yearLine = d => d.anoPct == null ? "" : d.ultimo
    ? `${pct(d.anoPct)} en lo que va de ${d.ano}`
    : `${pct(d.anoPct)} en ${d.ano}, hasta ${d.nombreMes}`;

  function header(ctx, x, y, logoSize) {
    logo(ctx, x, y, logoSize, T.logoFondo, T.logoTinta);
    text(ctx, "FINAPPGO", x + logoSize + 20, y + logoSize / 2 + logoSize * 0.17,
      { tam: Math.round(logoSize * 0.48), peso: 800, esp: 3, color: T.tinta });
  }

  function mini(ctx, d, o) {
    ctx.fillStyle = T.fondo;
    ctx.fillRect(0, 0, 1080, 1080);
    header(ctx, 96, 88, 72);
    ctx.save();
    ctx.font = `500 26px ${MONO}`;
    const wPill = ctx.measureText(d.etiqueta).width + 48;
    ctx.restore();
    box(ctx, 984 - wPill, 96, wPill, 56, 28, null, T.linea, 2);
    text(ctx, d.etiqueta, 984 - wPill / 2, 133, { tam: 26, peso: 500, mono: true, color: T.sub, alin: "center" });

    text(ctx, monthLabel(d), 96, 330, { tam: 28, peso: 500, mono: true, esp: 4, color: T.sub });
    text(ctx, pct(d.rentMes), 92, 560, { tam: 268, peso: 800, esp: -10, color: color(d.rentMes), max: 888 });
    curve(ctx, d.serieAno, 96, 600, 888, 140, T.curva, 5);
    text(ctx, yearLine(d), 96, 800, { tam: 38, peso: 500, max: 888 });

    line(ctx, 96, 850, 984, 850, T.linea, 2);
    text(ctx, "Hecho con FinAppGo", 96, 920, { tam: 36, peso: 700 });
    text(ctx, "Gratis y de código abierto.", 96, 966, { tam: 23, mono: true, color: T.sub });
    text(ctx, "Tus datos no salen de tu ordenador.", 96, 998, { tam: 23, mono: true, color: T.sub });
    qr(ctx, 834, 868, 150, o.qr, null, T.borde);
    text(ctx, (QR[o.qr] || QR.repo).texto, 909, 1050, { tam: 20, mono: true, color: T.sub, alin: "center" });
  }

  function summary(ctx, d, o) {
    ctx.fillStyle = T.fondo;
    ctx.fillRect(0, 0, 1080, 1350);
    header(ctx, 80, 80, 60);
    text(ctx, "Mi mes · " + d.etiqueta, 1000, 119, { tam: 24, peso: 500, mono: true, color: T.sub, alin: "right" });

    text(ctx, d.enCurso ? "EN LO QUE VA DE MES" : "ESTE MES", 80, 230, { tam: 24, peso: 500, mono: true, esp: 4, color: T.sub });
    text(ctx, pct(d.rentMes), 76, 400, { tam: 196, peso: 800, esp: -8, color: color(d.rentMes), max: o.euros ? 560 : 640 });
    text(ctx, "Rentabilidad de la cartera, sin contar lo que aporté", 80, 444, { tam: 20, mono: true, color: T.sub });
    if (o.euros) {
      text(ctx, "Patrimonio", 1000, 280, { tam: 22, mono: true, color: T.sub, alin: "right" });
      text(ctx, eur(d.patrimonio), 1000, 350, { tam: 64, peso: 700, alin: "right", max: 380 });
      text(ctx, eur(d.cambioEur, true) + " este mes", 1000, 392, { tam: 26, color: color(d.cambioEur), alin: "right" });
    } else {
      lock(ctx, 970, 270, T.sub);
      text(ctx, "Importes ocultos", 1000, 352, { tam: 28, peso: 700, alin: "right" });
      text(ctx, "Comparto cómo voy,", 1000, 386, { tam: 20, mono: true, color: T.sub, alin: "right" });
      text(ctx, "no cuánto tengo.", 1000, 412, { tam: 20, mono: true, color: T.sub, alin: "right" });
    }

    text(ctx, "Mi año, mes a mes", 80, 510, { tam: 22, peso: 500, mono: true, color: T.sub });
    curve(ctx, d.serieAno, 80, 525, 920, 180, T.curva, 5);
    line(ctx, 80, 706, 1000, 706, T.linea, 2);
    text(ctx, d.etqIni, 80, 740, { tam: 20, mono: true, color: T.sub });
    text(ctx, d.etqFin, 1000, 740, { tam: 20, mono: true, color: T.sub, alin: "right" });

    const kpis = [
      ["En el año", pct(d.anoPct), color(d.anoPct)],
      d.tir != null ? ["TIR anual", pct(d.tir), T.tinta] : ["Desde el inicio", pct(d.desdeInicio), T.tinta],
      d.racha >= 1 ? ["Aportando", d.racha + (d.racha === 1 ? " mes" : " meses"), T.tinta] : ["Desde el inicio", pct(d.desdeInicio), T.tinta],
      ["Mi patrimonio", pct(d.crecimiento), color(d.crecimiento)],
    ];
    if (kpis[1][0] === kpis[2][0]) kpis[2] = ["Este mes", pct(d.rentMes), color(d.rentMes)];
    kpis.forEach(([etq, value, col], i) => {
      const x = 80 + i * 234;
      box(ctx, x, 775, 218, 140, 22, T.caja, T.linea, 2);
      text(ctx, etq, x + 22, 822, { tam: 19, mono: true, color: T.sub, max: 180 });
      text(ctx, value, x + 22, 884, { tam: 42, peso: 700, color: col, max: 176 });
    });

    text(ctx, "De dónde sale el cambio del mes", 80, 975, { tam: 22, peso: 500, mono: true, color: T.sub });
    const a = Math.abs(d.aportadoEur || 0), m = Math.abs(d.mercadoEur || 0), total = a + m;
    box(ctx, 80, 995, 920, 30, 15, T.pista);
    if (total > 0) {
      const wa = 920 * a / total;
      if (wa > 1) box(ctx, 80, 995, Math.max(wa - 2, 30), 30, 15, T.aporte);
      if (920 - wa > 1) box(ctx, 80 + wa + 2, 995, Math.max(920 - wa - 2, 30), 30, 15, color(d.mercadoEur));
    }
    const vA = o.euros ? eur(d.aportadoEur, true) : pct(d.porAportado);
    const vM = o.euros ? eur(d.mercadoEur, true) : pct(d.porMercado);
    const wA = text(ctx, "Lo pusiste tú", 80, 1065, { tam: 27, peso: 700, color: T.aporteTxt });
    text(ctx, " · " + vA, 80 + wA, 1065, { tam: 27 });
    ctx.save();
    ctx.font = `400 27px ${FONT}`;
    const wVM = ctx.measureText(" · " + vM).width;
    ctx.restore();
    text(ctx, " · " + vM, 1000, 1065, { tam: 27, alin: "right" });
    text(ctx, d.mercadoEur < 0 ? "Lo restó el mercado" : "Lo puso el mercado", 1000 - wVM, 1065,
      { tam: 27, peso: 700, color: color(d.mercadoEur), alin: "right" });

    line(ctx, 80, 1105, 1000, 1105, T.linea, 2);
    text(ctx, "¿Quieres el tuyo? Hazte tu FinAppGo", 80, 1170, { tam: 34, peso: 700, max: 740 });
    text(ctx, "Gratis y de código abierto.", 80, 1210, { tam: 21, mono: true, color: T.sub });
    text(ctx, "Tus datos no salen de tu ordenador.", 80, 1240, { tam: 21, mono: true, color: T.sub });
    qr(ctx, 860, 1125, 140, o.qr, null, T.borde);
  }

  function story(ctx, d, o) {
    ctx.fillStyle = T.fondo;
    ctx.fillRect(0, 0, 1080, 1920);
    header(ctx, 80, 150, 76);
    text(ctx, d.etiqueta, 1000, 198, { tam: 28, peso: 500, mono: true, color: T.sub, alin: "right" });

    text(ctx, monthLabel(d), 80, 420, { tam: 32, peso: 500, mono: true, esp: 4, color: T.sub });
    text(ctx, pct(d.rentMes), 72, 700, { tam: 330, peso: 800, esp: -14, max: 930, color: color(d.rentMes) });
    curve(ctx, d.serieAno, 80, 760, 920, 260, T.curva, 7);

    const rows = [];
    if (d.anoPct != null) rows.push([pct(d.anoPct), d.ultimo ? "en lo que va de año" : `en ${d.ano}, hasta ${d.nombreMes}`]);
    if (d.racha >= 2) rows.push([String(d.racha), "meses seguidos invirtiendo"]);
    else if (d.desdeInicio != null) rows.push([pct(d.desdeInicio), "desde que empecé"]);
    rows.slice(0, 2).forEach(([large, small], i) => {
      const y = 1110 + i * 130;
      line(ctx, 80, y, 1000, y, T.linea, 3);
      const w = text(ctx, large, 80, y + 90, { tam: 76, peso: 800 });
      text(ctx, small, 80 + w + 24, y + 90, { tam: 38, peso: 500, color: T.sub, max: 920 - w - 24 });
    });

    box(ctx, 80, 1420, 920, 330, 40, "#ffffff", T.borde, 2);
    qr(ctx, 110, 1460, 250, o.qr, "#121211");
    text(ctx, "¿Quieres el tuyo?", 392, 1530, { tam: 48, peso: 800, color: "#121211", max: 580 });
    text(ctx, "FinAppGo es gratis y de código", 392, 1585, { tam: 30, color: "#3f3e3a" });
    text(ctx, "abierto. Escanea y llévatelo.", 392, 1625, { tam: 30, color: "#3f3e3a" });
    text(ctx, "Tus datos no salen de tu ordenador.", 392, 1690, { tam: 22, mono: true, color: "#5b5a55", max: 580 });
  }

  const DRAWING = { mini, resumen: summary, story };

  function draw(ctx, format, data, options) {
    const o = { euros: false, qr: "repo", tema: "oscuro", ...(options || {}) };
    T = THEMES[o.tema] || THEMES.oscuro;
    (DRAWING[format] || mini)(ctx, data, o);
  }

  function open() {
    const D = window.DATOS, C = window.Calculos;
    const rm = (D && D.resumenMensual) || [];
    if (!rm.length || !C) { alert("Todavía no hay ningún mes que compartir."); return; }
    const lee = (k, def) => { try { return localStorage.getItem(k) || def; } catch (e) { return def; } };
    const save = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {  } };
    const sel = document.getElementById("mesSel");
    const op = {
      formato: lee("finappgo.compartir.formato", "resumen"),
      qr: "repo",
      tema: lee("finappgo.compartir.tema", "oscuro"),
      euros: false,
      mes: sel && sel.value !== "" ? +sel.value : rm.length - 1,
    };
    if (!FORMATS[op.formato]) op.formato = "resumen";
    if (!THEMES[op.tema]) op.tema = "oscuro";
    const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
    const months = rm.map((r, i) => ({ i, etq: C.resumenParaCompartir(D, i).etiqueta })).reverse().slice(0, 36);
    const dlg = document.getElementById("modal");
    dlg.innerHTML = `<form class="mForm cmpForm" novalidate>
      <header><h2>Compartir mi mes</h2><button type="button" class="x" data-cerrar aria-label="Cerrar">×</button></header>
      <div class="mCuerpo">
        <div class="cmpOpciones">
          <div class="segm" id="cmpFormato" role="group" aria-label="Formato de la imagen">
            ${Object.entries(FORMATS).map(([k, f]) => `<button type="button" data-f="${k}">${f.nombre}</button>`).join("")}
          </div>
          <div class="segm" id="cmpTema" role="group" aria-label="Tema de la imagen">
            ${Object.entries(THEMES).map(([k, t]) => `<button type="button" data-t="${k}">${t.nombre}</button>`).join("")}
          </div>
          <select id="cmpMes" aria-label="Mes">${months.map(m => `<option value="${m.i}">${esc(m.etq)}</option>`).join("")}</select>
          <label class="cmpEuros"><input type="checkbox" id="cmpEuros"> Mostrar euros</label>
        </div>
        <canvas id="cmpLienzo" class="cmpLienzo" role="img" aria-label="Vista previa de la imagen"></canvas>
        <p class="ayuda" id="cmpNota"></p>
      </div>
      <footer><button type="button" class="btn" id="cmpCopiar">Copiar imagen</button>
        <button type="button" class="btn prim" id="cmpBajar">Descargar imagen</button></footer></form>`;
    const $ = s => dlg.querySelector(s);
    dlg.querySelectorAll("[data-cerrar]").forEach(b => { b.onclick = () => dlg.close(); });
    const canvas = $("#cmpLienzo");
    const render = () => {
      const f = FORMATS[op.formato];
      canvas.width = f.w;
      canvas.height = f.h;
      const data = C.resumenParaCompartir(D, op.mes);
      draw(canvas.getContext("2d"), op.formato, data, op);
      dlg.querySelectorAll("#cmpFormato button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.f === op.formato)));
      dlg.querySelectorAll("#cmpTema button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.t === op.tema)));
      $(".cmpEuros").hidden = op.formato !== "resumen";
      $("#cmpNota").textContent = op.formato === "resumen" && op.euros
        ? "Con euros: se ve tu patrimonio y cuánto has aportado. Revísala antes de publicarla."
        : "Solo porcentajes: nadie sabe cuánto tienes. El QR lleva a la página de FinAppGo para descargarlo.";
    };
    $("#cmpMes").value = String(op.mes);
    dlg.querySelectorAll("#cmpFormato button").forEach(b => {
      b.onclick = () => { op.formato = b.dataset.f; save("finappgo.compartir.formato", op.formato); render(); };
    });
    dlg.querySelectorAll("#cmpTema button").forEach(b => {
      b.onclick = () => { op.tema = b.dataset.t; save("finappgo.compartir.tema", op.tema); render(); };
    });
    $("#cmpMes").onchange = e => { op.mes = +e.target.value; render(); };
    $("#cmpEuros").onchange = e => { op.euros = e.target.checked; render(); };
    const name = () => `finappgo-${rm[op.mes].mes}-${op.formato}-${op.tema}.png`;
    $("#cmpBajar").onclick = () => canvas.toBlob(b => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = name();
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
    }, "image/png");
    $("#cmpCopiar").onclick = () => canvas.toBlob(async b => {
      const button = $("#cmpCopiar");
      try {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": b })]);
        button.textContent = "¡Copiada!";
        setTimeout(() => { button.textContent = "Copiar imagen"; }, 1800);
      } catch (e) {
        alert("Tu navegador no deja copiar imágenes. Descárgala con «Descargar imagen».");
      }
    }, "image/png");
    render();
    dlg.classList.add("cmpModal");
    dlg.addEventListener("close", () => dlg.classList.remove("cmpModal"), { once: true });
    dlg.showModal();
  }

  function mount() {
    if (typeof document === "undefined") return;
    const bar = document.querySelector("#tab-mes .mesBarra");
    if (!bar || document.getElementById("btnCompartir")) return;
    const D = window.DATOS;
    if (!D || D.modo === "demo" || !(D.resumenMensual || []).length) return;
    const b = document.createElement("button");
    b.className = "btn prim";
    b.id = "btnCompartir";
    b.type = "button";
    b.textContent = "Compartir mi mes";
    b.title = "Una imagen de tu mes para redes, con solo porcentajes";
    b.onclick = open;
    bar.appendChild(b);
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
    else mount();
  }

  return { FORMATOS: FORMATS, TEMAS: THEMES, QR, dibuja: draw, abrir: open, pct, eur };
});
