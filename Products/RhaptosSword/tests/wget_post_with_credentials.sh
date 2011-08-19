#!/bin/bash

wget -q -O- --user=$1 --password=$1 --auth-no-challenge --header='Content-Type: multipart/related; boundary="===============1338623209=="' --header="Slug: testmodule" --header="In-Progress: True" --post-file=$3 $4
