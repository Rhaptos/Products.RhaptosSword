#!/bin/bash

wget -q -O- --user=$1 --password=$1 \
--auth-no-challenge \
--no-cookies \
--header="Content-Type: application/atom+xml;type=entry" \
--header="In-Progress: True"\
--header="Slug: atom entry testmodule"\
--post-file=$3 $4
