import mysql.connector
import os

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "Bhavitha08"),
        database=os.getenv("DB_NAME", "expense_tracker"),
        port=int(os.getenv("DB_PORT", 3306))
    )
