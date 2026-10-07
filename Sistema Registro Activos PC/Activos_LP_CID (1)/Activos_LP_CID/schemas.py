"""Modelos de entrada (Pydantic) de /equipos. Los nombres de campo son los que envía el frontend;
los campos desconocidos se ignoran."""
import ipaddress
from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

TIPOS_PROPIEDAD = {"PROPIO", "ARRIENDO", "RENTADO"}  # los tres existen en la BD y en el formulario


class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class CompanyIn(_Entrada):
    nombre: str = Field(min_length=1, max_length=100)


class PersonIn(_Entrada):
    cedula: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=100)
    cargo: str = Field(default="", max_length=100)
    area: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=150)
    company_id: int


class PersonUpdate(PersonIn):
    status_id: Optional[int] = None


class HardwareIn(_Entrada):
    tipo_equipo: str = Field(min_length=1, max_length=50)
    marca: str = Field(min_length=1, max_length=50)
    modelo: str = Field(min_length=1, max_length=50)
    procesador: str = Field(min_length=1, max_length=100)
    ram_gb: int = Field(ge=0, le=100000)
    almacenamiento: str = Field(min_length=1, max_length=50)
    sistema_operativo: str = Field(min_length=1, max_length=50)
    pantalla: Optional[str] = Field(default=None, max_length=50)
    otros: Optional[str] = None
    status_id: Optional[int] = None
    # Confirma que pantalla/otros/status_id se apliquen a todos los equipos que comparten la especificación
    aplicar_a_todos: bool = False


class HardwareUpdate(HardwareIn):
    # Identifica el equipo que se edita (copy-on-write de la especificación compartida)
    numero_serie: Optional[str] = None


class ComputerIn(_Entrada):
    hardware_spec_id: int
    numero_serie: str = Field(min_length=1, max_length=50)
    tipo_propiedad: str
    tarifa_mensual: Decimal = Field(default=Decimal("0"), ge=0)
    fecha_recepcion_proveedor: date = Field(default_factory=date.today)
    anio_fabricacion: int = Field(ge=1900, le=2100)
    observaciones: Optional[str] = None

    @field_validator("tipo_propiedad")
    @classmethod
    def _tipo_propiedad(cls, v: str) -> str:
        v = v.upper()
        if v not in TIPOS_PROPIEDAD:
            raise ValueError("El tipo de propiedad debe ser PROPIO, ARRIENDO o RENTADO.")
        return v


class AccessoryTypeIn(_Entrada):
    nombre: str = Field(max_length=50)


class AccessoryIn(_Entrada):
    accessory_type_id: int
    marca: str = Field(max_length=50)
    modelo: str = Field(max_length=50)
    numero_serie: str = Field(max_length=50)
    tipo_propiedad: str = Field(max_length=50)


class AssignComputerIn(_Entrada):
    computer_id: int
    person_id: int


class AssignAccessoryIn(_Entrada):
    accessory_id: int
    person_id: int


class StatusChangeIn(_Entrada):
    nuevo_estado: str = Field(min_length=1, max_length=50)


# ---------- /impresoras ----------
def _normalizar_ip(v):
    """Valida IPv4/IPv6 y devuelve la forma canónica (cadena vacía = sin IP)."""
    if v is None or v == "":
        return None
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        raise ValueError("La dirección IP no es una IPv4/IPv6 válida.")


def _vacio_a_none(v):
    return None if isinstance(v, str) and v == "" else v


def _validar_tipo_propiedad(v):
    if v is None:
        return v
    v = v.upper()
    if v not in TIPOS_PROPIEDAD:
        raise ValueError("El tipo de propiedad debe ser PROPIO, ARRIENDO o RENTADO.")
    return v


class _CamposImpresora(_Entrada):
    company_id: Optional[int] = None
    ip_address: Optional[str] = Field(default=None, max_length=45)
    hostname: Optional[str] = Field(default=None, max_length=100)
    area: Optional[str] = Field(default=None, max_length=100)
    ubicacion: Optional[str] = Field(default=None, max_length=150)
    proveedor: Optional[str] = Field(default=None, max_length=100)
    observaciones: Optional[str] = None

    @field_validator("ip_address")
    @classmethod
    def _ip(cls, v):
        return _normalizar_ip(v)

    @field_validator("hostname", "area", "ubicacion", "proveedor", "observaciones")
    @classmethod
    def _opcionales(cls, v):
        return _vacio_a_none(v)


class PrinterIn(_CamposImpresora):
    numero_serie: str = Field(min_length=1, max_length=50)
    marca: str = Field(min_length=1, max_length=50)
    modelo: str = Field(min_length=1, max_length=50)
    tipo_propiedad: str
    tarifa_mensual: Decimal = Field(default=Decimal("0"), ge=0)
    fecha_recepcion_proveedor: Optional[date] = None
    anio_fabricacion: Optional[int] = Field(default=None, ge=1900, le=2100)
    es_color: bool = False

    @field_validator("tipo_propiedad")
    @classmethod
    def _tipo(cls, v):
        return _validar_tipo_propiedad(v)


class PrinterUpdate(_CamposImpresora):
    """Actualización parcial: solo se cambian los campos enviados."""
    marca: Optional[str] = Field(default=None, min_length=1, max_length=50)
    modelo: Optional[str] = Field(default=None, min_length=1, max_length=50)
    tipo_propiedad: Optional[str] = None
    tarifa_mensual: Optional[Decimal] = Field(default=None, ge=0)
    es_color: Optional[bool] = None

    @field_validator("tipo_propiedad")
    @classmethod
    def _tipo(cls, v):
        return _validar_tipo_propiedad(v)


class _CamposLectura(_Entrada):
    periodo: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    fecha_lectura: date
    contador_bn: int = Field(ge=0, le=9_000_000_000_000_000_000)
    contador_color: int = Field(default=0, ge=0, le=9_000_000_000_000_000_000)
    es_reinicio: bool = False
    observaciones: Optional[str] = None

    @field_validator("observaciones")
    @classmethod
    def _obs(cls, v):
        return _vacio_a_none(v)


class ReadingIn(_CamposLectura):
    pass


class ReadingBatchItem(_CamposLectura):
    printer_id: int


class ReadingBatchIn(_Entrada):
    lecturas: List[ReadingBatchItem] = Field(max_length=5000)
    modo: Literal["validar", "aplicar"]
