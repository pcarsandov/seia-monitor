#!/usr/bin/env python3
# seia_feed.py — versión POST + mapeo por encabezados
import requests, time, hashlib, json, datetime, re
from bs4 import BeautifulSoup
from xml.sax.saxutils import escape
from dateutil import tz

BASE = "https://seia.sea.gob.cl/busqueda/buscarProyectoResumen.php"
DOMAIN = "https://seia.sea.gob.cl"
LOCAL_TZ = tz.gettz("America/Santiago")
USER_AGENT = "Mozilla/5.0 (compatible; SEIA-monitor/1.1; +https://github.com/)"
PAGES_TO_SCAN = 2  # si aparecen muchos ingresos por día, sube a 3-4

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
    # Primer GET para cookies y posibles tokens (si los hubiese)
    s.get(BASE, timeout=30)
    return s

def post_list_page(session: requests.Session, page: int = 1) -> str:
    """
    Emula el envío básico del formulario de resumen, ordenando por más recientes.
    Si el sitio cambia los nombres de campos, habrá que ajustar el payload.
    """
    payload = {
        # Muchos formularios PHP usan un botón 'buscar' o similar; esto es genérico:
        "accion": "buscar",
        # Paginación (nombres típicos; si cambia, ajusta)
        "pagina": str(page),
        # Orden más reciente → más antiguo (nombres típicos; si cambia, ajusta)
        "orden": "fecha_ingreso",
        "dir": "desc",
        # Si el formulario exige campos vacíos para 'todos', dejamos strings vacíos:
        "tipo": "", "region": "", "comuna": "", "titular": "", "proyecto": ""
    }
    r = session.post(BASE, data=payload, timeout=30)
    r.raise_for_status()
    return r.text

def guess_table_and_columns(soup: BeautifulSoup):
    """
    Busca una tabla con encabezados que contengan textos clave y
    devuelve (tabla, dict_mapa_columnas).
    """
    wanted = {
        "folio": ["folio", "id"],
        "proyecto": ["proyecto", "nombre"],
        "tipo": ["tipo", "instrumento", "dia", "eia"],
        "titular": ["titular"],
        "lugar": ["comuna", "región", "region", "ubicación"]
    }
    tables = soup.find_all("table")
    for tbl in tables:
        thead = tbl.find("thead")
        if not thead:
            continue
        ths = [th.get_text(" ", strip=True).lower() for th in thead.find_all("th")]
        if not ths or len(ths) < 4:
            continue
        # mapeo por keywords
        idx = {}
        for i, label in enumerate(ths):
            for key, keys in wanted.items():
                if any(k in label for k in keys):
                    idx.setdefault(key, i)
        # necesitamos al menos folio y proyecto
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

        # link al expediente: intenta cualquier <a> de la fila
        a = tr.find("a", href=True)
        link = absolutize(a["href"]) if a else BASE

        # Filtra filas vacías
        if not proyecto and not titular:
            continue

        items.append({
            "folio": folio, "proyecto": proyecto, "tipo": tipo,
            "titular": titular, "lugar": lugar, "link": link
        })
    return items

def fetch_items():
    s = get_session()
    all_items = []
    for page in range(1, PAGES_TO_SCAN + 1):
        html = post_list_page(s, page=page)
        soup = BeautifulSoup(html, "html.parser")
        tbl, idx = guess_table_and_columns(soup)
        if not tbl:
            # Fallback muy básico: intentar filas sin encabezado
            rows = soup.select("table tbody tr")
            if not rows:
                continue
            # Asumimos orden de columnas clásico
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
                all_items.append({
                    "folio": folio, "proyecto": proyecto, "tipo": tipo,
                    "titular": titular, "lugar": lugar, "link": link
                })
        else:
            all_items.extend(parse_rows_from_table(tbl, idx))
        time.sleep(1.2)  # amable con el servidor
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
    # Salidas
    import os
    os.makedirs("out", exist_ok=True)
    with open("out/feed.xml", "w", encoding="utf-8") as f:
        f.write(make_feed(items))
    now = datetime.datetime.now(tz=LOCAL_TZ).isoformat()
    with open("out/data.json", "w", encoding="utf-8") as f:
        json.dump({"generated": now, "count": len(items), "items": items},
                  f, ensure_ascii=False, indent=2)
    print(f"OK: {len(items)} items.")

if __name__ == "__main__":
    main()
