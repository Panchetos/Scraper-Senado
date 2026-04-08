import os
import json
import time
from datetime import datetime
from flask import Flask, jsonify, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
URL_BASE = "https://tv.senado.cl/tvsenado/site/tax/port/all/taxport_7_41__1.html"
FECHA_LIMITE = datetime(2026, 1, 1)          # Scraping desde esta fecha en adelante
ARCHIVO_PROGRESO = "/tmp/senado_progreso.json"  # Persiste entre reintentos en la misma instancia
SCROLL_PAUSA = 4        # Segundos de espera tras cada scroll
TIMEOUT_PAGINA = 8      # Segundos de espera máxima para elementos en página de sesión
MAX_RONDAS_SIN_NUEVOS = 3  # Cuántas rondas sin artículos nuevos antes de considerar el fin


# ─────────────────────────────────────────────
# DRIVER
# ─────────────────────────────────────────────
def configurar_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


# ─────────────────────────────────────────────
# PERSISTENCIA DE PROGRESO
# ─────────────────────────────────────────────
def cargar_progreso():
    """Carga el archivo de progreso si existe (para reanudar tras un fallo)."""
    if os.path.exists(ARCHIVO_PROGRESO):
        try:
            with open(ARCHIVO_PROGRESO, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"📂 Progreso anterior encontrado: {len(data['datos'])} sesiones ya extraídas.", flush=True)
            return data["datos"], set(data["procesados"])
        except Exception as e:
            print(f"⚠️ No se pudo leer el progreso anterior: {e}", flush=True)
    return [], set()


