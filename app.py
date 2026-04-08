import os
import time
from datetime import datetime
from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

def configurar_driver_nube():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

@app.route("/", methods=["GET"])
def iniciar_scraper():
    driver = configurar_driver_nube()
    URL_BASE = "https://tv.senado.cl/tvsenado/site/tax/port/all/taxport_7_41__1.html"
    FECHA_LIMITE = datetime(2026, 1, 1)
    
    datos_extraidos = []
    procesados = set()

    try:
        driver.get(URL_BASE)
        time.sleep(3) # Esperar carga inicial
        
        continuar = True
        while continuar:
            # Capturar TODAS las comisiones en pantalla (Cámara y Senado sin exclusión)
            articulos = driver.find_elements(By.CSS_SELECTOR, "article.col.span_1_of_4.article")
            nuevos_encontrados = False

            for art in articulos:
                try:
                    link_element = art.find_element(By.CSS_SELECTOR, "a.title")
                    url_sesion = link_element.get_attribute("href")
                    
                    if url_sesion in procesados:
                        continue
                        
                    nuevos_encontrados = True
                    procesados.add(url_sesion)
                    
                    # Verificación de Fecha
                    fecha_str = art.find_element(By.CSS_SELECTOR, ".date").text.strip()
                    fecha_dt = datetime.strptime(fecha_str, "%d/%m/%Y")
                    
                    if fecha_dt < FECHA_LIMITE:
                        continuar = False
                        break
                        
                    nombre_comision = link_element.text.strip()
                    
                    # Entrar a la sesión para buscar el MP4 en una pestaña nueva
                    driver.execute_script(f"window.open('{url_sesion}', '_blank');")
                    driver.switch_to.window(driver.window_handles[1])
                    
                    url_video = "No encontrado"
                    try:
                        wait = WebDriverWait(driver, 5)
                        link_mp4_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.downloadVideo")))
                        url_video = link_mp4_element.get_attribute("href")
                    except:
                        pass # Si no hay video, continúa
                        
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    
                    datos_extraidos.append({
                        "comision": nombre_comision,
                        "fecha": fecha_str,
                        "url_pagina": url_sesion,
                        "url_video": url_video
                    })
                except Exception as e:
                    # Recuperación en caso de error para no detener el barrido
                    if len(driver.window_handles) > 1:
                        driver.switch_to.window(driver.window_handles[1])
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue
            
            if not continuar:
                break
                
            # Scroll dinámico para cargar el siguiente bloque de comisiones
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(4)
            
            # Si el scroll no cargó nada nuevo, hemos llegado al final
            if not nuevos_encontrados:
                time.sleep(3)
                articulos_check = driver.find_elements(By.CSS_SELECTOR, "article.col.span_1_of_4.article")
                if len(articulos_check) == len(articulos):
                    break

        return jsonify({
            "status": "Exito",
            "mensaje": "Barrido completado sin omisiones.",
            "total_sesiones_extraidas": len(datos_extraidos),
            "datos": datos_extraidos
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        driver.quit()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)