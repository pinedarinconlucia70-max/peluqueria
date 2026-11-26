import hmac
import logging
import os
import unicodedata
from datetime import date, datetime, time, timedelta

import mysql.connector
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import obtener_conexion

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY", "dev-only-change-this-secret-key"
)
app.config["CLIENT_ROLE_ID"] = int(os.environ.get("CLIENT_ROLE_ID", "3"))
_SCHEMA_CACHE = {}
_ROLE_TABLE_NAME = None
_INSUMO_CATEGORIES = {
    "1": {
        "title": "Tintes y Coloración",
        "categories": {"Color", "tinte permanente"},
    },
    "2": {
        "title": "Manicura y Uñas",
        "categories": {"Semipermanente", "Acrílico", "Manicura"},
    },
    "3": {
        "title": "Damas",
        "categories": {"Cejas y Pestañas", "Ellas"},
    },
    "4": {
        "title": "Caballeros",
        "categories": {"Cejas y Pestañas", "Ellos"},
    },
    "5": {
        "title": "Depilación",
        "categories": {"depilacion"},
    },
}
_ROLE_ADMIN = 1
_ROLE_EMPLOYEE = 2
_ROLE_CLIENT = app.config["CLIENT_ROLE_ID"]
_SERVICE_CATALOGS = {
    "damas": {
        "title": "Servicios para Damas",
        "categories": {"damas", "ellas"},
    },
    "caballeros": {
        "title": "Servicios para Caballeros",
        "categories": {"caballeros", "ellos"},
    },
    "manos-y-pies": {
        "title": "Manos y Pies",
        "categories": {
            "Retiros",
            "Press On",
            "acrilico",
            "Combos",
            "decoracion",
            "manicura",
            "manos y pies",
            "mantenimiento",
            "pedicure",
            "semipermanente",
            "unas",
            "spa",
        },
    },
    "cejas-y-pestanas": {
        "title": "Cejas y Pestañas",
        "categories": {"cejas y pestanas"},
    },
    "depilacion": {
        "title": "Depilación",
        "categories": {"depilacion"},
    },
    "color": {
        "title": "Color",
        "categories": {"color"},
    },
}


@app.template_filter("duracion_texto")
def duracion_texto(duracion):
    if not duracion:
        return ""

    if isinstance(duracion, timedelta):
        total_seg = int(duracion.total_seconds())
        horas = total_seg // 3600
        minutos = (total_seg % 3600) // 60
    elif isinstance(duracion, time):
        horas = duracion.hour
        minutos = duracion.minute
    else:
        partes = str(duracion).split(":")
        horas = int(partes[0]) if len(partes) > 0 else 0
        minutos = int(partes[1]) if len(partes) > 1 else 0

    if horas > 0 and minutos > 0:
        return f"{horas} h {minutos} min"
    if horas > 0:
        return f"{horas} hora" if horas == 1 else f"{horas} horas"
    return f"{minutos} minutos"


