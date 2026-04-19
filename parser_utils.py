import re


ROOM_RE = r"\d+\s*\*?\s*[А-Яа-яA-Za-z]+(?:\s*\+\s*\d+\s*\*?\s*[А-Яа-яA-Za-z]+)?(?:\s+и\s+\d+\s*\*?\s*[А-Яа-яA-Za-z]+)?"

# Более терпимый шаблон преподавателя:
# Лукина Д.Ю.
# Лукина Д.Ю
# Лукина Д. Ю.
# Лукина Д Ю
# Дунина-Седенкова Е.Г.
# Ковалева С.А
TEACHER_RE = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)*(?:\s+[А-ЯЁ]\.?\s*[А-ЯЁ]\.?)"


MULTI_RECORD_RE = re.compile(
    rf"""
    (?P<subject>.+?)\s+
    (?P<room>{ROOM_RE})\s+
    Преп\.\s*(?P<teacher>{TEACHER_RE})
    (?:\s*(?P<note>\([^)]*\)))?
    (?=
        \s+.+?\s+{ROOM_RE}\s+Преп\.
        |$
    )
    """,
    re.X
)


def clean_text(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.replace("\n", " ").split()).strip()


def cleanup_trailing_initial_garbage(text: str) -> str:
    """
    Убирает только действительно подозрительный хвост после кривого распознавания
    инициалов преподавателя.

    Примеры:
    'Русский язык 541 Г А' -> 'Русский язык 541 Г'
    'А' -> ''

    Но НЕ трогает нормальные предметы вроде:
    'Т и ИФК и С'
    """
    text = clean_text(text)
    if not text:
        return ""

    # если строка состоит только из одной буквы — это точно мусор
    if re.fullmatch(r"[А-ЯЁA-Z]", text):
        return ""

    tokens = text.split()
    if len(tokens) < 2:
        return text

    last_token = tokens[-1]
    prev_token = tokens[-2]

    # срезаем одиночную букву в конце ТОЛЬКО если перед ней уже стоит
    # что-то похожее на аудиторию, например:
    # 'Русский язык 541 Г А'
    # 'Математика 216 М А'
    if re.fullmatch(r"[А-ЯЁA-Z]", last_token):
        if re.fullmatch(r"\d+", prev_token):
            return clean_text(" ".join(tokens[:-1]))

        if len(tokens) >= 3:
            prev2_token = tokens[-3]
            if re.fullmatch(r"\d+", prev2_token) and re.fullmatch(r"[А-Яа-яA-Za-z]+", prev_token):
                return clean_text(" ".join(tokens[:-1]))

    return text


def extract_teacher(text: str):
    """
    Вытаскивает всех преподавателей из текста.

    Если у преподавателя рядом есть примечание в скобках,
    например:
    Преп. Обрядин В.В. (по 20.05)

    то примечание сохраняется прямо у этого преподавателя:
    Обрядин В.В. (по 20.05)

    Это нужно, чтобы не терять смысл в кейсах,
    где один преподаватель ведёт до даты, а второй остаётся дальше.
    """
    teacher_pattern = re.compile(
        rf"Преп\.\s*(?P<teacher>{TEACHER_RE})(?:\s*(?P<note>\([^)]*\)))?"
    )

    matches = list(teacher_pattern.finditer(text))

    if not matches:
        return None, clean_text(text)

    teacher_parts = []
    for m in matches:
        teacher = clean_text(m.group("teacher"))
        note = clean_text(m.group("note")) if m.group("note") else ""

        if note:
            teacher_parts.append(f"{teacher} {note}")
        else:
            teacher_parts.append(teacher)

    teacher_value = "; ".join(teacher_parts)

    text = teacher_pattern.sub("", text)

    return teacher_value, clean_text(text)


def extract_note(text: str):
    notes = re.findall(r"\([^)]*\)", text)
    note = "; ".join(notes) if notes else None

    text = re.sub(r"\([^)]*\)", "", text)

    return note, clean_text(text)


