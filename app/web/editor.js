(function () {
  "use strict";

  const $ = s => document.querySelector(s);
  const D = window.DATOS;
  const SOLO_SALDO = ["efectivo", "deuda"];
  const E = { cfg: null, modo: "demo", tipos: {}, fuentes: {}, tiposMov: {}, vista: "productos", filtro: "todos" };

  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const eur = v => v == null ? "—" : Number(v).toLocaleString("es-ES", { style: "currency", currency: "EUR" });
  const num = (v, d = 4) => v == null ? "—" : Number(v).toLocaleString("es-ES", { maximumFractionDigits: d });
  const date = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "—";
  const hoy = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const readNumber = t => {
    t = String(t || "").replace(/[€\s]/g, "");

    if (t.includes(",") || /^-?\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
    return parseFloat(t);
  };
  const name = p => p ? (p.corto || p.nombre) : "¿?";
  const prod = id => E.cfg.productos.find(p => p.id === id);
  const balanceOnly = p => SOLO_SALDO.includes(p.tipo);

  const withMovements = p => !balanceOnly(p) || p.tipo === "efectivo";
  const manual = p => p.fuente === "manual" || balanceOnly(p);
  const options = (obj, sel) => Object.entries(obj)
    .map(([k, v]) => `<option value="${esc(k)}"${k === sel ? " selected" : ""}>${esc(v)}</option>`).join("");
  const preferences = {
    lee(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    guarda(k, v) { try { localStorage.setItem(k, v); } catch (e) {  } },
  };
  E.vista = new URLSearchParams(location.search).get("vista") || preferences.lee("patrimonio.editor") || "productos";

  const profileHeader = () => (window.PERFILES && window.PERFILES.activo ? { "X-FinAppGo-Perfil": window.PERFILES.activo } : {});

  document.addEventListener("visibilitychange", async () => {
    if (document.hidden || !window.PERFILES) return;
    try {
      const r = await fetch("api/perfiles", { cache: "no-store" });
      const j = await r.json();
      if (j && j.activo && j.activo !== window.PERFILES.activo) location.reload();
    } catch (e) {  }
  });

  async function api(method, url, body) {
    const r = await fetch(url, {
      method: method, headers: { "Content-Type": "application/json", ...profileHeader() },
      body: body ? JSON.stringify(body) : undefined,
    });
    let j = {};
    try { j = await r.json(); } catch (e) {  }
    if (r.status === 409 && j.perfilCambiado) { alert(j.errores.join("\n")); location.reload(); throw new Error(j.errores[0]); }
    if (!r.ok || j.ok === false) throw new Error((j.errores || [j.error || "Algo ha fallado. ¿Sigue abierta la ventana negra de la app?"]).join("\n"));
    return j;
  }
  async function load() {
    const j = await api("GET", "api/cartera");
    Object.assign(E, { cfg: j.cartera, modo: j.modo, tipos: j.tipos, fuentes: j.fuentes, tiposMov: j.tiposMovimiento });
  }
  async function save(collection, data) {
    const j = await api("POST", "api/" + collection, data);
    E.cfg = j.cartera;
    COP.lista = null;
    window.EDITOR_SUCIO = true;
    notify(j.avisos);
    return j.item;
  }
  async function remove(collection, id) {
    const j = await api("DELETE", `api/${collection}/${encodeURIComponent(id)}`);
    E.cfg = j.cartera;
    COP.lista = null;
    window.EDITOR_SUCIO = true;
  }
  function notify(warnings) {
    const el = $("#edAvisos");
    if (el) el.innerHTML = (warnings || []).map(a => `<div class="av"><span>⚠</span><span>${esc(a)}</span></div>`).join("");
  }

  function openModal(title, body, onSave, buttonLabel = "Guardar") {
    const dlg = $("#modal");
    dlg.innerHTML = `<form class="mForm" novalidate>
      <header><h2>${title}</h2><button type="button" class="x" data-cerrar aria-label="Cerrar">×</button></header>
      <div class="mCuerpo">${body}</div>
      <div class="mErr" hidden></div>
      <footer><button type="button" class="btn" data-cerrar>Cancelar</button>
        <button type="submit" class="btn prim">${buttonLabel}</button></footer></form>`;
    const f = dlg.querySelector("form");
    dlg.querySelectorAll("[data-cerrar]").forEach(b => { b.onclick = () => dlg.close(); });
    f.onsubmit = async e => {
      e.preventDefault();
      const btn = f.querySelector("[type=submit]"), err = f.querySelector(".mErr");
      btn.disabled = true;
      err.hidden = true;
      try {
        const next = await onSave(f);
        dlg.close();
        render();
        if (typeof next === "function") next();
      } catch (x) {
        err.textContent = x.message;
        err.hidden = false;
      } finally { btn.disabled = false; }
    };
    dlg.showModal();
    return f;
  }
  const fields = f => Object.fromEntries(new FormData(f).entries());
  function fillIn(f, obj) {
    Object.entries(obj).forEach(([k, v]) => {
      const el = f.elements[k];
      if (!el || v == null) return;
      if (el.type === "checkbox") el.checked = !!v;
      else if (el instanceof RadioNodeList) el.value = String(v);
      else el.value = v;
    });
  }

  function start() {
    const f = openModal("Empezar con mis datos", `
      <p>Ahora estás viendo una cartera de ejemplo. ¿Cómo quieres empezar la tuya?</p>
      <label class="opcion"><input type="radio" name="desde" value="vacia" checked>
        <span><b>Empezar de cero</b><br>Una cartera vacía para meter lo tuyo.</span></label>
      <label class="opcion"><input type="radio" name="desde" value="ejemplo">
        <span><b>Copiar el ejemplo para practicar</b><br>Puedes tocar, añadir y borrar sin miedo.
        Cuando quieras empezar de verdad, borra sus productos.</span></label>
      <p class="ayuda">Tus datos se guardan solo en tu ordenador, en la carpeta <code>mis_datos</code>.</p>`,
    async f => {
      await api("POST", "api/empezar", { desde: fields(f).desde });
      preferences.guarda("patrimonio.tab", "datos");
      location.reload();
    }, "Empezar");
    return f;
  }
  function reset() {
    openModal("Empezar de nuevo", `
      <p>¿Qué quieres hacer con la cartera que tienes ahora?</p>
      <label class="opcion"><input type="radio" name="a" value="vacia" checked>
        <span><b>Empezar de cero</b><br>Una cartera vacía para meter lo tuyo.</span></label>
      <label class="opcion"><input type="radio" name="a" value="demo">
        <span><b>Volver a ver la cartera de ejemplo</b><br>Luego podrás empezar otra vez con «Empezar con mis datos».</span></label>
      <p class="ayuda">No se pierde nada: tu cartera actual se guarda en <code>mis_datos/copias</code> por si quieres recuperarla.</p>`,
    async f => {
      await api("POST", "api/reiniciar", { a: fields(f).a });
      preferences.guarda("patrimonio.tab", "datos");
      location.reload();
    }, "Continuar");
  }
  function personalOnly(fn) {
    return (...a) => (E.modo === "demo" ? start()
      : E.modo === "todos" ? alert("Estás viendo «Todos juntos», que solo sirve para mirar. Elige un perfil en el selector de arriba para cambiar sus datos.")
      : fn(...a));
  }

  async function profiles() {
    let P;
    try { P = await api("GET", "api/perfiles"); } catch (x) { alert(x.message); return; }
    if (E.modo === "demo" && P.lista.length < 2) {
      alert("Primero empieza tu propia cartera con «Empezar con mis datos». Luego podrás añadir la de tu pareja o tus hijos.");
      return;
    }
    const rows = P.lista.map(x => `<div class="perfilFila">
        ${field(x.id === "principal" ? "Tu perfil (el principal)" : "Perfil", `<input name="n_${esc(x.id)}" value="${esc(x.nombre)}" maxlength="40">`)}
        ${x.id === "principal" ? "<span></span>" : `<button type="button" class="btn" data-borrar="${esc(x.id)}" style="margin-top:22px">Borrar</button>`}
      </div>`).join("");
    const f = openModal("Perfiles", `
      <p>Cada perfil es una cartera aparte: la tuya, la de tu pareja, la de tus hijos… Arriba eliges cuál ver, y con
        «Todos juntos» ves la suma de todas.</p>
      <div style="margin-top:10px">${rows}</div>
      ${section("Añadir un perfil")}
      ${field("Nombre", '<input name="nuevo" maxlength="40" placeholder="Por ejemplo: Ana, o Cuenta de Lucas">', "opcional")}
      <p class="ayuda">El perfil nuevo empieza vacío. Sus datos se guardan en <code>mis_datos/perfiles</code>.</p>`,
    async f => {
      const d = fields(f);
      for (const x of P.lista) {
        const newItem = (d["n_" + x.id] || "").trim();
        if (newItem && newItem !== x.nombre) await api("POST", "api/perfiles/renombrar", { id: x.id, nombre: newItem });
      }
      if ((d.nuevo || "").trim()) {
        await api("POST", "api/perfiles", { nombre: d.nuevo.trim() });
        preferences.guarda("patrimonio.tab", "datos");
        preferences.guarda("patrimonio.editor", "productos");
      }
      location.reload();
      return null;
    }, "Guardar");
    f.querySelectorAll("[data-borrar]").forEach(b => {
      b.onclick = async () => {
        const x = P.lista.find(y => y.id === b.dataset.borrar);
        if (!confirm(`¿Borrar el perfil «${x.nombre}» y toda su cartera?\n\nNo se pierde del todo: su carpeta se guarda en mis_datos/copias por si te arrepientes.`)) return;
        try { await api("POST", "api/perfiles/borrar", { id: x.id }); location.reload(); } catch (e) { alert(e.message); }
      };
    });
    if (P.lista.length < 2) f.elements.nuevo.focus();
  }

  function render() {
    const cont = $("#editor");
    if (!cont) return;
    if (!E.cfg) { cont.innerHTML = '<p class="subt" style="margin-top:24px">Cargando tus datos…</p>'; return; }
    let html = "";
    if (E.modo === "todos") {
      cont.innerHTML = `<section class="tarjeta bienvenida"><h2>Todos juntos</h2>
        <p class="subt">Esta vista suma las carteras de todos los perfiles y solo sirve para mirar. Para añadir o cambiar
        datos, elige un perfil en el selector de arriba.</p></section>`;
      return;
    }

    if (E.modo !== "demo" && !E.cfg.productos.length) {
      html += `<section class="tarjeta bienvenida"><h2>Tu cartera está vacía</h2><ol>
        <li><b>Añade tus productos</b>: fondos, acciones, cripto, tu cuenta del banco, tu plan de pensiones…
          Usa el buscador para encontrarlos por ISIN o ticker.</li>
        <li><b>Anota tus compras</b> en «Movimientos», o <b>los saldos</b> de tus cuentas en «Saldos y valores».
          ¿Tienes muchas? Tráelas de golpe desde <b>«Importar»</b>: MyInvestor, una hoja de Excel o con ayuda de una IA.</li>
        <li>Vuelve a la pestaña <b>Patrimonio</b> y mira tu panel.</li></ol>
        <button class="btn prim" data-acc="nuevoProducto">+ Añadir mi primer producto</button></section>`;
    }
    html += `<div class="edBarra"><div class="segm" id="edVistas"></div><span class="sp"></span>
      ${!D && E.cfg.productos.length ? '<button class="btn" data-acc="verPanel">Ver mi panel →</button>' : ""}
      ${E.modo === "propio" ? '<button class="btn" data-acc="objetivo" title="El objetivo de la barra de progreso del panel">Mi objetivo</button>' : ""}
      ${E.modo === "propio" ? '<button class="btn" data-acc="reiniciar">Empezar de nuevo…</button>' : ""}</div>
      <div id="edAvisos" class="avisos"></div><div id="edCuerpo"></div>`;
    cont.innerHTML = html;

    const views = [["productos", "Productos"], ["movimientos", "Movimientos"], ["saldos", "Saldos y valores"], ["importar", "Importar"], ["copias", "Copias y exportar"]];
    const seg = $("#edVistas");
    views.forEach(([id, et]) => {
      const b = document.createElement("button");
      b.textContent = et;
      b.setAttribute("aria-pressed", String(id === E.vista));
      b.onclick = () => { E.vista = id; preferences.guarda("patrimonio.editor", id); render(); };
      seg.appendChild(b);
    });
    $("#edCuerpo").innerHTML = ({ productos: productsView, movimientos: movementsView, saldos: balancesView,
      importar: importView, copias: backupsView }[E.vista] || productsView)();
    if (E.vista === "importar" || E.vista === "copias") bindImport();
    const filter = $("#edFiltro");
    if (filter) filter.onchange = e => { E.filtro = e.target.value; render(); };
  }

  function priceOf(p) {
    if (manual(p)) {
      const v = E.cfg.valoraciones.filter(x => x.producto === p.id).sort((a, b) => a.fecha < b.fecha ? 1 : -1)[0];
      return v ? `${eur(v.valor)} <small>${date(v.fecha)}</small>` : '<span class="neg">sin valor anotado</span>';
    }
    const c = D && (D.productos || []).find(x => x.id === p.id);
    return c && c.nav ? `${num(c.nav)} € <small>${date(c.navFecha)}</small>` : '<small>tras guardar</small>';
  }
  function productsView() {
    const rows = E.cfg.productos.map(p => {
      const n = balanceOnly(p) || manual(p)
        ? E.cfg.valoraciones.filter(v => v.producto === p.id).length + " valores"
        : E.cfg.movimientos.filter(m => m.producto === p.id).length + " movs.";
      return `<tr><td><i class="pt" style="background:var(--s${p.slot || 1})"></i>${esc(name(p))}
          ${p.identificador ? `<small class="idp">${esc(p.identificador)}</small>` : ""}</td>
        <td>${esc(E.tipos[p.tipo] || p.tipo)}</td><td>${priceOf(p)}</td>
        <td>${esc(E.fuentes[p.fuente] || "")}${p.codigo ? ` <small>${esc(p.codigo)}</small>` : ""}</td>
        <td>${n}</td>
        <td class="acc"><button data-acc="editarProducto" data-id="${esc(p.id)}">Editar</button>
          <button data-acc="borrarProducto" data-id="${esc(p.id)}">Borrar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Productos</h2>
        <span class="subt">Todo lo que tienes: fondos, acciones, cripto, cuentas, planes, inmuebles…</span>
        <span class="sp"></span>${E.cfg.productos.length > 1 ? '<button class="btn" data-acc="repartirColores" title="Da a cada producto un color distinto">Repartir colores</button>' : ""}
        <button class="btn prim" data-acc="nuevoProducto">+ Añadir producto</button></header>
      ${rows ? `<div class="tablaEnv"><table class="dt"><thead><tr><th>Producto</th><th>Tipo</th><th>Último precio</th>
        <th>Fuente del precio</th><th>Datos</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
        : '<p class="subt">Todavía no has añadido ningún producto.</p>'}</section>`;
  }

  function nextColor() {
    const uses = Array(13).fill(0);
    E.cfg.productos.forEach(p => { uses[p.slot || 1]++; });
    let best = 1;
    for (let i = 1; i <= 12; i++) if (uses[i] < uses[best]) best = i;
    return best;
  }

  const field = (et, control, hint = "", category = "") =>
    `<label class="campo ${category}"><span class="et">${et}${hint ? ` <em>${hint}</em>` : ""}</span>${control}</label>`;
  const section = t => `<div class="secc">${t}</div>`;
  const LUPA = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
  const COLOR_FUENTE = { morningstar: "var(--s3)", yahoo: "var(--s7)", coingecko: "var(--s4)" };
  const decimal = v => v == null || v === "" ? "" : String(v).replace(".", ",");

  function productForm(p) {
    const newItem = !p;
    p = p || { tipo: "fondo", fuente: "morningstar", moneda: "EUR", largoPlazo: true, slot: nextColor() };
    const categories = [...new Set(E.cfg.productos.map(x => x.clase).filter(Boolean))];
    const colors = Array.from({ length: 12 }, (_, i) =>
      `<label class="color" style="--c:var(--s${i + 1})" title="Color ${i + 1}"><input type="radio" name="slot" value="${i + 1}"><i></i></label>`).join("");
    const f = openModal(newItem ? "Añadir producto" : "Editar " + esc(name(p)), `
      <div class="buscador">
        <div class="tit">Busca tu producto</div>
        <div class="sub">Por ISIN, ticker o nombre. Comprobamos que tiene precio antes de proponerlo.</div>
        <div class="fila"><div class="caja">${LUPA}<input id="bq" placeholder="IE00BYX5NX33, AAPL, bitcoin, oro…" autocomplete="off"></div>
          <button type="button" class="btn prim" id="bBuscar">Buscar</button></div>
        <div id="bRes" class="bRes"></div>
        <p class="ayuda">¿No aparece o no tiene precio en internet (un piso, oro físico, un plan de pensiones)?
          Rellénalo abajo y elige <b>«Valor anotado a mano»</b> como fuente del precio.</p>
      </div>

      ${section("El producto")}
      <div class="rejilla">
        ${field("Nombre", '<input name="nombre" required>', "", "ancho")}
        ${field("Nombre corto", '<input name="corto" maxlength="24">', "para los gráficos")}
        ${field("Tipo", `<select name="tipo">${options(E.tipos, p.tipo)}</select>`)}
        ${field("ISIN o ticker", '<input name="identificador">', "opcional")}
        ${field("Banco o bróker", '<input name="entidad">', "opcional")}
      </div>

      <div class="siCotiza">${section("De dónde sale el precio")}
      <div class="rejilla tres">
        ${field("Fuente", `<select name="fuente">${options(E.fuentes, p.fuente)}</select>`)}
        ${field("Código", '<input name="codigo">', "", "siOnline")}
        ${field("Moneda", '<input name="moneda" maxlength="3">', "", "siOnline")}
      </div></div>

      ${section("Cómo se muestra")}
      <div class="rejilla">
        ${field("Clase de activo", `<input name="clase" list="edClases" placeholder="Renta variable global">
          <datalist id="edClases">${categories.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`, "opcional")}
        ${field("Color en los gráficos", `<div class="colores">${colors}</div>`)}
        <label class="interruptor ancho"><input type="checkbox" name="largoPlazo"><span class="pista"></span>
          <span><b>Inversión a largo plazo</b><small>El botón «Solo largo plazo» del panel quita lo que no lo es: colchón, cuentas…</small></span></label>
        <label class="interruptor ancho"><input type="checkbox" name="liquidez"><span class="pista"></span>
          <span><b>Cuenta como liquidez</b><small>Dinero que puedes tener en el banco en unos días (cuentas, monetarios…). Se suma en «Liquidez y fondo de emergencia».</small></span></label>
      </div>
      <p class="relleno" id="bRelleno" hidden></p>

      <details class="avanzado"><summary>Ficha y opciones avanzadas</summary>
        <div class="rejilla tres">
          ${field("Comisión anual", '<input name="ter" inputmode="decimal" placeholder="0,12">', "TER, %")}
          ${field("Riesgo", '<input name="riesgo" inputmode="numeric" placeholder="1 a 7">', "de 1 a 7")}
          ${field("Gestora", '<input name="gestora">')}
          ${field("Línea de respaldo", '<input name="respaldo" placeholder="BTCW.SW">', "Yahoo")}
          ${field("Moneda respaldo", '<input name="respaldoMoneda" maxlength="3" placeholder="CHF">')}
          ${field("Precio en vivo", '<input name="vivo" placeholder="bitcoin">', "id CoinGecko")}
          ${field("Reparto como el de", '<input name="expoComo" placeholder="IE00BYX5NX33">', "ISIN de un fondo parecido", "ancho")}
          ${field("Descripción", '<textarea name="papel" rows="2" placeholder="Para qué tienes este producto"></textarea>', "opcional", "ancho")}
        </div>
        <p class="ayuda">El <b>respaldo</b> contrasta cada día el precio con otra línea del mismo producto y usa esa
          cuando no coinciden. El <b>precio en vivo</b> mueve el valor minuto a minuto con una criptomoneda.
          <b>Reparto como el de</b>: para un plan o una cartera que no cotiza, el ISIN de un fondo que invierta en lo mismo
          (por ejemplo, el de un indexado al MSCI World): sus países y sectores se usan en «Dónde está tu dinero».</p>
      </details>`,
    async f => {
      const d = fields(f);
      d.largoPlazo = f.elements.largoPlazo.checked;
      d.liquidez = f.elements.liquidez.checked;
      if (!newItem) d.id = p.id;
      const item = await save("productos", d);
      if (!newItem) return null;

      return manual(item) ? () => valuationForm(null, item.id) : () => movementForm(null, item.id);
    }, newItem ? "Guardar producto" : "Guardar cambios");

    const defaultLiquidity = () => f.elements.tipo.value === "efectivo" ||
      /monetari/i.test([f.elements.nombre.value, f.elements.clase.value].join(" "));
    fillIn(f, { ...p, ter: p.ter != null ? decimal(+(p.ter * 100).toFixed(4)) : "" });
    f.elements.liquidez.checked = p.liquidez != null ? !!p.liquidez : defaultLiquidity();
    let liquidityChanged = p.liquidez != null;
    f.elements.liquidez.addEventListener("change", () => { liquidityChanged = true; });
    f.addEventListener("change", e => { if (!liquidityChanged && e.target.name !== "liquidez") f.elements.liquidez.checked = defaultLiquidity(); });
    const adjust = () => {
      const balance = SOLO_SALDO.includes(f.elements.tipo.value);
      const online = !balance && f.elements.fuente.value !== "manual";
      f.querySelector(".siCotiza").hidden = balance;
      f.querySelectorAll(".siOnline").forEach(el => { el.hidden = !online; });
      f.querySelector(".rejilla.tres").classList.toggle("una", !online);
      f.querySelector(".buscador").hidden = balance;
    };
    f.elements.tipo.onchange = adjust;
    f.elements.fuente.onchange = adjust;
    adjust();

    const search = async () => {
      const q = $("#bq").value.trim();
      const res = $("#bRes");
      if (!q) return;
      res.innerHTML = '<p class="cargando">Buscando y comprobando precios…</p>';
      try {
        const j = await api("GET", "api/buscar?q=" + encodeURIComponent(q));
        if (!j.resultados.length && j.sinConexion) {
          res.innerHTML = `<p class="neg">No he podido conectar con internet (o Yahoo/Morningstar no han
            respondido). Comprueba tu conexión e inténtalo otra vez.</p>`;
          return;
        }
        if (!j.resultados.length) {
          res.innerHTML = `<p class="neg">No encuentro «${esc(q)}» con precio en internet. Prueba con el ISIN
            (viene en la ficha del producto en tu banco) o elige «Valor anotado a mano».</p>`;
          return;
        }
        res.innerHTML = j.resultados.map((r, i) => `<button type="button" class="bItem" data-i="${i}" style="--c:${COLOR_FUENTE[r.fuente]}">
          <span class="franja"></span>
          <span><span class="nm">${esc(r.nombre || r.codigo)}</span>
            <span class="meta"><span>${esc(r.codigo)}</span>${r.mercado && r.mercado !== E.fuentes[r.fuente] ? `<span>${esc(r.mercado)}</span>` : ""}<span>${esc(E.fuentes[r.fuente])}</span></span></span>
          <span class="pre">${num(r.precio)} ${esc(r.moneda)}<small>${date(r.fecha)}</small></span></button>`).join("");
        res.querySelectorAll(".bItem").forEach(b => {
          b.onclick = () => {
            const r = j.resultados[+b.dataset.i];
            const n = r.nombre || r.codigo;
            const fi = r.ficha || {};
            fillIn(f, {
              nombre: n, corto: n.slice(0, 24).trim(), tipo: r.tipo, identificador: r.identificador,
              fuente: r.fuente, codigo: r.codigo, moneda: r.moneda || "EUR", vivo: r.vivo || "",
              ter: decimal(fi.ter), riesgo: fi.riesgo || "", gestora: fi.gestora || "",
            });
            if (fi.clase) f.elements.clase.value = fi.clase;
            const rell = [fi.ter != null && `comisión ${decimal(fi.ter)} %`, fi.riesgo && `riesgo ${fi.riesgo}/7`,
              fi.clase && "categoría", fi.gestora && "gestora"].filter(Boolean);
            const notice = $("#bRelleno");
            notice.hidden = !rell.length;
            notice.textContent = rell.length ? `✓ Ficha rellenada desde Morningstar: ${rell.join(", ")}.` : "";
            res.querySelectorAll(".bItem").forEach(x => x.classList.toggle("sel", x === b));
            adjust();
          };
        });
      } catch (x) { res.innerHTML = `<p class="neg">${esc(x.message)}</p>`; }
    };
    $("#bBuscar").onclick = search;
    $("#bq").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); search(); } };
    if (newItem) $("#bq").focus();
  }

  async function deleteProduct(id) {
    const p = prod(id);
    const nm = E.cfg.movimientos.filter(m => m.producto === id || m.destino === id).length;
    const nv = E.cfg.valoraciones.filter(v => v.producto === id).length;
    const extra = nm || nv ? `\n\nSe borrarán también sus ${nm} movimientos y ${nv} valores anotados.` : "";
    if (!confirm(`¿Borrar «${name(p)}»?${extra}\n\nSi te equivocas, hay copias automáticas en mis_datos/copias.`)) return;
    try { await remove("productos", id); render(); } catch (x) { alert(x.message); }
  }

  function movementsView() {
    const quotedProducts = E.cfg.productos.filter(withMovements);
    const movs = E.cfg.movimientos
      .filter(m => E.filtro === "todos" || m.producto === E.filtro || m.destino === E.filtro)
      .sort((a, b) => a.fecha < b.fecha ? 1 : a.fecha > b.fecha ? -1 : 0);
    const rows = movs.map(m => {
      const p = prod(m.producto);
      if (m.tipo === "ajuste") {
        return `<tr><td>${date(m.fecha)}</td><td style="text-align:left">${p ? `<i class="pt" style="background:var(--s${p.slot || 1})"></i>` : ""}${esc(name(p))}</td>
          <td style="text-align:left">Ajuste</td><td>= ${num(m.unidades)}</td><td>—</td><td>—</td>
          <td class="nota" title="${esc(m.nota)}">${esc(m.nota || "")}</td>
          <td class="acc"><button data-acc="editarMov" data-id="${esc(m.id)}">Editar</button>
            <button data-acc="borrarMov" data-id="${esc(m.id)}">Borrar</button></td></tr>`;
      }
      if (m.tipo === "traspaso") {
        const d = prod(m.destino);
        return `<tr><td>${date(m.fecha)}</td><td style="text-align:left">${p ? `<i class="pt" style="background:var(--s${p.slot || 1})"></i>` : ""}${esc(name(p))}
            → ${d ? `<i class="pt" style="background:var(--s${d.slot || 1});margin-left:4px"></i>` : ""}${esc(name(d))}</td>
          <td style="text-align:left">Traspaso${m.total ? " total" : ""}</td>
          <td>${m.unidades ? "−" + num(m.unidades) : "—"}${m.unidadesDestino ? ` <small>/ +${num(m.unidadesDestino)}</small>` : ""}</td>
          <td>${eur(m.importe)}</td><td>—</td>
          <td class="nota" title="${esc(m.nota)}">${esc(m.nota || "")}</td>
          <td class="acc"><button data-acc="editarMov" data-id="${esc(m.id)}">Editar</button>
            <button data-acc="borrarMov" data-id="${esc(m.id)}">Borrar</button></td></tr>`;
      }
      const price = m.unidades ? (m.importe - (m.comision || 0)) / m.unidades : null;
      return `<tr><td>${date(m.fecha)}</td><td style="text-align:left">${p ? `<i class="pt" style="background:var(--s${p.slot || 1})"></i>` : ""}${esc(name(p))}</td>
        <td style="text-align:left">${esc(E.tiposMov[m.tipo] || m.tipo)}</td>
        <td>${m.unidades ? num(m.unidades) : "—"}</td>
        <td class="${m.tipo === "compra" || m.tipo === "comision" ? "" : "pos"}">${eur(m.importe)}</td>
        <td>${price ? num(price) + " €" : "—"}</td>
        <td class="nota" title="${esc(m.nota)}">${esc(m.nota || "")}</td>
        <td class="acc"><button data-acc="editarMov" data-id="${esc(m.id)}">Editar</button>
          <button data-acc="borrarMov" data-id="${esc(m.id)}">Borrar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Movimientos</h2>
        <span class="subt">Compras, ventas, traspasos, dividendos y comisiones</span><span class="sp"></span>
        <select id="edFiltro" aria-label="Filtrar por producto"><option value="todos">Todos los productos</option>
          ${quotedProducts.map(p => `<option value="${esc(p.id)}"${p.id === E.filtro ? " selected" : ""}>${esc(name(p))}</option>`).join("")}</select>
        <button class="btn" data-acc="nuevoAjuste" title="Si las participaciones no coinciden con las de tu banco">Cuadrar participaciones</button>
        <button class="btn" data-acc="nuevoTraspaso" title="De un fondo o plan a otro, sin vender">⇄ Traspaso</button>
        <button class="btn" data-acc="periodica" title="La aportación de cada mes: FinAppGo la rellena con el precio de cada día">↻ Periódica</button>
        <button class="btn prim" data-acc="nuevoMov">+ Añadir movimiento</button></header>
      ${recurringNotice()}
      ${rows ? `<div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th><th style="text-align:left">Producto</th>
        <th style="text-align:left">Tipo</th><th>Unidades</th><th>Importe</th><th>Precio por unidad</th>
        <th style="text-align:left">Nota</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="subt" style="margin-top:10px">${movs.length} movimientos.</p>`
        : '<p class="subt">No hay movimientos todavía.</p>'}</section>`;
  }

  const AYUDA_IMPORTE = {
    compra: "Lo que salió de tu cuenta, con las comisiones incluidas.",
    venta: "Lo que te ingresaron, ya descontadas las comisiones.",
    dividendo: "Lo que te ingresaron por el dividendo o el cupón.",
    comision: "Comisiones sueltas, como la de custodia. Las de compra y venta ya van dentro de su importe.",
  };
  const AYUDA_INMUEBLE = {
    dividendo: "Lo que te ha pagado el inquilino. Puedes anotarlo cada mes o sumado por año. No cambia el valor del " +
      "inmueble (ese lo anotas en «Saldos y valores»): sirve para ver lo que te rinde.",
    comision: "Gastos del inmueble: comunidad, IBI, seguro, reparaciones, gestoría… Se restan de lo que te rinde.",
  };
  const AYUDA_INTERESES = "Los intereses que te ha pagado la cuenta, ya descontada la retención. No cambian el saldo " +
    "(ese lo anotas en «Saldos y valores»): sirven para ver cuánto te rinde en «Rendimiento».";

  const SIMBOLO = { EUR: "€", USD: "$", GBP: "£", CHF: "CHF", JPY: "¥", CAD: "CAD", AUD: "AUD" };
  const currenciesOf = p => {
    const personal = p && p.moneda ? (/^GB[pX]$/.test(p.moneda) ? "GBP" : p.moneda.toUpperCase()) : "EUR";
    return [...new Set(["EUR", personal, "USD"])];
  };
  const CAMBIOS = {};
  async function exchangeRate(currency, date) {
    const k = currency + date;
    if (!(k in CAMBIOS)) {
      CAMBIOS[k] = api("GET", `api/cambio?moneda=${currency}&fecha=${date}`).then(j => j.ok ? j.cambio : null).catch(() => null);
    }
    return CAMBIOS[k];
  }

  function movementForm(m, productId, type) {
    const quotedProducts = E.cfg.productos.filter(withMovements);
    if (!quotedProducts.length) { alert("Primero añade un producto en «Productos»."); return; }
    const newItem = !m;
    m = m || { fecha: hoy(), tipo: type || "compra", producto: productId || (E.filtro !== "todos" ? E.filtro : quotedProducts[0].id) };
    if (newItem && prod(m.producto) && prod(m.producto).tipo === "efectivo") m.tipo = "dividendo";
    if (m && m.tipo === "traspaso") return transferForm(m);
    if (m && m.tipo === "ajuste") return adjustmentForm(m);
    const pills = Object.entries(E.tiposMov).filter(([k]) => k !== "traspaso" && k !== "ajuste").map(([k, v]) =>
      `<label><input type="radio" name="tipo" value="${esc(k)}"><span>${esc(k === "dividendo" ? "Dividendo" : v)}</span></label>`).join("");
    const f = openModal(newItem ? "Añadir movimiento" : "Editar movimiento", `
      <div class="pildoras">${pills}</div>
      <div class="rejilla" style="margin-top:18px">
        ${field("Producto", `<select name="producto">${quotedProducts.map(p =>
          `<option value="${esc(p.id)}">${esc(name(p))}</option>`).join("")}</select>`, "", "ancho")}
        ${field("Fecha", `<input type="date" name="fecha" max="${hoy()}">`)}
        ${field("Unidades", `<div class="conBoton"><input name="unidades" inputmode="decimal" placeholder="0">
          <button type="button" class="btn" id="mTodas" title="Rellena las unidades exactas que tenías ese día">Todas</button></div>`, "participaciones, acciones…", "siUnid")}
        ${field("Importe total", `<div class="conSufijo conMoneda"><input name="importe" inputmode="decimal" placeholder="0,00">
          <select name="moneda" aria-label="Moneda del importe" title="¿Pagaste en otra moneda? Elígela y se pasa a euros con el cambio de ese día"></select></div>`)}
        ${field("Comisión", '<div class="conSufijo"><input name="comision" inputmode="decimal" placeholder="0,00"><span id="mSufCom">€</span></div>', "ya incluida en el importe", "siCom")}
        ${field("Nota", '<input name="nota" maxlength="200" placeholder="Por ejemplo: aportación mensual">', "opcional", "ancho")}
      </div>
      <div class="resumen"><span id="mAyuda"></span><b id="mPrecio"></b></div>`,
    async f => {
      const d = fields(f);
      if (!newItem) d.id = m.id;
      await save("movimientos", d);
      E.vista = "movimientos";
      preferences.guarda("patrimonio.editor", "movimientos");
      return null;
    }, newItem ? "Guardar movimiento" : "Guardar cambios");
    fillIn(f, { ...m, unidades: decimal(m.unidades || ""), importe: decimal(m.importe), comision: decimal(m.comision) });
    const currencySelector = f.elements.moneda;
    const setCurrencies = () => {
      const before = currencySelector.value || "EUR";
      const entries = currenciesOf(prod(f.elements.producto.value));
      currencySelector.innerHTML = entries.map(c => `<option value="${c}">${SIMBOLO[c] && SIMBOLO[c] !== c ? `${SIMBOLO[c]} ${c}` : c}</option>`).join("");
      currencySelector.value = entries.includes(before) ? before : "EUR";
    };
    setCurrencies();
    f.elements.producto.addEventListener("change", setCurrencies);
    const adjust = () => {
      const p = prod(f.elements.producto.value);

      const account = !!(p && p.tipo === "efectivo");
      const property = !!(p && p.tipo === "inmueble");
      f.querySelectorAll(".pildoras label").forEach(l => {
        const v = l.querySelector("input").value;
        l.hidden = account && v !== "dividendo";
        l.querySelector("span").textContent = v === "dividendo" ? (account ? "Intereses" : property ? "Alquiler" : "Dividendo")
          : v === "comision" && property ? "Gasto" : E.tiposMov[v];
      });
      f.querySelector(".pildoras").classList.toggle("una", account);
      if (account && f.elements.tipo.value !== "dividendo") f.elements.tipo.value = "dividendo";
      const t = f.elements.tipo.value;
      const mon = currencySelector.value || "EUR", sim = SIMBOLO[mon] || mon;
      $("#mSufCom").textContent = sim;
      const withUnits = t === "compra" || t === "venta";
      f.querySelector(".siUnid").hidden = !withUnits;
      f.querySelector(".siCom").hidden = !withUnits;

      $("#mTodas").hidden = t !== "venta";
      $("#mAyuda").textContent = (account ? AYUDA_INTERESES : property && AYUDA_INMUEBLE[t] || AYUDA_IMPORTE[t]) + (p && manual(p) && t === "compra"
        ? " Como este producto se valora a mano, las unidades son opcionales." : "");
      const u = readNumber(f.elements.unidades.value), imp = readNumber(f.elements.importe.value);
      const com = readNumber(f.elements.comision.value) || 0;
      $("#mPrecio").textContent = withUnits && u > 0 && imp > 0 ? `${num((imp - com) / u)} ${sim} / unidad` : "";

      if (mon !== "EUR") {
        const fe = f.elements.fecha.value;
        const request = mon + fe + imp;
        f.dataset.pedido = request;
        exchangeRate(mon, fe).then(fx => {
          if (f.dataset.pedido !== request) return;
          $("#mAyuda").textContent = AYUDA_IMPORTE[t] + (fx
            ? ` Se guarda en euros: ${imp > 0 ? `≈ ${eur(imp * fx)}` : `1 ${mon} = ${num(fx)} €`} con el cambio del ${date(fe)}.`
            : ` No encuentro el cambio de ${mon} de ese día: revisa tu conexión o escribe el importe en euros.`);
        });
      }
    };
    f.oninput = adjust;
    f.onchange = adjust;
    $("#mTodas").onclick = async () => {
      try {
        const q = new URLSearchParams({ producto: f.elements.producto.value, fecha: f.elements.fecha.value || hoy() });
        if (!newItem) q.set("excluir", m.id);
        const j = await api("GET", "api/unidades?" + q);
        f.elements.unidades.value = decimal(+j.unidades.toFixed(8));
        adjust();
      } catch (x) { alert(x.message); }
    };
    adjust();
  }

  function goalForm() {
    const o = E.cfg.objetivo || {};
    const personal = !!(o.activo && o.importe && (o.elegido || o.importe !== 100000));
    const f = openModal("Mi objetivo de patrimonio", `
      <label class="interruptor"><input type="checkbox" name="activo"><span class="pista"></span>
        <span><b>Usar mi propio objetivo</b><small>Si lo apagas, la barra del panel va al siguiente hito:
          10.000 €, 25.000 €, 50.000 €, 100.000 €…</small></span></label>
      <div class="rejilla siObjetivo" style="margin-top:16px">
        ${field("Importe", '<div class="conSufijo"><input name="importe" inputmode="decimal" placeholder="30.000"><span>€</span></div>')}
        ${field("Nombre", '<input name="etiqueta" maxlength="60" placeholder="Entrada del piso">', "opcional")}
      </div>`,
    async f => {
      const d = fields(f);
      d.activo = f.elements.activo.checked;
      const j = await api("POST", "api/objetivo", d);
      E.cfg = j.cartera;
      window.EDITOR_SUCIO = true;
      return null;
    });
    fillIn(f, { activo: personal, importe: personal ? decimal(o.importe) : "", etiqueta: personal ? o.etiqueta : "" });
    const adjust = () => { f.querySelector(".siObjetivo").hidden = !f.elements.activo.checked; };
    f.elements.activo.onchange = adjust;
    adjust();
  }

  const PRECIOS = {};
  async function price(pid, f) {
    const k = pid + f;
    if (!(k in PRECIOS)) {
      PRECIOS[k] = api("GET", `api/precio?producto=${encodeURIComponent(pid)}&fecha=${f}`)
        .then(j => j.ok ? j.precio : null).catch(() => null);
    }
    return PRECIOS[k];
  }

  function transferForm(m) {
    const eligibleForTransfer = E.cfg.productos.filter(p => !balanceOnly(p));
    if (eligibleForTransfer.length < 2) { alert("Para un traspaso necesitas al menos dos productos: el de origen y el de destino. Añade el nuevo en «Productos»."); return; }
    const newItem = !m;
    m = m || { fecha: hoy(), producto: E.filtro !== "todos" && prod(E.filtro) && !balanceOnly(prod(E.filtro)) ? E.filtro : eligibleForTransfer[0].id };
    if (!m.destino) m.destino = (eligibleForTransfer.find(p => p.id !== m.producto) || {}).id;
    const ops = eligibleForTransfer.map(p => `<option value="${esc(p.id)}">${esc(name(p))}</option>`).join("");
    const f = openModal(newItem ? "Traspaso entre productos" : "Editar traspaso", `
      <div class="rejilla">
        ${field("Sale de", `<select name="producto">${ops}</select>`)}
        ${field("Va a", `<select name="destino">${ops}</select>`)}
        ${field("Fecha", `<input type="date" name="fecha" max="${hoy()}">`)}
        ${field("Importe traspasado", '<div class="conSufijo"><input name="importe" inputmode="decimal" placeholder="0,00"><span>€</span></div>', "lo que valía ese día")}
        ${field("Participaciones que salen", `<div class="conBoton"><input name="unidades" inputmode="decimal" placeholder="0">
          <button type="button" class="btn" id="tTodas" title="Todas las que tenías ese día">Todas</button></div>`, "", "siUnidO")}
        ${field("Participaciones que entran", '<input name="unidadesDestino" inputmode="decimal" placeholder="0">', "en el destino", "siUnidD")}
        <label class="interruptor ancho siTotal"><input type="checkbox" name="total"><span class="pista"></span>
          <span><b>Lo traspaso todo</b><small>El producto de origen se queda a cero ese día.</small></span></label>
        ${field("Nota", '<input name="nota" maxlength="200" placeholder="Por ejemplo: traspaso a un indexado más barato">', "opcional", "ancho")}
      </div>
      <div class="resumen"><span id="tResumen"></span><b id="tPrecios"></b></div>`,
    async f => {
      const d = { ...fields(f), tipo: "traspaso", total: f.elements.total.checked };
      if (!newItem) d.id = m.id;
      await save("movimientos", d);
      E.vista = "movimientos";
      preferences.guarda("patrimonio.editor", "movimientos");
      return null;
    }, newItem ? "Guardar traspaso" : "Guardar cambios");
    fillIn(f, { ...m, unidades: decimal(m.unidades || ""), unidadesDestino: decimal(m.unidadesDestino || ""),
      importe: decimal(m.importe), total: !!m.total });

    const touched = { importe: !newItem, unidadesDestino: !newItem };
    ["importe", "unidadesDestino"].forEach(k => f.elements[k].addEventListener("input", () => { touched[k] = true; }));
    const adjust = async () => {
      const o = prod(f.elements.producto.value), dd = prod(f.elements.destino.value), fe = f.elements.fecha.value || hoy();
      f.querySelector(".siUnidO").hidden = manual(o);
      f.querySelector(".siUnidD").hidden = manual(dd);
      f.querySelector(".siTotal").hidden = !manual(o);
      const alreadyImported = dd && E.cfg.movimientos.some(x => x.producto === dd.id && x.tipo === "compra"
        && /MyInvestor · traspaso/.test(x.nota || ""));
      $("#tResumen").innerHTML = (o && dd && o.id !== dd.id
        ? `No es una venta: lo que llevabas metido en «${esc(name(o))}» y la fecha de cada compra pasan a «${esc(name(dd))}». Hacienda no cobra nada hasta que vendas.`
        : "Elige dos productos distintos.") + (alreadyImported
        ? `<span class="alerta">Ojo: «${esc(name(dd))}» ya trae lotes de un traspaso importados de MyInvestor. Si es este mismo traspaso, no lo anotes otra vez: vuelve a importar su CSV y, en la vista previa, di de qué fondo venía.</span>` : "");
      const request = [o && o.id, dd && dd.id, fe, f.elements.unidades.value, f.elements.importe.value].join("|");
      f.dataset.pedido = request;
      const [po, pd] = await Promise.all([o && !manual(o) ? price(o.id, fe) : null, dd && !manual(dd) ? price(dd.id, fe) : null]);
      if (f.dataset.pedido !== request) return;
      const u = readNumber(f.elements.unidades.value);
      if (!touched.importe && po && u > 0) f.elements.importe.value = decimal((u * po).toFixed(2));
      const imp = readNumber(f.elements.importe.value);
      if (!touched.unidadesDestino && pd && imp > 0) f.elements.unidadesDestino.value = decimal(+(imp / pd).toFixed(6));
      $("#tPrecios").textContent = [po && `${num(po)} €`, pd && `${num(pd)} €`].filter(Boolean).join(" → ");
    };
    f.oninput = adjust;
    f.onchange = adjust;
    $("#tTodas").onclick = async () => {
      try {
        const q = new URLSearchParams({ producto: f.elements.producto.value, fecha: f.elements.fecha.value || hoy() });
        if (!newItem) q.set("excluir", m.id);
        const j = await api("GET", "api/unidades?" + q);
        f.elements.unidades.value = decimal(+j.unidades.toFixed(8));
        adjust();
      } catch (x) { alert(x.message); }
    };
    adjust();
  }

  function adjustmentForm(m) {
    const quoted = E.cfg.productos.filter(p => !manual(p));
    if (!quoted.length) { alert("Ningún producto con precio en internet: no hay participaciones que cuadrar."); return; }
    const newItem = !m;
    m = m || { fecha: hoy(), producto: E.filtro !== "todos" && quoted.some(p => p.id === E.filtro) ? E.filtro : quoted[0].id };
    const f = openModal("Cuadrar participaciones con tu banco", `
      <p>Si las participaciones de un fondo no coinciden con las que ves en tu banco (pasa, por ejemplo, con algunos
        traspasos importados de MyInvestor), escribe aquí las buenas. Lo que pagaste no cambia: solo cuántas tienes.</p>
      <div class="rejilla" style="margin-top:14px">
        ${field("Producto", `<select name="producto">${quoted.map(p => `<option value="${esc(p.id)}">${esc(name(p))}</option>`).join("")}</select>`, "", "ancho")}
        ${field("Fecha", `<input type="date" name="fecha" max="${hoy()}">`, "la del dato de tu banco")}
        ${field("Participaciones según tu banco", '<input name="unidades" inputmode="decimal" placeholder="0">')}
      </div>
      <div class="resumen"><span id="aResumen">Calculando…</span></div>`,
    async f => {
      const d = { ...fields(f), tipo: "ajuste" };
      if (!newItem) d.id = m.id;
      await save("movimientos", d);
      E.vista = "movimientos";
      return null;
    }, newItem ? "Cuadrar" : "Guardar cambios");
    fillIn(f, { ...m, unidades: decimal(m.unidades || "") });
    const adjust = async () => {
      const q = new URLSearchParams({ producto: f.elements.producto.value, fecha: f.elements.fecha.value || hoy() });
      if (!newItem) q.set("excluir", m.id);
      try {
        const j = await api("GET", "api/unidades?" + q);
        const real = readNumber(f.elements.unidades.value);
        $("#aResumen").innerHTML = `FinAppGo calcula <b>${num(j.unidades, 6)}</b> participaciones ese día.` +
          (real >= 0 && !isNaN(real) ? ` Con tu cifra, ${real >= j.unidades ? "+" : "−"}${num(Math.abs(real - j.unidades), 6)}.` : "");
      } catch (x) { $("#aResumen").textContent = x.message; }
    };
    f.oninput = adjust;
    f.onchange = adjust;
    adjust();
  }

  function emergencyFundForm() {
    const c = E.cfg.colchon || { modo: "meses", meses: 6 };
    const f = openModal("Mi fondo de emergencia", `
      <p>Lo que quieres tener siempre a mano por si pasa algo (una avería, quedarte sin trabajo…). Lo habitual es entre
        3 y 6 meses de gastos. FinAppGo lo compara con tu liquidez y te dice cuánto te sobra para invertir.</p>
      <div class="pildoras" style="grid-template-columns:repeat(2,1fr);margin-top:12px">
        <label><input type="radio" name="modo" value="meses"><span>En meses de gastos</span></label>
        <label><input type="radio" name="modo" value="importe"><span>Un importe fijo</span></label></div>
      <div class="rejilla siMeses" style="margin-top:16px">
        ${field("Meses", '<input name="meses" inputmode="decimal" placeholder="6">')}
        ${field("Lo que gastas al mes", '<div class="conSufijo"><input name="gastoMensual" inputmode="decimal" placeholder="2.000"><span>€</span></div>')}
      </div>
      <div class="rejilla siImporte" style="margin-top:16px">
        ${field("Importe", '<div class="conSufijo"><input name="importe" inputmode="decimal" placeholder="12.000"><span>€</span></div>')}
      </div>
      <div class="resumen"><span id="cResumen"></span></div>
      ${E.cfg.colchon ? '<p class="ayuda"><button type="button" class="btn" id="cBorrar">Quitar mi fondo de emergencia</button></p>' : ""}`,
    async f => {
      const j = await api("POST", "api/colchon", fields(f));
      E.cfg = j.cartera;
      window.EDITOR_SUCIO = true;
      return () => { preferences.guarda("patrimonio.tab", "patrimonio"); location.reload(); };
    });
    fillIn(f, { modo: c.modo, meses: decimal(c.meses), gastoMensual: decimal(c.gastoMensual), importe: decimal(c.importe) });
    const adjust = () => {
      const m = f.elements.modo.value;
      f.querySelector(".siMeses").hidden = m !== "meses";
      f.querySelector(".siImporte").hidden = m !== "importe";
      const total = m === "meses" ? readNumber(f.elements.meses.value) * readNumber(f.elements.gastoMensual.value) : readNumber(f.elements.importe.value);
      $("#cResumen").textContent = total > 0 ? `Tu fondo de emergencia: ${eur(total)}.` : "Rellena las cifras.";
    };
    f.oninput = adjust;
    f.onchange = adjust;
    adjust();
    const deleteEntry = $("#cBorrar");
    if (deleteEntry) deleteEntry.onclick = async () => {
      if (!confirm("¿Quitar tu fondo de emergencia?")) return;
      try { await api("POST", "api/colchon", { borrar: true }); preferences.guarda("patrimonio.tab", "patrimonio"); location.reload(); }
      catch (x) { alert(x.message); }
    };
  }

  function tryDemo(d, weights, withCash, account) {
    const n = {};
    Object.entries(weights).forEach(([k, v]) => { const x = readNumber(v); if (x > 0) n[k] = x; });
    const total = Object.values(n).reduce((a, b) => a + b, 0);
    if (!Object.keys(n).length) throw new Error("Pon el % que quieres en al menos un grupo.");
    if (Math.abs(total - 100) > 0.5) throw new Error(`Los porcentajes suman ${num(total, 2)} %: tienen que sumar 100 %.`);
    const monitor = readNumber(d.vigilar) || 3, rebalance = readNumber(d.rebalancear) || 5;
    if (rebalance < monitor) throw new Error("El margen para rebalancear tiene que ser mayor que el de vigilar.");
    return applyDemo({ por: d.por === "producto" ? "producto" : "clase", pesos: n, vigilar: monitor, rebalancear: rebalance, conEfectivo: withCash, cuenta: account });
  }
  function applyDemo(o) {
    E.cfg.objetivoReparto = o;
    if (D) D.objetivoReparto = o;
    return () => document.dispatchEvent(new Event("finappgo:editor"));
  }

  function allocationForm() {
    const demo = E.modo === "demo";
    const o = window.Calculos.normalizaReparto(E.cfg.objetivoReparto) || { por: "clase", pesos: {}, vigilar: 3, rebalancear: 5 };
    const data = (D && D.productos ? D.productos.concat(D.otrosActivos || []) : []);

    const groups = por => {
      const m = new Map();
      data.filter(p => p.valor > 0 && p.tipoClave !== "deuda").forEach(p => {
        const k = por === "producto" ? (p.corto || p.nombre) : window.Calculos.tipoReparto(p);
        m.set(k, (m.get(k) || []).concat(p));
      });
      Object.keys(o.por === por ? o.pesos : {}).forEach(k => { if (!m.has(k)) m.set(k, []); });
      const order = por === "producto" ? [] : window.Calculos.TIPOS_REPARTO;
      return [...m.entries()].sort((a, b) => (order.indexOf(a[0]) + 1 || 99) - (order.indexOf(b[0]) + 1 || 99))
        .map(([name, de]) => ({ nombre: name, de }));
    };
    const f = openModal("Mi reparto objetivo", `
      <p>¿Qué parte de tu dinero quieres en cada sitio? FinAppGo compara con lo que tienes y te dice dónde meter
        la próxima aportación para volver a cuadrar, sin vender nada.</p>
      <div class="pildoras" style="grid-template-columns:repeat(2,1fr);margin-top:12px">
        <label><input type="radio" name="por" value="clase"><span>Por tipo de activo</span></label>
        <label><input type="radio" name="por" value="producto"><span>Por producto</span></label></div>
      <p class="ayuda" id="repQueEs"></p>
      <div class="listaValores" id="repGrupos"></div>
      <div class="resumen"><span>Tienen que sumar 100 %. Las cuentas solo cuentan si les pones un %.</span><b class="sumaRep" id="repSuma"></b></div>
      <p class="ayuda">Con el interruptor de cada producto decides si cuenta para este reparto (por ejemplo, deja fuera
        el plan de pensiones o mete una cuenta). Solo cambia el reparto: sigue en tu patrimonio, tus gráficas y tus totales.</p>
      <details class="avanzado"><summary>Márgenes y efectivo</summary>
        <div class="rejilla">
          ${field("OK hasta", '<div class="conSufijo"><input name="vigilar" inputmode="decimal"><span>pts</span></div>', "de desviación")}
          ${field("Rebalancear desde", '<div class="conSufijo"><input name="rebalancear" inputmode="decimal"><span>pts</span></div>')}
          <label class="interruptor ancho"><input type="checkbox" name="conEfectivo"><span class="pista"></span>
            <span><b>Contarlo todo</b><small>También las cuentas y lo que no es a largo plazo, aunque no les pongas %.</small></span></label>
        </div></details>
      ${E.cfg.objetivoReparto ? '<p class="ayuda"><button type="button" class="btn" id="repBorrar">Quitar mi reparto objetivo</button></p>' : ""}
      ${demo ? '<p class="ayuda">Es la cartera de ejemplo: el cambio se ve al momento, pero no se guarda.</p>' : ""}`,
    async f => {
      const d = fields(f);
      const weights = {};
      Object.keys(d).filter(k => k.startsWith("g_")).forEach(k => { if (String(d[k]).trim()) weights[f.elements[k].dataset.grupo] = d[k]; });
      const account = accountSelection();
      if (demo) return tryDemo(d, weights, f.elements.conEfectivo.checked, account);
      const j = await api("POST", "api/reparto", { por: d.por, pesos: weights, vigilar: d.vigilar, rebalancear: d.rebalancear,
        conEfectivo: f.elements.conEfectivo.checked, cuenta: account });
      E.cfg = j.cartera;
      window.EDITOR_SUCIO = true;
      return () => { preferences.guarda("patrimonio.tab", "patrimonio"); location.reload(); };
    });
    fillIn(f, { por: o.por, vigilar: decimal(o.vigilar), rebalancear: decimal(o.rebalancear), conEfectivo: !!o.conEfectivo });

    const Cal = window.Calculos;
    const candidates = data.filter(p => p.valor > 0 && p.tipoClave !== "deuda" && p.id != null);
    const byId = Object.fromEntries(candidates.map(p => [String(p.id), p]));
    const draft = () => {
      const weights = {};
      f.querySelectorAll("[data-grupo]").forEach(i => { const x = readNumber(i.value); if (x > 0) weights[i.dataset.grupo] = x; });
      return { por: f.elements.por.value, pesos: weights, conEfectivo: f.elements.conEfectivo.checked };
    };
    const selected = { ...(o.cuenta || {}) };
    const accountSelection = () => {
      const b = draft(), out = {};
      candidates.forEach(p => {
        if (Object.prototype.hasOwnProperty.call(selected, p.id) && selected[p.id] !== Cal.cuentaPorDefecto(p, b)) out[p.id] = selected[p.id];
      });
      return out;
    };
    const toggle = (p, withName) => `<label class="onoff" title="Cuenta para este reparto"><input type="checkbox" data-prod="${esc(p.id)}">
      <span class="pista"></span>${withName ? `<span class="nmP">${esc(p.corto || p.nombre)}</span>` : '<span class="est"></span>'}</label>`;
    const updateToggles = () => {
      const b = { ...draft(), cuenta: selected };
      f.querySelectorAll("[data-prod]").forEach(c => {
        const p = byId[c.dataset.prod];
        if (!p) return;
        c.checked = Cal.cuentaEnReparto(p, b);
        c.closest(".onoff").classList.toggle("fuera", !c.checked);
        const row = c.closest(".filaRep");
        if (row && b.por === "producto") row.classList.toggle("apagado", !c.checked);
      });
    };
    const renderGroups = () => {
      const por = f.elements.por.value;
      $("#repQueEs").textContent = por === "producto"
        ? "Cada fondo, acción o cuenta por separado: por ejemplo, 80 % al fondo del mundo y 20 % al de emergentes."
        : "Grupos grandes: toda la bolsa junta, la renta fija, el monetario… Para repartir entre fondos concretos, elige «Por producto».";
      $("#repGrupos").innerHTML = groups(por).map((g, i) => `<div class="filaValor filaRep"><span class="nm">${esc(g.nombre)}${
          por === "producto"
            ? (g.de[0] && g.de[0].id != null ? `<span class="onoffs">${toggle(g.de[0], false)}</span>` : "")
            : (g.de.length ? `<span class="onoffs">${g.de.filter(p => p.id != null).map(p => toggle(p, true)).join("")}</span>` : "")}</span>
        <span class="conSufijo"><input name="g_${i}" data-grupo="${esc(g.nombre)}" inputmode="decimal" placeholder="0"
          value="${o.por === por && o.pesos[g.nombre] != null ? decimal(o.pesos[g.nombre]) : ""}"><span>%</span></span></div>`).join("")
        || '<p class="subt">Primero añade productos con valor.</p>';
      updateToggles();
      sum();
    };
    $("#repGrupos").onchange = e => {
      const c = e.target.closest("[data-prod]");
      if (!c) return;
      selected[c.dataset.prod] = c.checked;
      updateToggles();
    };
    const sum = () => {
      const t = [...f.querySelectorAll("[data-grupo]")].reduce((a, i) => a + (readNumber(i.value) || 0), 0);
      const el = $("#repSuma");
      el.textContent = `Suma: ${num(t, 2)} %`;
      el.classList.toggle("mal", Math.abs(t - 100) > 0.5);
    };
    f.querySelectorAll('[name="por"]').forEach(r => { r.onchange = renderGroups; });
    f.oninput = e => { sum(); if (!e.target.closest("[data-prod]")) updateToggles(); };
    renderGroups();
    const deleteEntry = $("#repBorrar");
    if (deleteEntry) deleteEntry.onclick = async () => {
      if (!confirm("¿Quitar tu reparto objetivo?")) return;
      if (demo) { $("#modal").close(); applyDemo(null)(); return; }
      try { await api("POST", "api/reparto", { borrar: true }); preferences.guarda("patrimonio.tab", "patrimonio"); location.reload(); }
      catch (x) { alert(x.message); }
    };
  }

  async function deleteMovement(id) {
    const m = E.cfg.movimientos.find(x => x.id === id);
    const locationLabel = m.tipo === "traspaso" ? `de «${name(prod(m.producto))}» a «${name(prod(m.destino))}»` : `en «${name(prod(m.producto))}»`;
    if (!confirm(`¿Borrar ${(E.tiposMov[m.tipo] || "").toLowerCase()} de ${eur(m.importe)} del ${date(m.fecha)} ${locationLabel}?`)) return;
    try { await remove("movimientos", id); render(); } catch (x) { alert(x.message); }
  }

  const valueLabel = p => p.tipo === "efectivo" ? "Saldo" : p.tipo === "deuda" ? "Lo que queda por pagar" : "Valor";

  function balancesView() {
    const entries = E.cfg.productos.filter(manual);
    if (!entries.length) {
      return `<section class="tarjeta"><header><h2>Saldos y valores</h2></header>
        <p class="subt">Aquí aparecen tus cuentas, deudas, planes de pensiones y todo lo que no tiene precio en
        internet. Añádelos en «Productos» (tipo «Cuenta / efectivo», o fuente del precio «Valor anotado a mano»).</p></section>`;
    }
    const cards = entries.map(p => {
      const vals = E.cfg.valoraciones.filter(v => v.producto === p.id).sort((a, b) => a.fecha < b.fecha ? 1 : -1);
      const withContributions = !balanceOnly(p);
      const rows = vals.map(v => `<tr><td>${date(v.fecha)}</td><td>${eur(v.valor)}</td>
        ${withContributions ? `<td>${v.aportado != null ? eur(v.aportado) : "—"}</td>` : ""}
        <td class="acc"><button data-acc="editarValor" data-id="${esc(v.id)}">Editar</button>
          <button data-acc="borrarValor" data-id="${esc(v.id)}">Borrar</button></td></tr>`).join("");
      return `<section class="tarjeta saldo"><header><h2><i class="pt" style="background:var(--s${p.slot || 1})"></i>${esc(name(p))}</h2>
          <span class="subt">${esc(E.tipos[p.tipo] || "")}${p.entidad ? " · " + esc(p.entidad) : ""}</span><span class="sp"></span>
          ${p.tipo === "efectivo" || p.tipo === "p2p" ? `<button class="btn" data-acc="nuevoInteres" data-id="${esc(p.id)}" title="Intereses que te han pagado">+ Intereses</button>` : ""}
          ${p.tipo === "inmueble" ? `<button class="btn" data-acc="nuevoInteres" data-id="${esc(p.id)}" title="Lo que te ha pagado el inquilino">+ Alquiler</button>
            <button class="btn" data-acc="nuevoGasto" data-id="${esc(p.id)}" title="Comunidad, IBI, seguro, reparaciones…">+ Gasto</button>` : ""}
          <button class="btn" data-acc="nuevoValor" data-id="${esc(p.id)}">+ Anotar</button></header>
        ${rows ? `<div class="tablaEnv"><table class="dt"><thead><tr><th>Fecha</th><th>${valueLabel(p)}</th>
          ${withContributions ? "<th>Aportado</th>" : ""}<th></th></tr></thead><tbody>${rows}</tbody></table></div>`
          : '<p class="neg">Todavía no tiene ningún valor anotado.</p>'}</section>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Saldos y valores</h2>
        <span class="subt">Lo que no tiene precio en internet. Cuanto más a menudo lo anotes (una vez al mes basta),
        mejor sale su curva.</span><span class="sp"></span>
        <button class="btn prim" data-acc="todosValores">Anotar todos de una vez</button></header></section>
      <div class="saldos">${cards}</div>`;
  }

  function valuationForm(v, productId) {
    const newItem = !v;
    const p = prod(v ? v.producto : productId);
    const withContributions = !balanceOnly(p);
    const f = openModal(`${newItem ? "Anotar" : "Editar"} ${valueLabel(p).toLowerCase()} · ${esc(name(p))}`, `
      <div class="rejilla">
        ${field("Fecha", `<input type="date" name="fecha" max="${hoy()}">`)}
        ${field(valueLabel(p), '<div class="conSufijo"><input name="valor" inputmode="decimal" placeholder="0,00"><span>€</span></div>')}
        ${withContributions ? field("Aportado hasta esa fecha", '<div class="conSufijo"><input name="aportado" inputmode="decimal" placeholder="0,00"><span>€</span></div>', "opcional", "ancho") : ""}
      </div>
      <div class="resumen"><span>${withContributions
        ? "Lo aportado es el dinero que llevas metido en total. Si lo anotas, el panel calcula su rentabilidad."
        : "Copia el saldo que ves hoy en tu banco."} Si ya había un valor ese mismo día, se sustituye.</span></div>`,
    async f => {
      const d = { ...fields(f), producto: p.id };
      if (!newItem) d.id = v.id;
      await save("valoraciones", d);
      E.vista = "saldos";
      preferences.guarda("patrimonio.editor", "saldos");
      return null;
    });
    fillIn(f, v ? { ...v, valor: decimal(v.valor), aportado: decimal(v.aportado) } : { fecha: hoy() });
    f.elements.valor.focus();
  }

  function allValues() {
    const entries = E.cfg.productos.filter(manual);
    const last = id => E.cfg.valoraciones.filter(v => v.producto === id).sort((a, b) => a.fecha < b.fecha ? 1 : -1)[0];
    openModal("Anotar todos los saldos", `
      <div class="rejilla">${field("Fecha", `<input type="date" name="fecha" max="${hoy()}" value="${hoy()}">`)}</div>
      <div class="listaValores">${entries.map(p => {
        const u = last(p.id);
        return `<label class="filaValor"><span><span class="nm"><i class="pt" style="background:var(--s${p.slot || 1})"></i>${esc(name(p))}</span>
          <small>${u ? `Último: ${eur(u.valor)} el ${date(u.fecha)}` : "Sin valores todavía"}</small></span>
          <span class="conSufijo"><input name="v_${esc(p.id)}" inputmode="decimal" placeholder="${u ? decimal(u.valor) : "0,00"}"><span>€</span></span></label>`;
      }).join("")}</div>
      <div class="resumen"><span>Deja en blanco los que no quieras tocar. Es el gesto de cada mes: abre tu banco y copia los saldos.</span></div>`,
    async f => {
      const d = fields(f);
      const pending = entries.filter(p => String(d["v_" + p.id] || "").trim());
      if (!pending.length) throw new Error("No has escrito ningún valor.");
      for (const p of pending) {
        try { await save("valoraciones", { producto: p.id, fecha: d.fecha, valor: d["v_" + p.id] }); }
        catch (x) { throw new Error(`${name(p)}: ${x.message}`); }
      }
      E.vista = "saldos";
      return null;
    }, "Guardar todos");
  }

  async function deleteValuation(id) {
    const v = E.cfg.valoraciones.find(x => x.id === id);
    if (!confirm(`¿Borrar el valor de ${eur(v.valor)} del ${date(v.fecha)} de «${name(prod(v.producto))}»?`)) return;
    try { await remove("valoraciones", id); render(); } catch (x) { alert(x.message); }
  }

  const IMP = { origen: "myinvestor", informe: null, token: null, hecho: null, prompt: null, archivos: [], respuestas: {} };
  const ICONOS = {
    myinvestor: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6"/></svg>',
    plantilla: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/></svg>',
    ia: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"/></svg>',
  };

  function zone(accept, multiple, text) {
    return `<label class="zona" id="imZona"><input type="file" id="imArchivos" accept="${accept}"${multiple ? " multiple" : ""}>
      <span class="zIc">↥</span><b>${text}</b><small>o pulsa aquí para elegir${multiple ? "los" : "lo"}</small>
      <span class="zNom" id="imNombres"></span></label>`;
  }

  function importView() {
    if (IMP.informe) return preview();
    const success = IMP.hecho ? `<div class="exito"><b>✓ ${esc(IMP.hecho)}</b>
      <button class="btn" data-acc="verPanelDatos">Ver mi panel →</button></div>` : "";
    const op = (id, title, text) => `<button class="imOp${IMP.origen === id ? " sel" : ""}" data-acc="imOrigen" data-id="${id}">
      <span class="ic">${ICONOS[id]}</span><b>${title}</b><small>${text}</small></button>`;
    let step;
    if (IMP.origen === "myinvestor") {
      step = `<ol class="pasos">
          <li>Entra en MyInvestor desde el ordenador y abre <b>cada uno de tus fondos</b>.</li>
          <li>Pulsa <b>«Plusvalías y minusvalías»</b> y descarga el <b>CSV</b>. No le cambies el nombre: lleva el ISIN del fondo.</li>
          <li>Arrastra aquí todos los archivos a la vez.</li></ol>
        ${zone(".csv", true, "Arrastra aquí los CSV de MyInvestor")}
        <p class="ayuda">Cada importación sustituye lo que importaste antes de ese mismo fondo: repítela cada mes sin miedo a duplicar.
          MyInvestor no permite descargar las órdenes de ETF o acciones: haz capturas y usa la opción «Con ayuda de una IA».</p>`;
    } else if (IMP.origen === "plantilla") {
      step = `<ol class="pasos">
          <li>Descarga la plantilla: <a class="btn" href="api/plantilla.xlsx" download>Excel</a>
            <a class="btn" href="api/plantilla.csv" download>CSV</a></li>
          <li>Rellena una fila por operación. En la hoja «Ejemplo» tienes cinco filas de muestra.</li>
          <li>Guárdala y arrástrala aquí.</li></ol>
        ${zone(".xlsx,.csv,.txt", false, "Arrastra aquí tu plantilla")}`;
    } else {
      step = `<ol class="pasos">
          <li><b>Copia el prompt</b>: <button class="btn" data-acc="imCopiar" id="imCopiarBtn">Copiar prompt</button>
            <details class="verPrompt"><summary>Ver el prompt</summary><pre id="imPrompt">${esc(IMP.prompt || "Cargando…")}</pre></details></li>
          <li>Abre ChatGPT, Gemini o la IA que uses. Pega el prompt y, debajo, tu extracto, o adjunta el PDF o
            <b>capturas de pantalla</b> de tus órdenes (así se importan, por ejemplo, las compras de ETF o acciones de MyInvestor).
            <span class="alerta">Antes, borra (o tapa en las capturas) tu nombre, DNI, IBAN, números de cuenta y cualquier dato personal.</span></li>
          <li>Copia su respuesta y pégala aquí:</li></ol>
        <textarea id="imTexto" class="imTexto" rows="8" spellcheck="false"
          placeholder="fecha;identificador;nombre;tipo_producto;tipo_movimiento;unidades;importe;moneda;comision;nota"></textarea>`;
    }
    return `${success}<section class="tarjeta"><header><h2>Importar datos</h2>
        <span class="subt">Trae tus movimientos de golpe. Antes de guardar nada verás una vista previa.</span></header>
      <div class="imOps">
        ${op("myinvestor", "MyInvestor", "El CSV de cada fondo")}
        ${op("plantilla", "Plantilla", "Excel o CSV, para cualquier banco")}
        ${op("ia", "Con ayuda de una IA", "Convierte el extracto de tu banco")}
      </div>
      <p class="ayuda" style="margin-top:14px">¿Tu banco o bróker no está (Trade Republic, Bankinter, Indexa…)?
        Usa la plantilla o la opción «Con ayuda de una IA».</p>
      <div class="imPaso">${step}
        <div class="imErr" id="imFallo" hidden></div>
        <div class="imAcc"><span class="sp"></span>
          <button class="btn prim" data-acc="imRevisar" id="imRevisarBtn">Revisar antes de importar</button></div>
      </div></section>`;
  }

  function bindImport() {
    const inp = $("#imArchivos"), z = $("#imZona");
    if (inp) {
      const sample = () => {
        IMP.archivos = [...inp.files];
        $("#imNombres").textContent = IMP.archivos.map(f => f.name).join(" · ");
        z.classList.toggle("lleno", IMP.archivos.length > 0);
      };
      inp.onchange = sample;
      z.ondragover = e => { e.preventDefault(); z.classList.add("encima"); };
      z.ondragleave = () => z.classList.remove("encima");
      z.ondrop = e => {
        e.preventDefault();
        z.classList.remove("encima");
        inp.files = e.dataTransfer.files;
        sample();
      };
    }
    if (IMP.origen === "ia" && !IMP.prompt) {
      api("GET", "api/prompt").then(j => { IMP.prompt = j.texto; const pre = $("#imPrompt"); if (pre) pre.textContent = j.texto; });
    }
  }

  async function reviewImport() {
    const fd = new FormData();
    fd.append("origen", IMP.origen);
    const inp = $("#imArchivos");
    if (inp) [...inp.files].forEach(f => fd.append("archivos", f));
    const txt = $("#imTexto");
    if (txt) fd.append("texto", txt.value);
    const b = $("#imRevisarBtn"), failure = $("#imFallo");
    failure.hidden = true;
    b.disabled = true;
    b.textContent = "Revisando y buscando precios…";
    try {
      const r = await fetch("api/importar/previsualizar", { method: "POST", body: fd, headers: profileHeader() });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error((j.errores || ["Algo ha fallado al leerlo."]).join("\n"));
      IMP.informe = j.informe;
      IMP.token = j.token;
      IMP.hecho = null;
      render();
    } catch (x) {
      failure.textContent = x.message;
      failure.hidden = false;
      b.disabled = false;
      b.textContent = "Revisar antes de importar";
    }
  }

  function preview() {
    const inf = IMP.informe, t = inf.totales;
    const n = inf.añadidos + inf.saldos;
    const figure = (et, v, extra = "") => `<div class="cifra"><span>${et}</span><b>${v}</b>${extra ? `<small>${extra}</small>` : ""}</div>`;
    const errors = inf.errores.length ? `<div class="imErr"><b>${inf.errores.length} ${inf.errores.length === 1 ? "fila tiene" : "filas tienen"} problemas y no se importará${inf.errores.length === 1 ? "" : "n"}:</b>
      <ul>${inf.errores.map(e => `<li><span class="fila">${typeof e.fila === "number" ? "Fila " + e.fila : esc(e.fila)}</span>${esc(e.mensaje)}</li>`).join("")}</ul></div>` : "";
    const warnings = inf.avisos.map(a => `<div class="av"><span>⚠</span><span>${esc(a)}</span></div>`).join("");
    const newEntries = inf.productosNuevos.length ? `<div class="imNuevos"><div class="secc">Productos nuevos que se crearán</div>
      ${inf.productosNuevos.map(p => `<div class="imProd"><b>${esc(p.nombre)}</b>
        <span class="meta"><span>${esc(E.tipos[p.tipo] || p.tipo)}</span><span>${esc(p.codigo || "valor a mano")}</span>
        <span>${esc(E.fuentes[p.fuente])}</span>${p.precio ? `<span>${num(p.precio)} ${esc(p.monedaPrecio)} · ${date(p.fechaPrecio)}</span>` : ""}</span></div>`).join("")}</div>` : "";
    const transfers = (inf.traspasosMyInvestor || []).map((t, i) => {
      const r = t.respuesta || t.sugerencia || {};
      const source = r.origen || "ninguno";
      const lots = (t.detalle && t.detalle.length) ? t.detalle : [[null, t.coste]];
      const dateOf = k => (r.fechas && r.fechas[k] != null) ? r.fechas[k] : (r.fecha || "");
      const undated = source !== "ninguno" && lots.some((l, k) => !dateOf(k));
      const state = t.hecho
        ? `<p class="relleno">✓ Se creará un traspaso desde «${esc((t.origenes.find(o => o.id === source) || {}).nombre || source)}»: no contará dos veces ni como venta.</p>`
        : t.error ? `<div class="imErr">${esc(t.error)}</div>`
        : undated ? `<div class="imErr">Falta la fecha del traspaso. Sin ella no se puede crear: ponla para seguir.</div>` : "";
      return `<div class="bloque traspasoMI" style="margin-top:12px" data-ref="${esc(t.ref)}">
        <b>«${esc(t.nombre)}»: ${t.lotes} ${t.lotes === 1 ? "lote viene" : "lotes vienen"} de un traspaso</b>
        <p class="ayuda">${eur(t.coste)} de coste, ≈ ${num(t.unidades, 4)} participaciones. MyInvestor no dice de qué fondo
          venían. Si ese fondo está en FinAppGo, elígelo y pon la fecha del traspaso: FinAppGo hará un traspaso de verdad, el dinero
          no contará dos veces y verás cómo salió de él, aunque su extracto ya no traiga lo que se traspasó.</p>
        <div class="rejilla" style="margin-top:10px">
          ${field("Venía de", `<select name="tmi_origen_${i}" data-i="${i}"><option value="ninguno">No está en FinAppGo: importar como compras</option>
            ${t.origenes.map(o => `<option value="${esc(o.id)}"${o.id === source ? " selected" : ""}>${esc(o.nombre)}</option>`).join("")}</select>`)}
        </div>
        <div class="lotesTraspaso">${lots.map((l, k) => {
          const f = dateOf(k), estimate = f === "estimar";
          return `<div class="loteTraspaso">
            <span class="loteEtq">${lots.length > 1 ? `Lote ${k + 1}: ` : ""}${eur(l[1])}${l[0] ? ` · comprado el ${date(l[0])}` : ""}</span>
            <label class="campo"><span>Fecha del traspaso</span>
              <input type="date" name="tmi_fecha_${i}_${k}" max="${hoy()}" value="${estimate ? "" : esc(f)}"${estimate ? " disabled" : ""}></label>
            <label class="noSe"><input type="checkbox" name="tmi_estimar_${i}_${k}"${estimate ? " checked" : ""}> No la sé: que FinAppGo la estime</label>
          </div>`;
        }).join("")}
          <p class="ayuda">La fecha está en el historial de órdenes de MyInvestor. Si no la encuentras, FinAppGo la estima con los
            precios de los dos fondos y la marca como estimada.</p></div>${state}${t.aviso ? `<div class="comprueba">${esc(t.aviso)}</div>` : ""}</div>`;
    }).join("");
    const ESTADO = { nuevo: "Nuevo", repetido: "Ya estaba", error: "Con error" };
    const rows = inf.filas.map(f => `<tr class="est-${f.estado}"><td>${date(f.fecha)}</td>
      <td style="text-align:left">${esc(f.productoNombre)}</td><td style="text-align:left">${esc(E.tiposMov[f.tipo] || "Saldo")}</td>
      <td>${f.unidades ? num(f.unidades) : "—"}</td><td>${eur(f.importe)}</td>
      <td style="text-align:left">${f.marcas.map(m => `<span class="etqImp">${esc(m)}</span>`).join("")}</td>
      <td><span class="estado">${ESTADO[f.estado]}</span></td></tr>`).join("");
    return `<section class="tarjeta"><header><h2>Vista previa</h2>
        <span class="subt">Todavía no se ha guardado nada.</span></header>
      <div class="cifras">
        ${figure("Movimientos nuevos", inf.añadidos, t.numCompras ? `${t.numCompras} compras` : "")}
        ${figure("Invertido en compras", eur(t.compras))}
        ${figure("Ventas y dividendos", eur(t.ventas + t.dividendos))}
        ${inf.saldos ? figure("Saldos anotados", inf.saldos) : ""}
        ${inf.repetidos ? figure("Ya estaban", inf.repetidos, "se omiten") : ""}
        ${inf.sustituidos ? figure("Sustituyen a", inf.sustituidos, "importados antes") : ""}
      </div>
      <div class="comprueba"><b>Compara estas cifras con tu banco antes de confirmar.</b>
        ${IMP.origen === "ia" ? "Una IA puede equivocarse al copiar números o saltarse alguna fila: revisa sobre todo el total invertido." : ""}</div>
      ${warnings}${errors}${transfers ? `<div class="imNuevos"><div class="secc">Traspasos</div>${transfers}</div>` : ""}${newEntries}
      ${rows ? `<div class="tablaEnv alto" style="margin-top:16px"><table class="dt"><thead><tr><th>Fecha</th>
        <th style="text-align:left">Producto</th><th style="text-align:left">Tipo</th><th>Unidades</th><th>Importe</th>
        <th style="text-align:left"></th><th>Estado</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
      <div class="imAcc"><button class="btn" data-acc="imCancelar">Cancelar</button><span class="sp"></span>
        <button class="btn prim" data-acc="imConfirmar" id="imConfirmarBtn"${n ? "" : " disabled"}>
          ${n ? `Importar ${n} ${n === 1 ? "dato" : "datos"}` : "No hay nada nuevo que importar"}</button></div></section>`;
  }

  function readAnswers() {
    const inf = IMP.informe;
    const out = {};
    (inf && inf.traspasosMyInvestor || []).forEach((t, i) => {
      const o = document.querySelector(`[name="tmi_origen_${i}"]`);
      if (!o) return;
      const n = (t.detalle && t.detalle.length) || 1, dates = [];
      for (let k = 0; k < n; k++) {
        const est = document.querySelector(`[name="tmi_estimar_${i}_${k}"]`), f = document.querySelector(`[name="tmi_fecha_${i}_${k}"]`);
        dates.push(est && est.checked ? "estimar" : (f ? f.value : ""));
      }
      out[t.ref] = { origen: o.value, fechas: dates, fecha: dates[0] };
    });
    return out;
  }
  async function reviewTransfers() {
    const answers = readAnswers();
    try {
      const j = await api("POST", "api/importar/revisar", { token: IMP.token, respuestas: answers });
      IMP.informe = j.informe;
      IMP.respuestas = answers;
      render();
    } catch (x) { alert(x.message); }
  }
  document.addEventListener("change", e => {
    if (e.target.closest && e.target.closest(".traspasoMI") && E.vista === "importar" && IMP.informe) reviewTransfers();
  });

  async function confirmImport() {
    const b = $("#imConfirmarBtn");
    const missing = Object.values(readAnswers()).filter(r => r.origen && r.origen !== "ninguno" && r.fechas.some(f => !f)).length;
    if (missing) {
      alert(missing === 1 ? "Falta la fecha de un traspaso. Ponla, o elige «No está en FinAppGo», antes de importar."
        : `Faltan las fechas de ${missing} traspasos. Ponlas, o elige «No está en FinAppGo», antes de importar.`);
      return;
    }
    b.disabled = true;
    b.textContent = "Importando…";
    try {
      const j = await api("POST", "api/importar/confirmar", { token: IMP.token, respuestas: readAnswers() });
      E.cfg = j.cartera;
      window.EDITOR_SUCIO = true;
      const i = j.informe;
      const pl = (n, uno, multiple) => `${n} ${n === 1 ? uno : multiple}`;
      IMP.hecho = "Importado: " + [i.añadidos && pl(i.añadidos, "movimiento", "movimientos"),
        i.saldos && pl(i.saldos, "saldo", "saldos")].filter(Boolean).join(" y ") +
        ((n => n ? ` (${pl(n, "traspaso", "traspasos")} desde otro fondo)` : "")((i.traspasosMyInvestor || []).filter(t => t.hecho).length)) +
        (i.repetidos ? `. ${pl(i.repetidos, "ya estaba y se ha omitido", "ya estaban y se han omitido")}` : "") + ".";
      IMP.informe = null;
      IMP.token = null;
      render();
      notify(j.avisos);
    } catch (x) {
      alert(x.message);
      b.disabled = false;
    }
  }

  const pendingRecurring = () => window.Calculos && E.cfg
    ? window.Calculos.periodicasPendientes(E.cfg.periodicas, E.cfg.productos.map(p => p.id), hoy()) : [];

  function recurringNotice() {
    return pendingRecurring().map(x => {
      const key = esc(x.producto + "|" + x.dia);
      return `<div class="av"><span>↻</span><span>Aportación periódica de ${eur(x.importe)} a ${esc(name(prod(x.producto)))}
        (día ${x.dia}): ${x.cuantas === 1 ? `toca anotar la del ${date(x.desde)}` : `faltan ${x.cuantas}, desde el ${date(x.desde)}`}.
        <button class="btn" data-acc="periodicaPendiente" data-id="${key}" style="margin-left:6px">Revisar y añadir</button>
        <button class="btn" data-acc="periodicaOlvidar" data-id="${key}">No me lo recuerdes</button></span></div>`;
    }).join("");
  }

  function contributionForm(pre) {
    const entries = E.cfg.productos.filter(p => !balanceOnly(p));
    if (!entries.length) { alert("Primero añade un producto en «Productos»."); return; }
    const filter = prod(E.filtro);
    const d = pre || { producto: filter && !balanceOnly(filter) ? filter.id : entries[0].id, dia: 1, hasta: hoy() };
    const f = openModal("Aportación periódica", `
      <p>¿Aportas lo mismo cada mes a un fondo, un ETF o un plan? Dile a FinAppGo cuánto, qué día y desde cuándo, y prepara
        una compra por mes con el precio de cierre de ese día.</p>
      <div class="rejilla">
        ${field("Producto", `<select name="producto">${entries.map(p =>
          `<option value="${esc(p.id)}">${esc(name(p))}</option>`).join("")}</select>`, "", "ancho")}
        ${field("Cuánto cada mes", '<div class="conSufijo"><input name="importe" inputmode="decimal" placeholder="200,00"><span>€</span></div>')}
        ${field("Qué día del mes", '<input name="dia" inputmode="numeric" placeholder="1">', "si ese día no hay cierre, el anterior")}
        ${field("Desde", `<input type="date" name="desde" max="${hoy()}">`)}
        ${field("Hasta", `<input type="date" name="hasta" max="${hoy()}">`)}
      </div>
      <p class="ayuda">Son <b>estimadas</b>: tu banco puede ejecutarlas otro día o a otro precio. Antes de guardar verás la
        lista; después puedes corregir cada una con lo que diga tu banco. Las que ya tengas anotadas se saltan.</p>`,
    async f => {
      const data = fields(f);
      const j = await api("POST", "api/periodicas/ver", data);
      return () => reviewContribution(data, j.plan);
    }, "Ver las aportaciones");
    fillIn(f, { ...d, importe: d.importe != null ? decimal(d.importe) : "" });
  }

  function reviewContribution(data, pl) {
    const etq = { nueva: "Se añade", repetida: "Ya la tienes", sinPrecio: "Sin precio ese día" };
    const rows = pl.lineas.map(x => `<tr${x.estado === "nueva" ? "" : ' class="subt"'}><td>${date(x.fecha)}</td>
      <td>${eur(x.importe)}</td><td>${x.precio ? num(x.precio) + " €" : "—"}</td>
      <td>${x.unidades ? num(x.unidades) : "—"}</td><td style="text-align:left">${etq[x.estado]}</td></tr>`).join("");
    const n = pl.nuevas;
    const f = openModal("Revisa las aportaciones", `
      <p><b>${esc(pl.nombre)}</b>: ${pl.lineas.length} ${pl.lineas.length === 1 ? "aportación" : "aportaciones"} de
        ${eur(pl.importe)}, el día ${pl.dia} de cada mes. Se ${n === 1 ? "añade" : "añaden"} <b>${n}</b>${n < pl.lineas.length ? "; el resto se salta" : ""}.</p>
      <div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th><th>Importe</th><th>Precio de cierre</th>
        <th>Participaciones</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="ayuda">Cada una se guarda como una compra con la nota «Aportación periódica (estimada…)». FinAppGo se acuerda de
        esta aportación y, cuando toque la siguiente, te avisará aquí, en Movimientos.</p>`,
    async () => {
      const j = await api("POST", "api/periodicas/crear", data);
      E.cfg = j.cartera;
      COP.lista = null;
      window.EDITOR_SUCIO = true;
      notify(j.avisos);
      E.vista = "movimientos";
      preferences.guarda("patrimonio.editor", "movimientos");
      return null;
    }, n ? `Añadir ${n} ${n === 1 ? "aportación" : "aportaciones"}` : "Nada que añadir");
    if (!n) f.querySelector("[type=submit]").disabled = true;
  }

  const COP = { lista: null };

  function backupsView() {
    if (COP.lista === null) {
      api("GET", "api/copias").then(j => { COP.lista = j.copias; if (E.vista === "copias") render(); });
    }
    const personal = E.modo === "propio";
    const rows = (COP.lista || []).map(c => `<tr><td>${date(c.fecha.slice(0, 10))} <small>${c.fecha.slice(11, 16)}</small></td>
      <td style="text-align:left">${esc(c.motivo)}</td><td>${c.productos}</td><td>${c.movimientos}</td>
      <td class="acc"><button data-acc="recuperarCopia" data-id="${esc(c.archivo)}">Recuperar</button></td></tr>`).join("");
    return `<section class="tarjeta"><header><h2>Copia de seguridad</h2>
        <span class="subt">Un archivo con toda tu cartera, para guardarlo donde quieras o pasarlo a otro ordenador.</span></header>
      <div class="dosCol">
        <div class="bloque"><b>Guardar una copia</b>
          <p class="ayuda">Descarga un archivo <code>.json</code> con todos tus productos, movimientos y saldos.
            Guárdalo en tu nube o en un USB de vez en cuando.</p>
          ${personal ? '<a class="btn prim" href="api/copia/descargar" download>Descargar copia</a>'
            : '<span class="subt">Disponible cuando empieces tu propia cartera.</span>'}</div>
        <div class="bloque"><b>Recuperar desde un archivo</b>
          <p class="ayuda">Sube una copia que descargaste antes. Sustituye la cartera actual (que se guarda antes, por si acaso).</p>
          ${zone(".json", false, "Arrastra aquí tu copia")}
          <div class="imErr" id="copFallo" hidden></div>
          <div class="imAcc"><span class="sp"></span><button class="btn prim" data-acc="subirCopia" id="copSubirBtn">Recuperar esta copia</button></div></div>
      </div></section>

      <section class="tarjeta"><header><h2>Tus datos en Excel</h2>
        <span class="subt">Para revisarlos, hacer tus propias cuentas o llevártelos a otra app.</span></header>
      <p class="ayuda" style="margin-top:0">Un archivo <code>.xlsx</code> (se abre con Excel, Google Sheets o LibreOffice) con
        todos tus movimientos y saldos, y una hoja con la ficha de cada producto. La hoja «Movimientos» tiene el mismo
        formato que la plantilla de importación: puedes cambiarla y volver a importarla.</p>
      <a class="btn prim" href="api/exportar-excel" download>Descargar en Excel</a></section>

      <section class="tarjeta"><header><h2>Copias automáticas</h2>
        <span class="subt">Antes de cada cambio se guarda una copia (las últimas 20). Si te equivocas, vuelve a una anterior.</span></header>
      ${COP.lista === null ? '<p class="cargando">Cargando…</p>' : rows
        ? `<div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th><th style="text-align:left">Motivo</th>
          <th>Productos</th><th>Movimientos</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
        : '<p class="subt">Todavía no hay copias: se crean solas en cuanto cambias algo.</p>'}</section>

      <section class="tarjeta"><header><h2>Publicar como web</h2>
        <span class="subt">Tu panel en un solo archivo, de solo lectura, para enseñarlo o subirlo a internet.</span></header>
      <label class="interruptor"><input type="checkbox" id="webOcultar"><span class="pista"></span>
        <span><b>Ocultar importes</b><small>Solo se ven porcentajes y la forma de las gráficas. Las cantidades reales no
          van dentro del archivo, ni siquiera escondidas.</small></span></label>
      <ol class="pasos" style="margin-top:18px">
        <li><button class="btn prim" data-acc="exportarWeb">Descargar la web</button>
          Puedes abrirla con doble clic o mandarla por correo.</li>
        <li>Para tener un enlace: crea una carpeta, mete dentro el archivo, cámbiale el nombre a <code>index.html</code>
          y arrastra la carpeta a <a href="https://app.netlify.com/drop" target="_blank" rel="noopener">app.netlify.com/drop</a>.
          En unos segundos te da una dirección para compartir.</li>
      </ol>
      <p class="ayuda">La web lleva la fecha de hoy: cuando actualices tus datos, vuelve a descargarla y súbela otra vez.</p></section>`;
  }

  async function uploadBackup() {
    const inp = $("#imArchivos"), failure = $("#copFallo");
    failure.hidden = true;
    if (!inp.files.length) { failure.textContent = "Elige primero el archivo de la copia."; failure.hidden = false; return; }
    if (E.modo === "propio" && !confirm("Esto sustituye tu cartera actual por la de la copia. Tu cartera actual se guarda antes en «Copias automáticas». ¿Seguir?")) return;
    const fd = new FormData();
    fd.append("archivo", inp.files[0]);
    const r = await fetch("api/copia/subir", { method: "POST", body: fd, headers: profileHeader() });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) { failure.textContent = (j.errores || ["No he podido leer la copia."]).join("\n"); failure.hidden = false; return; }
    preferences.guarda("patrimonio.tab", "datos");
    preferences.guarda("patrimonio.editor", "productos");
    location.reload();
  }

  async function restoreBackup(file) {
    const c = COP.lista.find(x => x.archivo === file);
    if (!confirm(`¿Volver a la copia del ${date(c.fecha.slice(0, 10))} a las ${c.fecha.slice(11, 16)} (${c.productos} productos, ${c.movimientos} movimientos)?\n\nTu cartera actual se guarda antes, así que puedes deshacerlo.`)) return;
    try {
      await api("POST", "api/copia/recuperar", { archivo: file });
      preferences.guarda("patrimonio.tab", "datos");
      location.reload();
    } catch (x) { alert(x.message); }
  }

  api("GET", "api/version").then(v => {
    const pie = $("#ayudaVersion");
    if (pie) pie.innerHTML = `Versión ${esc(v.actual)}. ¿Otra duda o un fallo? Cuéntalo en la
      <a href="${esc(v.repo)}" target="_blank" rel="noopener">página del proyecto en GitHub</a>.`;
    if (!v.hayNueva) return;
    $("#bannerVersionTexto").innerHTML =
      `<b>Hay una versión nueva (${esc(v.ultima)}).</b> Para actualizar, ejecuta
      <code>docker compose pull &amp;&amp; docker compose up -d</code> en el equipo donde tienes FinAppGo.`;
    $("#bannerVersion").hidden = false;
  }).catch(() => {  });

  setTimeout(() => api("GET", "api/novedades").then(n => {
    const view = preferences.lee("finappgo.novedades") || "";

    const force = new URLSearchParams(location.search).has("novedades");
    let release = null, key = "";
    if (n.nueva) { release = n.nueva; key = "nueva:" + n.nueva.version + (n.nueva.video ? ":v" : ""); }
    else if (n.tuya && (n.tuya.novedades.length || n.tuya.video) && D && (D.modo !== "demo" || force)) {
      release = n.tuya; key = "tuya:" + n.tuya.version + (n.tuya.video ? ":v" : "");
    }
    if (!release || (view === key && !force) || $("#modal").open || document.body.classList.contains("video")) return;
    preferences.guarda("finappgo.novedades", key);
    const entries = release.novedades.length ? `<ul class="listaNovedades">${release.novedades.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";

    const video = release.video ? `<div class="verEnVideo"><b>¿Prefieres verlo en vídeo?</b>
       <a class="btn prim" href="${esc(release.video)}" target="_blank" rel="noopener">▶ Ver las novedades en YouTube</a></div>` : "";
    const f = openModal(n.nueva ? `Hay una versión nueva: ${esc(release.titulo || release.version)}` : `Novedades de ${esc(release.titulo || "FinAppGo " + release.version)}`,
      `${video}${n.nueva ? `<p>Tienes la ${esc(n.actual)}. Esto es lo que trae la ${esc(release.version)}:</p>` : "<p>Esto es lo que ha cambiado desde tu versión anterior:</p>"}
       ${entries}<div class="imAcc">${n.nueva ? `<a class="btn" href="${esc(n.repo)}" target="_blank" rel="noopener">Descargar en GitHub</a>` : ""}</div>
       ${n.nueva ? (n.docker ? '<p class="ayuda">Para actualizar: <code>docker compose pull &amp;&amp; docker compose up -d</code>. Tus datos no se tocan.</p>'
         : '<p class="ayuda">Para actualizar sin perder nada, sigue los pasos de Ayuda → «¿Cómo actualizo a una versión nueva?».</p>') : ""}`,
      async () => null, "Entendido");
    f.querySelector("footer [data-cerrar]").hidden = true;
  }).catch(() => {  }), 2500);

  const ACC = {
    empezar: start,
    reiniciar: reset,
    verPanel() { preferences.guarda("patrimonio.tab", "patrimonio"); location.reload(); },
    nuevoProducto: personalOnly(() => productForm(null)),
    editarProducto: personalOnly(id => productForm(prod(id))),
    borrarProducto: personalOnly(deleteProduct),
    nuevoMov: personalOnly(() => movementForm(null)),
    nuevoInteres: personalOnly(id => movementForm(null, id, "dividendo")),
    nuevoGasto: personalOnly(id => movementForm(null, id, "comision")),
    periodica: personalOnly(() => contributionForm()),
    periodicaPendiente: personalOnly(key => {
      const x = pendingRecurring().find(r => r.producto + "|" + r.dia === key);
      if (x) contributionForm({ producto: x.producto, importe: x.importe, dia: x.dia, desde: x.desde, hasta: hoy() });
    }),
    periodicaOlvidar: personalOnly(async key => {
      const x = pendingRecurring().find(r => r.producto + "|" + r.dia === key);
      if (!x || !confirm("¿Dejo de recordarte esta aportación periódica? Las compras que ya anotaste no se tocan.")) return;
      try {
        const j = await api("POST", "api/periodicas/olvidar", { producto: x.producto, dia: x.dia });
        E.cfg = j.cartera;
        render();
      } catch (e) { alert(e.message); }
    }),
    nuevoTraspaso: personalOnly(() => transferForm(null)),
    nuevoAjuste: personalOnly(() => adjustmentForm(null)),
    objetivo: personalOnly(() => goalForm()),
    reparto: (...a) => (E.modo === "demo" ? allocationForm() : personalOnly(() => allocationForm())(...a)),
    colchon: personalOnly(() => emergencyFundForm()),
    editarMov: personalOnly(id => movementForm(E.cfg.movimientos.find(m => m.id === id))),
    borrarMov: personalOnly(deleteMovement),
    nuevoValor: personalOnly(id => valuationForm(null, id)),
    editarValor: personalOnly(id => valuationForm(E.cfg.valoraciones.find(v => v.id === id))),
    borrarValor: personalOnly(deleteValuation),
    todosValores: personalOnly(allValues),
    repartirColores: personalOnly(async () => {
      try {
        const j = await api("POST", "api/repartir-colores");
        E.cfg = j.cartera;
        window.EDITOR_SUCIO = true;
        render();
      } catch (x) { alert(x.message); }
    }),
    imOrigen(id) { IMP.origen = id; IMP.hecho = null; render(); },
    imRevisar: personalOnly(reviewImport),
    imCancelar() { IMP.informe = null; IMP.token = null; render(); },
    imConfirmar: confirmImport,
    subirCopia: uploadBackup,
    recuperarCopia: restoreBackup,
    exportarWeb() { location.href = "api/exportar-web?ocultar=" + ($("#webOcultar").checked ? "1" : "0"); },
    verPanelDatos() { preferences.guarda("patrimonio.tab", "patrimonio"); location.reload(); },
    async imCopiar() {
      const txt = IMP.prompt || (await api("GET", "api/prompt")).texto;
      IMP.prompt = txt;
      try { await navigator.clipboard.writeText(txt); } catch (e) {
        const ta = document.createElement("textarea"); ta.value = txt; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove();
      }
      const b = $("#imCopiarBtn");
      if (b) { b.textContent = "✓ Copiado"; setTimeout(() => { b.textContent = "Copiar prompt"; }, 2000); }
    },
  };
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-acc]");
    if (b && ACC[b.dataset.acc]) ACC[b.dataset.acc](b.dataset.id);
  });
  const btnDiag = $("#btnDiagnostico");
  if (btnDiag) btnDiag.onclick = async () => {
    try {
      const j = await api("GET", "api/diagnostico");
      try { await navigator.clipboard.writeText(j.texto); } catch (e) {
        const ta = document.createElement("textarea"); ta.value = j.texto; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove();
      }
      btnDiag.textContent = "✓ Copiado: pégalo en el issue";
      setTimeout(() => { btnDiag.textContent = "Copiar informe para soporte"; }, 3000);
    } catch (x) { alert(x.message); }
  };
  const startButton = $("#btnEmpezar");
  if (startButton) startButton.onclick = start;

  (function channel() {
    const K = window.CANAL;
    if (!K) return;
    document.querySelectorAll(".autorCanal").forEach(el => { el.textContent = K.autor; });
    document.querySelectorAll(".enlaceCanal").forEach(el => { el.href = K.canal; });
    document.querySelectorAll(".enlaceSuscribir").forEach(el => { el.href = K.suscribir; });
    const nov = $("#ayudaNovedades");
    if (nov && K.novedades) { nov.href = K.novedades; nov.hidden = false; }

    if (!D || D.modo !== "propio" || !(D.productos || []).length) return;
    let est = {};
    try { est = JSON.parse(preferences.lee("patrimonio.canal") || "{}"); } catch (e) { est = {}; }
    const MES = 30 * 24 * 3600 * 1000;
    if (est.hecho || (est.veces || 0) >= 2 || (est.veces === 1 && Date.now() - (est.ultima || 0) < MES)) return;
    const save = changes => preferences.guarda("patrimonio.canal", JSON.stringify({ ...est, ...changes }));

    setTimeout(() => {
      if (document.body.classList.contains("video") || $("#modal").open) return;
      const t = document.createElement("div");
      t.className = "tarjetaCanal";
      t.setAttribute("role", "dialog");
      t.innerHTML = `<button class="x" aria-label="Cerrar">×</button>
        <b>¿Te está siendo útil?</b>
        <p>Esta herramienta es gratis. La hago para mi canal de YouTube, donde cuento cómo invierto:
          suscribirte es la mejor forma de apoyarla. — ${esc(K.autor)}</p>
        <div class="botones"><a class="btn prim" href="${esc(K.suscribir)}" target="_blank" rel="noopener">▶ Suscribirme</a>
          <button class="ahoraNo">Ahora no</button></div>`;
      const close = () => { t.remove(); save({ veces: (est.veces || 0) + 1, ultima: Date.now() }); };
      t.querySelector(".x").onclick = close;
      t.querySelector(".ahoraNo").onclick = close;
      t.querySelector("a").onclick = () => { save({ hecho: true }); setTimeout(() => t.remove(), 300); };
      document.body.appendChild(t);
    }, 6000);
  })();

  window.Editor = { mostrar: render, objetivo: () => ACC.objetivo(), reparto: () => ACC.reparto(),
    colchon: () => ACC.colchon(), perfiles: profiles };

  document.dispatchEvent(new Event("finappgo:editor"));
  load().then(render).catch(x => {
    const cont = $("#editor");
    if (cont) cont.innerHTML = `<div class="av"><span>⚠</span><span>${esc(x.message)}</span></div>`;
  });
})();
