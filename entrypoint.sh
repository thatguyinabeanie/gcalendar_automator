#!/bin/bash

# if RUNNING_IN_DOCKER is not true
if [ -z "$RUNNING_IN_DOCKER" ]; then
    echo "RUNNING_IN_DOCKER is not set"
    echo "Setting up environment variables"
    # Load environment variables from .env file
    if [ -f .env ]
    then
        export $(cat .env | sed 's/#.*//g' | xargs)
    fi
fi

# echo "Current working directory: $(pwd)"
python ./gmail_client.py


