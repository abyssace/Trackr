from enum import Enum as PyEnum


class Rol(str, PyEnum):
    SOLO_LECTURA = "solo_lectura"
    VENDEDOR = "vendedor"
    ALMACEN = "almacen"
    ENSAMBLADOR = "ensamblador"
    ADMINISTRADOR = "administrador"
