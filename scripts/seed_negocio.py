import argparse
import sys
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.base import SessionLocal, engine
from app.db.modelos import Usuario
from app.servicios.auth import get_password_hash
from app.servicios.roles import Rol
from app.db.negocio import (
    Cliente,
    Empleado,
    TipoMedidor,
    Medidor,
    Tamano,
    TipoUTD,
    Categoria,
    Proveedor,
    Producto,
    Receta,
    Pedido,
    PedidoItem,
    MovimientoInventario,
)


def _es_sqlite_local(url: str | None = None) -> bool:
    try:
        parsed = make_url(url or settings.DATABASE_URL)
    except Exception:
        return False
    if not parsed.drivername.startswith("sqlite") or not parsed.database:
        return False
    database = parsed.database.lower()
    memory_mode = any(
        key.lower() == "mode" and str(value).lower() == "memory"
        for key, value in (parsed.query or {}).items()
    )
    return database != ":memory:" and not database.startswith("file::memory:") and not memory_mode


def _obtener_o_crear(db, modelo, nombre: str, **valores):
    registro = db.query(modelo).filter(modelo.nombre == nombre).first()
    if registro:
        return registro
    registro = modelo(nombre=nombre, **valores)
    db.add(registro)
    db.flush()
    return registro


def _asegurar_catalogos_inventario(db):
    categorias = {
        "componentes": _obtener_o_crear(
            db, Categoria, "Componentes", descripcion="Refacciones y piezas para ensamble"
        ),
        "empaque": _obtener_o_crear(
            db, Categoria, "Empaque", descripcion="Materiales de empaque"
        ),
        "medidores": _obtener_o_crear(
            db, Categoria, "Medidores", descripcion="Medidores terminados"
        ),
    }
    proveedores = {
        "regio": _obtener_o_crear(
            db,
            Proveedor,
            "Suministros Regiomontanos S.A. de C.V.",
            contacto="Mariana Salas",
            telefono="8180001200",
            correo="ventas@ejemplo.mx",
        ),
        "norte": _obtener_o_crear(
            db,
            Proveedor,
            "Componentes del Norte S. de R.L. de C.V.",
            contacto="Jorge Luna",
            telefono="8180003400",
            correo="pedidos@ejemplo.mx",
        ),
    }
    return categorias, proveedores


def _tiene_datos_negocio(db) -> bool:
    return any(
        db.query(modelo).first() is not None
        for modelo in (Cliente, Empleado, Producto, Pedido, MovimientoInventario)
    )


def _sembrar_productos_demo_aditivos(db, categorias, proveedores):
    """Añade ejemplos con códigos estables; nunca borra ni sobrescribe productos."""
    demo = [
        {
            "nombre": "Medidor residencial 1 pulgada (demo)",
            "codigo": "DEMO-MED-001",
            "tipo": "terminado",
            "unidad_medida": "pieza",
            "stock_minimo": 5,
            "categoria_id": categorias["medidores"].id,
            "proveedor_id": proveedores["regio"].id,
            "precio_compra": Decimal("420.00"),
            "precio_venta": Decimal("690.00"),
            "cantidad": 8,
        },
        {
            "nombre": "Válvula de latón 1/2 pulgada (demo)",
            "codigo": "DEMO-CMP-001",
            "tipo": "componente",
            "unidad_medida": "pieza",
            "stock_minimo": 8,
            "categoria_id": categorias["componentes"].id,
            "proveedor_id": proveedores["norte"].id,
            "precio_compra": Decimal("85.50"),
            "precio_venta": Decimal("139.90"),
            "cantidad": 12,
        },
        {
            "nombre": "Empaque O-ring NBR (demo)",
            "codigo": "DEMO-EMP-001",
            "tipo": "componente",
            "unidad_medida": "pieza",
            "stock_minimo": 10,
            "categoria_id": categorias["empaque"].id,
            "proveedor_id": proveedores["norte"].id,
            "precio_compra": Decimal("5.75"),
            "precio_venta": Decimal("12.50"),
            "cantidad": 7,
        },
    ]
    for valores in demo:
        existente = db.query(Producto).filter(
            (Producto.codigo == valores["codigo"])
            | (Producto.nombre == valores["nombre"])
        ).first()
        if existente:
            continue
        cantidad = valores.pop("cantidad")
        producto = Producto(**valores)
        db.add(producto)
        db.flush()
        db.add(
            MovimientoInventario(
                producto_id=producto.id,
                cantidad=cantidad,
                tipo_movimiento="entrada",
                referencia=f"Seed demo {producto.codigo}",
            )
        )


