#!/bin/bash

# SPDX-License-Identifier: BSD-2-Clause

docker run --platform=linux/amd64 -v ${PWD}:/src ghcr.io/google/addlicense -v -check -l BSD-2-Clause -c "ChipFlow" -s=only -ignore **/__init__.py **/*.py


