from oso.framework.plugin.base import PluginProtocol
from oso.framework.data.types import V1_3
from oso.framework.plugin import current_oso_plugin
from oso.framework.plugin.addons.signing_server import SigningServerAddon, KeyType
from pydantic_settings import BaseSettings, SettingsConfigDict

import sys
import json
import logging
import requests

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("helloworld plugin")

class HelloWorld(PluginProtocol):
    class Config(BaseSettings):
        api_url: str = "http://localhost:8000/custody"
        model_config = SettingsConfigDict(env_prefix="HW__")

    def __init__(self, plugin_config: dict | None = None):
        super().__init__()
        self.Backend_TxAnswerList = None
        self.config = self.Config(**(plugin_config or {}))

    def to_oso(self):
        try:
          match current_oso_plugin().config.mode:
            #Retrieve doc from the custody and returns it as an OSO doc list
            case "frontend":
               # Example metadata value (adjust as needed)
               meta = {"source": "custody"}

               # Query the API
               response = requests.get(self.config.api_url)
               response.raise_for_status()  # raise exception if request failed

               # Parse JSON array
               data = response.json()
               docs =  []  

               # Loop through each item and generate a Document snippet
               for i, item in enumerate(data, start=1):
                   doc_id = item.get("id", "")
                   content = item.get("content", "") 
                   doc = V1_3.Document(
                       id=doc_id,
                       content=content,
                       metadata=json.dumps(meta),
                   )   
                   docs.append(doc)
            #Retrieve HSM signed tx and sent them back to OSO as a doc list !
            case "backend":
              docs = self.Backend_TxAnswerList
        except Exception:
          logger.exception("Error in HelloWorld plugin")
          raise

        # Build docs here...
        return V1_3.DocumentList(documents=docs,count=len(docs))

    def to_isv(self, oso):
      try:
          logger.debug(f"Entering to_oso()")
          logger.info(current_oso_plugin().config.mode)
          mode_value = current_oso_plugin().config.mode
          match current_oso_plugin().config.mode:
            #Send the OSO doc list to the custody  
            case "frontend":
              API_URL = self.config.api_url
              # Prepare list of documents
              docs_payload = []
              for doc in oso.documents:
                  docs_payload.append({
                      "txid": doc.id,
                      "result": doc.content
                  })

              try:
                  response = requests.post(f"{API_URL}/", json=docs_payload)
                  response.raise_for_status()  # raise error if HTTP status is 4xx/5xx
                  logger.info(f"All documents sent successfully: {response.status_code}")
              except requests.RequestException as e:
                  logger.error(f"Failed to send documents: {e}")
            case "backend":
              signing_server = current_oso_plugin().addons["SigningServer"]
              self.Backend_TxAnswerList = [] 
              for doc in oso.documents:
                  logger.info(f"Processing document: {doc.id}")

                  try:
                      # doc.content contains the JSON command
                      command_data = json.loads(doc.content)
                      command = command_data.get("command", "").upper()
                  except (json.JSONDecodeError, AttributeError) as e:
                      logger.error(f"Invalid JSON in doc.content: {e}")
                      continue

                  # Create a copy of the doc to hold the result
                  newdoc = V1_3.Document(
                      id=doc.id,
                      content="",  # will set below
                      metadata=doc.metadata
                  )

                  if command == "GENERATE":
                      nb = int(command_data.get("nb", 1))
                      keys_info = []
                      for _ in range(nb):
                          key_id, pub_key_pem = signing_server.generate_key_pair(KeyType.SECP256K1)
                          keys_info.append({
                            "keyid": key_id,
                            "public_key": pub_key_pem
                          })
                      newdoc.content = json.dumps(keys_info)
                      logger.info(f"Generated keys for {doc.id}: {keys_info}")

                  elif command == "SIGN":
                      # Get parameters from parsed JSON
                      key_id = command_data.get("key_id")
                      data = command_data.get("data", "").encode()
                      signature = signing_server.sign(key_id, data)
                      newdoc.content = signature
                      newdoc.metadata="signature"
                      logger.info(f"Generated signature for {doc.id}: {newdoc.content}")

                  elif command == "VERIFY":
                      key_id = command_data.get("key_id")
                      signature_hex = command_data.get("signature", "")
                      data = command_data.get("data", "").encode()
                      verified = signing_server.verify(key_id, data, signature_hex)
                      newdoc.content = str(verified)
                      newdoc.metadata="verify"
                      logger.info(f"Verification result for {doc.id}: {newdoc.content}")

                  else:
                      logger.warning(f"Unknown command: {command}")
                      continue

                  # Update the singleton key store with the processed doc content
                  self.Backend_TxAnswerList.append(newdoc)
                  logger.info(f"Backend_TxAnswerList updated with {newdoc.id}")

                  # Optionally, replace the original doc with newdoc in oso.documents

      except Exception as e:
        logger.exception(f"Error in to_isv: {e}")
      return ["OK"]
 
    def status(self):
         return V1_3.ComponentStatus(
               status_code=200,
               status="OK",
               errors=[],
         )
