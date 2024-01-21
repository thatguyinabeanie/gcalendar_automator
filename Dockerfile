FROM python:3.12-slim

ENV RUNNING_IN_DOCKER 1
ENV APP_HOME=/app

# set work directory
WORKDIR ${APP_HOME}

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN mkdir -p ${APP_HOME}

COPY . $APP_HOME

RUN \
    addgroup --system app && adduser --system --group app && \
    pip install -r requirements.txt && \
    sed -i 's/\r$//g'  $APP_HOME/entrypoint.sh && \
    chmod +x  $APP_HOME/entrypoint.sh && \
    chown -R app:app $APP_HOME

# change to the app user
USER app

ENTRYPOINT ["/app/entrypoint.sh"]
