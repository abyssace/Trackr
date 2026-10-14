import argparse
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.base import Base
from app.db.modelos import Usuario
from app.servicios.auth import get_password_hash
from app.servicios.roles import Rol


def _roles_texto() -> str:
    return ", ".join(r.value for r in Rol)


def main():
    parser = argparse.ArgumentParser(
        description="Crea un usuario de Trackr con un rol específico."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--nombre", required=True)
    parser.add_argument(
        "--rol",
        required=True,
        choices=[r.value for r in Rol],
        metavar="ROL",
        help=f"Rol del usuario. Valores válidos: {_roles_texto()}",
    )
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    if db.query(Usuario).filter(Usuario.username == args.username).first():
        print("Usuario ya existe")
        sys.exit(1)

    usuario = Usuario(
        nombre=args.nombre,
        username=args.username,
        password_hash=get_password_hash(args.password),
        activo=True,
        rol=args.rol,
        es_admin=args.rol == Rol.ADMINISTRADOR.value,
    )
    db.add(usuario)
    db.commit()
    print(f"Usuario {args.username} creado con rol {args.rol}")


if __name__ == "__main__":
    main()
