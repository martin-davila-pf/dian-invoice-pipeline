"""Etapa 1: navegador visible, sin evasión de controles del portal."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep

from playwright.sync_api import TimeoutError as TiempoAgotado
from playwright.sync_api import expect, sync_playwright

from dian_pipeline.core import (
    cargar_consultas,
    guardar_json,
    nombre_pdf,
    resumir,
    validar_pdf,
)

URL = "https://catalogo-vpfe.dian.gov.co/User/SearchDocument"


class AccesoBloqueado(Exception):
    """La sesión no permite continuar sin completar un control de acceso."""


def descargar(page, consulta: dict, destino: Path, espera: int) -> dict:
    respuesta = page.goto(URL, wait_until="domcontentloaded")
    if respuesta and respuesta.status in {401, 403, 429}:
        raise AccesoBloqueado(f"El portal devolvió HTTP {respuesta.status}.")
    cuerpo = page.locator("body").inner_text()
    if "Solicitud bloqueada" in cuerpo:
        raise AccesoBloqueado("Solicitud bloqueada por controles de seguridad.")
    page.get_by_placeholder("Ingrese el código CUFE o UUID", exact=True).fill(consulta["cufe"])
    nit = page.get_by_placeholder(
        "Digite el NIT del emisor o receptor, sin puntos, comas, ni DV", exact=True
    )
    nit.wait_for(state="visible")
    nit.fill(consulta["nit"])
    # Solo se observa el estado normal del widget: no se obtiene ni guarda el token.
    widget = page.locator('input[name="cf-turnstile-response"]')
    if widget.count():
        try:
            expect(widget).not_to_have_value("", timeout=espera * 1000)
        except AssertionError:
            raise AccesoBloqueado(
                "Cloudflare no completó la validación en el plazo configurado."
            ) from None
    page.get_by_role("button", name="Buscar", exact=True).click()
    enlace = page.get_by_role("link", name="Descargar PDF", exact=True)
    try:
        enlace.wait_for(state="visible")
    except TiempoAgotado:
        cuerpo = page.locator("body").inner_text().lower()
        if "captcha" in cuerpo or "bloqueada" in cuerpo:
            raise AccesoBloqueado("El portal rechazó la validación de acceso.") from None
        raise RuntimeError(
            "No apareció Descargar PDF; consulta o selectores no confirmados."
        ) from None
    temporal = destino.with_suffix(".pdf.part")
    try:
        with page.expect_download() as evento:
            enlace.click()
        descarga = evento.value
        if descarga.failure():
            raise RuntimeError("El navegador informó un fallo de descarga.")
        descarga.save_as(temporal)
        validacion = validar_pdf(temporal, consulta["cufe"])
        temporal.replace(destino)
        return validacion
    finally:
        temporal.unlink(missing_ok=True)


def ejecutar(args) -> int:
    consultas = cargar_consultas(args.entrada)
    if args.limite:
        consultas = consultas[: args.limite]
    args.salida.mkdir(parents=True, exist_ok=True)
    informe = args.salida / "resultados.json"
    if informe.exists():
        raise ValueError("La carpeta ya contiene resultados.json; usa una carpeta nueva.")
    inicio = perf_counter()
    resultados = []
    contexto = {
        "inicio_utc": datetime.now(timezone.utc).isoformat(),
        "intervencion_humana_permitida": args.permitir_intervencion,
        "modo": "asistido" if args.permitir_intervencion else "sin_intervencion",
        "captcha_automatico_demostrado": False,
        "etapa": 1,
    }

    def persistir():
        guardar_json(
            informe,
            {
                **contexto,
                "resumen": resumir(resultados, perf_counter() - inicio),
                "resultados": resultados,
            },
        )

    detener = False
    with sync_playwright() as p:
        navegador = None
        try:
            navegador = p.chromium.launch(channel=args.canal, headless=False)
            sesion = navegador.new_context(accept_downloads=True)
            page = sesion.new_page()
            page.set_default_timeout(args.timeout * 1000)
            if args.permitir_intervencion:
                print("Modo asistido: puedes completar el control en el navegador visible.")
                print("Esto NO demuestra resolución automática del CAPTCHA.")
            for consulta in consultas:
                registro = {"cufe": consulta["cufe"], "estado": "no_procesada"}
                t = perf_counter()
                if detener:
                    registro["motivo"] = "Lote detenido tras un bloqueo de acceso."
                else:
                    destino = args.salida / nombre_pdf(consulta["cufe"])
                    try:
                        existente = (
                            validar_pdf(destino, consulta["cufe"]) if destino.exists() else None
                        )
                        if existente and existente["correspondencia"] == "confirmada":
                            registro.update(existente, estado="reutilizada")
                        else:
                            validacion = descargar(
                                page, consulta, destino, args.espera_verificacion
                            )
                            estado = (
                                "confirmada"
                                if validacion["correspondencia"] == "confirmada"
                                else "no_verificable"
                            )
                            registro.update(validacion, estado=estado)
                    except AccesoBloqueado as e:
                        registro.update(estado="bloqueada", motivo=str(e))
                        detener = True
                    except Exception as e:
                        # No volcar excepciones Playwright: pueden incluir valores del formulario.
                        registro.update(
                            estado="error", motivo=f"Fallo de procesamiento: {type(e).__name__}"
                        )
                    if not detener:
                        sleep(args.pausa)
                registro["duracion_segundos"] = round(perf_counter() - t, 3)
                resultados.append(registro)
                persistir()
                print(
                    f"Consulta {len(resultados)}/{len(consultas)}: {registro['estado']}", flush=True
                )
        except Exception as e:
            contexto["error_global"] = type(e).__name__
            procesadas = {r["cufe"] for r in resultados}
            for consulta in consultas:
                if consulta["cufe"] not in procesadas:
                    resultados.append(
                        {
                            "cufe": consulta["cufe"],
                            "estado": "no_procesada",
                            "motivo": "Error global de navegador o ejecución.",
                        }
                    )
        finally:
            persistir()
            if navegador:
                navegador.close()
    resumen = resumir(resultados, perf_counter() - inicio)
    guardar_json(informe, {**contexto, "resumen": resumen, "resultados": resultados})
    print(f"Informe privado: {informe.resolve()}")
    print(resumen)
    return 0 if resumen["confirmadas"] + resumen["reutilizadas"] == len(consultas) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Etapa 1: consulta DIAN y validación de PDF.")
    parser.add_argument("--entrada", type=Path, required=True, help="JSON privado con cufe y nit.")
    parser.add_argument(
        "--salida", type=Path, required=True, help="Carpeta privada de ejecución nueva."
    )
    parser.add_argument("--canal", choices=["msedge", "chrome", "chromium"], default="msedge")
    parser.add_argument("--timeout", type=int, default=30, help="Plazo por acción, en segundos.")
    parser.add_argument("--espera-verificacion", type=int, default=45)
    parser.add_argument("--permitir-intervencion", action="store_true")
    parser.add_argument("--pausa", type=float, default=2)
    parser.add_argument(
        "--limite", type=int, default=None, help="Máximo de consultas para una prueba."
    )
    args = parser.parse_args()
    if (
        args.timeout <= 0
        or args.espera_verificacion <= 0
        or args.pausa < 0
        or (args.limite is not None and args.limite <= 0)
    ):
        parser.error("Plazos y límite deben ser positivos; pausa no puede ser negativa.")
    if not args.permitir_intervencion and args.espera_verificacion > 60:
        parser.error("Esperas mayores de 60 s requieren --permitir-intervencion explícito.")
    try:
        return ejecutar(args)
    except (ValueError, OSError) as e:
        print(f"Error de entrada o salida: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
