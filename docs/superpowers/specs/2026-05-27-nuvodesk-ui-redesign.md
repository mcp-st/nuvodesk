# NuvoDesk UI/UX Redesign — Design Spec

**Fecha:** 2026-05-27  
**Proyecto:** [NUVODESK]  
**Problema:** La interfaz se percibe como construida a trozos por equipos distintos. Esquema de colores demasiado llamativo (gradientes agresivos, tonos neón). Detalle de proyecto fragmentado en demasiadas pestañas.  
**Objetivo:** Rediseño cohesivo con paleta Neutral Warm, eliminar gradientes decorativos, reorganizar la estructura del detalle de proyecto.

---

## 1. Sistema de diseño — Tokens CSS

### 1.1 Paleta de color (modo claro)

| Token | Valor actual | Valor nuevo | Uso |
|---|---|---|---|
| `--bg` | `#eef2ff` | `#fafaf9` | Fondo general (arena cálida) |
| `--bg2` | `#ffffff` | `#ffffff` | Superficie de cards y modales |
| `--bg3` | `#f8f9ff` | `#f5f5f4` | Fondo de campos de formulario, fondos secundarios |
| `--bg4` | `#f1f4fd` | `#e7e5e4` | Fondos de hover en tablas |
| `--text` | `#1a1d2e` | `#0f172a` | Texto principal |
| `--muted` | `#6b7196` | `#78716c` | Texto secundario (stone-500) |
| `--border` | `#e3e8f7` | `#e7e5e4` | Bordes de cards y separadores |
| `--primary` | `#4361ee` | `#0f172a` | Acento principal (navy carbón) |
| `--primary-dim` | `rgba(67,97,238,.09)` | `rgba(15,23,42,.06)` | Fondo de hover en nav |
| `--primary-light` | `#ebedff` | `#f5f5f4` | Fondo activo de nav, hover suave |
| `--secondary` | `#7209b7` | *(eliminado)* | — |
| `--grad` | `linear-gradient(135deg,#4361ee,#7209b7)` | *(eliminado)* | Reemplazado por colores planos |
| `--grad-soft` | gradiente RGBA | *(eliminado)* | — |
| `--green` | `#06d6a0` | `#15803d` | Estado activo / completado |
| `--green-dim` | `rgba(6,214,160,.1)` | `rgba(21,128,61,.08)` | Fondo de badge activo |
| `--amber` | `#f59e0b` | `#b45309` | Estado pausado / advertencia |
| `--amber-dim` | `rgba(245,158,11,.1)` | `rgba(179,83,9,.08)` | — |
| `--red` | `#f72585` | `#dc2626` | Estado urgente / error |
| `--red-dim` | `rgba(247,37,133,.1)` | `rgba(220,38,38,.08)` | — |
| `--violet` | `#7209b7` | *(eliminado)* | — |
| `--blue` | `#4361ee` | `#0f172a` | Alias de primary |
| `--side-bg` | `#ffffff` | `#fafaf9` | Fondo de sidebar |

### 1.2 Sombras

| Token | Valor nuevo |
|---|---|
| `--shadow` | `0 1px 3px rgba(0,0,0,.04), 0 2px 8px rgba(0,0,0,.06)` |
| `--shadow-md` | `0 4px 16px rgba(0,0,0,.08), 0 1px 4px rgba(0,0,0,.04)` |
| `--shadow-lg` | `0 12px 40px rgba(0,0,0,.12), 0 2px 8px rgba(0,0,0,.06)` |

Las sombras actuales usan color `rgba(67,97,238,...)` que tiñe de azul. Las nuevas son neutras.

### 1.3 Dark mode

Los tokens dark no cambian estructuralmente, solo se eliminan las referencias a `--grad` y `--secondary` del dark override. El dark mode sigue siendo opcional (toggle en sidebar).

---

## 2. Sidebar y navegación

### 2.1 Cambios en `.sidebar`

- **Logo mark** (`.logo-mark`): `background: var(--grad)` → `background: #0f172a`; eliminar `box-shadow` con color primario
- **Nav item activo** (`.nav-item.active`): `background: var(--grad)` → `background: #0f172a; color: #fff`; eliminar `box-shadow: 0 4px 14px rgba(67,97,238,.3)`
- **Nav item hover** (`.nav-item:hover`): `background: var(--bg3); color: #0f172a`
- **Sidebar background**: ya usa `var(--side-bg)`, que cambia a `#fafaf9` por el token
- **Timer widget** (`.sidebar-timer`): `background: color-mix(in srgb,var(--green,#15803d) 10%,var(--surface))` → `background: rgba(21,128,61,.07); border: 1px solid rgba(21,128,61,.2)`. Los valores `color-mix` no son necesarios.

### 2.2 Bottom nav (móvil)

- `.nav-item.active` en bottom nav hereda el cambio de tokens. Sin cambios adicionales.

---

## 3. Login

### 3.1 Layout

Se mantiene el diseño split de dos paneles (panel marca izquierdo + formulario derecho). En móvil el panel izquierdo se oculta.

