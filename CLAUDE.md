# NuvoDesk [NUVODESK]

App de gestión de proyectos de telecomunicaciones para Nuvolink. Proyectos de instalación/avería/mantenimiento, asignación a técnicos, gestión de materiales (stock almacén vs campo), calendario, informes PDF.

## Rutas
- **Local:** `/home/admingemini/nuvodesk/`
- **VPS producción (master):** `https://desk.nupro.es/` · `/srv/openclaw/projects/nuvodesk/`
- **VPS legacy (no usar):** `https://dev.nupro.es/nuvodesk/` · `/srv/nuvolink/apps/nuvodesk/`
- **GitHub:** `git@github.com:mcp-st/nuvodesk.git`

## Stack
Python stdlib HTTP server · SQLite · Vanilla JS SPA · PWA (mobile-first) · CSS externo (`assets/styles/app.css`)

## Archivos clave
- `app.py` — servidor HTTP, SCHEMA/init_db, Handler (~2800 líneas)
- `core/db.py` — PORT, BP, DATA_DIR, DB_PATH, helpers db/q/q1/run/rs/r2d
- `core/helpers.py` — _esc, _badge, _pcolor, _wt_badge, constantes, _stock_move
- `web/layout.py` — _shell(), _NAV_ICONS SVG
- `web/pages/` — dashboard, projects, inventory, kit, users, reports, calendar, workload, misc
- `assets/styles/app.css` — CSS externo (dark mode, tablet rail 768-1023px, mobile drawer)

## Deploy VPS producción (desk.nupro.es)
```bash
# 1. rsync a staging
sshpass -p "mui0EoqONtdzoLD7" rsync -az \
  --exclude '__pycache__/' --exclude '.venv/' --exclude 'data/' --exclude '.git/' \
  -e "ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no -o ServerAliveInterval=10 -o ServerAliveCountMax=12" \
  /home/admingemini/nuvodesk/ tenacitas_assist@187.33.147.85:/tmp/deploy-desk/

# 2. copiar a producción y reiniciar (UNA sola conexión SSH)
sshpass -p "mui0EoqONtdzoLD7" ssh \
  -o StrictHostKeyChecking=no -o PubkeyAuthentication=no \
  -o ServerAliveInterval=10 -o ServerAliveCountMax=12 \
  tenacitas_assist@187.33.147.85 \
  "echo 'mui0EoqONtdzoLD7' | sudo -S rsync -a --exclude 'data/' \
     /tmp/deploy-desk/ /srv/openclaw/projects/nuvodesk/ && \
   echo 'mui0EoqONtdzoLD7' | sudo -S systemctl restart nuvodesk-direct && \
   systemctl is-active nuvodesk-direct"
```

## Servicio systemd
- Nombre: `nuvodesk-direct`
- Puerto: `8015`
- Sin `BASE_PATH` (acceso directo en raíz `/`)
- Usuario: `www-data`
- WorkingDirectory: `/srv/openclaw/projects/nuvodesk`
