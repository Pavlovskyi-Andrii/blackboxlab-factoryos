FROM node:22-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --break-system-packages requests \
    && npm install -g @anthropic-ai/claude-code

RUN useradd -m -u 10001 agent
USER agent
WORKDIR /work

COPY --chown=agent:agent autopilot/autopilot.py /work/autopilot.py
COPY --chown=agent:agent autopilot/notify.py /work/notify.py

CMD ["python3", "/work/autopilot.py"]
