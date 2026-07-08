"""Inventory page."""
import json
from core.db import BP, q, q1, rs
from core.helpers import _esc, _jattr, _empty_state
from web.layout import _shell


def _inventory_page(user):
    is_admin = user.get("role") == "admin"
    mats  = rs(q("SELECT * FROM materials ORDER BY category, name"))
    cats  = sorted({m["category"] for m in mats if m.get("category")})
    moves = rs(q("""SELECT mv.*,m.name mat_name,m.code mat_code,u.display_name uname
        FROM stock_movements mv JOIN materials m ON m.id=mv.material_id
        LEFT JOIN users u ON u.id=mv.user_id
        ORDER BY mv.created_at DESC LIMIT 30"""))
    locs  = rs(q("""SELECT wl.*,
        COALESCE(SUM(sbl.qty),0) total_stock,
        COUNT(DISTINCT sbl.material_id) n_materials
        FROM warehouse_locations wl
        LEFT JOIN stock_by_location sbl ON sbl.location_id=wl.id AND sbl.qty>0
        GROUP BY wl.id ORDER BY wl.warehouse,wl.code"""))

    critical = [m for m in mats if m["stock_min"] > 0 and m["stock_warehouse"] <= m["stock_min"]]

    # ── low-stock panel ──────────────────────────────────────────────────────────
    alert_panel = ""
    if critical:
        crit_rows = "".join(
            f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;'
            f'border-bottom:1px solid var(--border)">'
            f'<span class="chip">{_esc(m["code"])}</span>'
            f'<span style="flex:1;font-size:.85rem">{_esc(m["name"])}</span>'
            f'<span style="font-size:.82rem;color:#dc2626;font-weight:700;white-space:nowrap">'
            f'{m["stock_warehouse"]} / mín {m["stock_min"]} {_esc(m["unit"])}</span>'
            f'<button class="btn btn-ghost btn-icon" title="Ajustar stock" '
            f'onclick="openAdjust({m["id"]},{json.dumps(m["name"])},{m["stock_warehouse"]})">±</button>'
            f'</div>'
            for m in critical)
        alert_panel = (
            f'<div class="card" style="border-left:4px solid #dc2626;padding:14px 16px;margin-bottom:16px">'
            f'<div style="font-weight:700;margin-bottom:8px">⚠️ Stock crítico — {len(critical)} '
            f'material{"es" if len(critical)!=1 else ""} por debajo del mínimo</div>'
            f'{crit_rows}</div>')

    # ── category options ─────────────────────────────────────────────────────────
    cat_opts = "".join(f'<option value="{_esc(c)}">{_esc(c)}</option>' for c in cats)

    # ── location options for selectors ───────────────────────────────────────────
    loc_opts_all = "".join(
        f'<option value="{l["id"]}">[{_esc(l["code"])}] {_esc(l["name"])} — {_esc(l["warehouse"])}</option>'
        for l in locs if l.get("active", 1))

    # ── materials table ──────────────────────────────────────────────────────────
    rows = ""
    for m in mats:
        is_crit  = m["stock_min"] > 0 and m["stock_warehouse"] <= m["stock_min"]
        low_sty  = "color:var(--s-err);font-weight:700" if is_crit else ""
        crit_ico = " ⚠️" if is_crit else ""
        crit_row = ' class="nd-crit"' if is_crit else ''
        rows += (
            f'<tr{crit_row} data-name="{_esc((m["name"]+m["code"]).lower())}" '
            f'data-cat="{_esc(m["category"] or "")}" '
            f'data-crit="{1 if is_crit else 0}">'
            f'<td><span class="chip">{_esc(m["code"])}</span></td>'
            f'<td><span class="fw7">{_esc(m["name"])}</span>{crit_ico}'
            f'{"<br><span class=muted style=font-size:.72rem>"+_esc(m["description"])+"</span>" if m.get("description") else ""}'
            f'</td>'
            f'<td class="muted col-m-hide">{_esc(m["category"] or "—")}</td>'
            f'<td style="text-align:center;{low_sty}">{m["stock_warehouse"]}</td>'
            f'<td style="text-align:center">{m["stock_field"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_warehouse"]+m["stock_field"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_min"] or "—"}</td>'
            f'<td class="muted col-m-hide">{_esc(m["unit"])}</td>'
            f'<td style="white-space:nowrap">'
            f'<div style="display:flex;align-items:center;gap:2px">'
            f'<button class="btn btn-ghost btn-icon" title="Ajustar stock" '
            f'onclick="openAdjust({m["id"]},{json.dumps(m["name"])},{m["stock_warehouse"]})">±</button>'
            f'<button class="btn btn-ghost btn-icon" title="Transferir" '
            f'onclick="openTransfer({m["id"]},{json.dumps(m["name"])},{m["stock_warehouse"]},{m["stock_field"]})">⇄</button>'
            f'<div class="nd-ovfl-wrap">'
            f'<button class="btn btn-ghost btn-icon" onclick="ndOverflow(this)" title="Más acciones">···</button>'
            f'<div class="nd-ovfl-drop">'
            f'<button class="nd-ovfl-item" onclick="openLocStock({m["id"]},{json.dumps(m["name"])})">📍 Stock por ubicación</button>'
            f'<button class="nd-ovfl-item" onclick="openUsage({m["id"]},{json.dumps(m["name"])})">📋 Uso en proyectos</button>'
            f'<button class="nd-ovfl-item" onclick="editMat({_jattr(dict(m))})">✏️ Editar</button>'
            f'<button class="nd-ovfl-item danger" onclick="delMat({m["id"]})">✕ Eliminar</button>'
            f'</div></div>'
            f'</div></td></tr>')

    # ── movements table ──────────────────────────────────────────────────────────
    _SRC_LABEL = {
        "adjust": "Ajuste", "kit": "Kit técnico", "kit_return": "Dev. kit",
        "transfer_to_field": "→ Campo", "transfer_to_warehouse": "← Almacén",
        "transfer_internal": "⇄ Interno",
    }
    mv_rows = ""
    for mv in moves:
        icon = '<span class="mv-in">+</span>' if mv["direction"] == "in" else '<span class="mv-out">−</span>'
        src_lbl = _SRC_LABEL.get(mv["source"] or "", mv["source"] or "—")
        mv_rows += (
            f'<tr>'
            f'<td class="muted" style="font-size:.75rem;white-space:nowrap">{mv["created_at"][:16]}</td>'
            f'<td><span class="chip">{_esc(mv["mat_code"])}</span> {_esc(mv["mat_name"])}</td>'
            f'<td style="text-align:center">{icon} {mv["qty"]}</td>'
            f'<td class="muted col-m-hide">{src_lbl}</td>'
            f'<td class="muted col-m-hide">{_esc(mv["uname"] or "—")}</td>'
            f'<td class="muted col-m-hide" style="font-size:.78rem">{_esc(mv["notes"] or "")}</td>'
            f'</tr>')

    # ── locations table ──────────────────────────────────────────────────────────
    loc_rows = ""
    warehouses = {}
    for l in locs:
        wh = l.get("warehouse") or "Sin grupo"
        warehouses.setdefault(wh, []).append(l)

    for wh_name, wh_locs in warehouses.items():
        loc_rows += (
            f'<tr><td colspan="6" style="background:var(--surface2,#f1f5f9);'
            f'font-weight:700;font-size:.8rem;color:var(--muted);padding:6px 12px;'
            f'letter-spacing:.04em;text-transform:uppercase">'
            f'🏭 {_esc(wh_name)}</td></tr>')
        for l in wh_locs:
            active_badge = ('<span style="color:#16a34a;font-size:.75rem">● Activa</span>'
                           if l.get("active", 1) else
                           '<span style="color:#94a3b8;font-size:.75rem">○ Inactiva</span>')
            edit_btn = (f'<button class="btn btn-ghost btn-icon" '
                        f'onclick="editLoc({_jattr(dict(l))})" title="Editar">✏️</button>'
                        f'<button class="btn btn-danger btn-icon" '
                        f'onclick="delLoc({l["id"]},{json.dumps(l["name"])})" title="Eliminar">✕</button>'
                        if is_admin else "")
            loc_rows += (
                f'<tr>'
                f'<td><span class="chip">{_esc(l["code"])}</span></td>'
                f'<td><span class="fw7">{_esc(l["name"])}</span>'
                f'{"<br><span class=muted style=font-size:.72rem>"+_esc(l["description"])+"</span>" if l.get("description") else ""}'
                f'</td>'
                f'<td class="muted col-m-hide">{_esc(wh_name)}</td>'
                f'<td style="text-align:center">{int(l["total_stock"])}</td>'
                f'<td style="text-align:center">{int(l["n_materials"])}</td>'
                f'<td>{active_badge} {edit_btn}</td>'
                f'</tr>')

    empty_mats = ('<tr><td colspan="9" class="muted" style="text-align:center;padding:24px">'
                  'Sin materiales</td></tr>')
    empty_mvs  = ('<tr><td colspan="6" class="muted" style="text-align:center;padding:16px">'
                  'Sin movimientos</td></tr>')
    empty_locs = ('<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">'
                  'Sin ubicaciones definidas</td></tr>')

    new_loc_btn = (
        f'<button class="btn btn-ghost" onclick="openNewWarehouse()" style="margin-right:4px">+ Almacén</button>'
        f'<button class="btn btn-primary" onclick="openNewLoc()">+ Ubicación</button>'
        if is_admin else ""
    )

    locs_json = json.dumps([dict(l) for l in locs])

    content = f"""
{alert_panel}
<div class="toolbar">
  <h1>📦 Inventario</h1>
  <div style="display:flex;gap:8px">
    <button class="btn btn-ghost" id="tab-mats-btn" onclick="showTab('mats')" style="font-weight:700">Materiales</button>
    <button class="btn btn-ghost" id="tab-locs-btn" onclick="showTab('locs')">Ubicaciones</button>
  </div>
  <div id="tab-mats-actions">
    <button class="btn btn-primary" onclick="openNewMat()">+ Material</button>
  </div>
  <div id="tab-locs-actions" style="display:none">
    {new_loc_btn}
  </div>
</div>

<!-- ── MATERIALES TAB ── -->
<div id="tab-mats">
<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
  <input id="inv-search" type="search" placeholder="Buscar nombre o código…"
    style="padding:7px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;
           font-family:inherit;outline:none;min-width:200px;background:var(--surface)"
    oninput="filterMats()">
  <select id="inv-cat"
    style="padding:7px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;
           font-family:inherit;background:var(--surface);outline:none"
    onchange="filterMats()">
    <option value="">Todas las categorías</option>{cat_opts}
  </select>
  <label style="display:flex;align-items:center;gap:6px;font-size:.85rem;cursor:pointer;white-space:nowrap">
    <input type="checkbox" id="inv-crit" onchange="filterMats()"> Solo críticos ⚠️
  </label>
  <span id="inv-count" class="muted" style="font-size:.8rem;margin-left:auto"></span>
</div>

<div class="card" style="padding:0">
<div class="tbl-wrap"><table id="inv-table"><thead><tr>
  <th>Código</th><th>Nombre</th><th class="col-m-hide">Categoría</th>
  <th style="text-align:center">Almacén</th>
  <th style="text-align:center">Campo</th>
  <th style="text-align:center" class="col-m-hide">Total</th>
  <th style="text-align:center" class="col-m-hide">Mínimo</th>
  <th class="col-m-hide">Ud</th><th></th>
</tr></thead>
<tbody id="inv-tbody">{rows or empty_mats}</tbody>
</table></div>
</div>

<div class="card" style="margin-top:16px">
  <h2 style="margin:0 0 12px">Últimos movimientos</h2>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Fecha</th><th>Material</th><th style="text-align:center">Cant.</th>
    <th class="col-m-hide">Tipo</th><th class="col-m-hide">Usuario</th><th class="col-m-hide">Notas</th>
  </tr></thead><tbody>{mv_rows or empty_mvs}</tbody></table></div>
</div>
</div><!-- /tab-mats -->

<!-- ── UBICACIONES TAB ── -->
<div id="tab-locs" style="display:none">
<div class="card" style="padding:0">
<div class="tbl-wrap"><table><thead><tr>
  <th>Código</th><th>Nombre</th><th class="col-m-hide">Almacén</th>
  <th style="text-align:center">Stock</th>
  <th style="text-align:center">Materiales</th>
  <th>Estado</th>
</tr></thead>
<tbody>{loc_rows or empty_locs}</tbody>
</table></div>
</div>
</div><!-- /tab-locs -->

<!-- ── modal: nuevo/editar material ── -->
<div class="modal-bg" id="mat-modal">
<div class="modal">
  <h2 id="mat-modal-title">Nuevo material</h2>
  <form id="mat-form">
  <input type="hidden" id="mat-id">
  <div class="form-row">
    <div><label>Código</label><input id="m-code" required placeholder="SFP-SM-1G"></div>
    <div><label>Nombre</label><input id="m-name" required placeholder="Transceptor SFP SM 1G"></div>
  </div>
  <div class="form-row">
    <div><label>Categoría</label><input id="m-cat" list="cat-dl" placeholder="Transceivers">
      <datalist id="cat-dl">{cat_opts}</datalist></div>
    <div><label>Unidad</label><select id="m-unit">
      <option value="ud">ud</option><option value="m">m</option>
      <option value="m2">m²</option><option value="kg">kg</option>
      <option value="l">l</option><option value="bobina">bobina</option>
      <option value="caja">caja</option><option value="rollo">rollo</option>
      <option value="par">par</option>
    </select></div>
  </div>
  <div class="form-row single"><label>Descripción</label><textarea id="m-desc" rows="2"></textarea></div>
  <div class="form-row">
    <div><label>Stock almacén</label><input type="number" id="m-wh" min="0" value="0"></div>
    <div><label>Stock campo</label><input type="number" id="m-fi" min="0" value="0"></div>
    <div><label>Stock mínimo</label><input type="number" id="m-min" min="0" value="0"></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeMatModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<!-- ── modal: ajuste de stock ── -->
<div class="modal-bg" id="adj-modal">
<div class="modal" style="max-width:400px">
  <h2 id="adj-title">Ajuste de stock — Almacén</h2>
  <input type="hidden" id="adj-mid">
  <div class="field"><label>Variación (+entrada / −salida)</label>
    <input type="number" id="adj-qty" placeholder="Ej: +10 o -5"></div>
  <div class="field"><label>Ubicación <span class="muted" style="font-size:.78rem">(opcional)</span></label>
    <select id="adj-loc">
      <option value="">— Sin ubicación específica —</option>
      {loc_opts_all}
    </select>
  </div>
  <div class="field"><label>Notas</label>
    <input id="adj-notes" placeholder="Motivo del ajuste"></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeAdjModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doAdjust()">Aplicar</button>
  </div>
</div></div>

<!-- ── modal: transferencia ── -->
<div class="modal-bg" id="tr-modal">
<div class="modal" style="max-width:420px">
  <h2>Transferir stock</h2>
  <div id="tr-info" class="muted" style="font-size:.82rem;margin-bottom:12px"></div>
  <input type="hidden" id="tr-mid">
  <div class="form-row single">
    <label>Origen</label>
    <select id="tr-from">
      <option value="field">Campo</option>
      {loc_opts_all}
    </select>
  </div>
  <div class="form-row single">
    <label>Destino</label>
    <select id="tr-to">
      <option value="field">Campo</option>
      {loc_opts_all}
    </select>
  </div>
  <div class="form-row">
    <div><label>Cantidad</label>
      <input type="number" id="tr-qty" min="1" value="1"></div>
  </div>
  <div id="tr-loc-stock" class="muted" style="font-size:.78rem;margin-bottom:8px"></div>
  <div class="field"><label>Notas</label>
    <input id="tr-notes" placeholder="Motivo (opcional)"></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeTrModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doTransfer()">Transferir</button>
  </div>
</div></div>

<!-- ── modal: stock por ubicación ── -->
<div class="modal-bg" id="loc-stock-modal">
<div class="modal" style="max-width:480px">
  <h2>Stock por ubicación: <span id="ls-mat-name" style="font-weight:400"></span></h2>
  <div id="ls-body" style="min-height:60px"><p class="muted">Cargando…</p></div>
  <div class="modal-foot">
    <button class="btn btn-ghost" onclick="document.getElementById('loc-stock-modal').classList.remove('open')">Cerrar</button>
  </div>
</div></div>

<!-- ── modal: uso en proyectos ── -->
<div class="modal-bg" id="use-modal">
<div class="modal">
  <h2>Uso en proyectos: <span id="use-mat-name" style="font-weight:400"></span></h2>
  <div id="use-body" style="min-height:60px"><p class="muted">Cargando…</p></div>
  <div class="modal-foot">
    <button class="btn btn-ghost" onclick="document.getElementById('use-modal').classList.remove('open')">Cerrar</button>
  </div>
</div></div>

<!-- ── modal: nuevo almacén ── -->
<div class="modal-bg" id="wh-new-modal">
<div class="modal" style="max-width:380px">
  <h2>Nuevo almacén</h2>
  <p class="muted" style="font-size:.84rem;margin-bottom:16px;line-height:1.5">
    Los almacenes agrupan ubicaciones. Al confirmar, se abrirá el formulario para añadir
    la primera ubicación dentro de este almacén.
  </p>
  <div class="field">
    <label>Nombre del almacén</label>
    <input id="wh-new-name" placeholder="Ej: Almacén Secundario" autocomplete="off">
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeWhModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="confirmNewWarehouse()">Continuar →</button>
  </div>
</div></div>

<!-- ── modal: nueva/editar ubicación ── -->
<div class="modal-bg" id="loc-modal">
<div class="modal" style="max-width:420px">
  <h2 id="loc-modal-title">Nueva ubicación</h2>
  <input type="hidden" id="loc-id">
  <div class="form-row">
    <div><label>Código</label><input id="l-code" required placeholder="A1-EST1" style="text-transform:uppercase"></div>
    <div><label>Nombre</label><input id="l-name" required placeholder="Estantería 1"></div>
  </div>
  <div class="form-row single">
    <label>Almacén <span class="muted" style="font-size:.78rem">(agrupa ubicaciones)</span></label>
    <input id="l-warehouse" placeholder="Almacén Principal" value="Almacén Principal" list="wh-dl">
    <datalist id="wh-dl">
      {''.join(f'<option value="{_esc(wh)}"></option>' for wh in {l.get("warehouse","") for l in locs if l.get("warehouse")})}
    </datalist>
  </div>
  <div class="form-row single"><label>Descripción</label>
    <input id="l-desc" placeholder="Descripción opcional"></div>
  <div class="form-row single">
    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
      <input type="checkbox" id="l-active" checked> Ubicación activa
    </label>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeLocModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="saveLoc()">Guardar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
var _allLocs={locs_json};

// ── tabs ─────────────────────────────────────────────────────────────────────
function showTab(t){{
  document.getElementById('tab-mats').style.display=t==='mats'?'':'none';
  document.getElementById('tab-locs').style.display=t==='locs'?'':'none';
  document.getElementById('tab-mats-actions').style.display=t==='mats'?'':'none';
  document.getElementById('tab-locs-actions').style.display=t==='locs'?'':'none';
  document.getElementById('tab-mats-btn').style.fontWeight=t==='mats'?'700':'400';
  document.getElementById('tab-locs-btn').style.fontWeight=t==='locs'?'700':'400';
}}

// ── filter ────────────────────────────────────────────────────────────────────
function filterMats(){{
  var q=(document.getElementById('inv-search').value||'').toLowerCase();
  var cat=(document.getElementById('inv-cat').value||'').toLowerCase();
  var crit=document.getElementById('inv-crit').checked;
  var rows=document.querySelectorAll('#inv-tbody tr');
  var shown=0;
  rows.forEach(function(r){{
    var name=(r.dataset.name||'');
    var rc=(r.dataset.cat||'').toLowerCase();
    var isCrit=r.dataset.crit==='1';
    var ok=(!q||name.includes(q))&&(!cat||rc===cat)&&(!crit||isCrit);
    r.style.display=ok?'':'none';
    if(ok)shown++;
  }});
  document.getElementById('inv-count').textContent=shown+' resultado'+(shown!==1?'s':'');
}}
(function(){{filterMats();}}());

// ── mat modal ─────────────────────────────────────────────────────────────────
function openNewMat(){{
  document.getElementById('mat-modal-title').textContent='Nuevo material';
  document.getElementById('mat-id').value='';
  ['code','name','cat','desc'].forEach(function(f){{document.getElementById('m-'+f).value='';}});
  document.getElementById('m-unit').value='ud';
  ['wh','fi','min'].forEach(function(f){{document.getElementById('m-'+f).value=0;}});
  document.getElementById('mat-modal').classList.add('open');
}}
function editMat(m){{
  document.getElementById('mat-modal-title').textContent='Editar material';
  document.getElementById('mat-id').value=m.id;
  document.getElementById('m-code').value=m.code||'';
  document.getElementById('m-name').value=m.name||'';
  document.getElementById('m-cat').value=m.category||'';
  document.getElementById('m-desc').value=m.description||'';
  document.getElementById('m-unit').value=m.unit||'ud';
  document.getElementById('m-wh').value=m.stock_warehouse||0;
  document.getElementById('m-fi').value=m.stock_field||0;
  document.getElementById('m-min').value=m.stock_min||0;
  document.getElementById('mat-modal').classList.add('open');
}}
function closeMatModal(){{document.getElementById('mat-modal').classList.remove('open');}}
document.getElementById('mat-modal').onclick=function(e){{if(e.target===this)closeMatModal();}};
document.getElementById('mat-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('mat-id').value;
  var d={{code:document.getElementById('m-code').value,
    name:document.getElementById('m-name').value,
    category:document.getElementById('m-cat').value,
    description:document.getElementById('m-desc').value,
    unit:document.getElementById('m-unit').value,
    stock_warehouse:parseInt(document.getElementById('m-wh').value)||0,
    stock_field:parseInt(document.getElementById('m-fi').value)||0,
    stock_min:parseInt(document.getElementById('m-min').value)||0}};
  fetch(id?bp+'/api/materials/'+id:bp+'/api/materials',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}};
function delMat(id){{
  ConfirmDialog.show('¿Eliminar material?','Esta acción no se puede deshacer.')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/materials/'+id,{{method:'DELETE'}})
        .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
    }});
}}

// ── adjust modal ──────────────────────────────────────────────────────────────
function openAdjust(id,name,cur){{
  document.getElementById('adj-title').textContent='Ajuste almacén: '+name+' (actual: '+cur+')';
  document.getElementById('adj-mid').value=id;
  document.getElementById('adj-qty').value='';
  document.getElementById('adj-loc').value='';
  document.getElementById('adj-notes').value='';
  document.getElementById('adj-modal').classList.add('open');
}}
function closeAdjModal(){{document.getElementById('adj-modal').classList.remove('open');}}
document.getElementById('adj-modal').onclick=function(e){{if(e.target===this)closeAdjModal();}};
function doAdjust(){{
  var mid=document.getElementById('adj-mid').value;
  var qty=parseInt(document.getElementById('adj-qty').value);
  var lid=document.getElementById('adj-loc').value;
  var notes=document.getElementById('adj-notes').value;
  if(isNaN(qty)||qty===0){{Toast.show('Introduce una cantidad distinta de 0','err');return;}}
  var d={{qty:qty,notes:notes}};
  if(lid)d.location_id=parseInt(lid);
  fetch(bp+'/api/materials/'+mid+'/adjust',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}

// ── transfer modal ────────────────────────────────────────────────────────────
var _trMid=null;
function openTransfer(id,name,wh,fi){{
  _trMid=id;
  document.getElementById('tr-mid').value=id;
  document.getElementById('tr-info').textContent=
    name+' — Almacén: '+wh+' ud · Campo: '+fi+' ud';
  document.getElementById('tr-from').value='field';
  document.getElementById('tr-to').value='field';
  document.getElementById('tr-qty').value=1;
  document.getElementById('tr-notes').value='';
  document.getElementById('tr-loc-stock').textContent='';
  document.getElementById('tr-modal').classList.add('open');
  // load per-material location stock to show hints
  fetch(bp+'/api/materials/'+id+'/stock_by_location')
    .then(function(r){{return r.json();}})
    .then(function(rows){{
      // update from selector options with stock hints
      var sel=document.getElementById('tr-from');
      Array.from(sel.options).forEach(function(o){{
        if(o.value==='field'){{o.textContent='Campo ('+fi+' ud)';return;}}
        var loc=rows.find(function(r){{return String(r.location_id)===o.value;}});
        var qty=loc?loc.qty:0;
        var base=o.textContent.replace(/ \\(\\d+ ud\\)$/,'');
        o.textContent=base+' ('+qty+' ud)';
      }});
    }});
}}
function closeTrModal(){{document.getElementById('tr-modal').classList.remove('open');}}
document.getElementById('tr-modal').onclick=function(e){{if(e.target===this)closeTrModal();}};
function doTransfer(){{
  var mid=document.getElementById('tr-mid').value;
  var qty=parseInt(document.getElementById('tr-qty').value);
  var from_loc=document.getElementById('tr-from').value;
  var to_loc=document.getElementById('tr-to').value;
  var notes=document.getElementById('tr-notes').value;
  if(!qty||qty<1){{Toast.show('Cantidad mínima: 1','err');return;}}
  if(from_loc===to_loc){{Toast.show('Origen y destino deben ser diferentes','err');return;}}
  fetch(bp+'/api/materials/'+mid+'/transfer',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{qty:qty,from_loc:from_loc,to_loc:to_loc,notes:notes}})}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}location.reload();}});
}}

// ── stock por ubicación modal ─────────────────────────────────────────────────
function openLocStock(id,name){{
  document.getElementById('ls-mat-name').textContent=name;
  document.getElementById('ls-body').innerHTML='<p class="muted">Cargando…</p>';
  document.getElementById('loc-stock-modal').classList.add('open');
  fetch(bp+'/api/materials/'+id+'/stock_by_location')
    .then(function(r){{return r.json();}})
    .then(function(rows){{
      if(!rows.length){{
        document.getElementById('ls-body').innerHTML=
          '<p class="muted" style="text-align:center;padding:20px">Sin stock registrado por ubicación</p>';
        return;
      }}
      var html='<div class="tbl-wrap"><table><thead><tr>'
        +'<th>Código</th><th>Ubicación</th><th>Almacén</th>'
        +'<th style="text-align:center">Stock</th></tr></thead><tbody>';
      rows.forEach(function(r){{
        html+='<tr>'
          +'<td><span class="chip">'+r.loc_code+'</span></td>'
          +'<td>'+r.loc_name+'</td>'
          +'<td class="muted">'+r.warehouse+'</td>'
          +'<td style="text-align:center;font-weight:700">'+r.qty+'</td></tr>';
      }});
      html+='</tbody></table></div>';
      document.getElementById('ls-body').innerHTML=html;
    }});
}}
document.getElementById('loc-stock-modal').onclick=function(e){{
  if(e.target===this)this.classList.remove('open');
}};

// ── usage modal ───────────────────────────────────────────────────────────────
var _ST={{'requested':'Solicitado','assigned':'Asignado','consumed':'Consumido','returned':'Devuelto'}};
var _ST_C={{'requested':'#6366f1','assigned':'#22c55e','consumed':'#f59e0b','returned':'#94a3b8'}};
function openUsage(id,name){{
  document.getElementById('use-mat-name').textContent=name;
  document.getElementById('use-body').innerHTML='<p class="muted">Cargando…</p>';
  document.getElementById('use-modal').classList.add('open');
  fetch(bp+'/api/materials/'+id+'/assignments')
    .then(function(r){{return r.json();}})
    .then(function(rows){{
      if(!rows.length){{
        document.getElementById('use-body').innerHTML=
          '<p class="muted" style="text-align:center;padding:20px">Sin asignaciones a proyectos</p>';
        return;
      }}
      var html='<div class="tbl-wrap"><table><thead><tr>'
        +'<th>Proyecto</th><th style="text-align:center">Sol.</th>'
        +'<th style="text-align:center">Asig.</th><th style="text-align:center">Cons.</th>'
        +'<th style="text-align:center">Dev.</th><th>Estado</th></tr></thead><tbody>';
      rows.forEach(function(a){{
        var sc=_ST_C[a.status]||'#94a3b8';
        html+='<tr>'
          +'<td><a href="'+bp+'/projects/'+a.pid+'" style="font-weight:700">'+a.pname+'</a>'
          +'<span class="muted" style="font-size:.72rem;margin-left:6px">'+a.pstatus+'</span></td>'
          +'<td style="text-align:center">'+a.qty_requested+'</td>'
          +'<td style="text-align:center">'+a.qty_assigned+'</td>'
          +'<td style="text-align:center">'+a.qty_consumed+'</td>'
          +'<td style="text-align:center">'+a.qty_returned+'</td>'
          +'<td><span style="background:'+sc+';color:#fff;border-radius:4px;padding:2px 7px;font-size:.72rem">'
          +(_ST[a.status]||a.status)+'</span></td></tr>';
      }});
      html+='</tbody></table></div>';
      document.getElementById('use-body').innerHTML=html;
    }});
}}
document.getElementById('use-modal').onclick=function(e){{
  if(e.target===this)this.classList.remove('open');
}};

// ── location CRUD modal ───────────────────────────────────────────────────────
function openNewLoc(){{
  document.getElementById('loc-modal-title').textContent='Nueva ubicación';
  document.getElementById('loc-id').value='';
  document.getElementById('l-code').value='';
  document.getElementById('l-name').value='';
  document.getElementById('l-warehouse').value='Almacén Principal';
  document.getElementById('l-desc').value='';
  document.getElementById('l-active').checked=true;
  document.getElementById('loc-modal').classList.add('open');
}}
function editLoc(l){{
  document.getElementById('loc-modal-title').textContent='Editar ubicación';
  document.getElementById('loc-id').value=l.id;
  document.getElementById('l-code').value=l.code||'';
  document.getElementById('l-name').value=l.name||'';
  document.getElementById('l-warehouse').value=l.warehouse||'Almacén Principal';
  document.getElementById('l-desc').value=l.description||'';
  document.getElementById('l-active').checked=l.active!==0;
  document.getElementById('loc-modal').classList.add('open');
}}
function closeLocModal(){{document.getElementById('loc-modal').classList.remove('open');}}
document.getElementById('loc-modal').onclick=function(e){{if(e.target===this)closeLocModal();}};
function saveLoc(){{
  var id=document.getElementById('loc-id').value;
  var d={{
    code:document.getElementById('l-code').value.toUpperCase(),
    name:document.getElementById('l-name').value,
    warehouse:document.getElementById('l-warehouse').value||'Almacén Principal',
    description:document.getElementById('l-desc').value,
    active:document.getElementById('l-active').checked
  }};
  if(!d.code||!d.name){{Toast.show('Código y nombre son obligatorios','err');return;}}
  fetch(id?bp+'/api/locations/'+id:bp+'/api/locations',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}
function delLoc(id,name){{
  ConfirmDialog.show('¿Eliminar ubicación "'+name+'"?','Solo es posible si no tiene stock.')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/locations/'+id,{{method:'DELETE'}})
        .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
    }});
}}

// ── nuevo almacén ─────────────────────────────────────────────────────────────
function openNewWarehouse(){{
  document.getElementById('wh-new-name').value='';
  document.getElementById('wh-new-modal').classList.add('open');
  setTimeout(function(){{document.getElementById('wh-new-name').focus();}},80);
}}
function closeWhModal(){{document.getElementById('wh-new-modal').classList.remove('open');}}
document.getElementById('wh-new-modal').onclick=function(e){{if(e.target===this)closeWhModal();}};
document.getElementById('wh-new-name').onkeydown=function(e){{if(e.key==='Enter')confirmNewWarehouse();}};
function confirmNewWarehouse(){{
  var name=document.getElementById('wh-new-name').value.trim();
  if(!name){{Toast.show('Escribe el nombre del almacén','err');return;}}
  closeWhModal();
  openNewLoc();
  document.getElementById('l-warehouse').value=name;
}}
</script>"""
    return _shell("inventory", user, content, title="Inventario")
