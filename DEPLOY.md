# Despliegue de Trackr en Railway

Trackr es una aplicación FastAPI + SQLite diseñada para correr en un solo contenedor.

## Variables de entorno obligatorias

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `DATABASE_URL` | Ruta absoluta del SQLite en el volumen (`/data`) | `sqlite:////data/trackr.db` |
| `SECRET_KEY` | Clave para firmar sesiones (mínimo 32 caracteres) | `cambia-esto-en-produccion` |
| `OPENAI_API_KEY` | API key de OpenAI (preferida si está configurada) | `sk-...` |
| `OPENAI_BASE_URL` | Base URL opcional para OpenAI | `https://api.openai.com/v1` |
| `OPENROUTER_API_KEY` | API key de OpenRouter (fallback) | `sk-or-...` |
| `OPENROUTER_API_BASE_URL` | Base URL de OpenRouter | `https://openrouter.ai/api/v1` |
| `MODEL_AGENTE` | Modelo usado por el agente | `gpt-4o-mini` |
| `TIMEZONE` | Zona horaria para recordatorios y backups | `America/Monterrey` |

## Variables de entorno opcionales

| Variable | Descripción | Valor por defecto |
|----------|-------------|-------------------|
| `PORT` | Puerto del contenedor | `8000` |
| `BACKUP_DIR` | Directorio donde se guardan backups diarios | `/data/backups` |
| `BACKUP_RETENTION_DAYS` | Días que se conservan backups | `7` |
| `BACKUP_HOUR_UTC` | Hora UTC del backup diario | `6` |
| `SCHEDULER_INTERVAL_SECONDS` | Frecuencia del scheduler de recordatorios | `10` |
| `CHAT_RATE_LIMIT_PER_MINUTE` | Límite de mensajes por usuario/minuto | `60` |
| `MAX_LOGIN_ATTEMPTS` | Intentos de login antes de bloquear | `5` |
| `LOCKOUT_MINUTES` | Minutos de bloqueo tras intentos fallidos | `15` |
| `MEMORIA_MENSAJES_MAX` | Mensajes de historial por usuario | `20` |
| `MAX_AUDIO_SEGUNDOS` | Duración máxima de notas de voz | `60` |

## Despliegue en Railway (pasos manuales)

1. Crea un proyecto y un servicio vacío en Railway.
2. Conecta el repositorio de GitHub.
3. Configura la variable `DATABASE_URL` como `sqlite:////data/trackr.db` (cuatro `/`: ruta absoluta `/data/trackr.db` dentro del volumen).
4. Activa el **volume persistente** y móntalo en `/data`.
5. Configura `SECRET_KEY` y al menos una API key de LLM (`OPENAI_API_KEY` o `OPENROUTER_API_KEY`).
6. Despliega. Railway usará el `Dockerfile` incluido.

## Crear el primer administrador en Railway

No uses `scripts/seed_negocio` en producción. Ejecuta:

```bash
railway run -- uv run python -m scripts.crear_usuario \
    --username admin \
    --password "<seguro>" \
    --nombre "Administrador" \
    --rol administrador
```

## Backup y restauración

- El scheduler crea un backup online diario en `BACKUP_DIR`.
- Descarga el backup más reciente desde `/api/admin/backup` con un usuario administrador.
- Para restaurar localmente, copia el backup sobre `trackr.db`.

## Migraciones de SQLite

El esquema no se migra automáticamente al arrancar la aplicación. Antes de iniciar
una versión nueva, crea una copia de seguridad y aplica las migraciones con la
misma `DATABASE_URL` que usará Trackr:

```bash
uv run alembic upgrade head
```

En una base existente, detén la aplicación y verifica el backup antes de ejecutar
el comando. Las migraciones de catálogo, movimientos, roles/auditoría,
contraseña inicial y auditoría por trigger de precios son aditivas y usan modo batch de SQLite para conservar
los registros existentes. No se ejecutan desde `app.main` ni desde el seed. Los downgrades están bloqueados para evitar
eliminar códigos, precios, relaciones o responsables; para volver atrás, restaura
un backup revisado.

En una base nueva también se usa `alembic upgrade head`; Alembic crea el esquema
inicial y registra la revisión. Ejecuta `scripts.seed_negocio` solo después de
migrar y únicamente contra un archivo SQLite local.

## Notas

- No ejecutes más de una réplica contra el mismo volumen SQLite.
- El Dockerfile usa un solo worker (`--workers 1`) para evitar corrupción de SQLite.
- La aplicación habilita WAL en SQLite para mejorar concurrencia de lectura.