def extract_subgroup(text: str):
    match = re.search(r"(\d+\s*п/г)", text, flags=re.IGNORECASE)
    subgroup = match.group(1) if match else None

    if subgroup:
        text = re.sub(r"\d+\s*п/г", "", text, flags=re.IGNORECASE)

    return subgroup, clean_text(text)


def extract_room(text: str):
    match = re.search(rf"({ROOM_RE})$", text)
    room = match.group(1).strip() if match else None

    if room:
        text = re.sub(rf"({ROOM_RE})$", "", text).strip()

    text = cleanup_trailing_initial_garbage(text)

    return room, clean_text(text)


def parse_lesson_block(block_text: str) -> dict:
    text = clean_text(block_text)

    if not text:
        return {
            "subject": None,
            "room": None,
            "teacher": None,
            "subgroup": None,
            "note": None,
        }

    teacher, text = extract_teacher(text)
    note, text = extract_note(text)
    subgroup, text = extract_subgroup(text)
    room, text = extract_room(text)

    text = cleanup_trailing_initial_garbage(text)
    subject = clean_text(text) if text else None

    return {
        "subject": subject,
        "room": room,
        "teacher": teacher,
        "subgroup": subgroup,
        "note": note,
    }


def parse_compound_records(text: str):
    """
    Пытается разобрать ячейку как несколько полноценных записей:
    'Предмет 544 Г Преп. ... (по ...) Другой предмет 669 Гт Преп. ... (с ...)'
    """
    text = clean_text(text)
    if not text:
        return []

    matches = list(MULTI_RECORD_RE.finditer(text))
    if not matches:
        return []

    reconstructed = " ".join(clean_text(m.group(0)) for m in matches)

    if clean_text(reconstructed) != text:
        return []

    parsed = []
    for m in matches:
        parsed.append({
            "subject": cleanup_trailing_initial_garbage(clean_text(m.group("subject"))) or None,
            "room": clean_text(m.group("room")),
            "teacher": clean_text(m.group("teacher")),
            "subgroup": None,
            "note": clean_text(m.group("note")) or None,
        })

    return parsed


def parse_subject_with_subgroup_lines(cell_text: str):
    """
    Разбор кейса вида:

    Информатика
    Преп. Гусаров Б.Н. 1 п/г 216 Г
    Преп. Ананьева О.В. 2 п/г 221 аГт

    Возвращает 2 отдельные записи с одним и тем же subject.
    """
    if not cell_text:
        return []

    raw_lines = [line.strip() for line in str(cell_text).split("\n") if line and line.strip()]
    if len(raw_lines) < 2:
        return []

    subject = clean_text(raw_lines[0])
    if not subject:
        return []

    subgroup_items = []

    line_pattern = re.compile(
        rf"""
        ^Преп\.\s*
        (?P<teacher>{TEACHER_RE})
        (?:\s+(?P<subgroup>\d+\s*п/г))?
        \s+(?P<room>{ROOM_RE})
        (?:\s*(?P<note>\([^)]*\)))?
        $
        """,
        re.X
    )

    for line in raw_lines[1:]:
        line = clean_text(line)

        m = line_pattern.match(line)
        if m:
            subgroup_items.append({
                "subject": subject,
                "room": clean_text(m.group("room")) or None,
                "teacher": clean_text(m.group("teacher")) or None,
                "subgroup": clean_text(m.group("subgroup")) or None,
                "note": clean_text(m.group("note")) or None,
            })
            continue

        # запасной вариант:
        # если в строке преподаватель вытащился криво и остался хвост
        teacher_match = re.search(rf"^Преп\.\s*(?P<teacher>{TEACHER_RE})", line)
        subgroup_match = re.search(r"(?P<subgroup>\d+\s*п/г)", line, flags=re.IGNORECASE)
        room_match = re.search(rf"(?P<room>{ROOM_RE})$", line)

        if teacher_match and room_match:
            subgroup_items.append({
                "subject": subject,
                "room": clean_text(room_match.group("room")) or None,
                "teacher": clean_text(teacher_match.group("teacher")) or None,
                "subgroup": clean_text(subgroup_match.group("subgroup")) if subgroup_match else None,
                "note": None,
            })
            continue

        return []

    return subgroup_items


