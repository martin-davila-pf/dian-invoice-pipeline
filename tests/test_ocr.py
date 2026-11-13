"""Casos sintéticos de OCR y conciliación; no sustituyen la ejecución real."""

import copy

import pytest

from dian_pipeline.audit import comparable
from dian_pipeline.ocr import (
    detectar_filas,
    leer_celda,
    limpiar_lineas,
    metadatos,
    numero_colombiano,
)
from dian_pipeline.reconcile import conciliar_frame


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("1,00", "1.00"),
        ("75.000,00", "75000.00"),
        ("2.900.000,00", "2900000.00"),
        ("$ \r\n75.000,00", "75000.00"),
        ("0,00", "0.00"),
        ("12", "12"),
    ],
)
def test_numero_decimal_sin_float(texto, esperado):
    assert numero_colombiano(texto) == esperado


@pytest.mark.parametrize("texto", ["1.20", "I,00", "1,00,00", "75.OOO,00", "", "1.2.3", "-1,00"])
def test_numero_ambiguo_no_se_repara(texto):
    with pytest.raises(ValueError):
        numero_colombiano(texto)


def test_metadatos_emisor_no_receptor():
    texto = "Número de Factura: XYZ-001 Forma de pago: Crédito\nFecha de Emisión: 01/02/2025\n"
    texto += "Nit del Emisor: 123456789 País: Colombia\nNúmero Documento: 987654321"
    assert metadatos(texto) == {
        "numero_factura": "XYZ-001",
        "fecha_emision": "2025-02-01",
        "nit_emisor": "123456789",
    }


def test_metadatos_rechaza_faltantes():
    with pytest.raises(ValueError, match="numero_factura"):
        metadatos("Datos del documento sin campos")


def test_fecha_no_valida():
    with pytest.raises(ValueError):
        metadatos("Numero de Factura: X-1\nFecha de Emision: 31/02/2025\nNit del Emisor: 123")


def test_geometria_dos_filas_y_limpieza():
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(image)
    verde = (70, 210, 140)
    bordes = [20 + i * 73 for i in range(14)]
    draw.rectangle((bordes[0], 20, bordes[-1], 50), fill=verde)
    for y in [50, 120, 220]:
        draw.line((bordes[0], y, bordes[-1], y), fill=verde, width=3)
    for x in bordes:
        draw.line((x, 50, x, 220), fill=verde, width=3)
    draw.text((bordes[2] + 10, 70), "Producto sintetico", fill="black")
    filas = detectar_filas(image, 0)
    assert len(filas) == 2
    assert all(len(f["bordes"]) == 14 for f in filas)
    limpia = np.array(limpiar_lineas(image))
    assert tuple(limpia[20, 20]) == (255, 255, 255)
    assert (limpia < 128).any()


def test_celda_vacia_no_invoca_ocr(monkeypatch):
    pytesseract = pytest.importorskip("pytesseract")
    Image = pytest.importorskip("PIL.Image")

    def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("Una celda vacía no debe producir caracteres inventados.")

    monkeypatch.setattr(pytesseract, "image_to_string", no_debe_llamarse)
    image = Image.new("RGB", (200, 100), "white")
    fila = {"bordes": [0, 100, 200], "arriba": 0, "abajo": 100}
    assert leer_celda(image, fila, 0, "", "codigo") == ""


def test_concordancia_no_oculta_caracteres_distintos():
    assert comparable("descripcion", "PALAB RA\nI") == comparable("descripcion", "PALABRA I")
    assert comparable("codigo", "S123") != comparable("codigo", "5123")
    assert comparable("descripcion", "I") != comparable("descripcion", "1")
    assert comparable("descripcion", "ACCION") != comparable("descripcion", "ACCIÓN")


def ejemplo():
    pd = pytest.importorskip("pandas")
    fila = {
        "numero_factura": "XYZ-01",
        "fecha_emision": "2025-02-01",
        "nit_emisor": "123",
        "codigo": "5123",
        "descripcion": "PRODUCTO",
        "cantidad": "1.00",
        "precio_unitario": "1250.00",
        "fila": "1",
        "cufe": "a" * 96,
        "codigo_ausente": "False",
    }
    referencia = {**copy.deepcopy(fila), "fila": 1, "codigo": "S123"}
    return pd.DataFrame([fila]), [referencia]


def test_conciliacion_explicita_no_modifica_ocr():
    frame, referencias = ejemplo()
    original = frame.copy(deep=True)
    salida, cambios = conciliar_frame(frame, referencias)
    assert frame.equals(original)
    assert salida.iloc[0].codigo == "S123"
    assert salida.iloc[0].campos_conciliados == "codigo"
    assert salida.iloc[0].metodo_extraccion == "ocr_conciliado_con_texto_pdf"
    assert cambios == [
        {
            "fila": 1,
            "campo": "codigo",
            "valor_ocr": "5123",
            "valor_pdf": "S123",
            "fuente_final": "capa_texto_pdf",
        }
    ]


def test_conciliacion_mantiene_codigo_ausente():
    frame, referencias = ejemplo()
    frame.at[0, "codigo"] = ""
    referencias[0]["codigo"] = ""
    salida, cambios = conciliar_frame(frame, referencias)
    assert salida.iloc[0].codigo == ""
    assert salida.iloc[0].codigo_ausente
    assert cambios == []


def test_conciliacion_no_inventa_filas():
    frame, _ = ejemplo()
    with pytest.raises(ValueError, match="filas ausentes"):
        conciliar_frame(frame, [])


def test_conciliacion_no_reordena_filas():
    frame, referencias = ejemplo()
    referencias[0]["fila"] = 2
    with pytest.raises(ValueError, match="secuencia"):
        conciliar_frame(frame, referencias)
