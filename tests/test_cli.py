"""Pruebas de orquestación con navegador sustituido explícitamente."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import dian_pipeline.cli as cli
from dian_pipeline.core import guardar_json


@pytest.mark.parametrize("caso", ["bloqueo", "error", "correcto", "sin_cufe"])
def test_orquestacion(tmp_path, monkeypatch, caso):
    consultas = [{"cufe": caracter * 96, "nit": "123"} for caracter in "abcdef0123"]
    entrada = tmp_path / "entrada.json"
    guardar_json(entrada, consultas)
    page = SimpleNamespace(set_default_timeout=lambda _: None)
    browser = SimpleNamespace(
        new_context=lambda **_: SimpleNamespace(new_page=lambda: page), close=lambda: None
    )

    @contextmanager
    def navegador_falso():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_: browser))

    llamadas = []

    def descarga_falsa(_page, consulta, _destino, _espera):
        llamadas.append(consulta["cufe"])
        if caso == "bloqueo":
            raise cli.AccesoBloqueado("Bloqueo sintético de prueba.")
        if caso == "error":
            raise RuntimeError("Error sintético de prueba.")
        return {
            "correspondencia": "no_verificable" if caso == "sin_cufe" else "confirmada",
            "bytes": 100,
            "paginas": 1,
        }

    monkeypatch.setattr(cli, "sync_playwright", navegador_falso)
    monkeypatch.setattr(cli, "descargar", descarga_falsa)
    args = SimpleNamespace(
        entrada=entrada,
        salida=tmp_path / "salida",
        limite=None,
        permitir_intervencion=False,
        canal="msedge",
        timeout=1,
        espera_verificacion=1,
        pausa=0,
    )
    codigo = cli.ejecutar(args)
    reporte = json.loads((args.salida / "resultados.json").read_text(encoding="utf-8"))
    resumen = reporte["resumen"]
    assert resumen["total"] == len(reporte["resultados"]) == 10
    assert (
        sum(
            resumen[k]
            for k in [
                "confirmadas",
                "reutilizadas",
                "pendientes_verificacion",
                "bloqueadas",
                "errores",
                "no_procesadas",
            ]
        )
        == 10
    )
    assert len(llamadas) == (1 if caso == "bloqueo" else 10)
    assert codigo == (0 if caso == "correcto" else 2)
    assert reporte["captcha_automatico_demostrado"] is False
    if caso == "bloqueo":
        assert resumen["bloqueadas"] == 1
        assert resumen["no_procesadas"] == 9
    with pytest.raises(ValueError, match="carpeta nueva"):
        cli.ejecutar(args)
