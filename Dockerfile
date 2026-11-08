FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/tickets.db \
    SITE_DIR=/srv/site

WORKDIR /srv/app
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

# application code
COPY app/ /srv/app/
# public static pages only (allowlisted by the app as well)
COPY index.html faq.html contact.html links.html journey.html /srv/site/
COPY en/ /srv/site/en/
COPY assets/ /srv/site/assets/
COPY infographics/ /srv/site/infographics/

RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data \
    && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8080

CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "/dev/null", "--no-control-socket", "app:app"]
