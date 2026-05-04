"""
Клієнт для Monobank Acquiring API.
"""
from __future__ import annotations
import asyncio
import logging
import aiohttp


class MonobankClient:
    BASE_URL = "https://api.monobank.ua"
    FINAL_FAILURE = {"failure", "reversed", "expired"}

    def __init__(self, token: str):
        if not token:
            raise ValueError("MONOBANK_TOKEN is empty")
        self.token = token
        self._headers = {
            "X-Token": token,
            "Content-Type": "application/json",
        }

    async def create_invoice(
        self,
        amount_kopecks: int,
        reference: str,
        destination: str = "Замовлення в кав'ярні Take A Break",
        basket_order: list | None = None,
        validity_seconds: int = 900,
    ) -> dict | None:
        """Створює інвойс. amount_kopecks — сума в копійках."""
        if amount_kopecks <= 0:
            return None
        paym_info = {"reference": str(reference), "destination": destination}
        if basket_order:
            paym_info["basketOrder"] = basket_order
        payload = {
            "amount": int(amount_kopecks),
            "ccy": 980,  # UAH
            "merchantPaymInfo": paym_info,
            "validity": int(validity_seconds),
            "paymentType": "debit",
        }
        url = f"{self.BASE_URL}/api/merchant/invoice/create"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self._headers, json=payload, timeout=20) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        logging.error(f"[Mono] Create invoice HTTP {resp.status}: {text[:300]}")
                        return None
                    data = await resp.json(content_type=None)

            invoice_id = data.get("invoiceId")
            page_url = data.get("pageUrl")
            if not invoice_id or not page_url:
                logging.error(f"[Mono] Missing invoiceId/pageUrl: {data}")
                return None
            return {"invoiceId": invoice_id, "pageUrl": page_url}
        except Exception as e:
            logging.error(f"[Mono] create_invoice error: {e}")
            return None

    async def get_invoice_status(self, invoice_id: str) -> dict | None:
        """Повертає статус інвойсу."""
        url = f"{self.BASE_URL}/api/merchant/invoice/status"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers, params={"invoiceId": invoice_id}, timeout=15
                ) as resp:
                    if resp.status >= 400:
                        return None
                    return await resp.json(content_type=None)
        except Exception as e:
            logging.error(f"[Mono] get_invoice_status error: {e}")
            return None

    async def cancel_invoice(self, invoice_id: str) -> bool:
        """Скасовує інвойс."""
        url = f"{self.BASE_URL}/api/merchant/invoice/cancel"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self._headers, json={"invoiceId": invoice_id}, timeout=15
                ) as resp:
                    return resp.status < 400
        except Exception as e:
            logging.error(f"[Mono] cancel_invoice error: {e}")
            return False
