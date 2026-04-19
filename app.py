import os
import sqlite3

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

from save_to_db import save_pdf_to_db

app = Flask(__name__)
app.secret_key = "schedule-secret-key"
ADMIN_PASSWORD = "150526"

BASE_DIR = os.environ.get("DATA_DIR", ".")
DB_PATH = os.path.join(BASE_DIR, "database", "schedule.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf"}

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

TIMEZONE = "Asia/Novosibirsk"

DAY_ORDER = {
    "ПОНЕДЕЛЬНИК": 1,
    "ВТОРНИК": 2,
    "СРЕДА": 3,
    "ЧЕТВЕРГ": 4,
    "ПЯТНИЦА": 5,
    "СУББОТА": 6,
}

PAIR_TIMES = {
    1: "08:30 - 09:50",
    2: "10:00 - 11:20",
    3: "12:00 - 13:30",
    4: "13:50 - 15:20",
    5: "15:30 - 17:00",
}

DAYS = list(DAY_ORDER.keys())

WEEKDAY_TO_DAY = {
    0: "ПОНЕДЕЛЬНИК",
    1: "ВТОРНИК",
    2: "СРЕДА",
    3: "ЧЕТВЕРГ",
    4: "ПЯТНИЦА",
    5: "СУББОТА",
}


# ---------------- TIME ----------------

def get_local_now():
    return datetime.now(ZoneInfo(TIMEZONE))


def get_today_day_name():
    now = get_local_now()
    return WEEKDAY_TO_DAY.get(now.weekday(), "ПОНЕДЕЛЬНИК")


def parse_time_to_minutes(time_str):
    hours, minutes = map(int, time_str.strip().split(":"))
    return hours * 60 + minutes


def get_current_pair_number():
    now = get_local_now()
    current_minutes = now.hour * 60 + now.minute

    for pair_number, time_range in PAIR_TIMES.items():
        start_str, end_str = [x.strip() for x in time_range.split("-")]
        start_minutes = parse_time_to_minutes(start_str)
        end_minutes = parse_time_to_minutes(end_str)

        if start_minutes <= current_minutes <= end_minutes:
            return pair_number

    return None


# ---------------- DB ----------------

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_setting(key, default=None):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    ).fetchone()
    conn.close()

    if row:
        return row["value"]
    return default


def set_setting(key, value):
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()
    conn.close()
    
def is_admin_logged_in():
    return session.get("admin_logged_in") is True


# ---------------- SETTINGS ----------------

def get_current_week_type():
    value = get_setting("current_week_type", "even")
    return value if value in ("odd", "even") else "even"


def set_current_week_type(week_type):
    if week_type in ("odd", "even"):
        set_setting("current_week_type", week_type)


def toggle_week_type_value(week_type):
    return "even" if week_type == "odd" else "odd"


def sync_week_type_with_sunday():
    """
    Автоматически переключает неделю каждое воскресенье один раз.
    Переключение происходит при первом запросе после наступления воскресенья.
    """
    now = get_local_now()
    today_str = now.date().isoformat()

    current_week_type = get_current_week_type()
    last_switch_date = get_setting("last_week_switch_date", "")

    # weekday(): понедельник=0 ... воскресенье=6
    if now.weekday() == 6 and last_switch_date != today_str:
        new_week_type = toggle_week_type_value(current_week_type)
        set_current_week_type(new_week_type)
        set_setting("last_week_switch_date", today_str)
        return new_week_type

    return current_week_type


# ---------------- COURSES ----------------

def get_available_courses():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT DISTINCT course_name FROM lessons
        ORDER BY course_name
    """).fetchall()
    conn.close()

    return [row["course_name"] for row in rows]


def get_groups_by_course(course_name):
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT DISTINCT group_name
        FROM lessons
        WHERE course_name = ?
        ORDER BY group_name
    """, (course_name,)).fetchall()
    conn.close()

    return [row["group_name"] for row in rows]


# ---------------- SCHEDULE ----------------

def get_schedule_for_group(course_name, group_name, day_name, week_type):
    conn = get_db_connection()

    rows = conn.execute("""
        SELECT *
        FROM lessons
        WHERE course_name = ?
          AND group_name = ?
          AND day = ?
          AND (week_type = 'both' OR week_type = ?)
        ORDER BY lesson_number
    """, (course_name, group_name, day_name, week_type)).fetchall()

    conn.close()

    grouped = {}

    for lesson in rows:
        lesson_dict = dict(lesson)
        num = lesson_dict["lesson_number"]

        if num not in grouped:
            grouped[num] = {
                "number": num,
                "time": PAIR_TIMES.get(num, ""),
                "data": []
            }

        grouped[num]["data"].append(lesson_dict)

    return [grouped[k] for k in sorted(grouped)]


