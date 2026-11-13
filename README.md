# Consulta y descarga de facturas DIAN

RPA en Python para consultar facturas por CUFE y NIT, descargar su representación gráfica y verificar que cada PDF corresponda al documento solicitado.

El motor principal usa **Microsoft Edge normal y Windows UI Automation**, sin WebDriver, servicios de resolución de CAPTCHA ni pagos. Cada ejecución crea un perfil exclusivo y no copia cookies del navegador personal.

**Etapa 1 verificada:** diez facturas descargadas y confirmadas en una ejecución real sin intervención humana, con perfil nuevo y validación automática de Cloudflare. Se verificaron veinte páginas en total; el lote duró 160,202 segundos. El programa activó una casilla de Cloudflare en una de las pantallas. Son resultados de esa ejecución, no una garantía sobre otras sesiones.

**Etapa 2 verificada:** veinte páginas renderizadas, diez DataFrames y diez CSV por factura, más un consolidado de veintiún productos. Se conservan el OCR original y una salida conciliada con procedencia explícita. El OCR original coincidió en 110 de 114 comparaciones con el texto PDF (96,49 %); cuatro celdas se conciliaron y registraron, sin modificar el OCR. Esa concordancia no es una estimación general de precisión. El procesamiento OCR y exportación original tardó 68,533 segundos.

## Requisitos

