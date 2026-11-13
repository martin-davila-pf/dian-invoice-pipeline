"""OCR local de la plantilla gráfica DIAN; sin leer texto PDF para producir los CSV."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandas import DataFrame

from dian_pipeline.core import cargar_consultas, guardar_json, nombre_pdf, validar_pdf


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))


def numero_colombiano(texto: str) -> str:
    valor = re.sub(r"\s+", "", texto.replace("$", ""))
    if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", valor):
        raise ValueError("Formato numérico colombiano ambiguo o ilegible.")
    return format(Decimal(valor.replace(".", "").replace(",", ".")), "f")


def metadatos(texto: str) -> dict[str, str]:
    base = sin_acentos(texto)
    patrones = {
        "numero_factura": r"numero\s+de\s+factura\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]*)",
        "fecha_emision": r"fecha\s+de\s+emision\s*:\s*(\d{2}/\d{2}/\d{4})",
        "nit_emisor": r"nit\s+del\s+emisor\s*:\s*(\d+)",
    }
    resultado = {}
    for campo, patron in patrones.items():
        match = re.search(patron, base, re.I)
        if not match:
            raise ValueError(f"No se pudo extraer {campo} del texto OCR.")
        resultado[campo] = match.group(1)
    resultado["fecha_emision"] = (
        datetime.strptime(resultado["fecha_emision"], "%d/%m/%Y").date().isoformat()
    )
    return resultado


def grupos(indices) -> list[tuple[int, int]]:
    import numpy as np

    return [
        (int(g[0]), int(g[-1]))
        for g in np.split(indices, np.where(np.diff(indices) > 1)[0] + 1)
        if len(g)
    ]


def mascara_verde(imagen):
    import numpy as np

    rgb = np.asarray(imagen.convert("RGB")).astype("int16")
    return (rgb[:, :, 1] > rgb[:, :, 0] + 8) & (rgb[:, :, 1] > rgb[:, :, 2] + 3)


def detectar_filas(imagen, desde_y: int) -> list[dict]:
    import numpy as np

    mask = mascara_verde(imagen)
    horizontales = grupos(np.flatnonzero(mask.sum(axis=1) > imagen.width * 0.7))
    horizontales = [g for g in horizontales if g[0] >= desde_y]
    filas = []
    for anterior, siguiente in zip(horizontales, horizontales[1:], strict=False):
        arriba, abajo = anterior[1] + 3, siguiente[0] - 3
        if abajo - arriba < 12:
            continue
        zona = mask[arriba:abajo]
        verticales = grupos(np.flatnonzero(zona.sum(axis=0) > zona.shape[0] * 0.75))
        # La tabla observada tiene trece columnas, incluidas unidades, impuestos y total.
        if len(verticales) != 14:
            continue
        bordes = [(a + b) // 2 for a, b in verticales]
        filas.append({"arriba": arriba, "abajo": abajo, "bordes": bordes})
    return filas


def limpiar_lineas(imagen):
    import numpy as np
    from PIL import Image

    rgb = np.array(imagen.convert("RGB"))
    rgb[mascara_verde(imagen)] = 255
    return Image.fromarray(rgb)


def leer_celda(imagen, fila: dict, columna: int, config: str, tipo: str) -> str:
    import numpy as np
    import pytesseract

    izquierda, derecha = fila["bordes"][columna : columna + 2]
    margen = max(3, int((derecha - izquierda) * 0.14)) if tipo == "precio" else 4
    celda = imagen.crop((izquierda + margen, fila["arriba"], derecha - 4, fila["abajo"]))
    if not (np.asarray(celda.convert("L")) < 128).any():
        return ""
    celda = celda.resize((celda.width * 2, celda.height * 2))
    psm = 6 if tipo == "descripcion" else 7
    extra = ""
    if tipo in {"precio", "cantidad", "fila"}:
        extra = " -c tessedit_char_whitelist=0123456789.,"
    elif tipo == "codigo":
        extra = (
            " -c tessedit_char_whitelist="
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._"
        )
    return pytesseract.image_to_string(
        celda, lang="spa", config=f"{config} --psm {psm}{extra}"
    ).strip()


def procesar_pdf(
    ruta: Path, consulta: dict, salida: Path, tesseract: str, modelos: Path, dpi: int = 400
) -> tuple[DataFrame, dict]:
    import pandas as pd
    import pypdfium2 as pdfium
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract
    os.environ["TESSDATA_PREFIX"] = str(modelos.resolve())
    config = ""
    inicio = perf_counter()
    if validar_pdf(ruta, consulta["cufe"], consulta["nit"])["correspondencia"] != "confirmada":
        raise ValueError("No se pudo verificar el CUFE del documento de entrada.")
    carpeta = salida / consulta["cufe"]
    carpeta.mkdir(parents=True)
    filas_csv, auditoria, tiempos = [], [], []
    datos_documento = None
    documento = pdfium.PdfDocument(str(ruta), password=consulta["nit"])
    try:
        for pagina_num in range(len(documento)):
            t = perf_counter()
            pagina = documento[pagina_num]
            imagen = pagina.render(scale=dpi / 72).to_pil().convert("RGB")
            imagen.save(carpeta / f"pagina-{pagina_num + 1:02d}.png")
            t_render = perf_counter() - t
            t = perf_counter()
            palabras = pytesseract.image_to_data(
                imagen,
                lang="spa",
                config=config + " --psm 3",
                output_type=pytesseract.Output.DATAFRAME,
            )
            palabras.to_csv(carpeta / f"pagina-{pagina_num + 1:02d}.tsv", sep="\t", index=False)
            # El texto de lectura se reconstruye de una sola inferencia por página.
            validas = palabras[palabras.text.notna() & (palabras.conf >= 0)]
            lineas = validas.groupby(["block_num", "par_num", "line_num"], sort=False).text.apply(
                lambda s: " ".join(str(v) for v in s)
            )
            texto = "\n".join(lineas)
            (carpeta / f"pagina-{pagina_num + 1:02d}.txt").write_text(texto, encoding="utf-8")
            if datos_documento is None:
                datos_documento = metadatos(texto)
            etiquetas = validas[
                validas.text.astype(str).map(lambda s: sin_acentos(s).lower()) == "detalles"
            ]
            filas_geometricas = (
                detectar_filas(imagen, int(etiquetas.top.min())) if len(etiquetas) else []
            )
            limpia = limpiar_lineas(imagen)
            for fila in filas_geometricas:
                # El ordinal es trazabilidad geométrica, no un campo solicitado al OCR.
                numero_ocr = leer_celda(limpia, fila, 0, config, "fila")
                numero = len(filas_csv) + 1
                codigo = leer_celda(limpia, fila, 1, config, "codigo")
                descripcion = leer_celda(limpia, fila, 2, config, "descripcion")
                cantidad = leer_celda(limpia, fila, 4, config, "cantidad")
                precio = leer_celda(limpia, fila, 5, config, "precio")
                if not descripcion:
                    raise ValueError("Descripción de producto vacía en OCR.")
                filas_csv.append(
                    {
                        "cufe": consulta["cufe"],
                        **datos_documento,
                        "pagina": pagina_num + 1,
                        "fila": int(numero),
                        "codigo": codigo,
                        "descripcion": " ".join(descripcion.split()),
                        "cantidad": numero_colombiano(cantidad),
                        "precio_unitario": numero_colombiano(precio),
                        "codigo_ausente": not bool(codigo),
                    }
                )
                auditoria.append(
                    {
                        "pagina": pagina_num + 1,
                        "fila": int(numero),
                        "numero_fila_ocr": numero_ocr,
                        "geometria": fila,
                        "codigo_ocr": codigo,
                        "descripcion_ocr": descripcion,
                        "cantidad_ocr": cantidad,
                        "precio_unitario_ocr": precio,
                    }
                )
            tiempos.append(
                {
                    "pagina": pagina_num + 1,
                    "render_segundos": round(t_render, 3),
                    "ocr_y_tabla_segundos": round(perf_counter() - t, 3),
                    "filas_geometricas": len(filas_geometricas),
                }
            )
            pagina.close()
    finally:
        documento.close()
    if not filas_csv:
        raise ValueError("No se detectaron productos; no se genera un CSV vacío como éxito.")
    frame = pd.DataFrame(filas_csv)
    if frame.fila.tolist() != list(range(1, len(frame) + 1)):
        raise ValueError("Las filas de productos no forman una secuencia completa desde uno.")
    frame.to_csv(salida / (consulta["cufe"] + ".csv"), index=False, encoding="utf-8-sig")
    guardar_json(carpeta / "auditoria-ocr.json", {"filas": auditoria, "paginas": tiempos})
    return frame, {
        "estado": "extraida",
        "productos": len(frame),
        "paginas": len(tiempos),
        "codigos_ausentes": int(frame.codigo_ausente.sum()),
        "duracion_segundos": round(perf_counter() - inicio, 3),
        "paginas_tiempos": tiempos,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Etapa 2: PDF a imágenes, OCR local y CSV por factura."
    )
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--pdfs", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--modelos", type=Path, default=Path("data/tessdata-best"))
    parser.add_argument(
        "--tesseract",
        default=shutil.which("tesseract") or "C:/Program Files/Tesseract-OCR/tesseract.exe",
    )
    parser.add_argument("--dpi", type=int, default=400)
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()
    if args.dpi < 150 or args.dpi > 600 or (args.limite is not None and args.limite <= 0):
        parser.error("DPI debe estar entre 150 y 600; límite debe ser positivo.")
    if args.salida.exists():
        parser.error("La salida debe ser una carpeta nueva.")
    if not args.modelos.joinpath("spa.traineddata").is_file():
        parser.error("Falta spa.traineddata en la carpeta de modelos indicada.")
    consultas = cargar_consultas(args.entrada)
    if args.limite:
        consultas = consultas[: args.limite]
    args.salida.mkdir(parents=True)
    inicio = perf_counter()
    resultados, frames = [], []
    for i, q in enumerate(consultas, 1):
        t = perf_counter()
        try:
            frame, resultado = procesar_pdf(
                args.pdfs / nombre_pdf(q["cufe"]),
                q,
                args.salida,
                args.tesseract,
                args.modelos,
                args.dpi,
            )
            frames.append(frame)
        except Exception as e:
            resultado = {
                "estado": "error",
                "motivo": f"{type(e).__name__}: {e}",
                "duracion_segundos": round(perf_counter() - t, 3),
            }
        resultados.append({"cufe": q["cufe"], **resultado})
        guardar_json(args.salida / "resultados-ocr.json", {"resultados": resultados})
        print(f"Factura {i}/{len(consultas)}: {resultado['estado']}", flush=True)
    if frames:
        import pandas as pd

        pd.concat(frames, ignore_index=True).to_csv(
            args.salida / "productos-consolidados.csv", index=False, encoding="utf-8-sig"
        )
    resumen = {
        "total": len(consultas),
        "extraidas": len(frames),
        "dataframes_creados": len(frames),
        "errores": len(consultas) - len(frames),
        "productos": sum(len(f) for f in frames),
        "duracion_segundos": round(perf_counter() - inicio, 3),
    }
    guardar_json(
        args.salida / "resultados-ocr.json",
        {
            "motor": "tesseract_local_spa",
            "dpi": args.dpi,
            "modelo_sha256": hashlib.sha256(
                (args.modelos / "spa.traineddata").read_bytes()
            ).hexdigest(),
            "final_utc": datetime.now(timezone.utc).isoformat(),
            "texto_pdf_como_fuente_de_csv": False,
            "resumen": resumen,
            "resultados": resultados,
        },
    )
    print(resumen)
    return 0 if not resumen["errores"] else 2


if __name__ == "__main__":
    sys.exit(main())
