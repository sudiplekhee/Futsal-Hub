import sqlite3
import os
from werkzeug.security import generate_password_hash


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE = os.path.join(
    BASE_DIR,
    "futsal.db"
)


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    conn = sqlite3.connect(DATABASE)

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


# ============================================================
# ADD COLUMN IF IT DOES NOT EXIST
# ============================================================

def add_column_if_not_exists(
    conn,
    table_name,
    column_name,
    column_definition
):

    cursor = conn.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]

    if column_name not in columns:

        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name}
            {column_definition}
            """
        )

        print(
            f"Added column: {table_name}.{column_name}"
        )


# ============================================================
# CREATE DATABASE
# ============================================================

def setup_database():

    conn = get_connection()

    # ========================================================
    # USERS TABLE
    # ========================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            email TEXT NOT NULL UNIQUE,

            password TEXT NOT NULL,

            is_admin INTEGER DEFAULT 0

        )
        """
    )


    # ========================================================
    # GROUNDS TABLE
    # ========================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grounds (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            location TEXT NOT NULL,

            price REAL NOT NULL,

            contact TEXT,

            opening_time TEXT,

            closing_time TEXT,

            description TEXT,

            image TEXT

        )
        """
    )


    # ========================================================
    # BOOKINGS TABLE
    # ========================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            ground_id INTEGER NOT NULL,

            booking_date TEXT NOT NULL,

            booking_time TEXT NOT NULL,

            duration INTEGER DEFAULT 1,

            status TEXT DEFAULT 'confirmed',

            created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP,

            payment_status TEXT
                DEFAULT 'pending',

            payment_method TEXT
                DEFAULT 'cash',

            payment_reference TEXT,

            paid_at TIMESTAMP,

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


    # ========================================================
    # USERS TABLE MIGRATION
    # ========================================================

    add_column_if_not_exists(
        conn,
        "users",
        "is_admin",
        "INTEGER DEFAULT 0"
    )


    # ========================================================
    # BOOKINGS TABLE MIGRATION
    # ========================================================

    add_column_if_not_exists(
        conn,
        "bookings",
        "duration",
        "INTEGER DEFAULT 1"
    )

    add_column_if_not_exists(
        conn,
        "bookings",
        "status",
        "TEXT DEFAULT 'confirmed'"
    )

    add_column_if_not_exists(
        conn,
        "bookings",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )

    add_column_if_not_exists(
        conn,
        "bookings",
        "payment_status",
        "TEXT DEFAULT 'pending'"
    )

    add_column_if_not_exists(
        conn,
        "bookings",
        "payment_method",
        "TEXT DEFAULT 'cash'"
    )

    add_column_if_not_exists(
        conn,
        "bookings",
        "payment_reference",
        "TEXT"
    )

    add_column_if_not_exists(
        conn,
        "bookings",
        "paid_at",
        "TIMESTAMP"
    )


    # ========================================================
    # STEP 31 - ESEWA PAYMENT COLUMNS
    # ========================================================

    # Unique transaction ID generated by our website
    add_column_if_not_exists(
        conn,
        "bookings",
        "transaction_uuid",
        "TEXT"
    )


    # Transaction code returned by eSewa
    add_column_if_not_exists(
        conn,
        "bookings",
        "esewa_transaction_code",
        "TEXT"
    )


    # eSewa product code
    add_column_if_not_exists(
        conn,
        "bookings",
        "esewa_product_code",
        "TEXT"
    )


    # Amount sent to eSewa
    add_column_if_not_exists(
        conn,
        "bookings",
        "esewa_amount",
        "REAL"
    )


    # Date/time when eSewa payment was verified
    add_column_if_not_exists(
        conn,
        "bookings",
        "esewa_verified_at",
        "TIMESTAMP"
    )


    # ========================================================
    # CREATE INDEX FOR TRANSACTION UUID
    # ========================================================

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_bookings_transaction_uuid

        ON bookings(transaction_uuid)
        """
    )


    # ========================================================
    # CREATE ADMIN ACCOUNT
    # ========================================================

    admin_email = "admin@futsal.com"

    admin_password = "admin123"

    existing_admin = conn.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        (admin_email,)
    ).fetchone()


    if existing_admin:

        conn.execute(
            """
            UPDATE users

            SET
                is_admin = 1

            WHERE email = ?
            """,
            (admin_email,)
        )

        print(
            "Admin account already exists."
        )

    else:

        hashed_password = generate_password_hash(
            admin_password
        )

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
                admin_email,
                hashed_password
            )
        )

        print(
            "Default admin account created."
        )


    # ========================================================
    # COMMIT CHANGES
    # ========================================================

    conn.commit()

    conn.close()

    print()
    print(
        "Database setup completed successfully!"
    )
    print()
    print(
        "eSewa payment database fields are ready."
    )


# ============================================================
# RUN DATABASE SETUP
# ============================================================

if __name__ == "__main__":

    setup_database()