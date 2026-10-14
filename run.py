"""Start the PhishCheck server:  python run.py   (then open http://127.0.0.1:5000)"""
import logging

from server import config, rag
from server.app import create_app

if __name__ == "__main__":
    log = logging.getLogger("phishcheck")
    log.info("Loading the embedding model...")
    rag.warm_up()
    log.info("PhishCheck running at http://127.0.0.1:%s", config.FLASK_PORT)
    create_app().run(host="127.0.0.1", port=config.FLASK_PORT, debug=False)
