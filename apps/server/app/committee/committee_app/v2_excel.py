"""Spreadsheet exports shared by the headless modules."""

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font

from .v2_core import ExportFile


def export_xlsx(filename: str, headers: list[str], rows: list[list[Any]]) -> ExportFile:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "평가위원"
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(
            [
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in row
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 24
    stream = BytesIO()
    book.save(stream)
    book.close()
    return ExportFile(filename, stream.getvalue())
