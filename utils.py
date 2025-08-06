import libsql as libsql_client
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv
import os

# Carga variables de entorno
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

URL = os.getenv('URL')
TOKEN = os.getenv('TOKEN')

class Database:
    def __init__(self, client):
        self._client = client

    @classmethod
    def connect(cls) -> "Database":
        """
        Crea el cliente síncrono y devuelve la instancia de Database.
        """
        client = libsql_client.connect(
            URL,
            auth_token=TOKEN
        )
        return cls(client)

    def execute(self, query: str, *params):
        """
        Ejecuta una consulta SQL y devuelve el cursor.
        """
        cur = self._client.cursor()
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        return cur

    def fetch_one(self, query: str, *params):
        """
        Devuelve la primera fila o None.
        """
        cur = self.execute(query, *params)
        row = cur.fetchone()
        cur.close()
        return row

    def fetch_all(self, query: str, *params):
        """
        Devuelve todas las filas.
        """
        cur = self.execute(query, *params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def commit(self):
        self._client.commit()

    def close(self):
        try:
            self._client.close()
        except:
            pass

@contextmanager
def get_db():
    db = Database.connect()
    try:
        yield db
    finally:
        db.close()

CREATE_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT    NOT NULL UNIQUE,
    doc_type TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def main():
    with get_db() as db:
        # Crea la tabla si no existe
        db.execute(CREATE_DOCS_TABLE)
        db.commit()

if __name__ == "__main__":
    main()
