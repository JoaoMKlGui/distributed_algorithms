# Dockerfile to build the node image (Python + gRPC)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install necessary dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages (grpc + tools)
RUN pip install --no-cache-dir grpcio grpcio-tools protobuf

# Copy proto and code
COPY proto/ ./proto/
COPY server/ ./server/
COPY client/ ./client/

# Compiles the gRPC artifacts from the proto
RUN python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. proto/distributed.proto

# This final command will run the server (env variables are expected to be defined)
EXPOSE 50051
CMD ["python", "server/node_server.py"]
