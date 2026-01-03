from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.list import ListView
from django.views.generic.base import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponseForbidden, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from fgtsweb.mixins import EmpresaScopeMixin, get_allowed_empresa_ids, is_empresa_allowed, get_active_empresa_ids
from .models import Funcionario
from .forms import FuncionarioForm
from .services import FuncionarioImportService
from empresas.models import Empresa
from billing.models import BillingCustomer
from io import BytesIO

class FuncionarioCreateView(LoginRequiredMixin, EmpresaScopeMixin, CreateView):
    model = Funcionario
    form_class = FuncionarioForm
    template_name = 'funcionarios/funcionario_form.html'
    success_url = reverse_lazy('funcionario-list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            form.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is None:
            empresas = Empresa.objects.all()
        else:
            empresas = Empresa.objects.filter(codigo__in=allowed_ids)
        context['empresas_permitidas'] = empresas.values('codigo', 'nome')
        return context

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        funcionario = form.save()
        messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" cadastrado com sucesso!')
        return super().form_valid(form)

class FuncionarioListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_list.html'
    context_object_name = 'funcionarios'
    paginate_by = 20
    
    def get_queryset(self):
        qs = super().get_queryset().select_related('empresa')
        # Filtra empresas permitidas e com assinatura ativa ou em trial
        active_empresa_ids = get_active_empresa_ids()
        return self.filter_queryset_by_empresa(qs).filter(empresa__codigo__in=active_empresa_ids)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = FuncionarioForm()
        
        # Contar funcionários ativos e demitidos
        queryset = self.get_queryset()
        context['ativos_count'] = queryset.filter(data_demissao__isnull=True).count()
        context['demitidos_count'] = queryset.filter(data_demissao__isnull=False).count()
        context['total_count'] = queryset.count()
        
        return context


class FuncionarioUpdateView(LoginRequiredMixin, EmpresaScopeMixin, UpdateView):
    model = Funcionario
    form_class = FuncionarioForm
    template_name = 'funcionarios/funcionario_form.html'
    success_url = reverse_lazy('funcionario-list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            form.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is None:
            empresas = Empresa.objects.all()
        else:
            empresas = Empresa.objects.filter(codigo__in=allowed_ids)
        context['empresas_permitidas'] = empresas.values('codigo', 'nome')
        return context

    def get_queryset(self):
        qs = super().get_queryset()
        return self.filter_queryset_by_empresa(qs)

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        funcionario = form.save()
        messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" atualizado com sucesso!')
        return super().form_valid(form)


class FuncionarioDeleteView(LoginRequiredMixin, EmpresaScopeMixin, DeleteView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_confirm_delete.html'
    success_url = reverse_lazy('funcionario-list')

    def get_queryset(self):
        qs = super().get_queryset()
        return self.filter_queryset_by_empresa(qs)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        nome = self.object.nome
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'✅ Funcionário "{nome}" excluído com sucesso!')
        return response

class FuncionarioDownloadTemplateView(LoginRequiredMixin, View):
    """Download do modelo XLSX para importação de funcionários"""
    
    def get(self, request):
        try:
            wb = FuncionarioImportService.generate_template_xlsx()
            
            # Salvar em BytesIO
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            
            # Preparar resposta
            response = HttpResponse(
                output.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="modelo_funcionarios_{datetime.now().strftime("%d_%m_%Y")}.xlsx"'
            
            return response
        except Exception as e:
            messages.error(request, f'❌ Erro ao gerar modelo: {str(e)}')
            return redirect('funcionario-list')


class FuncionarioUploadImportView(LoginRequiredMixin, EmpresaScopeMixin, View):
    """Upload e processamento de importação em lote"""
    
    def post(self, request):
        try:
            # Validar arquivo
            if 'import_file' not in request.FILES:
                return JsonResponse({'success': False, 'error': 'Nenhum arquivo foi enviado'}, status=400)
            
            file = request.FILES['import_file']
            
            # Validar extensão
            if not file.name.endswith('.xlsx'):
                return JsonResponse({'success': False, 'error': 'Por favor, envie um arquivo XLSX'}, status=400)
            
            # Obter empresa se fornecida
            empresa_id = request.POST.get('empresa_id')
            
            # Processar importação com validações de permissão e billing
            result = FuncionarioImportService.import_funcionarios_from_file(
                file=file,
                empresa_id=empresa_id,
                user=request.user
            )
            
            # Preparar resposta com IDs dos funcionários criados
            response_data = {
                'success': result['success'] > 0,
                'total': result['total'],
                'success_count': result['success'],
                'error_count': len(result['errors']),
                'errors': result['errors'],  # Todos os erros
                'created_ids': result['created_funcionarios'],
                'message': f"✅ {result['success']} funcionário(s) importado(s) com sucesso!"
            }
            
            if result['errors']:
                response_data['message'] += f" ⚠️ {len(result['errors'])} erro(s) encontrado(s)."
            
            return JsonResponse(response_data)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erro na importação: {str(e)}", exc_info=True)
            return JsonResponse({'success': False, 'error': f'Erro ao processar arquivo: {str(e)}'}, status=400)


from datetime import datetime