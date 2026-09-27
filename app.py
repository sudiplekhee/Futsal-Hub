import os
import sqlite3
import uuid
import hmac
import hashlib
import base64
import requests

from functools import wraps
from flask_wtf.csrf import CSRFProtect
from datetime import datetime, date, timedelta
from functools import wraps


from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    send_from_directory
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename


# ============================================================
# FLASK CONFIGURATION
# ============================================================

app = Flask(__name__)
# ============================================================
# CSRF PROTECTION
# ============================================================

csrf = CSRFProtect(app)

# ------------------------------------------------------------
# SECRET KEY
# ------------------------------------------------------------
# The secret key is used to protect Flask sessions.
#
# IMPORTANT:
# For local development, the fallback value below is acceptable.
# For production, create an environment variable named:
#
# FUTSAL_SECRET_KEY
#
# Example in Windows PowerShell:
#
# $env:FUTSAL_SECRET_KEY="your-long-random-secret-key"
# ------------------------------------------------------------

app.secret_key = os.environ.get(
    "FUTSAL_SECRET_KEY",
    "dev-only-change-this-secret-key"
)

# Prevent browsers from accessing the session cookie through JavaScript.
app.config["SESSION_COOKIE_HTTPONLY"] = True

# Prevent the session cookie from being sent with cross-site requests.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Set this to True when the website is running over HTTPS in production.
app.config["SESSION_COOKIE_SECURE"] = False

# ============================================================
# LOGIN REQUIRED
# ============================================================

def login_required(view_function):

    @wraps(view_function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:

            flash(
                "Please login first.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        return view_function(
            *args,
            **kwargs
        )

    return wrapper


# ============================================================
# ADMIN REQUIRED
# ============================================================

def admin_required(view_function):

    @wraps(view_function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:

            flash(
                "Please login first.",
                "warning"
            )

            return redirect(
                url_for("admin_login")
            )

        user_id = session.get("user_id")

        conn = get_db()

        user = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                is_admin
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()

        conn.close()

        if user is None:

            session.clear()

            flash(
                "Your account could not be found. Please login again.",
                "warning"
            )

            return redirect(
                url_for("admin_login")
            )

        if user["is_admin"] != 1:

            session.clear()

            flash(
                "Admin access required.",
                "danger"
            )

            return redirect(
                url_for("index")
            )

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["is_admin"] = 1

        return view_function(
            *args,
            **kwargs
        )

    return wrapper
# ============================================================
# PATH CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATABASE = os.path.join(
    BASE_DIR,
    "futsal.db"
)

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.config["MAX_CONTENT_LENGTH"] = (
    10 * 1024 * 1024
)


# ============================================================
# SERVE UPLOADED IMAGES
# ============================================================

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename
    )


# ============================================================
# ALLOWED IMAGE TYPES
# ============================================================

ALLOWED_IMAGE_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp"
}


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


# ============================================================
# DATABASE MIGRATION
#
# This helps older futsal.db files work with the new app.
# ============================================================

def column_exists(
    conn,
    table_name,
    column_name
):

    columns = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(
        column["name"] == column_name
        for column in columns
    )


def add_column_if_missing(
    conn,
    table_name,
    column_name,
    column_definition
):

    if not column_exists(
        conn,
        table_name,
        column_name
    ):

        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name}
            {column_definition}
            """
        )


def initialize_database():

    conn = get_db()

    # --------------------------------------------------------
    # USERS TABLE
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
        """
    )

    # --------------------------------------------------------
    # GROUNDS TABLE
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT,
            price REAL DEFAULT 0,
            contact TEXT,
            opening_time TEXT DEFAULT '06:00',
            closing_time TEXT DEFAULT '22:00',
            description TEXT,
            image TEXT
        )
        """
    )

    # --------------------------------------------------------
    # BOOKINGS TABLE
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ground_id INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            duration INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            payment_status TEXT DEFAULT 'pending',
            payment_method TEXT,
            payment_reference TEXT,
            paid_at TIMESTAMP,

            transaction_uuid TEXT,
            esewa_transaction_code TEXT,
            esewa_product_code TEXT,
            esewa_amount REAL,
            esewa_verified_at TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            FOREIGN KEY (ground_id)
                REFERENCES grounds(id)
                ON DELETE CASCADE,

            UNIQUE (
                ground_id,
                booking_date,
                booking_time
            )
        )
        """
    )

    # --------------------------------------------------------
    # MIGRATE OLD USERS TABLE
    # --------------------------------------------------------

    add_column_if_missing(
        conn,
        "users",
        "is_admin",
        "INTEGER DEFAULT 0"
    )

    # --------------------------------------------------------
    # MIGRATE OLD GROUNDS TABLE
    # --------------------------------------------------------

    add_column_if_missing(
        conn,
        "grounds",
        "location",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "grounds",
        "price",
        "REAL DEFAULT 0"
    )

    add_column_if_missing(
        conn,
        "grounds",
        "contact",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "grounds",
        "opening_time",
        "TEXT DEFAULT '06:00'"
    )

    add_column_if_missing(
        conn,
        "grounds",
        "closing_time",
        "TEXT DEFAULT '22:00'"
    )

    add_column_if_missing(
        conn,
        "grounds",
        "description",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "grounds",
        "image",
        "TEXT"
    )

    # --------------------------------------------------------
    # MIGRATE OLD BOOKINGS TABLE
    # --------------------------------------------------------

    add_column_if_missing(
        conn,
        "bookings",
        "duration",
        "INTEGER DEFAULT 1"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "status",
        "TEXT DEFAULT 'pending'"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "payment_status",
        "TEXT DEFAULT 'pending'"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "payment_method",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "payment_reference",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "paid_at",
        "TIMESTAMP"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "transaction_uuid",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "esewa_transaction_code",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "esewa_product_code",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "esewa_amount",
        "REAL"
    )

    add_column_if_missing(
        conn,
        "bookings",
        "esewa_verified_at",
        "TIMESTAMP"
    )

    # --------------------------------------------------------
    # INDEX
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_bookings_transaction_uuid
        ON bookings(transaction_uuid)
        """
    )

    # --------------------------------------------------------
    # DEFAULT ADMIN
    # --------------------------------------------------------

    admin = conn.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        ("admin@futsal.com",)
    ).fetchone()

    if admin is None:

        conn.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password,
                is_admin
            )
            VALUES (?, ?, ?, 1)
            """,
            (
                "Administrator",
                "admin@futsal.com",
                generate_password_hash(
                    "admin123"
                )
            )
        )

    else:

        conn.execute(
            """
            UPDATE users
            SET is_admin = 1
            WHERE email = ?
            """,
            ("admin@futsal.com",)
        )

    conn.commit()

    conn.close()


# Run database initialization when app starts.
initialize_database()


# ============================================================
# SECURE IMAGE VALIDATION
# ============================================================

ALLOWED_IMAGE_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp"
}

MAX_IMAGE_SIZE = 5 * 1024 * 1024


def allowed_image(filename):

    if not filename:
        return False

    filename = filename.strip()

    if not filename:
        return False

    # Reject suspicious path characters.
    if "/" in filename or "\\" in filename:
        return False

    if filename.startswith("."):
        return False

    if "." not in filename:
        return False

    extension = filename.rsplit(
        ".",
        1
    )[1].lower()

    return extension in ALLOWED_IMAGE_EXTENSIONS


# ============================================================
# SECURE ADMIN REQUIRED DECORATOR
# ============================================================

