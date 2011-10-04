Some background on wget usage:

Setup a multipart post with the following parameters:
- post-file: data/mulitpart.txt
- credentials of user1
- target URL of http://localhost:8080/Members/user1/sword
- boundary must obviously match the one used in the file mulitpart.txt

wget -q -O- --user=user1 --password=user1 --auth-no-challenge \
 --header='Content-Type: multipart/related; boundary="===============1338623209=="' \
 --header="Slug: testmodule" --header="In-Progress: True" \
 --post-file=./data/multipart.txt http://localhost:8080/Members/user1/sword

