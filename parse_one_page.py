import pdfplumber
from pprint import pprint
from collections import Counter

from parse_page_groups import find_groups_on_page, clean_cell_text
from parser_utils import parse_lesson_blocks, is_suspicious_lesson


PDF_PATH = r"uploads\2 курс Весенний семестр 2025-2026.pdf"
PAGE_INDEX = 2

DAY_COL = 1
LESSON_COL = 2

DAY_PATTERNS = {
    "ПОНЕДЕЛЬНИК": ["ПОНЕДЕЛЬНИК", "К И Н Ь Л Е Д Е Н О П"],
    "ВТОРНИК": ["ВТОРНИК", "К И Н Р О Т В"],
    "СРЕДА": ["СРЕДА", "А Д Е Р С"],
    "ЧЕТВЕРГ": ["ЧЕТВЕРГ", "Г Р Е В Т Е Ч"],
    "ПЯТНИЦА": ["ПЯТНИЦА", "А Ц И Н Т Я П"],
    "СУББОТА": ["СУББОТА", "А Т О Б Б У С"],
}

ROMAN_TO_INT = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
}

ABSENCE_MARKERS = [
    "самостоятельной работы",
    "курсового проектирования",
]


def normalize_day_name(text):
    text = clean_cell_text(text)
    if not text:
        return None

    for normal_day, variants in DAY_PATTERNS.items():
        if text in variants:
            return normal_day

    return None


def normalize_group_name(group_name):
    return group_name.split()[0]


def append_parsed_lessons(
    lessons,
    parsed_list,
    group_name,
    current_day,
    lesson_number,
    week_type,
    page_index
):
    for item in parsed_list:
        if is_suspicious_lesson(item):
            print("\n[ПОДОЗРИТЕЛЬНАЯ ЗАПИСЬ]")
            print("Группа:", group_name)
            print("День:", current_day)
            print("Пара:", lesson_number)
            print("Неделя:", week_type)
            print("Данные:", item)

        lessons.append({
            "group": group_name,
            "day": current_day,
            "lesson_number": lesson_number,
            "subject": item.get("subject"),
            "room": item.get("room"),
            "teacher": item.get("teacher"),
            "subgroup": item.get("subgroup"),
            "note": item.get("note"),
            "week_type": week_type,
            "page": page_index + 1,
        })


def build_column_bounds(table_obj):
    max_cols = max(len(row.cells) for row in table_obj.rows)
    bounds = {}

    for col_index in range(max_cols):
        cells = [
            row.cells[col_index]
            for row in table_obj.rows
            if col_index < len(row.cells) and row.cells[col_index] is not None
        ]

        if not cells:
            continue

        x0_counter = Counter(round(cell[0], 3) for cell in cells)
        x1_counter = Counter(round(cell[2], 3) for cell in cells)

        x0 = x0_counter.most_common(1)[0][0]
        x1 = x1_counter.most_common(1)[0][0]

        bounds[col_index] = (x0, x1)

    return bounds


def get_row_bottom(row_cells):
    values = [cell[3] for cell in row_cells if cell is not None]
    return max(values) if values else None


def cell_overlaps_target(cell, target_col, column_bounds, eps=1.0):
    if cell is None or target_col not in column_bounds:
        return False

    target_x0, target_x1 = column_bounds[target_col]
    cell_x0, _, cell_x1, _ = cell

    return cell_x0 <= target_x0 + eps and cell_x1 >= target_x1 - eps


def find_left_span_source(raw_row, cleaned_row, row_cells, target_col, group_cols, column_bounds):
    left_candidates = [c for c in group_cols if c < target_col]

    for left_col in reversed(left_candidates):
        if left_col >= len(row_cells):
            continue

        left_cell = row_cells[left_col]
        if left_cell is None:
            continue

        left_raw_text = str(raw_row[left_col]) if left_col < len(raw_row) and raw_row[left_col] is not None else ""
        left_clean_text = clean_cell_text(left_raw_text)
        if not left_clean_text:
            continue

        blocked = False
        for mid in range(left_col + 1, target_col + 1):
            if mid >= len(row_cells):
                blocked = True
                break

            mid_cell = row_cells[mid]
            mid_text = cleaned_row[mid] if mid < len(cleaned_row) else ""

            if mid_cell is not None and mid_text:
                blocked = True
                break

        if blocked:
            continue

        if cell_overlaps_target(left_cell, target_col, column_bounds):
            return {
                "source_col": left_col,
                "text": left_raw_text,
                "cell": left_cell,
                "direct": False,
            }

    return None


