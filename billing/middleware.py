"""Middleware para verificação e exibição de avisos de trial"""

from datetime import date
import logging
from django.shortcuts import redirect
from django.contrib import messages
from billing.models import BillingCustomer


logger = logging.getLogger(__name__)


class TrialWarningMiddleware:
    """
    Middleware que:
    1. Verifica se trial expirou
    2. Bloqueia acesso com mensagem amigável
    3. Adiciona contexto de trial às requisições
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Não interferir no Django Admin / assets
        if request.path.startswith('/admin/') or request.path.startswith('/static/') or request.path.startswith('/media/'):
            return self.get_response(request)

        # Aplicar apenas para usuários autenticados
        if request.user.is_authenticated:
            try:
                # Encontrar billing customer pela empresa do usuário
                empresa_id = getattr(request.user, 'empresa_id', None)
                if empresa_id:
                    billing_customer = BillingCustomer.objects.filter(empresa_id=empresa_id).first()
                    
                    if billing_customer:
                        # Adicionar ao request para usar em templates
                        request.trial_customer = billing_customer
                        
                        # Verificar se trial expirou
                        if billing_customer.trial_active and billing_customer.trial_expires:
                            if date.today() > billing_customer.trial_expires:
                                # Trial expirou
                                billing_customer.trial_active = False
                                billing_customer.status = 'pending'
                                billing_customer.save()
                                
                                # Se não está em página de checkout, redirecionar
                                if 'checkout' not in request.path and 'billing' not in request.path:
                                    messages.error(
                                        request,
                                        '❌ Seu trial de 7 dias expirou! Assine um plano para continuar.'
                                    )
                                    return redirect('billing:checkout-plano')
            
            except Exception:
                # Se algo der errado, deixa continuar normalmente, mas registra para diagnóstico
                logger.exception('Erro no TrialWarningMiddleware')
        
        response = self.get_response(request)
        return response
