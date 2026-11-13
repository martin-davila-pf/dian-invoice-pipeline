"""RPA de escritorio Windows: Edge normal, perfil aislado y validación natural."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep

from dian_pipeline.core import cargar_consultas, guardar_json, nombre_pdf, resumir, validar_pdf

URL = "https://catalogo-vpfe.dian.gov.co/User/SearchDocument"


class PlazoAgotado(RuntimeError):
    """Una condición observable no se completó dentro de su plazo."""


def esperar(condicion, segundos: int, mensaje: str):
    inicio = perf_counter()
    while perf_counter() - inicio < segundos:
        try:
            resultado = condicion()
            if resultado:
                return resultado
        except Exception:
            # UI Automation puede invalidar elementos durante una navegación.
            pass
        sleep(0.5)
    raise PlazoAgotado(mensaje)


def documento(ventana, titulo: str):
    return ventana.child_window(title=titulo, control_type="Document").wrapper_object()


def nombres_texto(documento_uia) -> list[str]:
    return [e.window_text() for e in documento_uia.descendants(control_type="Text")]


def verificar_acceso(ventana, titulo: str, timeout: int) -> dict:
    """Espera la verificación normal y permite un único clic en la casilla visible."""
    inicio = perf_counter()
    clic = False
    while perf_counter() - inicio < timeout:
        try:
            doc = documento(ventana, titulo)
            if "Success!" in nombres_texto(doc):
                return {"segundos": round(perf_counter() - inicio, 3), "clic_casilla": clic}
            if not clic:
                casillas = [
                    e
                    for e in doc.descendants(control_type="CheckBox")
                    if "human" in e.window_text().lower()
                ]
                if len(casillas) == 1 and casillas[0].is_visible():
                    casillas[0].click_input()
                    clic = True
        except Exception:
            pass
        sleep(0.5)
    raise PlazoAgotado("Cloudflare no completó la comprobación del navegador.")


def navegar(ventana) -> None:
    from pywinauto.keyboard import send_keys

    ventana.set_focus()
    send_keys("{ESC}")
    send_keys("^l")
    send_keys(URL, pause=0.01, with_spaces=True)
    send_keys("{ENTER}")


def consultar(ventana, consulta: dict, salida: Path, indice: int, timeout: int) -> dict:
    from pywinauto.keyboard import send_keys

    inicio = perf_counter()
    if indice > 1:
        navegar(ventana)
    esperar(
        lambda: documento(ventana, "DIAN | Acceder"),
        timeout,
        "No apareció el formulario de consulta.",
    )
    ventana.set_focus()
    send_keys("{ESC}")
    verificacion = verificar_acceso(ventana, "DIAN | Acceder", timeout)
    segundos_verificacion = verificacion["segundos"]
    ventana.capture_as_image().save(salida / f"{indice:02d}-validacion.png")
    doc = documento(ventana, "DIAN | Acceder")
    campos = doc.descendants(control_type="Edit")
    if len(campos) != 1:
        raise RuntimeError("El formulario inicial no tiene exactamente un campo de CUFE.")
    campos[0].click_input()
    campos[0].type_keys(consulta["cufe"], pause=0.01, with_spaces=True)
    campos = esperar(
        lambda: (
            c
            if len(c := documento(ventana, "DIAN | Acceder").descendants(control_type="Edit")) == 2
            else None
        ),
        timeout,
        "No apareció el campo NIT después del CUFE.",
    )
    campos[1].click_input()
    campos[1].type_keys(consulta["nit"], pause=0.02)
    ventana.child_window(title="Buscar", control_type="Button").click_input()
    esperar(
        lambda: (
            consulta["cufe"]
            in "\n".join(nombres_texto(documento(ventana, "DIAN | Detalles del documento")))
        ),
        timeout,
        "No apareció la previsualización con el CUFE consultado.",
    )
    detalles = documento(ventana, "DIAN | Detalles del documento")
    texto = "\n".join(nombres_texto(detalles))
    if consulta["cufe"] not in texto:
        raise ValueError("El CUFE de la previsualización no corresponde a la consulta.")
    verificacion_detalle = verificar_acceso(ventana, "DIAN | Detalles del documento", timeout)
    # El contenido puede ser accesible antes de terminar la carga y el enlace de eventos.
    sleep(2)
    ventana.capture_as_image().save(salida / f"{indice:02d}-previsualizacion.png")
    inicio_descarga = perf_counter()
    ventana.child_window(title_re=".*Descargar PDF", control_type="Hyperlink").invoke()
    aceptar = esperar(
        lambda: ventana.child_window(title="Aceptar", control_type="Button").wrapper_object(),
        timeout,
        "No apareció el aviso previo de descarga.",
    )
    # La DIAN informa que la contraseña del archivo es el NIT de la consulta.
    aceptar.invoke()
    esperar(
        lambda: not ventana.child_window(title="Aceptar", control_type="Button").exists(timeout=0),
        timeout,
        "El aviso de contraseña no se cerró después de aceptar.",
    )
    bruto = salida / "descargas" / nombre_pdf(consulta["cufe"])

    def archivo_completo():
        parciales = list(bruto.parent.glob("*.crdownload"))
        if bruto.is_file() and bruto.stat().st_size > 5 and not parciales:
            return bruto
        return None

    esperar(archivo_completo, timeout, "No finalizó la descarga del PDF en la carpeta privada.")
    validacion = validar_pdf(bruto, consulta["cufe"], consulta["nit"])
    destino = salida / nombre_pdf(consulta["cufe"])
    bruto.replace(destino)
    return {
        **validacion,
        "estado": "confirmada"
        if validacion["correspondencia"] == "confirmada"
        else "no_verificable",
        "validacion_natural": True,
        "clic_casilla_formulario": verificacion["clic_casilla"],
        "clic_casilla_detalle": verificacion_detalle["clic_casilla"],
        "verificacion_segundos": segundos_verificacion,
        "descarga_y_validacion_segundos": round(perf_counter() - inicio_descarga, 3),
        "duracion_segundos": round(perf_counter() - inicio, 3),
        "archivo": destino.name,
        "sha256": hashlib.sha256(destino.read_bytes()).hexdigest(),
    }


def ejecutar(args) -> int:
    if sys.platform != "win32":
        raise ValueError("El motor de escritorio requiere Windows con sesión gráfica activa.")
    from pywinauto import Desktop

    consultas = cargar_consultas(args.entrada)
    if args.limite:
        consultas = consultas[: args.limite]
    salida = args.salida.resolve()
    perfil = args.perfil.resolve()
    if salida.exists() or perfil.exists():
        raise ValueError(
            "La carpeta de salida y el perfil deben ser nuevos para aislar la evidencia."
        )
    edge = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    edge /= "Microsoft/Edge/Application/msedge.exe"
    if not edge.is_file():
        raise ValueError("No se encontró Microsoft Edge instalado.")
    (salida / "descargas").mkdir(parents=True)
    (perfil / "Default").mkdir(parents=True)
    preferencias = {
        "download": {
            "default_directory": str(salida / "descargas"),
            "prompt_for_download": False,
            "directory_upgrade": True,
        },
        "plugins": {"always_open_pdf_externally": True},
        "translate": {"enabled": False},
    }
    (perfil / "Default" / "Preferences").write_text(json.dumps(preferencias), encoding="utf-8")
    inicio = perf_counter()
    resultados: list[dict] = []
    contexto = {
        "etapa": 1,
        "motor": "escritorio_uia_edge",
        "perfil_nuevo": True,
        "inicio_utc": datetime.now(timezone.utc).isoformat(),
        "intervencion_humana_permitida": False,
        "servicios_externos_de_resolucion": False,
        "captcha_automatico_demostrado": False,
    }
    ventana = None
    error_global = None
    try:
        proceso = subprocess.Popen(
            [
                str(edge),
                "--user-data-dir=" + str(perfil),
                "--no-first-run",
                "--new-window",
                URL,
            ]
        )
        escritorio = Desktop(backend="uia")
        ventana = esperar(
            lambda: next(
                iter(escritorio.windows(process=proceso.pid, control_type="Window")), None
            ),
            args.timeout,
            "No apareció una ventana para el navegador iniciado.",
        )
        # windows() devuelve un wrapper; child_window requiere WindowSpecification.
        ventana = escritorio.window(handle=ventana.handle)
        ventana.set_focus()
        ventana.maximize()
        detenido = False
        for indice, consulta in enumerate(consultas, 1):
            registro = {"cufe": consulta["cufe"], "estado": "no_procesada"}
            t = perf_counter()
            if detenido:
                registro["motivo"] = "Lote detenido tras el primer fallo."
            else:
                try:
                    registro.update(consultar(ventana, consulta, salida, indice, args.timeout))
                except Exception as e:
                    registro.update(
                        estado="bloqueada" if isinstance(e, PlazoAgotado) else "error",
                        motivo=(
                            str(e)
                            if isinstance(e, PlazoAgotado)
                            else f"{type(e).__name__}: procesamiento no completado."
                        ),
                    )
                    detenido = True
                    try:
                        ventana.capture_as_image().save(salida / f"{indice:02d}-fallo.png")
                    except Exception:
                        pass
            registro["duracion_segundos"] = round(perf_counter() - t, 3)
            resultados.append(registro)
            guardar_json(
                salida / "resultados.json",
                {
                    **contexto,
                    "resumen": resumir(resultados, perf_counter() - inicio),
                    "resultados": resultados,
                },
            )
            print(f"Consulta {indice}/{len(consultas)}: {registro['estado']}", flush=True)
            if not detenido:
                sleep(args.pausa)
    except Exception as e:
        error_global = type(e).__name__
    finally:
        procesadas = {r["cufe"] for r in resultados}
        resultados.extend(
            {
                "cufe": q["cufe"],
                "estado": "no_procesada",
                "motivo": "Fallo global antes de procesar la consulta.",
            }
            for q in consultas
            if q["cufe"] not in procesadas
        )
        if ventana is not None:
            try:
                ventana.close()
            except Exception:
                contexto["cierre_navegador_confirmado"] = False
        if error_global:
            contexto["error_global"] = error_global
        resumen = resumir(resultados, perf_counter() - inicio)
        contexto["captcha_automatico_demostrado"] = resumen["confirmadas"] == len(
            consultas
        ) and all(r.get("validacion_natural") is True for r in resultados)
        guardar_json(
            salida / "resultados.json", {**contexto, "resumen": resumen, "resultados": resultados}
        )
    print(resumen, flush=True)
    print(f"Informe privado: {salida / 'resultados.json'}", flush=True)
    return 0 if contexto["captcha_automatico_demostrado"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="RPA gratuito de escritorio DIAN, sin WebDriver.")
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--perfil", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--pausa", type=float, default=2)
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()
    if args.timeout <= 0 or args.pausa < 0 or (args.limite is not None and args.limite <= 0):
        parser.error("Timeout y límite deben ser positivos; pausa no puede ser negativa.")
    try:
        return ejecutar(args)
    except (ValueError, OSError) as e:
        print(f"No se pudo iniciar: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