def enrich_lesson_notes(lessons):
    for pair in lessons:
        for lesson in pair["data"]:
            subject = (lesson.get("subject") or "").strip()
            note = (lesson.get("note") or "").strip()

            if "БЖД(ОВП" in subject or "БЖД (ОВП" in subject:
                extra = "Практические занятия для юношей"
                if extra not in note:
                    lesson["note"] = f"{note}; {extra}" if note else extra

            if "БЖД**" in subject:
                extra = "Практические занятия для девушек"
                if extra not in note:
                    lesson["note"] = f"{note}; {extra}" if note else extra

    return lessons


# ---------------- ADMIN LESSONS ----------------

def get_admin_lessons(course_name=None, group_name=None, day_name=None):
    conn = get_db_connection()

    query = """
        SELECT *
        FROM lessons
        WHERE 1=1
    """
    params = []

    if course_name:
        query += " AND course_name = ?"
        params.append(course_name)

    if group_name:
        query += " AND group_name = ?"
        params.append(group_name)

    if day_name:
        query += " AND day = ?"
        params.append(day_name)

    query += """
        ORDER BY
            course_name,
            group_name,
            CASE day
                WHEN 'ПОНЕДЕЛЬНИК' THEN 1
                WHEN 'ВТОРНИК' THEN 2
                WHEN 'СРЕДА' THEN 3
                WHEN 'ЧЕТВЕРГ' THEN 4
                WHEN 'ПЯТНИЦА' THEN 5
                WHEN 'СУББОТА' THEN 6
                ELSE 99
            END,
            lesson_number,
            week_type
    """

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_lesson_by_id(lesson_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM lessons WHERE id = ?",
        (lesson_id,)
    ).fetchone()
    conn.close()
    return row


# ---------------- FILE ----------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_uploaded_files():
    if not os.path.exists(UPLOAD_FOLDER):
        return []

    return sorted(
        [f for f in os.listdir(UPLOAD_FOLDER) if f.lower().endswith(".pdf")],
        reverse=True
    )


def process_uploaded_pdfs():
    uploaded_files = get_uploaded_files()

    if not uploaded_files:
        return 0, 0

    total_count = 0
    processed_files = 0

    for filename in uploaded_files:
        file_path = os.path.join(UPLOAD_FOLDER, filename)

        course_name = filename.split("_", 1)[0].strip()
        if not course_name:
            continue

        count = save_pdf_to_db(
            pdf_path=file_path,
            course_name=course_name,
            clear_existing=False
        )
        total_count += count
        processed_files += 1

    return processed_files, total_count


# ---------------- ROUTES ----------------

@app.route("/", methods=["GET", "POST"])
def index():
    current_week_type = sync_week_type_with_sunday()

    courses = get_available_courses()

    selected_course = None
    selected_group = None
    today_day_name = get_today_day_name()
    selected_day = today_day_name

    schedule = []
    current_pair_number = get_current_pair_number()

    if request.method == "POST":
        selected_course = request.form.get("course")
        selected_group = request.form.get("group")
        selected_day = request.form.get("day") or today_day_name

        if "toggle_week" in request.form:
            current_week_type = toggle_week_type_value(current_week_type)
            set_current_week_type(current_week_type)

        if selected_course and selected_group and selected_day:
            schedule = get_schedule_for_group(
                course_name=selected_course,
                group_name=selected_group,
                day_name=selected_day,
                week_type=current_week_type
            )
            schedule = enrich_lesson_notes(schedule)

    groups = []
    if selected_course:
        groups = get_groups_by_course(selected_course)

    if selected_day != today_day_name:
        current_pair_number = None

    return render_template(
        "index.html",
        courses=courses,
        groups=groups,
        days=DAYS,
        schedule=schedule,
        selected_course=selected_course,
        selected_group=selected_group,
        selected_day=selected_day,
        current_week_type=current_week_type,
        current_pair_number=current_pair_number,
        today_day_name=today_day_name,
    )

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")

        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))

        flash("Неверный пароль", "error")
        return redirect(url_for("admin_login"))

    return render_template("admin_login.html")
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Вы вышли из админ-панели", "success")
    return redirect(url_for("admin_login"))
