"""Archivos de despliegue de la sesión 5 (requisito 13 del plan).

Se leen como texto: no hace falta Docker ni Render. ``render.yaml`` lo cambia
deploy (fase 7) y ``.env.example`` lo cambia costs (fase 5): hasta entonces
estas pruebas fallan, y es lo esperado. Nunca se lee ``.env``.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Dependencias de la sesión 4: la sesión 5 usa solo la biblioteca estándar.
SESSION4_REQUIREMENTS = {
    "fastapi", "uvicorn", "pydantic", "httpx", "langsmith", "pytest",
    "pytest-bdd", "pytest-cov", "pylint", "pytest-playwright",
}


def _read(relative):
    """Lee un archivo de ``product/`` como texto."""
    return (ROOT / relative).read_text(encoding="utf-8")


def _env_example():
    """Variables de ``.env.example`` como diccionario ``{nombre: valor}``."""
    values = {}
    for line in _read(".env.example").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def test_render_runs_in_multi_mode_and_asks_for_the_gateway_id_as_a_secret():
    blueprint = _read("render.yaml")

    assert re.search(r'key:\s*ORCHESTRATION\s+value:\s*"?multi"?', blueprint)
    assert re.search(r"key:\s*CF_GATEWAY_ID\s+sync:\s*false", blueprint)
    assert re.search(r"name:\s*hr-assistant\b", blueprint)


def test_env_example_documents_the_new_variables_with_safe_defaults():
    values = _env_example()

    assert values.get("ORCHESTRATION") in ("single", "multi")
    assert values.get("MAX_ANSWER_CHARS") == "2000"
    assert "CF_GATEWAY_ID" in values


DEV_ONLY_REQUIREMENTS = {
    "pytest", "pytest-bdd", "pytest-cov", "pylint", "pytest-playwright",
}


def _requirement_names(relative):
    """Nombres de paquete de un requirements y sus directivas ``-r``.

    Ignora comentarios y líneas vacías. Devuelve ``(nombres, directivas)``;
    cualquier línea que empiece por ``-`` se trata como directiva, nunca
    como paquete, para que la prueba decida si es aceptable.
    """
    names, directives = set(), []
    for line in _read(relative).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            directives.append(" ".join(line.split()))
        else:
            names.add(re.split(r"[<>=!~\[ ;]", line, maxsplit=1)[0].lower())
    return names, directives


def test_requirements_add_no_new_dependencies():
    prod, prod_directives = _requirement_names("requirements.txt")
    dev, dev_directives = _requirement_names("requirements-dev.txt")

    # Solo se admite que desarrollo incluya producción; nada más.
    assert not prod_directives
    assert dev_directives == ["-r requirements.txt"]
    # Producción no arrastra herramientas de pruebas ni de estilo.
    assert not prod & DEV_ONLY_REQUIREMENTS
    # Entre los dos archivos, exactamente las dependencias de la sesión 4.
    assert prod | dev == SESSION4_REQUIREMENTS


def test_dockerfile_installs_only_from_requirements_txt():
    dockerfile = _read("Dockerfile")

    installs = re.findall(r"pip install[^\n]*", dockerfile)
    assert installs == ["pip install --no-cache-dir -r requirements.txt"]
    assert re.search(r"^FROM python:3\.12-slim", dockerfile, re.M)
