FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Treina/salva o modelo na construção da imagem (a subida do container fica rápida)
RUN python -m app.modelo
# Gera os stubs gRPC (arquivos *_pb2*.py são ignorados pelo git)
RUN python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/inferencia.proto

EXPOSE 8001
CMD ["uvicorn", "app.api_rest:app", "--host", "0.0.0.0", "--port", "8001"]
