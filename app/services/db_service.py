import os
from dotenv import load_dotenv
import pymysql
from pymysql.cursors import DictCursor

# Load .env automatically for local Windows development.
load_dotenv()


def get_db_config() -> dict:
    """Read database configuration from environment variables."""
    return {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "easyocr_slip_demo"),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": True,
    }


def get_connection():
    return pymysql.connect(**get_db_config())


def fetch_all(sql: str, params=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            return cursor.fetchall()


def fetch_one(sql: str, params=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            return cursor.fetchone()


def execute_insert(sql: str, params=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            return cursor.lastrowid


def execute_sql(sql: str, params=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if params is None:
                return cursor.execute(sql)
            return cursor.execute(sql, params)
