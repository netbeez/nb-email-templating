# nb-email-templating runtime image
FROM python:3.11-slim AS runtime
WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY dashboard_templates/ dashboard_templates/
COPY static/ static/
RUN pip install --no-cache-dir .

RUN adduser --disabled-password --gecos "" appuser
RUN mkdir -p /app/data /app/logs /app/email_templates /app/config && chown -R appuser:appuser /app

USER appuser
ENV PYTHONUNBUFFERED=1
ENV CONFIG_PATH=/app/config/config.yaml
ENV EMAIL_TEMPLATES_DIR=/app/email_templates
ENV DATA_DIR=/app/data
ENV DASHBOARD_TEMPLATES_DIR=/app/dashboard_templates
ENV STATIC_DIR=/app/static
EXPOSE 8025
ENTRYPOINT ["uvicorn", "nb_email_templating.main:app", "--host", "0.0.0.0", "--port", "8025"]
