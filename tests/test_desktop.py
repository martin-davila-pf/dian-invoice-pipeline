"""Pruebas del estado del widget con UI Automation simulado, sin consultar el portal."""

from types import SimpleNamespace

import pytest

import dian_pipeline.desktop as desktop


@pytest.mark.parametrize("requiere_clic", [False, True])
def test_estado_widget_sin_intervencion(monkeypatch, requiere_clic):
    estado = {"validado": not requiere_clic, "clics": 0}

    def click():
        estado["clics"] += 1
        estado["validado"] = True

    casilla = SimpleNamespace(
        window_text=lambda: "Verify you are human", is_visible=lambda: True, click_input=click
    )
    doc = SimpleNamespace(descendants=lambda **_: [casilla])
    monkeypatch.setattr(desktop, "documento", lambda *_: doc)
    monkeypatch.setattr(
        desktop, "nombres_texto", lambda _: ["Success!"] if estado["validado"] else []
    )
    monkeypatch.setattr(desktop, "sleep", lambda _: None)
    resultado = desktop.verificar_acceso(None, "documento simulado", 1)
    assert resultado["clic_casilla"] is requiere_clic
    assert estado["clics"] == int(requiere_clic)


def test_no_confunde_formulario_con_widget_validado(monkeypatch):
    doc = SimpleNamespace(descendants=lambda **_: [])
    monkeypatch.setattr(desktop, "documento", lambda *_: doc)
    monkeypatch.setattr(desktop, "nombres_texto", lambda _: ["Buscar documento"])
    contador = iter([0, 0.1, 2])
    monkeypatch.setattr(desktop, "perf_counter", lambda: next(contador))
    monkeypatch.setattr(desktop, "sleep", lambda _: None)
    with pytest.raises(desktop.PlazoAgotado, match="Cloudflare"):
        desktop.verificar_acceso(None, "documento simulado", 1)


def test_un_solo_clic_aunque_no_complete(monkeypatch):
    estado = {"clics": 0}

    def click():
        estado["clics"] += 1

    casilla = SimpleNamespace(
        window_text=lambda: "Verify you are human", is_visible=lambda: True, click_input=click
    )
    doc = SimpleNamespace(descendants=lambda **_: [casilla])
    monkeypatch.setattr(desktop, "documento", lambda *_: doc)
    monkeypatch.setattr(desktop, "nombres_texto", lambda _: [])
    contador = iter([0, 0.1, 0.2, 0.3, 2])
    monkeypatch.setattr(desktop, "perf_counter", lambda: next(contador))
    monkeypatch.setattr(desktop, "sleep", lambda _: None)
    with pytest.raises(desktop.PlazoAgotado):
        desktop.verificar_acceso(None, "documento simulado", 1)
    assert estado["clics"] == 1


def test_espera_no_oculta_timeout(monkeypatch):
    contador = iter([0, 0.1, 2])
    monkeypatch.setattr(desktop, "perf_counter", lambda: next(contador))
    monkeypatch.setattr(desktop, "sleep", lambda _: None)
    with pytest.raises(desktop.PlazoAgotado, match="condición no cumplida"):
        desktop.esperar(lambda: False, 1, "condición no cumplida")


def test_espera_retorna_resultado():
    assert desktop.esperar(lambda: "listo", 1, "error") == "listo"
