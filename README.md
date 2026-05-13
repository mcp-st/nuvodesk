# NuvoDesk

Project & materials management for Nuvolink field operations.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 (stdlib) · SQLite · WAL mode |
| Frontend | Vanilla JS SPA · mobile-first CSS · PWA |
| Android app | Flutter (Phase 2 — planned) |
| Deploy | vmslave `10.1.50.97` → production VPS |

## Modules

- **Projects** — status, client, location, dates, assigned technician
- **Tasks** — per-project, assigned to user, subtasks, comments, photo attachments
- **Inventory** — materials with available stock, minimum stock, warehouse vs field
- **Material assignment** — reserve from warehouse to project; on close → consumed or returned
- **Users & roles** — admin, field technician, backoffice
- **Dashboard** — active projects, critical stock, workload per technician

## Running locally

```bash
python3 app.py
# → http://localhost:8014
```

First run creates `admin` / `admin` — change from settings panel.

## Deploy to vmslave

```bash
bash scripts/deploy.sh
```

URL: `http://10.1.50.97/nuvodesk/`

## Phase 2 — Android app

Planned Flutter app in `android-app/`. Consumes the same REST API exposed by `app.py`.
Distributed as APK (no Play Store required).

## Port assignment

| App | Port |
|-----|------|
| lan-discovery | 8011 |
| switch-proxy | 8012 |
| deckbuddy | 8013 |
| **nuvodesk** | **8014** |
