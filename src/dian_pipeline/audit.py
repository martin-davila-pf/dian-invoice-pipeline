"""Compara la salida OCR con la capa de texto PDF; no modifica los CSV."""

import argparse
import json
import re
from pathlib import Path

from dian_pipeline.core import cargar_consultas, guardar_json
from dian_pipeline.ocr import numero_colombiano


def comparable(campo: str, valor: str) -> str:
    if campo == "descripcion":
        # El diseño parte palabras entre líneas; no se corrigen letras ni signos.
        return re.sub(r"\s+", "", valor)
    return valor


def auditar(consultas: list[dict], pdfs: Path, salida_ocr: Path) -> dict:
    import pandas as pd
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    discrepancias, resultados, referencias = [], [], []
    comparaciones = coincidencias = 0
    for i, q in enumerate(consultas, 1):
        ruta = pdfs / (q["cufe"] + ".pdf")
        reader = PdfReader(ruta)
        if reader.is_encrypted and not reader.decrypt(q["nit"]):
            raise ValueError("No se pudo abrir un PDF de referencia.")
        texto = "\n".join(p.extract_text() or "" for p in reader.pages)
        patrones = {
            "numero_factura": r"Número de Factura:\s*([\w-]+)",
            "fecha_emision": r"Fecha de Emisión:\s*(\d{2})/(\d{2})/(\d{4})",
            "nit_emisor": r"Nit del Emisor:\s*(\d+)",
        }
        referencia = {}
        for campo, patron in patrones.items():
            match = re.search(patron, texto)
            if match is None:
                raise ValueError(f"Falta {campo} en el texto de referencia.")
            referencia[campo] = (
                f"{match[3]}-{match[2]}-{match[1]}" if campo == "fecha_emision" else match[1]
            )
        frame = pd.read_csv(salida_ocr / (q["cufe"] + ".csv"), dtype=str, keep_default_na=False)
        for campo, esperado in referencia.items():
            comparaciones += 1
            encontrado = frame.iloc[0][campo]
            coincide = encontrado == esperado
            coincidencias += coincide
            if not coincide:
                discrepancias.append(
                    {"factura": i, "campo": campo, "ocr": encontrado, "referencia_pdf": esperado}
                )
        seccion = texto.split("Detalles de Productos", 1)[1]
        seccion = re.split(
            r"Descuentos y Recargos Globales|Referencias|Notas Finales|Hoja ", seccion, maxsplit=1
        )[0]
        lineas = [v.strip() for v in seccion.splitlines() if v.strip()]
        secuencia = [
            v
            for n, v in enumerate(lineas[:-1])
            if re.fullmatch(r"[1-9]\d{0,2}", v) and not re.fullmatch(r"\d+,\d+", lineas[n + 1])
        ]
        if [int(v) for v in secuencia] != list(range(1, len(frame) + 1)):
            discrepancias.append(
                {
                    "factura": i,
                    "campo": "numero_de_filas",
                    "ocr": len(frame),
                    "referencia_pdf": secuencia,
                }
            )
        auditoria = json.loads(
            (salida_ocr / q["cufe"] / "auditoria-ocr.json").read_text(encoding="utf-8")
        )
        doc = pdfium.PdfDocument(str(ruta), password=q["nit"])
        try:
            for n, fila in enumerate(auditoria["filas"]):
                page = doc[fila["pagina"] - 1]
                textpage = page.get_textpage()
                reporte = json.loads(
                    (salida_ocr / "resultados-ocr.json").read_text(encoding="utf-8")
                )
                escala = reporte["dpi"] / 72
                g = fila["geometria"]
                valores = {}
                for campo, col in [
                    ("codigo", 1),
                    ("descripcion", 2),
                    ("cantidad", 4),
                    ("precio_unitario", 5),
                ]:
                    valor = textpage.get_text_bounded(
                        left=(g["bordes"][col] + 3) / escala,
                        right=(g["bordes"][col + 1] - 3) / escala,
                        top=page.get_height() - g["arriba"] / escala,
                        bottom=page.get_height() - g["abajo"] / escala,
                    ).strip()
                    if campo in {"cantidad", "precio_unitario"}:
                        try:
                            valor = numero_colombiano(valor)
                        except ValueError as error:
                            raise ValueError(
                                f"Referencia factura {i}, fila {n + 1}, {campo}: {valor!r}"
                            ) from error
                    elif campo == "descripcion":
                        valor = " ".join(valor.split())
                    valores[campo] = valor
                    obtenido = frame.iloc[n][campo]
                    coincide = comparable(campo, obtenido) == comparable(campo, valor)
                    comparaciones += 1
                    coincidencias += coincide
                    if not coincide:
                        discrepancias.append(
                            {
                                "factura": i,
                                "fila": n + 1,
                                "campo": campo,
                                "ocr": obtenido,
                                "referencia_pdf": valor,
                            }
                        )
                referencias.append({"factura": i, **referencia, "fila": n + 1, **valores})
                textpage.close()
                page.close()
        finally:
            doc.close()
        resultados.append({"factura": i, "filas": len(frame)})
    return {
        "metodo": "concordancia_ocr_con_capa_texto_pdf_no_precision_manual",
        "comparaciones": comparaciones,
        "coincidencias": coincidencias,
        "discrepancias": discrepancias,
        "facturas": resultados,
        "referencias": referencias,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditar CSV OCR sin corregir sus valores.")
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--pdfs", type=Path, required=True)
    parser.add_argument("--ocr", type=Path, required=True)
    args = parser.parse_args()
    resultado = auditar(cargar_consultas(args.entrada), args.pdfs, args.ocr)
    guardar_json(args.ocr / "auditoria-concordancia.json", resultado)
    print({k: v for k, v in resultado.items() if k not in {"referencias", "facturas"}})
    return 0 if not resultado["discrepancias"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
