"""Módulo de impresoras: migración 005, CRUD, autorización, reglas de lecturas, lote atómico y resumen
(solo contra la copia local; ver conftest)."""
import os
import subprocess
import sys
import threading
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app

RAIZ = Path(__file__).resolve().parent.parent
HOY = date.today()


def _mes_relativo(delta: int) -> date:
    n = HOY.year * 12 + HOY.month - 1 + delta
    return date(n // 12, n % 12 + 1, 1)


def _lectura(periodo: str, bn: int, color: int = 0, **extra):
    return {"periodo": periodo, "fecha_lectura": f"{periodo}-15", "contador_bn": bn, "contador_color": color, **extra}


@pytest.fixture()
def crear_impresora(client, db):
    """Crea impresoras por la API y las borra (lecturas en cascada, computers) al terminar."""
    creadas = []

    def _crear(es_color=False, **extra):
        sufijo = uuid.uuid4().hex[:10].upper()
        cuerpo = {"numero_serie": f"TPR-{sufijo}", "marca": "TESTPRN", "modelo": f"TP-{'C' if es_color else 'M'}{sufijo[:4]}",
                  "tipo_propiedad": "RENTADO", "tarifa_mensual": 12.5, "es_color": es_color, **extra}
        r = client.post("/impresoras", json=cuerpo)
        assert r.status_code == 201, r.text
        creadas.append(r.json()["computer_id"])
        return r.json()

    yield _crear
    if creadas:
        db.execute("DELETE FROM printers WHERE computer_id = ANY(%s)", (creadas,))
        db.execute("DELETE FROM delivery_history WHERE computer_id = ANY(%s)", (creadas,))
        db.execute("DELETE FROM computers WHERE id = ANY(%s)", (creadas,))
        db.execute("DELETE FROM hardware_specs WHERE marca = 'TESTPRN' AND id NOT IN "
                   "(SELECT hardware_spec_id FROM computers WHERE hardware_spec_id IS NOT NULL)")


def _post_lectura(client, impresora, periodo, bn, color=0, **extra):
    return client.post(f"/impresoras/{impresora['id']}/lecturas", json=_lectura(periodo, bn, color, **extra))


# ---------- migración ----------
def test_migracion_idempotente(db):
    def ejecutar(*args):
        r = subprocess.run([sys.executable, str(RAIZ / "sql" / "005_impresoras.py"), *args],
                           capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    simulacro = ejecutar()
    assert "Simulacro" in simulacro
    primera = ejecutar("--aplicar", "--si")
    segunda = ejecutar("--aplicar", "--si")
    assert "0 impresoras insertadas" in segunda
    assert "impresoras insertadas" in primera

    db.execute("SELECT COUNT(*) FROM printers")
    en_printers = db.fetchone()[0]
    db.execute("""SELECT COUNT(*) FROM computers c JOIN hardware_specs hs ON hs.id = c.hardware_spec_id
                  WHERE hs.tipo_equipo ILIKE 'impres%'""")
    assert en_printers == db.fetchone()[0]
    ejecutar("--aplicar", "--si")  # una tercera vez tampoco cambia nada
    db.execute("SELECT COUNT(*) FROM printers")
    assert db.fetchone()[0] == en_printers


# ---------- CRUD ----------
def test_crud_impresora(client, crear_impresora):
    p = crear_impresora(es_color=True, ip_address="10.250.1.7", hostname="HOST-PRN", area="Contabilidad",
                        ubicacion="Piso 2", proveedor="Canon EC", observaciones="nueva")
    assert p["estado"] == "DISPONIBLE" and p["es_color"] is True and p["ip_address"] == "10.250.1.7"
    assert p["empresa"] is None and p["ultima_lectura"] is None and p["consumo_ultimo"] is None
    assert p["lectura_mes_actual"] is False and p["tarifa_mensual"] == 12.5

    r = client.get(f"/impresoras/{p['id']}")
    assert r.status_code == 200 and r.json()["numero_serie"] == p["numero_serie"]
    assert any(i["id"] == p["id"] for i in client.get("/impresoras").json())

    # se creó el activo como equipo de tipo Impresora
    inv = client.get("/equipos/vista/inventario-general").json()
    assert next(e for e in inv if e["numero_serie"] == p["numero_serie"])["tipo_equipo"] == "Impresora"

    # actualización parcial: lo no enviado se conserva
    r = client.put(f"/impresoras/{p['id']}", json={"area": "Gerencia", "hostname": "NUEVO", "tarifa_mensual": 20,
                                                   "modelo": "TP-RENOMBRADO"})
    assert r.status_code == 200, r.text
    nuevo = r.json()
    assert (nuevo["area"], nuevo["hostname"], nuevo["tarifa_mensual"], nuevo["modelo"]) == ("Gerencia", "NUEVO", 20.0, "TP-RENOMBRADO")
    assert nuevo["ip_address"] == "10.250.1.7" and nuevo["ubicacion"] == "Piso 2" and nuevo["es_color"] is True

    assert client.get("/impresoras/99999999").status_code == 404
    assert client.put("/impresoras/99999999", json={"area": "x"}).status_code == 404


def test_crear_validaciones(client, crear_impresora):
    p = crear_impresora(ip_address="10.250.1.8")
    base = {"numero_serie": f"TPR-{uuid.uuid4().hex[:10]}", "marca": "TESTPRN", "modelo": "X", "tipo_propiedad": "PROPIO"}
    assert client.post("/impresoras", json={**base, "numero_serie": p["numero_serie"]}).status_code == 400
    assert client.post("/impresoras", json={**base, "ip_address": "10.250.1.8"}).status_code == 409
    assert client.post("/impresoras", json={**base, "ip_address": "no-es-ip"}).status_code == 422
    assert client.post("/impresoras", json={**base, "tipo_propiedad": "REGALADO"}).status_code == 422
    assert client.post("/impresoras", json={**base, "company_id": 99999999}).status_code == 400


def test_copy_on_write_de_especificacion_compartida(client, crear_impresora, db):
    a = crear_impresora()
    # la segunda usa exactamente la misma marca/modelo => comparte la especificación
    b = crear_impresora(modelo=a["modelo"])
    db.execute("SELECT hardware_spec_id FROM computers WHERE id IN (%s, %s)", (a["computer_id"], b["computer_id"]))
    assert len({f[0] for f in db.fetchall()}) == 1
    r = client.put(f"/impresoras/{a['id']}", json={"modelo": "TP-COW"})
    assert r.status_code == 200 and r.json()["modelo"] == "TP-COW"
    assert client.get(f"/impresoras/{b['id']}").json()["modelo"] == a["modelo"]  # la otra no cambia


def test_impresora_ya_no_monocromatica_con_color_cargado(client, crear_impresora):
    p = crear_impresora(es_color=True)
    assert _post_lectura(client, p, "2024-01", 100, 50).status_code == 201
    assert client.put(f"/impresoras/{p['id']}", json={"es_color": False}).status_code == 409


# ---------- autorización ----------
def test_usuario_lee_y_no_escribe(client_usuario, client_anonimo, crear_impresora):
    p = crear_impresora()
    assert client_usuario.get("/impresoras").status_code == 200
    assert client_usuario.get(f"/impresoras/{p['id']}").status_code == 200
    assert client_usuario.get(f"/impresoras/{p['id']}/lecturas").status_code == 200
    assert client_usuario.get("/impresoras/resumen").status_code == 200

    escrituras = [
        ("post", "/impresoras", {"numero_serie": "X", "marca": "X", "modelo": "X", "tipo_propiedad": "PROPIO"}),
        ("put", f"/impresoras/{p['id']}", {"area": "x"}),
        ("post", f"/impresoras/{p['id']}/lecturas", _lectura("2024-01", 1)),
        ("put", "/impresoras/lecturas/1", _lectura("2024-01", 1)),
        ("delete", "/impresoras/lecturas/1", None),
        ("post", "/impresoras/lecturas/lote", {"lecturas": [], "modo": "validar"}),
    ]
    for metodo, ruta, cuerpo in escrituras:
        r = getattr(client_usuario, metodo)(ruta, **({"json": cuerpo} if cuerpo is not None else {}))
        assert r.status_code == 403, (metodo, ruta, r.text)
        assert r.json()["detail"] == "Se requiere rol ADMIN"


def test_sin_token_401(client_anonimo):
    for ruta in ("/impresoras", "/impresoras/1", "/impresoras/1/lecturas", "/impresoras/resumen"):
        r = client_anonimo.get(ruta)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client_anonimo.post("/impresoras/1/lecturas", json=_lectura("2024-01", 1)).status_code == 401
    assert client_anonimo.post("/impresoras/lecturas/lote", json={"lecturas": [], "modo": "validar"}).status_code == 401


# ---------- lecturas: consumo y reglas ----------
def test_consumo_y_reinicio(client, crear_impresora):
    p = crear_impresora(es_color=True)
    r1 = _post_lectura(client, p, "2024-01", 1000, 500)
    assert r1.status_code == 201
    primera = r1.json()
    assert primera["periodo"] == "2024-01" and primera["consumo_bn"] is None and primera["consumo_color"] is None  # sin base

    seg = _post_lectura(client, p, "2024-02", 1300, 560).json()
    assert (seg["consumo_bn"], seg["consumo_color"]) == (300, 60)

    # reinicio: el consumo es el contador mismo (aunque sea menor que el anterior)
    rei = _post_lectura(client, p, "2024-03", 80, 7, es_reinicio=True)
    assert rei.status_code == 201
    assert (rei.json()["consumo_bn"], rei.json()["consumo_color"], rei.json()["es_reinicio"]) == (80, 7, True)
    # tras el reinicio se vuelve a restar
    cuarta = _post_lectura(client, p, "2024-04", 130, 10).json()
    assert (cuarta["consumo_bn"], cuarta["consumo_color"]) == (50, 3)

    lecturas = client.get(f"/impresoras/{p['id']}/lecturas").json()
    assert [x["periodo"] for x in lecturas] == ["2024-04", "2024-03", "2024-02", "2024-01"]  # DESC

    ficha = client.get(f"/impresoras/{p['id']}").json()
    assert ficha["ultima_lectura"]["periodo"] == "2024-04" and ficha["ultima_lectura"]["contador_bn"] == 130
    assert ficha["consumo_ultimo"] == {"periodo": "2024-04", "bn": 50, "color": 3}


def test_contador_menor_que_el_anterior_400(client, crear_impresora):
    p = crear_impresora(es_color=True)
    assert _post_lectura(client, p, "2024-01", 1000, 500).status_code == 201
    r = _post_lectura(client, p, "2024-02", 900, 500)
    assert r.status_code == 400
    assert r.json()["detail"] == ("El contador B/N (900) es menor que la lectura anterior (1000) del enero de 2024. "
                                  "Si cambió el equipo o se reinició el contador, marca 'Reinicio de contador'.")
    r = _post_lectura(client, p, "2024-02", 1000, 400)
    assert r.status_code == 400 and "color" in r.json()["detail"] and "(400)" in r.json()["detail"]
    assert _post_lectura(client, p, "2024-02", 1000, 500).status_code == 201  # igual es válido (consumo 0)


def test_color_en_monocromatica_400(client, crear_impresora):
    p = crear_impresora(es_color=False)
    assert _post_lectura(client, p, "2024-01", 100, 5).status_code == 400
    assert _post_lectura(client, p, "2024-01", 100, 0).status_code == 201


def test_periodo_duplicado_409(client, crear_impresora):
    p = crear_impresora()
    assert _post_lectura(client, p, "2024-01", 100).status_code == 201
    assert _post_lectura(client, p, "2024-01", 200).status_code == 409


def test_insercion_en_medio_del_historico(client, crear_impresora):
    p = crear_impresora(es_color=True)
    assert _post_lectura(client, p, "2024-01", 1000, 100).status_code == 201
    assert _post_lectura(client, p, "2024-03", 1600, 300).status_code == 201

    # mayor que la siguiente => 400
    r = _post_lectura(client, p, "2024-02", 1700, 100)
    assert r.status_code == 400 and "mayor que la lectura siguiente (1600)" in r.json()["detail"]
    r = _post_lectura(client, p, "2024-02", 1200, 400)
    assert r.status_code == 400 and "mayor que la lectura siguiente (300)" in r.json()["detail"]
    # menor que la anterior => 400
    assert _post_lectura(client, p, "2024-02", 900, 100).status_code == 400

    medio = _post_lectura(client, p, "2024-02", 1200, 150)
    assert medio.status_code == 201 and (medio.json()["consumo_bn"], medio.json()["consumo_color"]) == (200, 50)
    # el consumo de la siguiente se recalcula contra la nueva
    por_periodo = {x["periodo"]: x for x in client.get(f"/impresoras/{p['id']}/lecturas").json()}
    assert (por_periodo["2024-03"]["consumo_bn"], por_periodo["2024-03"]["consumo_color"]) == (400, 150)


def test_actualizar_y_eliminar_lectura(client, crear_impresora):
    p = crear_impresora()
    ids = {}
    for per, bn in (("2024-01", 100), ("2024-02", 200), ("2024-03", 300)):
        ids[per] = _post_lectura(client, p, per, bn).json()["id"]

    # revalida contra anterior y siguiente
    assert client.put(f"/impresoras/lecturas/{ids['2024-02']}", json=_lectura("2024-02", 50)).status_code == 400
    assert client.put(f"/impresoras/lecturas/{ids['2024-02']}", json=_lectura("2024-02", 350)).status_code == 400
    r = client.put(f"/impresoras/lecturas/{ids['2024-02']}", json=_lectura("2024-02", 250, observaciones="corregida"))
    assert r.status_code == 200 and r.json()["contador_bn"] == 250 and r.json()["consumo_bn"] == 150
    assert r.json()["observaciones"] == "corregida"
    # no se puede mover a un periodo ocupado
    assert client.put(f"/impresoras/lecturas/{ids['2024-02']}", json=_lectura("2024-03", 250)).status_code == 409
    assert client.put("/impresoras/lecturas/99999999", json=_lectura("2024-02", 1)).status_code == 404

    assert client.delete(f"/impresoras/lecturas/{ids['2024-02']}").status_code == 204
    assert client.delete(f"/impresoras/lecturas/{ids['2024-02']}").status_code == 404
    assert [x["periodo"] for x in client.get(f"/impresoras/{p['id']}/lecturas").json()] == ["2024-03", "2024-01"]


def test_eliminar_reinicio_que_dejaria_inconsistente_409(client, crear_impresora):
    p = crear_impresora()
    _post_lectura(client, p, "2024-01", 1000)
    rei = _post_lectura(client, p, "2024-02", 10, es_reinicio=True).json()
    _post_lectura(client, p, "2024-03", 50)
    assert client.delete(f"/impresoras/lecturas/{rei['id']}").status_code == 409
    assert len(client.get(f"/impresoras/{p['id']}/lecturas").json()) == 3


def test_periodo_futuro_400(client, crear_impresora):
    p = crear_impresora()
    futuro = _mes_relativo(1).strftime("%Y-%m")
    r = client.post(f"/impresoras/{p['id']}/lecturas", json={**_lectura(futuro, 10), "fecha_lectura": HOY.isoformat()})
    assert r.status_code == 400 and "futuro" in r.json()["detail"]
    # fecha de lectura futura en un periodo válido
    actual = _mes_relativo(0).strftime("%Y-%m")
    r = client.post(f"/impresoras/{p['id']}/lecturas",
                    json={**_lectura(actual, 10), "fecha_lectura": (HOY + timedelta(days=1)).isoformat()})
    assert r.status_code == 400 and "futura" in r.json()["detail"]
    # el mes actual sí es válido
    r = client.post(f"/impresoras/{p['id']}/lecturas", json={**_lectura(actual, 10), "fecha_lectura": HOY.isoformat()})
    assert r.status_code == 201
    assert client.get(f"/impresoras/{p['id']}").json()["lectura_mes_actual"] is True


def test_formato_de_periodo_invalido_422(client, crear_impresora):
    p = crear_impresora()
    for periodo in ("2024-13", "2024-1", "24-01", "2024-01-01"):
        assert client.post(f"/impresoras/{p['id']}/lecturas", json={**_lectura("2024-01", 1), "periodo": periodo}).status_code == 422
    assert client.post(f"/impresoras/{p['id']}/lecturas", json=_lectura("2024-01", -1)).status_code == 422
    assert client.post("/impresoras/99999999/lecturas", json=_lectura("2024-01", 1)).status_code == 404


def test_registrado_por_es_el_usuario_autenticado(client, crear_impresora, usuarios_sesion):
    p = crear_impresora()
    r = _post_lectura(client, p, "2024-01", 10, registrado_por="intruso")
    assert r.status_code == 201
    assert r.json()["registrado_por"] == usuarios_sesion["ADMIN"][1] != "intruso"
    lote = client.post("/impresoras/lecturas/lote", json={"modo": "aplicar", "lecturas": [
        {"printer_id": p["id"], "registrado_por": "intruso", **_lectura("2024-02", 20)}]})
    assert lote.status_code == 200 and lote.json()["ok"] is True
    assert {x["registrado_por"] for x in client.get(f"/impresoras/{p['id']}/lecturas").json()} == {usuarios_sesion["ADMIN"][1]}


# ---------- lote ----------
def _contar_lecturas(client, p):
    return len(client.get(f"/impresoras/{p['id']}/lecturas").json())


def test_lote_aplicar_ok(client, crear_impresora):
    a, b = crear_impresora(), crear_impresora(es_color=True)
    r = client.post("/impresoras/lecturas/lote", json={"modo": "aplicar", "lecturas": [
        {"printer_id": a["id"], **_lectura("2024-01", 100)},
        {"printer_id": a["id"], **_lectura("2024-02", 150)},   # valida contra la fila anterior del mismo lote
        {"printer_id": b["id"], **_lectura("2024-01", 10, 5)},
    ]})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "creadas": 3, "validas": 3, "errores": []}
    assert _contar_lecturas(client, a) == 2 and _contar_lecturas(client, b) == 1
    assert client.get(f"/impresoras/{a['id']}/lecturas").json()[0]["consumo_bn"] == 50


def test_lote_atomico_con_un_error_no_inserta_nada(client, crear_impresora):
    a, b = crear_impresora(), crear_impresora(es_color=False)
    r = client.post("/impresoras/lecturas/lote", json={"modo": "aplicar", "lecturas": [
        {"printer_id": a["id"], **_lectura("2024-01", 100)},
        {"printer_id": b["id"], **_lectura("2024-01", 100, 9)},    # color en monocromática
        {"printer_id": a["id"], **_lectura("2024-01", 120)},       # periodo duplicado dentro del lote
        {"printer_id": 99999999, **_lectura("2024-01", 1)},        # impresora inexistente
        {"printer_id": a["id"], **_lectura("2024-02", 150)},
    ]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["ok"] is False and cuerpo["creadas"] == 0 and cuerpo["validas"] == 2
    assert [(e["indice"], e["printer_id"], e["periodo"]) for e in cuerpo["errores"]] == [
        (1, b["id"], "2024-01"), (2, a["id"], "2024-01"), (3, 99999999, "2024-01")]
    assert all(e["mensaje"] for e in cuerpo["errores"])
    assert _contar_lecturas(client, a) == 0 and _contar_lecturas(client, b) == 0


def test_lote_validar_nunca_escribe(client, crear_impresora):
    a = crear_impresora()
    lecturas = [{"printer_id": a["id"], **_lectura("2024-01", 100)}, {"printer_id": a["id"], **_lectura("2024-02", 150)}]
    r = client.post("/impresoras/lecturas/lote", json={"modo": "validar", "lecturas": lecturas})
    assert r.json() == {"ok": True, "creadas": 0, "validas": 2, "errores": []}  # validar nunca crea
    assert _contar_lecturas(client, a) == 0
    # con errores también informa y tampoco escribe
    lecturas[1]["contador_bn"] = 50
    r = client.post("/impresoras/lecturas/lote", json={"modo": "validar", "lecturas": lecturas})
    assert r.json()["ok"] is False and r.json()["creadas"] == 0 and r.json()["errores"][0]["indice"] == 1
    assert _contar_lecturas(client, a) == 0
    # y las lecturas ya guardadas se tienen en cuenta
    assert _post_lectura(client, a, "2024-01", 100).status_code == 201
    r = client.post("/impresoras/lecturas/lote", json={"modo": "validar", "lecturas": lecturas[:1]})
    assert r.json()["ok"] is False and "Ya existe" in r.json()["errores"][0]["mensaje"]


def test_lote_modo_invalido_422(client):
    assert client.post("/impresoras/lecturas/lote", json={"lecturas": [], "modo": "otro"}).status_code == 422


# ---------- resumen ----------
def test_resumen_serie_y_top(client, crear_impresora):
    actual, previo, antes = (_mes_relativo(d).strftime("%Y-%m") for d in (0, -1, -2))
    a, b = crear_impresora(es_color=True, hostname="HOST-A", area="AREA-A"), crear_impresora(hostname="HOST-B")
    c = crear_impresora()  # sin lecturas
    for imp, lecturas in ((a, [(antes, 1000, 100), (previo, 1500, 130), (actual, 2600, 400)]),
                          (b, [(antes, 500, 0), (previo, 600, 0), (actual, 650, 0)])):
        for per, bn, color in lecturas:
            r = client.post(f"/impresoras/{imp['id']}/lecturas",
                            json={"periodo": per, "fecha_lectura": f"{per}-01" if per != actual else HOY.isoformat(),
                                  "contador_bn": bn, "contador_color": color})
            assert r.status_code == 201, r.text

    base = client.get("/impresoras/resumen?meses=3").json()
    assert base["periodo_actual"] == actual
    assert [s["periodo"] for s in base["serie"]] == [antes, previo, actual]
    # las demás impresoras de la copia pueden aportar consumo: se verifica solo el aporte de las de la prueba
    sin = client.get("/impresoras/resumen?meses=3").json()
    por_periodo = {s["periodo"]: s for s in sin["serie"]}
    assert por_periodo[previo]["bn"] >= (500 + 100) and por_periodo[actual]["bn"] >= (1100 + 50)
    assert por_periodo[actual]["color"] >= 270
    assert sin["consumo_mes"] == {"bn": por_periodo[actual]["bn"], "color": por_periodo[actual]["color"]}
    assert sin["consumo_mes_anterior"] == {"bn": por_periodo[previo]["bn"], "color": por_periodo[previo]["color"]}
    assert sin["activas"] >= 3 and sin["color"] >= 1 and sin["monocromo"] >= 2
    assert sin["activas"] == sin["color"] + sin["monocromo"] and sin["total"] >= sin["activas"]
    assert sin["sin_lectura_mes_actual"] >= 1  # c

    top = sin["top"]
    assert 1 <= len(top) <= 5
    assert [t["total"] for t in top] == sorted((t["total"] for t in top), reverse=True)
    assert all(t["total"] == t["bn"] + t["color"] for t in top)
    # a: 1100 B/N + 270 color en el mes actual; no hay otra con datos reales que la supere salvo lecturas previas ajenas
    mio = next((t for t in top if t["printer_id"] == a["id"]), None)
    if mio:
        assert (mio["bn"], mio["color"], mio["total"]) == (1100, 270, 1370)
        assert (mio["hostname"], mio["area"]) == ("HOST-A", "AREA-A")
        assert mio["modelo"] == a["modelo"] and mio["empresa"] is None
    assert c["lectura_mes_actual"] is False


def test_resumen_meses_invalido_422(client):
    assert client.get("/impresoras/resumen?meses=0").status_code == 422
    assert client.get("/impresoras/resumen?meses=61").status_code == 422
    r = client.get("/impresoras/resumen?meses=1").json()
    assert len(r["serie"]) == 1


def test_baja_se_excluye_salvo_incluir_baja(client, crear_impresora, db):
    p = crear_impresora()
    db.execute("UPDATE computers SET estado_id = (SELECT id FROM statuses WHERE nombre = 'BAJA') WHERE id = %s",
               (p["computer_id"],))
    assert all(i["id"] != p["id"] for i in client.get("/impresoras").json())
    assert any(i["id"] == p["id"] and i["estado"] == "BAJA" for i in client.get("/impresoras?incluir_baja=true").json())


# ---------- resumen: estados ----------
def _poner_estado(db, impresora, estado):
    db.execute("UPDATE computers SET estado_id = (SELECT id FROM statuses WHERE nombre = %s) WHERE id = %s",
               (estado, impresora["computer_id"]))


def test_resumen_consumo_incluye_baja_excluye_eliminado_y_top_solo_activas(client, crear_impresora, db):
    actual, previo = (_mes_relativo(d).strftime("%Y-%m") for d in (0, -1))
    activa, baja, eliminada = crear_impresora(), crear_impresora(), crear_impresora()
    antes = client.get("/impresoras/resumen?meses=2").json()
    # consumo del mes actual: activa 1e12, baja 2e12, eliminada 4e12 (la eliminada y la baja desplazarían a la activa del top)
    for imp, base, consumo in ((activa, 10**12, 10**12), (baja, 10**12, 2 * 10**12), (eliminada, 10**12, 4 * 10**12)):
        assert _post_lectura(client, imp, previo, base, fecha_lectura=f"{previo}-01").status_code == 201
        assert _post_lectura(client, imp, actual, base + consumo, fecha_lectura=f"{actual}-01").status_code == 201
    _poner_estado(db, baja, "BAJA")
    _poner_estado(db, eliminada, "ELIMINADO")

    r = client.get("/impresoras/resumen?meses=2").json()
    por = {s["periodo"]: s for s in r["serie"]}
    por_antes = {s["periodo"]: s for s in antes["serie"]}
    # serie y consumo_mes: activa + baja (3e12), sin la eliminada; el mes previo aporta solo la primera lectura
    # de cada una (sin lectura anterior no hay consumo)
    assert por[actual]["bn"] - por_antes[actual]["bn"] == 3 * 10**12
    assert r["consumo_mes"]["bn"] - antes["consumo_mes"]["bn"] == 3 * 10**12
    assert r["consumo_mes"] == {"bn": por[actual]["bn"], "color": por[actual]["color"]}
    assert r["consumo_mes_anterior"] == {"bn": por[previo]["bn"], "color": por[previo]["color"]}

    ids_top = [t["printer_id"] for t in r["top"]]
    assert activa["id"] in ids_top and baja["id"] not in ids_top and eliminada["id"] not in ids_top
    assert next(t for t in r["top"] if t["printer_id"] == activa["id"])["total"] == 10**12
    # conteos (línea base con las 3 activas): la baja deja de ser activa pero cuenta en total; la eliminada ya no cuenta
    assert r["activas"] - antes["activas"] == -2 and r["total"] - antes["total"] == -1


def test_resumen_top_ignora_baja_aunque_sea_el_ultimo_periodo(client, crear_impresora, db):
    """El periodo del top se calcula entre activas: una BAJA no lo vacía ni lo desplaza."""
    previo, actual = (_mes_relativo(d).strftime("%Y-%m") for d in (-1, 0))
    activa, baja = crear_impresora(), crear_impresora()
    for per, bn in ((previo, 10**12), (actual, 2 * 10**12)):
        assert _post_lectura(client, activa, per, bn, fecha_lectura=f"{per}-01").status_code == 201
    assert _post_lectura(client, baja, previo, 5 * 10**12, fecha_lectura=f"{previo}-01").status_code == 201
    assert _post_lectura(client, baja, actual, 9 * 10**12, fecha_lectura=f"{actual}-01").status_code == 201
    _poner_estado(db, baja, "BAJA")
    ids_top = [t["printer_id"] for t in client.get("/impresoras/resumen").json()["top"]]
    assert activa["id"] in ids_top and baja["id"] not in ids_top


# ---------- concurrencia PUT / DELETE de lecturas ----------
def test_put_y_delete_concurrentes_de_lectura_no_dejan_historico_inconsistente(client, crear_impresora, db):
    """Histórico heredado: P(03)=1000, N(05)=60 (inconsistente: N sin reinicio < P) y B(06)=100 sin reinicio.
    Un PUT mueve B a 04 como reinicio (B puentea P y N: es válido) mientras un DELETE borra B.
    Resultados legítimos: DELETE primero -> (PUT 404, DELETE 204); PUT primero -> el DELETE se valida contra
    el periodo NUEVO (04), dejaría N < P y responde 409. (PUT 200, DELETE 204) solo ocurre si el DELETE usó
    el periodo viejo (06) y deja el histórico roto."""
    for ronda in range(25):
        p = crear_impresora()
        ids = {}
        for nombre, per, bn in (("P", "2024-03", 1000), ("N", "2024-05", 60), ("B", "2024-06", 100)):
            db.execute("""INSERT INTO printer_readings (printer_id, periodo, fecha_lectura, contador_bn, contador_color,
                          es_reinicio, registrado_por) VALUES (%s, %s, %s, %s, 0, false, 'test') RETURNING id""",
                       (p["id"], f"{per}-01", f"{per}-15", bn))
            ids[nombre] = db.fetchone()[0]
        barrera = threading.Barrier(2)
        resultado = {}

        def actualizar():
            c = TestClient(app)
            c.headers.update(client.headers)
            barrera.wait()
            resultado["put"] = c.put(f"/impresoras/lecturas/{ids['B']}",
                                     json=_lectura("2024-04", 50, es_reinicio=True)).status_code

        def borrar():
            c = TestClient(app)
            c.headers.update(client.headers)
            barrera.wait()
            resultado["delete"] = c.delete(f"/impresoras/lecturas/{ids['B']}").status_code

        hilos = [threading.Thread(target=actualizar), threading.Thread(target=borrar)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        assert (resultado["put"], resultado["delete"]) in {(404, 204), (200, 409)}, f"ronda {ronda}: {resultado}"
        db.execute("SELECT count(*) FROM printer_readings WHERE id = %s", (ids["B"],))
        existe = db.fetchone()[0]
        assert existe == (1 if resultado["delete"] == 409 else 0)
        # el histórico no empeora: sigue sin existir ningún par consecutivo roto salvo el heredado P -> N sin B de por medio
        if existe:
            db.execute("SELECT periodo FROM printer_readings WHERE id = %s", (ids["B"],))
            assert db.fetchone()[0].strftime("%Y-%m") == "2024-04"


def test_put_cambiando_periodo_valida_la_posicion_antigua(client, crear_impresora, db):
    """Un reinicio que puentea dos lecturas no puede moverse a otro mes: dejaría N < P en su hueco."""
    p = crear_impresora()
    r1 = _post_lectura(client, p, "2024-01", 1000)
    rb = _post_lectura(client, p, "2024-02", 50, es_reinicio=True)  # puentea P(01) y N(03)
    r3 = _post_lectura(client, p, "2024-03", 60)
    assert r1.status_code == rb.status_code == r3.status_code == 201
    antes = client.get(f"/impresoras/{p['id']}/lecturas").json()

    r = client.put(f"/impresoras/lecturas/{rb.json()['id']}", json=_lectura("2024-05", 70, es_reinicio=True))
    assert r.status_code == 409, r.text
    assert "No se puede mover la lectura" in r.json()["detail"] and "marzo de 2024" in r.json()["detail"]
    assert client.get(f"/impresoras/{p['id']}/lecturas").json() == antes  # sin cambios en la BD

    # sin cambio de periodo (solo contadores) sigue permitido
    r = client.put(f"/impresoras/lecturas/{rb.json()['id']}", json=_lectura("2024-02", 55, es_reinicio=True))
    assert r.status_code == 200, r.text
