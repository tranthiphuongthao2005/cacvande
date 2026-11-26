FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest==8.3.5
COPY pytest.ini .
COPY app/api.py app/storage.py app/telemetry.py app/producer_accounting.py ./app/
COPY tests/test_integration.py ./tests/
USER 10001:10001
CMD ["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_integration.py"]
