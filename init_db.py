import sqlite3

DB_PATH = "database/schedule.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT NOT NULL,
        group_name TEXT NOT NULL,
        day TEXT NOT NULL,
        lesson_number INTEGER NOT NULL,
        subject TEXT,
        room TEXT,
        teacher TEXT,
        subgroup TEXT,
        note TEXT,
        week_type TEXT NOT NULL,
        page INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cursor.execute("""
    INSERT OR IGNORE INTO settings (key, value)
    VALUES ('current_week_type', 'odd')
    """)

    conn.commit()
    conn.close()
    print("База данных инициализирована")


if __name__ == "__main__":
    init_db()