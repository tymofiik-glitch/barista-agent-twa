import httpx
import logging


class ExpirenzaClient:
    """Клієнт для Monobank Acquiring API (інтернет-еквайринг)."""

    def __init__(self, token: str):
        self.token = token
        self.api_url = "https://api.monobank.ua/api/merchant/invoice/create"
        self.webhook_url = "http://185.166.216.234:8080/webhook/monobank"

    async def create_invoice(self, amount_cents: int, internal_order_id: str, order_description: str) -> dict | None:
        """Створює інвойс у Monobank. amount_cents — сума в КОПІЙКАХ."""
        if not self.token:
            logging.error("[Monobank] Token is empty!")
            return None

        if amount_cents <= 0:
            logging.error(f"[Monobank] Invalid amount: {amount_cents} cents")
            return None

        headers = {
            "X-Token": self.token,
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount_cents,
            "ccy": 980,  # UAH
            "merchantPaymentInfo": {
                "reference": str(internal_order_id),
                "destination": f"Замовлення: {order_description}"
            },
            "redirectUrl": "https://t.me/TakeABreakBarista_bot",
            "webhookUrl": self.webhook_url,
        }

        logging.info(f"[Monobank] Creating invoice: {amount_cents} cents, order={internal_order_id}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.api_url, headers=headers, json=payload, timeout=30.0)
                if response.status_code == 200:
                    data = response.json()
                    logging.info(f"[Monobank] Invoice created: {data.get('pageUrl', 'no URL')}")
                    return data
                else:
                    logging.error(f"[Monobank] HTTP {response.status_code}: {response.text}")
                    return None
            except Exception as e:
                logging.error(f"[Monobank] Request failed: {e}")
                return None
