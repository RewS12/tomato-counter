FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-ai.txt ./
ARG INSTALL_AI=false
RUN python -m pip install --no-cache-dir -r requirements.txt && if [ "$INSTALL_AI" = "true" ]; then python -m pip install --no-cache-dir -r requirements-ai.txt; fi
COPY backend ./backend
COPY frontend ./frontend
COPY data ./data
COPY models ./models
RUN mkdir -p /app/runtime/images && useradd --uid 10001 --create-home agrovision && chown -R agrovision:agrovision /app/runtime /app/models
USER agrovision
EXPOSE 8000
CMD ["python","-m","uvicorn","backend.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","127.0.0.1"]
