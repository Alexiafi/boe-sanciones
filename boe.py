import os
import re
import io
import json
import csv
import sqlite3
import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from pdfminer.high_level import extract_text as pdf_extract_text
from lxml import etree

# =========================
# CONFIG
# =========================
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sanciones.db")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

BOE_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{yyyymmdd}"
UA = {"User-Agent": "Mozilla/5.0"}

KEYWORDS = [
    "sanción", "sanciones", "multa", "expediente sancionador",
    "procedimiento sancionador", "resolución sancionadora",
    "infracción", "sancionador"
]

NIF_RE = re.compile(r"\b(\d{8}[A-Z])\b", re.IGNORECASE)
CIF_RE = re.compile(r"\b([ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J])\b", re.IGNORECASE)

# =========================
# UTILS
# =========================
def ddmmyyyy_to_yyyymmdd(s: str) -> str:
    # "04/02/2026" -> "20260204"
    parts = s.strip().split("/")
    if len(parts) != 3:
        raise ValueError("Fecha inválida. Usa dd/mm/yyyy")
    dd, mm, yyyy = parts
    return f"{yyyy}{mm.zfill(2)}{dd.zfill(2)}"

def contains_keywords(text: str) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in KEYWORDS)

def fetch_text(url: str, accept_xml: bool = False) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    if accept_xml:
        headers["Accept"] = "application/xml"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_bytes(url: str) -> bytes:
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.content

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Contenedores típicos
    for sel in ["article", "div#contenido", "main", "div.content", "div#cuerpo", "div#texto"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return " ".join(el.get_text(" ", strip=True).split())
    return " ".join(soup.get_text(" ", strip=True).split())

def xml_to_text(xml: str) -> str:
    soup = BeautifulSoup(xml, "xml")
    return " ".join(soup.get_text(" ", strip=True).split())

def pdf_bytes_to_text(pdf_bytes: bytes) -> str:
    with io.BytesIO(pdf_bytes) as f:
        text = pdf_extract_text(f)
    return " ".join(text.split())

def extract_ids_regex(text: str) -> str:
    nifs = sorted(set(m.group(1).upper() for m in NIF_RE.finditer(text)))
    cifs = sorted(set(m.group(1).upper() for m in CIF_RE.finditer(text)))
    return ", ".join(cifs + nifs)

# =========================
# OPENAI (opcional)
# =========================
def extract_sanctioned_with_ai(text: str) -> str:
    """
    Devuelve EXACTO:
    - 'NOMBRE | ID'
    - o 'NADA'
    """
    if not client:
        return "NADA (NO_API_KEY)"

    text = (text or "")[:6000]  # recorte por coste/tokens
    prompt = (
        "Eres un extractor de datos. Del siguiente texto del BOE, extrae:\n"
        "1) nombre de la persona o empresa sancionada\n"
        "2) DNI/NIF/CIF si aparece\n"
        "Devuelve EXACTAMENTE en formato: NOMBRE | ID\n"
        "Si no hay datos claros, devuelve EXACTAMENTE: NADA\n\n"
        f"TEXTO:\n{text}"
    )

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            timeout=30
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"NADA (OPENAI_ERROR: {e})"

# =========================
# DB
# =========================
def conectar_db(reset: bool = False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if reset:
        cur.execute("DROP TABLE IF EXISTS sanciones")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sanciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            yyyymmdd TEXT,
            organismo TEXT,
            seccion TEXT,
            titulo TEXT,
            texto TEXT,
            sancionado TEXT,
            identificacion TEXT,
            enlace_boe TEXT,
            enlace_pdf TEXT,
            fuente_texto TEXT,
            record_key TEXT UNIQUE
        )
    """)
    conn.commit()
    return conn, cur

def make_record_key(yyyymmdd: str, boe_url: str, titulo: str) -> str:
    # clave estable para dedupe
    return f"{yyyymmdd}|{boe_url}|{titulo}"

# =========================
# PARSEO SUMARIO BOE (API)
# =========================
def parse_sumario(sumario_xml: str):
    """
    Devuelve lista de dicts con:
    - titulo
    - url_html, url_xml, url_pdf
    - organismo (si aparece)
    - seccion (ruta jerárquica aproximada)
    """
    root = etree.fromstring(sumario_xml.encode("utf-8", errors="ignore"))

    items = root.xpath("//item")
    out = []

    for it in items:
        titulo = it.xpath("string(./titulo)").strip()
        if not titulo:
            continue

        url_html = it.xpath("string(./urlHtml)").strip() or ""
        url_xml = it.xpath("string(./urlXml)").strip() or ""
        url_pdf = it.xpath("string(./urlPdf)").strip() or ""

        organismo = it.xpath("string(./departamento)").strip()
        if not organismo:
            organismo = it.xpath("string(./organismo)").strip()

        # Construye una "sección" aproximada con ancestros que tengan <titulo>
        section_parts = []
        for anc in it.iterancestors():
            t = anc.xpath("string(./titulo)").strip()
            if t:
                section_parts.append(t)
        section_parts = list(reversed(section_parts))
        seccion = " > ".join(section_parts[:4])  # limitamos longitud

        out.append({
            "titulo": titulo,
            "url_html": url_html,
            "url_xml": url_xml,
            "url_pdf": url_pdf,
            "organismo": organismo,
            "seccion": seccion
        })

    return out

def get_best_text_and_source(entry: dict):
    """
    Preferencia: HTML -> XML -> PDF
    Devuelve (texto, fuente, pdf_url)
    """
    # HTML
    if entry["url_html"]:
        try:
            html = fetch_text(entry["url_html"])
            return html_to_text(html), "html", entry["url_pdf"] or ""
        except Exception:
            pass

    # XML
    if entry["url_xml"]:
        try:
            xml = fetch_text(entry["url_xml"])
            return xml_to_text(xml), "xml", entry["url_pdf"] or ""
        except Exception:
            pass

    # PDF
    if entry["url_pdf"]:
        try:
            pdf_bytes = fetch_bytes(entry["url_pdf"])
            return pdf_bytes_to_text(pdf_bytes), "pdf", entry["url_pdf"]
        except Exception:
            pass

    return "", "none", entry["url_pdf"] or ""

# =========================
# EXPORT
# =========================
def export_daily(conn: sqlite3.Connection, yyyymmdd: str):
    df = pd.read_sql_query(
        "SELECT yyyymmdd, organismo, seccion, titulo, sancionado, identificacion, enlace_boe, enlace_pdf, fuente_texto "
        "FROM sanciones WHERE yyyymmdd = ? ORDER BY id DESC",
        conn,
        params=(yyyymmdd,)
    )

    csv_path = os.path.join(EXPORT_DIR, f"sanciones_{yyyymmdd}.csv")
    json_path = os.path.join(EXPORT_DIR, f"sanciones_{yyyymmdd}.json")

    df.to_csv(csv_path, index=False)

    records = df.to_dict(orient="records")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return csv_path, json_path, len(df)

# =========================
# PIPELINE PRINCIPAL
# =========================
def run_pipeline(ddmmyyyy: str, reset_db: bool = False, use_ai: bool = True, max_items: int = 300):
    yyyymmdd = ddmmyyyy_to_yyyymmdd(ddmmyyyy)

    conn, cur = conectar_db(reset=reset_db)

    sumario_url = BOE_SUMARIO_URL.format(yyyymmdd=yyyymmdd)
    st.write("📡 Sumario API:", sumario_url)

    sumario_xml = fetch_text(sumario_url, accept_xml=True)
    st.write("🧾 XML recibido (primeros 200 chars):", sumario_xml[:200])

    entries = parse_sumario(sumario_xml)

    st.write(f"📄 Items en sumario: {len(entries)}")
    st.write("🧾 Primeros 20 títulos del BOE:")
    for e in entries[:20]:
        st.write("-", e["titulo"])


    scanned = 0
    candidates = 0
    inserted = 0

    for e in entries[:max_items]:
        scanned += 1

        # descargamos texto SIEMPRE (hasta un límite razonable)
        text, source, pdf_url = get_best_text_and_source(e)

        if not text:
            continue

        # ahora sí, filtramos por keywords en el TEXTO
        if not contains_keywords(text):
            continue
        candidates += 1

        # texto completo
        text, source, pdf_url = get_best_text_and_source(e)

        # confirmación por texto completo
        if text and not contains_keywords(text):
            # si el título tenía keyword pero el texto no, lo descartamos
            continue

        boe_url = e["url_html"] or e["url_xml"] or ""
        if not boe_url:
            continue

        # IDs por regex
        id_guess = extract_ids_regex(text)

        # IA (opcional)
        sancionado = ""
        identificacion = id_guess

        ai_result = "NADA"
        if use_ai and text:
            ai_result = extract_sanctioned_with_ai(text)

        if not ai_result.startswith("NADA") and "|" in ai_result:
            sancionado, ident = ai_result.split("|", 1)
            sancionado = sancionado.strip()
            ident = ident.strip()
            if ident and not ident.upper().startswith("NADA"):
                identificacion = ident

        # Si no hay sancionado ni IDs, aun así podrías guardar por título (pero suele meter ruido).
        # Para MVP, exigimos al menos alguna señal:
        if not sancionado and not identificacion:
            continue

        record_key = make_record_key(yyyymmdd, boe_url, e["titulo"])

        try:
            cur.execute("""
                INSERT OR IGNORE INTO sanciones
                (yyyymmdd, organismo, seccion, titulo, texto, sancionado, identificacion,
                 enlace_boe, enlace_pdf, fuente_texto, record_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                yyyymmdd,
                e["organismo"] or "",
                e["seccion"] or "",
                e["titulo"],
                (text or "")[:4000],
                sancionado,
                identificacion,
                boe_url,
                pdf_url or e["url_pdf"] or "",
                source,
                record_key
            ))
            if cur.rowcount == 1:
                inserted += 1
        except Exception as ex:
            st.write("⚠️ Error insert:", ex)

    conn.commit()

    csv_path, json_path, n = export_daily(conn, yyyymmdd)

    st.write(f"✅ scanned={scanned} candidates={candidates} inserted_new={inserted}")
    st.write("📁 CSV:", csv_path)
    st.write("📁 JSON:", json_path)

    return conn, yyyymmdd