- Windows con sesión gráfica abierta y desbloqueada.
- Microsoft Edge instalado.
- Python 3.11 o posterior y [uv](https://docs.astral.sh/uv/).
- Acceso autorizado a las facturas consultadas.

```bash
uv sync --locked --extra escritorio --group dev
uv run --extra escritorio dian-escritorio --help
```

El navegador permanece visible y el RPA utiliza teclado y ratón. **No interactuar con el equipo mientras se ejecuta.** No requiere credenciales de servicios externos.

## Entrada privada

Crear `data/consultas.json` con una lista de objetos que contengan exactamente `cufe` y `nit`, ambos cadenas de texto. El CUFE debe tener 96 caracteres hexadecimales en minúsculas; el NIT, solo dígitos sin separadores ni dígito de verificación. Se rechazan duplicados y valores inválidos, sin recortar espacios ni cambiar caracteres.

Si los CUFE están en Word, preparar la entrada con:

```bash
uv run python scripts/preparar_consultas.py data/documento.docx --nit NIT_DE_CONSULTA --salida data/consultas.json --esperados 10
```

Sustituir `NIT_DE_CONSULTA` por el valor autorizado. El script lee párrafos y tablas, admite numeración en línea o separada y comprueba el total esperado. La salida no debe existir previamente.

El portal admite el NIT del emisor **o** del receptor. No debe copiarse ese valor como NIT del emisor al extraer datos: puede corresponder a la otra parte.

Los documentos, CUFE, perfiles y resultados reales quedan fuera de Git en `data/` y `outputs/`.

## Ejecutar

```bash
uv run --extra escritorio dian-escritorio --entrada data/consultas.json --salida outputs/ejecucion-01 --perfil data/perfil-01 --timeout 60
```

Para una sola factura, añadir `--limite 1`. La salida y el perfil deben ser nuevos. No se sobrescribe evidencia ni se reutilizan sesiones personales.

El proceso es secuencial:

1. Abrir Edge con el perfil aislado y esperar el formulario.
2. Esperar `Success!` en la validación de Cloudflare.
3. Ingresar CUFE, esperar el campo NIT, completarlo y buscar.
4. Esperar la previsualización y comprobar el CUFE mostrado.
5. Activar **Descargar PDF** y aceptar el aviso de contraseña.
6. Esperar el archivo completo, verificarlo y registrar el resultado.

Se usan controles de accesibilidad de Windows. No se inyectan tokens ni se modifica el widget. Si aparece una casilla accesible de verificación humana, el programa permite un único clic normal y sigue esperando la validación. El informe distingue ese clic de la validación no interactiva.

### Alcance del CAPTCHA automático

El programa no solicita ayuda humana. En el lote real verificado completó la comprobación de Cloudflare en un perfil nuevo y sin servicios externos. **No es un solucionador universal de Turnstile ni garantiza que una sesión futura sea aceptada.**

Si el widget no valida, cambia la interfaz o una descarga no termina dentro del plazo, se detiene el lote y se registran los documentos restantes como no procesados. No hay bucles de reintento ni proveedores pagos como alternativa.

## PDF cifrados

La DIAN informa que la contraseña del PDF es el NIT usado en la consulta. `pypdf` abre el documento en memoria con ese valor y soporte AES de `cryptography`; no se adivinan contraseñas.

**El original se conserva cifrado.** Se comprueban firma `%PDF-`, estructura, páginas y CUFE en el texto extraíble. Un documento corrupto, con clave incorrecta o con otro CUFE no se confirma. Un PDF legible sin CUFE verificable se conserva como `no_verificable`.

Estas comprobaciones no equivalen a una certificación de autenticidad fiscal.

## Evidencia y métricas

La salida contiene PDF, capturas de validación y previsualización y `resultados.json`. Es material privado: el informe contiene CUFE y las capturas pueden incluir datos empresariales.

Por documento se registran estado, duración, páginas, bytes, correspondencia del CUFE, tiempo de verificación, tiempo combinado de descarga y validación, interacción con la casilla, nombre de archivo y SHA-256.

| Estado | Significado |
|---|---|
| `confirmada` | PDF descargado, legible y correspondiente al CUFE. |
| `no_verificable` | PDF legible cuya correspondencia necesita revisión. |
| `bloqueada` | Se agotó un plazo de acceso, navegación o descarga; consultar el motivo. |
| `error` | Fallo de procesamiento o estructura inesperada. |
| `no_procesada` | Consulta omitida tras el primer fallo o por un error global. |

El motor de escritorio devuelve `0` solo si todas las consultas quedan confirmadas y todas sus validaciones del navegador se completan sin pedir intervención humana. En otro caso devuelve `2`. La marca `captcha_automatico_demostrado` se limita a esa ejecución concreta.

Los tiempos usan `perf_counter`. El global incluye inicio, cierre y pausas entre consultas. El individual excluye esas pausas y la inicialización global. El tiempo de verificación se mide desde que el formulario está disponible; si el widget ya finalizó durante la carga, no representa toda su latencia de red. Aún no hay métricas de precisión OCR.

## Etapa 2: OCR local y CSV

La segunda etapa usa Tesseract en español y PDFium a 400 DPI. Extrae número de factura, fecha, NIT emisor, código, descripción, cantidad y precio unitario. Conserva un código ausente como vacío; no lo inventa. Algunas facturas contienen datos personales: imágenes, texto, informes y CSV deben permanecer privados.

Instalación, comandos probados, auditoría, conciliación, esquema y límites: **[docs/extraccion.md](docs/extraccion.md)**.

```bash
uv sync --locked --extra escritorio --extra ocr --group dev
uv run python scripts/preparar_modelo_ocr.py --salida data/tessdata-reproducible
uv run dian-ocr --entrada data/consultas.json --pdfs outputs/lote-escritorio-09 --salida outputs/etapa2-final --modelos data/tessdata-reproducible --dpi 400
uv run dian-auditar --entrada data/consultas.json --pdfs outputs/lote-escritorio-09 --ocr outputs/etapa2-final
uv run dian-conciliar --entrada data/consultas.json --ocr outputs/etapa2-final
```

Tesseract debe instalarse antes según la guía. Cambiar la salida para repetir. El auditor devuelve `2` al detectar diferencias: no significa que el OCR no se ejecutara. La conciliación usa la capa de texto PDF como segunda fuente declarada y registra todos los ajustes; no debe confundirse con una salida obtenida exclusivamente por OCR.

## Pruebas

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
```

La suite cubre entradas, extracción desde Word, cifrado AES, PDF corruptos o ajenos, CUFE fragmentados, estados del widget y orquestación de lotes. Sus datos sintéticos no cuentan como evidencia DIAN.

Para incluir cuatro pruebas locales con Playwright y Edge visible, en Bash:

```bash
DIAN_BROWSER_TESTS=1 uv run pytest -q
```

En PowerShell, establecer `$env:DIAN_BROWSER_TESTS = '1'` antes de ejecutar `uv run pytest -q`. No ejecutar pruebas de navegador simultáneamente con el RPA de escritorio porque pueden cambiar el foco.

## Dos versiones implementadas y motivo de la elección

Se desarrollaron y se conservan ambas versiones en Python:

| Versión | Implementación | Resultado comprobado |
|---|---|---|
| Automatización web con Playwright | `src/dian_pipeline/cli.py` — comando `dian-facturas` | Formulario y selectores comprobados; descarga y validación probadas con documentos sintéticos. La ejecución real no completó la validación de Cloudflare Turnstile. |
| RPA de escritorio con pywinauto | `src/dian_pipeline/desktop.py` — comando `dian-escritorio` | Lote real completo: diez PDF correspondientes, validaciones de Cloudflare automáticas y perfil nuevo, sin intervención humana ni servicios externos. |

### Limitación observada de Playwright

En las sesiones probadas, el navegador controlado por Playwright pudo cargar el formulario e ingresar CUFE y NIT, pero Turnstile no completó la validación dentro del plazo configurado. Un envío exploratorio mostró **«Falta Token de validación de captcha»**. La ejecución formal terminó con código `2`: una consulta bloqueada y nueve no procesadas, sin PDF descargados.

El bloqueo se observó **antes de la descarga**. Por ello, la versión Playwright no tiene validación real de extremo a extremo del aviso previo ni de la descarga de PDF cifrados. Sus pruebas locales con datos sintéticos comprueban el manejo de formularios, descargas y errores, pero no demuestran aceptación por Cloudflare ni éxito contra DIAN.

Esta es una limitación de las configuraciones y sesiones ensayadas, **no una afirmación de que Playwright sea incapaz de automatizar el portal en cualquier circunstancia**. Tampoco se verificó una causa única del rechazo.

Se eligió el motor de escritorio para la ejecución real porque completó el recorrido exigido en las condiciones probadas. La versión Playwright se conserva como implementación alternativa y para diagnóstico; **`dian-escritorio` es el comando recomendado para el resultado verificado**.

## Limitaciones

- Windows, Edge y sesión gráfica desbloqueada; no es un servicio sin escritorio.
- Los nombres de controles y la interfaz pueden cambiar.
- Cloudflare puede pedir verificaciones adicionales o rechazar futuras sesiones.
- No hay reanudación automática: cada ejecución conserva su evidencia.
- El OCR está ajustado a la plantilla observada; la conciliación requiere una capa de texto PDF legible y una estructura compatible.
