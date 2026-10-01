"use strict";
const $ = id => document.getElementById(id);
const labels = {pending: "Pendente", confirmed: "Confirmado", corrected: "Corrigido", rejected: "Rejeitado"};
const colors = {pending: "#ae731e", confirmed: "#19604d", corrected: "#2973b7", rejected: "#bd4839"};
let points = [], selected = null, routeId = "", provider = null, busy = false, dirty = false;
let map = null, layers = null, draft = null, tiles = null, matrixId = null, entriesOffset = 0;
let networkMatrices = [], macroPlanId = null;

function notice(message, error = false) { $("notice").textContent = message; $("notice").className = error ? "error" : ""; }
async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Revise os campos informados.");
  return data;
}
function post(path, data) { return request(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)}); }
async function action(work) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("button,input,select,textarea")];
  const previous = controls.map(control => control.disabled);
  controls.forEach(control => control.disabled = true);
  try { await work(); } catch (error) { notice(error.message, true); }
  finally { busy = false; controls.forEach((control, i) => control.disabled = previous[i]); updateAvailability(); }
}
function canLeave() { return !dirty || window.confirm("Há um ajuste não salvo. Deseja descartá-lo?"); }
function make(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }

function initializeMap() {
  if (!window.L) { $("map").append(make("p", "Mapa indisponível. A revisão por coordenadas continua funcionando.")); return; }
  map = L.map("map").setView([-23.55, -46.63], 13);
  layers = L.layerGroup().addTo(map);
  map.on("click", event => {
    if (!selected || busy) return;
    $("review-status").value = "corrected";
    $("latitude").value = event.latlng.lat.toFixed(7);
    $("longitude").value = event.latlng.lng.toFixed(7);
    dirty = true; updateDraft(); updateAvailability();
  });
}
function updateDraft() {
  if (!map) return;
  if (draft) { draft.remove(); draft = null; }
  const lat = Number($("latitude").value), lng = Number($("longitude").value);
  if (dirty && selected && $("review-status").value === "corrected" && Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
    draft = L.circleMarker([lat, lng], {radius: 12, color: "#7143a8", fillOpacity: .15, dashArray: "3 3"}).addTo(map);
  }
}
function visiblePoints() {
  const search = $("search").value.toLocaleLowerCase();
  return points.filter(p => ($("filter").value === "all" || p.review_status === $("filter").value) &&
    (p.original_address + " " + p.original_neighborhood).toLocaleLowerCase().includes(search));
}
function renderPoints() {
  $("points").replaceChildren(); if (layers) layers.clearLayers();
  const visible = visiblePoints();
  $("point-count").textContent = visible.length;
  if (!visible.length) $("points").append(make("p", "Nenhum ponto encontrado."));
  visible.forEach(p => {
    const button = make("button", "", "point" + (selected?.id === p.id ? " selected" : ""));
    button.append(make("strong", p.original_address), make("small", `${p.original_neighborhood} · ${p.package_count} pacote(s)`), make("span", labels[p.review_status], "badge " + p.review_status));
    button.onclick = () => { if (!busy && canLeave()) selectPoint(p); };
    $("points").append(button);
    if (map) {
      const marker = L.circleMarker([p.effective_latitude, p.effective_longitude], {radius: selected?.id === p.id ? 10 : 7, color: colors[p.review_status], fillOpacity: .75, bubblingMouseEvents: false}).addTo(layers);
      marker.bindTooltip(make("span", p.original_address));
      marker.on("click", event => { L.DomEvent.stopPropagation(event); if (!busy && canLeave()) selectPoint(p); });
    }
  });
  if (map && selected) L.circleMarker([selected.imported_latitude, selected.imported_longitude], {radius: 14, color: "#45574e", fillOpacity: 0, dashArray: "3 3", interactive: false}).addTo(layers);
  const pending = points.filter(p => p.review_status === "pending").length;
  const rejected = points.filter(p => p.review_status === "rejected").length;
  $("summary").textContent = `${points.reduce((s, p) => s + p.package_count, 0)} pacotes · ${points.length} entradas · ${pending} pendentes · ${rejected} rejeitadas`;
  updateAvailability();
}
function fitPoints() { if (map && points.length) map.fitBounds(points.map(p => [p.effective_latitude, p.effective_longitude]), {padding: [35, 35], maxZoom: 17}); }
function updateAvailability() {
  $("compute").disabled = busy || !routeId || !points.length || points.some(p => !["confirmed", "corrected"].includes(p.review_status)) || points.length > (provider?.max_matrix_points || 200);
  $("latitude").disabled = busy || $("review-status").value !== "corrected";
  $("longitude").disabled = $("latitude").disabled;
  $("matrix-help").textContent = points.length > (provider?.max_matrix_points || 200) ? "Quantidade de entradas acima do limite da matriz." : $("compute").disabled ? "Confirme ou corrija todas as entradas antes do cálculo." : "Entradas revisadas. A matriz calcula os custos entre pares; o planejamento do circuito será feito na próxima etapa.";
  $("create-macro").disabled = busy || !routeId || !networkMatrices.length || !$("macro-matrix").value || points.some(p => !["confirmed", "corrected"].includes(p.review_status));
  $("macro-help").textContent = networkMatrices.length ? "O agrupamento respeita os limites informados e preserva cada pacote. Revise cada proposta antes de usá-la." : "É necessária uma matriz pedestre de rede atual. A estimativa em linha reta não serve para planejar.";
}
async function loadHistory(pointId) {
  try {
    const reviews = await request(`/api/v1/delivery-points/${pointId}/reviews`);
    if (selected?.id !== pointId) return;
    $("history").replaceChildren(...reviews.map(review => make("li", `Revisão ${review.revision} · ${labels[review.after.review_status]} · ${review.after.effective_latitude}, ${review.after.effective_longitude} · ${review.after.review_note || "Sem observação"}`)));
    if (!reviews.length) $("history").append(make("li", "Sem revisões registradas."));
  } catch (error) { if (selected?.id === pointId) $("history").replaceChildren(make("li", error.message)); }
}
function selectPoint(p) {
  selected = p; dirty = false;
  $("selection-empty").hidden = true; $("review-form").hidden = false;
  $("address").textContent = p.original_address;
  $("point-meta").textContent = `${p.original_city} · ${p.package_count} pacote(s) · revisão ${p.revision}`;
  $("original").textContent = `Importado: ${p.imported_latitude}, ${p.imported_longitude}`;
  $("review-status").value = p.review_status === "pending" ? "confirmed" : p.review_status;
  $("latitude").value = p.effective_latitude; $("longitude").value = p.effective_longitude; $("note").value = p.review_note || "";
  renderPoints(); updateDraft();
  if (map) map.panTo([p.effective_latitude, p.effective_longitude]);
  $("history").replaceChildren(make("li", "Carregando…")); loadHistory(p.id);
}
async function loadRoute(id) {
  routeId = id; selected = null; dirty = false; matrixId = null; macroPlanId = null; networkMatrices = [];
  $("review-form").hidden = true; $("selection-empty").hidden = false; $("matrix-detail").hidden = true; $("matrices").replaceChildren();
  $("macro-history").replaceChildren(); $("macro-detail").replaceChildren(); $("macro-matrix").replaceChildren();
  points = []; renderPoints(); updateDraft();
  if (!id) { $("matrices").replaceChildren(); return; }
  points = await request(`/api/v1/routes/${id}/delivery-points`);
  renderPoints(); fitPoints(); await loadMatrices();
}
async function loadRoutes(preferred = routeId) {
  const routes = [];
  for (let offset = 0; ; offset += 200) {
    const page = await request(`/api/v1/routes?limit=200&offset=${offset}`); routes.push(...page);
    if (page.length < 200) break;
  }
  $("routes").replaceChildren(make("option", "Selecione uma rota")); $("routes").firstChild.value = "";
  routes.forEach(route => { const option = make("option", `${route.external_id} · ${route.package_count} pacotes · ${route.id.slice(0, 8)}`); option.value = route.id; $("routes").append(option); });
  $("routes").value = routes.some(r => r.id === preferred) ? preferred : routes[0]?.id || "";
  await loadRoute($("routes").value);
}
async function loadMatrices() {
  const matrices = await request(`/api/v1/routes/${routeId}/walking-matrices`);
  const priorMatrix = $("macro-matrix").value;
  networkMatrices = matrices.filter(matrix => matrix.quality === "network" && !matrix.stale);
  $("macro-matrix").replaceChildren();
  networkMatrices.forEach(matrix => { const option = make("option", `${matrix.provider} · ${new Date(matrix.created_at).toLocaleString("pt-BR")} · ${matrix.point_count} entradas`); option.value = matrix.id; $("macro-matrix").append(option); });
  if (networkMatrices.some(matrix => matrix.id === priorMatrix)) $("macro-matrix").value = priorMatrix;
  $("matrices").replaceChildren();
  if (!matrices.length) { const tr = document.createElement("tr"), td = make("td", "Nenhuma matriz calculada para esta rota."); td.colSpan = 6; tr.append(td); $("matrices").append(tr); }
  matrices.forEach(matrix => {
    const tr = document.createElement("tr");
    [new Date(matrix.created_at).toLocaleString("pt-BR"), matrix.quality === "estimate_only" ? "Estimativa em linha reta" : matrix.provider + " · rede", matrix.point_count, matrix.unreachable_pairs, matrix.stale ? "Desatualizada" : "Atual"].forEach(value => tr.append(make("td", String(value))));
    const td = document.createElement("td"), button = make("button", "Ver pares", "secondary");
    button.onclick = () => action(async () => { matrixId = matrix.id; entriesOffset = 0; $("entries").replaceChildren(); $("matrix-detail").hidden = false; $("matrix-detail-summary").textContent = matrix.stale ? "Matriz histórica: calculada com uma revisão ou configuração anterior." : matrix.quality === "estimate_only" ? "Estimativa: não identifica barreiras ou acessos reais." : "Custos da rede pedestre configurada."; await loadEntries(); });
    td.append(button); tr.append(td); $("matrices").append(tr);
  });
  await loadMacroPlans(); updateAvailability();
}
async function loadMacroPlans() {
  if (!routeId) return;
  const plans = await request(`/api/v1/routes/${routeId}/macro-plans`);
  $("macro-history").replaceChildren();
  if (!plans.length) { $("macro-history").append(make("p", "Nenhuma proposta criada para esta rota.")); $("macro-detail").replaceChildren(); return; }
  plans.forEach(plan => {
    const button = make("button", `${new Date(plan.created_at).toLocaleString("pt-BR")} · ${plan.macro_stop_count} macro-paradas · ${plan.stale ? "desatualizada" : "atual"}`, "secondary");
    button.type = "button"; button.onclick = () => { macroPlanId = plan.id; renderMacroPlan(plan); };
    $("macro-history").append(button);
  });
  const current = plans.find(plan => plan.id === macroPlanId) || plans[0];
  macroPlanId = current.id; renderMacroPlan(current);
}
function renderMacroPlan(plan) {
  const detail = $("macro-detail"); detail.replaceChildren();
  const title = make("h3", `Proposta: ${plan.macro_stop_count} macro-paradas para ${plan.package_count} pacotes`);
  const summary = make("p", `${plan.exact_coverage ? "Cobertura exata" : "Cobertura inconsistente"} · ${plan.original_stop_count} paradas originais · ${plan.packages_without_original_stop} pacote(s) sem parada original · ${plan.original_stops_split} parada(s) originais divididas${plan.stale ? " · DESATUALIZADA" : ""}.`);
  detail.append(title, summary, make("p", plan.distance_comparison_note));
  plan.stops.forEach(stop => {
    const card = document.createElement("article"); card.className = "macro-stop";
    card.append(make("h3", `Macro-parada ${stop.ordinal} · ${stop.package_count} pacote(s)`));
    card.append(make("p", `Base candidata: ${stop.candidate_base_address} · estacionamento não verificado.`));
    const addresses = stop.delivery_point_ids.map(id => points.find(point => point.id === id)?.original_address || id);
    const list = document.createElement("ul"); addresses.forEach(address => list.append(make("li", address))); card.append(list);
    card.append(make("p", `Paradas originais: ${stop.original_stops.join(", ") || "sem número"}. Maior par: ${Math.round(stop.max_pairwise_m)} m. Maior ida e volta individual: ${Math.round(stop.max_base_roundtrip_m)} m.`));
    card.append(make("p", `Revisão: ${stop.review_status === "accepted" ? "agrupamento aceito" : stop.review_status === "rejected" ? "agrupamento rejeitado" : "pendente"}.`));
    const note = document.createElement("textarea"); note.maxLength = 2000; note.rows = 2; note.placeholder = "Observação sobre o agrupamento"; note.value = stop.review_note || ""; note.disabled = plan.stale;
    const label = make("label", "Observação"); label.append(note); card.append(label);
    for (const [decision, caption] of [["accepted", "Aceitar agrupamento"], ["rejected", "Rejeitar agrupamento"]]) {
      const button = make("button", caption, decision === "accepted" ? "" : "secondary"); button.type = "button"; button.disabled = plan.stale;
      button.onclick = () => action(async () => {
        const updated = await request(`/api/v1/macro-stops/${stop.id}/review`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({review_status: decision, review_note: note.value || null})});
        renderMacroPlan(updated); notice("Revisão do agrupamento salva. A vaga continua sem validação.");
      });
      card.append(button);
    }
    detail.append(card);
  });
}
async function loadEntries() {
  const entries = await request(`/api/v1/walking-matrices/${matrixId}/entries?limit=100&offset=${entriesOffset}`);
  const addresses = new Map(points.map(p => [p.id, p.original_address]));
  entries.forEach(entry => { const tr = document.createElement("tr"); [addresses.get(entry.origin_delivery_point_id) || entry.origin_delivery_point_id, addresses.get(entry.destination_delivery_point_id) || entry.destination_delivery_point_id, entry.distance_m === null ? "—" : Math.round(entry.distance_m) + " m", entry.duration_s === null ? "—" : Math.round(entry.duration_s) + " s", entry.reachable ? "Acessível" : "Sem caminho · " + entry.error_code].forEach(value => tr.append(make("td", value))); $("entries").append(tr); });
  entriesOffset += entries.length; $("more-entries").hidden = entries.length < 100;
}

