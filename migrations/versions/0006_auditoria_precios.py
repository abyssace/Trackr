"""Audit product price updates with actor and SQLite timestamp triggers.

Revision ID: 0006_auditoria_precios
Revises: 0005_forced_password_change
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_auditoria_precios"
down_revision = "0005_forced_password_change"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "contexto_auditoria_precios" not in tables:
        op.create_table(
            "contexto_auditoria_precios",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("usuario_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["usuario_id"], ["usuarios.id"], name="fk_contexto_precio_usuario"
            ),
        )
    if "auditoria_cambios_precios" not in tables:
        op.create_table(
            "auditoria_cambios_precios",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("producto_id", sa.Integer(), nullable=False),
            sa.Column("producto_nombre", sa.String(length=100), nullable=False),
            sa.Column("campo", sa.String(length=30), nullable=False),
            sa.Column("valor_anterior", sa.Numeric(12, 2), nullable=True),
            sa.Column("valor_nuevo", sa.Numeric(12, 2), nullable=True),
            sa.Column("usuario_id", sa.Integer(), nullable=False),
            sa.Column("cambiado_en", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["producto_id"], ["productos.id"], name="fk_auditoria_precios_producto"
            ),
            sa.ForeignKeyConstraint(
                ["usuario_id"], ["usuarios.id"], name="fk_auditoria_precios_usuario"
            ),
        )

    op.execute(
        "INSERT OR IGNORE INTO contexto_auditoria_precios (id, usuario_id) VALUES (1, NULL)"
    )
    op.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_auditoria_cambios_precios
        AFTER UPDATE OF precio_compra, precio_venta ON productos
        FOR EACH ROW
        WHEN OLD.precio_compra IS NOT NEW.precio_compra
          OR OLD.precio_venta IS NOT NEW.precio_venta
        BEGIN
          SELECT CASE
            WHEN (SELECT usuario_id FROM contexto_auditoria_precios WHERE id = 1) IS NULL
            THEN RAISE(ABORT, 'price update requires an authenticated user context')
          END;
          INSERT INTO auditoria_cambios_precios
            (producto_id, producto_nombre, campo, valor_anterior, valor_nuevo, usuario_id, cambiado_en)
          SELECT NEW.id, NEW.nombre, 'precio_compra', OLD.precio_compra, NEW.precio_compra,
                 (SELECT usuario_id FROM contexto_auditoria_precios WHERE id = 1), CURRENT_TIMESTAMP
          WHERE OLD.precio_compra IS NOT NEW.precio_compra;
          INSERT INTO auditoria_cambios_precios
            (producto_id, producto_nombre, campo, valor_anterior, valor_nuevo, usuario_id, cambiado_en)
          SELECT NEW.id, NEW.nombre, 'precio_venta', OLD.precio_venta, NEW.precio_venta,
                 (SELECT usuario_id FROM contexto_auditoria_precios WHERE id = 1), CURRENT_TIMESTAMP
          WHERE OLD.precio_venta IS NOT NEW.precio_venta;
        END"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado para conservar la auditoría de cambios de precios. "
        "Restaura un backup revisado si necesitas volver atrás."
    )
