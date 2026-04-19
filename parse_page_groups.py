import pdfplumber
from pprint import pprint
import re

PDF_PATH = r"uploads\3 курс Весенний семестр 2025-2026.pdf"
PAGE_INDEX = 0  # 1 страница


def clean_cell_text(cell):
    if cell is None:
        return ""
    return " ".join(str(cell).replace("\n", " ").split()).strip()


def is_group_name(text):
    if not text:
        return False

    text = text.strip()
    first_part = text.split()[0]

    # Поддержка обычных групп:
    # К-ИСП-232
    # и групп с делением:
    # К-ИСП-231(1), К-ИСП-231(2), К-МПИ-23(1), К-МПИ-23(2)
    return bool(
        re.match(r"^[А-ЯЁ0-9]+(?:-[А-ЯЁ0-9]+)+(?:\(\d+\))?$", first_part)
    )


def find_groups_on_page(table_obj):
    extracted = table_obj.extract()
    groups = {}

    for row in extracted:
        cleaned_row = [clean_cell_text(cell) for cell in row]

        for col_index, cell in enumerate(cleaned_row):
            if is_group_name(cell):
                groups[cell] = col_index

    return dict(sorted(groups.items(), key=lambda x: x[1]))


if __name__ == "__main__":
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[PAGE_INDEX]
        tables = page.find_tables()

        if not tables:
            print("Таблицы не найдены")
            raise SystemExit

        table_obj = tables[0]
        groups = find_groups_on_page(table_obj)

        print("Найденные группы на странице:")
        pprint(groups, sort_dicts=False)