### 3.2 Panel marca (izquierdo)

**Actual:** `linear-gradient(150deg, #1e1b4b 0%, #3730a3 60%, #4f46e5 100%)` con radial highlight  
**Nuevo:** fondo sólido `#0f172a`. Sin gradiente. El `brand-mark` (el "N") pasa a `background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.2)` — vidrio sutil sobre oscuro.

### 3.3 Formulario (derecho)

- `.form-logo`: `background: var(--grad)` → `background: #0f172a`; eliminar `box-shadow` con color primario
- Botón submit: `.btn-primary` hereda el nuevo color `#0f172a`
- Fondo del cuerpo: radial gradients actuales → fondo plano `var(--bg)` = `#fafaf9`
- `.login-wrap` border-radius: `24px` → `16px` (más contenido, menos redondeado)

---

## 4. Dashboard

### 4.1 KPI cards (`.kpi`)

**Problema actual:** `.kpi .val` usa `-webkit-background-clip: text` con gradientes, lo que produce números de color inconsistente y con artefactos en algunos navegadores.

**Cambio:**
- `.kpi .val`: eliminar `background`, `-webkit-background-clip`, `-webkit-text-fill-color`. Valor nuevo: `color: #0f172a`
- `.kpi.g .val`: `color: var(--green)` = `#15803d`
- `.kpi.a .val`: `color: var(--amber)` = `#b45309`
- `.kpi.r .val`: `color: var(--red)` = `#dc2626`
- `.kpi::after` (franja superior): `background: var(--grad)` → `background: #0f172a`
- `.kpi.g::after`: `background: #15803d`
- `.kpi.a::after`: `background: #b45309`
- `.kpi.r::after`: `background: #dc2626`
- `.kpi::before` (overlay hover): eliminar — era el gradiente soft en hover. Reemplazar por `background: rgba(0,0,0,.02)` en hover

### 4.2 Cards de alerta en dashboard

Las cards con `border-left:4px solid var(--amber/red/blue)` en `dashboard.py` se consolidan como el patrón único de alerta visual. No cambio estructural, solo heredan los nuevos colores de token.

### 4.3 Botón "⚡ Avería rápida"

Hereda `.btn-primary` que pasa a `background: #0f172a`. Sin cambio en el HTML.

---

## 5. Lista de proyectos

### 5.1 Project cards (`.proj-card`)

**Eliminar:**
- `.proj-card-strip` (la franja de 5px con gradiente en la parte superior): eliminada del HTML en `_project_card()`
- En hover: `transform: translateY(-4px)` → sin transform (demasiado "saltarín")

**Añadir:**
- Borde izquierdo de 3px codificado por estado en el elemento `.proj-card`:
  - `active` → `border-left: 3px solid #15803d`
  - `paused` → `border-left: 3px solid #b45309`
  - `cancelled` → `border-left: 3px solid #dc2626`
  - `completed` → `border-left: 3px solid #78716c`

**Badges de estado y prioridad** — paleta actual (sólidos neón) → nueva (fondo suave + borde):
| Estado | Fondo | Color texto | Borde |
|---|---|---|---|
| Activo | `#dcfce7` | `#15803d` | `#bbf7d0` |
| Pausado | `#fef3c7` | `#b45309` | `#fde68a` |
| Completado | `#f5f5f4` | `#78716c` | `#e7e5e4` |
| Cancelado | `#f5f5f4` | `#78716c` | `#e7e5e4` |

| Prioridad | Fondo | Color texto | Borde |
|---|---|---|---|
| Urgente | `#fee2e2` | `#dc2626` | `#fecaca` |
| Alta | `#fef3c7` | `#b45309` | `#fde68a` |
| Normal | `#f5f5f4` | `#78716c` | `#e7e5e4` |
| Baja | `#f5f5f4` | `#a8a29e` | `#e7e5e4` |

**Barra de progreso:** `background: var(--grad)` → color del estado (verde/ámbar/rojo/gris según estado del proyecto)

### 5.2 `.proj-card-foot`

Sin cambio estructural. Hereda tokens.

---

## 6. Detalle de proyecto — Reestructuración de pestañas

Este es el cambio más significativo en HTML/Python.

### 6.1 Cabecero permanente (nuevo)

Por encima de las pestañas, siempre visible, se añade una banda de contexto con:
- Nombre del proyecto + cliente
- Badges de estado y prioridad
- Fecha de vencimiento
- Botón "Editar" (abre modal existente)
- Mini KPI row: % avance (con barra), N/total tareas, horas totales, tareas pendientes
- Botón "▶ Iniciar jornada" (o "⏹ Parar" si hay timer activo)

Este cabecero sustituye la información que actualmente está dispersa dentro de la pestaña "Info".

Los campos secundarios del proyecto (descripción, dirección, tipo de trabajo) se muestran como una fila de metadatos en texto pequeño bajo el nombre del proyecto, dentro del mismo cabecero. Si la descripción es larga, se trunca a 2 líneas con un enlace "ver más" que expande inline. No se usa una pestaña separada ni un modal adicional para esto.

