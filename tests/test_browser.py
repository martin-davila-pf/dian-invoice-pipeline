"""Integración local con navegador real y PDF sintético; no consulta la DIAN."""

import base64
import os

import pytest
from playwright.sync_api import sync_playwright
from test_core import CUFE, pdf_prueba

import dian_pipeline.cli as cli

pytestmark = pytest.mark.skipif(
    os.environ.get("DIAN_BROWSER_TESTS") != "1",
    reason="Activar DIAN_BROWSER_TESTS=1 para pruebas locales con Edge visible.",
)


@pytest.mark.parametrize("caso", ["correcto", "sin_cufe", "ajeno", "bloqueo"])
def test_descarga_local(tmp_path, monkeypatch, caso):
    monkeypatch.setattr(cli, "URL", "https://fixture.invalid/consulta")
    texto = {"correcto": CUFE, "sin_cufe": "", "ajeno": "b" * 96, "bloqueo": ""}[caso]
    contenido = base64.b64encode(pdf_prueba(texto)).decode()
    html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"></head><body>
    <input placeholder="Ingrese el código CUFE o UUID"
      oninput="document.getElementById('nit').hidden=false">
    <input id="nit" hidden
      placeholder="Digite el NIT del emisor o receptor, sin puntos, comas, ni DV">
    <button onclick="document.getElementById('pdf').hidden=false">Buscar</button>
    <a id="pdf" hidden download="factura.pdf"
      href="data:application/pdf;base64,{contenido}">Descargar PDF</a>
    </body></html>"""
    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="msedge", headless=False)
        try:
            page = navegador.new_page(accept_downloads=True)
            page.set_default_timeout(5000)
            page.route(
                "https://fixture.invalid/consulta",
                lambda ruta: ruta.fulfill(
                    status=403 if caso == "bloqueo" else 200, content_type="text/html", body=html
                ),
            )
            destino = tmp_path / f"{CUFE}.pdf"
            if caso == "bloqueo":
                with pytest.raises(cli.AccesoBloqueado, match="403"):
                    cli.descargar(page, {"cufe": CUFE, "nit": "123"}, destino, 1)
                assert not destino.exists()
            elif caso == "ajeno":
                with pytest.raises(ValueError, match="distinto"):
                    cli.descargar(page, {"cufe": CUFE, "nit": "123"}, destino, 1)
                assert not destino.exists()
                assert not destino.with_suffix(".pdf.part").exists()
            else:
                resultado = cli.descargar(page, {"cufe": CUFE, "nit": "123"}, destino, 1)
                esperado = "confirmada" if caso == "correcto" else "no_verificable"
                assert resultado["correspondencia"] == esperado
                assert destino.read_bytes().startswith(b"%PDF-")
        finally:
            navegador.close()
