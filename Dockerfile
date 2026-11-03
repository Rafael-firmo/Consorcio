FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./

ENV PYTHONUNBUFFERED=1 PORTA=5001 DADOS=/dados
EXPOSE 5001

CMD ["python", "servidor.py"]
