#!/bin/bash
docker build --rm -f Dockerfile -t mdhom/meltem-to-mqtt:latest --build-arg RELEASE_NAME=LocalPythonPack .