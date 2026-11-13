"""Validación local sin normalizar identificadores de entrada."""

import json
import re
from pathlib import Path

from pypdf import PdfReader

CUFE = re.compile(r"[0-9a-f]{96}")
NIT = re.compile(r"[0-9]{1,15}")


def validar_consultas(datos: object) -> list[dict[str, str]]:
    if not isinstance(datos, list) or not datos:
        raise ValueError("La entrada debe ser una lista no vacía de consultas.")
    vistos: set[str] = set()
    resultado = []
    for indice, item in enumerate(datos, 1):
        if not isinstance(item, dict) or set(item) != {"cufe", "nit"}:
            raise ValueError(f"Consulta {indice}: se requieren exactamente cufe y nit.")
        cufe, nit = item["cufe"], item["nit"]
        if not isinstance(cufe, str) or not CUFE.fullmatch(cufe):
            raise ValueError(f"Consulta {indice}: CUFE inválido; no se modifica la entrada.")
        if not isinstance(nit, str) or not NIT.fullmatch(nit):
            raise ValueError(f"Consulta {indice}: NIT debe ser texto numérico sin separadores.")
        if cufe in vistos:
            raise ValueError(f"Consulta {indice}: CUFE duplicado.")
        vistos.add(cufe)
        resultado.append({"cufe": cufe, "nit": nit})
    return resultado


def cargar_consultas(ruta: Path) -> list[dict[str, str]]:
    return validar_consultas(json.loads(ruta.read_text(encoding="utf-8")))


def nombre_pdf(cufe: str) -> str:
    if not CUFE.fullmatch(cufe):
        raise ValueError("CUFE inválido para construir el nombre de archivo.")
    return f"{cufe}.pdf"


def validar_pdf(ruta: Path, cufe: str, clave: str | None = None) -> dict:
    nombre_pdf(cufe)
    with ruta.open("rb") as archivo:
        if archivo.read(5) != b"%PDF-":
            raise ValueError("El archivo recibido no tiene firma PDF.")
    lector = PdfReader(ruta, strict=True)
    if lector.is_encrypted:
        if clave is None or not lector.decrypt(clave):
            raise ValueError("PDF cifrado: falta una clave válida para verificar su contenido.")
    if not lector.pages:
        raise ValueError("El PDF no contiene páginas.")
    texto = "\n".join(pagina.extract_text() or "" for pagina in lector.pages)
    compacto = re.sub(r"\s+", "", texto)
    encontrados = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{96}(?![0-9a-f])", compacto))
    if cufe in encontrados:
        correspondencia = "confirmada"
    elif encontrados:
        raise ValueError("El PDF contiene un CUFE distinto al consultado.")
    else:
        correspondencia = "no_verificable"
    return {
        "paginas": len(lector.pages),
        "bytes": ruta.stat().st_size,
        "correspondencia": correspondencia,
    }


def resumir(resultados: list[dict], duracion: float) -> dict:
    estados = [r["estado"] for r in resultados]
    return {
        "total": len(resultados),
        "confirmadas": estados.count("confirmada"),
        "reutilizadas": estados.count("reutilizada"),
        "pendientes_verificacion": estados.count("no_verificable"),
        "bloqueadas": estados.count("bloqueada"),
        "errores": estados.count("error"),
        "no_procesadas": estados.count("no_procesada"),
        "duracion_segundos": round(duracion, 3),
    }


def guardar_json(ruta: Path, datos: object) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporal.replace(ruta)
