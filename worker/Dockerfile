FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Treina/salva o modelo na construção da imagem
RUN python -m app.modelo

CMD ["python", "-m", "app.worker"]
