import json
import requests


OLLAMA_URL = "http://172.31.240.1:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"


def build_prompt(text: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Ты извлекаешь данные из протоколов аукционов и торгов по земельным участкам. "
                "Верни только JSON по заданной схеме. "
                "Ничего не выдумывай. Если значение отсутствует или неясно, верни null."
            ),
        },
        {
            "role": "user",
            "content": f"""
Извлеки данные из протокола торгов/аукциона и верни JSON строго по схеме:

{{
  "document_kind": "auction_protocol",
  "protocol_number": null,
  "protocol_date": null,
  "procedure_number": null,
  "auction_form": null,
  "organizer_name": null,
  "seller_name": null,
  "winner_name": null,
  "winner_inn": null,
  "participants": [],
  "subject": {{
    "cadastral_number": null,
    "area_hectares": null,
    "location": null,
    "lot_number": null,
    "subject_text": null
  }},
  "result": {{
    "status": null,
    "final_price": null,
    "starting_price": null,
    "annual_rent": null
  }}
}}

Правила:
1. protocol_date верни в формате YYYY-MM-DD, если дата определяется однозначно.
2. protocol_number — номер самого протокола.
3. procedure_number — номер процедуры/извещения/торгов, если он есть.
4. winner_name — победитель торгов, если указан.
5. participants — список участников, если они явно перечислены.
6. area_hectares верни числом в гектарах.
7. Ничего не выдумывай.

Текст:
\"\"\"{text[:5000]}\"\"\"
""",
        },
    ]


def call_ollama(messages: list[dict]) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {
                "temperature": 0,
                "num_predict": 500,
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def safe_parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
    return {"error": "invalid_json", "raw": text}


def resolve_auction_protocol_with_llm(text: str) -> dict:
    messages = build_prompt(text)
    raw = call_ollama(messages)
    parsed = safe_parse_json(raw)

    return {"raw": raw, "parsed": parsed}
