from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150))
    razon_social: Mapped[Optional[str]] = mapped_column(String(150))
    rfc: Mapped[Optional[str]] = mapped_column(String(13))
    direccion: Mapped[Optional[str]] = mapped_column(String(255))
    telefono: Mapped[Optional[str]] = mapped_column(String(15))
    correo: Mapped[Optional[str]] = mapped_column(String(100))
    contacto: Mapped[Optional[str]] = mapped_column(String(100))
    fecha_registro: Mapped[Optional[datetime]] = mapped_column(default=utc_now)


class Empleado(Base):
    __tablename__ = "empleados"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150))
    rol: Mapped[Optional[str]] = mapped_column(String(50))
    telefono: Mapped[Optional[str]] = mapped_column(String(15))
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"))
    activo: Mapped[bool] = mapped_column(default=True)


class TipoMedidor(Base):
    __tablename__ = "tipos_medidor"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)


class Medidor(Base):
    __tablename__ = "medidores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_modelo: Mapped[str] = mapped_column(String(50))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    tipo_medidor_id: Mapped[int] = mapped_column(ForeignKey("tipos_medidor.id"))

    tipo_medidor: Mapped["TipoMedidor"] = relationship()


class Tamano(Base):
    __tablename__ = "tamanos"

    id: Mapped[int] = mapped_column(primary_key=True)
    pulgadas: Mapped[int]


class TipoUTD(Base):
    __tablename__ = "tipos_utd"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    tecnologia: Mapped[Optional[str]] = mapped_column(String(60))


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), index=True)
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20))  # componente | terminado
    unidad_medida: Mapped[Optional[str]] = mapped_column(String(20))
    stock_minimo: Mapped[Optional[int]]
    medidor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("medidores.id"))
    tamano_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tamanos.id"))
    tipo_utd_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tipos_utd.id"))
    alias: Mapped[Optional[str]] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(default=True)

    medidor: Mapped[Optional["Medidor"]] = relationship()
    tamano: Mapped[Optional["Tamano"]] = relationship()
    tipo_utd: Mapped[Optional["TipoUTD"]] = relationship()


class Receta(Base):
    __tablename__ = "recetas"

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_terminado_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    producto_componente_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad_requerida: Mapped[int]


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    empleado_id: Mapped[Optional[int]] = mapped_column(ForeignKey("empleados.id"))
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    tipo_entrega: Mapped[Optional[str]] = mapped_column(String(20))
    paqueteria: Mapped[Optional[str]] = mapped_column(String(50))
    guia: Mapped[Optional[str]] = mapped_column(String(50))
    fecha_pedido: Mapped[datetime] = mapped_column(default=utc_now)
    fecha_entrega_estimada: Mapped[Optional[datetime]]
    observaciones: Mapped[Optional[str]] = mapped_column(Text)

    cliente: Mapped["Cliente"] = relationship()
    items: Mapped[list["PedidoItem"]] = relationship(back_populates="pedido")


class PedidoItem(Base):
    __tablename__ = "pedido_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[int]
    precio_unitario: Mapped[Optional[float]]
    inventario_descontado: Mapped[bool] = mapped_column(default=False)
    observaciones: Mapped[Optional[str]] = mapped_column(Text)

    pedido: Mapped["Pedido"] = relationship(back_populates="items")
    producto: Mapped["Producto"] = relationship()


class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[int]
    tipo_movimiento: Mapped[str] = mapped_column(String(20))
    pedido_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pedidos.id"))
    empleado_id: Mapped[Optional[int]] = mapped_column(ForeignKey("empleados.id"))
    empleado_entrega_id: Mapped[Optional[int]] = mapped_column(ForeignKey("empleados.id"))
    referencia: Mapped[Optional[str]] = mapped_column(String(100))
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(default=utc_now)