def _crear_usuario_admin(db):
    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    if admin:
        return

    admin = Usuario(
        nombre="Administrador",
        username="admin",
        password_hash=get_password_hash("admin"),
        activo=True,
        es_admin=True,
        rol=Rol.ADMINISTRADOR.value,
    )
    db.add(admin)
    db.commit()


def seed(database_url: str | None = None):
    target_url = database_url or settings.DATABASE_URL
    if not _es_sqlite_local(target_url):
        print(
            "ERROR: Este script solo puede ejecutarse contra un archivo SQLite local.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Suprimir warning inofensivo de passlib con bcrypt >=4.1
    import logging

    logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)

    owns_engine = database_url is not None
    target_engine = create_engine(
        target_url,
        connect_args={"check_same_thread": False},
    ) if owns_engine else engine
    target_sessions = sessionmaker(autocommit=False, autoflush=False, bind=target_engine) if owns_engine else SessionLocal
    db = target_sessions()
    try:
        _crear_usuario_admin(db)
        categorias, proveedores = _asegurar_catalogos_inventario(db)
        if _tiene_datos_negocio(db):
            _sembrar_productos_demo_aditivos(db, categorias, proveedores)
            db.commit()
            print("[OK] Seed aditivo de inventario completado.")
            print(f"   Productos: {db.query(Producto).count()}")
            print(f"   Movimientos: {db.query(MovimientoInventario).count()}")
            return

        # Catálogos
        tipos_medidor = {
            "domestico": TipoMedidor(
                nombre="Doméstico", descripcion="Uso residencial"
            ),
            "industrial": TipoMedidor(
                nombre="Industrial", descripcion="Uso comercial e industrial"
            ),
        }
        db.add_all(tipos_medidor.values())
        db.flush()

        medidores = {
            "a100": Medidor(
                nombre_modelo="A-100",
                descripcion="Medidor doméstico estándar",
                tipo_medidor_id=tipos_medidor["domestico"].id,
            ),
            "b200": Medidor(
                nombre_modelo="B-200",
                descripcion="Medidor industrial alto caudal",
                tipo_medidor_id=tipos_medidor["industrial"].id,
            ),
            "c300": Medidor(
                nombre_modelo="C-300",
                descripcion="Medidor doméstico compacto",
                tipo_medidor_id=tipos_medidor["domestico"].id,
            ),
        }
        db.add_all(medidores.values())

        tamanos = {
            1: Tamano(pulgadas=1),
            2: Tamano(pulgadas=2),
            3: Tamano(pulgadas=3),
        }
        db.add_all(tamanos.values())

        tipos_utd = {
            "clasica": TipoUTD(
                nombre="Clásica", descripcion="Tecnología tradicional", tecnologia="Mecánica"
            ),
            "inteligente": TipoUTD(
                nombre="Inteligente",
                descripcion="Lectura remota",
                tecnologia="Ultrasonido",
            ),
        }
        db.add_all(tipos_utd.values())
        db.flush()

        # Clientes
        clientes = [
            Cliente(
                nombre="Juan Pérez",
                rfc="PEJU800101ABC",
                telefono="8112345678",
                correo="juan@ejemplo.mx",
            ),
            Cliente(
                nombre="María García",
                rfc="GAMA850202DEF",
                telefono="8123456789",
                correo="maria@ejemplo.mx",
            ),
            Cliente(
                nombre="Distribuidora del Norte",
                razon_social="Distribuidora del Norte S.A. de C.V.",
                rfc="DIN090909XYZ",
                telefono="8134567890",
                correo="compras@dnorte.mx",
            ),
            Cliente(
                nombre="Constructora López",
                razon_social="Constructora López S.A. de C.V.",
                rfc="CLO101010UVW",
                telefono="8145678901",
                correo="pedidos@clopez.mx",
            ),
        ]
        db.add_all(clientes)

        # Empleados
        empleados = [
            Empleado(nombre="Pedro Sánchez", rol="Vendedor", telefono="8111111111"),
            Empleado(nombre="Ana Martínez", rol="Almacén", telefono="8222222222"),
            Empleado(nombre="Luis Torres", rol="Producción", telefono="8333333333"),
        ]
        db.add_all(empleados)
        db.flush()

        # Componentes
        componentes = {
            "sellos": Producto(
                nombre="Sellos de seguridad",
                tipo="componente",
                unidad_medida="pieza",
                stock_minimo=50,
                alias="sellos",
            ),
            "cajas": Producto(
                nombre="Cajas medianas",
                tipo="componente",
                unidad_medida="pieza",
                stock_minimo=10,
                alias="cajas medianas,cajas",
            ),
            "bolsas": Producto(
                nombre="Bolsas de empaque",
                tipo="componente",
                unidad_medida="pieza",
                stock_minimo=100,
                alias="bolsas,bolsas de empaque",
            ),
            "tornillos": Producto(
                nombre="Tornillos hexagonales",
                tipo="componente",
                unidad_medida="pieza",
                stock_minimo=200,
                alias="tornillos",
            ),
            "carcasa": Producto(
                nombre="Carcasa de medidor",
                tipo="componente",
                unidad_medida="pieza",
                stock_minimo=20,
                alias="carcasa",
            ),
            "sensor": Producto(
                nombre="Sensor de flujo",
                tipo="componente",
                unidad_medida="pieza",
                stock_minimo=15,
                alias="sensor",
            ),
        }

        # Productos terminados
        terminados = {
            "med_dom_1_clas": Producto(
                nombre="Medidor A-100 1 pulgada UTD Clásica",
                tipo="terminado",
                unidad_medida="pieza",
                stock_minimo=5,
                medidor_id=medidores["a100"].id,
                tamano_id=tamanos[1].id,
                tipo_utd_id=tipos_utd["clasica"].id,
                alias="medidor 1 pulgada,medidor domestico clasico",
            ),
            "med_dom_2_clas": Producto(
                nombre="Medidor A-100 2 pulgadas UTD Clásica",
                tipo="terminado",
                unidad_medida="pieza",
                stock_minimo=3,
                medidor_id=medidores["a100"].id,
                tamano_id=tamanos[2].id,
                tipo_utd_id=tipos_utd["clasica"].id,
                alias="medidor 2 pulgadas",
            ),
            "med_ind_3_int": Producto(
                nombre="Medidor B-200 3 pulgadas UTD Inteligente",
                tipo="terminado",
                unidad_medida="pieza",
                stock_minimo=2,
                medidor_id=medidores["b200"].id,
                tamano_id=tamanos[3].id,
                tipo_utd_id=tipos_utd["inteligente"].id,
                alias="medidor industrial inteligente",
            ),
        }

        productos = {**componentes, **terminados}
        inventario_seed = {
            "sellos": ("DEMO-CMP-002", "componentes", "norte", "18.00", "29.00"),
            "cajas": ("DEMO-EMP-002", "empaque", "regio", "12.50", "22.00"),
            "bolsas": ("DEMO-EMP-003", "empaque", "regio", "1.20", "2.50"),
            "tornillos": ("DEMO-CMP-003", "componentes", "norte", "0.85", "1.80"),
            "carcasa": ("DEMO-CMP-004", "componentes", "norte", "75.00", "125.00"),
            "sensor": ("DEMO-CMP-005", "componentes", "norte", "110.00", "185.00"),
            "med_dom_1_clas": ("DEMO-MED-002", "medidores", "regio", "420.00", "690.00"),
            "med_dom_2_clas": ("DEMO-MED-003", "medidores", "regio", "590.00", "920.00"),
            "med_ind_3_int": ("DEMO-MED-004", "medidores", "regio", "1450.00", "2250.00"),
        }
        for clave, producto in productos.items():
            codigo, categoria, proveedor, precio_compra, precio_venta = inventario_seed[clave]
            producto.codigo = codigo
            producto.categoria_id = categorias[categoria].id
            producto.proveedor_id = proveedores[proveedor].id
            producto.precio_compra = Decimal(precio_compra)
            producto.precio_venta = Decimal(precio_venta)
        db.add_all(productos.values())
        db.flush()

        # Recetas (BOM)
        recetas = [
            Receta(
                producto_terminado_id=terminados["med_dom_1_clas"].id,
                producto_componente_id=componentes["carcasa"].id,
                cantidad_requerida=1,
            ),
            Receta(
                producto_terminado_id=terminados["med_dom_1_clas"].id,
                producto_componente_id=componentes["sensor"].id,
                cantidad_requerida=1,
            ),
            Receta(
                producto_terminado_id=terminados["med_dom_1_clas"].id,
                producto_componente_id=componentes["sellos"].id,
                cantidad_requerida=2,
            ),
            Receta(
                producto_terminado_id=terminados["med_dom_1_clas"].id,
                producto_componente_id=componentes["tornillos"].id,
                cantidad_requerida=4,
            ),
            Receta(
                producto_terminado_id=terminados["med_ind_3_int"].id,
                producto_componente_id=componentes["carcasa"].id,
                cantidad_requerida=1,
            ),
            Receta(
                producto_terminado_id=terminados["med_ind_3_int"].id,
                producto_componente_id=componentes["sensor"].id,
                cantidad_requerida=2,
            ),
        ]
        db.add_all(recetas)

        # Stock inicial vía movimientos (ledger)
        movimientos = [
            # Componentes
            MovimientoInventario(
                producto_id=componentes["sellos"].id,
                cantidad=120,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=componentes["cajas"].id,
                cantidad=8,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=componentes["bolsas"].id,
                cantidad=300,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=componentes["tornillos"].id,
                cantidad=500,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=componentes["carcasa"].id,
                cantidad=40,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=componentes["sensor"].id,
                cantidad=20,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            # Terminados
            MovimientoInventario(
                producto_id=terminados["med_dom_1_clas"].id,
                cantidad=12,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=terminados["med_dom_2_clas"].id,
                cantidad=5,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
            MovimientoInventario(
                producto_id=terminados["med_ind_3_int"].id,
                cantidad=4,
                tipo_movimiento="entrada",
                referencia="Inventario inicial",
            ),
        ]
        db.add_all(movimientos)

        # Pedidos
        pedidos = [
            Pedido(
                cliente_id=clientes[0].id,  # Juan Pérez
                empleado_id=empleados[0].id,
                estado="pendiente",
                tipo_entrega="paqueteria",
                paqueteria="FedEx",
                guia="1234567890",
                observaciones="Urgente",
            ),
            Pedido(
                cliente_id=clientes[0].id,  # Juan Pérez, segundo pedido
                empleado_id=empleados[0].id,
                estado="enviado",
                tipo_entrega="directa",
                observaciones="Entrega programada",
            ),
            Pedido(
                cliente_id=clientes[1].id,  # María García
                empleado_id=empleados[1].id,
                estado="entregado",
                tipo_entrega="paqueteria",
                paqueteria="DHL",
                guia="9988776655",
            ),
            Pedido(
                cliente_id=clientes[2].id,  # Distribuidora del Norte
                empleado_id=empleados[0].id,
                estado="pendiente",
                tipo_entrega="directa",
            ),
        ]
        db.add_all(pedidos)
        db.flush()

        # Items de pedido
        items = [
            PedidoItem(
                pedido_id=pedidos[0].id,
                producto_id=terminados["med_dom_1_clas"].id,
                cantidad=10,
                precio_unitario=450.00,
            ),
            PedidoItem(
                pedido_id=pedidos[0].id,
                producto_id=terminados["med_dom_2_clas"].id,
                cantidad=3,
                precio_unitario=620.00,
            ),
            PedidoItem(
                pedido_id=pedidos[1].id,
                producto_id=terminados["med_ind_3_int"].id,
                cantidad=2,
                precio_unitario=1500.00,
            ),
            PedidoItem(
                pedido_id=pedidos[3].id,
                producto_id=terminados["med_dom_1_clas"].id,
                cantidad=5,
                precio_unitario=430.00,
            ),
        ]
        db.add_all(items)

        _sembrar_productos_demo_aditivos(db, categorias, proveedores)

        db.commit()
        print("[OK] Seed de negocio completado.")
        print(f"   Clientes: {db.query(Cliente).count()}")
        print(f"   Productos: {db.query(Producto).count()}")
        print(f"   Pedidos: {db.query(Pedido).count()}")
        print(f"   Movimientos: {db.query(MovimientoInventario).count()}")
    finally:
        db.close()
        if owns_engine:
            target_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Seed de datos de negocio para Trackr (SQLite local únicamente).")
    parser.parse_args()
    seed()


if __name__ == "__main__":
    main()