$("upload-form").onsubmit = event => { event.preventDefault(); if (!canLeave()) return; action(async () => { notice("Importando planilha…"); const data = new FormData(); data.append("file", $("file").files[0]); const imported = await request("/api/v1/imports", {method: "POST", body: data}); await loadRoutes(imported.routes[0].id); notice(`${imported.package_count} pacotes importados · ${imported.warning_count} avisos. Confira as entradas antes de confirmar.`); }); };
$("routes").onchange = () => { const id = $("routes").value; if (!canLeave()) { $("routes").value = routeId; return; } action(() => loadRoute(id)); };
$("reload").onclick = () => { if (canLeave()) action(() => loadRoutes()); };
$("search").oninput = renderPoints; $("filter").onchange = renderPoints;
$("fit").onclick = fitPoints;
$("tiles").onclick = () => { if (!map) return notice("Biblioteca de mapas indisponível; recarregue com internet.", true); if (tiles) { tiles.remove(); tiles = null; $("tiles").textContent = "Mostrar ruas"; return; } tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map); tiles.on("tileerror", () => { $("map-note").textContent = "Não foi possível carregar algumas ruas. Verifique a conexão; os pontos continuam disponíveis."; }); $("tiles").textContent = "Ocultar ruas"; };
$("review-form").oninput = () => { dirty = true; if ($("review-status").value === "confirmed" && selected) { $("latitude").value = selected.imported_latitude; $("longitude").value = selected.imported_longitude; } updateDraft(); updateAvailability(); };
$("discard").onclick = () => { if (selected) selectPoint(selected); };
$("review-form").onsubmit = event => { event.preventDefault(); action(async () => {
  const command = {review_status: $("review-status").value, review_source: "operator", review_note: $("note").value || null, expected_revision: selected.revision};
  if (command.review_status === "corrected") { command.latitude = Number($("latitude").value); command.longitude = Number($("longitude").value); }
  const point = await request(`/api/v1/delivery-points/${selected.id}/review`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(command)});
  points = points.map(p => p.id === point.id ? point : p); selectPoint(point); await loadMatrices(); $("matrix-detail").hidden = true; notice("Revisão salva. O histórico e o estado das matrizes foram atualizados.");
}); };
$("compute").onclick = () => action(async () => { notice("Calculando matriz…"); const matrix = await post(`/api/v1/routes/${routeId}/walking-matrices`, {}); await loadMatrices(); notice(matrix.quality === "estimate_only" ? "Estimativa salva. Para validar acessos reais, configure o serviço pedestre." : `Matriz salva: ${matrix.unreachable_pairs} pares sem caminho.`); });
$("more-entries").onclick = () => action(loadEntries);
$("macro-form").onsubmit = event => { event.preventDefault(); action(async () => {
  notice("Gerando proposta de macro-paradas…");
  const plan = await post(`/api/v1/routes/${routeId}/macro-plans`, {
    walking_matrix_id: $("macro-matrix").value,
    max_packages: Number($("macro-capacity").value),
    max_pairwise_m: Number($("macro-pairwise").value),
    max_base_roundtrip_m: Number($("macro-roundtrip").value),
  });
  macroPlanId = plan.id; await loadMacroPlans();
  notice(`${plan.macro_stop_count} macro-paradas propostas para ${plan.package_count} pacotes. Confira agrupamentos e vagas antes do uso.`);
}); };
window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
initializeMap();
action(async () => { provider = await request("/api/v1/maps/config"); $("provider").textContent = provider.quality === "estimate_only" ? "Modo de desenvolvimento · estimativa em linha reta. Barreiras e acessos reais não são considerados." : `Rede pedestre · ${provider.provider} · perfil ${provider.profile}`; await loadRoutes(); notice(routeId ? "Rota carregada. Selecione um endereço para conferir a entrada." : "Importe uma planilha .xlsx para iniciar a revisão."); });