def admin_required(view_function):

    @wraps(view_function)
    def wrapper(*args, **kwargs):

        # ----------------------------------------------------
        # User must be logged in
        # ----------------------------------------------------

        if "user_id" not in session:

            flash(
                "Please login first.",
                "warning"
            )

            return redirect(
                url_for("admin_login")
            )

        user_id = session.get("user_id")

        # ----------------------------------------------------
        # Verify admin status directly from database
        # ----------------------------------------------------

        conn = get_db()

        user = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                is_admin
            FROM users
            WHERE id = ?
            """,
            (
                user_id,
            )
        ).fetchone()

        conn.close()

        # ----------------------------------------------------
        # User does not exist anymore
        # ----------------------------------------------------

        if user is None:

            session.clear()

            flash(
                "Your account could not be found. Please login again.",
                "warning"
            )

            return redirect(
                url_for("admin_login")
            )

        # ----------------------------------------------------
        # Database says user is NOT an admin
        # ----------------------------------------------------

        if user["is_admin"] != 1:

            session.clear()

            flash(
                "Admin access required.",
                "danger"
            )

            return redirect(
                url_for("index")
            )

        # ----------------------------------------------------
        # Refresh trusted session information
        # ----------------------------------------------------

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["is_admin"] = 1

        # ----------------------------------------------------
        # Allow access
        # ----------------------------------------------------

        return view_function(
            *args,
            **kwargs
        )

    return wrapper


def get_current_user():

    if "user_id" not in session:
        return None

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    conn.close()

    return user


# ============================================================
# TIME HELPERS
# ============================================================

def normalize_time(time_value):

    if not time_value:
        return None

    time_value = str(
        time_value
    ).strip()

    formats = [
        "%H:%M",
        "%H:%M:%S",
        "%I:%M %p",
        "%I:%M%p"
    ]

    for fmt in formats:

        try:

            parsed = datetime.strptime(
                time_value,
                fmt
            )

            return parsed.strftime(
                "%H:%M"
            )

        except ValueError:
            continue

    return None


def time_to_minutes(time_value):

    normalized = normalize_time(
        time_value
    )

    if normalized is None:
        return None

    hour, minute = map(
        int,
        normalized.split(":")
    )

    return (
        hour * 60
        + minute
    )


def format_time_display(time_value):

    normalized = normalize_time(
        time_value
    )

    if normalized is None:
        return time_value

    parsed = datetime.strptime(
        normalized,
        "%H:%M"
    )

    return parsed.strftime(
        "%I:%M %p"
    ).lstrip("0")


def generate_time_slots(
    opening_time,
    closing_time
):

    start_minutes = time_to_minutes(
        opening_time
    )

    end_minutes = time_to_minutes(
        closing_time
    )

    if start_minutes is None:
        start_minutes = 6 * 60

    if end_minutes is None:
        end_minutes = 22 * 60

    slots = []

    current = start_minutes

    while current < end_minutes:

        hour = current // 60
        minute = current % 60

        value = f"{hour:02d}:{minute:02d}"

        slots.append({
            "value": value,
            "label": format_time_display(
                value
            )
        })

        current += 60

    return slots


# ============================================================
# ESEWA FUNCTIONS
# ============================================================

def generate_esewa_signature(
    total_amount,
    transaction_uuid,
    product_code
):

    # eSewa signs the exact string values submitted in the form.
    # Always format the amount to exactly two decimal places so the
    # signed value and the submitted total_amount are identical.
    formatted_amount = f"{float(total_amount):.2f}"

    message = (
        f"total_amount={formatted_amount},"
        f"transaction_uuid={transaction_uuid},"
        f"product_code={product_code}"
    )

    secret_key = ESEWA_SECRET_KEY.encode(
        "utf-8"
    )

    message_bytes = message.encode(
        "utf-8"
    )

    signature = hmac.new(
        secret_key,
        message_bytes,
        hashlib.sha256
    )

    return base64.b64encode(
        signature.digest()
    ).decode(
        "utf-8"
    )


def generate_transaction_uuid():

    timestamp = datetime.now().strftime(
        "%Y%m%d%H%M%S"
    )

    random_part = uuid.uuid4().hex[:8]

    return (
        f"FUTSAL-{timestamp}-{random_part}"
    )


def verify_esewa_transaction(
    transaction_uuid,
    total_amount
):

    try:

        response = requests.get(
            ESEWA_STATUS_URL,
            params={
                "product_code":
                    ESEWA_PRODUCT_CODE,

                "total_amount":
                    str(total_amount),

                "transaction_uuid":
                    transaction_uuid
            },
            timeout=15
        )

        print(
            "eSewa verification HTTP:",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "eSewa response:",
                response.text
            )

            return None

        return response.json()

    except Exception as error:

        print(
            "eSewa verification error:",
            error
        )

        return None
# ============================================================
# ESEWA PAYMENT ROUTE
# ============================================================

@app.route("/esewa/pay/<int:booking_id>")
@login_required
def esewa_pay(booking_id):

    conn = get_db()

    booking = conn.execute(
        """
        SELECT
            bookings.*,
            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS price,
            grounds.price AS ground_price
        FROM bookings
        JOIN grounds ON bookings.ground_id = grounds.id
        WHERE bookings.id = ?
        AND bookings.user_id = ?
        """,
        (booking_id, session["user_id"])
    ).fetchone()

    if booking is None:
        conn.close()
        flash("Booking not found.", "danger")
        return redirect(url_for("my_bookings"))

    if booking["status"] == "cancelled":
        conn.close()
        flash("This booking has been cancelled.", "danger")
        return redirect(url_for("booking_details", booking_id=booking_id))

    if booking["payment_status"] == "paid":
        conn.close()
        flash("This booking has already been paid.", "success")
        return redirect(url_for("booking_details", booking_id=booking_id))

    try:
        price = float(booking["price"] or 0)
        duration = float(booking["duration"] or 1)
    except (TypeError, ValueError):
        conn.close()
        flash("Invalid booking amount.", "danger")
        return redirect(url_for("booking_details", booking_id=booking_id))

    total_amount = round(price * duration, 2)

    if total_amount <= 0:
        conn.close()
        flash("Invalid booking amount.", "danger")
        return redirect(url_for("booking_details", booking_id=booking_id))

    # Always create a NEW UUID for every new eSewa payment attempt.
    transaction_uuid = generate_transaction_uuid()

    # Extra uniqueness check against our database.
    while conn.execute(
        "SELECT id FROM bookings WHERE transaction_uuid = ?",
        (transaction_uuid,)
    ).fetchone() is not None:
        transaction_uuid = generate_transaction_uuid()

    conn.execute(
        """
        UPDATE bookings
        SET
            transaction_uuid = ?,
            esewa_product_code = ?,
            esewa_amount = ?,
            payment_status = 'pending',
            payment_method = 'esewa'
        WHERE id = ?
        AND user_id = ?
        """,
        (
            transaction_uuid,
            ESEWA_PRODUCT_CODE,
            total_amount,
            booking_id,
            session["user_id"]
        )
    )
    conn.commit()
    conn.close()

    # Use exactly the same string for the form and the signature.
    formatted_amount = f"{total_amount:.2f}"

    signature = generate_esewa_signature(
        formatted_amount,
        transaction_uuid,
        ESEWA_PRODUCT_CODE
    )

    signed_field_names = "total_amount,transaction_uuid,product_code"

    return render_template(
        "esewa_payment.html",
        booking=booking,
        amount=formatted_amount,
        tax_amount="0",
        total_amount=total_amount,
        transaction_uuid=transaction_uuid,
        product_code=ESEWA_PRODUCT_CODE,
        product_service_charge=0,
        product_delivery_charge=0,
        success_url=url_for("esewa_success", _external=True),
        failure_url=url_for("esewa_failure", _external=True),
        signed_field_names=signed_field_names,
        signature=signature,
        esewa_payment_url=ESEWA_PAYMENT_URL
    )




# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    conn = get_db()

    grounds = conn.execute(
        """
        SELECT *
        FROM grounds
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "index.html",
        grounds=grounds
    )
# ============================================================
# ESEWA SUCCESS ROUTE
# ============================================================
# ============================================================
# ESEWA SUCCESS ROUTE
# ============================================================

