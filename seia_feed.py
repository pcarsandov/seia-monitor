#!/usr/bin/env python3
# Genera feed.xml (RSS) y data.json con los proyectos recientes del SEIA
# Fuente: https://seia.sea.gob.cl/busqueda/buscarProyectoResumen.php

import requests, time, hashlib, json, datetime, re
from bs4 import BeautifulSoup
from xml.sax.saxutils import escape
from dateutil import tz

BASE = "https://seia.sea.gob.cl/busqueda/buscarProyectoResumen.php"
DOMAIN = "https://seia.sea.gob.cl"
LOCAL_TZ = tz.gettz("America/Santiago")

# Configuración simple para principiantes:
PAGES_TO_SCAN = 2   # cuántas páginas quieres leer (2 suele bastar para cubrir el día)
USER_AGENT = "Mozilla/5.0 (compatible; SEIA-monitor/1.0; +https://github.com/)"

def to_rfc822(dt):
    import datetime as _dt
    from dateutil import tz as _tz
    return dt.astimezone(_tz.tzutc()).strftime("%a, %d %b %Y %H:%M:%S +0000")

def fetch(url):
    r = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text

def absolutize(href):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return DOMAIN + href
    return DOMAIN + "/" + href

def parse_list(html):
    """
    Intenta encontrar filas de resultados.
    Esta función está pensada para ser fácil de ajustar si el HTML cambia.
    """
    soup = BeautifulSoup(html, "html.parser")

    items = []

    # 1) Intenta tabla estándar: <table class="..."> ... <tbody><tr>...</tr>
    rows = soup.select("table tbody tr")

    # 2) Si no encuentra, intenta bloques tipo cards
    if not rows:
        rows = soup.select(".resultado-item, .busqueda-lista .item, .view-content .views-row")

    for row in rows:
        try:
            # Caso típico: columnas en <td>
            tds = row.find_all("td")
            if len(tds) >= 5:
                folio = tds[0].get_text(strip=True)
                proyecto = tds[1].get_text(strip=True)
                tipo = tds[2].get_text(strip=True)     # DIA / EIA
                titular = tds[3].get_text(strip=True)
                lugar = tds[4].get_text(strip=True)    # comuna / región (depende del sitio)
                a = row.find("a", href=True)
                link = absolutize(a["href"]) if a else BASE
            else:
                # Fallback: intentar por etiquetas con strong/spans
                text = row.get_text(" ", strip=True)
                # heurísticas suaves:
                folio_match = re.search(r"\b\d{2}\.\d{3}\.\d{3}\-\d\b|\bID\s*:\s*(\w+)", text)
                folio = folio_match.group(0) if folio_match else "SIN_FOLIO"
                proyecto = text[:120]
                tipo = "DIA/EIA"
                titular = ""
                lugar = ""
                a = row.find("a", href=True)
                link = absolutize(a["href"]) if a else BASE

            items.append({
                "folio": folio,
                "proyecto": proyecto,
                "tipo": tipo,
                "titular": titular,
                "lugar": lugar,
                "link": link
            })
        except Exception:
            continue

    # Buscar link “Siguiente” (o equivalente)
    next_link = None
    # comunes: texto "Siguiente", ">", o rel="next"
    nxt = soup.find("a", attrs={"rel": "next"}) or soup.find("a", string=lambda s: s and "Siguiente" in s)
    if nxt and nxt.get("href"):
        next_link = absolutize(nxt["href"])

    return items, next_link

def make_feed(items):
    now = datetime.datetime.now(tz=LOCAL_TZ)
    header = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>SEIA - Ingresos recientes (no oficial)</title>
<link>{BASE}</link>
<description>Feed generado automáticamente desde la lista pública del SEIA</description>
<lastBuildDate>{to_rfc822(now)}</lastBuildDate>
"""
    body = ""
    for it in items:
        title = f"{it['folio']} - {it['proyecto']}"
        link = it['link'] or BASE
        desc = f"Titular: {it['titular']} | Tipo: {it['tipo']} | Ubicación: {it['lugar']}"
        guid = hashlib.sha1((it['folio'] + it['proyecto']).encode()).hexdigest()
        pub = to_rfc822(now)  # sin fecha oficial por ítem: usamos la de generación
        body += f"""  <item>
    <title>{escape(title)}</title>
    <link>{escape(link)}</link>
    <guid isPermaLink="false">{guid}</guid>
    <pubDate>{pub}</pubDate>
    <description>{escape(desc)}</description>
  </item>
"""
    footer = "</channel>\n</rss>\n"
    return header + body + footer

def main():
    url = BASE
    all_items = []
    pages = 0
    while url and pages < PAGES_TO_SCAN:
        html = fetch(url)
        items, next_link = parse_list(html)
        all_items.extend(items)
        url = next_link
        pages += 1
        time.sleep(1.2)  # amable con el servidor

    # Genera salida
    import os
    os.makedirs("out", exist_ok=True)

    # RSS
    rss = make_feed(all_items)
    with open("out/feed.xml", "w", encoding="utf-8") as f:
        f.write(rss)

    # JSON
    now = datetime.datetime.now(tz=LOCAL_TZ).isoformat()
    with open("out/data.json", "w", encoding="utf-8") as f:
        json.dump({"generated": now, "count": len(all_items), "items": all_items}, f, ensure_ascii=False, indent=2)

    print(f"Listo: {len(all_items)} items escritos en out/feed.xml y out/data.json")

if __name__ == "__main__":
    main()
