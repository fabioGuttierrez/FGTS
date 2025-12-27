from django.urls import path
from .views import checkout_empresa, asaas_webhook

urlpatterns = [
    path('checkout/<int:empresa_id>/', checkout_empresa, name='billing-checkout-empresa'),
    path('webhook/', asaas_webhook, name='billing-webhook'),
]