# =========================
# STREAMLIT UI
# =========================
st.set_page_config(page_title="BOE Sanciones (API)", layout="wide")
st.title("📌 Extracción de sanciones desde BOE (API oficial)")

st.sidebar.write("📍 BD:")
st.sidebar.code(DB_PATH)

fecha = st.sidebar.text_input("Fecha (dd/mm/yyyy)", value="04/02/2026")
reset_db = st.sidebar.checkbox("Reset BD (borrar y recrear)", value=True)
use_ai = st.sidebar.checkbox("Usar OpenAI para extraer sancionado", value=True)
max_items = st.sidebar.slider("Máximo items del sumario a revisar", 50, 1000, 300, 50)

if st.sidebar.button("🚀 INICIAR"):
    with st.spinner("Ejecutando pipeline…"):
        try:
            conn, yyyymmdd = run_pipeline(fecha, reset_db=reset_db, use_ai=use_ai, max_items=max_items)
            # Mostrar resultados
            df = pd.read_sql_query(
                "SELECT yyyymmdd, organismo, seccion, titulo, sancionado, identificacion, enlace_boe, enlace_pdf, fuente_texto "
                "FROM sanciones WHERE yyyymmdd = ? ORDER BY id DESC LIMIT 500",
                conn,
                params=(yyyymmdd,)
            )
            conn.close()

            if df.empty:
                st.warning("0 resultados: puede que ese día no haya sanciones con esas keywords, o las keywords no coinciden.")
            else:
                st.success(f"Resultados: {len(df)}")
                st.dataframe(df, use_container_width=True)

        except Exception as e:
            st.error(f"Error: {e}")

# Mostrar últimos 200 de la BD (sin filtrar por día) para ver que persiste
try:
    conn2 = sqlite3.connect(DB_PATH)
    df2 = pd.read_sql_query(
        "SELECT yyyymmdd, titulo, sancionado, identificacion FROM sanciones ORDER BY id DESC LIMIT 200",
        conn2
    )
    conn2.close()
    if not df2.empty:
        st.subheader("Últimos registros guardados")
        st.dataframe(df2, use_container_width=True)
except Exception:
    pass
