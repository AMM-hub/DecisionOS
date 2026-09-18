FROM python:3.13-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY decisionos_analytics ./decisionos_analytics
RUN pip install --no-cache-dir .
RUN useradd -r worker && mkdir -p /var/lib/decisionos && chown worker /var/lib/decisionos
USER worker
EXPOSE 8100
CMD ["uvicorn", "decisionos_analytics.serve:app", "--host", "0.0.0.0", "--port", "8100"]
