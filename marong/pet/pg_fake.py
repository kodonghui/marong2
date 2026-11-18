"""In-process payment gateway for isolated tests. It makes no network calls."""

import hmac

from .billing import Payment


class FakeGateway:
    client_key = "test_fixture_gateway"

    def __init__(self, secret):
        self.secret = secret
        self.payments = {}
        self.calls = []

    def add(self, payment_key, order_no, amount, *, paid=True):
        self.payments[payment_key] = Payment(order_no, "fixture-" + payment_key, amount, paid)

    async def approve(self, order_no, payment_key, amount):
        self.calls.append((order_no, payment_key, amount))
        return self.payments.get(payment_key)

    def sign(self, raw):
        return hmac.digest(self.secret, raw, "sha256").hex()

    def valid_signature(self, raw, signature):
        return signature.isascii() and hmac.compare_digest(self.sign(raw), signature)
