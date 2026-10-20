FROM python:3.15-slim@sha256:2da676046630d7bf14c6764ae1143dc7fa0377a53f94bf5a642f0b214aca5bce
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN mkdir /data && chown 10001:10001 /data
COPY collect /app/collect
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "collect.collect_service"]
