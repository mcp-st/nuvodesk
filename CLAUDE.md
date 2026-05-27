# NuvoDesk [NUVODESK]

App de gestión de proyectos de telecomunicaciones para Nuvolink. Proyectos de instalación/avería/mantenimiento, asignación a técnicos, gestión de materiales (stock almacén vs campo), calendario, informes PDF.

## Rutas
- **Local:** `/home/admingemini/nuvodesk/`
- **VMSLAVE:** `10.1.50.97:8014` · `/srv/openclaw/projects/nuvodesk/`
- **VPS producción:** `https://dev.nupro.es/nuvodesk/` · `/srv/openclaw/projects/nuvodesk/`
- **GitHub:** `git@github.com:mcp-st/nuvodesk.git`

## Stack
Python stdlib HTTP server · SQLite · Vanilla JS SPA · PWA (mobile-first) · CSS externo (`assets/styles/app.css`)

## Archivos clave
- `app.py` — servidor HTTP, SCHEMA/init_db, Handler (~2161 líneas)
- `core/db.py` — PORT, BP, DATA_DIR, DB_PATH, helpers db/q/q1/run/rs/r2d
- `core/helpers.py` — _esc, _badge, _pcolor, _wt_badge, constantes, _stock_move
- `web/layout.py` — _shell(), _NAV_ICONS SVG
- `web/pages/` — dashboard, projects, inventory, kit, users, reports, calendar, workload, misc
- `assets/styles/app.css` — CSS externo (dark mode, tablet rail 768-1023px, mobile drawer)

## Deploy VMSLAVE
```bash
sshpass -p "openclaw" rsync -az --exclude '__pycache__/' --exclude '.venv/' --exclude 'data/' --exclude '.git/' \
  -e "sshpass -p 'openclaw' ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no" \
  /home/admingemini/nuvodesk/ tenacitas@10.1.50.97:/srv/openclaw/projects/nuvodesk/
sshpass -p "openclaw" ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no tenacitas@10.1.50.97 \
  "echo 'openclaw' | sudo -S systemctl restart nuvodesk"
```

## Deploy VPS producción
```bash
sshpass -p "mui0EoqONtdzoLD7" rsync -az --exclude '__pycache__/' --exclude '.venv/' --exclude 'data/' --exclude '.git/' \
  -e "sshpass -p 'mui0EoqONtdzoLD7' ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no" \
  /home/admingemini/nuvodesk/ tenacitas_assist@187.33.147.85:/tmp/deploy-nuvodesk/
sshpass -p "mui0EoqONtdzoLD7" ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no \
  tenacitas_assist@187.33.147.85 \
  "echo 'mui0EoqONtdzoLD7' | sudo -S rsync -a --exclude 'data/' \
     /tmp/deploy-nuvodesk/ /srv/openclaw/projects/nuvodesk/ && \
   echo 'mui0EoqONtdzoLD7' | sudo -S systemctl restart nuvodesk"
```

## Servicio systemd
- Nombre: `nuvodesk`
- Puerto: `8014`
- `BASE_PATH=/nuvodesk` (VPS) · vacío en VMSLAVE
