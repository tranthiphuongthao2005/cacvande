FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/contracts.py app/trace_store.py app/context_store.py app/incident_context.py app/rule_detection.py app/hybrid_detection.py ./app/
COPY app/monitoring_*.py app/context_integration*.py app/workflow_*.py app/mock_analysis_api.py ./app/
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
CMD ["python", "-m", "app.workflow_dispatcher"]
