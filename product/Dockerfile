# Imagen del HR Assistant: dos etapas sobre Python slim fijado por digest,
# solo dependencias de producción, usuario sin privilegios y puerto de Render.

# ---------------------------------------------------------------------------
# Etapa 1 (builder): instala las dependencias de producción en un venv y
# prepara el código y los datos con sus permisos finales.
# ---------------------------------------------------------------------------
# La base se fija por digest para que cada construcción parta exactamente de
# la misma imagen (reproducible); la etiqueta queda solo como referencia.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# El venv vive fuera de /app para copiarlo entero a la etapa final.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Solo requirements.txt (producción): las herramientas de desarrollo y de
# pruebas están en requirements-dev.txt y no entran en la imagen.
# Después se quitan pip, setuptools y wheel del venv: solo sirven para
# instalar y la etapa final no debe llevar un instalador de paquetes.
# requirements.txt y constraints.txt quedan en /build, fuera de /build/app y
# /build/data, así que no llegan a la etapa final.
# PIP_CONSTRAINT hace que pip respete las versiones fijadas en constraints.txt
# (directas e indirectas). Se define solo en el entorno de esa orden RUN: no
# persiste en la capa ni llega a la etapa final.
WORKDIR /build
COPY requirements.txt constraints.txt ./
RUN PIP_CONSTRAINT=/build/constraints.txt pip install --no-cache-dir -r requirements.txt
RUN python -m pip uninstall -y pip setuptools wheel \
    && chmod -R u=rwX,go=rX /opt/venv

# Código y datos con permisos de solo lectura para todos salvo root. Se
# ajustan aquí y no en la etapa final para no duplicar archivos en otra capa.
COPY app/ /build/app/
COPY data/ /build/data/
RUN chmod -R u=rwX,go=rX /build

# ---------------------------------------------------------------------------
# Etapa 2 (final): solo el intérprete, el venv y lo que la app lee.
# ---------------------------------------------------------------------------
# Misma base y mismo digest que el builder: los enlaces del venv apuntan al
# intérprete de /usr/local, que es idéntico en las dos etapas.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

# Sin bytecode en disco: el código es de solo lectura para el usuario del servicio.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

# También se quita el pip del sistema que trae la imagen base: en ejecución
# nadie instala paquetes (si un paquete no está, pip solo avisa y sigue).
RUN python -m pip uninstall -y pip setuptools wheel \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

# COPY deja todo como propiedad de root (no se usa --chown) y conserva los
# permisos de solo lectura preparados en el builder: appuser puede leer y
# ejecutar, pero no escribir. La aplicación solo lee app/ y data/ y escribe
# sus logs en stdout.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Solo lo que la aplicación usa en ejecución: el código (con app/static/) y
# los datos por omisión (data/employees.json y data/model_prices.json).
COPY --from=builder /build/app ./app
COPY --from=builder /build/data ./data

# El servicio no corre como root.
USER appuser

EXPOSE 8000

# Render define PORT; en local se usa 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
