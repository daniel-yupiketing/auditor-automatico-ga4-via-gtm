# 🤖 Auditor automático de eventos de GA4 frente a GTM (Python + Playwright + Streamlit)

Herramienta en Python para auditar de forma **autónoma** los eventos enviados al `dataLayer` de una o varias páginas web y contrastarlos automáticamente con las reglas, activadores y parámetros configurados en un contenedor de **Google Tag Manager (GTM)**.

Incluye tanto una **interfaz web interactiva con Streamlit** como una **interfaz por línea de comandos (CLI)**, y genera informes gráficos en **HTML** (con el mismo diseño visual que la extensión de Chrome), **CSV** (listo para Excel) y **JSON**.

---

## ✨ Características principales

1. **Rastreador y auditor autónomo con Playwright**:
   - Inyecta un interceptor en `window.dataLayer` antes de que cargue cualquier script de la página (`add_init_script`).
   - Acepta automáticamente banners de cookies (OneTrust, Didomi, Cookiebot, etc.).
   - Realiza *scroll* progresivo e intercepta `IntersectionObserver` para disparar todos los eventos de visibilidad (`view_promotion` y `view_item_list`).
   - **Priorización inteligente de clics**: localiza en el DOM las promociones y tarjetas de producto asociadas a `view_promotion` y `view_item_list` y alterna clics (50 % promociones / 50 % productos) bloqueando la navegación para capturar `select_promotion`, `select_item` y `view_item` en la misma sesión.
2. **Soporte para listado personalizado de URL o rastreo automático**:
   - Permite pegar un listado de URL o subir un archivo `.txt` / `.csv`.
   - O bien partir de una URL inicial y descubrir enlaces internos automáticamente.
3. **Validación estricta frente al contenedor de GTM**:
   - Incluye integrado por defecto el contenedor `GTM-NK9G27ZB` (`tarifasfibramovil.es`), con opción de subir cualquier otro archivo JSON exportado de GTM.
   - Distingue entre parámetros obligatorios (`ERROR` ❌), recomendados o no recogidos por GTM (`WARNING` ⚠️) y parámetros opcionales en eventos personalizados como `services` o `funnel_step`.
   - Deduplicación inteligente de errores para no duplicar incidencias idénticas y agrupar las URL donde se detectan.
4. **Informes visuales en HTML, CSV y JSON**:
   - Generación automática de informe interactivo en HTML con buscador, filtro por estado y botón para imprimir o guardar en PDF.

---

## 🚀 Instalación

1. Clona este repositorio:
   ```bash
   git clone https://github.com/daniel-yupiketing/auditor-automatico-ga4-via-gtm.git
   cd auditor-automatico-ga4-via-gtm
   ```

2. Instala las dependencias de Python y el navegador Chromium de Playwright:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

---

## 🖥️ Uso desde la interfaz web (Streamlit)

Ejecuta el siguiente comando para abrir la aplicación en tu navegador (`http://localhost:8501`):

```bash
streamlit run ga4_event_analyzer.py
```

Desde la interfaz podrás:
- Pegar un listado de URL o subir un archivo `.txt`/`.csv` y lanzar la auditoría autónoma en vivo.
- Subir archivos `.json` exportados desde la extensión de Chrome.
- Visualizar el informe gráfico directamente en pantalla y descargarlo en **HTML**, **CSV** o **JSON**.

---

## 💻 Uso por línea de comandos (CLI)

### 1. Auditar una o varias URL automáticamente (genera y abre el informe HTML)
```bash
python ga4_event_analyzer.py --url https://www.masmovil.es/ https://www.masmovil.es/fibra-optica
```

### 2. Auditar un listado de URL desde un archivo `.txt` o `.csv`
```bash
python ga4_event_analyzer.py --urls-file urls.txt --max-clicks 10 --html mi_informe.html
```

### 3. Rastrear una web descubriendo enlaces internos
```bash
python ga4_event_analyzer.py --url https://www.masmovil.es/ --crawl --max-pages 5
```

### 4. Auditar un archivo JSON de eventos ya capturados
```bash
python ga4_event_analyzer.py eventos_capturados.json --html informe.html -o informe.json
```

---

## ☁️ Despliegue en Google Cloud Run

El repositorio incluye un `Dockerfile` preparado con la imagen oficial de Playwright. Para desplegarlo en Cloud Run con escalado a cero (`min-instances=0`):

```bash
gcloud run deploy auditor-ga4-gtm \
  --source . \
  --region europe-southwest1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 600 \
  --min-instances 0 \
  --max-instances 2
```
