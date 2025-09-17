#!/usr/bin/env python3
# seia_feed.py — robusto: prueba GET y dos variantes POST, mapea por encabezados y sube páginas
import requests, time, hashlib, json, datetime, re, os
from bs4 import BeautifulSoup
from xml.sax.saxutils import escape
from dateutil import tz

BASE = "https://seia.sea.gob.cl/busqueda/buscarProyectoResumen.php"
DOMAIN = "https://seia.sea.gob.cl"
LOCAL_TZ = tz.gettz("America/Santiago")
USER_AGENT = "Mozilla/5.0 (compatible; SEIA-monitor/1.2; +https://github.com/)"

# Escanea más páginas para cubrir el día
PAGES_TO_SCAN = 4
REQUEST_PAUSE_SEC = 1.2

def to_rfc822(dt):
    from dateutil import tz as _tz
    return dt.astimezone(_tz.tzutc()).strftime("%a, %d %b %Y %H:%M:%S +0000")

def absolutize(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return DOMAIN + href
    return DOMAIN + "/" + href

def get_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    s.get(BASE, timeout=30)
    return s

def fetch_page_variants(session: requests.Session, page: int):
    """Devuelve HTML usando 3 variantes: GET con params, POST accion=buscar, POST buscar=Buscar"""
    # Variante 1: GET con parámetros (muchos sitios PHP aceptan esto)
    params = {
        "accion": "buscar",
        "pagina": str(page),
        "orden": "fecha_ingreso",
        "dir": "desc",
        "tipo": "", "region": "", "comuna": "", "titular": "", "proyecto": ""
    }
    try:
        r = session.get(BASE, params=params, timeout=30)
        r.raise_for_status()
        html = r.text
        if looks_like_results(html):
            return html, "GET"
    except Exception:
        pass

    # Variante 2: POST con accion=buscar
    payload = dict(params)
    try:
        r = session.post(BASE, data=payload, timeout=30)
        r.raise_for_status()
        html = r.text
        if looks_like_results(html):
            return html, "POST_accion"
    except Exception:
        pass

    # Variante 3: POST con botón típico buscar=Buscar
    payload_alt = {
        "buscar": "Buscar",
        "pagina": str(page),
        "orden": "fecha_ingreso",
        "dir": "desc",
        "tipo": "", "region": "", "comuna": "", "titular": "", "proyecto": ""
    }
    try:
        r = session.post(BASE, data=payload_alt, timeout=30)
        r.raise_for_status()
        html = r.text
        if looks_like_results(html):
            return html, "POST_boton"
    except Exception:
        pass

    # Si ninguna devolvió algo que parezca “resultados”, retornamos la última para debug
    return html if 'html' in locals() else "", "NONE"

def looks_like_results(html: str) -> bool:
    # Señales suaves de que hay tabla de resultados:
    if not html:
        return False
    # Palabras que suelen estar en la tabla/encabezados de resultados
    hints = ["Folio", "Proyecto", "Titular", "Comuna", "Región", "Resultados", "resultado", "tbody", "<table"]
    score = sum(1 for h in hints if h.lower() in html.lower())
    return score >= 3

def guess_table_and_columns(soup: BeautifulSoup):
    wanted = {
        "folio": ["folio", "id"],
        "proyecto": ["proyecto", "nombre"],
        "tipo": ["tipo", "instrumento", "dia", "eia"],
        "titular": ["titular"],
        "lugar": ["comuna", "región", "region", "ubicación", "ubicacion"]
    }
    tables = soup.find_all("table")
    for tbl in tables:
        thead = tbl.find("thead")
        if not thead:
            continue
        ths = [th.get_text(" ", strip=True).lower() for th in thead.find_all("th")]
        if not ths or len(ths) < 4:
            continue
        idx = {}
        for i, label in enumerate(ths):
            for key, keys in wanted.items():
                if any(k in label for k in keys):
                    idx.setdefault(key, i)
        if "folio" in idx and "proyecto" in idx:
            return tbl, idx
    return None, {}

def parse_rows_from_table(tbl, idx_map):
    items = []
    tbody = tbl.find("tbody") or tbl
    for tr in tbody.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue

        def val(key, default=""):
            i = idx_map.get(key, None)
            if i is None or i >= len(tds):
                return default
            return tds[i].get_text(" ", strip=True)

        folio = val("folio", "SIN_FOLIO")
        proyecto = val("proyecto", "")
        tipo = val("tipo", "")
        titular = val("titular", "")
        lugar = val("lugar", "")
        a = tr.find("a", href=True)
        link = absolutize(a["href"]) if a else BASE
        if not proyecto and not titular:
            continue
        items.append({
            "folio": folio, "proyecto": proyecto, "tipo": tipo,
            "titular": titular, "lugar": lugar, "link": link
        })
    return items

def parse_list(html: str):
    soup = BeautifulSoup(html, "html.parser")
    # Intento 1: por encabezados
    tbl, idx = guess_table_and_columns(soup)
    if tbl:
        items = parse_rows_from_table(tbl, idx)
    else:
        # Intento 2: tabla sin thead
        items = []
        rows = soup.select("table tbody tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            folio = tds[0].get_text(strip=True)
            proyecto = tds[1].get_text(strip=True)
            tipo = tds[2].get_text(strip=True)
            titular = tds[3].get_text(strip=True)
            lugar = tds[4].get_text(strip=True)
            a = tr.find("a", href=True)
            link = absolutize(a["href"]) if a else BASE
            if not proyecto and not titular:
                continue
            items.append({
                "folio": folio, "proyecto": proyecto, "tipo": tipo,
                "titular": titular, "lugar": lugar, "link": link
            })
    # “Siguiente” (por si después quieres encadenar desde HTML; ahora paginamos por parámetro)
    next_link = None
    return items, next_link

def fetch_items():
    s = get_session()
    all_items = []
    debug_html = []
    for page in range(1, PAGES_TO_SCAN + 1):
        html, mode = fetch_page_variants(s, page)
        debug_html.append((page, mode, html[:2000]))  # guardamos primeros caracteres para diagnóstico
        items, _ = parse_list(html)
        all_items.extend(items)
        time.sleep(REQUEST_PAUSE_SEC)
    # Si no hay items, volcamos un HTML de muestra para inspección en el artifact
    if not all_items:
        os.makedirs("out", exist_ok=True)
        with open("out/debug_sample.html", "w", encoding="utf-8") as f:
            f.write("<!-- MODES -->\n")
            for page, mode, snippet in debug_html:
                f.write(f"\n<!-- page={page} mode={mode} -->\n")
                f.write(snippet)
                f.write("\n")
    return all_items

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
        title = f"{it['folio']} - {it['proyecto']}".strip(" -")
        link = it['link'] or BASE
        desc = f"Titular: {it['titular']} | Tipo: {it['tipo']} | Ubicación: {it['lugar']}"
        guid = hashlib.sha1((it['folio'] + it['proyecto']).encode()).hexdigest()
        pub = to_rfc822(now)
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
    items = fetch_items()
    os.makedirs("out", exist_ok=True)
    with open("out/feed.xml", "w", encoding="utf-8") as f:
        f.write(make_feed(items))
    now = datetime.datetime.now(tz=LOCAL_TZ).isoformat()
    with open("out/data.json", "w", encoding="utf-8") as f:
        json.dump({"generated": now, "count": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    print(f"OK: {len(items)} items.")

if __name__ == "__main__":
    main()
