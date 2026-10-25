"""Require new personnel accounts to change their temporary password.

Revision ID: 0005_forced_password_change
Revises: 0004_archive_order_items
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_forced_password_change"
down_revision = "0004_archive_order_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("usuarios"):
        return
    columns = {column["name"] for column in inspector.get_columns("usuarios")}
    if "debe_cambiar_password" not in columns:
        with op.batch_alter_table("usuarios", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "debe_cambiar_password",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado para conservar el requisito de cambio de contraseña."
    )
