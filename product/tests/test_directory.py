"""Pruebas de app.directory."""

import pytest

from app.directory import Directory, DirectoryError


def test_employee_is_found_by_id(directory):
    employee = directory.get_employee("EMP-0004")

    assert employee["name"] == "Jorge Díaz"


def test_unknown_employee_is_reported_as_missing(directory):
    assert directory.get_employee("EMP-9999") is None


def test_department_search_ignores_case_and_accents(directory):
    found = directory.search_by_department("tecnologia")

    assert [e["id"] for e in found] == ["EMP-0001", "EMP-0003", "EMP-0004"]
    assert directory.search_by_department("Legal") == []


@pytest.mark.parametrize("content", [None, "[{ not json"])
def test_missing_or_invalid_file_fails_with_a_clear_error(tmp_path, content):
    path = tmp_path / "employees.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    with pytest.raises(DirectoryError):
        Directory(path)
