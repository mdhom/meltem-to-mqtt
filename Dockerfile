FROM python:3.9-slim-bullseye

ENV MQTT_BROKER=

ENV ADDITIONAL_PARAMETERS=

COPY ./meltem_to_mqtt/*.py ./meltem_to_mqtt/
COPY ./*.py .
COPY ./README.md .

RUN pip install "minimalmodbus>=2.0.1"
RUN pip install paho-mqtt
RUN pip install Events

# install our meltem-to-mqtt package from src
RUN pip install -e ./

ARG RELEASE_NAME
ENV RELEASE=$RELEASE_NAME
RUN echo 'Release: ' ${RELEASE}

CMD e3dc-to-mqtt --releaseName ${RELEASE} --mqtt-broker ${MQTT_BROKER} ${ADDITIONAL_PARAMETERS}