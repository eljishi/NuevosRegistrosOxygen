FROM python:3.12-slim
WORKDIR /app
COPY backend/ backend/
RUN pip install --no-cache-dir fastapi uvicorn
WORKDIR /app/backend
CMD ["python", "server.py"]
