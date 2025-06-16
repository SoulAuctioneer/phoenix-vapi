#!/bin/bash

clear
git pull || echo "Git pull failed, continuing..."
./run.sh "$@"
