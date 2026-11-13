# Extracción de facturas: imágenes, OCR y conciliación

## Resultado de la ejecución verificada

Se procesaron diez PDF cifrados, con veinte páginas físicas, y se crearon diez DataFrames. La salida contiene un CSV por factura y un consolidado de veintiuna filas de productos.

El OCR original coincidió con la capa de texto del PDF en **110 de 114 comparaciones de campos únicos (96,49 %)**. Las cuatro diferencias fueron dos códigos con confusión `S/5`, una descripción con `I/1` y una tilde que no figuraba en el texto original. Es concordancia con otra representación del mismo documento, **no una estimación general de precisión ni una evaluación con un conjunto de referencia independiente**.

Se conservaron los CSV OCR sin cambios. Los CSV finales conciliados incorporan cuatro ajustes documentados usando la capa de texto del PDF; las celdas discrepantes también se revisaron visualmente en las imágenes originales. Se verificaron los siete campos en cada una de las veintiuna filas finales: 147 comprobaciones de consistencia. Esto no se presenta como precisión OCR del 100 %.

Una factura no incluye código de producto. Ese campo permanece vacío y se marca `codigo_ausente`; no se inventó un código ni se confundió un vacío con el código literal `0` de otra factura.

## Dependencias y preparación

```bash
uv sync --locked --extra escritorio --extra ocr --group dev
winget install --id UB-Mannheim.TesseractOCR --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
uv run python scripts/preparar_modelo_ocr.py --salida data/tessdata-reproducible
```

El instalador puede requerir permisos del sistema. En el equipo validado se usó Tesseract 5.4.0.20240606. El programa busca `tesseract` en PATH o en `C:/Program Files/Tesseract-OCR/tesseract.exe`; admite una ruta diferente con `--tesseract`.

`preparar_modelo_ocr.py` descarga únicamente el modelo español `spa.traineddata` de `tessdata_best`, fijado a una revisión y SHA-256. Los PDF y sus imágenes **no se envían a servicios externos**. Tras instalar las dependencias y descargar el modelo, el procesamiento es local y no requiere API ni pagos.

## Recorrido reproducible

Usar la entrada privada de consultas y una carpeta nueva de salida:

```bash
uv run dian-ocr --entrada data/consultas.json --pdfs outputs/lote-escritorio-09 --salida outputs/etapa2-final --modelos data/tessdata-reproducible --dpi 400
uv run dian-auditar --entrada data/consultas.json --pdfs outputs/lote-escritorio-09 --ocr outputs/etapa2-final
uv run dian-conciliar --entrada data/consultas.json --ocr outputs/etapa2-final
```

En la ejecución documentada, el modelo se preparó en `data/tessdata-reproducible`; puede usarse la ruta predeterminada `data/tessdata-best` y omitir `--modelos` si se preparó allí. Para repetir, cambiar el nombre de la carpeta de salida: no se sobrescriben los resultados.

`dian-ocr` devuelve `0` si extrae todas las facturas. Eso prueba finalización del procedimiento, **no exactitud de todos los caracteres**. `dian-auditar` devuelve `2` si encuentra discrepancias; en esta ejecución ese resultado era esperado y quedó conservado. La conciliación exige que no existan diferencias estructurales de filas y devuelve `0` al generar los CSV conciliados. No debe ignorarse un fallo técnico del auditor para continuar como si no hubiera diferencias.

## Cómo se obtiene el texto

1. Verificar el CUFE del PDF de entrada y abrirlo con el NIT autorizado indicado por el portal.
2. Renderizar todas las páginas a PNG RGB, a 400 DPI, con PDFium. No se altera el PDF cifrado.
3. Ejecutar Tesseract en español sobre cada imagen y conservar palabras, coordenadas y confianza en TSV, además del texto de lectura.
4. Extraer número de factura, fecha de emisión y NIT del **emisor**, no el del receptor.
5. Detectar la cuadrícula de productos por sus líneas verdes y separar las celdas. La plantilla observada tiene trece columnas; solo se exportan los campos requeridos más trazabilidad.
6. Eliminar el color de las líneas sin inventar caracteres y aplicar OCR por celda. Una celda sin tinta oscura se considera vacía en lugar de aceptar una letra espuria.
7. Construir un DataFrame por PDF y exportarlo a CSV, repitiendo sus metadatos en cada producto.

