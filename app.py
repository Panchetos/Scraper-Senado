import os
from flask import Flask

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def iniciar_scraper():
    return "Scraping en construccion", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
