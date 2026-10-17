ARG UV_IMAGE
ARG PYTHON_IMAGE
FROM ${UV_IMAGE} AS uvbin
FROM ${PYTHON_IMAGE}
COPY --from=uvbin /uv /uvx /usr/local/bin/
WORKDIR /app
COPY . /app
RUN uv sync --frozen --no-dev --extra reference \
    && mkdir -p /app/artifacts \
    && chown -R 10001:10001 /app/artifacts
USER 10001:10001
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["/app/.venv/bin/python", "/app/tools/container_entry.py"]
