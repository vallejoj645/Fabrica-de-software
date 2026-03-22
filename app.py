"""
CodeForge Studio · Backend API
================================
Servidor Flask con SQLite para registro de clientes potenciales.

Instalación:
    pip install flask flask-cors

Ejecución:
    python app.py

La app estará disponible en: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import re
from datetime import datetime

# ── CONFIGURACIÓN ──────────────────────────────────────────────
app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)  # Permitir peticiones desde cualquier origen

ADMIN_USER = "admin"
ADMIN_PASS = "123456"

DB_PATH = "cocode+.db"


# ── BASE DE DATOS ───────────────────────────────────────────────
def get_db():
    """Retorna una conexión a la base de datos SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Resultados como diccionarios
    return conn


def init_db():
    """Crea las tablas si no existen."""
    conn = get_db()
    cursor = conn.cursor()

    # Tabla principal: clientes potenciales (leads)
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

    # Índice para búsquedas rápidas por email
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)
    """)

    # Tabla de log de actividad (auditoría)
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
    print("Base de datos inicializada correctamente.")


# ── UTILIDADES ──────────────────────────────────────────────────
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


# ── RUTAS FRONTEND ─────────────────────────────────────────────
@app.route("/")
def index():
    """Sirve el archivo HTML principal."""
    return send_from_directory(".", "index.html")


# ── API: REGISTRO DE LEAD ───────────────────────────────────────
@app.route("/api/registro", methods=["POST"])
def registrar_lead():
    """
    Registra un cliente potencial en la base de datos.
    Espera un JSON con: nombre, empresa, email, telefono, servicio, presupuesto, mensaje
    """
    data = request.get_json(silent=True)

    # ── Validación de datos ──
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400

    campos_requeridos = ["nombre", "email", "telefono", "servicio", "mensaje"]
    for campo in campos_requeridos:
        if not data.get(campo, "").strip():
            return jsonify({"error": f"El campo '{campo}' es requerido"}), 422

    if not validar_email(data["email"]):
        return jsonify({"error": "El correo electrónico no tiene un formato válido"}), 422

    if not validar_telefono(data["telefono"]):
        return jsonify({"error": "El número de teléfono no es válido"}), 422

    # ── Sanitizar datos ──
    nombre      = data["nombre"].strip()[:120]
    empresa     = data.get("empresa", "").strip()[:120]
    email       = data["email"].strip().lower()[:200]
    telefono    = data["telefono"].strip()[:30]
    servicio    = data["servicio"].strip()[:60]
    presupuesto = data.get("presupuesto", "").strip()[:60]
    mensaje     = data["mensaje"].strip()[:2000]
    ip_origen   = request.remote_addr

    # ── Insertar en la base de datos ──
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
        conn.close()
        print(f"❌ Error de base de datos: {e}")
        return jsonify({"error": "Error interno al guardar el registro"}), 500
    finally:
        conn.close()

    # ── Log de auditoría ──
    log_actividad("nuevo_lead", lead_id, f"Servicio: {servicio} | Email: {email}")
    print(f"✅ Nuevo lead registrado: [{lead_id}] {nombre} <{email}> — {servicio}")

    return jsonify({
        "ok": True,
        "mensaje": "¡Registro exitoso! Te contactaremos pronto.",
        "lead_id": lead_id
    }), 201


# ── API: LISTAR LEADS (panel admin) ────────────────────────────
@app.route("/api/leads", methods=["GET"])
def listar_leads():
    """
    Lista todos los clientes registrados.
    Parámetros opcionales: ?estado=nuevo&limite=50&pagina=1
    """
    estado = request.args.get("estado")
    limite = min(int(request.args.get("limite", 50)), 200)
    pagina = max(int(request.args.get("pagina", 1)), 1)
    offset = (pagina - 1) * limite

    conn = get_db()
    if estado:
        rows = conn.execute(
            "SELECT * FROM leads WHERE estado=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (estado, limite, offset)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE estado=?", (estado,)
        ).fetchone()[0]
    else:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ? OFFSET ?",
            (limite, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    conn.close()

    return jsonify({
        "leads": [dict(r) for r in rows],
        "total": total,
        "pagina": pagina,
        "paginas": (total + limite - 1) // limite
    })


# ── API: ACTUALIZAR ESTADO DE LEAD ─────────────────────────────
@app.route("/api/leads/<int:lead_id>/estado", methods=["PATCH"])
def actualizar_estado(lead_id: int):
    """
    Actualiza el estado de un lead.
    Estados posibles: nuevo | contactado | en_proceso | cerrado | descartado
    """
    data = request.get_json(silent=True) or {}
    estados_validos = {"nuevo", "contactado", "en_proceso", "cerrado", "descartado"}
    nuevo_estado = data.get("estado", "").strip()

    if nuevo_estado not in estados_validos:
        return jsonify({"error": f"Estado inválido. Opciones: {', '.join(estados_validos)}"}), 422

    conn = get_db()
    result = conn.execute(
        "UPDATE leads SET estado=? WHERE id=?", (nuevo_estado, lead_id)
    )
    conn.commit()
    conn.close()

    if result.rowcount == 0:
        return jsonify({"error": "Lead no encontrado"}), 404

    log_actividad("estado_actualizado", lead_id, f"Nuevo estado: {nuevo_estado}")
    return jsonify({"ok": True, "estado": nuevo_estado})


# ── API: ESTADÍSTICAS ───────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def estadisticas():
    """Retorna estadísticas generales del CRM."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    por_estado = conn.execute(
        "SELECT estado, COUNT(*) as cantidad FROM leads GROUP BY estado"
    ).fetchall()
    por_servicio = conn.execute(
        "SELECT servicio, COUNT(*) as cantidad FROM leads GROUP BY servicio ORDER BY cantidad DESC"
    ).fetchall()
    ultimos_7_dias = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE creado_en >= datetime('now', '-7 days')"
    ).fetchone()[0]
    conn.close()

    return jsonify({
        "total_leads": total,
        "ultimos_7_dias": ultimos_7_dias,
        "por_estado": [dict(r) for r in por_estado],
        "por_servicio": [dict(r) for r in por_servicio],
    })


# ── HEALTH CHECK ────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


# ── INICIAR SERVIDOR ────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("""
╔══════════════════════════════════════╗
║   CodeForge Studio · Backend API     ║
╠══════════════════════════════════════╣
║  http://localhost:5000               ║
║  Base de datos: codeforge.db         ║
╚══════════════════════════════════════╝
    """)
    app.run(debug=True, host="0.0.0.0", port=5000)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
