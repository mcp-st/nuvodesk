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
        addr_js = _json.dumps(p.get("address",""))
        return (f'<tr><td><a href="{BP}/projects/{pid}">{_esc(p["name"])}</a></td>'
                f'<td class="muted" style="font-size:.8rem">{_esc(p.get("address",""))}</td>'
                f'<td><button class="btn btn-ghost btn-sm" onclick="geocodeProject({pid},{addr_js})">📍 Geolocalizar</button></td></tr>')
    unmapped_rows = "".join(_unmapped_row(p) for p in unmapped)

    content = f"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<div class="toolbar"><h1>Mapa de intervenciones</h1>
  <span class="muted" style="font-size:.875rem">{len(mapped)} ubicaciones · {len(unmapped)} sin geolocalizar</span>
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
markers.forEach(function(m){{
  var sc=STATUS_COLOR[m.status]||'#64748b';
  var icon=L.divIcon({{
    html:'<div style="width:14px;height:14px;border-radius:50%;background:'+sc+';border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35)"></div>',
    iconSize:[14,14],iconAnchor:[7,7],className:''
  }});
  var mk=L.marker([m.lat,m.lng],{{icon:icon}}).addTo(map);
  mk.bindPopup(
    '<div style="min-width:180px">'
    +'<div style="font-weight:700;font-size:.9rem;margin-bottom:2px">'+m.name+'</div>'
    +'<div style="font-size:.8rem;color:#64748b;margin-bottom:6px">'+m.client+'</div>'
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
function geocodeProject(pid,address){{
  if(!address){{alert('Este proyecto no tiene dirección. Edítalo primero.');return;}}
  fetch('https://nominatim.openstreetmap.org/search?q='+encodeURIComponent(address)+'&format=json&limit=1',
    {{headers:{{'Accept':'application/json','User-Agent':'NuvoDesk/1.0'}}}})
    .then(function(r){{return r.json();}})
    .then(function(d){{
      if(!d.length){{alert('No se encontró la dirección: '+address);return;}}
      var lat=parseFloat(d[0].lat),lng=parseFloat(d[0].lon);
      fetch(bp+'/api/projects/'+pid+'/geocode',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{lat:lat,lng:lng}})}})
        .then(function(r){{if(r.ok)location.reload();}});
    }}).catch(function(){{alert('Error al geolocalizar. Comprueba la conexión.');}});
}}
</script>"""
    return _shell("map", user, content)
