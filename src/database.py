import sqlite3
import random
from pathlib import Path

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"

DATABASE = DATA_DIRECTORY / "user.db"

def get_connect():
    return sqlite3.connect(DATABASE)

def create_table():
    conn=get_connect()
    cursor=conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER UNIQUE NOT NULL,
    email TEXT NOT NULL,
    password TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()


def generate_customer_id():
    return random.randint(100000,999999)

def save_user(email,password):
    conn=get_connect()
    cursor=conn.cursor()
    while True:
        customer_id=generate_customer_id()
        try:
            cursor.execute(
                """
                INSERT INTO users(customer_id,email,password) VALUES (?,?,?)
                """,
                (customer_id,email,password)
            )
            conn.commit()
            conn.close()
            return customer_id
        except sqlite3.IntegrityError:
            continue
def check_user(email,password):
    conn=get_connect()
    #cursor=conn.cursor()
    user=conn.execute(
        """
        SELECT customer_id
        FROM users
        WHERE email=? AND password=?
        """,
        (email,password)
    ).fetchone()
    #user=conn.fetchone()
    conn.close()
    return user

