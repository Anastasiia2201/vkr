import json
import requests
import re


OLLAMA_URL = "http://172.31.240.1:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"


def trim_contract_text(text: str) -> str:

    lower = text.lower()

    # --- 1. найти "права и обязанности"
    start_match = re.search(r"права\s+и\s+обязанност", lower)
    start_idx = start_match.start() if start_match else None

    # --- 2. найти "подписи сторон"
    end_match = re.search(r"подпис[ьи]\s+сторон", lower)
    end_idx = end_match.start() if end_match else None

    # --- 3. если нет "подписей" — возвращаем как есть
    if end_idx is None:
        return text

    # --- 4. отрезаем хвост после подписей
    text = text[:end_idx]

    # --- 5. если нашли "права и обязанности"
    if start_idx is not None:
        before = text[:start_idx]

        # берём кусок перед подписями (буфер)
        buffer_size = 800
        tail = text[max(len(text) - buffer_size, 0):]

        return (before + "\n\n" + tail).strip()

    return text.strip()


def build_prompt(text: str) -> list[dict]:
    trimmed = trim_contract_text(text)
    print(len(trimmed))
    print(trimmed)

    return [
        {
            "role": "system",
            "content": (
                "Ты извлекаешь данные из договоров аренды земельных участков. "
                "Верни только JSON. Ничего не выдумывай. Если нет данных — null."
            ),
        },
        {
            "role": "user",
            "content": f"""
Извлеки данные из договора и верни JSON:

{{
  "contract_number": null,
  "contract_date": null,
  "parties": {{
    "lessor_name": null,
    "lessee_name": null
  }},
  "subject": {{
    "cadastral_number": null,
    "area_hectares": null,
    "subject_text": null
  }},
  "term": {{
    "start_date": null,
    "end_date": null
  }},
  "rent_payment": {{
    "rent_amount": null,
    "payment_period": null
  }},
  "party_details": {{
    "lessor": {{
      "legal_address": null,
      "actual_address": null,
      "postal_address": null,
      "inn": null,
      "kpp": null,
      "ogrn": null,
      "bik": null,
      "checking_account": null,
      "oktmo": null,
      "kbk": null,
      "phone": null
    }},
    "lessee": {{
      "legal_address": null,
      "actual_address": null,
      "postal_address": null,
      "inn": null,
      "kpp": null,
      "ogrn": null,
      "bik": null,
      "checking_account": null,
      "oktmo": null,
      "kbk": null,
      "phone": null
    }}
  }}  
}}

Если блок реквизитов перемешан, соотнеси строки с нужной стороной по названию организации, адресу и характерным реквизитам.

Текст:
\"\"\"{trimmed[:5000]}\"\"\"
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
            "keep_alive": -1
        },
        timeout=60,
    )
    print(response)
    response.raise_for_status()
    return response.json()["message"]["content"]


def safe_parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        # Попытка вытащить JSON из текста
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
    return {"error": "invalid_json", "raw": text}


def resolve_rent_contract_with_llm(text: str) -> dict:
    messages = build_prompt(text)
    raw = call_ollama(messages)
    parsed = safe_parse_json(raw)

    return {"raw": raw, "parsed": parsed}
