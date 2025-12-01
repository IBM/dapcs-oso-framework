# Environment variables to set in the terminal running the plugin
```
export APP__NAME="my-plugin"
export APP__ENTRY="oso.framework.plugin:create_app"
export PLUGIN__APPLICATION=helloworld:HelloWorld

export PLUGIN__ADDONS__0__TYPE="oso.framework.plugin.addons.signing_server"
export PLUGIN__ADDONS__0__CA_CERT="$(base64 -w0 grep11ca.pem)"
export PLUGIN__ADDONS__0__CLIENT_KEY="$(base64 -w0 grep11client-key.pem)"
export PLUGIN__ADDONS__0__CLIENT_CERT="$(base64 -w0 grep11client.pem)"
export  PLUGIN__ADDONS__0__GREP11_ENDPOINT=192.168.96.21:9876
export  PLUGIN__ADDONS__0__KEYSTORE_PATH="/tmp/newkeystore.db"
```
Assumption is that the grep11 service is available to have the backend working with HSM


# Sample tx to test backend mode

```
echo '{"documents":[{"id":"genedis1","content":"{ \"command\": \"GENERATE\", \"nb\": 2 }","metadata":"genesis"}, {"id":"genedis2","content":"{ \"command\": \"GENERATE\", \"nb\": 2 }","metadata":"genesis"}],"count":2}' > txfile.json

echo '{"documents":[{"id":"sig1","content":"{ \"command\": \"SIGN\", \"key_id\": \"e5d2f569-7992-417a-be1c-6e1ac1115f88\", \"data\":\"helloworld\" }","metadata":"dummy"}],"count":1}' > txfile.json

echo '{"documents":[{"id":"sig1","content":"{ \"command\": \"VERIFY\", \"key_id\": \"e5d2f569-7992-417a-be1c-6e1ac1115f88\", \"signature\":\"5be6031f31cd989992b15f6c8d549731a83de04ba66e9c36415ceec5963c018be34ebeab78d15908ba781a36f26d12ce380598e80854e03dab70fedd757f2114\",\"data\":\"helloworld\" }","metadata":"dummy"}],"count":1}' > txfile.json
```

# End to End test  

- Start the dummy custody (osopluginsrv) `./server.sh`

`copy tx1.json tx.json` to test key generation

`copy tx2.json tx.json` to test signing

- e2e test 
```
export HW__API_URL="http://localhost:8000/custody"

PLUGIN__MODE=frontend uv  run start-component
curl -s -X GET http://127.0.0.1:8080/api/frontend/v1alpha1/documents  | tee txfile.json
 
PLUGIN__MODE=backend uv  run start-component
curl -s -X POST -d @txfile.json -k http://127.0.0.1:8080/api/backend/v1alpha1/documents
curl -s -X GET http://127.0.0.1:8080/api/backend/v1alpha1/documents | tee txsigned.json

PLUGIN__MODE=frontend uv  run start-component
curl -s -X POST -d @txsigned.json http://127.0.0.1:8080/api/frontend/v1alpha1/documents
```

- check the result in `/tmp/received.json` !

