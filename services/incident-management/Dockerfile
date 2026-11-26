FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && install -d -o 10001 -g 10001 -m 0750 /data /source
COPY app/contracts.py app/trace_store.py app/context_store.py app/incident_context.py app/rule_detection.py app/hybrid_detection.py ./app/
COPY app/context_integration_models.py app/context_integration_client.py app/monitoring_models.py app/workflow_models.py ./app/
COPY app/incident_api.py app/incident_config.py app/incident_handoff.py app/incident_models.py app/incident_store.py app/scenario_incident_store.py ./app/
USER 10001:10001
CMD ["uvicorn", "app.incident_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
