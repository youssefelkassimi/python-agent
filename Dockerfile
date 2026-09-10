FROM python:3.12-slim

WORKDIR /app

# iputils-ping: used as an ICMP fallback when icmplib can't open raw/
# unprivileged sockets in this container (very common without
# --cap-add=NET_RAW). procps for `top`, if allow-listed in remote_commands.
RUN apt-get update && apt-get install -y --no-install-recommends \
        iputils-ping \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Health endpoint, if enabled in config.yaml with host: "0.0.0.0"
EXPOSE 9273

CMD ["python3", "main.py"]