def split_by_teacher(text: str):
    """
    Резервный вариант разбиения:
    делит строку по нескольким 'Преп.'
    """
    text = clean_text(text)

    teacher_positions = [m.start() for m in re.finditer(r"Преп\.", text)]

    if len(teacher_positions) <= 1:
        return [text]

    parts = []
    start = 0

    for i in range(1, len(teacher_positions)):
        split_pos = teacher_positions[i]
        parts.append(text[start:split_pos].strip())
        start = split_pos

    parts.append(text[start:].strip())

    return parts

def merge_teacher_continuation_lines(cell_text: str) -> str:
    """
    Склеивает строки вида 'Преп. ...' с предыдущим занятием,
    если это не новый предмет, а продолжение списка преподавателей.

    Пример:
    Безопасность жизнедеятельности 662 Гт
    Преп. Андропова В.С.
    Преп. Обрядин В.В. (по 17.03)
    БЖД (ОВП*) 201 бГ
    Преп. Лементуев А.Б. (с 31.03)

    После склейки логически останется 2 блока:
    1) Безопасность... + два преподавателя
    2) БЖД (ОВП*) ... + свой преподаватель
    """
    if not cell_text:
        return ""

    lines = [line.strip() for line in str(cell_text).split("\n") if line and line.strip()]
    if not lines:
        return ""

    merged_blocks = []
    current_block = []

    def is_teacher_line(line: str) -> bool:
        return clean_text(line).startswith("Преп.")

    for line in lines:
        if not current_block:
            current_block = [line]
            continue

        if is_teacher_line(line):
            current_block.append(line)
        else:
            merged_blocks.append("\n".join(current_block))
            current_block = [line]

    if current_block:
        merged_blocks.append("\n".join(current_block))

    return "\n\n".join(merged_blocks)


def parse_lesson_blocks(cell_text: str):
    """
    Разбирает ячейку, где может быть одна или несколько записей.

    Порядок:
    1) Склейка строк-продолжений с преподавателями.
    2) Особый кейс: один предмет + несколько строк по подгруппам.
    3) Несколько полноценных записей.
    4) Резервный разбор.
    """
    if not cell_text:
        return []

    cell_text = merge_teacher_continuation_lines(cell_text)

    # если после склейки получилось несколько отдельных блоков,
    # разбираем каждый блок отдельно
    separated_blocks = [block.strip() for block in cell_text.split("\n\n") if block.strip()]
    if len(separated_blocks) > 1:
        result = []
        for block in separated_blocks:
            result.extend(parse_lesson_blocks(block))
        return result

    subgroup_items = parse_subject_with_subgroup_lines(cell_text)
    if subgroup_items:
        return subgroup_items

    text = clean_text(cell_text)
    if not text:
        return []

    compound_items = parse_compound_records(text)
    if compound_items:
        return compound_items

    blocks = split_by_teacher(text)

    if len(blocks) == 1:
        return [parse_lesson_block(blocks[0])]

    parsed_items = []
    for block in blocks:
        parsed = parse_lesson_block(block)
        parsed_items.append(parsed)

    for item in parsed_items:
        if not item.get("subject"):
            return [parse_lesson_block(text)]

    return parsed_items


def is_suspicious_lesson(parsed: dict) -> bool:
    subject = parsed.get("subject") or ""
    room = parsed.get("room") or ""
    teacher = parsed.get("teacher") or ""
    note = parsed.get("note") or ""

    if len(subject) > 90:
        return True

    if "Преп." in subject:
        return True

    if len(re.findall(r"\d+\s*\*?\s*[А-Яа-яA-Za-z]+", subject)) >= 2:
        return True

    if teacher and not room and re.search(r"\d+\s*\*?\s*[А-Яа-яA-Za-z]+", subject):
        return True

    if note and note.count(";") >= 4:
        return True

    return False