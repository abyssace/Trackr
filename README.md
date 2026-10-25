# Trackr

Trackr es una aplicación web para administrar inventario, pedidos, personal y recordatorios de un negocio. Se usa desde el navegador, con una interfaz de chat por texto y herramientas de gestión según el rol de cada cuenta.

## Qué puedes hacer

- Consultar productos, existencias, pedidos y recordatorios, de acuerdo con los permisos del usuario.
- Gestionar productos, categorías y proveedores; registrar movimientos de inventario y consultar su historial.
- Crear recordatorios personales. La fecha y hora deben ser futuras.
- Administrar cuentas de personal y sus roles.
- Gestionar precios: administración puede ver y editar compra y venta; ventas puede ver y editar únicamente el precio de venta. Los cambios quedan registrados con usuario y fecha/hora.
- Descargar respaldos con una cuenta administradora.

## Empezar en Windows

Necesitas Python 3.11 o posterior y [`uv`](https://docs.astral.sh/uv/).

En PowerShell, desde la carpeta del proyecto:

```powershell
uv sync --group dev
Copy-Item .env.example .env
```

Abre `.env` y configura al menos:

- `OPENROUTER_API_KEY`: tu clave de OpenRouter.
- `SECRET_KEY`: una clave larga y aleatoria para proteger las sesiones.

No compartas ni subas `.env` al repositorio. Para desarrollo, `.env.example` ya incluye los demás valores de ejemplo, como la base SQLite local y la zona horaria.

Prepara la base y crea el primer usuario administrador:

```powershell
uv run alembic upgrade head
uv run python -m scripts.crear_usuario --username admin --password "CambiaEstaClave" --nombre "Administrador" --rol administrador
```

Inicia el servidor:

```powershell
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abre <http://127.0.0.1:8000> e inicia sesión con el usuario creado. Detén el servidor con `Ctrl+C` en la terminal.

Opcionalmente, puedes añadir datos de ejemplo a una base local vacía:

```powershell
uv run python -m scripts.seed_negocio
```

No ejecutes el seed de datos de ejemplo en una base de producción.

## Roles

- **Administrador:** tiene acceso total. Puede usar el chat con todas las herramientas, gestionar productos, categorías, proveedores y movimientos de inventario, administrar personal y roles, gestionar precios, consultar su auditoría, desactivar productos y descargar respaldos.
- **Almacén:** administra productos, categorías, proveedores y movimientos de inventario.
- **Vendedor:** gestiona pedidos y puede cambiar precios de venta; no puede ver precios de compra.
- **Ensamblador:** consulta información operativa y registra productos terminados según los permisos de la aplicación.
- **Solo lectura:** consulta la información disponible sin herramientas de escritura.

Las cuentas nuevas se enlazan con el registro de empleado y deben cambiar su contraseña temporal en el primer inicio de sesión.

## Base de datos y pruebas

Trackr usa SQLite y Alembic. Antes de aplicar una migración a una base con datos, detén la aplicación y verifica un respaldo. Las migraciones se ejecutan manualmente; la aplicación no las aplica al arrancar.

Ejecuta las pruebas con:

```powershell
uv run pytest
```

Para desplegar la aplicación en Railway —incluidos el volumen persistente y los respaldos— consulta [`DEPLOY.md`](DEPLOY.md). La aplicación sirve la interfaz y la API desde el mismo servicio.
