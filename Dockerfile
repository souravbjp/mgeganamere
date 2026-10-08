# Python 3.11 official slim image use kora hocche
FROM python:3.11-slim

# Container-er vitor working directory set kora holo
WORKDIR /app

# Proyojoniyo system package install kora hocche (curl_cffi ba pycryptodome er jonno lagte pare)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt copy kore dependency install kora
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tomar project-er sob file copy kora (mega folder, megarenamerbot.py etc.)
COPY . .

# Health check server-er jonno port expose kora
ENV PORT=8000
EXPOSE 8000

# Bot run korar main command
CMD ["python", "megarenamerbot.py"]
