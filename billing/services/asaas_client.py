import os
import requests

DEFAULT_TIMEOUT = 10


class AsaasClient:
    def __init__(self):
        self.api_key = os.getenv('ASAAS_API_KEY') or os.getenv('ASAAS_API_KEY_SANDBOX')
        self.env = os.getenv('ASAAS_ENV', 'sandbox')
        self.base_url = 'https://sandbox.asaas.com/api/v3' if self.env == 'sandbox' else 'https://api.asaas.com/v3'
        if not self.api_key:
            raise ValueError('Configure ASAAS_API_KEY or ASAAS_API_KEY_SANDBOX para usar o checkout Asaas.')

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'access_token': self.api_key,
        }

    def create_customer(self, payload: dict) -> dict:
        url = f"{self.base_url}/customers"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def create_subscription(self, payload: dict) -> dict:
        url = f"{self.base_url}/subscriptions"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def create_payment(self, payload: dict) -> dict:
        url = f"{self.base_url}/payments"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
