# Trackr

Asistente de Negocio por Voz

Aplicación web para gestionar inventario, pedidos, clientes y empleados de un negocio, controlada mediante comandos de voz o chat de texto. El usuario habla o escribe, un agente de IA interpreta la instrucción y ejecuta la acción correspondiente sobre la base de datos. Si se usa voz, el audio se transcribe primero y el resultado cae en el mismo chat.

Estado: en desarrollo. Fase actual: construir el harness (voz → agente → herramientas → recordatorios) con SQLite, antes de conectar MySQL.

Ejemplo de uso

🎙️ "Recuérdame mañana a las 5 llamar al proveedor de empaques"

El navegador graba el audio y lo envía al backend.
Whisper lo transcribe a texto.
El agente interpreta la intención y llama a la herramienta crear_recordatorio.
El recordatorio se guarda en la base de datos con estado pendiente.
Cuando llega la fecha, el scheduler lo detecta y lo muestra en pantalla.
Se marca como entregado (no se borra, queda como historial).
Otros comandos previstos
Dices	El sistema hace
"¿Cuántas cajas medianas nos quedan?"	Consulta existencias del producto (consultar_existencia)
"¿Qué se está acabando?"	Lista productos por debajo de su stock mínimo (listar_stock_bajo)
"Recuérdame hacer restock de bolsas el viernes"	Crea un recordatorio manual
"¿Cómo va el pedido de Juan Pérez?"	Consulta el estado del pedido (consultar_estado_pedido)
"El pedido 124 salió por paquetería, guía 998877"	Registra el envío, cambia estado a enviado y descuenta existencias
"Ya entregamos el pedido 125"	Cambia estado a entregado y descuenta existencias (si no se descontaron antes)

Además de los recordatorios que pides tú, el sistema genera alertas automáticas de restock cuando un producto cae por debajo de su stock mínimo.

Arquitectura
Navegador (MediaRecorder)
   │  POST /api/voz  (audio)
   ▼
Backend FastAPI
   ├─ Whisper (OpenAI)  →  texto
   ├─ Agente (LangChain + tool calling)
   │     └─ Tools: crear_recordatorio, listar_recordatorios, ...
   └─ Capa de datos (SQLAlchemy)  →  SQLite (dev) / MySQL (prod)

Scheduler (APScheduler)
   └─ revisa recordatorios vencidos → los empuja al navegador (SSE)
Principios de diseño
El agente nunca escribe SQL. Solo llama herramientas con parámetros definidos por nosotros.
Capa de datos desacoplada. SQLAlchemy permite pasar de SQLite a MySQL cambiando únicamente la cadena de conexión.
Confirmación antes de acciones importantes. Whisper puede equivocarse con nombres de clientes o productos; las acciones destructivas o que escriben pedidos requieren confirmación del usuario.
No se borran registros por defecto. Se cambia el estado para conservar historial.
Voz y chat son equivalentes. Ambos desembocan en el mismo agente y las mismas herramientas. La voz solo agrega un paso previo (Whisper) y llena el cuadro de chat con lo transcrito.
El audio transcrito se puede revisar antes de enviarse. Así el usuario corrige errores de Whisper (nombres de clientes o productos) antes de que el agente actúe.
El chat guarda el contexto de la conversación. Permite seguimientos como "¿y de las medianas?" o responder "sí, confírmalo" a una confirmación pendiente.
Stack
Capa	Tecnología
Backend	Python 3.11+, FastAPI
Agente	LangChain
Voz a texto	OpenAI Whisper
Base de datos	SQLite (desarrollo) → MySQL (producción)
ORM	SQLAlchemy
Scheduler	APScheduler
Frontend	HTML + JavaScript (MediaRecorder, SSE)
Estructura del proyecto
.
├── app/
│   ├── main.py            # Punto de entrada FastAPI
│   ├── config.py          # Variables de entorno y settings
│   ├── api/
│   │   ├── voz.py         # POST /api/voz (audio → texto transcrito)
│   │   ├── chat.py        # POST /api/chat (mensaje de texto → agente)
│   │   └── eventos.py     # GET /api/eventos (SSE)
│   ├── agente/
│   │   ├── agente.py      # Construcción del agente
│   │   └── tools/
│   │       └── recordatorios.py
│   ├── db/
│   │   ├── base.py        # Engine y sesión
│   │   ├── modelos.py     # Modelos SQLAlchemy
│   │   └── repos.py       # Funciones de acceso a datos
│   ├── servicios/
│   │   ├── whisper.py     # Transcripción
│   │   └── scheduler.py   # Entrega de recordatorios
│   └── static/
│       └── index.html     # UI mínima con botón de voz
├── tests/
├── .env.example
├── requirements.txt
└── README.md
