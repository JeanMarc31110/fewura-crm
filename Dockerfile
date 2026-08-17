FROM python:3.11-slim

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FEWURA_CRM_HOST=0.0.0.0 \
    FEWURA_CRM_PORT=8020

WORKDIR /app

# Install build deps required for some wheels (lxml, cryptography, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libxml2-dev \
       libxslt1-dev \
       libffi-dev \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

EXPOSE 8020

# Default command runs the agent which starts uvicorn
CMD ["python", "agent.py"]
