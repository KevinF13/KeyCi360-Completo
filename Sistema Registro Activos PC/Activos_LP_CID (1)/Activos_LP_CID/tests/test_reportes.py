"""Reportes de solo lectura para exportar a Excel: GET /impresoras/lecturas y GET /equipos/accessories/reporte
(solo contra la copia local; ver conftest)."""
import uuid
from datetime import date

import pytest

from conftest import KEVIN_ID

HOY = date.today()
CLAVES_LECTURA = {"printer_id", "numero_serie", "modelo", "empresa", "ip_address", "hostname", "area", "es_color",
                  "estado", "periodo", "fecha_lectura", "contador_bn", "contador_color", "es_reinicio",
                  "consumo_bn", "consumo_color", "registrado_por"}
CLAVES_ACCESORIO = {"id", "tipo", "marca", "modelo", "numero_serie", "tipo_propiedad", "asignado", "asignado_a",
                    "cedula", "empresa", "fecha_asignacion"}


def _mes(delta: int) -> str:
    n = HOY.year * 12 + HOY.month - 1 + delta
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


@pytest.fixture()
def impresora_con_lecturas(client, db):
    """Impresora a color con 3 lecturas consecutivas (hace 3, 2 y 1 meses); se borra al terminar."""
    sufijo = uuid.uuid4().hex[:10].upper()
    r = client.post("/impresoras", json={
        "numero_serie": f"TRP-{sufijo}", "marca": "TESTPRN", "modelo": f"TP-C{sufijo[:4]}", "tipo_propiedad": "RENTADO",
        "es_color": True, "ip_address": f"10.251.{int(sufijo[:2], 16) % 250}.{int(sufijo[2:4], 16) % 250 + 1}",
        "hostname": "HOST-REP", "area": "Reportes"})
    assert r.status_code == 201, r.text
    p = r.json()
    for delta, bn, color in ((-3, 1000, 100), (-2, 1500, 140), (-1, 2100, 200)):
        periodo = _mes(delta)
        rr = client.post(f"/impresoras/{p['id']}/lecturas", json={
            "periodo": periodo, "fecha_lectura": f"{periodo}-15", "contador_bn": bn, "contador_color": color})
        assert rr.status_code == 201, rr.text
    yield p
    db.execute("DELETE FROM printers WHERE computer_id = %s", (p["computer_id"],))
    db.execute("DELETE FROM delivery_history WHERE computer_id = %s", (p["computer_id"],))
    db.execute("DELETE FROM computers WHERE id = %s", (p["computer_id"],))
    db.execute("DELETE FROM hardware_specs WHERE marca = 'TESTPRN' AND id NOT IN "
               "(SELECT hardware_spec_id FROM computers WHERE hardware_spec_id IS NOT NULL)")


def _filas(client, printer_id, **params):
    r = client.get("/impresoras/lecturas", params=params)
    assert r.status_code == 200, r.text
    return [f for f in r.json() if f["printer_id"] == printer_id]


# ---------- GET /impresoras/lecturas ----------
def test_lecturas_forma_y_orden(client, impresora_con_lecturas):
    p = impresora_con_lecturas
    filas = _filas(client, p["id"])
    assert [f["periodo"] for f in filas] == [_mes(-3), _mes(-2), _mes(-1)]
    f = filas[1]
    assert set(f) == CLAVES_LECTURA
    assert f["numero_serie"] == p["numero_serie"] and f["hostname"] == "HOST-REP" and f["area"] == "Reportes"
    assert f["es_color"] is True and f["estado"] == "DISPONIBLE" and f["es_reinicio"] is False
    assert f["fecha_lectura"] == f"{_mes(-2)}-15" and f["contador_bn"] == 1500 and f["contador_color"] == 140
    assert f["consumo_bn"] == 500 and f["consumo_color"] == 40 and f["registrado_por"]
    assert filas[0]["consumo_bn"] is None  # primera lectura del histórico: sin base
    # el orden global es por impresora y luego por periodo
    todas = client.get("/impresoras/lecturas").json()
    claves = [(x["printer_id"], x["periodo"]) for x in todas]
    assert claves == sorted(claves)


