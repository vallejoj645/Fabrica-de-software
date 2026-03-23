"""
CodeForge Studio · Backend API
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

# ⚠️ static_folder=None desactiva el manejador interno de Flask
# para que no entre en conflicto con nuestra ruta /<path:filename>
app = Flask(__name__, static_folder=None)
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)")
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


init_db()


# ── UTILIDADES ─────────────────────────────────────────────────
def validar_email(email: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))


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


# ── API ────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


@app.route("/api/registro", methods=["POST"])
def registrar_lead():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400

    for campo in ["nombre", "email", "telefono", "servicio", "mensaje"]:
        if not data.get(campo, "").strip():
            return jsonify({"error": f"El campo '{campo}' es requerido"}), 422

    if not validar_email(data["email"]):
        return jsonify({"error": "Correo inválido"}), 422
    if not validar_telefono(data["telefono"]):
        return jsonify({"error": "Teléfono inválido"}), 422

    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO leads
              (nombre, empresa, email, telefono, servicio, presupuesto, mensaje, ip_origen, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["nombre"].strip()[:120],
            data.get("empresa", "").strip()[:120],
            data["email"].strip().lower()[:200],
            data["telefono"].strip()[:30],
            data["servicio"].strip()[:60],
            data.get("presupuesto", "").strip()[:60],
            data["mensaje"].strip()[:2000],
            request.remote_addr,
            datetime.now().isoformat()
        ))
        lead_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error as e:
        print(f"❌ Error DB: {e}")
        return jsonify({"error": "Error interno"}), 500
    finally:
        conn.close()

    log_actividad("nuevo_lead", lead_id)
    return jsonify({"ok": True, "lead_id": lead_id}), 201


@app.route("/api/leads")
@requiere_auth
def listar_leads():
    conn = get_db()
    rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/leads/<int:lead_id>/estado", methods=["PATCH"])
@requiere_auth
def actualizar_estado(lead_id):
    data = request.get_json(silent=True) or {}
    nuevo_estado = data.get("estado", "").strip()
    if nuevo_estado not in {"nuevo", "contactado", "en_proceso", "cerrado", "descartado"}:
        return jsonify({"error": "Estado inválido"}), 422

    conn = get_db()
    result = conn.execute("UPDATE leads SET estado=? WHERE id=?", (nuevo_estado, lead_id))
    conn.commit()
    conn.close()

    if result.rowcount == 0:
        return jsonify({"error": "No encontrado"}), 404
    log_actividad("estado_actualizado", lead_id)
    return jsonify({"ok": True})


@app.route("/api/stats")
@requiere_auth
def estadisticas():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    por_estado = conn.execute(
        "SELECT estado, COUNT(*) as cantidad FROM leads GROUP BY estado"
    ).fetchall()
    conn.close()
    return jsonify({"total": total, "por_estado": [dict(r) for r in por_estado]})


# ── FRONTEND ───────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    file_path = os.path.join(BASE_DIR, filename)
    print(f"🔍 Solicitado: {filename} → {file_path}")
    if os.path.isfile(file_path):
        print(f"✅ Encontrado: {file_path}")
        return send_from_directory(BASE_DIR, filename)
    print(f"❌ No existe: {file_path}")
    return jsonify({"error": f"No encontrado: {filename}"}), 404


# ── SERVIDOR LOCAL ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 http://localhost:{port}  |  BASE_DIR: {BASE_DIR}")
    app.run(host="0.0.0.0", port=port)
