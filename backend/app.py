# backend/app.py
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import threading, os

app = Flask(__name__)
# CORS amplio: sirve para pruebas; si deseas, ajusta orígenes
CORS(app, resources={r"/*": {"origins": "*"}})

LOCK = threading.Lock()

# ── rutas absolutas y carpeta data junto al app.py
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXCEL_PATH = DATA_DIR / "encuestas_satisfaccion.xlsx"
SHEET = "respuestas"

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

def _ensure_excel():
    if not EXCEL_PATH.exists():
        cols = ["encuesta_id","pregunta_id","pregunta","valor",
                "sugerencia","nombre","contacto","fecha","created_at"]
        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as xw:
            pd.DataFrame(columns=cols).to_excel(xw, index=False, sheet_name=SHEET)

def _read_df():
    _ensure_excel()
    try:
        return pd.read_excel(EXCEL_PATH, sheet_name=SHEET)
    except Exception:
        return pd.DataFrame(columns=["encuesta_id","pregunta_id","pregunta","valor",
                                     "sugerencia","nombre","contacto","fecha","created_at"])

# ──────────────────────────────
# Errores siempre en JSON
# ──────────────────────────────
@app.errorhandler(404)
def not_found(e): 
    return jsonify(ok=False, error="Ruta no encontrada", path=request.path), 404

@app.errorhandler(405)
def not_allowed(e): 
    return jsonify(ok=False, error="Método no permitido", path=request.path), 405

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify(ok=False, error=e.description, code=e.code), e.code
    return jsonify(ok=False, error=str(e)), 500

# ──────────────────────────────
# Helpers de rutas (soportar con/sin /api)
# ──────────────────────────────
def dual_route(rule, **options):
    """
    Registra el mismo endpoint con y sin prefijo /api.
    Ej: @dual_route('/encuesta-satisfaccion/ping')
    crea:
      /encuesta-satisfaccion/ping
      /api/encuesta-satisfaccion/ping
    """
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

@dual_route("/encuesta-satisfaccion/routes", methods=["GET"])
def routes():
    rules = sorted([str(r) for r in app.url_map.iter_rules()])
    return jsonify(ok=True, routes=rules)

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
    created_at = datetime.now(timezone.utc).isoformat()
    encuesta_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

    rows = []
    for r in respuestas:
        pid = int(r.get("pregunta_id", 0))
        val = int(r.get("valor", 0))
        if pid not in PREGUNTAS or val not in [1,2,3,4,5]:
            return jsonify(ok=False, error=f"Entrada inválida (pregunta_id={pid}, valor={val})"), 400
        rows.append({
            "encuesta_id": encuesta_id,
            "pregunta_id": pid,
            "pregunta": PREGUNTAS[pid],
            "valor": val,
            "sugerencia": sugerencia,
            "nombre": nombre,
            "contacto": contacto,
            "fecha": fecha,
            "created_at": created_at
        })

    df_new = pd.DataFrame(rows)
    with LOCK:
        _ensure_excel()
        try:
            df_old = pd.read_excel(EXCEL_PATH, sheet_name=SHEET)
        except Exception:
            df_old = pd.DataFrame(columns=df_new.columns)
        df_out = pd.concat([df_old, df_new], ignore_index=True)
        tmp = EXCEL_PATH.with_suffix(".tmp.xlsx")
        with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
            df_out.to_excel(xw, index=False, sheet_name=SHEET)
        tmp.replace(EXCEL_PATH)

    return jsonify(ok=True, encuesta_id=encuesta_id, guardadas=len(rows), path=request.path)

# ──────────────────────────────
# Stats
# ──────────────────────────────
@dual_route("/encuesta-satisfaccion/stats", methods=["GET"])
def stats():
    df = _read_df()
    if df.empty:
        return jsonify(ok=True, total_respuestas=0, promedios={}, distribuciones={}, sugerencias=[], path=request.path)

    total_encuestas = df["encuesta_id"].nunique()

    prom = (df.groupby("pregunta_id")["valor"].mean().round(2)).to_dict()
    dist = (df.groupby(["pregunta_id","valor"]).size().reset_index(name="conteo"))
    out_dist = {}
    for pid in sorted(PREGUNTAS.keys()):
        sub = dist[dist["pregunta_id"] == pid]
        m = {v: int(sub[sub["valor"]==v]["conteo"].sum()) for v in [1,2,3,4,5]}
        out_dist[str(pid)] = m

    sug = (df[df["sugerencia"].astype(str).str.strip() != ""]
             .drop_duplicates(subset=["encuesta_id","sugerencia","created_at"])
             .sort_values("created_at", ascending=False)
             .head(100)[["sugerencia","nombre","contacto","fecha","created_at"]])
    sugerencias = [{
        "texto": r["sugerencia"],
        "nombre": r.get("nombre", ""),
        "contacto": r.get("contacto", ""),
        "fecha": r.get("fecha", ""),
        "created_at": r.get("created_at", "")
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
# Descargar Excel
# ──────────────────────────────
@dual_route("/encuesta-satisfaccion/excel", methods=["GET"])
def export_excel():
    _ensure_excel()
    return send_file(EXCEL_PATH, as_attachment=True, download_name="encuestas_satisfaccion.xlsx")

def _print_routes():
    print("=== RUTAS FLASK ===")
    for r in sorted(app.url_map.iter_rules(), key=lambda x: str(x)):
        print(f"{list(r.methods)} -> {r}")

if __name__ == "__main__":
    _print_routes()
    # sin reloader para evitar instancias duplicadas
    app.run(host="0.0.0.0", port=6020, debug=True, use_reloader=False)