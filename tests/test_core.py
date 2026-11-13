"""Pruebas con datos sintéticos; no son evidencia de descargas DIAN."""

import io
import json

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from dian_pipeline.core import (
    cargar_consultas,
    guardar_json,
    nombre_pdf,
    resumir,
    validar_consultas,
    validar_pdf,
)

CUFE = "a" * 96


def pdf_prueba(texto=""):
    escritor = PdfWriter()
    pagina = escritor.add_blank_page(width=612, height=792)
    fuente = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    pagina[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): fuente})}
    )
    contenido = DecodedStreamObject()
    contenido.set_data(f"BT /F1 10 Tf 10 700 Td ({texto}) Tj ET".encode())
    pagina[NameObject("/Contents")] = escritor._add_object(contenido)
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def test_consulta_valida_preservada():
    entrada = [{"cufe": CUFE, "nit": "001234"}]
    assert validar_consultas(entrada) == entrada


@pytest.mark.parametrize(
    "valor",
    ["A" * 96, "a" * 95, "a" * 97, CUFE + "\n", " " + CUFE, "g" * 96, "../factura", None, 123],
)
def test_rechaza_cufe_sin_repararlo(valor):
    with pytest.raises(ValueError):
        validar_consultas([{"cufe": valor, "nit": "123"}])


@pytest.mark.parametrize("valor", [123, "12-3", "12.3", " 123", "", None, "1" * 16])
def test_rechaza_nit(valor):
    with pytest.raises(ValueError):
        validar_consultas([{"cufe": CUFE, "nit": valor}])


@pytest.mark.parametrize("valor", [[], {}, None, [{}], [{"cufe": CUFE, "nit": "123", "x": 1}]])
def test_estructura_invalida(valor):
    with pytest.raises(ValueError):
        validar_consultas(valor)


def test_duplicados():
    item = {"cufe": CUFE, "nit": "123"}
    with pytest.raises(ValueError):
        validar_consultas([item, item])


def test_nombre_seguro():
    assert nombre_pdf(CUFE) == CUFE + ".pdf"
    with pytest.raises(ValueError):
        nombre_pdf("../archivo")


def test_pdf_correspondiente(tmp_path):
    ruta = tmp_path / "factura.pdf"
    ruta.write_bytes(pdf_prueba(CUFE))
    resultado = validar_pdf(ruta, CUFE)
    assert resultado["correspondencia"] == "confirmada"
    assert resultado["paginas"] == 1
    assert resultado["bytes"] == ruta.stat().st_size


def test_pdf_cufe_fragmentado(tmp_path):
    ruta = tmp_path / "factura.pdf"
    ruta.write_bytes(pdf_prueba(CUFE[:48] + " " + CUFE[48:]))
    assert validar_pdf(ruta, CUFE)["correspondencia"] == "confirmada"


def test_pdf_ajeno(tmp_path):
    ruta = tmp_path / "otra.pdf"
    ruta.write_bytes(pdf_prueba("b" * 96))
    with pytest.raises(ValueError, match="distinto"):
        validar_pdf(ruta, CUFE)


def test_pdf_sin_cufe_no_es_exito(tmp_path):
    ruta = tmp_path / "sin_texto.pdf"
    ruta.write_bytes(pdf_prueba())
    assert validar_pdf(ruta, CUFE)["correspondencia"] == "no_verificable"


@pytest.mark.parametrize("contenido", [b"<html>bloqueo</html>", b"", b"%PDF-basura"])
def test_pdf_invalido(tmp_path, contenido):
    ruta = tmp_path / "falso.pdf"
    ruta.write_bytes(contenido)
    with pytest.raises((ValueError, PdfReadError)):
        validar_pdf(ruta, CUFE)


def test_pdf_vacio(tmp_path):
    ruta = tmp_path / "vacio.pdf"
    with ruta.open("wb") as salida:
        PdfWriter().write(salida)
    with pytest.raises(ValueError, match="páginas"):
        validar_pdf(ruta, CUFE)


def test_json_y_resumen(tmp_path):
    ruta = tmp_path / "privado" / "entrada.json"
    datos = [{"cufe": CUFE, "nit": "123"}]
    guardar_json(ruta, datos)
    assert cargar_consultas(ruta) == datos
    assert json.loads(ruta.read_text()) == datos
    assert not ruta.with_suffix(".json.tmp").exists()
    estados = ["confirmada", "reutilizada", "no_verificable", "bloqueada", "error", "no_procesada"]
    resumen = resumir([{"estado": e} for e in estados], 1.23456)
    assert resumen == {
        "total": 6,
        "confirmadas": 1,
        "reutilizadas": 1,
        "pendientes_verificacion": 1,
        "bloqueadas": 1,
        "errores": 1,
        "no_procesadas": 1,
        "duracion_segundos": 1.235,
    }