### 6.2 Estructura de pestañas — de 6 a 3

| Anterior | Nueva agrupación |
|---|---|
| Info | → contenido movido al cabecero permanente |
| Tareas | → **Trabajo** (tareas + horas + comentarios) |
| Horas | → fusionado en Trabajo |
| Archivos | → **Recursos** (archivos + kit/equipo) |
| Kit campo | → fusionado en Recursos |
| Comentarios | → fusionado en Trabajo |
| Cierre | → **Cierre** (checklist + albarán + firma) |

### 6.3 Pestaña Trabajo — layout en dos columnas (desktop)

En `≥1024px`:
```
┌─────────────────────────────┬──────────────────────┐
│  TAREAS                     │  HORAS REGISTRADAS   │
│  [checkbox] tarea 1 ✓       │  hoy: 3h 20m         │
│  [checkbox] tarea 2 ✓       │  ayer: 4h            │
│  [checkbox] tarea 3 (activa)│  ─────────────────── │
│  [checkbox] tarea 4         │  ACTIVIDAD RECIENTE  │
│  + Añadir tarea             │  [comentario 1]      │
│                             │  [cambio estado]     │
│                             │  [add comentario…]   │
└─────────────────────────────┴──────────────────────┘
```

En `<1024px` (tablet y móvil): las dos columnas se apilan en una sola columna (columna derecha pasa debajo).

Implementación: `display: grid; grid-template-columns: 1fr 360px` en desktop, `grid-template-columns: 1fr` en tablet/móvil.

### 6.4 Pestaña Recursos

Columna única. Secciones:
1. Archivos (grid actual, sin cambio estructural)
2. Equipamiento / Kit (tabla actual, sin cambio estructural)

### 6.5 Pestaña Cierre

Columna única. Secciones:
1. Checklist de cierre (checkboxes)
2. Firma cliente (botón modal existente + preview si existe)
3. Albarán PDF (botón link existente)

---

## 7. Componentes globales

### 7.1 Botones

| Clase | Actual | Nuevo |
|---|---|---|
| `.btn-primary` | `background: var(--grad)` | `background: #0f172a; color: #fff` |
| `.btn-primary:hover` | translateY + shadow azul | `background: #1e293b` (más claro) |
| `.btn-success` | gradiente verde turquesa | `background: #15803d` |
| `.btn-danger` | gradiente rosa→rojo | `background: #dc2626` |
| `.btn-amber` | gradiente ámbar | `background: #b45309` |
| `.btn-ghost` | borde `var(--border)` | sin cambio de estructura; hereda tokens |

### 7.2 Badges y chips (`.badge`, `.chip`)

`background: var(--primary-light); color: var(--primary)` heredan el cambio de tokens. Sin cambio de código.

### 7.3 Kanban task cards

`.task-card-strip` (franja izquierda de 4px): se mantiene como indicador de prioridad. Colores actualizados a la paleta sobria:
- Urgente: `#dc2626`
- Alta: `#b45309`
- Normal: `#0f172a`
- Baja: `#78716c`

`.task-card:hover`: `transform: translateY(-2px)` → eliminar transform, solo `box-shadow` más pronunciado.

### 7.4 Progress bars

`.progress-bar`: `background: var(--grad)` → `background: var(--green)` = `#15803d` por defecto. En contextos de alerta, se sobreescribe con color inline (ya se hace en algunos sitios).

### 7.5 Modales

`.modal`: `border-radius: 20px` → `16px`. Sin más cambios — hereda tokens.

### 7.6 Timer banner

`.timer-banner`: `background: linear-gradient(135deg,#06d6a0,#059669)` → `background: #15803d`. Eliminar gradiente.

---

## 8. Archivos afectados

| Archivo | Tipo de cambio | Alcance |
|---|---|---|
| `assets/styles/app.css` | Redefinir tokens `:root`, eliminar `.grad` en nav/botones/KPIs/progress | **Alto** — todo lo demás cascada |
| `web/pages/misc.py` | `_login_page()`: eliminar gradientes en brand panel y form-logo | Bajo |
| `web/pages/dashboard.py` | `_dashboard()` + `_my_day()`: KPI `.val` sin gradiente-texto | Bajo |
| `web/pages/projects.py` | `_project_card()`: quitar strip, añadir border-left; restructurar pestañas en `_project_detail()` | **Alto** |
| `app.py` | Cabecero permanente en detalle de proyecto; reestructurar contenido de pestañas Trabajo/Recursos/Cierre | **Alto** |

---

## 9. Fuera de alcance

- Cambios en lógica de negocio o endpoints de API
- Rediseño de páginas secundarias (Inventario, Calendario, Cargas, Mapa, Kit campo, Usuarios) — heredan los tokens automáticamente, no requieren cambios de HTML
- Cambios en el modo oscuro más allá de eliminar referencias a `--grad` y `--secondary`
- PWA manifest o iconos
