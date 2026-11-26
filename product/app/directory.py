"""Directorio de empleados de solo lectura."""

import json
import unicodedata
from pathlib import Path


class DirectoryError(Exception):
    """El archivo de empleados falta o no es válido."""


def _normalize(text: str) -> str:
    """Pasa a minúsculas y quita acentos.

    :param text: Texto original.
    :return: Texto normalizado para comparar.
    """
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class Directory:
    """Acceso de solo lectura a los datos de empleados.

    :param path: Ruta del archivo JSON de empleados.
    :raises DirectoryError: Si el archivo falta o es inválido.
    """

    def __init__(self, path):
        try:
            raw = Path(path).read_text(encoding="utf-8")
            data = json.loads(raw)
        except OSError as error:
            raise DirectoryError(f"Cannot read employees file: {path}") from error
        except json.JSONDecodeError as error:
            raise DirectoryError(f"Invalid JSON in employees file: {path}") from error
        if not isinstance(data, list):
            raise DirectoryError(f"Employees file must hold a list: {path}")
        self._employees = tuple(data)

    @property
    def departments(self) -> list:
        """Departamentos distintos presentes en los datos.

        :return: Lista de nombres de departamento.
        """
        names = {e.get("department", "") for e in self._employees}
        return sorted(name for name in names if name)

    def get_employee(self, employee_id: str):
        """Busca un empleado por id.

        :param employee_id: Id con forma ``EMP-0001``.
        :return: El empleado o ``None`` si no existe.
        """
        for employee in self._employees:
            if employee.get("id") == employee_id:
                return dict(employee)
        return None

    def search_by_department(self, department: str) -> list:
        """Lista los empleados de un departamento.

        :param department: Nombre, sin distinguir mayúsculas ni acentos.
        :return: Lista de empleados (vacía si no hay).
        """
        wanted = _normalize(department)
        return [
            dict(e)
            for e in self._employees
            if _normalize(e.get("department", "")) == wanted
        ]