La capa de texto PDF se usa inicialmente para comprobar identidad del archivo, **no para producir los campos del CSV OCR original**. El contraste y los ajustes de fuente son fases posteriores explícitas.

## Auditoría y conciliación

El auditor obtiene los metadatos desde el texto PDF y los campos de productos desde regiones geométricas de su capa de texto. Compara esos valores con el OCR, verifica la secuencia de filas y conserva las discrepancias. Los metadatos se comparan una vez por documento; los cuatro campos de producto se comparan por fila.

Para descripciones se ignoran únicamente espacios y saltos introducidos por la maquetación. No se ignoran diferencias de letras, números, tildes o signos. No se intenta corregir nombres, completar palabras partidas ni mejorar la redacción del documento.

La conciliación crea una carpeta aparte, nunca modifica el OCR original y registra `valor_ocr`, `valor_pdf`, campo y fila de cada cambio en `conciliacion.json`. En los CSV finales, `campos_conciliados` y `metodo_extraccion` indican qué filas usaron la segunda fuente. Sin capa de texto o con una estructura incompatible, la auditoría no puede certificar ni conciliar automáticamente el documento: se requiere revisión.

## Esquema de los CSV

| Campo | Tratamiento |
|---|---|
| `numero_factura` | Texto; conserva prefijos y ceros. |
| `fecha_emision` | Fecha ISO `AAAA-MM-DD`. |
| `nit_emisor` | Texto, sin sustituirlo por el NIT de consulta. |
| `codigo` | Texto; admite vacío cuando falta en el original y conserva `0`. |
| `descripcion` | Texto con saltos de celda unidos mediante espacios. |
| `cantidad` | Decimal sin pasar por números binarios de punto flotante. |
| `precio_unitario` | Decimal sin separadores de miles, con punto decimal. |

Se añaden `cufe`, `pagina`, `fila` y `codigo_ausente` para trazabilidad. La conciliación añade sus dos columnas de procedencia. Los CSV usan comas y UTF-8 con BOM. Al importar en Excel conviene seleccionar explícitamente delimitador coma, punto decimal y tipo texto para CUFE, NIT y código.

## Archivos de salida

- Raíz: diez CSV OCR y `productos-consolidados.csv`.
- Carpeta por CUFE: PNG, texto, TSV por página y `auditoria-ocr.json` con geometría y tiempos.
- `resultados-ocr.json`: estados y tiempos por factura, DPI y hash del modelo.
- `auditoria-concordancia.json`: comparación OCR/PDF y referencias.
- `conciliados/`: diez CSV finales, consolidado y registro de cambios.
- `verificacion-final.json`: comprobaciones finales y hashes de los CSV conciliados.

Todo este material queda excluido de Git. Algunas facturas contienen datos personales; las salidas no son ejemplos para publicar ni fixtures de pruebas.

## Tiempos y límites

El lote de renderizado, OCR y exportación original tardó **68,533 segundos**. Esa medición incluye verificación de entrada, imágenes, OCR de páginas y celdas, archivos de evidencia y CSV; **no incluye descarga inicial, instalación, desarrollo, auditoría ni conciliación posterior**. Los tiempos por página y documento se conservan en el informe. No se atribuyen tiempos no medidos a otras fases.

El procedimiento se ajustó a la plantilla DIAN observada. Cambios de color, estructura, columnas, resolución o idioma pueden impedir la detección. La auditoría se verificó con estos diez PDF de dos páginas físicas; no se ha demostrado cobertura de todas las variantes multipágina de la DIAN. Los dígitos o códigos nunca se reparan por sustituciones globales como `S → 5` o `I → 1`.
