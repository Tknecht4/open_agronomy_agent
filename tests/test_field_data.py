from __future__ import annotations

import io
import zipfile

import pytest

from agronomy_agent.field_data import parse_table


def test_csv_and_tab_locators_preserve_logical_records() -> None:
    csv_data = b'Field,Note,Value\nA,"line one\nline two",1\nA,plain,-2\n'
    parsed = parse_table("records.csv", csv_data)
    assert parsed["row_count"] == 2
    assert parsed["rows"][0]["locator"] == {"record": 2, "physical_line_end": 3}
    assert parsed["rows"][0]["values"]["Note"] == "line one\nline two"
    assert parsed["rows"][1]["values"]["Value"] == "-2"
    tabbed = parse_table("records.tab", b"Field\tValue\nA\t2\n")
    assert tabbed["delimiter"] == "\t"


def test_encoding_duplicate_ragged_and_formula_fail_closed() -> None:
    with pytest.raises(ValueError, match="decoding"):
        parse_table("latin.csv", b"Field,Note\nA,caf\xe9\n")
    assert parse_table("latin.csv", b"Field,Note\nA,caf\xe9\n", "latin-1")["rows"][0]["values"]["Note"] == "café"
    with pytest.raises(ValueError, match="duplicate"):
        parse_table("duplicate.csv", b"A,A\n1,2\n")
    with pytest.raises(ValueError, match="ragged"):
        parse_table("ragged.csv", b"A,B\n1\n")
    with pytest.raises(ValueError, match="formula"):
        parse_table("injection.csv", b"A,B\n1,=HYPERLINK(\"http://x\")\n")


def test_xlsx_zip_bounds_and_formulas_fail_closed() -> None:
    with io.BytesIO() as output:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bomb", b"x" * (64 * 1024 * 1024 + 1))
        oversized = output.getvalue()
    # Compressed upload fits the byte limit, expanded member does not.
    with pytest.raises(ValueError, match="expansion|limits"):
        parse_table("bomb.xlsx", oversized)
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Field", "Rate"])
    sheet.append(["A", "=2+2"])
    output = io.BytesIO()
    workbook.save(output)
    with pytest.raises(ValueError, match="formula"):
        parse_table("formula.xlsx", output.getvalue())

    good = openpyxl.Workbook()
    good.active.title = "Soil"
    good.active.append(["Field", "Value"])
    good.active.append(["A", 2.5])
    good_output = io.BytesIO()
    good.save(good_output)
    parsed = parse_table("soil.xlsx", good_output.getvalue())
    assert parsed["rows"][0]["locator"] == {"sheet": "Soil", "record": 2}
    assert parsed["rows"][0]["values"] == {"Field": "A", "Value": "2.5"}
    assert parsed["member_sha256"]


def test_malformed_xlsx_package_and_truncated_archive_are_validation_errors() -> None:
    with io.BytesIO() as output:
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("foo.txt", "not a workbook")
        unrelated_zip = output.getvalue()
    with pytest.raises(ValueError, match="workbook structure"):
        parse_table("malformed.xlsx", unrelated_zip)

    with io.BytesIO() as output:
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", "not xml")
            archive.writestr("xl/workbook.xml", "not xml")
            archive.writestr("xl/worksheets/sheet1.xml", "not xml")
        malformed_xml_zip = output.getvalue()
    with pytest.raises(ValueError, match="workbook structure"):
        parse_table("broken-xml.xlsx", malformed_xml_zip)

    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    workbook.active.append(["Field", "Value"])
    workbook.active.append(["A", 2])
    output = io.BytesIO()
    workbook.save(output)
    with pytest.raises(ValueError, match="XLSX"):
        parse_table("truncated.xlsx", output.getvalue()[:-30])
