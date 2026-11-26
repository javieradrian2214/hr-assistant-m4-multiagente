"""Verificación estática de los archivos de despliegue (sesión 4).

Se leen como texto: no hace falta Docker, Render ni GitHub para probarlos.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = ["style", "unit", "e2e", "docker"]


def _read(relative):
    """Lee un archivo del repositorio (``product/``) como texto."""
    return (ROOT / relative).read_text(encoding="utf-8")


def _job_block(workflow, job):
    """Devuelve el texto de un trabajo del workflow."""
    pattern = rf"^  {job}:\n(.*?)(?=^  [\w-]+:\n|\Z)"
    match = re.search(pattern, workflow, re.M | re.S)
    assert match, f"job {job} is missing"
    return match.group(1)


def test_dockerfile_runs_uvicorn_as_non_root_and_dockerignore_hides_secrets():
    """Imagen slim, usuario sin root, puerto de ${PORT} y sin .env dentro."""
    dockerfile = _read("Dockerfile")
    assert re.search(r"^FROM python:3\.12-slim", dockerfile, re.M)
    assert re.search(r"^USER\s+(?!root\b)\S+", dockerfile, re.M)
    command = "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
    assert command in dockerfile

    ignored = _read(".dockerignore").split()
    for entry in (".env", "tests/", "e2e/", "__pycache__", ".pytest_cache"):
        assert entry in ignored or entry + "/" in ignored


def test_render_blueprint_publishes_only_after_checks_and_keeps_secrets_out():
    """Nombre del repositorio, docker/free, checksPass y secretos con sync."""
    blueprint = _read("render.yaml")
    assert re.search(r"name:\s*hr-assistant\b", blueprint)
    for line in ("runtime: docker", "plan: free", "healthCheckPath: /health",
                 "autoDeployTrigger: checksPass"):
        assert line in blueprint
    for name, value in (("ENVIRONMENT", "production"),
                        ("MODEL_PROVIDER", "gateway"),
                        ("HIDE_INPUTS", "true"), ("HIDE_OUTPUTS", "true"),
                        ("EMPLOYEES_PATH", "data/employees.json")):
        assert re.search(rf'key:\s*{name}\s+value:\s*"?{value}"?', blueprint)
    for name in ("API_KEYS", "CF_ACCOUNT_ID", "CF_API_TOKEN"):
        assert re.search(rf"key:\s*{name}\s+sync:\s*false", blueprint)
    assert "LANGSMITH_API_KEY" not in blueprint
    assert (ROOT / "data" / "employees.json").is_file()


def test_ci_has_four_chained_jobs_with_the_quality_gates():
    """style -> unit -> e2e -> docker, en cada push y pull request."""
    workflow = _read(".github/workflows/ci.yml")
    assert re.search(r"^on:", workflow, re.M)
    assert "push" in workflow and "pull_request" in workflow
    previous = None
    for job in JOBS:
        block = _job_block(workflow, job)
        needs = re.search(r"needs:\s*\[?\s*([\w-]+)", block)
        assert (needs.group(1) if needs else None) == previous
        previous = job
    assert "--max-line-length=88" in _job_block(workflow, "style")
    assert "--cov-fail-under=80" in _job_block(workflow, "unit")
    assert "docker build" in _job_block(workflow, "docker")


def test_index_page_keeps_the_key_in_session_storage_only():
    """Campo de contraseña, sessionStorage, X-API-Key y mensajes de error."""
    page = _read("app/static/index.html")
    assert re.search(r'data-testid="api-key"', page)
    assert re.search(r'<input[^>]*type="password"[^>]*>', page)
    assert "sessionStorage" in page
    assert "localStorage" not in page
    assert "X-API-Key" in page
    assert "Clave inválida" in page
    assert "Demasiadas preguntas; espera" in page
