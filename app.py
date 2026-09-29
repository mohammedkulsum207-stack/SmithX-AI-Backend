import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)

CORS(app)

# ============================================================
# OPENAI SETUP
# ============================================================

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    client = OpenAI(api_key=api_key)
else:
    client = None


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "SM1THX AI Product Assistant",
        "ai_configured": bool(api_key)
    })


# ============================================================
# AI PRODUCT GENERATOR
# ============================================================

@app.route("/api/generate-product", methods=["POST"])
def generate_product():

    try:

        # ----------------------------------------------------
        # CHECK API KEY
        # ----------------------------------------------------

        if not client:

            print(
                "ERROR: OPENAI_API_KEY is missing.",
                flush=True
            )

            return jsonify({
                "error": "AI service is not configured on the server."
            }), 500


        # ----------------------------------------------------
        # READ REQUEST
        # ----------------------------------------------------

        data = request.get_json(silent=True) or {}

        product_name = str(
            data.get("product_name", "")
        ).strip()

        current_price = data.get(
            "price",
            ""
        )

        current_category = str(
            data.get("category", "")
        ).strip()

        current_description = str(
            data.get("description", "")
        ).strip()


        # ----------------------------------------------------
        # VALIDATE PRODUCT
        # ----------------------------------------------------

        if not product_name:

            return jsonify({
                "error": "Product name is required."
            }), 400


        # ----------------------------------------------------
        # CREATE AI PROMPT
        # ----------------------------------------------------

        prompt = f"""
You are the SM1THX AI Product Assistant.

Create a professional e-commerce listing for:

Product: {product_name}

Current price: {current_price}

Category: {current_category}

Description: {current_description}

Return ONLY valid JSON.

Use exactly this structure:

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
- Do not invent unsupported product claims.
- Keep the description clear and useful.
- Features should be short and useful.
- SEO keywords should be relevant.
- The advertisement caption should be short.
- Return JSON only.
- Do not use markdown.
- Do not add explanations outside the JSON.
"""


        # ----------------------------------------------------
        # CALL OPENAI
        # ----------------------------------------------------

        print(
            "SM1THX: Sending request to OpenAI...",
            flush=True
        )

        response = client.responses.create(
            model="gpt-5-mini",
            input=prompt
        )

        print(
            "SM1THX: OpenAI response received.",
            flush=True
        )


        # ----------------------------------------------------
        # READ RESPONSE
        # ----------------------------------------------------

        output = response.output_text.strip()

        if not output:

            print(
                "ERROR: OpenAI returned an empty response.",
                flush=True
            )

            return jsonify({
                "error": "AI returned an empty response."
            }), 500


        # ----------------------------------------------------
        # REMOVE CODE FENCES
        # ----------------------------------------------------

        if output.startswith("```"):

            output = output.replace(
                "```json",
                ""
            )

            output = output.replace(
                "```",
                ""
            )

            output = output.strip()


        # ----------------------------------------------------
        # CONVERT AI RESPONSE TO JSON
        # ----------------------------------------------------

        try:

            result = json.loads(output)

        except json.JSONDecodeError as error:

            print(
                "JSON PARSE ERROR:",
                repr(error),
                flush=True
            )

            print(
                "AI OUTPUT:",
                output,
                flush=True
            )

            return jsonify({
                "error": "AI returned an invalid product format."
            }), 500


        # ----------------------------------------------------
        # VALIDATE AI RESULT
        # ----------------------------------------------------

        required_fields = [
            "title",
            "description",
            "category",
            "price",
            "features",
            "seo_keywords",
            "ad_caption"
        ]

        missing_fields = [
            field
            for field in required_fields
            if field not in result
        ]

        if missing_fields:

            print(
                "MISSING FIELDS:",
                missing_fields,
                flush=True
            )

            return jsonify({
                "error": "AI response is missing required fields."
            }), 500


        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print(
            "SM1THX: Product listing generated successfully.",
            flush=True
        )

        return jsonify(result), 200


    # ========================================================
    # ERROR HANDLING
    # ========================================================

    except Exception as error:

        print(
            "SM1THX OPENAI/SERVER ERROR:",
            repr(error),
            flush=True
        )

        return jsonify({
            "error": str(error)
        }), 500


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
