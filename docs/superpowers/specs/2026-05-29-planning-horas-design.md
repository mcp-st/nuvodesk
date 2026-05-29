# Planificación de técnicos y registro de horas — Diseño

**Fecha:** 2026-05-29  
**Proyecto:** NuvoDesk [NUVODESK]  
**Estado:** Aprobado por usuario

---

## Objetivo

Reemplazar los tres sistemas de gestión de personal actuales (asignaciones por rango de fechas, slots hora a hora, temporizador de horas) por un sistema único, coherente y sin duplicación que cubra tanto la **planificación** (quién trabaja dónde y cuándo) como el **registro de horas reales** (qué se ejecutó). Incluye prevención de doble-booking y un flujo de solicitudes de cambio para técnicos.

---

## Problema actual

- `project_members`: asignaciones de rango de fechas (técnico → proyecto del día A al día B). Aparece en el calendario mensual como chips de color.
- `schedule_slots`: planificación hora a hora por día. Aparece en la vista de día del calendario. **Sin validación de conflictos** → permite doble-booking.
- `time_entries`: horas reales registradas con temporizador start/stop. Aparece en "Carga de trabajo".

Los tres sistemas no se hablan entre sí. El técnico no tiene una vista unificada de su agenda. "Carga de trabajo" es redundante con el calendario. El doble-booking ocurre en producción (incidente real).

---

## Modelo de datos

### Tablas nuevas

#### `activities` — reemplaza `project_members` + `schedule_slots`

```sql
CREATE TABLE activities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    activity_date TEXT NOT NULL,          -- 'YYYY-MM-DD'
    all_day     INTEGER NOT NULL DEFAULT 0, -- 1 = ocupa todo el día
    hour_start  INTEGER,                  -- 0-23, NULL si all_day
    hour_end    INTEGER,                  -- 0-23, NULL si all_day, exclusivo
    type        TEXT NOT NULL DEFAULT 'physical',
                                          -- physical|online|meeting|travel|other
    notes       TEXT DEFAULT '',
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT DEFAULT (datetime('now'))
);
```

**Regla de conflicto** (se valida en el servidor al crear/editar):
- Mismo `user_id` + mismo `activity_date`
- Los rangos se solapan: `A.hour_start < B.hour_end AND A.hour_end > B.hour_start`
- O alguna de las dos es `all_day=1`
- → Error 409, mensaje: "Conflicto: {nombre técnico} ya tiene '{proyecto}' de HH:00 a HH:00 ese día"

**Aviso no bloqueante** (warning, no error):
- El tipo es `physical` y el técnico tiene `tech_availability.status = 'traveling'` ese día
- → Se guarda pero la respuesta incluye `"warning": "El técnico está desplazado ese día"`

---

#### `tech_availability` — disponibilidad del técnico por día

```sql
CREATE TABLE tech_availability (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    avail_date  TEXT NOT NULL,            -- 'YYYY-MM-DD'
    status      TEXT NOT NULL DEFAULT 'available',
                                          -- available|remote|traveling|off
    notes       TEXT DEFAULT '',
    UNIQUE(user_id, avail_date)
);
```

Si no existe registro para un día, se asume `available`. Solo admins pueden crear/editar. Los técnicos pueden solicitarlo vía `change_requests`.

---

#### `work_logs` — reemplaza `time_entries`

```sql
CREATE TABLE work_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    log_date    TEXT NOT NULL,            -- 'YYYY-MM-DD'
    hours       REAL NOT NULL,            -- decimal: 0.5, 1.0, 3.5
    description TEXT DEFAULT '',
    activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT DEFAULT (datetime('now'))
);
```

Sin temporizador. Entrada manual siempre. El técnico registra solo las suyas; el admin puede registrar para cualquier técnico. El campo `activity_id` es opcional — permite registrar horas sin actividad planificada previa (urgencias, trabajo no planificado).

---

#### `change_requests` — solicitudes de cambio de técnico

```sql
CREATE TABLE change_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id     INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    requester_id    INTEGER NOT NULL REFERENCES users(id),
    admin_id        INTEGER NOT NULL REFERENCES users(id), -- created_by de la actividad
    type            TEXT NOT NULL,        -- cancel|reschedule|modify
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected
    admin_response  TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now')),
    resolved_at     TEXT
);
```

---

### Tablas obsoletas (datos de prueba cancelables)

- `schedule_slots` — se elimina
- `time_entries` — se elimina
- `project_members` — se mantiene para "equipo del proyecto" (quién está asignado al proyecto), **ya no se usa en el calendario**

---

## Roles y permisos

| Acción | Admin | Técnico | Backoffice |
|--------|:-----:|:-------:|:----------:|
| Crear/editar/eliminar activities (cualquier técnico) | ✅ | ❌ | ❌ |
| Ver activities | ✅ todas | ✅ solo las suyas | ✅ solo lectura |
| Crear/editar tech_availability | ✅ cualquiera | ❌ | ❌ |
| Crear work_logs | ✅ cualquiera | ✅ solo las suyas | ❌ |
| Editar/borrar work_logs | ✅ cualquiera | ✅ solo las suyas | ❌ |
| Crear change_request sobre actividad propia | — | ✅ | — |
| Aprobar/rechazar change_requests | ✅ | ❌ | ❌ |

