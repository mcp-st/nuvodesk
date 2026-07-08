"""Map page — project locations via Leaflet.js + OpenStreetMap."""
from core.db import BP, q, rs, r2d
from core.helpers import _esc, STATUS_COLOR, PRIORITY_COLOR
from web.layout import _shell

_STATUS_LBL = {"active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado"}
_PRI_LBL    = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}

def _map_page(user):
    projects = rs(q("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to
        WHERE p.status NOT IN ('completed','cancelled')
        ORDER BY p.updated_at DESC"""))

    mapped   = [p for p in projects if p.get("lat") and p.get("lng")]
    unmapped = [p for p in projects if not (p.get("lat") and p.get("lng")) and p.get("address")]

    import json as _json
    markers_js = _json.dumps([{
        "id":   p["id"],
        "name": p["name"],
        "client": p.get("client",""),
        "address": p.get("address",""),
        "tech": p.get("tech",""),
        "status": p.get("status",""),
        "priority": p.get("priority","normal"),
        "lat": p["lat"],
        "lng": p["lng"],
        "url": f"{BP}/projects/{p['id']}",
    } for p in mapped], ensure_ascii=False)

    def _unmapped_row(p):
        pid = p["id"]
        addr_attr = _esc(p.get("address",""))
        return (f'<tr><td><a href="{BP}/projects/{pid}">{_esc(p["name"])}</a></td>'
                f'<td class="muted" style="font-size:.8rem">{addr_attr}</td>'
                f'<td><button class="btn btn-ghost btn-sm" data-pid="{pid}" data-addr="{addr_attr}"'
                f' onclick="geocodeProject(this.dataset.pid,this.dataset.addr)">📍 Geolocalizar</button></td></tr>')
    unmapped_rows = "".join(_unmapped_row(p) for p in unmapped)

    content = f"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<div class="toolbar"><h1>Mapa de intervenciones</h1>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <span class="muted" style="font-size:.875rem">{len(mapped)} ubicaciones · {len(unmapped)} sin geolocalizar</span>
    <button class="btn btn-ghost btn-sm" onclick="toggleRoutePanel()">🗺️ Optimizar ruta</button>
  </div>
</div>
<div id="route-panel" style="display:none;margin-bottom:16px">
  <div class="card" style="padding:16px">
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
      <strong>🗺️ Ruta óptima (vecino más cercano)</strong>
      <span class="muted" style="font-size:.82rem">Pulsa un marcador en el mapa como punto de inicio</span>
      <button class="btn btn-ghost btn-sm" onclick="clearRoute()">✕ Limpiar</button>
    </div>
    <ol id="route-list" style="padding-left:20px;line-height:1.8;font-size:.88rem;color:var(--muted)">
      <li>Haz clic en el marcador desde donde empiezas</li>
    </ol>
  </div>
</div>
<div style="border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1);margin-bottom:20px">
  <div id="map" style="height:460px;width:100%"></div>
</div>
{f'''<div class="card"><h2 style="margin-bottom:12px">Proyectos sin ubicación ({len(unmapped)})</h2>
<div class="tbl-wrap"><table><thead><tr><th>Proyecto</th><th>Dirección</th><th></th></tr></thead>
<tbody>{unmapped_rows}</tbody></table></div></div>''' if unmapped else ''}
<script>
var bp={_json.dumps(BP)};
var markers={markers_js};
var map=L.map('map').setView([40.4,-3.7],6);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
  maxZoom:19,attribution:'© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>'
}}).addTo(map);
var STATUS_COLOR={{"active":"#15803d","paused":"#b45309","completed":"#1558c2","cancelled":"#94a3b8"}};
var PRI_COLOR={{"urgent":"#dc2626","high":"#ea580c","normal":"#1558c2","low":"#64748b"}};
var PRI_LBL={{"urgent":"Urgente","high":"Alta","normal":"Normal","low":"Baja"}};
var STATUS_LBL={{"active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado","pending_approval":"Pend. firma"}};
markers.forEach(function(m){{
  var pc=PRI_COLOR[m.priority]||'#64748b';
  var sc=STATUS_COLOR[m.status]||'#64748b';
  var icon=L.divIcon({{
    html:'<div style="width:14px;height:14px;border-radius:50%;background:'+pc+';border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35)"></div>',
    iconSize:[14,14],iconAnchor:[7,7],className:''
  }});
  var _idx=markers.indexOf(m);
  var mk=L.marker([m.lat,m.lng],{{icon:icon}}).addTo(map);
  mk.on('click',function(){{
    if(document.getElementById('route-panel').style.display!=='none'){{
      buildRoute(_idx);
    }}
  }});
  mk.bindPopup(
    '<div style="min-width:180px">'
    +'<div style="font-weight:700;font-size:.9rem;margin-bottom:2px">'+m.name+'</div>'
    +'<div style="font-size:.8rem;color:#64748b;margin-bottom:6px">'+m.client+'</div>'
    +'<div style="font-size:.76rem;margin-bottom:6px">'
    +'<span style="color:'+sc+';font-weight:600">● '+(STATUS_LBL[m.status]||m.status)+'</span>'
    +'<span style="color:'+pc+';font-weight:600;margin-left:8px">▲ '+(PRI_LBL[m.priority]||m.priority)+'</span>'
    +'</div>'
    +(m.address?'<div style="font-size:.75rem;color:#94a3b8;margin-bottom:6px">📍 '+m.address+'</div>':'')
    +(m.tech?'<div style="font-size:.78rem;margin-bottom:6px">👤 '+m.tech+'</div>':'')
    +'<a href="'+m.url+'" style="font-size:.78rem;color:#1558c2;font-weight:600">→ Abrir proyecto</a>'
    +'</div>');
}});
if(markers.length>1){{
  var bounds=L.latLngBounds(markers.map(function(m){{return[m.lat,m.lng];}}));
  map.fitBounds(bounds,{{padding:[40,40]}});
}} else if(markers.length===1){{
  map.setView([markers[0].lat,markers[0].lng],14);
}}
/* ── Route optimization ── */
var _routeLayer=null,_startIdx=null;
function toggleRoutePanel(){{
  var p=document.getElementById('route-panel');
  p.style.display=p.style.display==='none'?'block':'none';
}}
function clearRoute(){{
  if(_routeLayer){{map.removeLayer(_routeLayer);_routeLayer=null;}}
  _startIdx=null;
  document.getElementById('route-list').innerHTML='<li>Haz clic en el marcador desde donde empiezas</li>';
}}
function buildRoute(startIdx){{
  if(markers.length<2) return;
  var unvisited=markers.map(function(_,i){{return i;}});
  var route=[startIdx];
  unvisited.splice(unvisited.indexOf(startIdx),1);
  while(unvisited.length){{
    var cur=route[route.length-1];
    var best=-1,bestD=Infinity;
    unvisited.forEach(function(j){{
      var d=Math.pow(markers[cur].lat-markers[j].lat,2)+Math.pow(markers[cur].lng-markers[j].lng,2);
      if(d<bestD){{bestD=d;best=j;}}
    }});
    route.push(best);
    unvisited.splice(unvisited.indexOf(best),1);
  }}
  if(_routeLayer) map.removeLayer(_routeLayer);
  var latlngs=route.map(function(i){{return[markers[i].lat,markers[i].lng];}});
  _routeLayer=L.polyline(latlngs,{{color:'#1e40af',weight:3,opacity:.7,dashArray:'8,6'}}).addTo(map);
  map.fitBounds(_routeLayer.getBounds(),{{padding:[30,30]}});
  var list=document.getElementById('route-list');
  list.innerHTML=route.map(function(i,n){{
    return '<li><strong>'+(n+1)+'.</strong> <a href="'+markers[i].url+'">'+markers[i].name+'</a>'
      +'<span class="muted"> — '+markers[i].client+'</span></li>';
  }}).join('');
}}
function geocodeProject(pid,address){{
  if(!address){{Toast.show('Este proyecto no tiene dirección. Edítalo primero.','err');return;}}
  fetch(bp+'/api/geocode?q='+encodeURIComponent(address))
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'No encontrado');}});}})
    .then(function(d){{
      return fetch(bp+'/api/projects/'+pid+'/geocode',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{lat:d.lat,lng:d.lng}})}});
    }})
    .then(function(r){{if(r.ok)location.reload();}})
    .catch(function(err){{Toast.show('No se encontró: '+address+' — '+err.message,'err');}});
}}
</script>"""
    return _shell("map", user, content, title="Mapa")
