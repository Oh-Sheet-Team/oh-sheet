FROM python:3.12-slim

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install --no-cache-dir /app/shared

COPY svc-inference/ /app/svc-inference/
RUN cd /app/svc-inference && pip install --no-cache-dir .

ENV OHSHEET_INFERENCE_HOST=0.0.0.0 \
    OHSHEET_INFERENCE_PORT=8080 \
    OHSHEET_INFERENCE_RUNNER=stub

EXPOSE 8080

CMD ["uvicorn", "inference.app:app", "--host", "0.0.0.0", "--port", "8080"]
