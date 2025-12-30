# backend/app.py
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import threading, os
import pyodbc # Nuevo: Conector SQL Server
import json

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

LOCK = threading.Lock()

# ===================== CONFIGURACIÓN SQL SERVER =====================
SQL_CONN_STR = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=DESKTOP-EO74OCH\\SQLEXPRESS;"
    "Database=punta_medica;"
    "Trusted_Connection=yes;"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)

def get_db_connection():
    return pyodbc.connect(SQL_CONN_STR)

# ===================== INICIALIZACIÓN DE TABLA SQL =====================
def init_db_satisfaccion():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Creamos una tabla que soporte el desglose por pregunta para facilitar estadísticas
    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='EncuestaSatisfaccionPacientes' AND xtype='U')
        CREATE TABLE EncuestaSatisfaccionPacientes (
            ID INT IDENTITY(1,1) PRIMARY KEY,
            Encuesta_ID VARCHAR(50),
            Pregunta_ID INT,
            Pregunta_Texto VARCHAR(MAX),
            Valor INT,
            Sugerencia VARCHAR(MAX),
            Nombre VARCHAR(255),
            Contacto VARCHAR(255),
            Fecha_Encuesta VARCHAR(100),
            Created_At DATETIME DEFAULT GETDATE()
        )
    ''')
    conn.commit()
    conn.close()

init_db_satisfaccion()

# --- CONFIGURACIÓN ORIGINAL EXCEL (COMENTADA) ---
# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data"
# DATA_DIR.mkdir(parents=True, exist_ok=True)
# EXCEL_PATH = DATA_DIR / "encuestas_satisfaccion.xlsx"
# SHEET = "respuestas"

PREGUNTAS = {
    1: "La atención en Admisión fue rápida, eficiente y claras sus dudas.",
    2: "Información administrativa transparente y precisa.",
    3: "Información suficiente antes del Consentimiento (incluye hospitalización).",
    4: "Habitación y áreas cómodas, limpias y armónicas.",
    5: "Señalización clara.",
    6: "Instalaciones cómodas y accesibles.",
    7: "Alimentos satisfactorios.",
    8: "Trato respetuoso y compasivo.",
    9: "Respeto a su privacidad.",
    10: "Respeto a costumbres, creencias y cultura.",
    11: "Información clara del médico/equipo.",
    12: "Atención a dolor y otras molestias.",
    13: "Atención segura y de calidad.",
}

# --- HELPERS ORIGINALES EXCEL (COMENTADOS) ---
# def _ensure_excel(): ...
# def _read_df(): ...

# ──────────────────────────────
# Errores siempre en JSON
# ──────────────────────────────
@app.errorhandler(404)
def not_found(e): 
    return jsonify(ok=False, error="Ruta no encontrada", path=request.path), 404

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify(ok=False, error=e.description, code=e.code), e.code
    return jsonify(ok=False, error=str(e)), 500

def dual_route(rule, **options):
    def decorator(f):
        app.add_url_rule(rule, endpoint=f.__name__ + rule, view_func=f, **options)
        api_rule = "/api" + (rule if rule.startswith("/") else "/" + rule)
        app.add_url_rule(api_rule, endpoint=f.__name__ + api_rule, view_func=f, **options)
        return f
    return decorator

# ──────────────────────────────
# Health / Rutas
# ──────────────────────────────
@dual_route("/encuesta-satisfaccion/ping", methods=["GET"])
def ping():
    return jsonify(ok=True, ts=datetime.now(timezone.utc).isoformat(), path=request.path)

# ──────────────────────────────
# Guardar encuesta
# ──────────────────────────────
@dual_route("/encuesta-satisfaccion", methods=["POST"])
def guardar_encuesta():
    payload = request.get_json(silent=True) or {}
    respuestas = payload.get("respuestas") or []
    if not isinstance(respuestas, list) or not respuestas:
        return jsonify(ok=False, error="Respuestas vacías"), 400

    sugerencia = (payload.get("sugerencia") or "").strip()
    nombre = (payload.get("nombre") or "").strip()
    contacto = (payload.get("contacto") or "").strip()
    fecha = (payload.get("fecha") or "").strip()
    encuesta_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

    # --- LÓGICA SQL SERVER ---
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for r in respuestas:
            pid = int(r.get("pregunta_id", 0))
            val = int(r.get("valor", 0))
            if pid not in PREGUNTAS or val not in [1,2,3,4,5]:
                return jsonify(ok=False, error=f"Entrada inválida (pid={pid}, val={val})"), 400
            
            cursor.execute("""
                INSERT INTO EncuestaSatisfaccionPacientes 
                (Encuesta_ID, Pregunta_ID, Pregunta_Texto, Valor, Sugerencia, Nombre, Contacto, Fecha_Encuesta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (encuesta_id, pid, PREGUNTAS[pid], val, sugerencia, nombre, contacto, fecha))
        
        conn.commit()
        conn.close()

        # --- LÓGICA ORIGINAL EXCEL (COMENTADA) ---
        # rows.append({...})
        # with LOCK: ... (guardado en excel_path)

        return jsonify(ok=True, encuesta_id=encuesta_id, guardadas=len(respuestas), path=request.path)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# ──────────────────────────────
# Stats
# ──────────────────────────────
@dual_route("/encuesta-satisfaccion/stats", methods=["GET"])
def stats():
    # --- NUEVA LÓGICA SQL SERVER ---
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM EncuestaSatisfaccionPacientes", conn)
    conn.close()

    # --- LÓGICA ORIGINAL EXCEL (REEMPLAZADA POR DF DE SQL) ---
    # df = _read_df()

    if df.empty:
        return jsonify(ok=True, total_respuestas=0, promedios={}, distribuciones={}, sugerencias=[], path=request.path)

    total_encuestas = df["Encuesta_ID"].nunique()

    # Adaptación de nombres de columnas de SQL para mantener la lógica de pandas
    prom = (df.groupby("Pregunta_ID")["Valor"].mean().round(2)).to_dict()
    dist = (df.groupby(["Pregunta_ID","Valor"]).size().reset_index(name="conteo"))
    
    out_dist = {}
    for pid in sorted(PREGUNTAS.keys()):
        sub = dist[dist["Pregunta_ID"] == pid]
        m = {v: int(sub[sub["Valor"]==v]["conteo"].sum()) for v in [1,2,3,4,5]}
        out_dist[str(pid)] = m

    sug = (df[df["Sugerencia"].astype(str).str.strip() != ""]
             .drop_duplicates(subset=["Encuesta_ID","Sugerencia","Created_At"])
             .sort_values("Created_At", ascending=False)
             .head(100))
    
    sugerencias = [{
        "texto": r["Sugerencia"],
        "nombre": r.get("Nombre", ""),
        "contacto": r.get("Contacto", ""),
        "fecha": r.get("Fecha_Encuesta", ""),
        "created_at": r.get("Created_At").isoformat() if hasattr(r.get("Created_At"), 'isoformat') else str(r.get("Created_At"))
    } for _, r in sug.iterrows()]

    return jsonify(
        ok=True,
        total_respuestas=int(total_encuestas),
        promedios={str(k): float(prom.get(k, 0.0)) for k in PREGUNTAS.keys()},
        distribuciones=out_dist,
        sugerencias=sugerencias,
        path=request.path
    )

# ──────────────────────────────
# Descargar Excel (Ahora generado desde SQL)
# ──────────────────────────────
@dual_route("/encuesta-satisfaccion/excel", methods=["GET"])
def export_excel():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM EncuestaSatisfaccionPacientes", conn)
    conn.close()
    
    output_path = "export_satisfaccion.xlsx"
    df.to_excel(output_path, index=False)
    return send_file(output_path, as_attachment=True, download_name="encuestas_satisfaccion.xlsx")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6020, debug=True, use_reloader=False)