"""Additive role and login-audit schema for databases predating these models.

Revision ID: 0003_auth_schema
Revises: 0002_inventory_actor
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_auth_schema"
down_revision = "0002_inventory_actor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("usuarios"):
        columns = {column["name"] for column in inspector.get_columns("usuarios")}
        missing = {"rol", "intentos_fallidos", "bloqueado_hasta"} - columns
        if missing:
            with op.batch_alter_table("usuarios", recreate="always") as batch_op:
                if "rol" in missing:
                    batch_op.add_column(
                        sa.Column(
                            "rol",
                            sa.String(length=30),
                            nullable=False,
                            server_default=sa.text("'solo_lectura'"),
                        )
                    )
                if "intentos_fallidos" in missing:
                    batch_op.add_column(
                        sa.Column(
                            "intentos_fallidos",
                            sa.Integer(),
                            nullable=False,
                            server_default=sa.text("0"),
                        )
                    )
                if "bloqueado_hasta" in missing:
                    batch_op.add_column(sa.Column("bloqueado_hasta", sa.DateTime(), nullable=True))

            if "rol" in missing and "es_admin" in columns:
                op.execute(
                    sa.text(
                        "UPDATE usuarios SET rol = 'administrador' "
                        "WHERE es_admin = 1 AND rol = 'solo_lectura'"
                    )
                )

    if not sa.inspect(bind).has_table("auditoria"):
        op.create_table(
            "auditoria",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=100), nullable=True),
            sa.Column("ip", sa.String(length=100), nullable=True),
            sa.Column("exito", sa.Boolean(), nullable=False),
            sa.Column("razon", sa.String(length=200), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado para conservar roles, bloqueos y auditoría de login. "
        "Restaura un backup revisado si necesitas volver atrás."
    )
