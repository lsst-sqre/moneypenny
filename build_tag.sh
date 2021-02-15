#!/bin/sh

set -e
R="lsstsqre/moneypenny"
T="dev"
I="${R}:${T}"
L="${R}:latest"

docker build -t ${I} . --platform=amd64
docker tag ${I} ${L}
docker push ${I}
docker push ${L}
