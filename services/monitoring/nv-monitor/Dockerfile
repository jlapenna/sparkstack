FROM ubuntu:26.04
RUN apt-get update && apt-get install -y curl ca-certificates libncursesw6 python3 && rm -rf /var/lib/apt/lists/*
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "amd64" ]; then \
        BIN_ARCH="amd64"; \
    else \
        BIN_ARCH="arm64"; \
    fi && \
    curl -sL "https://github.com/wentbackward/nv-monitor/releases/download/v1.12.0/nv-monitor-linux-${BIN_ARCH}" -o /usr/local/bin/nv-monitor && \
    chmod +x /usr/local/bin/nv-monitor
COPY proxy.py /usr/local/bin/proxy.py
CMD /usr/local/bin/nv-monitor -n -p 9102 & python3 /usr/local/bin/proxy.py
