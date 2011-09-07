#!/bin/bash

wget -O $1"_depositreceipt.xml" \
--header="Content-Type: application/atom+xml;type=entry" \
--header="In-Progress: true" --auth-no-challenge --no-cookies \
--header "Cookie:__ac=YWRtaW46YWRtaW4%3D" --header "method:PUT" \
--post-file=$1 $2
