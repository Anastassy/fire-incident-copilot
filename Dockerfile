FROM python:3.12-slim

WORKDIR /code

# curl is only needed for the `app` service's HEALTHCHECK (docker-compose.yml); harmless
# for the `bridge` service, which reuses this same image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# `bridge` overrides this entrypoint (see docker-compose.yml) since migrations only need
# to run once, from `app`.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
