#!/bin/bash

# Pull the latest image
docker pull ghcr.io/check-the-vibe/vibestack:0.0.1

# Run the container
docker run -it -d \
  -p 222:22 \
  -p 80:80 \
  -v $(pwd):/home/vibe/code \
  -v /workspace/home:/home/vibe/ \
  ghcr.io/check-the-vibe/vibestack:0.0.1