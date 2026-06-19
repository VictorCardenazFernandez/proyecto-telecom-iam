FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY provisioner.py .

# El provisioner corre en modo demonio (bucle infinito con POLL_INTERVAL)
CMD ["python", "-u", "provisioner.py"]
