# Stage 1: Builder
FROM python:3.10-slim AS builder
WORKDIR /app
COPY requirements.txt.
RUN pip install --no-cache-dir -r requirements.txt
COPY src/.

# Stage 2: Final Image
FROM python:3.10-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /app /app

# Non-root user
RUN useradd --no-create-home appuser
USER appuser

CMD ["python", "main.py"]
