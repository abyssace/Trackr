"""Record responsible users and idempotency keys on inventory movements.

Revision ID: 0002_inventory_actor
Revises: 0001_inventory_catalog
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_inventory_actor"
down_revision = "0001_inventory_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("movimientos_inventario"):
        # A partial legacy database without the ledger has nothing to extend here.
        return

    columns = {column["name"] for column in inspector.get_columns("movimientos_inventario")}
    missing = {"usuario_id", "idempotency_key"} - columns
    if not missing:
        return

    with op.batch_alter_table("movimientos_inventario", recreate="always") as batch_op:
        if "usuario_id" in missing:
            batch_op.add_column(sa.Column("usuario_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_movimientos_usuario_id_usuarios", "usuarios", ["usuario_id"], ["id"]
            )
        if "idempotency_key" in missing:
            batch_op.add_column(sa.Column("idempotency_key", sa.String(length=120), nullable=True))
            batch_op.create_unique_constraint(
                "uq_movimientos_idempotency_key", ["idempotency_key"]
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado para conservar responsables e identificadores de movimientos. "
        "Restaura un backup revisado si necesitas volver atrás."
    )