# ---------------- ADMIN ----------------

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not is_admin_logged_in():
        return redirect(url_for("admin_login"))

    current_week_type = sync_week_type_with_sunday()

    if request.method == "POST":

        if "week_type" in request.form:
            week_type = request.form.get("week_type")
            if week_type in ("odd", "even"):
                set_current_week_type(week_type)
                current_week_type = week_type
                flash("Неделя обновлена", "success")

        elif "upload_pdf" in request.form:
            file = request.files.get("pdf_file")
            course_name = request.form.get("course_name", "").strip()

            if not course_name:
                flash("Выбери курс", "error")
            elif not file or not file.filename:
                flash("Выбери PDF файл", "error")
            elif not allowed_file(file.filename):
                flash("Разрешены только PDF файлы", "error")
            else:
                filename = secure_filename(file.filename)
                final_filename = f"{course_name}_{filename}"
                file_path = os.path.join(UPLOAD_FOLDER, final_filename)

                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(file_path)

                flash(f"Файл загружен: {final_filename}", "success")

        elif "update_db" in request.form:
            try:
                processed_files, total_count = process_uploaded_pdfs()

                if processed_files == 0:
                    flash("Нет загруженных PDF файлов для обработки", "error")
                else:
                    flash(
                        f"База данных обновлена. Обработано файлов: {processed_files}, загружено записей: {total_count}",
                        "success"
                    )
            except Exception as e:
                flash(f"Ошибка обновления базы данных: {e}", "error")

        elif "clear_db" in request.form:
            conn = get_db_connection()
            conn.execute("DELETE FROM lessons")
            conn.commit()
            conn.close()
            flash("База данных очищена", "success")

        elif "clear_files" in request.form:
            if os.path.exists(UPLOAD_FOLDER):
                for file in os.listdir(UPLOAD_FOLDER):
                    file_path = os.path.join(UPLOAD_FOLDER, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
            flash("Все PDF файлы удалены", "success")

        return redirect(url_for("admin"))

    uploaded_files = get_uploaded_files()

    return render_template(
        "admin.html",
        current_week_type=current_week_type,
        uploaded_files=uploaded_files,
    )


# ---------------- ADMIN LESSON EDITOR ----------------

@app.route("/admin/lessons", methods=["GET"])
def admin_lessons():
    if not is_admin_logged_in():
        return redirect(url_for("admin_login"))
    selected_course = request.args.get("course_name", "").strip()
    selected_group = request.args.get("group_name", "").strip()
    selected_day = request.args.get("day", "").strip()

    courses = get_available_courses()
    groups = get_groups_by_course(selected_course) if selected_course else []
    lessons = get_admin_lessons(
        course_name=selected_course or None,
        group_name=selected_group or None,
        day_name=selected_day or None
    )

    return render_template(
        "admin_lessons.html",
        lessons=lessons,
        courses=courses,
        groups=groups,
        days=DAYS,
        selected_course=selected_course,
        selected_group=selected_group,
        selected_day=selected_day,
    )


@app.route("/admin/lessons/add", methods=["GET", "POST"])
def admin_add_lesson():
    if not is_admin_logged_in():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute("""
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
            request.form.get("course_name", "").strip(),
            request.form.get("group_name", "").strip(),
            request.form.get("day", "").strip(),
            int(request.form.get("lesson_number", "1")),
            request.form.get("subject", "").strip(),
            request.form.get("room", "").strip(),
            request.form.get("teacher", "").strip(),
            request.form.get("subgroup", "").strip(),
            request.form.get("note", "").strip(),
            request.form.get("week_type", "both").strip(),
            request.form.get("page", "").strip() or None,
        ))
        conn.commit()
        conn.close()

        flash("Запись добавлена", "success")
        return redirect(url_for("admin_lessons"))

    return render_template(
        "admin_lesson_form.html",
        lesson=None,
        courses=get_available_courses(),
        days=DAYS,
    )


@app.route("/admin/lessons/edit/<int:lesson_id>", methods=["GET", "POST"])
def admin_edit_lesson(lesson_id):
    if not is_admin_logged_in():
        return redirect(url_for("admin_login"))
    lesson = get_lesson_by_id(lesson_id)

    if not lesson:
        flash("Запись не найдена", "error")
        return redirect(url_for("admin_lessons"))

    if request.method == "POST":
        conn = get_db_connection()
        conn.execute("""
            UPDATE lessons
            SET course_name = ?,
                group_name = ?,
                day = ?,
                lesson_number = ?,
                subject = ?,
                room = ?,
                teacher = ?,
                subgroup = ?,
                note = ?,
                week_type = ?,
                page = ?
            WHERE id = ?
        """, (
            request.form.get("course_name", "").strip(),
            request.form.get("group_name", "").strip(),
            request.form.get("day", "").strip(),
            int(request.form.get("lesson_number", "1")),
            request.form.get("subject", "").strip(),
            request.form.get("room", "").strip(),
            request.form.get("teacher", "").strip(),
            request.form.get("subgroup", "").strip(),
            request.form.get("note", "").strip(),
            request.form.get("week_type", "both").strip(),
            request.form.get("page", "").strip() or None,
            lesson_id,
        ))
        conn.commit()
        conn.close()

        flash("Запись обновлена", "success")
        return redirect(url_for("admin_lessons"))

    return render_template(
        "admin_lesson_form.html",
        lesson=lesson,
        courses=get_available_courses(),
        days=DAYS,
    )


@app.route("/admin/lessons/delete/<int:lesson_id>", methods=["POST"])
def admin_delete_lesson(lesson_id):
    if not is_admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db_connection()
    conn.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
    conn.commit()
    conn.close()

    flash("Запись удалена", "success")
    return redirect(url_for("admin_lessons"))


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)