def get_effective_source_info(raw_row, cleaned_row, row_cells, target_col, group_cols, column_bounds):
    if raw_row is None or cleaned_row is None or row_cells is None:
        return {
            "source_col": None,
            "text": "",
            "cell": None,
            "direct": False,
        }

    if target_col >= len(row_cells):
        return {
            "source_col": None,
            "text": "",
            "cell": None,
            "direct": False,
        }

    direct_cell = row_cells[target_col]
    direct_raw_text = str(raw_row[target_col]) if target_col < len(raw_row) and raw_row[target_col] is not None else ""
    direct_clean_text = cleaned_row[target_col] if target_col < len(cleaned_row) else ""

    if direct_cell is not None and direct_clean_text:
        return {
            "source_col": target_col,
            "text": direct_raw_text,
            "cell": direct_cell,
            "direct": True,
        }

    left_source = find_left_span_source(
        raw_row,
        cleaned_row,
        row_cells,
        target_col,
        group_cols,
        column_bounds
    )
    if left_source is not None:
        return left_source

    return {
        "source_col": target_col if direct_cell is not None else None,
        "text": direct_raw_text,
        "cell": direct_cell,
        "direct": direct_cell is not None,
    }


def is_structural_second_row(current_cleaned, current_cells, next_cleaned, next_cells):
    if next_cleaned is None or next_cells is None:
        return False

    next_lesson = next_cleaned[LESSON_COL] if LESSON_COL < len(next_cleaned) else ""
    next_day = normalize_day_name(next_cleaned[DAY_COL]) if DAY_COL < len(next_cleaned) else None

    if next_lesson in ROMAN_TO_INT:
        return False

    if next_day:
        return False

    if LESSON_COL >= len(current_cells):
        return False

    lesson_cell = current_cells[LESSON_COL]
    if lesson_cell is None:
        return False

    next_row_bottom = get_row_bottom(next_cells)
    if next_row_bottom is None:
        return False

    return lesson_cell[3] >= next_row_bottom - 0.5


def is_absence_marker(text: str) -> bool:
    low = clean_cell_text(text).lower()
    return any(marker in low for marker in ABSENCE_MARKERS)


def clean_lesson_text_for_group(text: str, group_col: int, max_group_col: int) -> str:
    """
    Сохраняем переводы строк, потому что они нужны
    для разбора сложных odd/even блоков и кейсов с подгруппами.
    """
    if text is None:
        return ""

    lines = [line.strip() for line in str(text).split("\n")]
    lines = [line for line in lines if line]

    return "\n".join(lines)


def split_multiline_week_blocks(text: str):
    """
    Разбивает многострочную ячейку на блоки по занятиям.
    Считаем, что новый блок начинается со строки,
    которая НЕ начинается с 'Преп.'.
    """
    if not text:
        return []

    raw_lines = [line.strip() for line in str(text).split("\n") if line and line.strip()]
    if not raw_lines:
        return []

    blocks = []
    current_block = []

    for line in raw_lines:
        if not current_block:
            current_block = [line]
            continue

        if line.startswith("Преп."):
            current_block.append(line)
        else:
            blocks.append("\n".join(current_block))
            current_block = [line]

    if current_block:
        blocks.append("\n".join(current_block))

    return blocks


