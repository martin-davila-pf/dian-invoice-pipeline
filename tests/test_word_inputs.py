"""La extracción de Word conserva CUFE en líneas numeradas y en tablas."""

import importlib.util
from pathlib import Path

import pytest
from docx import Document

spec = importlib.util.spec_from_file_location(
    "preparar_consultas", Path(__file__).parents[1] / "scripts" / "preparar_consultas.py"
)
modulo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)


def test_lineas_numeradas_y_tablas(tmp_path):
    doc = Document()
    for i, caracter in enumerate("abcde", 1):
        doc.add_paragraph(f"{i}. {caracter * 96}")
    for i, caracter in enumerate("f012", 6):
        doc.add_paragraph(f"{i}.")
        doc.add_paragraph(caracter * 96)
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "3" * 96
    ruta = tmp_path / "identificadores.docx"
    doc.save(ruta)
    consultas = modulo.extraer(ruta, "123", 10)
    assert len(consultas) == 10
    assert [q["cufe"] for q in consultas] == [c * 96 for c in "abcdef0123"]


@pytest.mark.parametrize("valor", ["A" * 96, "a" * 95, "a" * 97])
def test_no_repara_identificadores(tmp_path, valor):
    doc = Document()
    doc.add_paragraph(valor)
    ruta = tmp_path / "invalido.docx"
    doc.save(ruta)
    with pytest.raises(ValueError):
        modulo.extraer(ruta, "123", 1)


def test_total_incorrecto(tmp_path):
    doc = Document()
    doc.add_paragraph("a" * 96)
    ruta = tmp_path / "incompleto.docx"
    doc.save(ruta)
    with pytest.raises(ValueError, match="esperaban 10"):
        modulo.extraer(ruta, "123", 10)
