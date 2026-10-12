# Stdlib only, so the image is the interpreter plus the source. No install
# step means nothing to break between local and deployed.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv

COPY app/ /srv/app/
COPY taste/ /srv/taste/
COPY stats.py qloo_client.py /srv/

# Never bake a key into the image. It arrives as a Cloud Run env var.
EXPOSE 8080
CMD ["python3", "app/server.py"]