def parse_one_page(table_obj, page_index):
    extracted_table = table_obj.extract()
    groups = find_groups_on_page(table_obj)
    group_cols = sorted(groups.values())
    column_bounds = build_column_bounds(table_obj)

    lessons = []
    current_day = None
    row_index = 0

    while row_index < len(extracted_table):
        raw_row = extracted_table[row_index]
        row_cells = table_obj.rows[row_index].cells
        cleaned_row = [clean_cell_text(cell) for cell in raw_row]

        if DAY_COL < len(cleaned_row):
            day_name = normalize_day_name(cleaned_row[DAY_COL])
            if day_name:
                current_day = day_name

        if current_day is None:
            row_index += 1
            continue

        lesson_number = None
        if LESSON_COL < len(cleaned_row):
            lesson_raw = cleaned_row[LESSON_COL]
            if lesson_raw in ROMAN_TO_INT:
                lesson_number = ROMAN_TO_INT[lesson_raw]

        if lesson_number is None:
            row_index += 1
            continue

        first_raw_row = raw_row
        first_cleaned_row = cleaned_row
        first_row_cells = row_cells

        second_raw_row = None
        second_cleaned_row = None
        second_row_cells = None

        if row_index + 1 < len(extracted_table):
            next_raw_row = extracted_table[row_index + 1]
            next_cleaned = [clean_cell_text(cell) for cell in next_raw_row]
            next_cells = table_obj.rows[row_index + 1].cells

            if is_structural_second_row(first_cleaned_row, first_row_cells, next_cleaned, next_cells):
                second_raw_row = next_raw_row
                second_cleaned_row = next_cleaned
                second_row_cells = next_cells

        second_row_bottom = get_row_bottom(second_row_cells) if second_row_cells else None

        for raw_group_name, col_index in groups.items():
            group_name = normalize_group_name(raw_group_name)

            first_info = get_effective_source_info(
                first_raw_row,
                first_cleaned_row,
                first_row_cells,
                col_index,
                group_cols,
                column_bounds
            )

            if second_raw_row is not None:
                second_info = get_effective_source_info(
                    second_raw_row,
                    second_cleaned_row,
                    second_row_cells,
                    col_index,
                    group_cols,
                    column_bounds
                )
            else:
                second_info = {
                    "source_col": None,
                    "text": "",
                    "cell": None,
                    "direct": False,
                }

            first_text = clean_lesson_text_for_group(first_info["text"], col_index, max(group_cols))
            second_text = clean_lesson_text_for_group(second_info["text"], col_index, max(group_cols))

            if is_absence_marker(first_text):
                first_text = ""
            if is_absence_marker(second_text):
                second_text = ""

            if second_raw_row is None:
                if first_text:
                    parsed_list = parse_lesson_blocks(first_text)
                    if parsed_list:
                        append_parsed_lessons(
                            lessons,
                            parsed_list,
                            group_name,
                            current_day,
                            lesson_number,
                            "both",
                            page_index
                        )
                continue

            first_spans_two_rows = (
                first_info["cell"] is not None
                and second_row_bottom is not None
                and first_info["cell"][3] >= second_row_bottom - 0.5
            )

            multiline_blocks = split_multiline_week_blocks(first_text)
            if len(multiline_blocks) >= 3:
                for i, block in enumerate(multiline_blocks):
                    week_type = "odd" if i % 2 == 0 else "even"

                    parsed_list = parse_lesson_blocks(block)
                    if parsed_list:
                        append_parsed_lessons(
                            lessons,
                            parsed_list,
                            group_name,
                            current_day,
                            lesson_number,
                            week_type,
                            page_index
                        )
                continue

            if first_spans_two_rows:
                if first_text:
                    parsed_list = parse_lesson_blocks(first_text)
                    if parsed_list:
                        append_parsed_lessons(
                            lessons,
                            parsed_list,
                            group_name,
                            current_day,
                            lesson_number,
                            "both",
                            page_index
                        )
            else:
                if first_text:
                    parsed_first = parse_lesson_blocks(first_text)
                    if parsed_first:
                        append_parsed_lessons(
                            lessons,
                            parsed_first,
                            group_name,
                            current_day,
                            lesson_number,
                            "odd",
                            page_index
                        )

                if second_text:
                    parsed_second = parse_lesson_blocks(second_text)
                    if parsed_second:
                        append_parsed_lessons(
                            lessons,
                            parsed_second,
                            group_name,
                            current_day,
                            lesson_number,
                            "even",
                            page_index
                        )

        if second_raw_row is not None:
            row_index += 2
        else:
            row_index += 1

    return lessons


if __name__ == "__main__":
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[PAGE_INDEX]
        tables = page.find_tables()

        if not tables:
            print("Таблицы не найдены")
            raise SystemExit

        table_obj = tables[0]
        lessons = parse_one_page(table_obj, PAGE_INDEX)

        print(f"Всего записей: {len(lessons)}")
        pprint(lessons[:60], sort_dicts=False)