def test_primera_lectura_del_rango_usa_la_anterior(client, impresora_con_lecturas):
    filas = _filas(client, impresora_con_lecturas["id"], desde=_mes(-2), hasta=_mes(-1))
    assert [f["periodo"] for f in filas] == [_mes(-2), _mes(-1)]
    assert filas[0]["consumo_bn"] == 500 and filas[0]["consumo_color"] == 40  # usa la lectura de hace 3 meses
    assert filas[1]["consumo_bn"] == 600 and filas[1]["consumo_color"] == 60
    assert [f["periodo"] for f in _filas(client, impresora_con_lecturas["id"], hasta=_mes(-3))] == [_mes(-3)]


def test_lecturas_excluye_eliminadas(client, db, impresora_con_lecturas):
    p = impresora_con_lecturas
    db.execute("UPDATE computers SET estado_id = (SELECT id FROM statuses WHERE nombre = 'ELIMINADO') WHERE id = %s",
               (p["computer_id"],))
    assert _filas(client, p["id"]) == []


@pytest.mark.parametrize("params", [
    {"desde": "2026-13"}, {"hasta": "2026-00"}, {"desde": "26-01"}, {"desde": "2026-1"}, {"hasta": "abril"},
    {"desde": "2026-05", "hasta": "2026-04"},
])
def test_lecturas_rango_invalido_422(client, params):
    assert client.get("/impresoras/lecturas", params=params).status_code == 422


def test_lecturas_sin_token_401(client_anonimo):
    assert client_anonimo.get("/impresoras/lecturas").status_code == 401


def test_lecturas_user_puede_leer(client_usuario):
    r = client_usuario.get("/impresoras/lecturas")
    assert r.status_code == 200 and isinstance(r.json(), list)


# ---------- GET /equipos/accessories/reporte ----------
@pytest.fixture()
def accesorio_nuevo(client, db, serie_unica):
    tipo = client.get("/equipos/accessory-types").json()[0]
    r = client.post("/equipos/accessories", json={"accessory_type_id": tipo["id"], "marca": "Rep", "modelo": "R1",
                                                  "numero_serie": serie_unica, "tipo_propiedad": "propio"})
    assert r.status_code == 200, r.text
    acc_id = r.json()["accessory_id"]
    yield acc_id, tipo
    client.put(f"/equipos/unassign/accessory/{acc_id}")  # 404 si ya estaba libre: es inofensivo
    client.delete(f"/equipos/accessories/{acc_id}")


def _acc(client, acc_id):
    r = client.get("/equipos/accessories/reporte")
    assert r.status_code == 200, r.text
    return next((a for a in r.json() if a["id"] == acc_id), None)


def test_reporte_accesorios_disponible_y_asignado(client, accesorio_nuevo):
    acc_id, tipo = accesorio_nuevo
    libre = _acc(client, acc_id)
    assert set(libre) == CLAVES_ACCESORIO
    assert libre["tipo"] == tipo["nombre"] and libre["marca"] == "REP" and libre["tipo_propiedad"] == "PROPIO"
    assert libre["asignado"] is False
    assert libre["asignado_a"] is None and libre["cedula"] is None and libre["fecha_asignacion"] is None

    assert client.post("/equipos/assign/accessory", json={"accessory_id": acc_id, "person_id": KEVIN_ID}).status_code == 200
    asignado = _acc(client, acc_id)
    assert asignado["asignado"] is True and asignado["asignado_a"] and asignado["cedula"]
    assert asignado["fecha_asignacion"] == HOY.isoformat()

    assert client.put(f"/equipos/unassign/accessory/{acc_id}").status_code == 200
    assert _acc(client, acc_id)["asignado"] is False


def test_reporte_accesorios_excluye_eliminados(client, accesorio_nuevo):
    acc_id, _ = accesorio_nuevo
    assert _acc(client, acc_id) is not None
    assert client.delete(f"/equipos/accessories/{acc_id}").status_code == 200
    assert _acc(client, acc_id) is None


def test_reporte_accesorios_sin_token_401(client_anonimo):
    assert client_anonimo.get("/equipos/accessories/reporte").status_code == 401


def test_reporte_accesorios_user_puede_leer(client_usuario):
    assert client_usuario.get("/equipos/accessories/reporte").status_code == 200
