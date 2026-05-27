"""Inventory page."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
from web.layout import _shell

def _inventory_page(user):
    mats = rs(q("SELECT * FROM materials ORDER BY category, name"))
    cats = sorted({m['category'] for m in mats if m.get('category')})
    moves = rs(q("""SELECT mv.*,m.name mat_name,m.code mat_code,u.display_name uname
        FROM stock_movements mv JOIN materials m ON m.id=mv.material_id
        LEFT JOIN users u ON u.id=mv.user_id
        ORDER BY mv.created_at DESC LIMIT 30"""))

    cat_opts = "".join(f'<option value="{_esc(c)}">{_esc(c)}</option>' for c in cats)

    rows = ""
    for m in mats:
        critical = m['stock_warehouse'] <= m['stock_min'] and m['stock_min'] > 0
        low_style = 'color:var(--red);font-weight:700' if critical else ''
        critical_icon = ' ⚠️' if critical else ''
        rows += (f'<tr><td><span class="chip">{_esc(m["code"])}</span></td>'
            f'<td><span class="fw7">{_esc(m["name"])}</span>{critical_icon}'
            f'{"<br><span class=muted style=font-size:.72rem>"+_esc(m["description"])+"</span>" if m.get("description") else ""}</td>'
            f'<td class="muted col-m-hide">{_esc(m["category"] or "—")}</td>'
            f'<td style="text-align:center;{low_style}">{m["stock_warehouse"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_field"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_warehouse"]+m["stock_field"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_min"]}</td>'
            f'<td class="muted col-m-hide">{_esc(m["unit"])}</td>'
            f'<td>'
            f'<button class="btn btn-ghost btn-icon" title="Ajustar stock" onclick="openAdjust({m["id"]},{json.dumps(m["name"])},{m["stock_warehouse"]})">±</button>'
            f'<button class="btn btn-ghost btn-icon" onclick="editMat({json.dumps(dict(m))})">✏️</button>'
            f'<button class="btn btn-danger btn-icon" onclick="delMat({m["id"]})">✕</button>'
            f'</td></tr>')

    mv_rows = ""
    for mv in moves:
        icon = '<span class="mv-in">+</span>' if mv['direction']=='in' else '<span class="mv-out">−</span>'
        mv_rows += (f'<tr><td class="muted" style="font-size:.75rem;white-space:nowrap">{mv["created_at"][:16]}</td>'
            f'<td><span class="chip">{_esc(mv["mat_code"])}</span> {_esc(mv["mat_name"])}</td>'
            f'<td style="text-align:center">{icon} {mv["qty"]}</td>'
            f'<td class="muted col-m-hide">{_esc(mv["source"] or "—")}</td>'
            f'<td class="muted col-m-hide">{_esc(mv["uname"] or "—")}</td>'
            f'<td class="muted col-m-hide" style="font-size:.78rem">{_esc(mv["notes"] or "")}</td></tr>')

    content = f"""
<div class="toolbar"><h1>Inventario</h1>
  <button class="btn btn-primary" onclick="openNewMat()">+ Material</button>
</div>
<div class="card">
<div class="tbl-wrap"><table><thead><tr>
  <th>Código</th><th>Nombre</th><th class="col-m-hide">Categoría</th>
  <th style="text-align:center">Almacén</th><th style="text-align:center" class="col-m-hide">Campo</th>
  <th style="text-align:center" class="col-m-hide">Total</th>
  <th style="text-align:center" class="col-m-hide">Mínimo</th>
  <th class="col-m-hide">Ud</th><th></th>
</tr></thead><tbody>{rows or "<tr><td colspan='9' class='muted' style='text-align:center;padding:24px'>Sin materiales</td></tr>"}</tbody></table></div>
</div>

<div class="card">
  <h2>Últimos movimientos de stock</h2>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Fecha</th><th>Material</th><th style="text-align:center">Cant.</th>
    <th class="col-m-hide">Origen</th><th class="col-m-hide">Usuario</th><th class="col-m-hide">Notas</th>
  </tr></thead><tbody>{mv_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:16px'>Sin movimientos</td></tr>"}</tbody></table></div>
</div>

<!-- modal material -->
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
  </div>
  <div class="form-row"><div><label>Stock mínimo</label><input type="number" id="m-min" min="0" value="0"></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeMatModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<!-- modal ajuste rápido -->
<div class="modal-bg" id="adj-modal">
<div class="modal" style="max-width:360px">
  <h2 id="adj-title">Ajuste de stock</h2>
  <input type="hidden" id="adj-mid">
  <div class="field"><label>Variación (+entrada / -salida)</label>
    <input type="number" id="adj-qty" placeholder="Ej: +10 o -5"></div>
  <div class="field"><label>Notas</label>
    <input id="adj-notes" placeholder="Motivo del ajuste"></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeAdjModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doAdjust()">Aplicar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
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
  var d={{code:document.getElementById('m-code').value,name:document.getElementById('m-name').value,
    category:document.getElementById('m-cat').value,description:document.getElementById('m-desc').value,
    unit:document.getElementById('m-unit').value,
    stock_warehouse:parseInt(document.getElementById('m-wh').value)||0,
    stock_field:parseInt(document.getElementById('m-fi').value)||0,
    stock_min:parseInt(document.getElementById('m-min').value)||0}};
  fetch(id?bp+'/api/materials/'+id:bp+'/api/materials',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
function delMat(id){{
  if(!confirm('¿Eliminar material?')) return;
  fetch(bp+'/api/materials/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function openAdjust(id,name,cur){{
  document.getElementById('adj-title').textContent='Ajuste: '+name+' (actual: '+cur+')';
  document.getElementById('adj-mid').value=id;
  document.getElementById('adj-qty').value='';
  document.getElementById('adj-notes').value='';
  document.getElementById('adj-modal').classList.add('open');
}}
function closeAdjModal(){{document.getElementById('adj-modal').classList.remove('open');}}
document.getElementById('adj-modal').onclick=function(e){{if(e.target===this)closeAdjModal();}};
function doAdjust(){{
  var mid=document.getElementById('adj-mid').value;
  var qty=parseInt(document.getElementById('adj-qty').value);
  var notes=document.getElementById('adj-notes').value;
  if(isNaN(qty)||qty===0){{alert('Introduce una cantidad distinta de 0');return;}}
  fetch(bp+'/api/materials/'+mid+'/adjust',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{qty:qty,notes:notes}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
</script>"""
    return _shell("inventory", user, content)

# ── kit de técnico ────────────────────────────────────────────────────────────
