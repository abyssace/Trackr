"""Preserve replaced order lines instead of deleting them.

Revision ID: 0004_archive_order_items
Revises: 0003_auth_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_archive_order_items"
down_revision = "0003_auth_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pedido_items"):
        return
    columns = {column["name"] for column in inspector.get_columns("pedido_items")}
    if "activo" not in columns:
        with op.batch_alter_table("pedido_items", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "activo",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado para no eliminar el estado histórico de partidas de pedido."
    )
