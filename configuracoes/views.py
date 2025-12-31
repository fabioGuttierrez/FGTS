from django.shortcuts import render
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Configuracao


class ConfiguracaoListView(LoginRequiredMixin, ListView):
    """Listar configurações do sistema (apenas para admin)."""
    model = Configuracao
    template_name = 'configuracoes/configuracao_list.html'
    context_object_name = 'configuracoes'
    
    def dispatch(self, request, *args, **kwargs):
        """Garante que apenas admin possa acessar."""
        if not request.user.is_staff:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)
