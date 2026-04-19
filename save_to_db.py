import sqlite3

from parse_pdf import parse_pdf

DB_PATH = "database/schedule.db"


def clear_lessons(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lessons")
    conn.commit()
    conn.close()


def save_lessons_to_db(lessons, course_name, db_path=DB_PATH, clear_existing=False):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if clear_existing:
        cursor.execute("DELETE FROM lessons")

    for lesson in lessons:
        cursor.execute("""
            INSERT INTO lessons (
                course_name,
                group_name,
                day,
                lesson_number,
                subject,
                room,
                teacher,
                subgroup,
                note,
                week_type,
                page
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            course_name,
            lesson.get("group"),
            lesson.get("day"),
            lesson.get("lesson_number"),
            lesson.get("subject"),
            lesson.get("room"),
            lesson.get("teacher"),
            lesson.get("subgroup"),
            lesson.get("note"),
            lesson.get("week_type"),
            lesson.get("page"),
        ))

    conn.commit()
    conn.close()


def save_pdf_to_db(pdf_path, course_name, db_path=DB_PATH, clear_existing=False):
    lessons = parse_pdf(pdf_path)
    save_lessons_to_db(
        lessons=lessons,
        course_name=course_name,
        db_path=db_path,
        clear_existing=clear_existing
    )
    return len(lessons)


if __name__ == "__main__":
    PDF_PATH = r"uploads\2 курс Весенний семестр 2025-2026.pdf"
    COURSE_NAME = "2 курс"

    count = save_pdf_to_db(
        pdf_path=PDF_PATH,
        course_name=COURSE_NAME,
        clear_existing=True
    )

    print(f"В базу сохранено записей: {count}")