def guardar_progreso(datos, procesados):
    """Guarda progreso incremental en disco."""
    try:
        with open(ARCHIVO_PROGRESO, "w", encoding="utf-8") as f:
            json.dump(
                {"datos": datos, "procesados": list(procesados), "ultima_actualizacion": datetime.now().isoformat()},
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print(f"⚠️ Error guardando progreso: {e}", flush=True)


# ─────────────────────────────────────────────
# EXTRACCIÓN DEL LINK DE VIDEO
# ─────────────────────────────────────────────
def extraer_url_video(driver, url_sesion):
    """Abre la página de una sesión en una nueva pestaña y extrae el enlace MP4."""
    url_video = "No encontrado"
    try:
        driver.execute_script(f"window.open('{url_sesion}', '_blank');")
        driver.switch_to.window(driver.window_handles[1])

        try:
            # Selector 1: botón de descarga directo
            wait = WebDriverWait(driver, TIMEOUT_PAGINA)
            link_mp4 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.downloadVideo")))
            url_video = link_mp4.get_attribute("href")
            print(f"   ✅ MP4 vía botón de descarga", flush=True)
        except Exception:
            try:
                # Selector 2: buscar cualquier <a> cuyo href termine en .mp4
                links = driver.find_elements(By.TAG_NAME, "a")
                for link in links:
                    href = link.get_attribute("href") or ""
                    if href.endswith(".mp4"):
                        url_video = href
                        print(f"   ✅ MP4 vía href directo", flush=True)
                        break
            except Exception:
                pass

            if url_video == "No encontrado":
                try:
                    # Selector 3: etiqueta <source> dentro de <video>
                    source = driver.find_element(By.CSS_SELECTOR, "video source")
                    src = source.get_attribute("src") or ""
                    if src.endswith(".mp4"):
                        url_video = src
                        print(f"   ✅ MP4 vía etiqueta <source>", flush=True)
                except Exception:
                    print(f"   ⚠️ No se encontró enlace de video en esta sesión.", flush=True)

    except Exception as e:
        print(f"   ❌ Error abriendo pestaña de sesión: {e}", flush=True)
    finally:
        # Siempre cerrar la pestaña extra y volver a la principal
        try:
            if len(driver.window_handles) > 1:
                driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except Exception:
            pass

    return url_video


# ─────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ─────────────────────────────────────────────
def ejecutar_scraper():
    datos_extraidos, procesados = cargar_progreso()
    driver = configurar_driver()

    try:
        print(f"🌐 Abriendo página principal: {URL_BASE}", flush=True)
        driver.get(URL_BASE)
        time.sleep(3)

        ronda = 1
        rondas_sin_nuevos = 0
        continuar = True

        while continuar:
            print(f"\n🔄 Ronda #{ronda} — artículos procesados hasta ahora: {len(datos_extraidos)}", flush=True)

            articulos = driver.find_elements(By.CSS_SELECTOR, "article.col.span_1_of_4.article")
            print(f"🔎 Artículos visibles en pantalla: {len(articulos)}", flush=True)

            nuevos_en_ronda = 0

            for art in articulos:
                try:
                    # ── Obtener URL de la sesión ──
                    link_element = art.find_element(By.CSS_SELECTOR, ".text a")
                    url_sesion = link_element.get_attribute("href")

                    if not url_sesion or url_sesion in procesados:
                        continue

                    # ── Obtener fecha ──
                    try:
                        fecha_str = art.find_element(By.CSS_SELECTOR, ".date").text.strip()
                        fecha_dt = datetime.strptime(fecha_str, "%d/%m/%Y")
                    except Exception:
                        # Intentar formato alternativo dd-mm-yyyy
                        try:
                            fecha_str = art.find_element(By.CSS_SELECTOR, ".date").text.strip()
                            fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
                        except Exception as e_fecha:
                            print(f"   ⚠️ No se pudo parsear la fecha: {e_fecha}", flush=True)
                            continue

                    # ── Filtro de fecha ──
                    if fecha_dt < FECHA_LIMITE:
                        print(f"🛑 Fecha límite alcanzada ({fecha_str}). Deteniendo.", flush=True)
                        continuar = False
                        break

                    # ── Nombre de la comisión ──
                    try:
                        nombre_comision = art.find_element(By.CSS_SELECTOR, ".title").text.strip()
                    except Exception:
                        nombre_comision = "Desconocido"

                    print(f"▶️  {nombre_comision} | {fecha_str}", flush=True)

                    # ── Extraer URL del video ──
                    url_video = extraer_url_video(driver, url_sesion)

                    # ── Registrar y guardar inmediatamente ──
                    procesados.add(url_sesion)
                    datos_extraidos.append({
                        "comision": nombre_comision,
                        "fecha": fecha_str,
                        "url_pagina": url_sesion,
                        "url_video": url_video
                    })
                    nuevos_en_ronda += 1

                    # Guardado incremental: cada nuevo registro se persiste
                    guardar_progreso(datos_extraidos, procesados)

                except Exception as e:
                    print(f"❌ Error procesando artículo: {e}", flush=True)
                    # Asegurarse de volver a la pestaña principal si algo salió mal
                    try:
                        if len(driver.window_handles) > 1:
                            driver.switch_to.window(driver.window_handles[1])
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                    except Exception:
                        pass
                    continue

            if not continuar:
                break

            # ── Scroll para cargar más artículos ──
            if nuevos_en_ronda == 0:
                rondas_sin_nuevos += 1
                print(f"⏸️  Sin artículos nuevos — intento {rondas_sin_nuevos}/{MAX_RONDAS_SIN_NUEVOS}", flush=True)
                if rondas_sin_nuevos >= MAX_RONDAS_SIN_NUEVOS:
                    print("🏁 Fin de página detectado. Scraping completo.", flush=True)
                    break
            else:
                rondas_sin_nuevos = 0

            print("⏬ Haciendo scroll hacia abajo...", flush=True)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSA)
            ronda += 1

    except Exception as e:
        print(f"❌ ERROR CRÍTICO: {e}", flush=True)
        raise
    finally:
        driver.quit()
        print(f"\n🎉 Scraping finalizado. Total de sesiones: {len(datos_extraidos)}", flush=True)

    return datos_extraidos


# ─────────────────────────────────────────────
# ENDPOINTS FLASK
# ─────────────────────────────────────────────
@app.route("/", methods=["GET"])
def iniciar_scraper():
    """Inicia el scraping completo y devuelve los resultados al terminar."""
    print("🚀 Iniciando scraper del Senado...", flush=True)
    try:
        datos = ejecutar_scraper()
        return jsonify({
            "status": "Éxito",
            "total_sesiones": len(datos),
            "datos": datos
        }), 200
    except Exception as e:
        return jsonify({"status": "Error", "detalle": str(e)}), 500


@app.route("/progreso", methods=["GET"])
def ver_progreso():
    """Devuelve el estado del progreso guardado sin lanzar un nuevo scraping."""
    datos, procesados = cargar_progreso()
    if not datos:
        return jsonify({"status": "Sin progreso guardado"}), 404
    return jsonify({
        "status": "Progreso parcial",
        "total_sesiones": len(datos),
        "ultima_url": datos[-1]["url_pagina"] if datos else None,
        "datos": datos
    }), 200


@app.route("/limpiar", methods=["GET"])
def limpiar_progreso():
    """Elimina el archivo de progreso para empezar desde cero."""
    if os.path.exists(ARCHIVO_PROGRESO):
        os.remove(ARCHIVO_PROGRESO)
        return jsonify({"status": "Progreso eliminado. Próximo scraping empezará desde cero."}), 200
    return jsonify({"status": "No había progreso guardado."}), 200


# ─────────────────────────────────────────────
# ENTRADA
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)