@app.route("/esewa/success")
@login_required
def esewa_success():

    # --------------------------------------------------------
    # Get response from eSewa
    # --------------------------------------------------------

    encoded_data = request.args.get("data")

    if not encoded_data:

        flash(
            "eSewa did not return payment information.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    # --------------------------------------------------------
    # Decode Base64 response
    # --------------------------------------------------------

    try:

        decoded_bytes = base64.b64decode(
            encoded_data,
            validate=True
        )

        decoded_data = decoded_bytes.decode(
            "utf-8"
        )

        esewa_response = json.loads(
            decoded_data
        )

    except Exception as error:

        print(
            "eSewa response decoding error:",
            error
        )

        flash(
            "Invalid response received from eSewa.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    # --------------------------------------------------------
    # Read response fields
    # --------------------------------------------------------

    transaction_uuid = (
        esewa_response.get(
            "transaction_uuid"
        )
    )

    product_code = (
        esewa_response.get(
            "product_code"
        )
    )

    total_amount = (
        esewa_response.get(
            "total_amount"
        )
    )

    transaction_code = (
        esewa_response.get(
            "transaction_code"
        )
    )

    response_status = (
        esewa_response.get(
            "status"
        )
    )

    response_signature = (
        esewa_response.get(
            "signature"
        )
    )

    signed_field_names = (
        esewa_response.get(
            "signed_field_names"
        )
    )

    # --------------------------------------------------------
    # Required response fields
    # --------------------------------------------------------

    if not transaction_uuid:

        flash(
            "Transaction ID was not received from eSewa.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    if not response_signature:

        flash(
            "eSewa response signature was not received.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    if not signed_field_names:

        flash(
            "eSewa signed fields were not received.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    # --------------------------------------------------------
    # Verify product code
    # --------------------------------------------------------

    if product_code != ESEWA_PRODUCT_CODE:

        flash(
            "Invalid eSewa product code.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    # --------------------------------------------------------
    # Verify response signature
    #
    # eSewa returns signed_field_names such as:
    #
    # transaction_code,status,total_amount,
    # transaction_uuid,product_code,signed_field_names
    #
    # The signature must be generated from those exact
    # fields in that exact order.
    # --------------------------------------------------------

    try:

        signed_fields = [
            field.strip()
            for field in signed_field_names.split(",")
            if field.strip()
        ]

        if not signed_fields:

            flash(
                "Invalid eSewa signed fields.",
                "danger"
            )

            return redirect(
                url_for("my_bookings")
            )

        signed_values = []

        for field_name in signed_fields:

            if field_name not in esewa_response:

                print(
                    "Missing signed field:",
                    field_name
                )

                flash(
                    "Invalid eSewa response.",
                    "danger"
                )

                return redirect(
                    url_for("my_bookings")
                )

            value = esewa_response.get(
                field_name
            )

            # eSewa signs the string representation
            # of the returned field values.
            if value is None:

                value = ""

            signed_values.append(
                f"{field_name}={value}"
            )

        signature_message = ",".join(
            signed_values
        )

        expected_signature = base64.b64encode(
            hmac.new(
                ESEWA_SECRET_KEY.encode("utf-8"),
                signature_message.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode("utf-8")

        # Constant-time comparison prevents timing attacks.
        if not hmac.compare_digest(
            expected_signature,
            response_signature
        ):

            print(
                "eSewa signature verification failed."
            )

            print(
                "Expected signature:",
                expected_signature
            )

            print(
                "Received signature:",
                response_signature
            )

            flash(
                "eSewa response could not be verified.",
                "danger"
            )

            return redirect(
                url_for("my_bookings")
            )

    except Exception as error:

        print(
            "eSewa signature verification error:",
            error
        )

        flash(
            "Could not verify the eSewa response.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    # --------------------------------------------------------
    # Find the booking
    # --------------------------------------------------------

    conn = get_db()

    booking = conn.execute(
        """
        SELECT
            bookings.*,
            grounds.name AS ground_name,
            grounds.price AS ground_price
        FROM bookings
        JOIN grounds
            ON bookings.ground_id = grounds.id
        WHERE bookings.transaction_uuid = ?
        AND bookings.user_id = ?
        """,
        (
            transaction_uuid,
            session["user_id"]
        )
    ).fetchone()

    if booking is None:

        conn.close()

        flash(
            "Booking associated with this payment was not found.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # If this booking has already been paid, do not process
    # the same eSewa success response again.
    # --------------------------------------------------------

    if booking["payment_status"] == "paid":

        conn.close()

        flash(
            "This payment has already been verified.",
            "info"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Cancelled bookings cannot be paid
    # --------------------------------------------------------

    if booking["status"] == "cancelled":

        conn.close()

        flash(
            "This booking has been cancelled.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Calculate expected amount from our database
    # --------------------------------------------------------

    try:

        ground_price = float(
            booking["ground_price"] or 0
        )

    except (TypeError, ValueError):

        conn.close()

        flash(
            "Invalid ground price.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    try:

        duration = float(
            booking["duration"] or 1
        )

    except (TypeError, ValueError):

        conn.close()

        flash(
            "Invalid booking duration.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    expected_amount = round(
        ground_price * duration,
        2
    )

    if expected_amount <= 0:

        conn.close()

        flash(
            "Invalid booking amount.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Validate amount returned by eSewa
    # --------------------------------------------------------

    try:

        returned_amount = round(
            float(total_amount),
            2
        )

    except (TypeError, ValueError):

        conn.close()

        flash(
            "Invalid payment amount received from eSewa.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    if abs(
        returned_amount - expected_amount
    ) > 0.01:

        conn.close()

        print(
            "eSewa amount mismatch:",
            "expected=",
            expected_amount,
            "received=",
            returned_amount
        )

        flash(
            "Payment amount does not match the booking amount.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Verify transaction directly with eSewa
    #
    # This is the second verification layer.
    # --------------------------------------------------------

    verification = verify_esewa_transaction(
        transaction_uuid,
        expected_amount
    )

    if not verification:

        conn.close()

        flash(
            "Could not verify the payment with eSewa. Please try again.",
            "warning"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    print(
        "eSewa verification response:",
        verification
    )

    # --------------------------------------------------------
    # Verify status
    # --------------------------------------------------------

    verified_status = (
        verification.get(
            "status"
        )
    )

    if verified_status != "COMPLETE":

        conn.close()

        flash(
            f"eSewa payment status: {verified_status}",
            "warning"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Verify status API product code
    # --------------------------------------------------------

    verified_product_code = (
        verification.get(
            "product_code"
        )
        or verification.get(
            "scd"
        )
    )

    if verified_product_code != ESEWA_PRODUCT_CODE:

        conn.close()

        flash(
            "eSewa verification returned an invalid product code.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Verify status API transaction UUID when provided
    # --------------------------------------------------------

    verified_transaction_uuid = (
        verification.get(
            "transaction_uuid"
        )
    )

    if (
        verified_transaction_uuid
        and
        verified_transaction_uuid != transaction_uuid
    ):

        conn.close()

        flash(
            "eSewa transaction verification failed.",
            "danger"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Verify status API amount when provided
    # --------------------------------------------------------

    verified_amount = (
        verification.get(
            "total_amount"
        )
    )

    if verified_amount is None:

        verified_amount = verification.get(
            "totalAmount"
        )

    if verified_amount is not None:

        try:

            verified_amount = round(
                float(verified_amount),
                2
            )

        except (TypeError, ValueError):

            conn.close()

            flash(
                "Invalid amount returned by eSewa verification.",
                "danger"
            )

            return redirect(
                url_for(
                    "booking_details",
                    booking_id=booking["id"]
                )
            )

        if abs(
            verified_amount - expected_amount
        ) > 0.01:

            conn.close()

            flash(
                "eSewa verified amount does not match the booking amount.",
                "danger"
            )

            return redirect(
                url_for(
                    "booking_details",
                    booking_id=booking["id"]
                )
            )

    # --------------------------------------------------------
    # Get official eSewa reference ID
    # --------------------------------------------------------

    reference_id = (
        verification.get("refId")
        or verification.get("ref_id")
        or transaction_code
    )

    # --------------------------------------------------------
    # Final atomic payment update
    #
    # Only change the booking from unpaid -> paid.
    # This prevents duplicate processing.
    # --------------------------------------------------------

    cursor = conn.execute(
        """
        UPDATE bookings
        SET
            payment_status = 'paid',
            status = 'confirmed',
            payment_method = 'esewa',
            payment_reference = ?,
            esewa_transaction_code = ?,
            esewa_product_code = ?,
            esewa_amount = ?,
            esewa_verified_at = CURRENT_TIMESTAMP,
            paid_at = CURRENT_TIMESTAMP
        WHERE id = ?
        AND user_id = ?
        AND payment_status != 'paid'
        AND status != 'cancelled'
        """,
        (
            reference_id,
            transaction_code,
            ESEWA_PRODUCT_CODE,
            expected_amount,
            booking["id"],
            session["user_id"]
        )
    )

    conn.commit()

    updated_rows = cursor.rowcount

    conn.close()

    # --------------------------------------------------------
    # Check whether payment was actually updated
    # --------------------------------------------------------

    if updated_rows != 1:

        flash(
            "This payment was already processed or could not be updated.",
            "info"
        )

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking["id"]
            )
        )

    # --------------------------------------------------------
    # Success
    # --------------------------------------------------------

    flash(
        "eSewa payment successful and verified!",
        "success"
    )

    return redirect(
        url_for(
            "booking_details",
            booking_id=booking["id"]
        )
    )

# ============================================================
# ESEWA FAILURE ROUTE
# ============================================================

@app.route("/esewa/failure")
@login_required
def esewa_failure():

    encoded_data = request.args.get("data")


    # --------------------------------------------------------
    # Try to identify the booking
    # --------------------------------------------------------

    booking_id = None


    if encoded_data:

        try:

            decoded_bytes = base64.b64decode(
                encoded_data
            )

            decoded_data = decoded_bytes.decode(
                "utf-8"
            )

            import json

            esewa_response = json.loads(
                decoded_data
            )

            transaction_uuid = (
                esewa_response.get(
                    "transaction_uuid"
                )
            )


            if transaction_uuid:

                conn = get_db()

                booking = conn.execute(
                    """
                    SELECT id
                    FROM bookings
                    WHERE transaction_uuid = ?
                    AND user_id = ?
                    """,
                    (
                        transaction_uuid,
                        session["user_id"]
                    )
                ).fetchone()

                conn.close()


                if booking:

                    booking_id = booking["id"]

        except Exception as e:

            print(
                "eSewa failure response error:",
                e
            )


    # --------------------------------------------------------
    # Show failure message
    # --------------------------------------------------------

    flash(
        "eSewa payment was cancelled or unsuccessful.",
        "warning"
    )


    # --------------------------------------------------------
    # Return to booking if possible
    # --------------------------------------------------------

    if booking_id:

        return redirect(
            url_for(
                "booking_details",
                booking_id=booking_id
            )
        )


    return redirect(
        url_for("my_bookings")
    )

# ============================================================
# USER REGISTRATION
# ============================================================

# ============================================================
# USER REGISTRATION
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    # --------------------------------------------------------
    # SHOW REGISTER PAGE
    # --------------------------------------------------------

    if request.method == "GET":

        return render_template(
            "register.html"
        )

    # --------------------------------------------------------
    # GET FORM DATA
    # --------------------------------------------------------

    name = request.form.get(
        "name",
        ""
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    confirm_password = request.form.get(
        "confirm_password",
        ""
    )

    # --------------------------------------------------------
    # VALIDATE NAME
    # --------------------------------------------------------

    if not name:

        flash(
            "Please enter your name.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    if len(name) < 2:

        flash(
            "Name must contain at least 2 characters.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    # --------------------------------------------------------
    # VALIDATE EMAIL
    # --------------------------------------------------------

    if not email:

        flash(
            "Please enter your email.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    if "@" not in email or "." not in email:

        flash(
            "Please enter a valid email address.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    # --------------------------------------------------------
    # VALIDATE PASSWORD
    # --------------------------------------------------------

    if not password:

        flash(
            "Please enter a password.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    if len(password) < 6:

        flash(
            "Password must contain at least 6 characters.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    # --------------------------------------------------------
    # CONFIRM PASSWORD
    # --------------------------------------------------------

    if password != confirm_password:

        flash(
            "Passwords do not match.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    conn = get_db()

    try:

        # ----------------------------------------------------
        # CHECK EXISTING EMAIL
        # ----------------------------------------------------

        existing_user = conn.execute(
            """
            SELECT id
            FROM users
            WHERE LOWER(email) = ?
            """,
            (
                email,
            )
        ).fetchone()

        if existing_user is not None:

            flash(
                "This email is already registered. Please login.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        # ----------------------------------------------------
        # HASH PASSWORD
        # ----------------------------------------------------

        hashed_password = generate_password_hash(
            password
        )

        # ----------------------------------------------------
        # CREATE USER
        # ----------------------------------------------------

        conn.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password,
                is_admin
            )
            VALUES
            (
                ?,
                ?,
                ?,
                0
            )
            """,
            (
                name,
                email,
                hashed_password
            )
        )

        conn.commit()

        # ----------------------------------------------------
        # IMPORTANT
        #
        # DO NOT CREATE SESSION HERE.
        #
        # The user must login manually.
        # ----------------------------------------------------

        flash(
            "Registration successful! Please login to continue.",
            "success"
        )

        # ----------------------------------------------------
        # GO TO LOGIN PAGE
        # ----------------------------------------------------

        return redirect(
            url_for("login")
        )

    # --------------------------------------------------------
    # DUPLICATE EMAIL
    # --------------------------------------------------------

    except sqlite3.IntegrityError as error:

        conn.rollback()

        print(
            "REGISTRATION INTEGRITY ERROR:",
            error
        )

        flash(
            "This email is already registered. Please login.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    # --------------------------------------------------------
    # DATABASE ERROR
    # --------------------------------------------------------

    except sqlite3.Error as error:

        conn.rollback()

        print(
            "REGISTRATION DATABASE ERROR:",
            error
        )

        flash(
            "A database error occurred during registration.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    # --------------------------------------------------------
    # OTHER ERROR
    # --------------------------------------------------------

    except Exception as error:

        conn.rollback()

        print(
            "REGISTRATION ERROR:",
            error
        )

        flash(
            "Something went wrong during registration.",
            "danger"
        )

        return redirect(
            url_for("register")
        )

    finally:

        conn.close()


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (
                email,
            )
        ).fetchone()

        conn.close()

        if (
            user
            and
            check_password_hash(
                user["password"],
                password
            )
        ):

            session.clear()

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["is_admin"] = (
                user["is_admin"]
            )

            flash(
                "Login successful.",
                "success"
            )

            if user["is_admin"] == 1:

                return redirect(
                    url_for(
                        "admin_dashboard"
                    )
                )

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid email or password.",
            "danger"
        )

    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# CUSTOMER DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_db()
    user_id = session["user_id"]

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    total_bookings = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()["count"]

    paid_bookings = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE user_id = ?
        AND payment_status = 'paid'
        """,
        (user_id,)
    ).fetchone()["count"]

    pending_payments = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE user_id = ?
        AND payment_status = 'pending'
        AND status != 'cancelled'
        """,
        (user_id,)
    ).fetchone()["count"]

    total_paid_row = conn.execute(
        """
        SELECT COALESCE(
            SUM(grounds.price * bookings.duration),
            0
        ) AS total
        FROM bookings
        JOIN grounds
            ON bookings.ground_id = grounds.id
        WHERE bookings.user_id = ?
        AND bookings.payment_status = 'paid'
        """,
        (user_id,)
    ).fetchone()

    try:
        total_paid = float(total_paid_row["total"] or 0)
    except (TypeError, ValueError):
        total_paid = 0

    bookings = conn.execute(
        """
        SELECT
            bookings.*,
            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS ground_price,
            grounds.price AS price,
            grounds.image AS ground_image
        FROM bookings
        JOIN grounds
            ON bookings.ground_id = grounds.id
        WHERE bookings.user_id = ?
        ORDER BY
            bookings.created_at DESC,
            bookings.booking_date DESC,
            bookings.booking_time DESC
        LIMIT 5
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        user=user,
        total_bookings=total_bookings,
        paid_bookings=paid_bookings,
        pending_payments=pending_payments,
        total_paid=total_paid,
        bookings=bookings
    )


# ============================================================
# ALL GROUNDS
# ============================================================

@app.route("/grounds")
def grounds():

    conn = get_db()

    grounds_list = conn.execute(
        """
        SELECT *
        FROM grounds
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "grounds.html",
        grounds=grounds_list
    )


# ============================================================
# GROUND DETAILS
# ============================================================

@app.route(
    "/ground/<int:ground_id>"
)
def ground_details(ground_id):

    conn = get_db()

    ground = conn.execute(
        """
        SELECT *
        FROM grounds
        WHERE id = ?
        """,
        (
            ground_id,
        )
    ).fetchone()

    conn.close()

    if ground is None:

        flash(
            "Ground not found.",
            "danger"
        )

        return redirect(
            url_for("grounds")
        )

    return render_template(
        "ground_details.html",
        ground=ground
    )


# ============================================================
# AVAILABLE SLOTS
#
# THIS IS THE IMPORTANT FIX
# ============================================================

@app.route(
    "/available-slots/<int:ground_id>",
    methods=["GET"]
)
@login_required
def available_slots(ground_id):
    """Return booking start times in the format expected by book.html."""

    requested_date = request.args.get("date", "").strip()
    duration_text = request.args.get("duration", "1").strip()

    if not requested_date:
        return jsonify({
            "success": False,
            "message": "Please select a date first.",
            "slots": [],
            "available_slots": []
        }), 400

    try:
        selected_date = datetime.strptime(
            requested_date,
            "%Y-%m-%d"
        ).date()
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Invalid date format.",
            "slots": [],
            "available_slots": []
        }), 400

    if selected_date < date.today():
        return jsonify({
            "success": False,
            "message": "You cannot book a past date.",
            "slots": [],
            "available_slots": []
        }), 400

    try:
        requested_duration = float(duration_text or 1)
    except (TypeError, ValueError):
        requested_duration = 1.0

    if requested_duration not in {1.0, 1.5, 2.0}:
        requested_duration = 1.0

    conn = get_db()

    try:
        ground = conn.execute(
            """
            SELECT id, name, opening_time, closing_time
            FROM grounds
            WHERE id = ?
            """,
            (ground_id,)
        ).fetchone()

        if ground is None:
            return jsonify({
                "success": False,
                "message": "Ground not found.",
                "slots": [],
                "available_slots": []
            }), 404

        opening_minutes = time_to_minutes(
            ground["opening_time"] or "06:00"
        )
        closing_minutes = time_to_minutes(
            ground["closing_time"] or "22:00"
        )

        if opening_minutes is None:
            opening_minutes = 6 * 60
        if closing_minutes is None:
            closing_minutes = 22 * 60

        if closing_minutes <= opening_minutes:
            return jsonify({
                "success": False,
                "message": "Ground operating hours are invalid.",
                "slots": [],
                "available_slots": []
            }), 400

        bookings = conn.execute(
            """
            SELECT booking_time, duration
            FROM bookings
            WHERE ground_id = ?
              AND booking_date = ?
              AND status != 'cancelled'
            """,
            (ground_id, requested_date)
        ).fetchall()

        # Store every existing booking as a minute range.
        blocked_ranges = []

        for booking in bookings:
            existing_start = time_to_minutes(
                booking["booking_time"]
            )

            if existing_start is None:
                continue

            try:
                existing_duration = float(
                    booking["duration"] or 1
                )
            except (TypeError, ValueError):
                existing_duration = 1.0

            existing_duration = max(
                0.5,
                existing_duration
            )

            existing_end = existing_start + int(
                existing_duration * 60
            )

            blocked_ranges.append(
                (existing_start, existing_end)
            )

        # Generate 30-minute start times.
        # Return simple strings in "slots" because the booking page
        # expects strings such as "6:00 AM" rather than dictionaries.
        slots = []
        slot_details = []
        now_minutes = (
            datetime.now().hour * 60
            + datetime.now().minute
        )

        step = 30
        required_minutes = int(
            requested_duration * 60
        )

        current = opening_minutes

        while current + required_minutes <= closing_minutes:
            requested_end = current + required_minutes

            # For today's date, do not offer a time that has already passed.
            if selected_date == date.today() and current <= now_minutes:
                current += step
                continue

            overlaps = False

            for blocked_start, blocked_end in blocked_ranges:
                if (
                    current < blocked_end
                    and requested_end > blocked_start
                ):
                    overlaps = True
                    break

            if not overlaps:
                value = f"{current // 60:02d}:{current % 60:02d}"
                label = format_time_display(value)

                slots.append(label)
                slot_details.append({
                    "value": value,
                    "time": value,
                    "label": label,
                    "display": label,
                    "available": True,
                    "booked": False,
                    "status": "available"
                })

            current += step

        return jsonify({
            "success": True,
            "ground_id": ground_id,
            "date": requested_date,
            "duration": requested_duration,
            "opening_time": normalize_time(
                ground["opening_time"] or "06:00"
            ),
            "closing_time": normalize_time(
                ground["closing_time"] or "22:00"
            ),
            "slots": slots,
            "available_slots": slots,
            "slot_details": slot_details,
            "booked_times": [
                normalize_time(booking["booking_time"])
                for booking in bookings
                if normalize_time(booking["booking_time"]) is not None
            ],
            "message": "Available slots loaded successfully."
        })

    except sqlite3.Error as error:
        print("AVAILABLE SLOTS DATABASE ERROR:", error)
        return jsonify({
            "success": False,
            "message": "Database error while loading time slots.",
            "error": str(error),
            "slots": [],
            "available_slots": []
        }), 500

    except Exception as error:
        print("AVAILABLE SLOTS ERROR:", error)
        return jsonify({
            "success": False,
            "message": "Could not load available time slots.",
            "error": str(error),
            "slots": [],
            "available_slots": []
        }), 500

    finally:
        conn.close()


# ============================================================
# BOOK GROUND
# ============================================================

@app.route("/book/<int:ground_id>", methods=["GET", "POST"])
@login_required
def book_ground(ground_id):

    conn = get_db()

    ground = conn.execute(
        "SELECT * FROM grounds WHERE id = ?",
        (ground_id,)
    ).fetchone()

    if ground is None:
        conn.close()
        flash("Ground not found.", "danger")
        return redirect(url_for("grounds"))

    if request.method == "GET":
        conn.close()
        return render_template("book.html", ground=ground)

    booking_date = request.form.get("booking_date", "").strip()
    booking_time = request.form.get("booking_time", "").strip()
    duration_text = request.form.get("duration", "1").strip()

    try:
        duration = float(duration_text)
    except (TypeError, ValueError):
        conn.close()
        flash("Invalid booking duration.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    allowed_durations = {1.0, 1.5, 2.0}
    if duration not in allowed_durations:
        conn.close()
        flash("Invalid booking duration.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    try:
        selected_date = datetime.strptime(booking_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        conn.close()
        flash("Please select a valid date.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    if selected_date < date.today():
        conn.close()
        flash("You cannot book a past date.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    normalized_time = normalize_time(booking_time)
    if normalized_time is None:
        conn.close()
        flash("Please select a valid time.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    selected_minutes = time_to_minutes(normalized_time)
    opening_minutes = time_to_minutes(ground["opening_time"] or "06:00")
    closing_minutes = time_to_minutes(ground["closing_time"] or "22:00")

    if selected_minutes is None or opening_minutes is None or closing_minutes is None:
        conn.close()
        flash("Invalid ground operating hours.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    requested_end = selected_minutes + int(duration * 60)

    if selected_minutes < opening_minutes or requested_end > closing_minutes:
        conn.close()
        flash("Selected time and duration are outside the ground's operating hours.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    if selected_date == date.today():
        now_minutes = datetime.now().hour * 60 + datetime.now().minute
        if selected_minutes <= now_minutes:
            conn.close()
            flash("You cannot book a past time.", "danger")
            return redirect(url_for("book_ground", ground_id=ground_id))

    existing_bookings = conn.execute(
        """
        SELECT booking_time, duration, status
        FROM bookings
        WHERE ground_id = ?
        AND booking_date = ?
        AND status != 'cancelled'
        """,
        (ground_id, booking_date)
    ).fetchall()

    for existing in existing_bookings:
        existing_start = time_to_minutes(existing["booking_time"])
        if existing_start is None:
            continue
        try:
            existing_duration = float(existing["duration"] or 1)
        except (TypeError, ValueError):
            existing_duration = 1.0
        existing_end = existing_start + int(existing_duration * 60)

        if selected_minutes < existing_end and requested_end > existing_start:
            conn.close()
            flash("The selected time overlaps with an existing booking. Please choose another time.", "danger")
            return redirect(url_for("book_ground", ground_id=ground_id))

    try:
        cursor = conn.execute(
            """
            INSERT INTO bookings
            (user_id, ground_id, booking_date, booking_time, duration, status, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session["user_id"], ground_id, booking_date, normalized_time, duration, "pending", "pending")
        )
        conn.commit()
        booking_id = cursor.lastrowid
        conn.close()

        flash("Your booking was created successfully!", "success")
        return redirect(url_for("booking_success", booking_id=booking_id))

    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        flash("This time slot was just booked by another user. Please select another time.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))

    except sqlite3.Error as error:
        conn.rollback()
        conn.close()
        print("BOOKING DATABASE ERROR:", error)
        flash("Unable to create the booking. Please try again.", "danger")
        return redirect(url_for("book_ground", ground_id=ground_id))


# ============================================================
# BOOKING SUCCESS
# ============================================================

@app.route(
    "/booking-success/<int:booking_id>"
)
@login_required
def booking_success(booking_id):

    conn = get_db()

    booking = conn.execute(
        """
        SELECT
            bookings.*,
            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS ground_price,
            grounds.image AS ground_image
        FROM bookings
        JOIN grounds
            ON bookings.ground_id = grounds.id
        WHERE bookings.id = ?
        AND bookings.user_id = ?
        """,
        (
            booking_id,
            session["user_id"]
        )
    ).fetchone()

    conn.close()

    if booking is None:

        flash(
            "Booking not found.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    return render_template(
        "booking_success.html",
        booking=booking
    )


# ============================================================
# MY BOOKINGS
# ============================================================

@app.route("/my-bookings")
@login_required
def my_bookings():

    conn = get_db()

    bookings = conn.execute(
        """
        SELECT bookings.*,
               grounds.name AS ground_name,
               grounds.location AS ground_location,
               grounds.price AS ground_price,
               grounds.price AS price,
               grounds.image AS ground_image
        FROM bookings
        JOIN grounds ON bookings.ground_id = grounds.id
        WHERE bookings.user_id = ?
        ORDER BY bookings.booking_date DESC, bookings.booking_time DESC, bookings.created_at DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template("my_bookings.html", bookings=bookings)


# ============================================================
# BOOKING DETAILS
# ============================================================

@app.route("/booking/<int:booking_id>")
@login_required
def booking_details(booking_id):

    conn = get_db()

    booking = conn.execute(
        """
        SELECT
            bookings.*,
            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS price,
            grounds.price AS ground_price,
            grounds.contact AS ground_contact,
            grounds.opening_time AS opening_time,
            grounds.closing_time AS closing_time,
            grounds.image AS ground_image
        FROM bookings
        JOIN grounds ON bookings.ground_id = grounds.id
        WHERE bookings.id = ?
        AND bookings.user_id = ?
        """,
        (booking_id, session["user_id"])
    ).fetchone()

    conn.close()

    if booking is None:
        flash("Booking not found.", "danger")
        return redirect(url_for("my_bookings"))

    try:
        price = float(booking["price"] or 0)
    except (TypeError, ValueError):
        price = 0.0

    try:
        duration = float(booking["duration"] or 1)
    except (TypeError, ValueError):
        duration = 1.0

    total_amount = round(price * duration, 2)

    return render_template(
        "booking_details.html",
        booking=booking,
        price=price,
        duration=duration,
        total_amount=total_amount
    )




# ============================================================
# CANCEL BOOKING
# ============================================================
# ============================================================
# CANCEL BOOKING
# ============================================================

@app.route(
    "/cancel-booking/<int:booking_id>",
    methods=["POST"]
)
@login_required
def cancel_booking(booking_id):

    conn = get_db()

    try:

        booking = conn.execute(
            """
            SELECT *
            FROM bookings
            WHERE id = ?
            AND user_id = ?
            """,
            (
                booking_id,
                session["user_id"]
            )
        ).fetchone()

        if booking is None:

            flash(
                "Booking not found.",
                "danger"
            )

            return redirect(
                url_for("my_bookings")
            )

        if booking["status"] == "cancelled":

            flash(
                "Booking is already cancelled.",
                "warning"
            )

            return redirect(
                url_for("my_bookings")
            )

        if booking["payment_status"] == "paid":

            flash(
                "Paid bookings cannot be cancelled online.",
                "warning"
            )

            return redirect(
                url_for(
                    "booking_details",
                    booking_id=booking_id
                )
            )

        conn.execute(
            """
            UPDATE bookings
            SET status = 'cancelled'
            WHERE id = ?
            AND user_id = ?
            """,
            (
                booking_id,
                session["user_id"]
            )
        )

        conn.commit()

        flash(
            "Booking cancelled successfully.",
            "success"
        )

        return redirect(
            url_for("my_bookings")
        )

    except sqlite3.Error as error:

        conn.rollback()

        print(
            "CANCEL BOOKING DATABASE ERROR:",
            error
        )

        flash(
            "Unable to cancel the booking.",
            "danger"
        )

        return redirect(
            url_for("my_bookings")
        )

    finally:

        conn.close()


# ============================================================
# MANUAL PAYMENT
# ============================================================

@app.route("/payment/<int:booking_id>", methods=["GET", "POST"])
@login_required
def payment(booking_id):

    conn = get_db()

    booking = conn.execute(
        """
        SELECT
            bookings.*,
            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS price,
            grounds.price AS ground_price,
            grounds.contact AS ground_contact,
            grounds.opening_time AS opening_time,
            grounds.closing_time AS closing_time,
            grounds.image AS ground_image
        FROM bookings
        JOIN grounds ON bookings.ground_id = grounds.id
        WHERE bookings.id = ?
        AND bookings.user_id = ?
        """,
        (booking_id, session["user_id"])
    ).fetchone()

    if booking is None:
        conn.close()
        flash("Booking not found.", "danger")
        return redirect(url_for("my_bookings"))

    try:
        price = float(booking["price"] or 0)
    except (TypeError, ValueError):
        price = 0.0

    try:
        duration = float(booking["duration"] or 1)
    except (TypeError, ValueError):
        duration = 1.0

    total_amount = round(price * duration, 2)

    if booking["status"] == "cancelled":
        conn.close()
        flash("This booking has been cancelled.", "danger")
        return redirect(url_for("booking_details", booking_id=booking_id))

    if booking["payment_status"] == "paid":
        conn.close()
        flash("This booking has already been paid.", "success")
        return redirect(url_for("booking_details", booking_id=booking_id))

    if request.method == "POST":

        payment_method = request.form.get(
            "payment_method", ""
        ).strip().lower()

        payment_reference = request.form.get(
            "payment_reference", ""
        ).strip()

        allowed_methods = {"cash", "bank", "khalti"}

        if payment_method not in allowed_methods:
            conn.close()
            flash("Please select a valid payment method.", "danger")
            return redirect(url_for("payment", booking_id=booking_id))

        conn.execute(
            """
            UPDATE bookings
            SET
                payment_method = ?,
                payment_reference = ?,
                payment_status = 'submitted'
            WHERE id = ?
            AND user_id = ?
            """,
            (
                payment_method,
                payment_reference,
                booking_id,
                session["user_id"]
            )
        )
        conn.commit()
        conn.close()

        flash(
            "Payment submitted successfully. Waiting for admin verification.",
            "success"
        )

        return redirect(
            url_for("booking_details", booking_id=booking_id)
        )

    conn.close()

    return render_template(
        "payment.html",
        booking=booking,
        price=price,
        duration=duration,
        total_amount=total_amount,
        amount=total_amount
    )




# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/admin/login",
    methods=["GET", "POST"]
)
def admin_login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        admin = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            AND is_admin = 1
            """,
            (
                email,
            )
        ).fetchone()

        conn.close()

        if (
            admin
            and
            check_password_hash(
                admin["password"],
                password
            )
        ):

            session.clear()

            session["user_id"] = admin["id"]

            session["user_name"] = admin["name"]

            session["is_admin"] = 1

            flash(
                "Admin login successful.",
                "success"
            )

            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        flash(
            "Invalid admin credentials.",
            "danger"
        )

    return render_template(
        "admin/login.html"
    )


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route("/admin/logout")
def admin_logout():

    session.clear()

    flash(
        "Admin logged out.",
        "success"
    )

    return redirect(
        url_for("admin_login")
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@admin_required
def admin_dashboard():

    month = request.args.get("month", type=int)
    year = request.args.get("year", type=int)

    today = date.today()

    if month is None or month < 1 or month > 12:
        month = today.month

    if year is None or year < 1:
        year = today.year

    # --------------------------------------------------------
    # Month navigation
    # --------------------------------------------------------

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    if month == 1:
        previous_month = 12
        previous_year = year - 1
    else:
        previous_month = month - 1
        previous_year = year

    # --------------------------------------------------------
    # First day of current month
    # --------------------------------------------------------

    first_day = date(year, month, 1)

    # --------------------------------------------------------
    # Database connection
    # --------------------------------------------------------

    conn = get_db()

    # --------------------------------------------------------
    # Total users
    # --------------------------------------------------------

    total_users = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        WHERE is_admin = 0
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Total grounds
    # --------------------------------------------------------

    total_grounds = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM grounds
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Total bookings
    # --------------------------------------------------------

    total_bookings = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Paid bookings
    # --------------------------------------------------------

    paid_bookings = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE payment_status = 'paid'
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Pending payments
    # --------------------------------------------------------

    pending_payments = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE payment_status IN ('pending', 'submitted')
        AND status != 'cancelled'
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Cancelled bookings
    # --------------------------------------------------------

    cancelled_bookings = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE status = 'cancelled'
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Pending bookings
    # --------------------------------------------------------

    pending_bookings_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE status = 'pending'
        """
    ).fetchone()["count"]

    # --------------------------------------------------------
    # Total revenue
    # --------------------------------------------------------

    total_revenue = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(grounds.price * bookings.duration),
                0
            ) AS total
        FROM bookings
        JOIN grounds
            ON bookings.ground_id = grounds.id
        WHERE bookings.payment_status = 'paid'
        AND bookings.status != 'cancelled'
        """
    ).fetchone()["total"]

    # --------------------------------------------------------
    # Pending payment bookings
    # --------------------------------------------------------

    pending_payment_bookings = conn.execute(
        """
        SELECT
            bookings.*,

            users.name AS user_name,
            users.email AS user_email,

            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS ground_price,
            grounds.price AS price

        FROM bookings

        JOIN users
            ON bookings.user_id = users.id

        JOIN grounds
            ON bookings.ground_id = grounds.id

        WHERE bookings.payment_status IN (
            'pending',
            'submitted'
        )

        AND bookings.status != 'cancelled'

        ORDER BY
            bookings.booking_date ASC,
            bookings.booking_time ASC,
            bookings.id ASC

        LIMIT 10
        """
    ).fetchall()

    # --------------------------------------------------------
    # Recent bookings
    # --------------------------------------------------------

    recent_bookings = conn.execute(
        """
        SELECT
            bookings.*,

            users.name AS user_name,
            users.email AS user_email,

            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS ground_price,
            grounds.price AS price

        FROM bookings

        JOIN users
            ON bookings.user_id = users.id

        JOIN grounds
            ON bookings.ground_id = grounds.id

        ORDER BY bookings.id DESC

        LIMIT 10
        """
    ).fetchall()

    # --------------------------------------------------------
    # Calendar booking counts
    # --------------------------------------------------------

    # Calculate next month
    if month == 12:
        next_month_date = date(year + 1, 1, 1)
    else:
        next_month_date = date(year, month + 1, 1)

    # Number of days in current month
    days_in_month = (
        next_month_date - first_day
    ).days

    # Get booking counts for current month
    calendar_rows = conn.execute(
        """
        SELECT
            booking_date,
            COUNT(*) AS booking_count

        FROM bookings

        WHERE status != 'cancelled'

        AND strftime('%Y', booking_date) = ?

        AND strftime('%m', booking_date) = ?

        GROUP BY booking_date
        """,
        (
            str(year),
            f"{month:02d}"
        )
    ).fetchall()

    conn.close()

    # --------------------------------------------------------
    # Convert calendar rows into dictionary
    # --------------------------------------------------------

    booking_counts = {
        row["booking_date"]: row["booking_count"]
        for row in calendar_rows
    }

    # --------------------------------------------------------
    # Build calendar
    # --------------------------------------------------------

    calendar_days = []

    # Monday = 0
    # Sunday = 6
    first_weekday = first_day.weekday()

    # --------------------------------------------------------
    # Empty cells BEFORE first day
    #
    # IMPORTANT:
    # Never use None here.
    # Every calendar item must be a dictionary.
    # --------------------------------------------------------

    for _ in range(first_weekday):

        calendar_days.append(
            {
                "day": "",
                "date": "",
                "is_today": False,
                "bookings": [],
                "booking_count": 0
            }
        )

    # --------------------------------------------------------
    # Actual days
    # --------------------------------------------------------

    for day_number in range(
        1,
        days_in_month + 1
    ):

        date_string = (
            f"{year:04d}-"
            f"{month:02d}-"
            f"{day_number:02d}"
        )

        is_today = (
            date_string == today.isoformat()
        )

        calendar_days.append(
            {
                "day": day_number,
                "date": date_string,
                "is_today": is_today,
                "bookings": [],
                "booking_count": booking_counts.get(
                    date_string,
                    0
                )
            }
        )

    # --------------------------------------------------------
    # Empty cells AFTER last day
    #
    # Again, use dictionaries instead of None.
    # --------------------------------------------------------

    while len(calendar_days) % 7 != 0:

        calendar_days.append(
            {
                "day": "",
                "date": "",
                "is_today": False,
                "bookings": [],
                "booking_count": 0
            }
        )

    # --------------------------------------------------------
    # Make sure revenue is numeric
    # --------------------------------------------------------

    try:

        total_revenue = float(
            total_revenue or 0
        )

    except (
        TypeError,
        ValueError
    ):

        total_revenue = 0.0

    # --------------------------------------------------------
    # Render dashboard
    # --------------------------------------------------------

    return render_template(
        "admin/dashboard.html",

        total_users=total_users,

        total_grounds=total_grounds,

        total_bookings=total_bookings,

        paid_bookings=paid_bookings,

        pending_payments=pending_payments,

        cancelled_bookings=cancelled_bookings,

        pending_bookings=pending_bookings_count,

        total_revenue=total_revenue,

        pending_payment_bookings=(
            pending_payment_bookings
        ),

        recent_bookings=recent_bookings,

        calendar_days=calendar_days,

        month_name=first_day.strftime(
            "%B"
        ),

        calendar_year=year,

        previous_month=previous_month,

        previous_year=previous_year,

        next_month=next_month,

        next_year=next_year
    )


# ============================================================
# ADMIN CALENDAR
# ============================================================

@app.route("/admin/calendar")
@admin_required
def admin_calendar():

    today = date.today()

    month = request.args.get("month", type=int)
    year = request.args.get("year", type=int)

    if month is None or month < 1 or month > 12:
        month = today.month

    if year is None or year < 1:
        year = today.year

    # --------------------------------------------------------
    # Previous and next month
    # --------------------------------------------------------

    if month == 1:
        previous_month = 12
        previous_year = year - 1
    else:
        previous_month = month - 1
        previous_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    # --------------------------------------------------------
    # First and last day of month
    # --------------------------------------------------------

    first_day = date(year, month, 1)

    if month == 12:
        first_day_next_month = date(year + 1, 1, 1)
    else:
        first_day_next_month = date(year, month + 1, 1)

    last_day = first_day_next_month - timedelta(days=1)

    # --------------------------------------------------------
    # Get bookings for this month
    # --------------------------------------------------------

    conn = get_db()

    bookings = conn.execute(
        """
        SELECT
            bookings.*,
            users.id AS user_id,
            users.name AS user_name,
            users.email AS user_email,
            grounds.id AS ground_id,
            grounds.name AS ground_name,
            grounds.location AS ground_location,
            grounds.price AS ground_price,
            grounds.price AS price,
            grounds.contact AS ground_contact
        FROM bookings
        JOIN users
            ON bookings.user_id = users.id
        JOIN grounds
            ON bookings.ground_id = grounds.id
        WHERE bookings.booking_date >= ?
          AND bookings.booking_date <= ?
        ORDER BY
            bookings.booking_date ASC,
            bookings.booking_time ASC,
            bookings.id ASC
        """,
        (
            first_day.isoformat(),
            last_day.isoformat()
        )
    ).fetchall()

    conn.close()

    # --------------------------------------------------------
    # Group bookings by date
    # --------------------------------------------------------

    bookings_by_date = {}

    for booking in bookings:
        booking_date = booking["booking_date"]

        if booking_date not in bookings_by_date:
            bookings_by_date[booking_date] = []

        bookings_by_date[booking_date].append(booking)

    # --------------------------------------------------------
    # Build calendar
    #
    # IMPORTANT:
    # Every item is a dictionary. We never put None into
    # calendar_days because the template uses day.get(...).
    # --------------------------------------------------------

    calendar_days = []

    # Calendar starts on Sunday.
    # Python weekday(): Monday=0 ... Sunday=6.
    first_weekday = (first_day.weekday() + 1) % 7

    # Empty cells before first day
    for _ in range(first_weekday):
        calendar_days.append({
            "day": "",
            "date": "",
            "is_today": False,
            "bookings": [],
            "booking_count": 0
        })

    # Actual days
    current_day = first_day

    while current_day <= last_day:

        date_string = current_day.isoformat()
        day_bookings = bookings_by_date.get(
            date_string,
            []
        )

        calendar_days.append({
            "day": current_day.day,
            "date": date_string,
            "is_today": current_day == today,
            "bookings": day_bookings,
            "booking_count": len(day_bookings)
        })

        current_day += timedelta(days=1)

    # Empty cells after last day
    while len(calendar_days) % 7 != 0:
        calendar_days.append({
            "day": "",
            "date": "",
            "is_today": False,
            "bookings": [],
            "booking_count": 0
        })

    return render_template(
        "admin/calendar.html",
        calendar_days=calendar_days,
        bookings=bookings,
        month=month,
        year=year,
        month_name=first_day.strftime("%B"),
        calendar_year=year,
        previous_month=previous_month,
        previous_year=previous_year,
        next_month=next_month,
        next_year=next_year
    )


# ============================================================
# ADMIN USERS
# ============================================================

@app.route("/admin/users")
@admin_required
def admin_users():

    conn = get_db()

    users = conn.execute(
        """
        SELECT *
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "admin/users.html",
        users=users
    )


# ============================================================
# ADMIN DELETE USER
# ============================================================

@app.route(
    "/admin/users/delete/<int:user_id>",
    methods=["POST"]
)
@admin_required
def admin_delete_user(user_id):

    if user_id == session["user_id"]:

        flash(
            "You cannot delete your own admin account.",
            "danger"
        )

        return redirect(
            url_for("admin_users")
        )

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            user_id,
        )
    ).fetchone()

    if user is None:

        conn.close()

        flash(
            "User not found.",
            "danger"
        )

        return redirect(
            url_for("admin_users")
        )

    if user["is_admin"] == 1:

        conn.close()

        flash(
            "Admin accounts cannot be deleted.",
            "danger"
        )

        return redirect(
            url_for("admin_users")
        )

    conn.execute(
        """
        DELETE FROM bookings
        WHERE user_id = ?
        """,
        (
            user_id,
        )
    )

    conn.execute(
        """
        DELETE FROM users
        WHERE id = ?
        """,
        (
            user_id,
        )
    )

    conn.commit()

    conn.close()

    flash(
        "User deleted successfully.",
        "success"
    )

    return redirect(
        url_for("admin_users")
    )


# ============================================================
# ADMIN GROUNDS
# ============================================================

@app.route("/admin/grounds")
@admin_required
def admin_grounds():

    conn = get_db()

    grounds_list = conn.execute(
        """
        SELECT *
        FROM grounds
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "admin/grounds.html",
        grounds=grounds_list
    )


# ============================================================
# ADMIN ADD GROUND
# ============================================================

# ============================================================
# ADMIN - ADD GROUND
# ============================================================

@app.route(
    "/admin/grounds/add",
    methods=["GET", "POST"]
)
@admin_required
def admin_add_ground():

    # --------------------------------------------------------
    # SHOW ADD GROUND PAGE
    # --------------------------------------------------------

    if request.method == "GET":
        return render_template(
            "admin/add_ground.html"
        )

    conn = get_db()
    uploaded_filename = None

    try:

        # ----------------------------------------------------
        # GET FORM DATA
        # ----------------------------------------------------

        name = request.form.get(
            "name",
            ""
        ).strip()

        location = request.form.get(
            "location",
            ""
        ).strip()

        contact = request.form.get(
            "contact",
            ""
        ).strip()

        opening_time = request.form.get(
            "opening_time",
            ""
        ).strip()

        closing_time = request.form.get(
            "closing_time",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        price_text = request.form.get(
            "price",
            ""
        ).strip()

        image = request.files.get("image")

        # ----------------------------------------------------
        # VALIDATE NAME
        # ----------------------------------------------------

        if not name:

            flash(
                "Please enter the ground name.",
                "danger"
            )

            return redirect(
                url_for("admin_add_ground")
            )

        # ----------------------------------------------------
        # VALIDATE LOCATION
        # ----------------------------------------------------

        if not location:

            flash(
                "Please enter the ground location.",
                "danger"
            )

            return redirect(
                url_for("admin_add_ground")
            )

        # ----------------------------------------------------
        # VALIDATE PRICE
        # ----------------------------------------------------

        try:

            price = float(price_text)

        except (TypeError, ValueError):

            flash(
                "Please enter a valid price.",
                "danger"
            )

            return redirect(
                url_for("admin_add_ground")
            )

        if price <= 0:

            flash(
                "Price must be greater than 0.",
                "danger"
            )

            return redirect(
                url_for("admin_add_ground")
            )

        # ----------------------------------------------------
        # VALIDATE OPENING TIME
        # ----------------------------------------------------

        if not opening_time:

            opening_time = "06:00"

        # ----------------------------------------------------
        # VALIDATE CLOSING TIME
        # ----------------------------------------------------

        if not closing_time:

            closing_time = "22:00"

        # ----------------------------------------------------
        # VALIDATE TIME FORMAT
        # ----------------------------------------------------

        try:

            opening_obj = datetime.strptime(
                opening_time,
                "%H:%M"
            )

            closing_obj = datetime.strptime(
                closing_time,
                "%H:%M"
            )

        except ValueError:

            flash(
                "Please enter valid opening and closing times.",
                "danger"
            )

            return redirect(
                url_for("admin_add_ground")
            )

        # ----------------------------------------------------
        # CHECK OPERATING HOURS
        # ----------------------------------------------------

        if opening_obj >= closing_obj:

            flash(
                "Closing time must be later than opening time.",
                "danger"
            )

            return redirect(
                url_for("admin_add_ground")
            )

        # ----------------------------------------------------
        # IMAGE UPLOAD
        # ----------------------------------------------------

        image_filename = None

        if image and image.filename:

            original_filename = image.filename.strip()

            if not original_filename:

                flash(
                    "Invalid image file.",
                    "danger"
                )

                return redirect(
                    url_for("admin_add_ground")
                )

            if not allowed_image(original_filename):

                flash(
                    "Invalid image type. Allowed: JPG, JPEG, PNG, GIF, WEBP.",
                    "danger"
                )

                return redirect(
                    url_for("admin_add_ground")
                )

            # ------------------------------------------------
            # CHECK IMAGE SIZE
            # ------------------------------------------------

            image.seek(0, os.SEEK_END)

            image_size = image.tell()

            image.seek(0)

            if image_size > MAX_IMAGE_SIZE:

                flash(
                    "Image must be smaller than 5 MB.",
                    "danger"
                )

                return redirect(
                    url_for("admin_add_ground")
                )

            if image_size == 0:

                flash(
                    "The uploaded image is empty.",
                    "danger"
                )

                return redirect(
                    url_for("admin_add_ground")
                )

            # ------------------------------------------------
            # CREATE SAFE SERVER-SIDE FILENAME
            # ------------------------------------------------

            safe_original_name = secure_filename(
                original_filename
            )

            if not safe_original_name:

                flash(
                    "Invalid image filename.",
                    "danger"
                )

                return redirect(
                    url_for("admin_add_ground")
                )

            extension = safe_original_name.rsplit(
                ".",
                1
            )[1].lower()

            unique_name = (
                uuid.uuid4().hex
                + "."
                + extension
            )

            image_filename = unique_name

            upload_path = os.path.join(
                UPLOAD_FOLDER,
                image_filename
            )

            # ------------------------------------------------
            # MAKE SURE UPLOAD DIRECTORY EXISTS
            # ------------------------------------------------

            os.makedirs(
                UPLOAD_FOLDER,
                exist_ok=True
            )

            # ------------------------------------------------
            # SAVE IMAGE
            # ------------------------------------------------

            image.save(upload_path)

            uploaded_filename = upload_path

        # ----------------------------------------------------
        # INSERT GROUND INTO DATABASE
        # ----------------------------------------------------

        cursor = conn.execute(
            """
            INSERT INTO grounds (
                name,
                location,
                price,
                contact,
                opening_time,
                closing_time,
                description,
                image
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                location,
                price,
                contact,
                opening_time,
                closing_time,
                description,
                image_filename
            )
        )

        conn.commit()

        ground_id = cursor.lastrowid

        print("")
        print("========================================")
        print("GROUND ADDED SUCCESSFULLY")
        print("========================================")
        print("GROUND ID:", ground_id)
        print("NAME:", name)
        print("LOCATION:", location)
        print("PRICE:", price)
        print("OPENING:", opening_time)
        print("CLOSING:", closing_time)
        print("IMAGE:", image_filename)
        print("========================================")
        print("")

        flash(
            "Ground added successfully!",
            "success"
        )

        return redirect(
            url_for("admin_grounds")
        )

    except sqlite3.Error as error:

        conn.rollback()

        # -----------------------------------------------
        # DELETE IMAGE IF DATABASE INSERT FAILED
        # -----------------------------------------------

        if uploaded_filename:

            try:

                if os.path.exists(
                    uploaded_filename
                ):

                    os.remove(
                        uploaded_filename
                    )

            except OSError:

                pass

        print("")
        print("========================================")
        print("ADD GROUND DATABASE ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "Unable to add the ground because of a database error.",
            "danger"
        )

        return redirect(
            url_for("admin_add_ground")
        )

    except Exception as error:

        conn.rollback()

        # -----------------------------------------------
        # DELETE IMAGE IF SOMETHING ELSE FAILED
        # -----------------------------------------------

        if uploaded_filename:

            try:

                if os.path.exists(
                    uploaded_filename
                ):

                    os.remove(
                        uploaded_filename
                    )

            except OSError:

                pass

        print("")
        print("========================================")
        print("ADD GROUND ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "Unable to add the ground.",
            "danger"
        )

        return redirect(
            url_for("admin_add_ground")
        )

    finally:

        conn.close()


# ============================================================
# ADMIN EDIT GROUND
# ============================================================

# ============================================================
# ADMIN - EDIT GROUND
# ============================================================

@app.route(
    "/admin/grounds/edit/<int:ground_id>",
    methods=["GET", "POST"]
)
@admin_required
def admin_edit_ground(ground_id):

    conn = get_db()
    uploaded_filename = None

    try:

        # ----------------------------------------------------
        # FIND GROUND
        # ----------------------------------------------------

        ground = conn.execute(
            """
            SELECT *
            FROM grounds
            WHERE id = ?
            """,
            (ground_id,)
        ).fetchone()

        if ground is None:

            flash(
                "Ground not found.",
                "danger"
            )

            return redirect(
                url_for("admin_grounds")
            )

        # ----------------------------------------------------
        # GET REQUEST
        # ----------------------------------------------------

        if request.method == "GET":

            return render_template(
                "admin/edit_ground.html",
                ground=ground
            )

        # ----------------------------------------------------
        # GET FORM DATA
        # ----------------------------------------------------

        name = request.form.get(
            "name",
            ""
        ).strip()

        location = request.form.get(
            "location",
            ""
        ).strip()

        contact = request.form.get(
            "contact",
            ""
        ).strip()

        opening_time = request.form.get(
            "opening_time",
            ""
        ).strip()

        closing_time = request.form.get(
            "closing_time",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        price_text = request.form.get(
            "price",
            ""
        ).strip()

        image = request.files.get("image")

        # ----------------------------------------------------
        # VALIDATE NAME
        # ----------------------------------------------------

        if not name:

            flash(
                "Please enter the ground name.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_edit_ground",
                    ground_id=ground_id
                )
            )

        # ----------------------------------------------------
        # VALIDATE LOCATION
        # ----------------------------------------------------

        if not location:

            flash(
                "Please enter the ground location.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_edit_ground",
                    ground_id=ground_id
                )
            )

        # ----------------------------------------------------
        # VALIDATE PRICE
        # ----------------------------------------------------

        try:

            price = float(price_text)

        except (TypeError, ValueError):

            flash(
                "Please enter a valid price.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_edit_ground",
                    ground_id=ground_id
                )
            )

        if price <= 0:

            flash(
                "Price must be greater than 0.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_edit_ground",
                    ground_id=ground_id
                )
            )

        # ----------------------------------------------------
        # DEFAULT TIMES
        # ----------------------------------------------------

        if not opening_time:

            opening_time = "06:00"

        if not closing_time:

            closing_time = "22:00"

        # ----------------------------------------------------
        # VALIDATE TIMES
        # ----------------------------------------------------

        try:

            opening_obj = datetime.strptime(
                opening_time,
                "%H:%M"
            )

            closing_obj = datetime.strptime(
                closing_time,
                "%H:%M"
            )

        except ValueError:

            flash(
                "Please enter valid opening and closing times.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_edit_ground",
                    ground_id=ground_id
                )
            )

        # ----------------------------------------------------
        # CHECK TIME ORDER
        # ----------------------------------------------------

        if opening_obj >= closing_obj:

            flash(
                "Closing time must be later than opening time.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_edit_ground",
                    ground_id=ground_id
                )
            )

        # ----------------------------------------------------
        # KEEP OLD IMAGE
        # ----------------------------------------------------

        image_filename = ground["image"]

        # ----------------------------------------------------
        # NEW IMAGE UPLOAD
        # ----------------------------------------------------

        if image and image.filename:

            original_filename = image.filename.strip()

            if not original_filename:

                flash(
                    "Invalid image file.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_edit_ground",
                        ground_id=ground_id
                    )
                )

            if not allowed_image(original_filename):

                flash(
                    "Invalid image type. Allowed: JPG, JPEG, PNG, GIF, WEBP.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_edit_ground",
                        ground_id=ground_id
                    )
                )

            # ------------------------------------------------
            # CHECK SIZE
            # ------------------------------------------------

            image.seek(
                0,
                os.SEEK_END
            )

            image_size = image.tell()

            image.seek(0)

            if image_size > MAX_IMAGE_SIZE:

                flash(
                    "Image must be smaller than 5 MB.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_edit_ground",
                        ground_id=ground_id
                    )
                )

            if image_size == 0:

                flash(
                    "The uploaded image is empty.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_edit_ground",
                        ground_id=ground_id
                    )
                )

            # ------------------------------------------------
            # SAFE FILENAME
            # ------------------------------------------------

            safe_original_name = secure_filename(
                original_filename
            )

            if not safe_original_name:

                flash(
                    "Invalid image filename.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_edit_ground",
                        ground_id=ground_id
                    )
                )

            extension = safe_original_name.rsplit(
                ".",
                1
            )[1].lower()

            new_filename = (
                uuid.uuid4().hex
                + "."
                + extension
            )

            upload_path = os.path.join(
                UPLOAD_FOLDER,
                new_filename
            )

            os.makedirs(
                UPLOAD_FOLDER,
                exist_ok=True
            )

            # ------------------------------------------------
            # SAVE NEW IMAGE
            # ------------------------------------------------

            image.save(
                upload_path
            )

            uploaded_filename = upload_path

            image_filename = new_filename

        # ----------------------------------------------------
        # UPDATE DATABASE
        # ----------------------------------------------------

        conn.execute(
            """
            UPDATE grounds
            SET
                name = ?,
                location = ?,
                price = ?,
                contact = ?,
                opening_time = ?,
                closing_time = ?,
                description = ?,
                image = ?
            WHERE id = ?
            """,
            (
                name,
                location,
                price,
                contact,
                opening_time,
                closing_time,
                description,
                image_filename,
                ground_id
            )
        )

        conn.commit()

        # ----------------------------------------------------
        # DELETE OLD IMAGE
        # ----------------------------------------------------

        old_image = ground["image"]

        if (
            uploaded_filename
            and old_image
            and old_image != image_filename
        ):

            old_image_path = os.path.join(
                UPLOAD_FOLDER,
                old_image
            )

            try:

                if os.path.exists(
                    old_image_path
                ):

                    os.remove(
                        old_image_path
                    )

            except OSError as error:

                print(
                    "OLD IMAGE DELETE ERROR:",
                    error
                )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print("")
        print("========================================")
        print("GROUND UPDATED SUCCESSFULLY")
        print("========================================")
        print("GROUND ID:", ground_id)
        print("NAME:", name)
        print("LOCATION:", location)
        print("PRICE:", price)
        print("OPENING:", opening_time)
        print("CLOSING:", closing_time)
        print("IMAGE:", image_filename)
        print("========================================")
        print("")

        flash(
            "Ground updated successfully!",
            "success"
        )

        return redirect(
            url_for("admin_grounds")
        )

    except sqlite3.Error as error:

        conn.rollback()

        # ----------------------------------------------------
        # DELETE NEW IMAGE IF DATABASE UPDATE FAILED
        # ----------------------------------------------------

        if uploaded_filename:

            try:

                if os.path.exists(
                    uploaded_filename
                ):

                    os.remove(
                        uploaded_filename
                    )

            except OSError:

                pass

        print("")
        print("========================================")
        print("EDIT GROUND DATABASE ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "Unable to update the ground because of a database error.",
            "danger"
        )

        return redirect(
            url_for(
                "admin_edit_ground",
                ground_id=ground_id
            )
        )

    except Exception as error:

        conn.rollback()

        if uploaded_filename:

            try:

                if os.path.exists(
                    uploaded_filename
                ):

                    os.remove(
                        uploaded_filename
                    )

            except OSError:

                pass

        print("")
        print("========================================")
        print("EDIT GROUND ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "Unable to update the ground.",
            "danger"
        )

        return redirect(
            url_for(
                "admin_edit_ground",
                ground_id=ground_id
            )
        )

    finally:

        conn.close()


# ============================================================
# ADMIN DELETE GROUND
# ============================================================

# ============================================================
# ADMIN - DELETE GROUND
# ============================================================

@app.route(
    "/admin/grounds/delete/<int:ground_id>",
    methods=["POST"]
)
@admin_required
def admin_delete_ground(ground_id):

    conn = get_db()

    try:

        # ----------------------------------------------------
        # FIND GROUND
        # ----------------------------------------------------

        ground = conn.execute(
            """
            SELECT *
            FROM grounds
            WHERE id = ?
            """,
            (ground_id,)
        ).fetchone()

        if ground is None:

            flash(
                "Ground not found.",
                "danger"
            )

            return redirect(
                url_for("admin_grounds")
            )

        # ----------------------------------------------------
        # CHECK FOR BOOKINGS
        # ----------------------------------------------------

        booking_count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM bookings
            WHERE ground_id = ?
            """,
            (ground_id,)
        ).fetchone()

        booking_count = (
            booking_count_row["count"]
            or 0
        )

        # ----------------------------------------------------
        # DO NOT DELETE IF BOOKINGS EXIST
        # ----------------------------------------------------

        if booking_count > 0:

            flash(
                "This ground cannot be deleted because it has existing bookings.",
                "warning"
            )

            return redirect(
                url_for("admin_grounds")
            )

        # ----------------------------------------------------
        # SAVE OLD IMAGE NAME
        # ----------------------------------------------------

        old_image = ground["image"]

        # ----------------------------------------------------
        # DELETE GROUND
        # ----------------------------------------------------

        conn.execute(
            """
            DELETE FROM grounds
            WHERE id = ?
            """,
            (ground_id,)
        )

        conn.commit()

        # ----------------------------------------------------
        # DELETE IMAGE FILE
        # ----------------------------------------------------

        if old_image:

            old_image_path = os.path.join(
                UPLOAD_FOLDER,
                old_image
            )

            try:

                if os.path.exists(
                    old_image_path
                ):

                    os.remove(
                        old_image_path
                    )

            except OSError as error:

                print(
                    "GROUND IMAGE DELETE ERROR:",
                    error
                )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print("")
        print("========================================")
        print("GROUND DELETED SUCCESSFULLY")
        print("========================================")
        print("GROUND ID:", ground_id)
        print("GROUND NAME:", ground["name"])
        print("========================================")
        print("")

        flash(
            "Ground deleted successfully.",
            "success"
        )

        return redirect(
            url_for("admin_grounds")
        )

    except sqlite3.IntegrityError as error:

        conn.rollback()

        print("")
        print("========================================")
        print("GROUND DELETE INTEGRITY ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "This ground cannot be deleted because it is being used by another record.",
            "danger"
        )

        return redirect(
            url_for("admin_grounds")
        )

    except sqlite3.Error as error:

        conn.rollback()

        print("")
        print("========================================")
        print("GROUND DELETE DATABASE ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "Unable to delete the ground.",
            "danger"
        )

        return redirect(
            url_for("admin_grounds")
        )

    except Exception as error:

        conn.rollback()

        print("")
        print("========================================")
        print("GROUND DELETE ERROR")
        print("========================================")
        print(error)
        print("========================================")
        print("")

        flash(
            "An unexpected error occurred while deleting the ground.",
            "danger"
        )

        return redirect(
            url_for("admin_grounds")
        )

    finally:

        conn.close()


# ============================================================
# ADMIN BOOKINGS
# ============================================================

@app.route("/admin/bookings")
@admin_required
def admin_bookings():

    search = request.args.get("search", "").strip()
    payment_status = request.args.get("payment_status", "").strip().lower()

    conn = get_db()

    total_bookings = conn.execute(
        "SELECT COUNT(*) AS count FROM bookings"
    ).fetchone()["count"]

    pending_payments = conn.execute(
        """SELECT COUNT(*) AS count FROM bookings
           WHERE payment_status IN ('pending', 'submitted')
           AND status != 'cancelled'"""
    ).fetchone()["count"]

    paid_bookings = conn.execute(
        "SELECT COUNT(*) AS count FROM bookings WHERE payment_status = 'paid'"
    ).fetchone()["count"]

    cancelled_bookings = conn.execute(
        "SELECT COUNT(*) AS count FROM bookings WHERE status = 'cancelled'"
    ).fetchone()["count"]

    query = """
        SELECT bookings.*,
               users.name AS user_name,
               users.email AS user_email,
               grounds.name AS ground_name,
               grounds.location AS ground_location,
               grounds.price AS ground_price,
               grounds.price AS price
        FROM bookings
        JOIN users ON bookings.user_id = users.id
        JOIN grounds ON bookings.ground_id = grounds.id
        WHERE 1 = 1
    """
    params = []

    if search:
        query += """
            AND (users.name LIKE ? OR users.email LIKE ?
                 OR grounds.name LIKE ? OR grounds.location LIKE ?
                 OR bookings.booking_date LIKE ? OR bookings.booking_time LIKE ?)
        """
        value = f"%{search}%"
        params.extend([value] * 6)

    allowed = {"paid", "pending", "submitted", "rejected"}
    if payment_status in allowed:
        query += " AND bookings.payment_status = ? "
        params.append(payment_status)

    query += """
        ORDER BY bookings.booking_date DESC,
                 bookings.booking_time DESC,
                 bookings.created_at DESC
    """

    bookings = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "admin/bookings.html",
        bookings=bookings,
        total_bookings=total_bookings,
        pending_payments=pending_payments,
        paid_bookings=paid_bookings,
        cancelled_bookings=cancelled_bookings,
        search=search,
        payment_status=payment_status
    )


# ============================================================
# ADMIN BOOKING DETAILS
# ============================================================
# ============================================================
# ADMIN BOOKING DETAILS
# ============================================================

@app.route("/admin/bookings/<int:booking_id>")
@admin_required
def admin_booking_details(booking_id):

    conn = get_db()

    booking = conn.execute(
        """
        SELECT
            bookings.*,

            users.name AS user_name,
            users.email AS user_email,

            grounds.name AS ground_name,
            grounds.location AS ground_location,

            -- Provide BOTH names because different templates
            -- may use either price or ground_price.
            grounds.price AS price,
            grounds.price AS ground_price,

            grounds.image AS ground_image,
            grounds.contact AS ground_contact,
            grounds.opening_time AS opening_time,
            grounds.closing_time AS closing_time

        FROM bookings

        JOIN users
            ON bookings.user_id = users.id

        JOIN grounds
            ON bookings.ground_id = grounds.id

        WHERE bookings.id = ?
        """,
        (
            booking_id,
        )
    ).fetchone()

    conn.close()

    if booking is None:

        flash(
            "Booking not found.",
            "danger"
        )

        return redirect(
            url_for("admin_bookings")
        )

    # --------------------------------------------------------
    # Safely calculate price and total amount
    # --------------------------------------------------------

    try:
        price = float(
            booking["price"] or 0
        )
    except (TypeError, ValueError):
        price = 0.0

    try:
        duration = float(
            booking["duration"] or 1
        )
    except (TypeError, ValueError):
        duration = 1.0

    total_amount = round(
        price * duration,
        2
    )

    return render_template(
        "admin/booking_details.html",

        booking=booking,

        # Extra values available to the template
        price=price,
        duration=duration,
        total_amount=total_amount
    )


# ============================================================
# ADMIN CANCEL BOOKING
# ============================================================

# ============================================================
# ADMIN - CANCEL BOOKING
# ============================================================

@app.route(
    "/admin/bookings/cancel/<int:booking_id>",
    methods=["POST"]
)
@admin_required
def admin_cancel_booking(booking_id):

    conn = get_db()

    try:

        booking = conn.execute(
            """
            SELECT *
            FROM bookings
            WHERE id = ?
            """,
            (booking_id,)
        ).fetchone()

        if booking is None:

            flash(
                "Booking not found.",
                "danger"
            )

            return redirect(
                url_for("admin_bookings")
            )

        # ----------------------------------------------------
        # ALREADY CANCELLED
        # ----------------------------------------------------

        if booking["status"] == "cancelled":

            flash(
                "This booking is already cancelled.",
                "warning"
            )

            return redirect(
                url_for("admin_bookings")
            )

        # ----------------------------------------------------
        # CANCEL BOOKING
        # ----------------------------------------------------

        cursor = conn.execute(
            """
            UPDATE bookings
            SET
                status = 'cancelled'
            WHERE id = ?
            AND status != 'cancelled'
            """,
            (booking_id,)
        )

        conn.commit()

        if cursor.rowcount != 1:

            flash(
                "The booking could not be cancelled.",
                "danger"
            )

            return redirect(
                url_for("admin_bookings")
            )

        flash(
            "Booking cancelled successfully.",
            "success"
        )

        return redirect(
            url_for("admin_bookings")
        )

    except sqlite3.Error as error:

        conn.rollback()

        print(
            "ADMIN CANCEL BOOKING ERROR:",
            error
        )

        flash(
            "Unable to cancel the booking.",
            "danger"
        )

        return redirect(
            url_for("admin_bookings")
        )

    finally:

        conn.close()


# ============================================================
# ADMIN CONFIRM PAYMENT
# ============================================================

# ============================================================
# ADMIN - CONFIRM PAYMENT
# ============================================================

@app.route(
    "/admin/payment/confirm/<int:booking_id>",
    methods=["POST"]
)
@admin_required
def admin_confirm_payment(booking_id):

    conn = get_db()

    try:

        booking = conn.execute(
            """
            SELECT
                bookings.*,
                users.name AS user_name,
                users.email AS user_email,
                grounds.name AS ground_name,
                grounds.price AS ground_price
            FROM bookings
            JOIN users
                ON bookings.user_id = users.id
            JOIN grounds
                ON bookings.ground_id = grounds.id
            WHERE bookings.id = ?
            """,
            (booking_id,)
        ).fetchone()

        if booking is None:

            flash(
                "Booking not found.",
                "danger"
            )

            return redirect(
                url_for("admin_bookings")
            )

        # ----------------------------------------------------
        # CANCELLED BOOKING
        # ----------------------------------------------------

        if booking["status"] == "cancelled":

            flash(
                "A cancelled booking cannot be confirmed.",
                "warning"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # ALREADY PAID
        # ----------------------------------------------------

        if booking["payment_status"] == "paid":

            flash(
                "This payment has already been confirmed.",
                "info"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # VALID PAYMENT STATUS
        # ----------------------------------------------------

        if booking["payment_status"] not in (
            "pending",
            "submitted"
        ):

            flash(
                "This payment cannot be confirmed.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # CALCULATE TOTAL
        # ----------------------------------------------------

        try:

            price = float(
                booking["ground_price"] or 0
            )

        except (TypeError, ValueError):

            price = 0.0

        try:

            duration = float(
                booking["duration"] or 1
            )

        except (TypeError, ValueError):

            duration = 1.0

        total_amount = price * duration

        # ----------------------------------------------------
        # UPDATE PAYMENT
        # ----------------------------------------------------

        cursor = conn.execute(
            """
            UPDATE bookings
            SET
                payment_status = 'paid',
                status = 'confirmed',
                paid_at = CURRENT_TIMESTAMP,
                esewa_amount = CASE
                    WHEN payment_method = 'esewa'
                    THEN ?
                    ELSE esewa_amount
                END
            WHERE id = ?
            AND payment_status IN ('pending', 'submitted')
            AND status != 'cancelled'
            """,
            (
                total_amount,
                booking_id
            )
        )

        conn.commit()

        if cursor.rowcount != 1:

            flash(
                "The payment could not be confirmed.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        flash(
            "Payment confirmed successfully.",
            "success"
        )

        return redirect(
            url_for("admin_bookings")
        )

    except sqlite3.Error as error:

        conn.rollback()

        print(
            "ADMIN CONFIRM PAYMENT ERROR:",
            error
        )

        flash(
            "Unable to confirm the payment.",
            "danger"
        )

        return redirect(
            url_for("admin_bookings")
        )

    finally:

        conn.close()

# ============================================================
# ADMIN REJECT PAYMENT
# ============================================================

# ============================================================
# ADMIN - REJECT PAYMENT
# ============================================================

@app.route(
    "/admin/payment/reject/<int:booking_id>",
    methods=["POST"]
)
@admin_required
def admin_reject_payment(booking_id):

    conn = get_db()

    try:

        booking = conn.execute(
            """
            SELECT
                bookings.*,
                users.name AS user_name,
                users.email AS user_email,
                grounds.name AS ground_name
            FROM bookings
            JOIN users
                ON bookings.user_id = users.id
            JOIN grounds
                ON bookings.ground_id = grounds.id
            WHERE bookings.id = ?
            """,
            (booking_id,)
        ).fetchone()

        if booking is None:

            flash(
                "Booking not found.",
                "danger"
            )

            return redirect(
                url_for("admin_bookings")
            )

        # ----------------------------------------------------
        # CANCELLED
        # ----------------------------------------------------

        if booking["status"] == "cancelled":

            flash(
                "Payment for a cancelled booking cannot be rejected.",
                "warning"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # ALREADY PAID
        # ----------------------------------------------------

        if booking["payment_status"] == "paid":

            flash(
                "A paid payment cannot be rejected.",
                "warning"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # ALREADY REJECTED
        # ----------------------------------------------------

        if booking["payment_status"] == "rejected":

            flash(
                "This payment has already been rejected.",
                "info"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # VALID STATUS
        # ----------------------------------------------------

        if booking["payment_status"] not in (
            "pending",
            "submitted"
        ):

            flash(
                "This payment cannot be rejected.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_booking_details",
                    booking_id=booking_id
                )
            )

        # ----------------------------------------------------
        # REJECT
        # ----------------------------------------------------

        cursor = conn.execute(
            """
            UPDATE bookings
            SET
                payment_status = 'rejected'
            WHERE id = ?
            AND payment_status IN ('pending', 'submitted')
            AND status != 'cancelled'
            """,
            (booking_id,)
        )

        conn.commit()

        if cursor.rowcount != 1:

            flash(
                "The payment could not be rejected.",
                "danger"
            )

            return redirect(
                url_for("admin_bookings")
            )

        flash(
            "Payment rejected successfully.",
            "warning"
        )

        return redirect(
            url_for("admin_bookings")
        )

    except sqlite3.Error as error:

        conn.rollback()

        print(
            "ADMIN REJECT PAYMENT ERROR:",
            error
        )

        flash(
            "Unable to reject the payment.",
            "danger"
        )

        return redirect(
            url_for("admin_bookings")
        )

    finally:

        conn.close()


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


@app.errorhandler(413)
def file_too_large(error):

    flash(
        "File is too large. Maximum size is 10 MB.",
        "danger"
    )

    return redirect(
        url_for("index")
    )
# ============================================================
# GLOBAL ERROR HANDLERS
# ============================================================

@app.errorhandler(400)
def bad_request(error):

    return render_template(
        "error.html",
        error_code=400
    ), 400


@app.errorhandler(403)
def forbidden(error):

    return render_template(
        "error.html",
        error_code=403
    ), 403


@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "error.html",
        error_code=404
    ), 404


@app.errorhandler(500)
def internal_server_error(error):

    # Print the real error in the terminal
    # so the developer can still debug it.
    print(
        "INTERNAL SERVER ERROR:",
        error
    )

    return render_template(
        "error.html",
        error_code=500
    ), 500

# ============================================================
# START APPLICATION
# ============================================================

# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=False,
        host="127.0.0.1",
        port=5000
    )