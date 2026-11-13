"""Conciliación explícita: conserva OCR original y registra cada cambio de fuente."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandas import DataFrame

from dian_pipeline.audit import comparable
from dian_pipeline.core import cargar_consultas, guardar_json

CAMPOS = (
    "numero_factura",
    "fecha_emision",
    "nit_emisor",
    "codigo",
    "descripcion",
    "cantidad",
    "precio_unitario",
)


def conciliar_frame(frame, referencias: list[dict]) -> tuple[DataFrame, list[dict]]:
    copia = frame.copy(deep=True).astype(object)
    copia["campos_conciliados"] = ""
    copia["metodo_extraccion"] = ""
    if len(copia) != len(referencias) or not len(copia):
        raise ValueError("No se concilian tablas con filas ausentes o sobrantes.")
    cambios = []
    for indice, ref in enumerate(referencias):
        if int(copia.iloc[indice]["fila"]) != ref["fila"]:
            raise ValueError("La secuencia de filas no coincide con la referencia.")
        campos_modificados = []
        for campo in CAMPOS:
            original = str(copia.iloc[indice][campo])
            esperado = str(ref[campo])
            if comparable(campo, original) != comparable(campo, esperado):
                copia.at[copia.index[indice], campo] = esperado
                campos_modificados.append(campo)
                cambios.append(
                    {
                        "fila": ref["fila"],
                        "campo": campo,
                        "valor_ocr": original,
                        "valor_pdf": esperado,
                        "fuente_final": "capa_texto_pdf",
                    }
                )
        copia.at[copia.index[indice], "campos_conciliados"] = "|".join(campos_modificados)
        copia.at[copia.index[indice], "metodo_extraccion"] = (
            "ocr_conciliado_con_texto_pdf" if campos_modificados else "ocr"
        )
        copia.at[copia.index[indice], "codigo_ausente"] = not bool(copia.iloc[indice]["codigo"])
        for campo in CAMPOS:
            if comparable(campo, str(copia.iloc[indice][campo])) != comparable(
                campo, str(ref[campo])
            ):
                raise ValueError("La salida conciliada no coincide con su referencia.")
    return copia, cambios


def ejecutar(consultas: list[dict], ocr: Path) -> dict:
    import pandas as pd

    auditoria = json.loads((ocr / "auditoria-concordancia.json").read_text(encoding="utf-8"))
    if any(d["campo"] not in CAMPOS for d in auditoria["discrepancias"]):
        raise ValueError("Hay diferencias estructurales que exigen revisión antes de conciliar.")
    destino = ocr / "conciliados"
    if destino.exists():
        raise ValueError("La carpeta de conciliación ya existe; no se sobrescribe evidencia.")
    destino.mkdir()
    frames, cambios, resultados = [], [], []
    for indice, q in enumerate(consultas, 1):
        frame = pd.read_csv(ocr / (q["cufe"] + ".csv"), dtype=str, keep_default_na=False)
        if set(frame.cufe) != {q["cufe"]}:
            raise ValueError("Un CSV no corresponde al CUFE de su nombre.")
        referencias = [r for r in auditoria["referencias"] if r["factura"] == indice]
        conciliado, ajustes = conciliar_frame(frame, referencias)
        conciliado.to_csv(destino / (q["cufe"] + ".csv"), index=False, encoding="utf-8-sig")
        frames.append(conciliado)
        cambios.extend({"factura": indice, "cufe": q["cufe"], **c} for c in ajustes)
        resultados.append(
            {"cufe": q["cufe"], "filas": len(conciliado), "celdas_conciliadas": len(ajustes)}
        )
    pd.concat(frames, ignore_index=True).to_csv(
        destino / "productos-consolidados.csv", index=False, encoding="utf-8-sig"
    )
    informe = {
        "metodo": "ocr_con_conciliacion_explicita_capa_texto_pdf",
        "csv_por_factura": len(frames),
        "filas": sum(len(f) for f in frames),
        "celdas_conciliadas": len(cambios),
        "cambios": cambios,
        "resultados": resultados,
        "ocr_original_modificado": False,
    }
    guardar_json(destino / "conciliacion.json", informe)
    return informe


def main() -> int:
    parser = argparse.ArgumentParser(description="Conciliar CSV OCR con referencias PDF auditadas.")
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--ocr", type=Path, required=True)
    args = parser.parse_args()
    informe = ejecutar(cargar_consultas(args.entrada), args.ocr)
    print({k: informe[k] for k in ("csv_por_factura", "filas", "celdas_conciliadas")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
