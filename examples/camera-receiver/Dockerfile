# Supply an approved, immutable Clean slate digest at build time.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN useradd --uid 10001 --create-home --groups admiral-video robot-app \
    && mkdir -p /opt/app /var/lib/robot-app \
    && chown robot-app:robot-app /var/lib/robot-app
COPY --chown=robot-app:robot-app app.py /opt/app/app.py
ENV UNITREE_APP_USER=robot-app UNITREE_APP_DIR=/opt/app
# Keep the inherited ENTRYPOINT so robot services start and remain supervised.
CMD ["/usr/bin/python3", "-u", "/opt/app/app.py"]
