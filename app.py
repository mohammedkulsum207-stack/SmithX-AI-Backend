import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "SM1THX AI Product Assistant"
    })


@app.route("/api/generate-product", methods=["POST"])
def generate_product():
    try:
        if not client:
            return jsonify({
                "error": "AI service is not configured."
            }), 500

        data = request.get_json(silent=True) or {}

        product_name = str(data.get("product_name", "")).strip()
        current_price = data.get("price", "")
        current_category = str(data.get("category", "")).strip()
        current_description = str(
            data.get("description", "")
        ).strip()

        if not product_name:
            return jsonify({
                "error": "Product name is required."
            }), 400

        prompt = f"""
You are the SM1THX AI Product Assistant.

Create a professional e-commerce listing for:

Product: {product_name}
Current price: {current_price}
Category: {current_category}
Description: {current_description}

Return ONLY valid JSON:

{{
  "title": "professional product title",
  "description": "professional product description",
  "category": "Electronics",
  "price": 0,
  "features": [
    "feature 1",
    "feature 2",
    "feature 3",
    "feature 4",
    "feature 5"
  ],
  "seo_keywords": [
    "keyword 1",
    "keyword 2",
    "keyword 3",
    "keyword 4",
    "keyword 5"
  ],
  "ad_caption": "short advertising caption"
}}

Rules:
- Category must be Electronics, Fashion, Home, Beauty, or Accessories.
- Price must be in Kenyan Shillings.
- Do not invent specific technical specifications.
- Keep the description clear and useful.
- Return JSON only.
"""

        response = client.responses.create(
            model="gpt-5-mini",
            input=prompt
        )

        output = response.output_text.strip()

        if output.startswith("```"):
            output = output.replace("```json", "")
            output = output.replace("```", "")
            output = output.strip()

        result = json.loads(output)

        return jsonify(result)

    except Exception as error:
        print("ERROR:", error)

        return jsonify({
            "error": "Unable to generate the product listing."
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
