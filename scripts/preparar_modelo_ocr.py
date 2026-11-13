"""Descarga un modelo español fijado y verifica su integridad antes de usarlo."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

REVISION = "e12c65a915945e4c28e237a9b52bc4a8f39a0cec"
SHA256 = "e2c1ffdad8b30f26c45d4017a9183d3a7f9aa69e59918be4f88b126fac99ab2c"
URL = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{REVISION}/spa.traineddata"


def main():
    parser = argparse.ArgumentParser(
        description="Preparar modelo OCR español local, sin API de pago."
    )
    parser.add_argument("--salida", type=Path, default=Path("data/tessdata-best"))
    args = parser.parse_args()
    args.salida.mkdir(parents=True, exist_ok=True)
    destino = args.salida / "spa.traineddata"
    if destino.exists():
        contenido = destino.read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=60) as respuesta:
            contenido = respuesta.read()
    if hashlib.sha256(contenido).hexdigest() != SHA256:
        raise ValueError("El modelo no coincide con el SHA-256 esperado; no se utiliza.")
    if not destino.exists():
        temporal = destino.with_suffix(".tmp")
        temporal.write_bytes(contenido)
        temporal.replace(destino)
    print(f"Modelo español verificado: {len(contenido)} bytes. SHA-256: {SHA256}")


if __name__ == "__main__":
    main()
