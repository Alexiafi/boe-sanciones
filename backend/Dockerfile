FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONPATH=/app

# libpango/libcairo/libgdk-pixbuf/fonts-dejavu: required by WeasyPrint to
# render contrato/factura PDFs (services/documentos_pdf.py). shared-mime-info
# lets it detect embedded asset types.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libjpeg62-turbo libopenjp2-7 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test

RUN pip install --no-cache-dir -r requirements-test.txt

CMD ["pytest", "-q"]
