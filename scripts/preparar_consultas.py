"""Extrae identificadores literales de Word a una entrada privada de consultas."""

import argparse
import re
from pathlib import Path

from docx import Document

from dian_pipeline.core import guardar_json, validar_consultas


def extraer(ruta: Path, nit: str, esperados: int) -> list[dict[str, str]]:
    doc = Document(ruta)
    bloques = [p.text for p in doc.paragraphs]
    bloques.extend(
        celda.text for tabla in doc.tables for fila in tabla.rows for celda in fila.cells
    )
    candidatos = re.findall(
        r"(?<![0-9a-fA-F])[0-9a-fA-F]{80,110}(?![0-9a-fA-F])", "\n".join(bloques)
    )
    consultas = validar_consultas([{"cufe": cufe, "nit": nit} for cufe in candidatos])
    if len(consultas) != esperados:
        raise ValueError(f"Se esperaban {esperados} CUFE únicos; se encontraron {len(consultas)}.")
    return consultas


def main():
    parser = argparse.ArgumentParser(
        description="Preparar consultas privadas desde un documento Word."
    )
    parser.add_argument("documento", type=Path)
    parser.add_argument("--nit", required=True)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--esperados", type=int, default=10)
    args = parser.parse_args()
    if args.esperados <= 0 or args.salida.exists():
        parser.error("El total debe ser positivo y la salida no debe existir.")
    consultas = extraer(args.documento, args.nit, args.esperados)
    guardar_json(args.salida, consultas)
    print(f"Consultas únicas validadas: {len(consultas)}. Guardadas en {args.salida}.")


if __name__ == "__main__":
    main()
