FROM python:3.12-slim

WORKDIR /opt/app

# Install dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/

CMD ["python", "-m", "app.bot"]
