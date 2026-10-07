<div align="center">

# Trackr

**Tu negocio, a voz o por chat.**

Asistente web para gestionar inventario, pedidos, clientes y empleados con comandos de voz o texto.

![Estado](https://img.shields.io/badge/estado-en%20desarrollo-orange)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-4479A1?logo=mysql&logoColor=white)
![Licencia](https://img.shields.io/badge/licencia-por%20definir-lightgrey)

</div>

---

## Índice

- [Qué es Trackr](#qué-es-trackr)
- [Ejemplos de uso](#ejemplos-de-uso)
- [Arquitectura](#arquitectura)
- [Principios de diseño](#principios-de-diseño)
- [Stack](#stack)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Inicio rápido](#inicio-rápido)
- [Modelo de datos](#modelo-de-datos)
- [Herramientas del agente](#herramientas-del-agente)
- [Despliegue](#despliegue)
- [Seguridad](#seguridad)
- [Roadmap](#roadmap)
- [Pruebas](#pruebas)
- [Contribuir](#contribuir)
- [Licencia](#licencia)

---

## Qué es Trackr

Trackr es una aplicación web para llevar el control de un negocio: **inventario, pedidos, clientes y empleados**. En lugar de navegar menús y formularios, le hablas o le escribes en un chat y un agente de IA interpreta la instrucción, ejecuta la acción y te responde.

- 🎙️ **Voz**: el audio se transcribe con Whisper y el texto aparece en el chat para que lo revises antes de enviarlo.
- 💬 **Chat**: escribe la misma instrucción si prefieres no usar el micrófono.
- ⏰ **Recordatorios**: manuales y automáticos (por ejemplo, restock cuando baja el stock mínimo).
- 📦 **Pedidos e inventario**: al enviar o entregar un pedido, las existencias se actualizan solas.

> [!NOTE]
> **Estado actual:** en desarrollo. La fase en curso es construir el *harness* (voz/chat → agente → herramientas → recordatorios) sobre SQLite, antes de conectar MySQL.

---

## Ejemplos de uso

> 🎙️ *"Recuérdame mañana a las 5 llamar al proveedor de empaques"*

1. El navegador graba el audio y lo envía al backend.
2. Whisper lo transcribe y el texto aparece en el chat.
3. El agente interpreta la intención y llama a `crear_recordatorio`.
4. El recordatorio se guarda con estado `pendiente`.
5. Al llegar la fecha, el scheduler lo detecta y lo muestra en el chat.
6. Se marca como `entregado` (no se borra, queda como historial).

### Otros comandos previstos

| Dices | Trackr hace |
|---|---|
| *"¿Cuántas cajas medianas nos quedan?"* | Consulta existencias (`consultar_existencia`) |
| *"¿Qué se está acabando?"* | Lista productos bajo su stock mínimo (`listar_stock_bajo`) |
| *"Recuérdame hacer restock de bolsas el viernes"* | Crea un recordatorio manual |
| *"¿Cómo va el pedido de Juan Pérez?"* | Consulta el estado del pedido (`consultar_estado_pedido`) |
| *"El pedido 124 salió por paquetería, guía 998877"* | Registra el envío, pasa a `enviado` y descuenta existencias |
| *"Ya entregamos el pedido 125"* | Pasa a `entregado` y descuenta existencias si no se habían descontado |

Además de los recordatorios que pides, Trackr genera **alertas automáticas de restock** cuando un producto cae por debajo de su stock mínimo.

---

## Arquitectura

```mermaid
flowchart TD
    U["👤 Usuario<br/>(chat o voz)"]
    U -->|texto| C["POST /api/chat"]
    U -->|audio| V["POST /api/voz"]
    V --> W["Whisper<br/>audio → texto"]
    W -->|"texto para revisar"| U
    C --> A["Agente<br/>LangChain + tool calling"]
    A --> T["Tools"]
    T --> D[("SQLAlchemy<br/>SQLite / MySQL")]
    S["Scheduler<br/>APScheduler"] --> D
    S -->|"SSE"| U
```

El agente nunca toca la base de datos directamente: solo llama herramientas (*tools*) con parámetros definidos por nosotros.

---

## Principios de diseño

| Principio | Qué significa |
|---|---|
| **El agente nunca escribe SQL** | Solo llama herramientas con parámetros acotados. |
| **Capa de datos desacoplada** | SQLAlchemy permite pasar de SQLite a MySQL cambiando solo la cadena de conexión. |
| **Confirmación antes de actuar** | Las acciones que escriben pedidos o modifican inventario piden confirmación, porque Whisper puede equivocarse con nombres. |
| **No se borra, se cambia de estado** | Se conserva el historial para auditoría y recuperación. |
| **Voz y chat son equivalentes** | Ambos llegan al mismo agente y las mismas herramientas. |
| **La transcripción se puede corregir** | El texto de Whisper aparece en el cuadro del chat antes de enviarse. |
| **Memoria de conversación** | Permite seguimientos como *"¿y de las medianas?"* o responder *"sí, confírmalo"*. |

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11+, FastAPI |
| Agente | LangChain |
| Voz a texto | OpenAI Whisper |
| Base de datos | SQLite (desarrollo) → MySQL (producción) |
| ORM | SQLAlchemy |
| Scheduler | APScheduler |
| Frontend | HTML + JavaScript (MediaRecorder, SSE) |

---

## Estructura del proyecto

<details>
<summary>Ver árbol de carpetas</summary>

```
.
├── app/
│   ├── main.py              # Punto de entrada FastAPI
│   ├── config.py            # Variables de entorno y settings
│   ├── api/
│   │   ├── voz.py           # POST /api/voz   (audio → texto transcrito)
│   │   ├── chat.py          # POST /api/chat  (mensaje → agente)
│   │   └── eventos.py       # GET  /api/eventos (SSE)
│   ├── agente/
│   │   ├── agente.py        # Construcción del agente
│   │   └── tools/
│   │       └── recordatorios.py
│   ├── db/
│   │   ├── base.py          # Engine y sesión
│   │   ├── modelos.py       # Modelos SQLAlchemy
│   │   └── repos.py         # Acceso a datos
│   ├── servicios/
│   │   ├── whisper.py       # Transcripción
│   │   └── scheduler.py     # Entrega de recordatorios
│   └── static/
│       └── index.html       # UI mínima de chat con botón de voz
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

</details>

---

## Inicio rápido

### Requisitos

- Python 3.11 o superior
- API key de OpenAI
- Navegador con soporte de `MediaRecorder` (Chrome, Edge, Firefox)

> [!IMPORTANT]
> El micrófono solo funciona en `localhost` o con `https`.

### Instalación

```bash
git clone <url-del-repo>
cd trackr

python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env             # Edita .env con tus valores
```

### Variables de entorno

```env
OPENAI_API_KEY=sk-...
DATABASE_URL=sqlite:///./dev.db
# Producción:
# DATABASE_URL=mysql+pymysql://usuario:password@host:3306/trackr
TIMEZONE=America/Monterrey
MODEL_AGENTE=gpt-4o-mini
```

> [!WARNING]
> Nunca subas `.env` al repositorio. Agrega `.env`, `.venv/` y `*.db` a tu `.gitignore`.

### Ejecutar

```bash
uvicorn app.main:app --reload
```

Abre <http://localhost:8000> y escribe en el chat o mantén presionado el micrófono para hablar.

---

## Modelo de datos

### Fase 1: recordatorios

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | int | Identificador |
| `texto` | string | Contenido del recordatorio |
| `fecha_hora` | datetime | Cuándo debe dispararse |
| `estado` | enum | `pendiente`, `entregado`, `cancelado` |
| `creado_en` | datetime | Fecha de creación |

### Fase 3: negocio

| Tabla | Campos clave |
|---|---|
| `productos` | id, nombre, sku, existencia, stock_minimo, alias (nombres dichos en voz) |
| `clientes` | id, nombre, telefono, direccion |
| `empleados` | id, nombre, rol |
| `pedidos` | id, cliente_id, estado, tipo_entrega (`directa` / `paqueteria`), paqueteria, guia, inventario_descontado, creado_en |
| `pedido_items` | pedido_id, producto_id, cantidad |
| `movimientos_inventario` | id, producto_id, cantidad (+/-), motivo (`venta`, `entrada`, `ajuste`), pedido_id, creado_en |

### Estados de un pedido

```mermaid
stateDiagram-v2
    [*] --> pendiente
    pendiente --> enviado: paquetería
    pendiente --> entregado: entrega directa
    enviado --> entregado
    pendiente --> cancelado
    enviado --> cancelado
```

### Regla de descuento de existencias

<details>
<summary>Cómo se evita descontar dos veces el mismo pedido</summary>

- **Paquetería:** se descuenta al pasar a `enviado`, porque la mercancía ya salió.
- **Entrega directa:** se descuenta al pasar a `entregado`.
- El campo `inventario_descontado` impide que el descuento se aplique más de una vez.
- Cada descuento queda como una fila en `movimientos_inventario`, no solo como un número editado, lo que permite auditar y corregir errores.
- El cambio de estado y el descuento ocurren en **una sola transacción**: si uno falla, ninguno se aplica.

> [!NOTE]
> Es una propuesta. Si en tu negocio el stock debe descontarse al crear el pedido, o necesitas una columna de "apartado", se ajusta aquí.

</details>

### Alertas automáticas de restock

El scheduler revisa periódicamente los productos con `existencia <= stock_minimo` y crea una alerta. Solo genera una nueva si no hay una pendiente para ese producto, y la cierra cuando se registra una entrada de mercancía.

---

## Herramientas del agente

| Tool | Acción | ¿Pide confirmación? |
|---|---|:---:|
| `crear_recordatorio` | Crea un recordatorio manual | ❌ |
| `listar_recordatorios` | Lista recordatorios pendientes | ❌ |
| `consultar_existencia` | Existencia de un producto (si hay varias coincidencias, pregunta cuál) | ❌ |
| `listar_stock_bajo` | Productos bajo su stock mínimo | ❌ |
| `consultar_estado_pedido` | Estado de un pedido por número o cliente | ❌ |
| `registrar_entrada_mercancia` | Suma existencias tras un restock | ✅ |
| `registrar_envio` | Pasa a `enviado`, guarda paquetería y guía, descuenta stock | ✅ |
| `marcar_entregado` | Pasa a `entregado` y descuenta stock si no se había hecho | ✅ |

---

## Despliegue

La ruta recomendada para empezar es un **VPS con Docker Compose** (app + MySQL + Caddy para HTTPS automático).

<details>
<summary>Requisitos y recomendaciones</summary>

- **Proceso persistente:** el scheduler y las conexiones SSE no funcionan en plataformas serverless.
- **HTTPS obligatorio:** sin certificado, el navegador bloquea el micrófono.
- **Un solo scheduler:** con varios workers los recordatorios se duplican. Corre una sola instancia o separa el scheduler.
- **MySQL con volumen persistente** y respaldos diarios guardados fuera del servidor.
- **Migraciones con Alembic** para cambiar tablas sin perder datos.
- **SSE detrás del proxy:** desactiva el búfer de respuestas si usas Nginx.
- **Zona horaria consistente** entre servidor, base de datos y aplicación.

</details>

> [!IMPORTANT]
> La autenticación debe estar lista **antes** de publicar la app. Sin login, cualquiera con la URL puede ver tus pedidos y gastar tu cuota de OpenAI.

---

## Seguridad

- Las herramientas del agente son funciones acotadas; no hay ejecución de SQL arbitrario.
- En producción, el usuario de MySQL solo debe tener los permisos necesarios (sin `DROP`, `ALTER`, etc.).
- Se registra cada comando (texto, herramienta llamada y resultado) para poder auditar.
- Los parámetros que genera el agente se validan antes de escribir en la base de datos.
- Límites de uso por usuario en el endpoint de voz y tope de gasto en la cuenta de OpenAI.

---

## Roadmap

### Fase 1: Harness
- [ ] Endpoint de chat + agente con `crear_recordatorio` y `listar_recordatorios`
- [ ] Interfaz de chat (historial y respuestas en streaming)
- [ ] Memoria de conversación por sesión
- [ ] Persistencia con SQLAlchemy + SQLite
- [ ] Scheduler y entrega por SSE (los recordatorios aparecen en el chat)
- [ ] Captura de voz y transcripción con Whisper
- [ ] Paso de confirmación (*"Entendí: … ¿confirmo?"*)

### Fase 2: MySQL
- [ ] Migrar `DATABASE_URL` a MySQL
- [ ] Migraciones con Alembic
- [ ] Usuario de base de datos con permisos limitados

### Fase 3: Dominio del negocio
- [ ] Clientes y empleados
- [ ] Inventario: productos, existencias y movimientos
- [ ] Alertas automáticas de restock
- [ ] Pedidos: crear, consultar y cambiar estado
- [ ] Envíos por paquetería y actualización de existencias
- [ ] Descuento de inventario transaccional e idempotente

### Fase 4: Producto
- [ ] Autenticación y roles
- [ ] Frontend con framework (React u otro)
- [ ] Historial de comandos y auditoría
- [ ] Despliegue

---

## Pruebas

```bash
pytest
```

## Contribuir

1. Crea una rama: `git checkout -b feature/nombre`
2. Haz commits pequeños y descriptivos.
3. Abre un Pull Request explicando el cambio.

## Licencia

Por definir.