---

## Vistas del calendario

El calendario pasa a ser la única página de planificación. La página "Carga de trabajo" se elimina del menú; su funcionalidad queda en la vista Semana.

### Vista Mes (por defecto)

Matriz técnicos × días del mes. Cada celda muestra:
- Color del proyecto de la actividad (o primer proyecto si hay varios)
- Icono del tipo: ⚡ física · 🌐 online · 👥 reunión · ✈️ viaje
- Fondo gris si `status = off`
- Fondo rayado / distinto si `status = traveling`
- Borde rojo si existe conflicto detectado (solo posible con datos migrados)

Click en celda → Vista Día de esa fecha.

Botón `+ Actividad` visible solo para admins.

### Vista Semana

Dos tabs: **Planificado** | **Registrado**.

- **Planificado**: actividades de la semana, técnicos × días, con horas planificadas totales por técnico al pie.
- **Registrado**: work_logs de la semana, técnicos × días, con horas registradas totales.

Botón `+ Registrar horas` en cada celda del tab Registrado (admin: cualquier técnico; técnico: solo la suya).

### Vista Día

Matriz hora a hora (06:00–20:00) × técnicos con actividades planificadas.

- Bloque coloreado por proyecto con tipo y hora de fin.
- Conflicto → celda roja con tooltip de error.
- Técnico con `traveling` → cabecera de columna con badge ✈️.
- Cada bloque tiene botón `✕` (admin: elimina) o `↩ Solicitar cambio` (técnico: abre modal).

---

## Registro de horas

Modal accesible desde Vista Semana (tab Registrado) y desde la página del proyecto.

Campos:
- Técnico (admin: cualquiera; técnico: solo él mismo)
- Proyecto (dropdown de proyectos activos/pausados)
- Fecha (date picker)
- Horas (decimal, validar > 0 y ≤ 24)
- Descripción (texto libre)
- Actividad vinculada (opcional — dropdown de actividades de ese técnico en esa fecha)

Editar/borrar: botones en la tabla de registros. Confirmación modal (sin `window.confirm`). Técnico solo puede editar/borrar las suyas.

En la página del proyecto: sección "Horas registradas" con tabla paginada (técnico, fecha, horas, descripción) y totales por técnico.

---

## Solicitudes de cambio

### Flujo

1. Técnico ve su actividad en Vista Día → botón "Solicitar cambio".
2. Modal: tipo (Cancelar / Reagendar / Modificar) + mensaje obligatorio.
3. Se crea `change_request` con `status = pending`.
4. Se genera notificación para el `admin_id` (el `created_by` de la actividad).
5. Admin abre notificación → ve el detalle completo de la actividad + solicitud.
6. Admin escribe respuesta opcional y elige Aprobar o Rechazar.
7. Si **Aprobar** + tipo `cancel`: la actividad se elimina. Tipos `reschedule`/`modify`: la actividad permanece (el admin la edita manualmente después de aprobar).
8. `change_request.status` → `approved` o `rejected`, `resolved_at` = now().
9. Se genera notificación para el técnico con la decisión y la respuesta del admin.

### Visibilidad

- Centro de notificaciones (ya existe): badge suma solicitudes pendientes dirigidas al admin.
- Vista Día: si una actividad tiene `change_request` pendiente, su bloque muestra un icono de alerta ⚠️.

---

## Cambios en navegación

- **Eliminar** "Carga de trabajo" del menú lateral y de `_NAV_ICONS` en `web/layout.py`.
- **Calendario** mantiene su posición con selector de vistas Mes / Semana / Día.
- Ruta `/workload` devuelve 404 o redirige a `/calendar`.

---

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `app.py` | Schema: añadir 4 tablas, eliminar `schedule_slots`/`time_entries`. ~10 endpoints nuevos (CRUD activities, work_logs, availability, change_requests). Eliminar rutas `/workload`, `/api/schedule_slots`. |
| `web/pages/calendar.py` | Reescritura completa. Vistas Mes/Semana/Día con nueva lógica. |
| `web/pages/workload.py` | Eliminar (o vaciar y redirigir). |
| `web/pages/projects.py` | Añadir sección "Horas registradas" con tabla work_logs. |
| `web/layout.py` | Eliminar "workload" de `_NAV_ICONS` y `_BOTTOM_NAV_KEYS`. |
| `core/db.py` | Sin cambios de estructura (schema vive en `app.py`). |

---

## Lo que NO entra en este diseño (YAGNI)

- Aprobación delegada (admin delega a otro admin).
- Solicitud de cambio con fecha alternativa propuesta por el técnico (el técnico escribe texto libre).
- Exportación de horas a nómina o facturación.
- Notificaciones push / email para change_requests (usa el sistema de notificaciones interno existente).
- Festivos / calendarios regionales.
