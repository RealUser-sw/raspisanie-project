import pdfplumber
from pprint import pprint

from parse_one_page import parse_one_page

PDF_PATH = r"uploads\2 курс Весенний семестр 2025-2026.pdf"


def normalize_str(value):
    return (value or "").strip()


def lesson_key_fields(item):
    return (
        normalize_str(item.get("subject")),
        normalize_str(item.get("room")),
        normalize_str(item.get("teacher")),
    )


def repair_shifted_even_from_next_pair(all_lessons):
    """
    Исправляет кейсы, когда even-часть пары съехала на следующую пару.

    Логика:
    - у пары N есть только odd
    - у пары N+1 есть odd и even
    - odd у N и odd у N+1 совпадают
    => even из N+1 копируем в N

    ВАЖНО:
    для 1 пары этот фикс НЕ применяем,
    потому что у первой пары часто встречаются тонкие/пустые строки,
    и перенос even со 2 пары в 1 даёт ложные срабатывания.
    """
    from collections import defaultdict

    grouped = defaultdict(list)
    for lesson in all_lessons:
        key = (
            lesson["group"],
            lesson["day"],
            lesson["page"],
        )
        grouped[key].append(lesson)

    additions = []

    for _, lessons in grouped.items():
        by_pair = defaultdict(list)
        for lesson in lessons:
            by_pair[lesson["lesson_number"]].append(lesson)

        pair_numbers = sorted(by_pair.keys())

        for pair_num in pair_numbers:
            # НЕ трогаем первую пару
            if pair_num == 1:
                continue

            next_pair = pair_num + 1
            if next_pair not in by_pair:
                continue

            current_items = by_pair[pair_num]
            next_items = by_pair[next_pair]

            current_odd = [x for x in current_items if x["week_type"] == "odd"]
            current_even = [x for x in current_items if x["week_type"] == "even"]
            current_both = [x for x in current_items if x["week_type"] == "both"]

            next_odd = [x for x in next_items if x["week_type"] == "odd"]
            next_even = [x for x in next_items if x["week_type"] == "even"]

            # исправляем только узкий кейс:
            # текущая пара имеет odd, но не имеет even/both
            if not current_odd or current_even or current_both:
                continue

            if not next_odd or not next_even:
                continue

            current_odd_keys = {lesson_key_fields(x) for x in current_odd}
            next_odd_keys = {lesson_key_fields(x) for x in next_odd}

            # odd у текущей и следующей пары должен совпадать
            if not (current_odd_keys & next_odd_keys):
                continue

            # переносим even следующей пары в текущую
            for even_item in next_even:
                copied = dict(even_item)
                copied["lesson_number"] = pair_num
                additions.append(copied)

    # чтобы не дублировать уже существующие записи
    existing = {
        (
            x["group"],
            x["day"],
            x["lesson_number"],
            x["subject"],
            x["room"],
            x["teacher"],
            x["week_type"],
            x["page"],
        )
        for x in all_lessons
    }

    for item in additions:
        sig = (
            item["group"],
            item["day"],
            item["lesson_number"],
            item["subject"],
            item["room"],
            item["teacher"],
            item["week_type"],
            item["page"],
        )
        if sig not in existing:
            all_lessons.append(item)
            existing.add(sig)

    return all_lessons


def parse_pdf(pdf_path):
    all_lessons = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            tables = page.find_tables()

            if not tables:
                continue

            table_obj = tables[0]
            page_lessons = parse_one_page(table_obj, page_index)
            all_lessons.extend(page_lessons)

    all_lessons = repair_shifted_even_from_next_pair(all_lessons)

    return all_lessons


if __name__ == "__main__":
    lessons = parse_pdf(PDF_PATH)

    print(f"Всего записей во всём PDF: {len(lessons)}")
    pprint(lessons[:200], sort_dicts=False)