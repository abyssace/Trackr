import argparse
import getpass
import logging

from sqlalchemy import select
from passlib.context import CryptContext

from app.db.base import engine, SessionLocal, Base
from app.db.modelos import Usuario

logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def crear(nombre: str, username: str, password: str):
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        if db.scalar(select(Usuario).where(Usuario.username == username)):
            print("Ese username ya existe.")
            return

        user = Usuario(
            nombre=nombre,
            username=username,
            password_hash=pwd_context.hash(password),
        )
        db.add(user)
        db.commit()
        print(f"Usuario '{username}' creado con id {user.id}.")


def main():
    parser = argparse.ArgumentParser(description="Crea el primer usuario de Trackr.")
    parser.add_argument("--nombre", help="Nombre completo")
    parser.add_argument("--username", help="Nombre de usuario")
    parser.add_argument("--password", help="Contraseña (mejor no usar en producción)")
    args = parser.parse_args()

    nombre = args.nombre or input("Nombre: ").strip()
    username = args.username or input("Username: ").strip()
    if args.password:
        password = args.password
        confirm = args.password
    else:
        password = getpass.getpass("Contraseña: ")
        confirm = getpass.getpass("Repite contraseña: ")

    if password != confirm:
        print("Las contraseñas no coinciden.")
        return

    crear(nombre, username, password)


if __name__ == "__main__":
    main()
