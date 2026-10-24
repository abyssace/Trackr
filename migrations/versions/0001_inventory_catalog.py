"""Add categories, suppliers and product catalog fields.

Revision ID: 0001_inventory_catalog
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_inventory_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("productos"):
        # A fresh database has no pre-Alembic schema. Bootstrap it once from
        # the current model metadata; existing databases take the additive path below.
        from app.db.base import Base
        from app.db import modelos as trackr_models  # noqa: F401
        from app.db import negocio as business_models  # noqa: F401

        Base.metadata.create_all(bind=bind)
        return

    existing_tables = set(inspector.get_table_names())
    if "categorias" not in existing_tables:
        op.create_table(
            "categorias",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nombre", sa.String(length=100), nullable=False),
            sa.Column("descripcion", sa.Text(), nullable=True),
            sa.Column("activo", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("nombre", name="uq_categorias_nombre"),
        )
    if "proveedores" not in existing_tables:
        op.create_table(
            "proveedores",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nombre", sa.String(length=150), nullable=False),
            sa.Column("contacto", sa.String(length=100), nullable=True),
            sa.Column("telefono", sa.String(length=20), nullable=True),
            sa.Column("correo", sa.String(length=120), nullable=True),
            sa.Column("activo", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("nombre", name="uq_proveedores_nombre"),
        )

    current_columns = {column["name"] for column in sa.inspect(bind).get_columns("productos")}
    new_columns = {
        "codigo": sa.Column("codigo", sa.String(length=80), nullable=True),
        "categoria_id": sa.Column("categoria_id", sa.Integer(), nullable=True),
        "proveedor_id": sa.Column("proveedor_id", sa.Integer(), nullable=True),
        "precio_compra": sa.Column("precio_compra", sa.Numeric(12, 2), nullable=True),
        "precio_venta": sa.Column("precio_venta", sa.Numeric(12, 2), nullable=True),
    }
    missing_columns = set(new_columns) - current_columns
    if not missing_columns:
        return

    with op.batch_alter_table("productos", recreate="always") as batch_op:
        for name in ("codigo", "categoria_id", "proveedor_id", "precio_compra", "precio_venta"):
            if name not in current_columns:
                batch_op.add_column(new_columns[name])
        if "codigo" not in current_columns:
            batch_op.create_unique_constraint("uq_productos_codigo", ["codigo"])
        if "categoria_id" not in current_columns:
            batch_op.create_foreign_key(
                "fk_productos_categoria_id_categorias", "categorias", ["categoria_id"], ["id"]
            )
        if "proveedor_id" not in current_columns:
            batch_op.create_foreign_key(
                "fk_productos_proveedor_id_proveedores", "proveedores", ["proveedor_id"], ["id"]
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado para no eliminar códigos, precios ni relaciones de catálogo. "
        "Restaura un backup revisado si necesitas volver atrás."
    )