@app.template_filter("time_input")
def time_input(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    if hasattr(value, "total_seconds"):
        total_minutes = int(value.total_seconds() // 60)
        return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"
    return str(value)[:5]


def _fetch_all(sql, params=()):
    connection = obtener_conexion()
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()


def _fetch_one(sql, params=()):
    rows = _fetch_all(sql, params)
    return rows[0] if rows else None


def _execute(sql, params=()):
    connection = obtener_conexion()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            connection.commit()
            return cursor.lastrowid
        finally:
            cursor.close()
    finally:
        connection.close()


def _form_value(name):
    value = request.form.get(name, "").strip()
    if not value:
        abort(400, description=f"El campo «{name}» es obligatorio.")
    return value


def _form_integer(name):
    value = _form_value(name)
    try:
        return int(value)
    except ValueError:
        abort(400, description=f"El campo «{name}» debe ser un número entero.")


def _optional_form_integer(name):
    value = request.form.get(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        abort(400, description=f"El campo «{name}» debe ser un número entero.")


def _normalize_label(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).casefold().strip()


def _insumo_category_id(value):
    if value is None:
        return ""
    category_value = str(value).strip().lower()

    if category_value in _INSUMO_CATEGORIES:
        return category_value

    for category_id, data in _INSUMO_CATEGORIES.items():
        if category_value in data["categories"]:
            return category_id
    normalized_label = _normalize_label(category_value)
    for category_id, data in _INSUMO_CATEGORIES.items():
        if any(_normalize_label(cat) == normalized_label for cat in data["categories"]):
            return category_id

    return category_value


def _service_category_id(value):
    if value is None:
        return "otros"
    normalized_label = _normalize_label(value)
    for category_id, data in _SERVICE_CATALOGS.items():
        if normalized_label == category_id:
            return category_id
        if any(
            _normalize_label(category) == normalized_label
            for category in data["categories"]
        ):
            return category_id
    return "otros"


def _inventory_summary():
    summary = _fetch_one(
        "SELECT COALESCE(SUM(stockActual), 0) AS total_disponibles, "
        "COALESCE(SUM(CASE WHEN stockActual <= stockMinPosible "
        "THEN 1 ELSE 0 END), 0) AS stock_critico FROM insumo"
    )
    alerts = _fetch_all(
        "SELECT idInsumo, nombreInsumo, stockActual, stockMinPosible "
        "FROM insumo WHERE stockActual <= stockMinPosible "
        "ORDER BY stockActual ASC, nombreInsumo ASC LIMIT 7"
    )
    return summary, alerts


def _available_services():
    duration_expression = (
        "duracion" if "duracion" in _table_columns("servicio") else "NULL"
    )
    return _fetch_all(
        "SELECT idServicio, nombreServicio, descripcionServicio, precioBase, "
        f"estado, {duration_expression} AS duracion, categoria, idUsuarioFK, idInsumoFK "
        "FROM servicio WHERE estado IN ('Disponible', 'Activo') "
        "ORDER BY categoria, nombreServicio"
    )


def _booking_service():
    booking = session.get("booking")
    if not isinstance(booking, dict) or not booking.get("service_id"):
        return None
    duration_expression = (
        "s.duracion" if "duracion" in _table_columns("servicio") else "NULL"
    )
    return _fetch_one(
        "SELECT s.idServicio, s.nombreServicio, s.descripcionServicio, "
        f"s.precioBase, s.estado, {duration_expression} AS duracion, "
        "s.categoria, s.idUsuarioFK, "
        f"s.idInsumoFK, {_user_name_expression('u')} AS estilistaNombre "
        "FROM servicio AS s LEFT JOIN usuario AS u ON u.idUsuario = s.idUsuarioFK "
        "WHERE s.idServicio = %s AND s.estado IN ('Disponible', 'Activo')",
        (booking["service_id"],),
    )


def _require_client():
    user_id = session.get("usuario_id")
    if user_id is None:
        return None
    if session.get("usuarioLogueado", {}).get("idRolFK") != _ROLE_CLIENT:
        return None
    return user_id


def _require_admin():
    if session.get("usuario_id") is None:
        return redirect(url_for("login"))
    if session.get("usuarioLogueado", {}).get("idRolFK") != _ROLE_ADMIN:
        abort(403)
    return None


def _table_columns(table):
    allowed_tables = {"usuario", "cita", "servicio", "insumo"}
    if table not in allowed_tables:
        raise ValueError(f"Tabla no permitida: {table}")
    if table not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[table] = {
            row["Field"] for row in _fetch_all(f"SHOW COLUMNS FROM `{table}`")
        }
    return _SCHEMA_CACHE[table]


def _role_table_name():
    global _ROLE_TABLE_NAME
    if _ROLE_TABLE_NAME is None:
        rows = _fetch_all(
            "SELECT TABLE_NAME AS tableName FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND LOWER(TABLE_NAME) = 'rol'"
        )
        _ROLE_TABLE_NAME = rows[0]["tableName"] if rows else "Rol"
    return _ROLE_TABLE_NAME


def _user_name_fields(full_name, surname=""):
    columns = _table_columns("usuario")
    values = {}
    if "nombreCompleto" in columns:
        values["nombreCompleto"] = full_name
    elif "nombre" in columns:
        values["nombre"] = full_name
    if "apellido" in columns:
        surname = surname.strip()
        if not surname:
            parts = full_name.strip().split(maxsplit=1)
            if len(parts) != 2:
                abort(400, description="Ingresa nombre y apellido.")
            surname = parts[1]
        values["apellido"] = surname
    return values


def _user_name_expression(alias=""):
    columns = _table_columns("usuario")
    prefix = f"{alias}." if alias else ""
    if "nombreCompleto" in columns:
        return f"{prefix}nombreCompleto"
    return f"CONCAT_WS(' ', {prefix}nombre, {prefix}apellido)"


def _insert_user(values):
    columns = tuple(values)
    placeholders = ", ".join(["%s"] * len(columns))
    return _execute(
        f"INSERT INTO usuario ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values[column] for column in columns),
    )


def _update_user(user_id, values):
    assignments = ", ".join(f"{column} = %s" for column in values)
    _execute(
        f"UPDATE usuario SET {assignments} WHERE idUsuario = %s",
        tuple(values.values()) + (user_id,),
    )


def _user_query(where_clause="", include_password=False):
    columns = _table_columns("usuario")
    name_expression = _user_name_expression("u")
    address_expression = "u.direccion" if "direccion" in columns else "''"
    surname_expression = "u.apellido" if "apellido" in columns else "''"
    password_expression = ", u.contrasenia" if include_password else ""
    return (
        "SELECT u.idUsuario, u.tipoDocumento, u.numDocumento, "
        f"{name_expression} AS nombreCompleto, u.telefono, u.email, "
        f"{surname_expression} AS apellido, {address_expression} AS direccion, "
        "u.genero, u.cargo"
        f"{password_expression}, u.estado, u.idRolFK, r.descripcionRol "
        f"FROM usuario AS u LEFT JOIN `{_role_table_name()}` AS r "
        "ON r.idRol = u.idRolFK "
        f"{where_clause}"
    )


def _current_user():
    user_id = session.get("usuario_id")
    if user_id is None:
        return None
    return _fetch_one(_user_query("WHERE u.idUsuario = %s"), (user_id,))


def _service_form_data(service=None):
    return {
        "servicio": service or {},
        "tiene_duracion": "duracion" in _table_columns("servicio"),
        "categorias": [
            "Damas",
            "Caballeros",
            "Color",
            "Manos y Pies",
            "Depilación",
            "Cejas y Pestañas",
            "Otros",
        ],
        "usuarios": _fetch_all(
            "SELECT u.idUsuario, "
            f"{_user_name_expression('u')} AS nombreCompleto "
            "FROM usuario AS u ORDER BY nombreCompleto"
        ),
        "insumos": _fetch_all(
            "SELECT idInsumo, nombreInsumo FROM insumo ORDER BY nombreInsumo"
        ),
    }


def _appointment_form_data(appointment=None):
    service_filter = "" if appointment is not None else "WHERE estado = 'Activo' "
    return {
        "cita": appointment or {},
        "tiene_horario": "horaInicio" in _table_columns("cita"),
        "servicios": _fetch_all(
            "SELECT idServicio, nombreServicio, precioBase FROM servicio "
            f"{service_filter}ORDER BY nombreServicio"
        ),
        "usuarios": _fetch_all(
            "SELECT u.idUsuario, "
            f"{_user_name_expression('u')} AS nombreCompleto "
            "FROM usuario AS u ORDER BY nombreCompleto"
        ),
        "insumos": _fetch_all(
            "SELECT idInsumo, nombreInsumo FROM insumo ORDER BY nombreInsumo"
        ),
    }


# =========================================================================
# FUNCIONES AUXILIARES PARA DISPONIBILIDAD DE CITAS POR ESTILISTA
# =========================================================================

def _service_duration_delta(service):
    duration = service.get("duracion")
    if duration is None:
        return timedelta(minutes=30)
    if isinstance(duration, timedelta):
        return duration if duration.total_seconds() > 0 else timedelta(minutes=30)
    if isinstance(duration, time):
        delta = timedelta(
            hours=duration.hour, minutes=duration.minute, seconds=duration.second
        )
        return delta if delta.total_seconds() > 0 else timedelta(minutes=30)
    parsed = datetime.strptime(str(duration), "%H:%M:%S").time()
    delta = timedelta(hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second)
    return delta if delta.total_seconds() > 0 else timedelta(minutes=30)


def _active_stylists():
    return _fetch_all(
        "SELECT u.idUsuario, "
        f"{_user_name_expression('u')} AS nombreCompleto, u.cargo "
        "FROM usuario AS u "
        "WHERE u.estado = 'Activo' AND u.idRolFK IN (%s, %s) "
        "ORDER BY nombreCompleto",
        (_ROLE_EMPLOYEE, _ROLE_ADMIN),
    )


def _booked_slots_for_stylist(stylist_id, target_date):
    columns = _table_columns("cita")
    stylist_col = (
        "idEstilistaFK"
        if "idEstilistaFK" in columns
        else ("idEmpleadoFK" if "idEmpleadoFK" in columns else None)
    )
    if not stylist_col or "horaInicio" not in columns:
        return []

    rows = _fetch_all(
        f"SELECT horaInicio, horaFinal FROM cita "
        f"WHERE {stylist_col} = %s AND fecha = %s "
        f"AND estado NOT IN ('Cancelada', 'No asistida')",
        (stylist_id, target_date),
    )

    occupied = []
    for row in rows:
        raw_start = row.get("horaInicio")
        if raw_start is None:
            continue
        if isinstance(raw_start, timedelta):
            start_dt = datetime.combine(target_date, time.min) + raw_start
        elif isinstance(raw_start, time):
            start_dt = datetime.combine(target_date, raw_start)
        else:
            start_dt = datetime.combine(
                target_date, datetime.strptime(str(raw_start)[:8], "%H:%M:%S").time()
            )

        raw_end = row.get("horaFinal")
        if raw_end is not None:
            if isinstance(raw_end, timedelta):
                end_dt = datetime.combine(target_date, time.min) + raw_end
            elif isinstance(raw_end, time):
                end_dt = datetime.combine(target_date, raw_end)
            else:
                end_dt = datetime.combine(
                    target_date, datetime.strptime(str(raw_end)[:8], "%H:%M:%S").time()
                )
        else:
            end_dt = start_dt + timedelta(minutes=30)

        occupied.append((start_dt, end_dt))
    return occupied


def _available_hours_for_stylist(stylist_id, target_date, duration_delta, step_minutes=30):
    now = datetime.now()
    start_window = datetime.combine(target_date, time(8, 0))
    end_window = datetime.combine(target_date, time(22, 0))
    occupied = _booked_slots_for_stylist(stylist_id, target_date)

    slots = []
    current = start_window
    step = timedelta(minutes=step_minutes)

    while current + duration_delta <= end_window:
        slot_end = current + duration_delta
        is_past = target_date == date.today() and current <= now
        overlaps = any(
            current < occ_end and slot_end > occ_start
            for occ_start, occ_end in occupied
        )
        slots.append(
            {
                "hora": current.strftime("%H:%M"),
                "hora_fin": slot_end.strftime("%H:%M"),
                "disponible": not (is_past or overlaps),
                "motivo": (
                    "Hora pasada"
                    if is_past
                    else ("Ocupado con el estilista" if overlaps else "Disponible")
                ),
            }
        )
        current += step

    return slots


# =========================================================================
# MANEJO DE ERRORES Y RUTAS GENERALES
# =========================================================================

@app.errorhandler(mysql.connector.Error)
def handle_database_error(error):
    app.logger.exception("Error al consultar la base de datos", exc_info=error)
    if error.errno == 1062:
        message = "Ese número de documento ya está registrado."
        status = 409
    elif error.errno in {1048, 1364}:
        message = "Falta completar un campo obligatorio para guardar el usuario."
        status = 400
    elif error.errno == 1452:
        message = "El rol seleccionado no existe. Revisa los roles disponibles."
        status = 400
    elif error.errno == 1406:
        message = "Uno de los campos supera la longitud permitida por la base de datos."
        status = 400
    elif error.errno in {2002, 2003, 2005, 2006, 2013}:
        message = (
            "No se pudo conectar con MySQL. Verifica que el servidor esté activo "
            "y que DB_HOST, DB_PORT, DB_USER y DB_PASSWORD sean correctos."
        )
        status = 503
    else:
        message = (
            "MySQL rechazó la operación. Revisa el error del servidor para ver "
            "qué tabla o campo necesita corregirse."
        )
        status = 500
    return (
        render_template("error.html", mensaje=message),
        status,
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/usuarios/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        document = _form_value("numDocumento")
        password = _form_value("contrasenia")
        user = _fetch_one(
            _user_query(
                "WHERE u.numDocumento = %s AND u.estado = 'Activo'",
                include_password=True,
            ),
            (document,),
        )
        if user is None or not hmac.compare_digest(
            str(user["contrasenia"]), password
        ):
            flash("Documento o contraseña incorrectos.", "error")
            return redirect(url_for("login"))
        booking = session.get("booking")
        session.clear()
        if booking:
            session["booking"] = booking
        session["usuario_id"] = user["idUsuario"]
        session["usuarioLogueado"] = {
            "idRolFK": user["idRolFK"],
            "nombre": user["nombreCompleto"],
        }
        if user["idRolFK"] == _ROLE_CLIENT and session.get("booking"):
            return redirect(url_for("citas_calendario"))
        return redirect(url_for("dashboard"))
    return render_template(
        "usuarios/formularioInicioSesion.html",
        tiene_direccion="direccion" in _table_columns("usuario"),
        tiene_apellido="apellido" in _table_columns("usuario"),
    )


@app.route("/usuarios/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/usuarios/registrar", methods=["GET", "POST"])
def registrar_cliente():
    if request.method == "POST":
        user_columns = _table_columns("usuario")
        role_id = app.config["CLIENT_ROLE_ID"]
        if (
            _fetch_one(
                f"SELECT idRol FROM `{_role_table_name()}` WHERE idRol = %s",
                (role_id,),
            )
            is None
        ):
            abort(
                503,
                description=(
                    "Configura CLIENT_ROLE_ID con el identificador del rol de cliente "
                    "que exista en la tabla Rol."
                ),
            )
        values = {
            "tipoDocumento": _form_value("tipoDocumento"),
            "numDocumento": _form_integer("numDocumento"),
        }
        values.update(
            _user_name_fields(
                _form_value("nombreCompleto"),
                request.form.get("apellido", ""),
            )
        )
        if "direccion" in user_columns:
            values["direccion"] = _form_value("direccion")
        values.update(
            {
                "telefono": _form_integer("telefono"),
                "email": _form_value("email"),
                "genero": _form_value("genero"),
                "cargo": "",
                "contrasenia": _form_value("contrasenia"),
                "estado": "Activo",
                "idRolFK": role_id,
            }
        )
        user_id = _insert_user(values)
        session["usuario_id"] = user_id
        session["usuarioLogueado"] = {
            "idRolFK": role_id,
            "nombre": values.get("nombreCompleto", values.get("nombre", "")),
        }
        flash("Tu cuenta de cliente fue creada correctamente.", "success")
        if session.get("booking"):
            return redirect(url_for("citas_calendario"))
        return redirect(url_for("dashboard"))
    return render_template(
        "usuarios/formularioInicioSesion.html",
        tiene_direccion="direccion" in _table_columns("usuario"),
        tiene_apellido="apellido" in _table_columns("usuario"),
    )


@app.route("/usuarios/dashboard")
def dashboard():
    if session.get("usuario_id") is None:
        return redirect(url_for("login"))
    if session.get("usuarioLogueado", {}).get("idRolFK") == _ROLE_CLIENT:
        return redirect(url_for("portal_cliente"))
    return render_template("usuarios/dashboard.html")


@app.route("/cliente")
def portal_cliente():
    user_id = _require_client()
    if user_id is None:
        return redirect(
            url_for("dashboard") if session.get("usuario_id") else url_for("login")
        )
    citas = _fetch_all(
        "SELECT idCita, servicio, fecha, horaInicio, horaFinal, estado, observacion, totalServicio "
        "FROM cita WHERE idUsuarioFK = %s ORDER BY fecha DESC, idCita DESC",
        (user_id,),
    )
    return render_template("usuarios/portalCliente.html", citas=citas)


@app.route("/estilistas")
def listar_estilistas():
    staff = _fetch_all(
        "SELECT u.idUsuario, "
        f"{_user_name_expression('u')} AS nombreCompleto, u.cargo "
        "FROM usuario AS u WHERE u.idRolFK = %s AND u.estado = 'Activo' "
        "ORDER BY nombreCompleto",
        (_ROLE_EMPLOYEE,),
    )
    return render_template("estilistas.html", estilistas=staff)


@app.route("/servicios/catalogo/<slug>")
def catalogo_servicios(slug):
    catalog = _SERVICE_CATALOGS.get(slug)
    if catalog is None:
        abort(404)
    services = [
        service
        for service in _available_services()
        if _normalize_label(service["categoria"]) in catalog["categories"]
    ]
    return render_template(
        "servicios/catalogo.html",
        titulo=catalog["title"],
        slug=slug,
        servicios=services,
    )


@app.route("/citas/seleccionar", methods=["POST"])
def seleccionar_servicio():
    service_id = _form_integer("service_id")
    service = _fetch_one(
        "SELECT idServicio FROM servicio WHERE idServicio = %s "
        "AND estado IN ('Disponible', 'Activo')",
        (service_id,),
    )
    if service is None:
        abort(404, description="El servicio ya no está disponible.")
    catalog_slug = request.form.get("catalog_slug", "")
    session["booking"] = {
        "service_id": service_id,
        "catalog_slug": catalog_slug if catalog_slug in _SERVICE_CATALOGS else "damas",
    }
    if session.get("usuario_id") is None:
        flash("Inicia sesión o crea una cuenta de cliente para reservar.", "info")
        return redirect(url_for("login"))
    if _require_client() is None:
        return redirect(url_for("dashboard"))
    return redirect(url_for("citas_calendario"))


# =========================================================================
# VISTA 1: CALENDARIO MENSUAL (SELECCIÓN DE DÍA >= HOY)
# =========================================================================

@app.route("/citas/calendario", methods=["GET", "POST"])
def citas_calendario():
    if _require_client() is None:
        return redirect(
            url_for("dashboard") if session.get("usuario_id") else url_for("login")
        )
    service = _booking_service()
    if service is None:
        session.pop("booking", None)
        flash("Selecciona un servicio disponible para continuar.", "error")
        return redirect(url_for("home", _anchor="servicios"))

    if request.method == "POST":
        try:
            appointment_date = date.fromisoformat(_form_value("fecha"))
        except ValueError:
            abort(400, description="La fecha seleccionada no es válida.")
        if appointment_date < date.today():
            flash("No puedes seleccionar una fecha anterior a hoy.", "error")
            return redirect(url_for("citas_calendario"))

        booking = dict(session["booking"])
        booking["fecha"] = appointment_date.isoformat()
        booking.pop("hora", None)
        booking.pop("estilista_id", None)
        session["booking"] = booking
        return redirect(url_for("citas_horarios"))

    today = date.today()
    return render_template(
        "citas/calendario.html",
        servicio=service,
        fecha_minima=today.isoformat(),
        anio_actual=today.year,
        mes_actual=today.month,
        dia_actual=today.day,
        catalog_slug=session["booking"].get("catalog_slug", "damas"),
    )


# =========================================================================
# VISTA 2: ESTILISTA Y HORAS DISPONIBLES (08:00 A 22:00)
# =========================================================================

@app.route("/citas/horarios/disponibilidad")
def citas_horarios_disponibilidad():
    if _require_client() is None:
        return jsonify({"error": "No autorizado"}), 401
    service = _booking_service()
    booking = session.get("booking") or {}
    if service is None or not booking.get("fecha"):
        return jsonify({"error": "Selecciona primero una fecha"}), 400

    try:
        target_date = date.fromisoformat(request.args.get("fecha", booking["fecha"]))
        stylist_id = int(request.args.get("estilista_id", ""))
    except ValueError:
        return jsonify({"error": "Parámetros inválidos"}), 400

    if target_date < date.today():
        return jsonify({"slots": [], "mensaje": "Fecha anterior a hoy."})

    duration_delta = _service_duration_delta(service)
    slots = _available_hours_for_stylist(stylist_id, target_date, duration_delta)
    return jsonify(
        {
            "fecha": target_date.isoformat(),
            "estilista_id": stylist_id,
            "duracion_minutos": int(duration_delta.total_seconds() // 60),
            "slots": [s for s in slots if s["disponible"]],
            "todos_los_slots": slots,
        }
    )


@app.route("/citas/horarios", methods=["GET", "POST"])
def citas_horarios():
    if _require_client() is None:
        return redirect(
            url_for("dashboard") if session.get("usuario_id") else url_for("login")
        )
    service = _booking_service()
    booking = session.get("booking")
    if service is None or not isinstance(booking, dict) or not booking.get("fecha"):
        flash("Primero selecciona una fecha en el calendario.", "error")
        return redirect(url_for("citas_calendario"))

    appointment_date = date.fromisoformat(booking["fecha"])
    if appointment_date < date.today():
        flash("La fecha guardada ya pasó; elige una nueva fecha.", "error")
        return redirect(url_for("citas_calendario"))

    stylists = _active_stylists()
    if not stylists:
        flash("No hay estilistas activos disponibles en este momento.", "error")
        return redirect(url_for("citas_calendario"))

    duration_delta = _service_duration_delta(service)
    selected_stylist_id = (
        request.form.get("estilista_id")
        or request.args.get("estilista_id")
        or str(stylists[0]["idUsuario"])
    )
    try:
        stylist_id = int(selected_stylist_id)
    except ValueError:
        stylist_id = stylists[0]["idUsuario"]

    stylist_obj = next(
        (s for s in stylists if s["idUsuario"] == stylist_id), stylists[0]
    )
    stylist_id = stylist_obj["idUsuario"]

    if request.method == "POST":
        hora_str = _form_value("hora")
        try:
            appointment_time = datetime.strptime(hora_str, "%H:%M").time()
        except ValueError:
            abort(400, description="Hora inválida.")

        start_dt = datetime.combine(appointment_date, appointment_time)
        end_dt = start_dt + duration_delta

        if appointment_time < time(8, 0) or end_dt.time() > time(22, 0):
            abort(
                400,
                description="Solo se permiten citas entre las 08:00 y las 22:00.",
            )

        if appointment_date == date.today() and start_dt <= datetime.now():
            abort(
                400, description="No puedes seleccionar una hora anterior a la actual."
            )

        occupied = _booked_slots_for_stylist(stylist_id, appointment_date)
        if any(
            start_dt < occ_end and end_dt > occ_start for occ_start, occ_end in occupied
        ):
            flash(
                "Esa hora ya fue reservada para el estilista seleccionado. Elige otra.",
                "error",
            )
            return redirect(url_for("citas_horarios", estilista_id=stylist_id))

        columns = _table_columns("cita")
        values = {
            "servicio": service["nombreServicio"],
            "fecha": appointment_date,
            "estado": "Pendiente",
            "totalServicio": service["precioBase"],
            "idUsuarioFK": _require_client(),
            "idServicioFK": service["idServicio"],
            "idInsumoFK": service["idInsumoFK"],
        }
        if "idEstilistaFK" in columns:
            values["idEstilistaFK"] = stylist_id
        elif "idEmpleadoFK" in columns:
            values["idEmpleadoFK"] = stylist_id

        if "horaInicio" in columns:
            values["horaInicio"] = appointment_time
        if "horaFinal" in columns:
            values["horaFinal"] = end_dt.time()
        if "observacion" in columns:
            values["observacion"] = (
                f"Estilista: {stylist_obj['nombreCompleto']} | Hora: {hora_str}"
            )

        insert_columns = tuple(values)
        placeholders = ", ".join(["%s"] * len(insert_columns))
        _execute(
            f"INSERT INTO cita ({', '.join(insert_columns)}) VALUES ({placeholders})",
            tuple(values[col] for col in insert_columns),
        )
        session.pop("booking", None)
        flash(
            f"Cita agendada para el {appointment_date.isoformat()} a las {hora_str} "
            f"con {stylist_obj['nombreCompleto']}.",
            "success",
        )
        return redirect(url_for("portal_cliente"))

    slots = _available_hours_for_stylist(stylist_id, appointment_date, duration_delta)
    return render_template(
        "citas/horarios.html",
        servicio=service,
        fecha=appointment_date.isoformat(),
        estilistas=stylists,
        estilista_seleccionado=stylist_obj,
        slots=slots,
        duracion_texto_str=duracion_texto(duration_delta),
    )


# =========================================================================
# RUTAS DE PERFIL, USUARIOS, CITAS ADMIN, INSUMOS Y SERVICIOS
# =========================================================================

@app.route("/usuarios/perfil")
def perfil_usuario():
    usuario = _current_user()
    if usuario is None:
        return redirect(url_for("login"))
    resumen_insumos, alertas_stock = _inventory_summary()
    return render_template(
        "usuarios/perfilUsuario.html",
        usuario=usuario,
        resumen_insumos=resumen_insumos,
        alertas_stock=alertas_stock,
    )


@app.route("/usuarios/perfil/editar", methods=["GET", "POST"])
@app.route("/usuarios/editar", methods=["GET", "POST"])
def editar_perfil():
    usuario = _current_user()
    if usuario is None:
        return redirect(url_for("login"))
    if request.method == "POST":
        values = _user_name_fields(
            _form_value("nombreCompleto"),
            request.form.get("apellido", ""),
        )
        values.update(
            {
                "telefono": _form_integer("telefono"),
                "email": _form_value("email"),
                "genero": _form_value("genero"),
            }
        )
        if "direccion" in _table_columns("usuario") and request.form.get("direccion"):
            values["direccion"] = request.form.get("direccion", "").strip()
        _execute(
            "UPDATE usuario SET "
            + ", ".join(f"{column} = %s" for column in values)
            + " WHERE idUsuario = %s",
            tuple(values.values()) + (usuario["idUsuario"],),
        )
        flash("Perfil actualizado.", "success")
        return redirect(url_for("perfil_usuario"))
    return render_template(
        "usuarios/formularioActualizacionPerfil.html",
        usuario=usuario,
        tiene_direccion="direccion" in _table_columns("usuario"),
        tiene_apellido="apellido" in _table_columns("usuario"),
    )


@app.route("/usuarios")
def listar_usuarios():
    access_response = _require_admin()
    if access_response is not None:
        return access_response
    return render_template(
        "usuarios/tablaUsuarios.html",
        usuarios=_fetch_all(_user_query("ORDER BY u.idUsuario DESC")),
    )


@app.route("/usuarios/registro", methods=["GET"])
def usuariosregistrar():
    access_response = _require_admin()
    if access_response is not None:
        return access_response
    return render_template(
        "usuarios/formularioRegistro.html",
        usuario={},
        roles=_fetch_all(
            f"SELECT idRol, descripcionRol FROM `{_role_table_name()}` ORDER BY idRol"
        ),
        tiene_direccion="direccion" in _table_columns("usuario"),
        tiene_apellido="apellido" in _table_columns("usuario"),
    )


@app.route("/usuarios/guardar", methods=["POST"])
def usuariosguardar():
    access_response = _require_admin()
    if access_response is not None:
        return access_response
    user_columns = _table_columns("usuario")
    user_id = _optional_form_integer("idUsuario")
    values = {}
    if user_id is None:
        values.update(
            {
                "tipoDocumento": _form_value("tipoDocumento"),
                "numDocumento": _form_integer("numDocumento"),
            }
        )
    values.update(
        _user_name_fields(
            _form_value("nombreCompleto"),
            request.form.get("apellido", ""),
        )
    )
    if "direccion" in user_columns and request.form.get("direccion"):
        values["direccion"] = request.form.get("direccion", "").strip()
    elif "direccion" in user_columns and user_id is None:
        abort(400, description="El campo «direccion» es obligatorio.")
    values.update(
        {
            "telefono": _form_integer("telefono"),
            "email": _form_value("email"),
            "genero": _form_value("genero"),
            "cargo": request.form.get("cargo", "").strip(),
            "estado": request.form.get("estado", "Activo").strip() or "Activo",
            "idRolFK": _form_integer("idRolFK"),
        }
    )
    if user_id is not None:
        _update_user(user_id, values)
    else:
        values["contrasenia"] = _form_value("contrasenia")
        _insert_user(values)
    flash("Usuario guardado.", "success")
    return redirect(url_for("listar_usuarios"))


@app.route("/usuarios/editar/<int:id>")
def usuarios_editar(id):
    access_response = _require_admin()
    if access_response is not None:
        return access_response
    usuario = _fetch_one(_user_query("WHERE u.idUsuario = %s"), (id,))
    if usuario is None:
        abort(404)
    return render_template(
        "usuarios/formularioAtualizacionUsuarios.html",
        usuario=usuario,
        roles=_fetch_all(
            f"SELECT idRol, descripcionRol FROM `{_role_table_name()}` ORDER BY idRol"
        ),
        tiene_direccion="direccion" in _table_columns("usuario"),
        tiene_apellido="apellido" in _table_columns("usuario"),
    )


@app.route("/usuarios/<int:id>/estado/<estado>", methods=["POST"])
def usuarios_cambiar_estado(id, estado):
    access_response = _require_admin()
    if access_response is not None:
        return access_response
    if estado not in {"Activo", "Inactivo"}:
        abort(400)
    _execute("UPDATE usuario SET estado = %s WHERE idUsuario = %s", (estado, id))
    flash("Estado del usuario actualizado.", "success")
    return redirect(url_for("listar_usuarios"))


@app.route("/citas")
def listar_citas():
    return render_template(
        "citas/tablaCitas.html",
        citas=_fetch_all(
            "SELECT c.*, s.nombreServicio, "
            f"{_user_name_expression('u')} AS cliente, "
            f"{_user_name_expression('e')} AS estilista "
            "FROM cita AS c "
            "LEFT JOIN servicio AS s ON s.idServicio = c.idServicioFK "
            "LEFT JOIN usuario AS u ON u.idUsuario = c.idUsuarioFK "
            "LEFT JOIN usuario AS e ON e.idUsuario = c.idEstilistaFK "
            "ORDER BY c.fecha DESC, c.idCita DESC"
        ),
        tiene_horario="horaInicio" in _table_columns("cita"),
    )


@app.route("/citas/registro")
def citas_formulario_registro():
    return render_template(
        "citas/formularioRegistroCitas.html", **_appointment_form_data()
    )


@app.route("/citas/guardar", methods=["POST"])
def citas_guardar():
    service_id = _form_integer("idServicioFK")
    service = _fetch_one(
        "SELECT nombreServicio FROM servicio WHERE idServicio = %s", (service_id,)
    )
    if service is None:
        abort(400, description="Selecciona un servicio existente.")
    appointment_id = _optional_form_integer("idCita")
    user_id = _form_integer("idUsuarioFK")
    insumo_id = _form_integer("idInsumoFK")
    fields = {
        "servicio": service["nombreServicio"],
        "fecha": _form_value("fecha"),
        "estado": request.form.get("estado", "Pendiente").strip() or "Pendiente",
        "observacion": request.form.get("observacion", "").strip(),
        "totalServicio": _form_value("totalServicio"),
        "idUsuarioFK": user_id,
        "idServicioFK": service_id,
        "idInsumoFK": insumo_id,
    }
    cita_columns = _table_columns("cita")
    if "horaInicio" in cita_columns:
        fields["horaInicio"] = _form_value("horaInicio")
    if "horaFinal" in cita_columns:
        fields["horaFinal"] = _form_value("horaFinal")
    if appointment_id is not None:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        _execute(
            f"UPDATE cita SET {assignments} WHERE idCita=%s",
            tuple(fields.values()) + (appointment_id,),
        )
        flash("Cita actualizada.", "success")
    else:
        _execute(
            f"INSERT INTO cita ({', '.join(fields)}) "
            f"VALUES ({', '.join(['%s'] * len(fields))})",
            tuple(fields.values()),
        )
        flash("Cita registrada.", "success")
    return redirect(url_for("listar_citas"))


@app.route("/citas/editar/<int:id>")
def citas_formulario_actualizacion(id):
    cita = _fetch_one("SELECT * FROM cita WHERE idCita = %s", (id,))
    if cita is None:
        abort(404)
    return render_template(
        "citas/formularioActualizacionCitas.html",
        **_appointment_form_data(cita),
    )


@app.route("/citas/<int:id>/estado/<estado>", methods=["POST"])
def citas_cambiar_estado(id, estado):
    if estado not in {"Pendiente", "Asistida", "Cancelada"}:
        abort(400)
    _execute("UPDATE cita SET estado = %s WHERE idCita = %s", (estado, id))
    flash("Estado de la cita actualizado.", "success")
    return redirect(url_for("listar_citas"))


@app.route("/insumos")
def listar_insumos():
    insumos = _fetch_all("SELECT * FROM insumo ORDER BY idInsumo ASC")
    for insumo in insumos:
        category_value = insumo.get("categoriaInsumo")
        category_id = _insumo_category_id(category_value)
        insumo["categoriaInsumoId"] = category_id

        if category_value is not None and str(category_value).strip():
            insumo["categoriaInsumoNombre"] = str(category_value).strip()
        else:
            insumo["categoriaInsumoNombre"] = "Sin categoría"
    return render_template(
        "insumos/tablaInsumos.html",
        insumos=insumos,
        categorias=_INSUMO_CATEGORIES,
    )


@app.route("/insumos/registro")
def insumos_formulario_registro():
    return render_template("insumos/formularioRegistroInsumos.html", insumo={})


@app.route("/insumos/guardar", methods=["POST"])
def insumos_guardar():
    values = (
        _form_value("nombreInsumo"),
        _form_value("descripcionInsumo"),
        _form_value("categoriaInsumo"),
        _form_value("fechaVencimiento"),
        _form_integer("stockActual"),
        _form_integer("stockMinPosible"),
        _form_value("horaActualizacion"),
    )
    insumo_id = _optional_form_integer("idInsumo")
    if insumo_id is not None:
        _execute(
            "UPDATE insumo SET nombreInsumo=%s, descripcionInsumo=%s, "
            "categoriaInsumo=%s, fechaVencimiento=%s, stockActual=%s, "
            "stockMinPosible=%s, horaActualizacion=%s WHERE idInsumo=%s",
            values + (insumo_id,),
        )
        flash("Insumo actualizado.", "success")
    else:
        _execute(
            "INSERT INTO insumo "
            "(nombreInsumo, descripcionInsumo, categoriaInsumo, fechaVencimiento, "
            "stockActual, stockMinPosible, horaActualizacion) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            values,
        )
        flash("Insumo registrado.", "success")
    return redirect(url_for("listar_insumos"))


@app.route("/insumos/editar/<int:id>")
def insumos_formulario_actualizacion(id):
    insumo = _fetch_one("SELECT * FROM insumo WHERE idInsumo = %s", (id,))
    if insumo is None:
        abort(404)

    category_value = insumo.get("categoriaInsumo")
    insumo["categoriaId"] = _insumo_category_id(category_value)
    return render_template(
        "insumos/formularioActualizacionInsumos.html",
        insumo=insumo,
        categorias=_INSUMO_CATEGORIES,
    )


@app.route("/servicios")
def listar_servicios():
    servicios = _fetch_all("SELECT * FROM servicio ORDER BY idServicio DESC")
    for servicio in servicios:
        servicio["categoriaId"] = _service_category_id(servicio.get("categoria"))
    return render_template(
        "servicios/tablaServicios.html",
        servicios=servicios,
        tiene_duracion="duracion" in _table_columns("servicio"),
        categorias=_SERVICE_CATALOGS,
    )


@app.route("/servicios/registro")
def servicios_formulario_registro():
    return render_template(
        "servicios/formularioRegistroServicio.html", **_service_form_data()
    )


@app.route("/servicios/guardar", methods=["POST"])
def servicios_guardar():
    fields = {
        "nombreServicio": _form_value("nombreServicio"),
        "descripcionServicio": _form_value("descripcionServicio"),
        "precioBase": _form_value("precioBase"),
        "estado": request.form.get("estado", "Activo").strip() or "Activo",
    }
    if "duracion" in _table_columns("servicio"):
        fields["duracion"] = _form_value("duracion")
    fields.update(
        {
            "categoria": _form_value("categoria"),
            "idUsuarioFK": _form_integer("idUsuarioFK"),
            "idInsumoFK": _form_integer("idInsumoFK"),
        }
    )
    service_id = _optional_form_integer("idServicio")
    if service_id is not None:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        _execute(
            f"UPDATE servicio SET {assignments} WHERE idServicio=%s",
            tuple(fields.values()) + (service_id,),
        )
        flash("Servicio actualizado.", "success")
    else:
        _execute(
            f"INSERT INTO servicio ({', '.join(fields)}) "
            f"VALUES ({', '.join(['%s'] * len(fields))})",
            tuple(fields.values()),
        )
        flash("Servicio registrado.", "success")
    return redirect(url_for("listar_servicios"))


@app.route("/servicios/editar/<int:id>")
def servicios_formulario_actualizacion(id):
    service = _fetch_one("SELECT * FROM servicio WHERE idServicio = %s", (id,))
    if service is None:
        abort(404)
    return render_template(
        "servicios/formularioActualizacionServicio.html",
        **_service_form_data(service),
    )


@app.route("/servicios/<int:id>/estado/<estado>", methods=["POST"])
def servicios_cambiar_estado(id, estado):
    if estado not in {"Activo", "Inactivo"}:
        abort(400)
    _execute("UPDATE servicio SET estado = %s WHERE idServicio = %s", (estado, id))
    flash("Estado del servicio actualizado.", "success")
    return redirect(url_for("listar_servicios"))


@app.route("/usuarios/<int:id>/perfil")
def usuarioperfil(id):
    access_response = _require_admin()
    if access_response is not None:
        return access_response
    usuario = _fetch_one(_user_query("WHERE u.idUsuario = %s"), (id,))
    if usuario is None:
        abort(404)
    resumen_insumos, alertas_stock = _inventory_summary()
    return render_template(
        "usuarios/perfilUsuario.html",
        usuario=usuario,
        resumen_insumos=resumen_insumos,
        alertas_stock=alertas_stock,
    )


@app.errorhandler(400)
def handle_bad_request(error):
    return render_template("error.html", mensaje=error.description), 400


@app.errorhandler(404)
def handle_not_found(error):
    return (
        render_template(
            "error.html", mensaje=f"No se encontró el recurso solicitado ({error.code})."
        ),
        404,
    )


@app.errorhandler(503)
def handle_service_unavailable(error):
    return render_template("error.html", mensaje=error.description), 503


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True)