"""Casos de cifrado y límites del identificador, usando documentos sintéticos."""

import io

import pytest
from pypdf import PdfReader, PdfWriter
from test_core import CUFE, pdf_prueba

from dian_pipeline.core import validar_pdf


@pytest.mark.parametrize("clave", [None, "incorrecta", "123456"])
def test_pdf_aes_con_nit_conocido(tmp_path, clave):
    escritor = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_prueba(CUFE))))
    escritor.encrypt("123456", algorithm="AES-256")
    ruta = tmp_path / "cifrado.pdf"
    with ruta.open("wb") as archivo:
        escritor.write(archivo)
    if clave == "123456":
        assert validar_pdf(ruta, CUFE, clave)["correspondencia"] == "confirmada"
    else:
        with pytest.raises(ValueError, match="clave válida"):
            validar_pdf(ruta, CUFE, clave)
    assert PdfReader(ruta).is_encrypted


def test_no_acepta_subcadena_hexadecimal(tmp_path):
    ruta = tmp_path / "identificador_largo.pdf"
    ruta.write_bytes(pdf_prueba(CUFE + "a"))
    assert validar_pdf(ruta, CUFE)["correspondencia"] == "no_verificable"
