print('DEBUG: Arquivo views.py carregado', flush=True)
from django.shortcuts import render, redirect
from django.db import models
from django.db.models import OuterRef, Subquery
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
from .forms import FuncionarioForm, FuncionarioVinculoForm
from .forms_transferencia import TransferenciaFuncionarioForm
from .services import FuncionarioImportService
from empresas.models import Empresa
from billing.models import BillingCustomer
from io import BytesIO
from django.core.cache import cache
from django.views.generic.detail import DetailView
from empresas.models_grupo import TransferenciaFuncionario, FuncionarioVinculo
from usuarios.models import EmpresaUsuarioRole

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
        from lancamentos.models import Lancamento
        from decimal import Decimal
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        funcionario = form.save()
        # Criar primeiro lançamento automaticamente se salário inicial foi informado
        salario_inicial = form.cleaned_data.get('salario_inicial')
        data_admissao = form.cleaned_data.get('data_admissao')
        if salario_inicial and salario_inicial > 0 and data_admissao:
            competencia = data_admissao.strftime('%m/%Y')
            existe = Lancamento.objects.filter(
                empresa=empresa,
                funcionario=funcionario,
                competencia=competencia,
                parcela_13__isnull=True
            ).exists()
            if not existe:
                valor_fgts = salario_inicial * Decimal('0.08')
                Lancamento.objects.create(
                    empresa=empresa,
                    funcionario=funcionario,
                    competencia=competencia,
                    base_fgts=salario_inicial,
                    valor_fgts=valor_fgts,
                    pago=False
                )
                messages.success(
                    self.request, 
                    f'✅ Funcionário "{funcionario.nome}" cadastrado com sucesso! '
                    f'Lançamento inicial criado para {competencia} com base FGTS de R$ {salario_inicial}.'
                )
            else:
                messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" cadastrado com sucesso!')
        else:
            messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" cadastrado com sucesso!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return super().form_invalid(form)

class FuncionarioListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_list.html'
    context_object_name = 'funcionarios'
    paginate_by = 20

    def get_queryset(self):
        qs = Funcionario.objects.all()
        user = self.request.user
        allowed = get_allowed_empresa_ids(user)

        # Escopo por empresas permitidas (inclui grupo para matriz)
        if allowed is not None:
            if not allowed:
                return qs.none()
            qs = qs.filter(vinculos__empresa_id__in=allowed)

        # Filtros de UI
        empresa_id = self.request.GET.get('empresa')
        if empresa_id:
            qs = qs.filter(vinculos__empresa_id=empresa_id)

        status = self.request.GET.get('status')
        if status == 'ativo':
            qs = qs.filter(vinculos__data_demissao__isnull=True)
        elif status == 'demitido':
            qs = qs.filter(vinculos__data_demissao__isnull=False)

        busca = self.request.GET.get('q')
        if busca:
            qs = qs.filter(
                models.Q(nome__icontains=busca) |
                models.Q(cpf__icontains=busca) |
                models.Q(pis__icontains=busca)
            )

        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()

        # Contagem baseada no vínculo mais recente (evita duplicar quem tem histórico antigo ativo)
        latest_vinculo = FuncionarioVinculo.objects.filter(
            funcionario=OuterRef('pk')
        ).order_by('-data_admissao', '-id')

        annotated = queryset.annotate(
            ultima_demissao=Subquery(latest_vinculo.values('data_demissao')[:1])
        )

        context['ativos_count'] = annotated.filter(ultima_demissao__isnull=True).count()
        context['demitidos_count'] = annotated.filter(ultima_demissao__isnull=False).count()
        context['total_count'] = annotated.count()
        context['form'] = FuncionarioForm()
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is None:
            empresas = Empresa.objects.all()
        else:
            empresas = Empresa.objects.filter(codigo__in=allowed_ids)
        context['empresas_permitidas'] = empresas
        context['filtro_empresa'] = self.request.GET.get('empresa', '')
        context['filtro_status'] = self.request.GET.get('status', '')
        context['filtro_busca'] = self.request.GET.get('q', '')
        # Permissões de recursos para botões de ação
        from empresas.models_feature import empresa_tem_recurso
        empresa = None
        user = self.request.user

        # Resolver empresa base para o usuário
        if user.is_superuser or user.is_staff:
            context['can_add_funcionario'] = True
            context['can_gerar_relatorio'] = True
            return context

        if user.empresa_id:
            try:
                empresa = Empresa.objects.get(pk=user.empresa_id)
            except (Empresa.DoesNotExist, Exception):
                empresa = None
        if not empresa:
            try:
                empresa = user.empresas_permitidas.first()
            except Exception:
                empresa = None

        # Regras de habilitação: feature flag OU billing ativo/trial
        can_add = empresa_tem_recurso(empresa, 'criar_funcionario') if empresa else False
        can_report = empresa_tem_recurso(empresa, 'gerar_relatorio') if empresa else False

        if empresa and not can_add:
            try:
                billing_customer = empresa.billing_customer
                if billing_customer.status in ['trial', 'active']:
                    can_add = True
            except Exception:
                pass

        context['can_add_funcionario'] = can_add
        context['can_gerar_relatorio'] = can_report
        # Permissão para transferir: superuser/staff ou admin (role) em ao menos uma empresa permitida
        if user.is_superuser or user.is_staff:
            context['can_transfer_funcionario'] = True
        else:
            permitted_ids = list(allowed_ids) if allowed_ids is not None else []
            context['can_transfer_funcionario'] = EmpresaUsuarioRole.objects.filter(
                usuario=user,
                role=EmpresaUsuarioRole.ADMIN,
                empresa_id__in=permitted_ids
            ).exists() if permitted_ids else False
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
        # Não podemos usar super() aqui porque EmpresaScopeMixin filtra por campos
        # de empresa inexistentes neste modelo e derruba o queryset para vazio.
        qs = Funcionario.objects.all()
        allowed = get_allowed_empresa_ids(self.request.user)
        if allowed is None:
            return qs
        if not allowed:
            return qs.none()
        # Filtra por empresas permitidas via vínculos (multi-empresa)
        return qs.filter(vinculos__empresa_id__in=allowed).distinct()

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        funcionario = form.save()
        messages.success(self.request, f'✅ Funcionário "{funcionario.nome}" atualizado com sucesso!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return super().form_invalid(form)


class FuncionarioDeleteView(LoginRequiredMixin, EmpresaScopeMixin, DeleteView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_confirm_delete.html'
    success_url = reverse_lazy('funcionario-list')

    def get_queryset(self):
        # Evita filtro vazio do EmpresaScopeMixin em modelos sem campo empresa
        qs = Funcionario.objects.all()
        allowed = get_allowed_empresa_ids(self.request.user)
        if allowed is None:
            return qs
        if not allowed:
            return qs.none()
        return qs.filter(vinculos__empresa_id__in=allowed).distinct()

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
                response_data['message'] = 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.'
                response_data['message'] += f" ⚠️ {len(result['errors'])} erro(s) encontrado(s)."
            
            return JsonResponse(response_data)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erro na importação: {str(e)}", exc_info=True)
            return JsonResponse({'success': False, 'error': f'Erro ao processar arquivo: {str(e)}'}, status=400)


class FuncionarioDetailView(LoginRequiredMixin, EmpresaScopeMixin, DetailView):
    model = Funcionario
    template_name = 'funcionarios/funcionario_detail.html'
    context_object_name = 'funcionario'

    def get_queryset(self):
        # Evita filtro vazio do EmpresaScopeMixin em modelos sem campo empresa
        qs = Funcionario.objects.all()
        allowed = get_allowed_empresa_ids(self.request.user)
        if allowed is None:
            return qs
        if not allowed:
            return qs.none()
        return qs.filter(vinculos__empresa_id__in=allowed).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['historico_vinculos'] = self.object.historico_vinculos()
        return context


class FuncionarioVinculoCreateView(LoginRequiredMixin, EmpresaScopeMixin, CreateView):
    """Cria um novo vínculo (cadeira) para um funcionário existente."""

    model = FuncionarioVinculo
    form_class = FuncionarioVinculoForm
    template_name = 'funcionarios/funcionario_vinculo_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.funcionario = Funcionario.objects.get(pk=kwargs['pk'])

        # Garantir que o usuário tem acesso ao funcionário pelo escopo de empresas permitidas.
        allowed = get_allowed_empresa_ids(request.user)
        if allowed is not None and not (request.user.is_staff or request.user.is_superuser):
            if not self.funcionario.vinculos.filter(empresa_id__in=allowed).exists():
                return HttpResponseForbidden('Você não tem permissão para criar vínculo para este funcionário.')

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['funcionario'] = self.funcionario
        return context

    def form_valid(self, form):
        vinculo = form.save(commit=False)
        vinculo.funcionario = self.funcionario

        if not is_empresa_allowed(self.request.user, vinculo.empresa.codigo):
            return HttpResponseForbidden('Você não tem permissão para criar vínculo nesta empresa.')

        vinculo.save()
        messages.success(
            self.request,
            f'✅ Vínculo criado: {self.funcionario.nome} — {vinculo.empresa.nome} (Matrícula {vinculo.matricula}).'
        )
        return redirect('funcionario-detail', pk=self.funcionario.pk)

    def form_invalid(self, form):
        messages.error(self.request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return super().form_invalid(form)

class FuncionarioTransferenciaView(LoginRequiredMixin, EmpresaScopeMixin, View):
    template_name = 'funcionarios/funcionario_transferencia.html'

    def _verificar_permissao(self, request, funcionario):
        # Superuser/staff têm acesso
        if request.user.is_superuser or request.user.is_staff:
            return True
        empresa_origem = funcionario.empresa
        if not empresa_origem:
            return False
        # Precisa estar no escopo (inclui grupo para matriz)
        if not is_empresa_allowed(request.user, empresa_origem.codigo):
            return False
        # Precisa ser admin da empresa origem
        return EmpresaUsuarioRole.objects.filter(
            usuario=request.user,
            empresa=empresa_origem,
            role=EmpresaUsuarioRole.ADMIN
        ).exists()

    def get(self, request, pk):
        funcionario = Funcionario.objects.get(pk=pk)
        if not self._verificar_permissao(request, funcionario):
            return HttpResponseForbidden('Acesso restrito ao administrador da empresa de origem.')
        form = TransferenciaFuncionarioForm(funcionario)
        return render(request, self.template_name, {'form': form, 'funcionario': funcionario})

    def post(self, request, pk):
        funcionario = Funcionario.objects.get(pk=pk)
        if not self._verificar_permissao(request, funcionario):
            return HttpResponseForbidden('Acesso restrito ao administrador da empresa de origem.')
        form = TransferenciaFuncionarioForm(funcionario, request.POST)
        if form.is_valid():
            empresa_origem = funcionario.empresa
            empresa_destino = form.cleaned_data['empresa_destino']
            data_transferencia = form.cleaned_data['data_transferencia']
            cargo = form.cleaned_data.get('cargo')
            salario = form.cleaned_data.get('salario')
            observacoes = form.cleaned_data.get('observacoes')
            # Encerrar vínculo atual
            vinculo_atual = funcionario.vinculo_atual()
            if vinculo_atual:
                vinculo_atual.data_demissao = data_transferencia
                vinculo_atual.motivo_saida = 'transferencia'
                vinculo_atual.save()
            # Criar novo vínculo
            FuncionarioVinculo.objects.create(
                funcionario=funcionario,
                empresa=empresa_destino,
                data_admissao=data_transferencia,
                data_transferencia=data_transferencia,
                cargo=cargo,
                salario=salario,
                observacoes=observacoes
            )
            # Registrar auditoria
            TransferenciaFuncionario.objects.create(
                funcionario=funcionario,
                empresa_origem=empresa_origem,
                empresa_destino=empresa_destino,
                data_transferencia=data_transferencia,
                usuario_responsavel=request.user,
                observacoes=observacoes
            )
            messages.success(request, f'Transferência realizada com sucesso!')
            return redirect('funcionario-detail', pk=funcionario.pk)
        messages.error(request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return render(request, self.template_name, {'form': form, 'funcionario': funcionario})

from datetime import datetime