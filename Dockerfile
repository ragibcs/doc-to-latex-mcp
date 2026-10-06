FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends texlive-xetex texlive-latex-extra texlive-fonts-recommended fonts-texgyre lmodern ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
RUN useradd --create-home --uid 10001 folio
COPY --chown=folio:folio . .
USER folio
ENV PORT=10000 WORKSPACE_DIR=/tmp/folio-jobs
EXPOSE 10000
CMD ["python", "server.py"]
