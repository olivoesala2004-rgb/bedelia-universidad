"""
Bedelía U - Servidor Flask + SQLite
Ejecutar:  python app.py   ->   http://localhost:5000
La base de datos se crea sola en bedelia.db (con datos de ejemplo la primera vez).
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request

BASE = Path(__file__).parent
DB_PATH = BASE / "bedelia.db"

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")

SCHEMA = """
CREATE TABLE IF NOT EXISTS profesores (
    cc      TEXT PRIMARY KEY,
    nombre  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipos (
    codigo  TEXT PRIMARY KEY,
    tipo    TEXT NOT NULL CHECK (tipo IN ('Video-beam', 'Laptop')),
    modelo  TEXT NOT NULL,
    estado  TEXT NOT NULL DEFAULT 'Disponible'
            CHECK (estado IN ('Disponible', 'Prestado'))
);

CREATE TABLE IF NOT EXISTS prestamos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cc             TEXT NOT NULL REFERENCES profesores(cc) ON DELETE RESTRICT,
    codigo_equipo  TEXT NOT NULL REFERENCES equipos(codigo) ON DELETE CASCADE,
    hora_salida    TEXT NOT NULL,
    estado         TEXT NOT NULL DEFAULT 'Activo'
);

CREATE TABLE IF NOT EXISTS historial (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha        TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    descripcion  TEXT NOT NULL,
    color        TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- utilidades
def now_iso(delta=timedelta(0)):
    t = datetime.now(timezone.utc) - delta
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def log(db, tipo, descripcion, color):
    db.execute(
        "INSERT INTO historial (fecha, tipo, descripcion, color) VALUES (?, ?, ?, ?)",
        (now_iso(), tipo, descripcion, color),
    )


def error(msg, code=400):
    return jsonify(error=msg), code


def body():
    return request.get_json(silent=True) or {}


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    vacia = db.execute("SELECT COUNT(*) FROM profesores").fetchone()[0] == 0 \
        and db.execute("SELECT COUNT(*) FROM equipos").fetchone()[0] == 0
    if vacia:
        db.executemany("INSERT INTO profesores (cc, nombre) VALUES (?, ?)", [
            ("1098765432", "Dr. Carlos Mendoza"),
            ("1023456789", "Dra. Ana María Gómez"),
            ("1045678912", "Ing. Luis Fernando Ruiz"),
        ])
        db.executemany("INSERT INTO equipos (codigo, tipo, modelo, estado) VALUES (?, ?, ?, ?)", [
            ("VB-01", "Video-beam", "Epson PowerLite X49", "Disponible"),
            ("VB-02", "Video-beam", "Sony VPL-EX435", "Prestado"),
            ("PC-01", "Laptop", "Dell Latitude 3420", "Disponible"),
            ("PC-02", "Laptop", "Lenovo ThinkPad E14", "Prestado"),
        ])
        db.executemany("INSERT INTO prestamos (cc, codigo_equipo, hora_salida) VALUES (?, ?, ?)", [
            ("1098765432", "VB-02", now_iso(timedelta(hours=2))),
            ("1023456789", "PC-02", now_iso(timedelta(hours=1))),
        ])
        db.executemany("INSERT INTO historial (fecha, tipo, descripcion, color) VALUES (?, ?, ?, ?)", [
            (now_iso(timedelta(days=1, hours=4)), "PROFESOR", "Se registró nuevo profesor Dr. Carlos Mendoza", "emerald"),
            (now_iso(timedelta(days=1)), "EQUIPO", "Se registró nuevo Video-beam (VB-02)", "indigo"),
            (now_iso(timedelta(hours=2)), "PRÉSTAMO", "Dr. Carlos Mendoza retiró Video-beam (VB-02)", "blue"),
            (now_iso(timedelta(hours=1)), "PRÉSTAMO", "Dra. Ana María Gómez retiró Laptop (PC-02)", "blue"),
        ])
        db.commit()
    db.close()


# ---------------------------------------------------------------- página
@app.get("/")
def index():
    return app.send_static_file("index.html")


# ---------------------------------------------------------------- lectura
@app.get("/api/estado")
def estado():
    db = get_db()
    profesores = [dict(r) for r in db.execute(
        "SELECT cc, nombre FROM profesores ORDER BY rowid")]
    equipos = [dict(r) for r in db.execute(
        "SELECT codigo, tipo, modelo, estado FROM equipos ORDER BY rowid")]
    prestamos = [dict(r) for r in db.execute("""
        SELECT p.id, p.cc, pr.nombre,
               e.codigo || ' - ' || e.tipo || ' (' || e.modelo || ')' AS equipo,
               e.codigo AS codigoEquipo,
               p.hora_salida AS horaSalida,
               p.estado
        FROM prestamos p
        JOIN profesores pr ON pr.cc = p.cc
        JOIN equipos e ON e.codigo = p.codigo_equipo
        WHERE p.estado = 'Activo'
        ORDER BY p.id DESC""")]
    historial = [dict(r) for r in db.execute(
        "SELECT id, fecha, tipo, descripcion, color FROM historial ORDER BY id DESC")]
    return jsonify(profesores=profesores, equipos=equipos,
                   prestamos=prestamos, historialLogs=historial)


# ---------------------------------------------------------------- profesores
@app.post("/api/profesores")
def crear_profesor():
    d = body()
    cc = str(d.get("cc", "")).strip()
    nombre = str(d.get("nombre", "")).strip()
    if not cc or not nombre:
        return error("La cédula y el nombre son obligatorios")
    db = get_db()
    try:
        with db:
            db.execute("INSERT INTO profesores (cc, nombre) VALUES (?, ?)", (cc, nombre))
            log(db, "PROFESOR", f"Se registró nuevo profesor {nombre} (CC: {cc})", "emerald")
    except sqlite3.IntegrityError:
        return error("Ya existe un profesor registrado con esa cédula (CC)", 409)
    return jsonify(ok=True), 201


@app.delete("/api/profesores/<cc>")
def eliminar_profesor(cc):
    db = get_db()
    prof = db.execute("SELECT nombre FROM profesores WHERE cc = ?", (cc,)).fetchone()
    if not prof:
        return error("Profesor no encontrado", 404)
    activos = db.execute("SELECT COUNT(*) FROM prestamos WHERE cc = ?", (cc,)).fetchone()[0]
    if activos:
        return error("No se puede eliminar: el profesor tiene préstamos activos", 409)
    with db:
        db.execute("DELETE FROM profesores WHERE cc = ?", (cc,))
        log(db, "PROFESOR", f"Se eliminó profesor {prof['nombre']}", "rose")
    return jsonify(ok=True)


# ---------------------------------------------------------------- equipos
@app.post("/api/equipos")
def crear_equipo():
    d = body()
    codigo = str(d.get("codigo", "")).strip().upper()
    tipo = str(d.get("tipo", "")).strip()
    modelo = str(d.get("modelo", "")).strip()
    if not codigo or not modelo:
        return error("El código y el modelo son obligatorios")
    if tipo not in ("Video-beam", "Laptop"):
        return error("Tipo de equipo inválido")
    db = get_db()
    try:
        with db:
            db.execute(
                "INSERT INTO equipos (codigo, tipo, modelo, estado) VALUES (?, ?, ?, 'Disponible')",
                (codigo, tipo, modelo))
            log(db, "EQUIPO", f"Se registró nuevo equipo {tipo} ({codigo})", "indigo")
    except sqlite3.IntegrityError:
        return error("Ya existe un equipo registrado con ese código ID", 409)
    return jsonify(ok=True), 201


@app.delete("/api/equipos/<codigo>")
def eliminar_equipo(codigo):
    db = get_db()
    eq = db.execute("SELECT tipo FROM equipos WHERE codigo = ?", (codigo,)).fetchone()
    if not eq:
        return error("Equipo no encontrado", 404)
    with db:
        db.execute("DELETE FROM equipos WHERE codigo = ?", (codigo,))  # borra sus préstamos (CASCADE)
        log(db, "EQUIPO", f"Se eliminó equipo {eq['tipo']} ({codigo})", "rose")
    return jsonify(ok=True)


# ---------------------------------------------------------------- préstamos
@app.post("/api/prestamos")
def crear_prestamo():
    d = body()
    cc = str(d.get("cc", "")).strip()
    codigo = str(d.get("codigoEquipo", "")).strip()
    db = get_db()
    prof = db.execute("SELECT cc, nombre FROM profesores WHERE cc = ?", (cc,)).fetchone()
    eq = db.execute("SELECT codigo, tipo, estado FROM equipos WHERE codigo = ?", (codigo,)).fetchone()
    if not prof or not eq:
        return error("Datos inválidos para procesar el préstamo")
    if eq["estado"] != "Disponible":
        return error("Ese equipo ya está prestado", 409)
    with db:
        db.execute("INSERT INTO prestamos (cc, codigo_equipo, hora_salida) VALUES (?, ?, ?)",
                   (cc, codigo, now_iso()))
        db.execute("UPDATE equipos SET estado = 'Prestado' WHERE codigo = ?", (codigo,))
        log(db, "PRÉSTAMO", f"{prof['nombre']} retiró {eq['tipo']} ({codigo})", "blue")
    return jsonify(ok=True), 201


@app.post("/api/prestamos/<int:prestamo_id>/devolver")
def devolver_prestamo(prestamo_id):
    db = get_db()
    p = db.execute("""
        SELECT p.codigo_equipo, pr.nombre
        FROM prestamos p JOIN profesores pr ON pr.cc = p.cc
        WHERE p.id = ?""", (prestamo_id,)).fetchone()
    if not p:
        return error("Préstamo no encontrado", 404)
    with db:
        db.execute("DELETE FROM prestamos WHERE id = ?", (prestamo_id,))
        db.execute("UPDATE equipos SET estado = 'Disponible' WHERE codigo = ?", (p["codigo_equipo"],))
        log(db, "DEVOLUCIÓN", f"Se recibió {p['codigo_equipo']} entregado por {p['nombre']}", "emerald")
    return jsonify(ok=True)


# ---------------------------------------------------------------- historial
@app.delete("/api/historial")
def limpiar_historial():
    db = get_db()
    with db:
        db.execute("DELETE FROM historial")
    return jsonify(ok=True)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
