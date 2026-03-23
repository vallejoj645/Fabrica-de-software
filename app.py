"""
CodeForge Studio · Backend API
Servidor Flask con SQLite para registro de clientes potenciales.
Listo para Railway (con soporte correcto de archivos estáticos)
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import re
from datetime import datetime
from functools import wraps

# ── CONFIGURACIÓN ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
CORS(app)

DB_PATH = os.path.join(BASE_DIR, "codeforge.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "cambia_esta_clave")


# ── BASE DE DATOS ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT    NOT NULL,
            empresa     TEXT,
            email       TEXT    NOT NULL,
            telefono    TEXT    NOT NULL,
            servicio    TEXT    NOT NULL,
            presupuesto TEXT,
            mensaje     TEXT    NOT NULL,
            estado      TEXT    DEFAULT 'nuevo',
            ip_origen   TEXT,
            creado_en   TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS actividad_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            accion      TEXT    NOT NULL,
            lead_id     INTEGER,
            detalle     TEXT,
            creado_en   TEXT    NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada correctamente.")


# Se ejecuta al iniciar
init_db()


# ── UTILIDADES ─────────────────────────────────────────────────
def validar_email(email: str) -> bool:
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron, email))


def validar_telefono(tel: str) -> bool:
    limpio = re.sub(r'[\s\-\(\)\+]', '', tel)
    return 7 <= len(limpio) <= 15 and limpio.isdigit()


def log_actividad(accion: str, lead_id: int = None, detalle: str = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO actividad_log (accion, lead_id, detalle, creado_en) VALUES (?,?,?,?)",
        (accion, lead_id, detalle, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def requiere_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
            return jsonify({"error": "Acceso no autorizado"}), 401
        return f(*args, **kwargs)
    return decorated


# ── RUTAS FRONTEND ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


# 🔥 RUTA DINÁMICA CORREGIDA (SOLUCIÓN CLAVE)
@app.route("/<path:filename>")
def static_files(filename):
    file_path = os.path.join(BASE_DIR, filename)

    print("🔍 Buscando:", file_path)

    if os.path.isfile(file_path):
        return send_from_directory(BASE_DIR, filename)
    else:
        print("❌ No existe:", file_path)
        return "Archivo no encontrado", 404


# ── API: REGISTRO DE LEAD ──────────────────────────────────────
@app.route("/api/registro", methods=["POST"])
def registrar_lead():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400

    campos_requeridos = ["nombre", "email", "telefono", "servicio", "mensaje"]
    for campo in campos_requeridos:
        if not data.get(campo, "").strip():
            return jsonify({"error": f"El campo '{campo}' es requerido"}), 422

    if not validar_email(data["email"]):
        return jsonify({"error": "Correo inválido"}), 422

    if not validar_telefono(data["telefono"]):
        return jsonify({"error": "Teléfono inválido"}), 422

    nombre      = data["nombre"].strip()[:120]
    empresa     = data.get("empresa", "").strip()[:120]
    email       = data["email"].strip().lower()[:200]
    telefono    = data["telefono"].strip()[:30]
    servicio    = data["servicio"].strip()[:60]
    presupuesto = data.get("presupuesto", "").strip()[:60]
    mensaje     = data["mensaje"].strip()[:2000]
    ip_origen   = request.remote_addr

    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO leads
              (nombre, empresa, email, telefono, servicio, presupuesto, mensaje, ip_origen, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (nombre, empresa, email, telefono, servicio, presupuesto, mensaje, ip_origen,
              datetime.now().isoformat()))
        lead_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error as e:
        print(f"❌ Error DB: {e}")
        return jsonify({"error": "Error interno"}), 500
    finally:
        conn.close()

    log_actividad("nuevo_lead", lead_id)
    return jsonify({"ok": True, "lead_id": lead_id}), 201


# ── API: LISTAR LEADS ──────────────────────────────────────────
@app.route("/api/leads", methods=["GET"])
@requiere_auth
def listar_leads():
    conn = get_db()
    rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ── API: ACTUALIZAR ESTADO ─────────────────────────────────────
@app.route("/api/leads/<int:lead_id>/estado", methods=["PATCH"])
@requiere_auth
def actualizar_estado(lead_id):
    data = request.get_json(silent=True) or {}
    estados_validos = {"nuevo", "contactado", "en_proceso", "cerrado", "descartado"}
    nuevo_estado = data.get("estado", "").strip()

    if nuevo_estado not in estados_validos:
        return jsonify({"error": "Estado inválido"}), 422

    conn = get_db()
    result = conn.execute(
        "UPDATE leads SET estado=? WHERE id=?", (nuevo_estado, lead_id)
    )
    conn.commit()
    conn.close()

    if result.rowcount == 0:
        return jsonify({"error": "No encontrado"}), 404

    log_actividad("estado_actualizado", lead_id)
    return jsonify({"ok": True})


# ── API: ESTADÍSTICAS ──────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
@requiere_auth
def estadisticas():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    conn.close()

    return jsonify({"total": total})


# ── HEALTH CHECK ───────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route('/<path:filename>')
def serve_static_files(filename):
    return send_from_directory('.', filename)
# ── SERVIDOR ───────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Servidor en puerto {port}")
    app.run(host="0.0.0.0", port=port)
