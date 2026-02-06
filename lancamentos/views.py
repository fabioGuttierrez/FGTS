import time
from datetime import datetime, date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import FormView, CreateView, UpdateView, ListView, View, DetailView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from billing.services.features import can_use_feature, feature_block_context
from empresas.models import Empresa
from .models import Lancamento
from .models_conferencia import ConferenciaLancamento
from .forms import (
    RelatorioCompetenciaForm, 
    LancamentoForm, 
    LegacyImportForm,
    ConferenciaLancamentoForm,
    RejeicaoLancamentoForm,
    FiltroConferenciaForm
)
from .services.calculo import (
    calcular_fgts_atualizado,
    gerar_memoria_calculo,
    get_config_numeric,
    get_config_str,
    aplicar_plano_economico_legacy,
    calcular_jam_ate_pagamento,
    buscar_coef_jam,
)
from .services.importacao import LancamentoImportService
from .services.competencia_13 import Competencia13Service
from django.conf import settings
from indices.services.indice_service import IndiceFGTSService
from funcionarios.models import Funcionario
from fgtsweb.mixins import get_allowed_empresa_ids, is_empresa_allowed, EmpresaScopeMixin
from django.http import HttpResponseForbidden, HttpResponse
from django.db.models.functions import Substr
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required


class LancamentoDeleteView(LoginRequiredMixin, EmpresaScopeMixin, View):
    """Exclui um lançamento específico via POST."""

    def post(self, request, pk):
        try:
            lancamento = get_object_or_404(Lancamento, pk=pk)

            # Permissão por empresa
            if not is_empresa_allowed(request.user, lancamento.empresa.codigo):
                messages.error(request, '❌ Você não tem permissão para excluir este lançamento.')
                return redirect('lancamento-list')

            lancamento.delete()
            messages.success(request, '🗑️ Lançamento excluído com sucesso.')
        except Exception as e:
            messages.error(request, f'❌ Erro ao excluir lançamento: {str(e)}')

        return redirect('lancamento-list')


class LancamentoCreateView(LoginRequiredMixin, EmpresaScopeMixin, CreateView):
    """Criar novo lançamento mensal (base FGTS)"""
    model = Lancamento
    form_class = LancamentoForm
    template_name = 'lancamentos/lancamento_form.html'
    success_url = reverse_lazy('lancamento-list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        
        lancamento = form.save()  # Já calcula valor_fgts no save() do formulário
        vinculo_label = f" (matrícula {lancamento.vinculo.matricula})" if getattr(lancamento, 'vinculo', None) and lancamento.vinculo.matricula else ""
        messages.success(self.request, f'✅ Lançamento para {lancamento.funcionario.nome}{vinculo_label} ({lancamento.competencia}) registrado com sucesso!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return super().form_invalid(form)


class LancamentoUpdateView(LoginRequiredMixin, EmpresaScopeMixin, UpdateView):
    """Editar lançamento mensal"""
    model = Lancamento
    form_class = LancamentoForm
    template_name = 'lancamentos/lancamento_form.html'
    success_url = reverse_lazy('lancamento-list')
    pk_url_kwarg = 'pk'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        empresa = form.cleaned_data.get('empresa')
        if empresa and not is_empresa_allowed(self.request.user, empresa.codigo):
            return HttpResponseForbidden('Empresa não permitida para este usuário.')
        
        lancamento = form.save()
        vinculo_label = f" (matrícula {lancamento.vinculo.matricula})" if getattr(lancamento, 'vinculo', None) and lancamento.vinculo.matricula else ""
        messages.success(self.request, f'✅ Lançamento para {lancamento.funcionario.nome}{vinculo_label} ({lancamento.competencia}) atualizado com sucesso!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return super().form_invalid(form)


class LancamentoListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    """Listar lançamentos cadastrados"""
    model = Lancamento
    template_name = 'lancamentos/lancamento_list.html'
    context_object_name = 'lancamentos'
    paginate_by = 20


    def get_queryset(self):
        from empresas.models_grupo import FuncionarioVinculo
        from django.db import models
        from django.db.models import OuterRef, Exists, Q, DateField, Value, F, Func, Case, When
        from django.db.models.functions import Substr, Cast, TruncMonth
        import datetime

        qs = super().get_queryset().select_related('empresa', 'funcionario', 'vinculo')
        qs = qs.annotate(
            ano_comp=Case(
                When(
                    competencia__regex=r'^\d{2}/\d{4}$',
                    then=Substr('competencia', 4, 4)
                ),
                When(
                    competencia__regex=r'^\d{4}-\d{2}$',
                    then=Substr('competencia', 1, 4)
                ),
                default=Substr('competencia', 1, 4),
                output_field=models.CharField()
            )
        )

        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            qs = qs.filter(empresa__codigo__in=allowed_ids)

        competencia = self.request.GET.get('competencia', '').strip()
        funcionario_id = self.request.GET.get('funcionario', '').strip()
        empresa_id = self.request.GET.get('empresa', '').strip()
        matricula = self.request.GET.get('matricula', '').strip()
        vinculo_id = self.request.GET.get('vinculo', '').strip()
        ano = self.request.GET.get('ano', '').strip()
        status_pagto = self.request.GET.get('status_pagto', '').strip()

        # Usar sempre MM/YYYY (string) para busca
        if competencia:
            qs = qs.filter(competencia=competencia)

        if funcionario_id:
            qs = qs.filter(funcionario_id=funcionario_id)

        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)

        if vinculo_id:
            qs = qs.filter(vinculo_id=vinculo_id)

        if matricula:
            qs = qs.filter(vinculo__matricula__icontains=matricula)

        if status_pagto in ['pago', 'nao_pago']:
            qs = qs.filter(pago=(status_pagto == 'pago'))

        if ano:
            qs = qs.filter(ano_comp=ano)

        # Refatoração: filtro de vínculo ativo via Exists (SQL)
        # Considera vínculo ativo se:
        # - empresa igual
        # - funcionario igual
        # - data_admissao <= competência
        # - (data_demissao é nula ou >= competência)

        # Converter competencia (str) para data (primeiro dia do mês)

        # Anotar a data da competência (primeiro dia do mês) para cada lançamento

        from django.db.models.functions import Concat, Substr
        from django.db.models import Case, When
        # Se competencia tem '/' (MM/YYYY), converte para YYYY-MM-01, senão assume YYYY-MM-01
        qs = qs.annotate(
            competencia_date=Cast(
                Case(
                    When(
                        competencia__regex=r'^\d{2}/\d{4}$',
                        then=Concat(
                            Substr('competencia', 4, 4),  # YYYY
                            Value('-'),
                            Substr('competencia', 1, 2),  # MM
                            Value('-01')
                        )
                    ),
                    default=Concat(F('competencia'), Value('-01')),
                    output_field=models.CharField()
                ),
                output_field=DateField()
            )
        )

        vinculo_exists = Exists(
            FuncionarioVinculo.objects.annotate(
                adm_mes=TruncMonth('data_admissao'),
                dem_mes=TruncMonth('data_demissao'),
            ).filter(
                funcionario_id=OuterRef('funcionario_id'),
                empresa_id=OuterRef('empresa_id'),
                adm_mes__lte=OuterRef('competencia_date'),
            ).filter(
                Q(dem_mes__isnull=True) | Q(dem_mes__gte=OuterRef('competencia_date'))
            )
        )

        qs = qs.annotate(vinculo_legado_ativo=vinculo_exists)

        qs = qs.annotate(
            vinculo_adm_mes=TruncMonth('vinculo__data_admissao'),
            vinculo_dem_mes=TruncMonth('vinculo__data_demissao'),
        )

        vinculo_ativo_explicito = Case(
            When(
                condition=(
                    Q(vinculo__isnull=False)
                    & Q(vinculo_adm_mes__lte=F('competencia_date'))
                    & (Q(vinculo_dem_mes__isnull=True) | Q(vinculo_dem_mes__gte=F('competencia_date')))
                ),
                then=Value(True),
            ),
            When(
                condition=Q(vinculo__isnull=True) & Q(vinculo_legado_ativo=True),
                then=Value(True),
            ),
            default=Value(False),
            output_field=models.BooleanField(),
        )
        qs = qs.annotate(vinculo_ativo=vinculo_ativo_explicito).filter(vinculo_ativo=True)

        # Ordenação
        ordem = self.request.GET.get('ordem', '-competencia').strip()
        if ordem == 'competencia_asc':
            qs = qs.order_by('competencia')
        elif ordem == 'competencia_desc':
            qs = qs.order_by('-competencia')
        elif ordem == 'ano_asc':
            qs = qs.order_by('ano_comp', 'competencia')
        elif ordem == 'ano_desc':
            qs = qs.order_by('-ano_comp', '-competencia')
        elif ordem == 'funcionario_asc':
            qs = qs.order_by('funcionario__nome')
        elif ordem == 'funcionario_desc':
            qs = qs.order_by('-funcionario__nome')
        else:
            qs = qs.order_by('-competencia')

        return qs
    
    def get_context_data(self, **kwargs):
        # Local import to guarantee binding even if globals change or circular imports occur
        from funcionarios.models import Funcionario as FuncionarioModel

        context = super().get_context_data(**kwargs)

        # Adicionar empresas e funcionários permitidos para o filtro
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            context['empresas'] = Empresa.objects.filter(codigo__in=allowed_ids)
            funcionario_ids = FuncionarioModel.objects.filter(
                vinculos__empresa__codigo__in=allowed_ids
            ).distinct().values_list('id', flat=True)
            context['funcionarios'] = FuncionarioModel.objects.filter(id__in=funcionario_ids).order_by('nome')
            base_qs = Lancamento.objects.filter(empresa__codigo__in=allowed_ids)
        else:
            context['empresas'] = Empresa.objects.all()
            context['funcionarios'] = FuncionarioModel.objects.all().order_by('nome')
            base_qs = Lancamento.objects.all()

        # Aplicar os mesmos filtros do get_queryset
        competencia = self.request.GET.get('competencia', '').strip()
        funcionario_id = self.request.GET.get('funcionario', '').strip()
        empresa_id = self.request.GET.get('empresa', '').strip()
        status_pagto = self.request.GET.get('status_pagto', '').strip()
        # Não aplicar filtro de competência para o filtro de ano, para garantir que todos os anos presentes sejam exibidos

        def extract_ano(comp):
            if not comp:
                return None
            if '/' in comp:
                candidate = comp.split('/')[-1]
            elif '-' in comp:
                parts = comp.split('-')
                candidate = parts[0] if len(parts[0]) == 4 else parts[-1]
            else:
                candidate = comp[:4]
            return candidate if len(candidate) == 4 and candidate.isdigit() else None

        competencias_para_anos = base_qs.values_list('competencia', flat=True).distinct()
        anos_todos = set()
        for comp in competencias_para_anos:
            ano_extraido = extract_ano(comp)
            if ano_extraido:
                anos_todos.add(ano_extraido)
        context['anos_todos'] = sorted(anos_todos, reverse=True)

        # Agora sim, aplicar o filtro de competência para a listagem
        if competencia:
            comp_parts = competencia.split('/')
            competencia_db = f"{comp_parts[1]}-{comp_parts[0]}" if len(comp_parts) == 2 else competencia
            base_qs = base_qs.filter(competencia=competencia_db)
        if funcionario_id:
            base_qs = base_qs.filter(funcionario_id=funcionario_id)
        if empresa_id:
            base_qs = base_qs.filter(empresa_id=empresa_id)
        if status_pagto in ['pago', 'nao_pago']:
            base_qs = base_qs.filter(pago=(status_pagto == 'pago'))

        competencias = base_qs.values_list('competencia', flat=True).distinct()
        anos_validos = set()
        for comp in competencias:
            ano_extraido = extract_ano(comp)
            if ano_extraido:
                anos_validos.add(ano_extraido)
        context['anos'] = sorted(anos_validos, reverse=True)

        # Passar parâmetros de filtro para o template
        context['competencia_filtro'] = self.request.GET.get('competencia', '')
        context['funcionario_filtro'] = self.request.GET.get('funcionario', '')
        context['empresa_filtro'] = self.request.GET.get('empresa', '')
        context['matricula_filtro'] = self.request.GET.get('matricula', '')
        context['vinculo_filtro'] = self.request.GET.get('vinculo', '')
        context['ano_filtro'] = self.request.GET.get('ano', '')
        context['status_pagto_filtro'] = self.request.GET.get('status_pagto', '')
        context['ordem_filtro'] = self.request.GET.get('ordem', '-competencia')

        # Empresa de referência para validar plano/trial (filtro, usuário ou única empresa permitida)
        empresa_contexto = None
        empresa_param = context['empresa_filtro']
        if empresa_param:
            try:
                empresa_contexto = Empresa.objects.filter(pk=empresa_param).first()
            except Exception:
                empresa_contexto = None
        if not empresa_contexto:
            try:
                empresa_contexto = self.request.user.empresa
            except Exception:
                empresa_contexto = None
        if not empresa_contexto and allowed_ids and len(allowed_ids) == 1:
            empresa_contexto = Empresa.objects.filter(codigo=allowed_ids[0]).first()

        bloqueio_ctx = feature_block_context('custom_reports', user=self.request.user, empresa=empresa_contexto)
        context['relatorio_bloqueado'] = bloqueio_ctx['feature_blocked']
        context['relatorio_bloqueio_motivo'] = bloqueio_ctx['feature_block_reason']
        context['empresa_contexto'] = empresa_contexto

        # Construir um dicionário com a última competência de cada vínculo (ou funcionário, para legados)
        ultimas_competencias = {}
        lancamentos_list = context.get('lancamentos', [])

        for lancamento in lancamentos_list:
            key = ('v', lancamento.vinculo_id) if getattr(lancamento, 'vinculo_id', None) else ('f', lancamento.funcionario_id)
            if key not in ultimas_competencias:
                filtro = {'funcionario_id': lancamento.funcionario_id}
                if getattr(lancamento, 'vinculo_id', None):
                    filtro = {'vinculo_id': lancamento.vinculo_id}

                ultimo = Lancamento.objects.filter(**filtro).order_by('-competencia').first()
                if ultimo:
                    ultimas_competencias[key] = ultimo.competencia

        # Adicionar flag is_ultima_competencia a cada lançamento
        for lancamento in lancamentos_list:
            key = ('v', lancamento.vinculo_id) if getattr(lancamento, 'vinculo_id', None) else ('f', lancamento.funcionario_id)
            lancamento.is_ultima_competencia = (
                key in ultimas_competencias and 
                lancamento.competencia == ultimas_competencias[key]
            )

        # Buscar a data da última atualização da tabela indices_fgts (SupabaseIndice)
        try:
            from indices.models import SupabaseIndice
            ultima_atualizacao = SupabaseIndice.objects.order_by('-data_base').values_list('data_base', flat=True).first()
        except Exception:
            ultima_atualizacao = None
        context['ultima_atualizacao_indices_fgts'] = ultima_atualizacao

        return context


@login_required
def lancamento_ids(request):
    """Retorna todos os IDs de lançamentos aplicando os mesmos filtros da listagem."""
    view = LancamentoListView()
    view.request = request
    qs = view.get_queryset()
    ids = list(qs.values_list('id', flat=True))
    return JsonResponse({'ids': ids})


class GerarLancamentosAutomaticosView(LoginRequiredMixin, EmpresaScopeMixin, View):
    """
    Gera lançamentos automáticos para um funcionário específico.
    Pega o último lançamento e gera todos os meses subsequentes até hoje.
    Para na data de demissão se houver.
    """
    
    def post(self, request, funcionario_id):
        try:
            funcionario = Funcionario.objects.get(id=funcionario_id)
            
            # Verificar se o funcionário pertence a uma empresa permitida
            if not is_empresa_allowed(request.user, funcionario.empresa.codigo):
                messages.error(request, '❌ Você não tem permissão para gerar lançamentos para este funcionário.')
                return redirect('lancamento-list')
            
            # Verificar se o funcionário está ativo
            if funcionario.data_demissao:
                messages.warning(request, f'⚠️ {funcionario.nome} está demitido. Não é possível gerar lançamentos automáticos.')
                return redirect('lancamento-list')
            
            # Buscar o último lançamento do funcionário
            ultimo_lancamento = Lancamento.objects.filter(
                funcionario=funcionario
            ).order_by('-competencia').first()
            
            if not ultimo_lancamento:
                messages.error(request, f'❌ {funcionario.nome} não possui nenhum lançamento. Crie o primeiro lançamento manualmente.')
                return redirect('lancamento-list')
            
            # Converter competência do último lançamento para data
            mes, ano = map(int, ultimo_lancamento.competencia.split('/'))
            data_ultimo = datetime(ano, mes, 1)
            
            # Data final: hoje
            data_hoje = datetime.now()
            
            # Data limite: hoje ou data de demissão (o que vier primeiro)
            if funcionario.data_demissao:
                data_limite = datetime.combine(funcionario.data_demissao, datetime.min.time())
                if data_limite < data_hoje:
                    data_hoje = data_limite
            
            # Gerar lançamentos mês a mês
            lancamentos_criados = 0
            lancamentos_13_criados = 0
            data_atual = data_ultimo + relativedelta(months=1)
            base_fgts_anterior = ultimo_lancamento.base_fgts
            
            while data_atual <= data_hoje:
                competencia = data_atual.strftime('%m/%Y')
                
                # Verificar se já existe lançamento para esta competência
                if not Lancamento.objects.filter(funcionario=funcionario, competencia=competencia).exists():
                    # Criar novo lançamento herdando a base FGTS do anterior
                    Lancamento.objects.create(
                        empresa=funcionario.empresa,
                        funcionario=funcionario,
                        competencia=competencia,
                        base_fgts=base_fgts_anterior,
                        valor_fgts=base_fgts_anterior * Decimal('0.08'),  # 8% do FGTS
                        pago=False
                    )
                    lancamentos_criados += 1
                
                data_atual += relativedelta(months=1)

            # Gerar automaticamente as duas parcelas do 13º para os anos entre o último lançamento e o ano atual
            ano_inicio = data_ultimo.year
            ano_fim = data_hoje.year

            for ano_ref in range(ano_inicio, ano_fim + 1):
                competencias_13 = Competencia13Service.gerar_competencias_13(funcionario.empresa, ano_ref, funcionario)
                for comp_str, parcela in competencias_13:
                    if not Lancamento.objects.filter(funcionario=funcionario, competencia=comp_str, parcela_13=parcela).exists():
                        base_13_total = base_fgts_anterior
                        primeira_parcela_valor = base_13_total * Decimal('0.5')
                        base_13 = primeira_parcela_valor if parcela == 1 else (base_13_total - primeira_parcela_valor)
                        Lancamento.objects.create(
                            empresa=funcionario.empresa,
                            funcionario=funcionario,
                            competencia=comp_str,
                            parcela_13=parcela,
                            base_fgts=base_13,
                            valor_fgts=base_13 * Decimal('0.08'),
                            pago=False,
                        )
                        lancamentos_13_criados += 1
            
            if lancamentos_criados > 0:
                messages.success(
                    request, 
                    f'✅ {lancamentos_criados} lançamento(s) mensal(is) gerado(s) automaticamente para {funcionario.nome}!'
                )
            else:
                messages.info(
                    request,
                    f'ℹ️ Todos os lançamentos de {funcionario.nome} já estão cadastrados até hoje.'
                )

            if lancamentos_13_criados > 0:
                messages.success(
                    request,
                    f'✅ {lancamentos_13_criados} lançamento(s) de 13º gerado(s) automaticamente para {funcionario.nome}!'
                )
            
        except Funcionario.DoesNotExist:
            messages.error(request, '❌ Funcionário não encontrado.')
        except Exception as e:
            messages.error(request, f'❌ Erro ao gerar lançamentos: {str(e)}')
        
        return redirect('lancamento-list')


class GerarLancamentosAutomaticosVinculoView(LoginRequiredMixin, EmpresaScopeMixin, View):
    """Gera lançamentos automáticos para um vínculo específico (cadeira)."""

    def post(self, request, vinculo_id):
        from empresas.models_grupo import FuncionarioVinculo

        try:
            vinculo = FuncionarioVinculo.objects.select_related('empresa', 'funcionario').get(id=vinculo_id)
            empresa = vinculo.empresa
            funcionario = vinculo.funcionario

            if not is_empresa_allowed(request.user, empresa.codigo):
                messages.error(request, '❌ Você não tem permissão para gerar lançamentos para este vínculo.')
                return redirect('lancamento-list')

            # Se vínculo tem demissão, respeitar limite
            data_limite = datetime.now()
            if vinculo.data_demissao:
                data_limite = datetime.combine(vinculo.data_demissao, datetime.min.time())

            ultimo_lancamento = Lancamento.objects.filter(vinculo=vinculo).order_by('-competencia').first()
            if not ultimo_lancamento:
                messages.error(request, '❌ Este vínculo não possui nenhum lançamento. Crie o primeiro lançamento manualmente.')
                return redirect('lancamento-list')

            mes, ano = map(int, ultimo_lancamento.competencia.split('/'))
            data_ultimo = datetime(ano, mes, 1)

            lancamentos_criados = 0
            lancamentos_13_criados = 0
            data_atual = data_ultimo + relativedelta(months=1)
            base_fgts_anterior = ultimo_lancamento.base_fgts

            while data_atual <= data_limite:
                competencia = data_atual.strftime('%m/%Y')

                if not Lancamento.objects.filter(vinculo=vinculo, competencia=competencia, parcela_13__isnull=True).exists():
                    Lancamento.objects.create(
                        empresa=empresa,
                        funcionario=funcionario,
                        vinculo=vinculo,
                        competencia=competencia,
                        base_fgts=base_fgts_anterior,
                        valor_fgts=base_fgts_anterior * Decimal('0.08'),
                        pago=False,
                    )
                    lancamentos_criados += 1

                data_atual += relativedelta(months=1)

            ano_inicio = data_ultimo.year
            ano_fim = min(datetime.now().year, data_limite.year)

            for ano_ref in range(ano_inicio, ano_fim + 1):
                competencias_13 = Competencia13Service.gerar_competencias_13(empresa, ano_ref, funcionario)
                for comp_str, parcela in competencias_13:
                    if not Lancamento.objects.filter(vinculo=vinculo, competencia=comp_str, parcela_13=parcela).exists():
                        base_13_total = base_fgts_anterior
                        primeira_parcela_valor = base_13_total * Decimal('0.5')
                        base_13 = primeira_parcela_valor if parcela == 1 else (base_13_total - primeira_parcela_valor)
                        Lancamento.objects.create(
                            empresa=empresa,
                            funcionario=funcionario,
                            vinculo=vinculo,
                            competencia=comp_str,
                            parcela_13=parcela,
                            base_fgts=base_13,
                            valor_fgts=base_13 * Decimal('0.08'),
                            pago=False,
                        )
                        lancamentos_13_criados += 1

            if lancamentos_criados:
                messages.success(request, f'✅ {lancamentos_criados} lançamento(s) mensal(is) gerado(s) para {funcionario.nome} (matrícula {vinculo.matricula or vinculo.pk})!')
            else:
                messages.info(request, f'ℹ️ Todos os lançamentos deste vínculo já estão cadastrados até hoje.')

            if lancamentos_13_criados:
                messages.success(request, f'✅ {lancamentos_13_criados} lançamento(s) de 13º gerado(s) para este vínculo!')

        except FuncionarioVinculo.DoesNotExist:
            messages.error(request, '❌ Vínculo não encontrado.')
        except Exception as e:
            messages.error(request, f'❌ Erro ao gerar lançamentos: {str(e)}')

        return redirect('lancamento-list')


class RelatorioCompetenciaView(FormView):
    def normalizar_competencia(self, comp):
        """Aceita 'MM/YYYY', 'YYYY-MM' ou 'YYYY/MM' e retorna sempre 'MM/YYYY'."""
        if isinstance(comp, str):
            if '/' in comp:
                parts = comp.split('/')
                if len(parts) == 2 and len(parts[1]) == 4:
                    # MM/YYYY
                    return f'{parts[0].zfill(2)}/{parts[1]}'
                if len(parts) == 2 and len(parts[0]) == 4:
                    # YYYY/MM
                    return f'{parts[1].zfill(2)}/{parts[0]}'
            if '-' in comp:
                parts = comp.split('-')
                if len(parts) == 2 and len(parts[0]) == 4:
                    # YYYY-MM
                    return f'{parts[1].zfill(2)}/{parts[0]}'
        return comp
    template_name = 'lancamentos/relatorio_competencia.html'
    form_class = RelatorioCompetenciaForm
    success_url = reverse_lazy('relatorio-competencia')
    # Configurações de proteção contra loops
    MAX_ITERACOES_POR_COMPETENCIA = 10  # Máximo de vezes que a mesma competência pode ser reprocessada
    TIMEOUT_GLOBAL_SEGUNDOS = 60  # Timeout total de 60 segundos
    MAX_COMPETENCIAS = 12  # Limite para evitar timeouts em requisições grandes
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tempo_inicio = None
        self.competencias_processadas = {}  # Track {competencia: count}
    
    def _verificar_loop(self, competencia_str):
        """Verifica se há risco de loop infinito"""
        import time
        
        # Verificar timeout global
        if self.tempo_inicio is None:
            self.tempo_inicio = time.time()
        
        tempo_decorrido = time.time() - self.tempo_inicio
        if tempo_decorrido > self.TIMEOUT_GLOBAL_SEGUNDOS:
            raise Exception(
                f"🛑 TIMEOUT: Processamento levou mais de {self.TIMEOUT_GLOBAL_SEGUNDOS}s. "
                f"Interrompendo para evitar loop infinito."
            )
        
        # Verificar iterações por competência
        if competencia_str not in self.competencias_processadas:
            self.competencias_processadas[competencia_str] = 0
        
        self.competencias_processadas[competencia_str] += 1
        contador = self.competencias_processadas[competencia_str]
        
        if contador > self.MAX_ITERACOES_POR_COMPETENCIA:
            raise Exception(
                f"🛑 LOOP DETECTADO: Competência {competencia_str} foi processada {contador} vezes. "
                f"Limite máximo de {self.MAX_ITERACOES_POR_COMPETENCIA} iterações excedido. "
                f"Há um loop infinito no processamento."
            )
        
        # Aviso quando aproximando do limite
        if contador > self.MAX_ITERACOES_POR_COMPETENCIA * 0.7:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"⚠️ AVISO DE LOOP: Competência {competencia_str} já foi processada {contador} vezes "
                f"({int((contador/self.MAX_ITERACOES_POR_COMPETENCIA)*100)}% do limite)."
            )
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        empresa_ctx = None
        form = ctx.get('form')
        if form:
            empresa_value = None
            try:
                empresa_value = form.data.get('empresa') or form.initial.get('empresa')
            except Exception:
                empresa_value = None

            if empresa_value:
                if isinstance(empresa_value, Empresa):
                    empresa_ctx = empresa_value
                else:
                    try:
                        empresa_ctx = Empresa.objects.filter(pk=empresa_value).first()
                    except Exception:
                        empresa_ctx = None

        if not empresa_ctx:
            try:
                empresa_ctx = self.request.user.empresa
            except Exception:
                empresa_ctx = None

        bloqueio_ctx = feature_block_context('custom_reports', user=self.request.user, empresa=empresa_ctx)
        ctx['relatorio_bloqueado'] = bloqueio_ctx['feature_blocked']
        ctx['relatorio_bloqueio_motivo'] = bloqueio_ctx['feature_block_reason']
        ctx['empresa_contexto'] = empresa_ctx
        return ctx

    def form_invalid(self, form):
        messages.error(self.request, 'Foram encontradas inconsistencias nas informacoes enviadas. Revise as informacoes.')
        return super().form_invalid(form)

    def _agrupar_resultados(self, resultados, agrupamento):
        """Agrupa resultados por competência, ano, funcionário ou vínculo"""
        from collections import defaultdict
        
        grupos = defaultdict(lambda: {
            'items': [],
            'totais': {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
        })
        
        for resultado in resultados:
            lancamento = resultado['lancamento']
            calc = resultado['calc']
            competencia_raw = resultado.get('competencia')
            competencia_label = resultado.get('competencia_display', competencia_raw)
            parcela_13 = resultado.get('parcela_13') or 0
			
            # Determinar chave do grupo
            if agrupamento == 'ano':
                # Extrair ano da competência (MM/YYYY)
                ano = competencia_raw.split('/')[-1] if competencia_raw and '/' in competencia_raw else competencia_raw
                chave = ano
                label = f"Ano {ano}"
            elif agrupamento == 'funcionario':
                chave = lancamento.funcionario.pk
                label = f"{lancamento.funcionario.nome} - {lancamento.funcionario.cpf}"
            elif agrupamento == 'vinculo':
                if getattr(lancamento, 'vinculo_id', None):
                    chave = f"vinc_{lancamento.vinculo_id}"
                    matricula = (getattr(lancamento.vinculo, 'matricula', None) or '').strip()
                    matricula_label = matricula if matricula else str(lancamento.vinculo_id)
                    label = f"{lancamento.funcionario.nome} — matrícula {matricula_label}"
                else:
                    chave = f"func_{lancamento.funcionario.pk}"
                    label = f"{lancamento.funcionario.nome} - {lancamento.funcionario.cpf} (sem vínculo)"
            else:  # competencia
                chave = f"{competencia_raw}|{parcela_13}"
                label = competencia_label
            
            grupos[chave]['label'] = label
            grupos[chave]['items'].append(resultado)
            
            # Acumular totais do grupo
            for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']:
                if k in calc:
                    grupos[chave]['totais'][k] += calc[k]
            # Total exibido = depósito corrigido (sem somar JAM)
            grupos[chave]['totais']['total'] = grupos[chave]['totais']['valor_deposito_fgts']
        
        # Ordenar grupos
        if agrupamento == 'ano':
            grupos_ordenados = sorted(grupos.items(), key=lambda x: x[0])
        elif agrupamento == 'competencia':
            def parse_comp_key(key):
                try:
                    comp_part = key.split('|')[0]
                    return datetime.strptime(comp_part, '%m/%Y').date()
                except Exception:
                    return datetime(1900, 1, 1).date()
            grupos_ordenados = sorted(grupos.items(), key=lambda x: parse_comp_key(x[0]))
        else:  # funcionario/vinculo
            grupos_ordenados = sorted(grupos.items(), key=lambda x: grupos[x[0]]['label'])
        
        return grupos_ordenados

    def _compute_for(self, empresa, competencia_str, parcela_13, data_pagamento, funcionario=None, matricula=None, jam_state=None):
        import time
        from django.db.models import Q
        inicio_timestamp = time.time()
        inicio_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        try:
            if jam_state is None:
                jam_state = {}

            if parcela_13 in [0, '0', '', None]:
                parcela_13 = None

            competencia_norm = self.normalizar_competencia(competencia_str)

            # BLOQUEIO: Validar se data_pagamento está dentro do range de data_base disponível para a competência/tabela
            from indices.models import SupabaseIndice
            from indices.services.indice_service import IndiceFGTSService
            try:
                competencia_date = datetime.strptime(competencia_norm, '%m/%Y').date().replace(day=1)
            except ValueError:
                return None, None, 'Competência inválida. Use MM/YYYY.', jam_state, []

            tabela = int(IndiceFGTSService.determinar_tabela(competencia_date))
            qs_indices = SupabaseIndice.objects.filter(competencia=competencia_date, tabela=tabela)
            datas_base = list(qs_indices.values_list('data_base', flat=True))
            if not datas_base:
                return None, None, f'Nenhum índice cadastrado para competência {competencia_norm} (tabela {tabela}).', jam_state, []
            data_base_min = min(datas_base)
            data_base_max = max(datas_base)
            if data_pagamento < data_base_min or data_pagamento > data_base_max:
                msg = (
                    f'❌ Não é possível calcular para a data de pagamento {data_pagamento.strftime("%d/%m/%Y")}.'
                    f' O intervalo permitido para competência {competencia_norm} (tabela {tabela}) é de '
                    f'{data_base_min.strftime("%d/%m/%Y")} até {data_base_max.strftime("%d/%m/%Y")}.'
                    ' Geralmente, as datas vão do dia 21 ao dia 20 do mês seguinte.'
                )
                return None, None, msg, jam_state, []
            # ...existing code...
            # (todo o restante do método permanece igual)
        except Exception as e:
            return None, None, f'Erro inesperado ao processar relatório: {str(e)}', jam_state if jam_state else {}, []
        avisos = []
        
        # 🛡️ Verificar se há loop infinito
        try:
            loop_key = competencia_norm if parcela_13 is None else f"{competencia_norm}|{parcela_13}"
            self._verificar_loop(loop_key)
        except Exception as e:
            return None, None, str(e), jam_state, avisos
        
        try:
            competencia_date = datetime.strptime(competencia_norm, '%m/%Y').date().replace(day=1)
        except ValueError:
            return None, None, 'Competência inválida. Use MM/YYYY.', jam_state, avisos


        # Buscar lançamentos pela competência armazenada como string 'MM/YYYY'

        # Busca por competencia como string 'MM/YYYY'
        # Aceita competências armazenadas como MM/YYYY ou YYYY-MM
        comp_iso = None
        try:
            mes_norm, ano_norm = competencia_norm.split('/')
            comp_iso = f"{ano_norm}-{mes_norm.zfill(2)}"
        except Exception:
            comp_iso = None

        filtro_comp = Q(competencia=competencia_norm)
        if comp_iso:
            filtro_comp |= Q(competencia=comp_iso)

        lancs_qs = (Lancamento.objects
            .filter(empresa=empresa)
            .filter(filtro_comp)
            .filter(parcela_13=parcela_13, pago=False)
            .select_related('funcionario', 'vinculo')
            .order_by('funcionario_id', 'vinculo_id'))
        if funcionario:
            lancs_qs = lancs_qs.filter(funcionario=funcionario)
        if matricula:
            lancs_qs = lancs_qs.filter(vinculo__matricula__iexact=str(matricula).strip())

        # Filtrar por vínculo ativo na competência
        lancamentos_filtrados = []
        for l in lancs_qs:
            if getattr(l, 'vinculo_id', None):
                if l.vinculo and l.vinculo.empresa_id == empresa.pk and l.vinculo.is_ativo_em_competencia(competencia_norm):
                    lancamentos_filtrados.append(l)
                continue

            vinculos = getattr(l.funcionario, 'vinculos', None)
            if not vinculos:
                continue
            if any(v.empresa_id == empresa.pk and v.is_ativo_em_competencia(competencia_norm) for v in vinculos.all()):
                lancamentos_filtrados.append(l)

        # ⚡ Se não há lançamentos para esta competência, pular silenciosamente
        if not lancamentos_filtrados:
            print(f"[DEBUG FGTS] Nenhum lançamento encontrado para competência/parcela/empresa/funcionario/pago=False (após filtro de vínculo ativo)")
            return [], {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}, None, jam_state, avisos

        # REGRA DE NEGÓCIO IMUTÁVEL: Buscar índice EXATO
        # competencia = competencia_date E data_base = data_pagamento E tabela automática
        # USAR APENAS IndiceFGTSService - NUNCA ALTERAR ESTA LÓGICA
        # Tabela é determinada AUTOMATICAMENTE: 6 (até 09/1989) ou 7 (10/1989+)
        indice_valor = IndiceFGTSService.buscar_indice(
            competencia=competencia_date,
            data_pagamento=data_pagamento
            # tabela determinada automaticamente pelo serviço
        )

        if indice_valor is None:
            # Diagnóstico: listar datas_base disponíveis para a mesma competência/tabela
            try:
                from indices.models import SupabaseIndice
                datas_disponiveis = list(
                    SupabaseIndice.objects.filter(
                        competencia=competencia_date,
                        tabela=tabela
                    ).order_by('data_base').values_list('data_base', flat=True)
                )
            except Exception:
                datas_disponiveis = []

            # ⚠️ AVISO: Índice não encontrado, pular a competência mas notificar o usuário com as datas disponíveis
            if datas_disponiveis:
                datas_str = ', '.join([d.strftime('%d/%m/%Y') for d in datas_disponiveis])
                aviso = (
                    f"⚠️ Nenhum índice FGTS encontrado para competência {competencia_norm} na data de pagamento {data_pagamento.strftime('%d/%m/%Y')} "
                    f"(tabela {tabela}). Datas disponíveis na indices_fgts: {datas_str}."
                )
            else:
                aviso = (
                    f"⚠️ Nenhum índice FGTS encontrado para competência {competencia_norm} na data de pagamento {data_pagamento.strftime('%d/%m/%Y')} "
                    f"(tabela {tabela})."
                )

            avisos.append(aviso)
            return [], {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}, None, jam_state, avisos

        juros_tipo = get_config_str('JUROS_TIPO', 'MENSAL')
        juros_mensal = get_config_numeric('JUROS_MENSAL_PERCENT', Decimal('0.5'))
        juros_diario = get_config_numeric('JUROS_DIARIO_PERCENT', Decimal('0.033'))
        multa_percent = get_config_numeric('MULTA_PERCENT', Decimal('10.0'))

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
        meses_sem_coef_aviso: set[date] = set()
        coef_cache: dict[date, Decimal | None] = {}

        def _get_coef(comp_date: date) -> Decimal | None:
            comp_key = comp_date.replace(day=1)
            if comp_key not in coef_cache:
                coef_cache[comp_key] = buscar_coef_jam(comp_key)
            return coef_cache[comp_key]

        comp_display = competencia_norm
        if parcela_13 == 1:
            comp_display = f"{competencia_norm} (13º 1ª)"
        elif parcela_13 == 2:
            comp_display = f"{competencia_norm} (13º 2ª)"

        for l in lancamentos_filtrados:
            jam_key = None
            if getattr(l, 'vinculo_id', None):
                jam_key = f"vinc_{l.vinculo_id}"
            else:
                jam_key = f"func_{l.funcionario.pk}"

            if jam_key not in jam_state:
                jam_state[jam_key] = {'acumulado': Decimal('0.00')}

            # Ajuste de plano econômico legado (multiplica e divide conforme VB6)
            valor_fgts_ajustado, fator_mult, fator_div, fator_liquido = aplicar_plano_economico_legacy(
                l.valor_fgts,
                competencia_date,
            )

            valor_jam, _detalhes_jam, meses_sem_coef = calcular_jam_ate_pagamento(
                valor_fgts=valor_fgts_ajustado,
                competencia=competencia_date,
                data_pagamento=data_pagamento,
                coef_lookup=_get_coef,
            )

            if meses_sem_coef:
                meses_sem_coef_aviso.update(meses_sem_coef)

            jam_state[jam_key]['acumulado'] = jam_state[jam_key]['acumulado'] + valor_fgts_ajustado + valor_jam

            calc = calcular_fgts_atualizado(
                valor_fgts=valor_fgts_ajustado,
                competencia=competencia_date,
                pagamento=data_pagamento,
                indice=indice_valor,
                jam_coef=None,
                valor_jam_override=valor_jam,
                aplicar_plano_economico=False,
                fator_plano_info=(fator_mult, fator_div, fator_liquido),
                valor_fgts_base=l.base_fgts,
                juros_tipo=juros_tipo,
                juros_mensal=juros_mensal,
                juros_diario=juros_diario,
                multa_percent=multa_percent,
            )
            resultados.append({
                'lancamento': l,
                'calc': calc,
                'competencia': competencia_norm,
                'parcela_13': parcela_13,
                'competencia_display': comp_display,
            })
            for k in totais.keys():
                if k in calc:
                    totais[k] += calc[k]

        if meses_sem_coef_aviso:
            meses_txt = ', '.join(sorted({m.strftime('%m/%Y') for m in meses_sem_coef_aviso}))
            avisos.append(
                f"⚠️ Coeficiente JAM ausente para: {meses_txt}. Cálculo desses meses considerado como 0."
            )

        return resultados, totais, None, jam_state, avisos

    def form_valid(self, form):
        import logging
        import time
        from datetime import datetime
        logger = logging.getLogger(__name__)

        # Inicializar métricas de tempo para todos os fluxos
        inicio_timestamp = time.time()
        inicio_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

        # Reset contadores de loop para cada nova requisição
        self.tempo_inicio = None
        self.competencias_processadas = {}

        try:
            empresa = form.cleaned_data['empresa']
            competencia_str = (form.cleaned_data.get('competencia') or '').strip()
            competencias_multi = (form.cleaned_data.get('competencias') or '').strip()
            # Normalizar competência única para o formato do banco
            if competencia_str:
                competencia_str = self.normalizar_competencia(competencia_str)
            # Normalizar múltiplas competências (uma por linha)
            if competencias_multi:
                competencias_multi = '\n'.join([
                    self.normalizar_competencia(c.strip())
                    for c in competencias_multi.splitlines() if c.strip()
                ])
            funcionario = form.cleaned_data.get('funcionario')
            matricula = (form.cleaned_data.get('matricula') or '').strip()
            agrupamento = form.cleaned_data.get('agrupamento', 'competencia')
            if form.cleaned_data['data_pagamento']:
                data_pagamento = form.cleaned_data['data_pagamento']
            else:
                from indices.services.indice_service import IndiceFGTSService
                data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()

            # Escopo multi-tenant: empresa deve estar autorizada
            if not is_empresa_allowed(self.request.user, empresa.codigo):
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': 'Empresa não permitida para este usuário.',
                    **feature_block_context('custom_reports', user=self.request.user, empresa=empresa),
                })

            allowed_report, motivo_bloqueio = can_use_feature('custom_reports', user=self.request.user, empresa=empresa)
            if not allowed_report:
                messages.error(
                    self.request,
                    motivo_bloqueio or 'Trial expirado e nenhum plano ativo. Assine um plano para gerar relatórios.'
                )
                contexto_bloqueio = feature_block_context('custom_reports', user=self.request.user, empresa=empresa)
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': contexto_bloqueio.get('feature_block_reason') or motivo_bloqueio,
                    **contexto_bloqueio,
                })

            resultados = []
            totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
            avisos_total = []  # Coletar todos os avisos

            def format_comp_display(comp, parcela_13):
                if parcela_13 == 1:
                    return f"{comp} (13º 1ª)"
                if parcela_13 == 2:
                    return f"{comp} (13º 2ª)"
                return comp

            # Determinar lista de competências a processar (com parcela_13)
            if competencias_multi:
                competencias_list = [{'competencia': c.strip(), 'parcela_13': None} for c in competencias_multi.splitlines() if c.strip()]
            elif competencia_str:
                competencias_list = [{'competencia': competencia_str, 'parcela_13': None}]
            else:
                # Busca por competencia como string
                lancamentos_qs = Lancamento.objects.filter(
                    empresa=empresa,
                    pago=False
                )
                if funcionario:
                    lancamentos_qs = lancamentos_qs.filter(funcionario=funcionario)
                if matricula:
                    lancamentos_qs = lancamentos_qs.filter(vinculo__matricula__iexact=matricula)

                competencias_list = list(
                    lancamentos_qs.values('competencia', 'parcela_13')
                    .distinct()
                    .order_by('competencia', 'parcela_13')
                )

                if not competencias_list:
                    return render(self.request, self.template_name, {
                        'form': form,
                        'erro': 'Nenhum lançamento em aberto encontrado. Verifique se existem lançamentos com status "Não Pago".'
                    })

            # Ordena competências cronologicamente para respeitar o acumulado do JAM legado
            def _parse_comp(c: str):
                # Aceita 'MM/YYYY' ou 'YYYY-MM' como válido
                try:
                    if isinstance(c, str):
                        if '/' in c:
                            return datetime.strptime(c, '%m/%Y').date()
                        if '-' in c:
                            return datetime.strptime(c, '%Y-%m').date()
                    return None
                except Exception:
                    return None

            competencias_invalidas = [c['competencia'] for c in competencias_list if _parse_comp(c['competencia']) is None]
            competencias_list = [c for c in competencias_list if _parse_comp(c['competencia']) is not None]
            competencias_list.sort(key=lambda x: (_parse_comp(x['competencia']) or date(1900, 1, 1), x.get('parcela_13') or 0))

            # Limitar quantidade para evitar timeouts
            # Limite removido para teste de performance

            if not competencias_list:
                erro_msg = 'Nenhuma competência válida encontrada.'
                if competencias_invalidas:
                    erro_msg += (
                        f' Competências inválidas: {", ".join(competencias_invalidas[:5])}. '
                        'Aceitos: MM/YYYY ou YYYY-MM.'
                    )
                return render(self.request, self.template_name, {'form': form, 'erro': erro_msg})

            jam_state = {}
            total_lancamentos = 0
            competencias_com_erro = []
            # LOG TEMPORÁRIO: imprimir competências que serão usadas no filtro
            print('DEBUG - competencias_list:', [c['competencia'] for c in competencias_list])
            for comp_data in competencias_list:
                comp = comp_data['competencia']
                parc = comp_data.get('parcela_13')
                res, tot, err, jam_state, avisos = self._compute_for(empresa, comp, parc, data_pagamento, funcionario, matricula or None, jam_state)
                # Se houver erro (ex: índice ausente), registrar aviso e seguir para próxima competência
                if err:
                    comp_display = f"{comp} (13º {parc})" if parc else comp
                    aviso_erro = f"⚠️ Competência {comp_display} pulada: {err}"
                    avisos_total.append(aviso_erro)
                    competencias_com_erro.append(comp)
                    continue
                # Coletar avisos
                if avisos:
                    avisos_total.extend(avisos)
                if res:
                    resultados.extend(res)
                    total_lancamentos += len(res)
                    # ⚠️ NÃO SOMAR AQUI - os subtotais serão calculados na agregação
            if not resultados:
                fim_timestamp = time.time()
                fim_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                tempo_total = fim_timestamp - inicio_timestamp
                # Montar mensagem detalhada de filtros
                filtros_info = f"<br><strong>Filtros utilizados:</strong>"\
                    f"<br>Empresa: {empresa.nome} (ID: {empresa.pk})"\
                    f"<br>Funcionário: {funcionario.nome if funcionario else 'Todos'}"\
                    f"<br>Matrícula: {matricula or '—'}"\
                    f"<br>Competências: {', '.join([c['competencia'] for c in competencias_list])}"\
                    f"<br>Data de Pagamento: {data_pagamento.strftime('%d/%m/%Y')}"\
                    f"<br>Status: Não Pago (pago=False)"
                erro_msg = 'Nenhum lançamento encontrado com os filtros aplicados.' \
                    ' Verifique se há lançamentos com status "Não Pago" para as competências selecionadas.' \
                    + filtros_info
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': erro_msg,
                    'kpi_inicio': inicio_str,
                    'kpi_fim': fim_str,
                    'kpi_tempo': f'{tempo_total:.2f} segundos',
                    'kpi_lancamentos': total_lancamentos,
                    'kpi_competencias': len(competencias_list),
                })

            # Aplicar agrupamento
            resultados_agrupados = self._agrupar_resultados(resultados, agrupamento)
            
            # ✅ CORRIGIR: Recalcular totais gerais a partir dos grupos (evitar duplicação)
            totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
            for chave, grupo_data in resultados_agrupados:
                for k in totais.keys():
                    totais[k] += grupo_data['totais'][k]

            competencias_display = [format_comp_display(c['competencia'], c.get('parcela_13')) for c in competencias_list]
            competencias_param = [f"{c['competencia']}|{c.get('parcela_13') or ''}" for c in competencias_list]
            competencia_primeira = competencias_list[0]['competencia'] if competencias_list else ''

            fim_timestamp = time.time()
            fim_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            tempo_total = fim_timestamp - inicio_timestamp
            contexto = {
                'form': form,
                'empresa': empresa,
                'funcionario': funcionario,
                'matricula': matricula or None,
                'competencias': competencias_display,
                'competencias_param': competencias_param,
                'competencia_primeira': competencia_primeira,
                'data_pagamento': data_pagamento,
                'resultados': resultados,
                'resultados_agrupados': resultados_agrupados,
                'agrupamento': agrupamento,
                'totais': totais,
                'avisos': avisos_total,  # Adicionar avisos ao contexto
                'kpi_inicio': inicio_str,
                'kpi_fim': fim_str,
                'kpi_tempo': f'{tempo_total:.2f} segundos',
                'kpi_lancamentos': total_lancamentos,
                'kpi_competencias': len(competencias_list),
            }
            contexto.update(feature_block_context('custom_reports', user=self.request.user, empresa=empresa))
            return render(self.request, self.template_name, contexto)
            
        except Exception as e:
            logger.error(f"🛑 Erro em RelatorioCompetenciaView.form_valid: {str(e)}")
            return render(self.request, self.template_name, {
                'form': form,
                'erro': f"🛑 Erro ao processar relatório: {str(e)}",
                **feature_block_context('custom_reports', user=self.request.user, empresa=form.cleaned_data.get('empresa')),
            })

def relatorio_por_ids(request):
    from django.http import HttpResponse
    from django.shortcuts import render
    from collections import defaultdict
    from decimal import Decimal

    debug_detalhado = request.GET.get('debug', '') == '1'
    debug_lancamentos = []
    ids_str = request.GET.get('ids', '')
    if not ids_str:
        return HttpResponse('Nenhum lançamento selecionado.', status=400)
    try:
        ids = [int(id_str.strip()) for id_str in ids_str.split(',') if id_str.strip()]
    except ValueError:
        return HttpResponse('IDs inválidos.', status=400)
    if not ids:
        return HttpResponse('Nenhum lançamento selecionado.', status=400)

    # Buscar lançamentos pelos IDs e apenas não pagos
    lancamentos = Lancamento.objects.filter(id__in=ids, pago=False).select_related('empresa', 'funcionario', 'vinculo')
    if not lancamentos.exists():
        return HttpResponse('Nenhum lançamento encontrado.', status=404)

    empresa_referencia = lancamentos.first().empresa if lancamentos else None
    allowed_report, motivo_bloqueio = can_use_feature('custom_reports', user=request.user, empresa=empresa_referencia)
    if not allowed_report:
        messages.error(request, motivo_bloqueio or 'Trial expirado e nenhum plano ativo. Assine um plano para gerar relatórios.')
        return redirect('lancamento-list')

    # Verificar permissões multi-tenant
    allowed_ids = get_allowed_empresa_ids(request.user)
    if allowed_ids is not None:
        lancamentos = lancamentos.filter(empresa__codigo__in=allowed_ids)
        if not lancamentos.exists():
            return HttpResponse('Você não tem permissão para acessar esses lançamentos.', status=403)

    # Filtrar por vínculo ativo na competência e não pago
    lancamentos_filtrados = []
    avisos_total = []
    empresa = empresa_referencia
    # Forçar a data_pagamento para a última data_base disponível (ignora qualquer data enviada)
    from indices.services.indice_service import IndiceFGTSService
    data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()

    from empresas.models_grupo import FuncionarioVinculo  # noqa: F401 (usado para is_ativo_em_competencia)
    import re

    for lanc in lancamentos:
        competencia = lanc.competencia
        empresa = lanc.empresa
        funcionario = lanc.funcionario
        vinculos = getattr(funcionario, 'vinculos', None)
        competencia_norm = competencia
        match = re.match(r'^(\d{2})/(\d{4})$', competencia)
        if match:
            mes, ano = match.groups()
            competencia_norm = f"{ano}-{mes}"
        elif re.match(r'^13/\d{4}$', competencia):
            ano = competencia[-4:]
            competencia_norm = f"{ano}-12"
        motivo = []
        vinculo_ativo = False
        if vinculos:
            for v in vinculos.all():
                empresa_id = getattr(empresa, 'id', None) or getattr(empresa, 'codigo', None)
                if (str(v.empresa_id) == str(empresa_id)) and v.is_ativo_em_competencia(competencia_norm):
                    vinculo_ativo = True
                    break
        if not vinculos:
            motivo.append('Sem vínculos cadastrados')
        elif vinculo_ativo:
            motivo.append('Vínculo ativo OK')
        else:
            motivo.append('Sem vínculo ativo na competência')
        if not lanc.pago:
            motivo.append('Não pago')
        else:
            motivo.append('Já pago')

        if (vinculo_ativo or not vinculos) and not lanc.pago:
            lancamentos_filtrados.append(lanc)
            status = 'Incluído'
        else:
            status = 'Excluído'

        if debug_detalhado:
            debug_lancamentos.append({
                'id': lanc.id,
                'colaborador': getattr(funcionario, 'nome', str(funcionario)),
                'competencia': competencia,
                'empresa': getattr(empresa, 'nome', str(empresa)),
                'motivo': ', '.join(motivo),
                'status': status
            })

    print('DEBUG lancamentos_filtrados:', [(l.id, l.competencia, getattr(l, 'parcela_13', None)) for l in lancamentos_filtrados])

    # Usar o mesmo cálculo do relatório padrão (índice, correção, JAM)
    view = RelatorioCompetenciaView()
    view.request = request

    resultados = []
    totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
    jam_state = {}
    avisos_total = []
    ids_set = {l.id for l in lancamentos_filtrados}

    grupos = defaultdict(list)
    for lanc in lancamentos_filtrados:
        if empresa is None:
            empresa = lanc.empresa
        comp_norm = view.normalizar_competencia(lanc.competencia)
        key = (lanc.empresa_id, comp_norm, lanc.parcela_13 or 0)
        grupos[key].append(lanc)

    for (empresa_id, comp_norm, parcela_13), _lancs in grupos.items():
        empresa_grupo = _lancs[0].empresa
        res, _tot, err, jam_state, avisos = view._compute_for(
            empresa_grupo,
            comp_norm,
            parcela_13,
            data_pagamento,
            funcionario=None,
            jam_state=jam_state,
        )
        if avisos:
            avisos_total.extend(avisos)
        if err:
            continue

        # Manter apenas os lançamentos selecionados
        res_filtrados = [r for r in res if r.get('lancamento') and r['lancamento'].id in ids_set]
        resultados.extend(res_filtrados)

    for r in resultados:
        for k in totais.keys():
            totais[k] += r['calc'][k]
    totais['total'] = totais['valor_deposito_fgts']

    if not resultados:
        return HttpResponse('Nenhum resultado calculado para os lançamentos selecionados.', status=404)

    # Agrupar resultados por competência
    def parse_comp_key(key):
        try:
            return datetime.strptime(key[0], '%m/%Y').date()
        except Exception:
            return datetime(1900, 1, 1).date()

    resultados_agrupados = view._agrupar_resultados(resultados, 'competencia')

    def _format_comp_display(comp, parcela):
        if parcela == 1:
            return f"{comp} (13º 1ª)"
        if parcela == 2:
            return f"{comp} (13º 2ª)"
        return comp

    competencias_display = [_format_comp_display(k[1], k[2]) for k in grupos.keys()]
    competencias_param = [f"{k[1]}|{k[2] or ''}" for k in grupos.keys()]

    contexto = {
        'empresa': empresa,
        'competencias': competencias_display,
        'competencias_param': competencias_param,
        'data_pagamento': data_pagamento,
        'resultados': resultados,
        'resultados_agrupados': resultados_agrupados,
        'agrupamento': 'competencia',
        'totais': totais,
        'avisos': avisos_total,
        'from_selection': True,
        'ids_param': ','.join([str(i) for i in ids]),
        'debug_lancamentos': debug_lancamentos if debug_detalhado else None,
    }
    return render(request, 'lancamentos/relatorio_competencia.html', contexto)

def export_relatorio_competencia_csv(request):
    from django.http import HttpResponse
    from collections import defaultdict
    import urllib.parse
    
    empresa_id = request.GET.get('empresa')
    competencias_multi = request.GET.get('competencias', '')
    competencia_unica = request.GET.get('competencia', '')
    competencia_unica = request.GET.get('competencia', '')
    funcionario_id = request.GET.get('funcionario')
    matricula = (request.GET.get('matricula') or '').strip()
    data_pagamento_str = request.GET.get('data_pagamento')
    agrupamento = request.GET.get('agrupamento', 'competencia')
    ids_str = request.GET.get('ids', '').strip()
    ids_str = request.GET.get('ids', '').strip()

    # Decodificar competências que podem vir URL-encoded
    competencias_multi = urllib.parse.unquote(competencias_multi)

    empresa = Empresa.objects.get(pk=empresa_id)
    allowed_csv, motivo_bloqueio = can_use_feature('pdf_export', user=request.user, empresa=empresa)
    if not allowed_csv:
        return HttpResponseForbidden(motivo_bloqueio or 'Seu plano não permite exportar relatórios (CSV/PDF).')
    if data_pagamento_str:
        data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date()
    else:
        from indices.services.indice_service import IndiceFGTSService
        data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()
    funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

    view = RelatorioCompetenciaView()
    view.request = request

    if ids_str:
        try:
            ids = [int(id_str.strip()) for id_str in ids_str.split(',') if id_str.strip()]
        except ValueError:
            return HttpResponse('IDs inválidos.', status=400)
        if not ids:
            return HttpResponse('Nenhum lançamento selecionado.', status=400)

        from indices.services.indice_service import IndiceFGTSService
        data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()

        lancamentos = Lancamento.objects.filter(id__in=ids, pago=False).select_related('empresa', 'funcionario', 'vinculo')
        if not lancamentos.exists():
            return HttpResponse('Nenhum lançamento encontrado.', status=404)

        allowed_ids = get_allowed_empresa_ids(request.user)
        if allowed_ids is not None:
            lancamentos = lancamentos.filter(empresa__codigo__in=allowed_ids)
            if not lancamentos.exists():
                return HttpResponse('Você não tem permissão para acessar esses lançamentos.', status=403)

        lancamentos_filtrados = []
        empresa = None
        from empresas.models_grupo import FuncionarioVinculo  # noqa: F401 (usado para is_ativo_em_competencia)
        import re

        for lanc in lancamentos:
            competencia = lanc.competencia
            empresa = lanc.empresa
            funcionario = lanc.funcionario
            vinculos = getattr(funcionario, 'vinculos', None)
            competencia_norm = competencia
            match = re.match(r'^(\d{2})/(\d{4})$', competencia)
            if match:
                mes, ano = match.groups()
                competencia_norm = f"{ano}-{mes}"
            elif re.match(r'^13/\d{4}$', competencia):
                ano = competencia[-4:]
                competencia_norm = f"{ano}-12"

            vinculo_ativo = False
            if vinculos:
                for v in vinculos.all():
                    empresa_id_comp = getattr(empresa, 'id', None) or getattr(empresa, 'codigo', None)
                    if (str(v.empresa_id) == str(empresa_id_comp)) and v.is_ativo_em_competencia(competencia_norm):
                        vinculo_ativo = True
                        break

            if (vinculo_ativo or not vinculos) and not lanc.pago:
                lancamentos_filtrados.append(lanc)

        if not lancamentos_filtrados:
            return HttpResponse('Nenhum lançamento encontrado para os filtros aplicados.', status=404)

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
        jam_state = {}
        ids_set = {l.id for l in lancamentos_filtrados}

        grupos = defaultdict(list)
        for lanc in lancamentos_filtrados:
            if empresa is None:
                empresa = lanc.empresa
            comp_norm = view.normalizar_competencia(lanc.competencia)
            key = (lanc.empresa_id, comp_norm, lanc.parcela_13 or 0)
            grupos[key].append(lanc)

        for (_empresa_id, comp_norm, parcela_13), _lancs in grupos.items():
            empresa_grupo = _lancs[0].empresa
            res, _tot, err, jam_state, _avisos = view._compute_for(
                empresa_grupo,
                comp_norm,
                parcela_13,
                data_pagamento,
                funcionario=None,
                jam_state=jam_state,
            )
            if err:
                continue

            res_filtrados = [r for r in res if r.get('lancamento') and r['lancamento'].id in ids_set]
            resultados.extend(res_filtrados)

        for r in resultados:
            for k in totais.keys():
                totais[k] += r['calc'][k]
        totais['total'] = totais['valor_deposito_fgts']

        if not resultados:
            return HttpResponse('Nenhum resultado calculado para os lançamentos selecionados.', status=404)

        agrupamento = 'funcionario'
        resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)

        import csv
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="relatorio_fgts.csv"'
        writer = csv.writer(resp, delimiter=';')

        def _grupo_label(label):
            if agrupamento == 'funcionario':
                return f"Funcionário: {label}"
            if agrupamento == 'ano':
                return f"{label}"
            return f"Competência: {label}"

        writer.writerow(['Empresa', 'Competência', 'Funcionário', 'Matrícula', 'ID Vínculo', 'Empresa do Vínculo', 'Admissão', 'Demissão', 'Base FGTS', 'FGTS Valor', 'Índice', 'Correção', 'Total'])

        for _chave, grupo in resultados_agrupados:
            writer.writerow([])
            writer.writerow([_grupo_label(grupo.get('label'))])

            for item in grupo['items']:
                l = item['lancamento']
                c = item['calc']
                comp_out = item.get('competencia_display', item.get('competencia'))
                funcionario = l.funcionario
                vinculo = l.vinculo
                if not vinculo:
                    vinculo = funcionario.vinculos.filter(empresa=l.empresa).order_by('-data_admissao').first()
                empresa_vinculo = vinculo.empresa.nome if vinculo else l.empresa.nome
                data_admissao = vinculo.data_admissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_admissao else ''
                data_demissao = vinculo.data_demissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_demissao else ''
                writer.writerow([
                    empresa.nome,
                    comp_out,
                    funcionario.nome,
                    (vinculo.matricula if vinculo and vinculo.matricula else ''),
                    (vinculo.pk if vinculo else ''),
                    empresa_vinculo,
                    data_admissao,
                    data_demissao,
                    f"{l.base_fgts}",
                    f"{c.get('valor_fgts', l.valor_fgts)}",
                    f"{c.get('indice', '')}",
                    f"{c['valor_corrigido']}",
                    f"{c['total']}",
                ])

        writer.writerow([])
        writer.writerow(['Totais', '', '', '', '', '', totais['valor_fgts'], '', '', totais['valor_corrigido'], totais['total']])
        return resp
    
    # Parse competências (separar por \n ou %0A) mantendo parcela_13 quando informada
    competencias_raw = [c.strip() for c in competencias_multi.replace('%0A', '\n').split('\n') if c.strip()]
    competencias_list = []
    for entry in competencias_raw:
        comp_str = entry
        parc_val = None
        if '|' in entry:
            comp_str, parc_part = entry.split('|', 1)
            parc_part = parc_part.strip()
            if parc_part:
                try:
                    parc_val = int(parc_part)
                except ValueError:
                    parc_val = None
        if parc_val == 0:
            parc_val = None
        competencias_list.append({'competencia': comp_str, 'parcela_13': parc_val})
    
    # Se não houver competências especificadas, buscar todas em aberto
    if not competencias_list:
        lancamentos_qs = Lancamento.objects.filter(empresa=empresa, pago=False)
        if funcionario:
            lancamentos_qs = lancamentos_qs.filter(funcionario=funcionario)
        if matricula:
            lancamentos_qs = lancamentos_qs.filter(vinculo__matricula__iexact=matricula)
        
        competencias_unicas = (
            lancamentos_qs.values('competencia', 'parcela_13')
            .distinct()
            .order_by('competencia', 'parcela_13')
        )
        competencias_list = [
            {'competencia': item['competencia'], 'parcela_13': item['parcela_13']}
            for item in competencias_unicas
        ]
    
    # Ordenar por competência
    def _parse_comp(c_dict):
        try:
            comp_str = c_dict['competencia']
            return datetime.strptime(comp_str, '%m/%Y').date()
        except Exception:
            return date(1900, 1, 1)
    
    competencias_list.sort(key=lambda x: (_parse_comp(x), x.get('parcela_13') or 0))

    resultados = []
    totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
    jam_state = {}
    first_error = None
    first_error = None
    
    for comp_dict in competencias_list:
        comp = comp_dict['competencia']
        parcela_13 = comp_dict.get('parcela_13')
        
        res, tot, err, jam_state, _avisos = view._compute_for(empresa, comp, parcela_13, data_pagamento, funcionario, matricula or None, jam_state)
        if err:
            if first_error is None:
                first_error = err
            continue
        
        resultados.extend(res)
        
        for k in totais.keys():
            totais[k] += tot.get(k, Decimal('0'))


    if not resultados:
        mensagem = first_error or 'Nenhum lançamento encontrado para os filtros aplicados.'
        resp = HttpResponse(mensagem, status=400 if first_error else 404)
        resp['Content-Type'] = 'text/plain; charset=utf-8'
        return resp

    resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)

    import csv
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="relatorio_fgts.csv"'
    writer = csv.writer(resp, delimiter=';')
    
    def _grupo_label(label):
        if agrupamento == 'funcionario':
            return f"Funcionário: {label}"
        if agrupamento == 'ano':
            return f"{label}"
        return f"Competência: {label}"
    
    writer.writerow(['Empresa', 'Competência', 'Funcionário', 'Matrícula', 'ID Vínculo', 'Empresa do Vínculo', 'Admissão', 'Demissão', 'Base FGTS', 'FGTS Valor', 'Índice', 'Correção', 'Total'])

    for _chave, grupo in resultados_agrupados:
        writer.writerow([])
        writer.writerow([_grupo_label(grupo.get('label'))])

        for item in grupo['items']:
            l = item['lancamento']
            c = item['calc']
            comp_out = item.get('competencia_display', item.get('competencia'))
            funcionario = l.funcionario
            vinculo = l.vinculo
            if not vinculo:
                vinculo = funcionario.vinculos.filter(empresa=l.empresa).order_by('-data_admissao').first()
            empresa_vinculo = vinculo.empresa.nome if vinculo else l.empresa.nome
            data_admissao = vinculo.data_admissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_admissao else ''
            data_demissao = vinculo.data_demissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_demissao else ''
            writer.writerow([
                empresa.nome,
                comp_out,
                funcionario.nome,
                (vinculo.matricula if vinculo and vinculo.matricula else ''),
                (vinculo.pk if vinculo else ''),
                empresa_vinculo,
                data_admissao,
                data_demissao,
                f"{l.base_fgts}",
                f"{c.get('valor_fgts', l.valor_fgts)}",
                f"{c.get('indice', '')}",
                f"{c['valor_corrigido']}",
                f"{c['total']}",
            ])

    writer.writerow([])
    writer.writerow(['Totais', '', '', '', '', '', totais['valor_fgts'], '', '', totais['valor_corrigido'], totais['total']])
    return resp

def export_relatorio_competencia_pdf(request):
    # Função utilitária para converter competência em date
    def competencia_str_to_date(competencia):
        if isinstance(competencia, str):
            if '/' in competencia:
                mes, ano = competencia.split('/')
                return datetime(int(ano), int(mes), 1).date()
            elif '-' in competencia:
                ano, mes = competencia.split('-')
                return datetime(int(ano), int(mes), 1).date()
        elif isinstance(competencia, date):
            return competencia
        raise ValueError("Formato de competência inválido")

    from django.http import HttpResponse
    from collections import defaultdict
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak
    import urllib.parse
    
    empresa_id = request.GET.get('empresa')
    competencias_multi = request.GET.get('competencias', '')
    competencia_unica = request.GET.get('competencia', '')
    funcionario_id = request.GET.get('funcionario')
    matricula = (request.GET.get('matricula') or '').strip()
    data_pagamento_str = request.GET.get('data_pagamento')
    agrupamento = request.GET.get('agrupamento', 'competencia')
    ids_str = request.GET.get('ids', '').strip()

    # Decodificar competências que podem vir URL-encoded com %0A para \n
    competencias_multi = urllib.parse.unquote(competencias_multi)

    empresa = Empresa.objects.get(pk=empresa_id)
    allowed_pdf, motivo_bloqueio = can_use_feature('pdf_export', user=request.user, empresa=empresa)
    if not allowed_pdf:
        return HttpResponseForbidden(motivo_bloqueio or 'Seu plano não permite exportar relatórios (CSV/PDF).')
    if data_pagamento_str:
        data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date()
    else:
        from indices.services.indice_service import IndiceFGTSService
        data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()
    funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

    view = RelatorioCompetenciaView()
    view.request = request  # Necessário para EmpresaScopeMixin

    if ids_str:
        try:
            ids = [int(id_str.strip()) for id_str in ids_str.split(',') if id_str.strip()]
        except ValueError:
            return HttpResponse('IDs inválidos.', status=400)
        if not ids:
            return HttpResponse('Nenhum lançamento selecionado.', status=400)

        from indices.services.indice_service import IndiceFGTSService
        data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()

        lancamentos = Lancamento.objects.filter(id__in=ids, pago=False).select_related('empresa', 'funcionario', 'vinculo')
        if not lancamentos.exists():
            return HttpResponse('Nenhum lançamento encontrado.', status=404)

        allowed_ids = get_allowed_empresa_ids(request.user)
        if allowed_ids is not None:
            lancamentos = lancamentos.filter(empresa__codigo__in=allowed_ids)
            if not lancamentos.exists():
                return HttpResponse('Você não tem permissão para acessar esses lançamentos.', status=403)

        lancamentos_filtrados = []
        empresa = None
        from empresas.models_grupo import FuncionarioVinculo  # noqa: F401 (usado para is_ativo_em_competencia)
        import re

        for lanc in lancamentos:
            competencia = lanc.competencia
            empresa = lanc.empresa
            funcionario = lanc.funcionario
            vinculos = getattr(funcionario, 'vinculos', None)
            competencia_norm = competencia
            match = re.match(r'^(\d{2})/(\d{4})$', competencia)
            if match:
                mes, ano = match.groups()
                competencia_norm = f"{ano}-{mes}"
            elif re.match(r'^13/\d{4}$', competencia):
                ano = competencia[-4:]
                competencia_norm = f"{ano}-12"

            vinculo_ativo = False
            if vinculos:
                for v in vinculos.all():
                    empresa_id_comp = getattr(empresa, 'id', None) or getattr(empresa, 'codigo', None)
                    if (str(v.empresa_id) == str(empresa_id_comp)) and v.is_ativo_em_competencia(competencia_norm):
                        vinculo_ativo = True
                        break

            if (vinculo_ativo or not vinculos) and not lanc.pago:
                lancamentos_filtrados.append(lanc)

        if not lancamentos_filtrados:
            return HttpResponse('Nenhum lançamento encontrado para os filtros aplicados.', status=404)

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
        jam_state = {}
        ids_set = {l.id for l in lancamentos_filtrados}

        grupos = defaultdict(list)
        for lanc in lancamentos_filtrados:
            if empresa is None:
                empresa = lanc.empresa
            comp_norm = view.normalizar_competencia(lanc.competencia)
            key = (lanc.empresa_id, comp_norm, lanc.parcela_13 or 0)
            grupos[key].append(lanc)

        for (_empresa_id, comp_norm, parcela_13), _lancs in grupos.items():
            empresa_grupo = _lancs[0].empresa
            res, _tot, err, jam_state, _avisos = view._compute_for(
                empresa_grupo,
                comp_norm,
                parcela_13,
                data_pagamento,
                funcionario=None,
                jam_state=jam_state,
            )
            if err or not res:
                continue

            res_filtrados = [r for r in res if r.get('lancamento') and r['lancamento'].id in ids_set]
            resultados.extend(res_filtrados)

        for r in resultados:
            for k in totais.keys():
                totais[k] += r['calc'][k]
        totais['total'] = totais['valor_deposito_fgts']

        if not resultados:
            return HttpResponse('Nenhum resultado calculado para os lançamentos selecionados.', status=404)

        # Agrupar resultados por vínculo (quando disponível) para evitar ambiguidade
        from collections import defaultdict
        grupos_func = defaultdict(list)
        for item in resultados:
            l = item['lancamento']
            if getattr(l, 'vinculo_id', None):
                grupos_func[f"vinc_{l.vinculo_id}"].append(item)
            else:
                grupos_func[f"func_{l.funcionario_id}"].append(item)

        def _format_money(valor):
            try:
                return f"{valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            except Exception:
                return str(valor)

        def _format_indice(valor):
            try:
                return f"{valor:.9f}".replace('.', ',')
            except Exception:
                return str(valor)

        def _parse_comp(comp_str):
            try:
                return datetime.strptime(comp_str, '%m/%Y').date()
            except Exception:
                return date(1900, 1, 1)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        styles = getSampleStyleSheet()
        title_style = styles['Heading2']
        normal_style = styles['BodyText']
        small_style = styles['BodyText']
        small_style.fontSize = 8
        small_style.leading = 10

        now = datetime.now()
        usuario_label = getattr(request.user, 'username', 'Usuário')
        empresa_codigo = getattr(empresa, 'codigo_exibicao', None) or getattr(empresa, 'codigo', None)
        empresa_label = f"{empresa_codigo} {empresa.nome}" if empresa_codigo else empresa.nome
        cnpj_label = empresa.cnpj or ''

        story = []

        header_table = Table(
            [
                [
                    Paragraph("LISTAGEM DO RECOLHIMENTO FGTS", title_style),
                    Paragraph("Sistema FGTS em Atraso", normal_style),
                    Paragraph("FGTS WEB", normal_style),
                ],
                [
                    Paragraph(f"USUÁRIO: {usuario_label}", small_style),
                    Paragraph(f"{now.strftime('%d/%m/%Y')} - {now.strftime('%H:%M')}", small_style),
                    Paragraph("Página 1", small_style),
                ],
                [
                    Paragraph(empresa_label, normal_style),
                    Paragraph(f"CNPJ: {cnpj_label}", normal_style),
                    "",
                ],
            ],
            colWidths=[80*mm, 60*mm, 35*mm],
            hAlign='LEFT',
        )
        header_table.setStyle(
            TableStyle([
                ('LINEBELOW', (0, 2), (-1, 2), 0.75, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (2, 0), (2, 1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ])
        )
        story.append(header_table)
        story.append(Spacer(1, 6))

        for idx, (func_id, itens) in enumerate(grupos_func.items()):
            itens.sort(key=lambda x: _parse_comp(x.get('competencia') or x['lancamento'].competencia))
            funcionario = itens[0]['lancamento'].funcionario
            vinculo = itens[0]['lancamento'].vinculo

            data_adm = vinculo.data_admissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_admissao else ''
            data_nasc = funcionario.data_nascimento.strftime('%d/%m/%Y') if funcionario.data_nascimento else ''
            ctps = funcionario.carteira_profissional or ''
            serie = funcionario.serie_carteira or ''
            cbo = funcionario.cbo or ''
            pis = funcionario.pis or ''
            matricula_label = (vinculo.matricula if vinculo and vinculo.matricula else '')

            funcionario_header = Table(
                [
                    [
                        Paragraph(f"{funcionario.id}  {funcionario.nome}" + (f" (Matrícula {matricula_label})" if matricula_label else ""), normal_style),
                        Paragraph(f"Data Adm {data_adm}", normal_style),
                        Paragraph(f"C.B.O. {cbo}", normal_style),
                        Paragraph(f"Data Nasc {data_nasc}", normal_style),
                    ],
                    [
                        Paragraph(f"PIS {pis}", normal_style),
                        Paragraph(f"C.T.P.S. {ctps} / {serie}", normal_style),
                        "",
                        "",
                    ],
                ],
                colWidths=[70*mm, 35*mm, 40*mm, 35*mm],
                hAlign='LEFT',
            )
            funcionario_header.setStyle(
                TableStyle([
                    ('LINEBELOW', (0, 1), (-1, 1), 0.75, colors.black),
                ])
            )
            story.append(funcionario_header)
            story.append(Spacer(1, 4))

            # JAM é um assunto distinto da correção/depósito FGTS.
            # No PDF, exibimos o JAM separado e não o somamos ao depósito.
            table_data = [["Comp.", "13º", "Base FGTS", "Valor FGTS", "Correção", "JAM", "Total", "Índice CEF"]]

            total_fgts = Decimal('0')
            total_deposito_sem_jam = Decimal('0')
            total_jam = Decimal('0')
            total_recolher = Decimal('0')

            for item in itens:
                l = item['lancamento']
                c = item['calc']
                comp_label = l.competencia
                parcela_13 = l.parcela_13 or 0
                col_13 = "13º 1ª" if parcela_13 == 1 else "13º 2ª" if parcela_13 == 2 else ""
                valor_fgts = c.get('valor_fgts', l.valor_fgts)
                valor_deposito_sem_jam = c.get('valor_deposito_fgts')
                valor_correcao = c.get('valor_corrigido')
                valor_jam = c.get('valor_jam', Decimal('0'))
                valor_total = c.get('total')
                if valor_deposito_sem_jam is None:
                    # Fallback seguro (não deve acontecer se calc estiver completo)
                    valor_deposito_sem_jam = (Decimal(str(valor_fgts)) + Decimal(str(valor_correcao or 0))).quantize(Decimal('0.01'))
                if valor_correcao is None:
                    valor_correcao = (Decimal(str(valor_deposito_sem_jam)) - Decimal(str(valor_fgts))).quantize(Decimal('0.01'))
                if valor_total is None:
                    valor_total = (Decimal(str(valor_deposito_sem_jam)) + Decimal(str(valor_jam))).quantize(Decimal('0.01'))
                indice = c.get('indice', '')

                total_fgts += Decimal(str(valor_fgts))
                total_deposito_sem_jam += Decimal(str(valor_deposito_sem_jam))
                total_jam += Decimal(str(valor_jam))
                total_recolher += Decimal(str(valor_total))

                table_data.append([
                    comp_label,
                    col_13,
                    _format_money(l.base_fgts),
                    _format_money(valor_fgts),
                    _format_money(valor_correcao),
                    _format_money(valor_jam),
                    _format_money(valor_total),
                    _format_indice(indice) if indice != '' else '',
                ])

            table = Table(
                table_data,
                colWidths=[18*mm, 10*mm, 27*mm, 23*mm, 22*mm, 18*mm, 22*mm, 30*mm],
                hAlign='LEFT',
                repeatRows=1,
            )
            table.setStyle(
                TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#999999')),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
                ])
            )
            story.append(table)

            box_table = Table(
                [
                    [
                        Paragraph("DATA DO CÁLCULO", normal_style),
                        Paragraph(f"{data_pagamento.strftime('%d/%m/%Y')}", normal_style),
                        "",
                        Paragraph("Total do F.G.T.S. Mensal", normal_style),
                        Paragraph(_format_money(total_fgts), normal_style),
                    ],
                    [
                        "",
                        "",
                        "",
                        Paragraph("Total Depósito (sem JAM)", normal_style),
                        Paragraph(_format_money(total_deposito_sem_jam), normal_style),
                    ],
                    [
                        "",
                        "",
                        "",
                        Paragraph("Total JAM (juros)", normal_style),
                        Paragraph(_format_money(total_jam), normal_style),
                    ],
                    [
                        "",
                        "",
                        "",
                        Paragraph("Valor da Multa Rescisória", normal_style),
                        Paragraph(_format_money(Decimal('0.00')), normal_style),
                    ],
                    [
                        "",
                        "",
                        "",
                        Paragraph("TOTAL A RECOLHER", styles['Heading4']),
                        Paragraph(_format_money(total_recolher), styles['Heading4']),
                    ],
                ],
                colWidths=[35*mm, 30*mm, 10*mm, 55*mm, 30*mm],
                hAlign='LEFT',
            )
            box_table.setStyle(
                TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.75, colors.black),
                    ('SPAN', (0, 0), (1, 0)),
                    ('SPAN', (0, 1), (1, 1)),
                    ('SPAN', (0, 2), (1, 2)),
                    ('SPAN', (0, 3), (1, 3)),
                    ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ])
            )
            story.append(Spacer(1, 6))
            story.append(box_table)

            if idx < len(grupos_func) - 1:
                story.append(PageBreak())

        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()

        resp = HttpResponse(content_type='application/pdf')
        resp['Content-Disposition'] = 'attachment; filename="relatorio_fgts.pdf"'
        resp.write(pdf)
        return resp
    
    # Parse competências como dicionários com parcela_13
    # Separar por \n ou %0A (pode vir URL-encoded)
    competencias_raw = [c.strip() for c in competencias_multi.replace('%0A', '\n').split('\n') if c.strip()]

    if competencia_unica and not competencias_raw:
        competencias_raw = [competencia_unica.strip()]

    competencias_list = []
    for entry in competencias_raw:
        comp_str = entry
        parc_val = None
        if '|' in entry:
            comp_str, parc_part = entry.split('|', 1)
            parc_part = parc_part.strip()
            if parc_part:
                try:
                    parc_val = int(parc_part)
                except ValueError:
                    parc_val = None
        if parc_val == 0:
            parc_val = None
        competencias_list.append({'competencia': comp_str, 'parcela_13': parc_val})

    # Deduplicar competências (competencia, parcela_13)
    dedup = {}
    for c in competencias_list:
        key = (c['competencia'], c.get('parcela_13'))
        dedup[key] = c
    competencias_list = list(dedup.values())

    # Se não houver competências especificadas, não exportar para evitar incluir dados não solicitados
    if not competencias_list:
        resp = HttpResponse('Nenhuma competência informada para exportação.', status=400)
        resp['Content-Type'] = 'text/plain; charset=utf-8'
        return resp

    # Ordenar competências para respeitar o acumulado de JAM
    def _parse_comp(c: str):
        try:
            return datetime.strptime(c, '%m/%Y').date()
        except Exception:
            return None

    competencias_list = [c for c in competencias_list if _parse_comp(c['competencia']) is not None]
    competencias_list.sort(key=lambda x: (_parse_comp(x['competencia']) or date(1900, 1, 1), x.get('parcela_13') or 0))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = styles['Title']
    subtitle_style = styles['Heading3']
    normal_style = styles['BodyText']
    story = [
        Paragraph(f"Relatório FGTS — {empresa.nome}", title_style),
        Paragraph(f"Pagamento: {data_pagamento.strftime('%d/%m/%Y')}", normal_style),
        Spacer(1, 8),
    ]

    resultados = []
    totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
    jam_state = {}
    first_error = None

    for comp_dict in competencias_list:
        comp = comp_dict['competencia']
        parcela_13 = comp_dict.get('parcela_13')

        res, tot, err, jam_state, _avisos = view._compute_for(empresa, comp, parcela_13, data_pagamento, funcionario, jam_state)

        if err or not res:
            if err and first_error is None:
                first_error = err
            continue

        resultados.extend(res)

        for k in totais.keys():
            totais[k] += tot.get(k, Decimal('0'))

    totais['total'] = totais['valor_deposito_fgts']

    if not resultados:
        mensagem = first_error or 'Nenhum lançamento encontrado para os filtros aplicados.'
        resp = HttpResponse(mensagem, status=400 if first_error else 404)
        resp['Content-Type'] = 'text/plain; charset=utf-8'
        return resp

    resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)

    def _grupo_label(label):
        if agrupamento == 'funcionario':
            return f"Funcionário: {label}"
        if agrupamento == 'ano':
            return f"{label}"
        return f"Competência: {label}"

    from reportlab.platypus import PageBreak
    for idx, (_chave, grupo) in enumerate(resultados_agrupados):
        story.append(Spacer(1, 6))
        story.append(Paragraph(_grupo_label(grupo.get('label')), subtitle_style))

        table_data = [
            [
                "Competência",
                "Funcionário",
                "Demissão",
                "Base FGTS",
                "FGTS Valor",
                "Correção",
                "JAM",
                "Total",
            ]
        ]

        for item in grupo['items']:
            l = item['lancamento']
            c = item['calc']
            comp_label = item.get('competencia_display', item.get('competencia'))
            funcionario = l.funcionario
            comp_date = competencia_str_to_date(l.competencia)
            vinculo = funcionario.vinculos.filter(
                empresa=l.empresa,
                data_admissao__lte=comp_date,
            ).order_by('-data_admissao').first()
            if vinculo and vinculo.data_demissao and vinculo.data_demissao < comp_date:
                vinculo = None
            empresa_vinculo = vinculo.empresa.nome if vinculo else l.empresa.nome
            data_admissao = vinculo.data_admissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_admissao else ''
            data_demissao = vinculo.data_demissao.strftime('%d/%m/%Y') if vinculo and vinculo.data_demissao else ''
            table_data.append([
                comp_label,
                funcionario.nome,
                data_demissao,
                f"{l.base_fgts}",
                f"{c.get('valor_fgts', l.valor_fgts)}",
                f"{c['valor_corrigido']}",
                f"{c.get('valor_jam', Decimal('0.00'))}",
                f"{c.get('total') or (c.get('valor_deposito_fgts', Decimal('0.00')) + c.get('valor_jam', Decimal('0.00')))}",
            ])

        # Ajustar colWidths para caber em 170mm (A4 útil)
        # Ajustar colWidths para 9 colunas (sem empresa)
        # Ajustar colWidths para 8 colunas (sem admissão)
        table = Table(
            table_data,
            colWidths=[22*mm, 36*mm, 22*mm, 20*mm, 18*mm, 18*mm, 16*mm, 18*mm],
            hAlign='LEFT',
            repeatRows=1,
            splitByRow=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#333333')),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('ALIGN', (5, 1), (-1, -1), 'RIGHT'),
                    ('ALIGN', (0, 0), (4, -1), 'LEFT'),
                    ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cccccc')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fbfbfb')]),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]
            )
        )

        story.append(table)

    story.append(Spacer(1, 10))
    story.append(Paragraph("Totais", subtitle_style))
    total_recolher = (totais['valor_deposito_fgts'] + totais.get('valor_jam', Decimal('0'))).quantize(Decimal('0.01'))
    totais_table = Table(
        [
            [
                "Valor sem juros",
                "Correção",
                "Depósito (sem JAM)",
                "JAM",
                "Total a recolher",
            ],
            [
                f"{totais['valor_fgts']}",
                f"{totais['valor_corrigido']}",
                f"{totais['valor_deposito_fgts']}",
                f"{totais.get('valor_jam', Decimal('0.00'))}",
                f"{total_recolher}",
            ],
        ],
        colWidths=[28 * mm, 26 * mm, 34 * mm, 22 * mm, 32 * mm],
        hAlign='LEFT',
    )
    totais_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaeaea')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (0, 1), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cccccc')),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(totais_table)

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()

    resp = HttpResponse(content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="relatorio_fgts.pdf"'
    resp.write(pdf)
    return resp


def export_sefip(request):
    """Exporta arquivo SEFIP.RE seguindo a mesma lógica do sistema legado.

    Parâmetros via GET:
    - empresa: ID da empresa
    - competencia: MM/YYYY
    - funcionario_de: ID inicial do funcionário
    - funcionario_ate: ID final do funcionário
    """
    from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden

    empresa_id = request.GET.get('empresa')
    competencia = request.GET.get('competencia')
    func_de = request.GET.get('funcionario_de')
    func_ate = request.GET.get('funcionario_ate')

    if not all([empresa_id, competencia, func_de, func_ate]):
        return HttpResponseBadRequest('Parâmetros obrigatórios: empresa, competencia, funcionario_de, funcionario_ate')

    try:
        empresa = Empresa.objects.get(pk=empresa_id)
    except Empresa.DoesNotExist:
        return HttpResponseBadRequest('Empresa inválida')

    # Escopo multi-tenant: checar permissão da empresa
    if not is_empresa_allowed(request.user, empresa.codigo):
        return HttpResponseForbidden('Empresa não permitida para este usuário.')

    try:
        func_de_id = int(func_de)
        func_ate_id = int(func_ate)
    except ValueError:
        return HttpResponseBadRequest('IDs de funcionário inválidos')

    filtros = SefipFilters(
        empresa=empresa,
        competencia=competencia,
        funcionario_de=func_de_id,
        funcionario_ate=func_ate_id,
    )

    conteudo = gerar_sefip_conteudo(filtros)

    response = HttpResponse(conteudo, content_type='text/plain; charset=iso-8859-1')
    # Mesmo nome de arquivo do legado
    response['Content-Disposition'] = 'attachment; filename="SEFIP.RE"'
    return response


def download_memoria_calculo(request):
    """Gera e baixa a memória de cálculo em formato .txt"""
    from django.http import HttpResponse
    
    empresa_id = request.GET.get('empresa')
    funcionario_id = request.GET.get('funcionario')
    vinculo_id = request.GET.get('vinculo')
    competencia_str = request.GET.get('competencia')
    data_pagamento_str = request.GET.get('data_pagamento')
    
    if not all([empresa_id, funcionario_id, competencia_str, data_pagamento_str]):
        return HttpResponse('Parâmetros incompletos', status=400)
    
    empresa = Empresa.objects.get(pk=empresa_id)
    funcionario = Funcionario.objects.get(pk=funcionario_id)
    data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date()
    competencia_date = datetime.strptime(competencia_str, '%m/%Y').date().replace(day=1)
    
    # Busca o lançamento (vínculo-first para evitar ambiguidade)
    base_qs = Lancamento.objects.filter(
        empresa=empresa,
        funcionario=funcionario,
        competencia=competencia_str
    )
    if vinculo_id:
        base_qs = base_qs.filter(vinculo_id=vinculo_id)

    if not vinculo_id and base_qs.count() > 1:
        return HttpResponse('Lançamento ambíguo: informe o VÍNCULO (ID) ou MATRÍCULA para baixar a memória de cálculo.', status=400)

    lancamento = base_qs.first()
    
    if not lancamento:
        return HttpResponse('Lançamento não encontrado', status=404)
    
    # Busca índice
    indice_valor = IndiceFGTSService.buscar_indice(
        competencia=competencia_date,
        data_pagamento=data_pagamento
    )
    
    if indice_valor is None:
        indice_valor = Decimal('1.0')
    
    # Ajuste plano econômico legado (multiplica e divide conforme VB6)
    valor_fgts_ajustado, fator_mult, fator_div, fator_liquido = aplicar_plano_economico_legacy(
        lancamento.valor_fgts,
        competencia_date,
    )

    # JAM composto até a data de pagamento
    valor_jam, _detalhes_jam, meses_sem_coef = calcular_jam_ate_pagamento(
        valor_fgts=valor_fgts_ajustado,
        competencia=competencia_date,
        data_pagamento=data_pagamento,
    )

    # Calcula depósito correto e correção (Depósito - FGTS do mês)
    base_fgts = lancamento.base_fgts or valor_fgts_ajustado
    valor_deposito_fgts = (base_fgts * indice_valor).quantize(Decimal('0.01'))
    valor_corrigido = (valor_deposito_fgts - valor_fgts_ajustado).quantize(Decimal('0.01'))
    total = (valor_deposito_fgts + valor_jam).quantize(Decimal('0.01'))
    
    # Formata data de admissão para competência
    data_admissao_mes = funcionario.data_admissao.strftime('%m/%Y')
    
    # Gera memória de cálculo
    memoria = gerar_memoria_calculo(
        funcionario_nome=funcionario.nome,
        funcionario_cpf=funcionario.cpf,
        data_admissao=funcionario.data_admissao,
        valor_fgts=valor_fgts_ajustado,
        competencia_str=competencia_str,
        data_pagamento=data_pagamento,
        indice=indice_valor,
        valor_jam=valor_jam,
        valor_corrigido=valor_corrigido,
        total=total,
        data_admissao_mes=data_admissao_mes,
        salario_colaborador=lancamento.base_fgts,
        valor_deposito_fgts=valor_deposito_fgts,
        fator_plano_economico=fator_liquido,
        fator_plano_mult=fator_mult,
        fator_plano_div=fator_div,
    )
    
    # Retorna arquivo para download
    response = HttpResponse(memoria, content_type='text/plain; charset=utf-8')
    filename = f"memoria_calculo_{funcionario.nome.replace(' ', '_')}_{competencia_str.replace('/', '_')}.txt"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


class LancamentoDownloadTemplateView(LoginRequiredMixin, View):
    """View para download do template XLSX de importação de lançamentos"""
    
    def get(self, request):
        try:
            # Gerar arquivo template
            xlsx_bytes = LancamentoImportService.generate_template_xlsx()
            
            # Retornar como download
            response = HttpResponse(
                xlsx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = 'attachment; filename="template_lancamentos_fgts.xlsx"'
            return response
            
        except Exception as e:
            messages.error(request, f'❌ Erro ao gerar template: {str(e)}')
            return redirect('lancamento-list')


class LancamentoImportView(LoginRequiredMixin, EmpresaScopeMixin, View):
    """View para importação de lançamentos via XLSX"""
    template_name = 'lancamentos/lancamento_import.html'
    
    def get(self, request, *args, **kwargs):
        """Renderizar página de importação"""
        # Listar empresas permitidas
        empresa_ids = get_allowed_empresa_ids(request.user)
        empresas = Empresa.objects.filter(codigo__in=empresa_ids)
        
        context = {
            'empresas': empresas,
        }
        return render(request, self.template_name, context)
    
    def post(self, request, *args, **kwargs):
        # Validar arquivo
        if 'file' not in request.FILES:
            messages.error(request, '❌ Nenhum arquivo foi enviado.')
            return redirect('lancamento-import')
        
        file = request.FILES['file']
        
        # Validar extensão
        if not file.name.endswith('.xlsx'):
            messages.error(request, '❌ Apenas arquivos .xlsx são permitidos.')
            return redirect('lancamento-import')
        
        # Empresa selecionada é opcional quando o XLSX traz a coluna EMPRESA por linha.
        empresa = None
        empresa_codigo = request.POST.get('empresa')
        if empresa_codigo:
            try:
                empresa = Empresa.objects.get(codigo=empresa_codigo)
            except Empresa.DoesNotExist:
                messages.error(request, '❌ Empresa não encontrada.')
                return redirect('lancamento-import')

            # Validar permissões (quando empresa foi selecionada)
            if not is_empresa_allowed(request.user, empresa.codigo):
                return HttpResponseForbidden('Você não tem permissão para importar lançamentos para esta empresa.')
        
        # Processar importação
        try:
            result = LancamentoImportService.import_lancamentos_from_file(file, empresa, request.user)
            
            # Mensagens de sucesso
            if result['created'] > 0:
                messages.success(
                    request, 
                    f"✅ {result['created']} lançamento(s) criado(s) com sucesso!"
                )
            
            if result['updated'] > 0:
                messages.info(
                    request, 
                    f"ℹ️ {result['updated']} lançamento(s) atualizado(s)."
                )
            
            # Mensagens de erro
            if result['errors']:
                for error in result['errors'][:5]:  # Mostrar apenas os 5 primeiros
                    messages.error(
                        request,
                        f"❌ Linha {error['row']}: {error['error']}"
                    )
                
                if len(result['errors']) > 5:
                    messages.warning(
                        request,
                        f"⚠️ Mais {len(result['errors']) - 5} erro(s) encontrado(s). Verifique o arquivo."
                    )
            
            # Resumo
            if result['success'] > 0 or result['skipped'] > 0 or result['errors']:
                messages.success(
                    request,
                    f"📊 Resumo: {result['success']} sucesso(s), {len(result['errors'])} erro(s), {result['skipped']} pulado(s)"
                )
            
            # Se não houve nenhum sucesso, mas também não houve erros críticos
            if result['success'] == 0 and not result['errors']:
                messages.warning(
                    request,
                    "⚠️ Nenhum lançamento foi processado. Verifique se o arquivo contém dados válidos."
                )
            
            return redirect('lancamento-list')
            
        except ValueError as e:
            messages.error(request, f'❌ Erro de validação: {str(e)}')
            return redirect('lancamento-import')
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erro na importação de lançamentos: {str(e)}", exc_info=True)
            messages.error(request, f'❌ Erro inesperado ao importar: {str(e)}. Por favor, contate o suporte se o problema persistir.')
            return redirect('lancamento-import')


class LegacyImportView(LoginRequiredMixin, FormView):
    """View para importar dados históricos do sistema legado (VB6)"""
    form_class = LegacyImportForm
    template_name = 'lancamentos/legacy_import.html'
    success_url = reverse_lazy('legacy-import')
    
    def get_form_kwargs(self):
        """Passa o usuário ao formulário"""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        """Processa o arquivo CSV selecionado"""
        from .services.legacy_importer import LegacyDataImporter
        from django.core.files.storage import default_storage
        import tempfile
        import os
        
        try:
            # Obtém dados do formulário
            csv_file = form.cleaned_data['csv_file']
            import_type = form.cleaned_data['import_type']
            empresa = form.cleaned_data.get('empresa')
            skip_duplicates = form.cleaned_data.get('skip_duplicates', True)
            
            # Valida permissões de empresa
            if import_type in ['funcionarios', 'lancamentos'] and empresa:
                if not is_empresa_allowed(self.request.user, empresa.codigo):
                    messages.error(self.request, '❌ Você não tem permissão para importar dados nesta empresa.')
                    return self.form_invalid(form)
            
            # Salva arquivo temporário
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as tmp_file:
                for chunk in csv_file.chunks():
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name
            
            try:
                # Instancia o importador
                importer = LegacyDataImporter()
                
                # Processa a importação conforme o tipo
                registros_criados = 0
                erros = []
                avisos = []
                
                if import_type == 'empresas':
                    registros_criados, erros = importer.importar_empresas(tmp_path)
                
                elif import_type == 'funcionarios' and empresa:
                    registros_criados, erros = importer.importar_funcionarios(tmp_path, empresa_id=empresa.pk)
                
                elif import_type == 'lancamentos' and empresa:
                    registros_criados, erros = importer.importar_lancamentos(tmp_path, empresa_id=empresa.pk)
                
                # Obtém relatório completo
                relatorio = importer.relatorio()
                
                # Armazena relatório na sessão para exibição
                self.request.session['last_import_report'] = {
                    'import_type': import_type,
                    'linhas_processadas': relatorio.get('linhas_processadas', 0),
                    'registros_criados': registros_criados,
                    'registros_duplicados': relatorio.get('registros_duplicados', 0),
                    'erros': erros[:20],  # Limita a 20 erros para exibição
                    'avisos': relatorio.get('avisos', [])[:20],
                    'total_erros': len(erros),
                    'total_avisos': len(relatorio.get('avisos', [])),
                }
                
                # Mensagem de sucesso
                tipo_desc = {
                    'empresas': 'empresas',
                    'funcionarios': 'funcionários',
                    'lancamentos': 'lançamentos'
                }.get(import_type, 'registros')
                
                mensagem = f'✅ Importação de {tipo_desc} realizada com sucesso! '
                mensagem += f'{registros_criados} registros criados'
                
                if relatorio.get('registros_duplicados', 0) > 0:
                    mensagem += f', {relatorio.get("registros_duplicados")} duplicados ignorados'
                
                if erros:
                    mensagem += f', {len(erros)} erros'
                
                messages.success(self.request, mensagem + '.')
                
                # Redireciona para página de resultado
                return redirect('legacy-import-result')
            
            finally:
                # Remove arquivo temporário
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erro na importação legada: {str(e)}", exc_info=True)
            messages.error(self.request, f'❌ Erro ao processar importação: {str(e)}')
            return self.form_invalid(form)
    
    def get_context_data(self, **kwargs):
        """Adiciona dados do último relatório ao contexto"""
        context = super().get_context_data(**kwargs)
        context['last_import_report'] = self.request.session.get('last_import_report')
        context['page_title'] = 'Importar Dados Legados'
        context['page_description'] = 'Importe dados históricos do sistema legado (VB6) para o novo sistema'
        return context


class LegacyImportResultView(LoginRequiredMixin, View):
    """Exibe resultado detalhado da importação legada"""
    template_name = 'lancamentos/legacy_import_result.html'
    
    def get(self, request, *args, **kwargs):
        """Exibe o relatório da importação"""
        from django.shortcuts import render
        
        relatorio = request.session.get('last_import_report')
        
        if not relatorio:
            messages.warning(request, '⚠️ Nenhuma importação anterior encontrada.')
            return redirect('legacy-import')
        
        context = {
            'relatorio': relatorio,
            'page_title': 'Resultado da Importação',
            'success': len(relatorio.get('erros', [])) == 0,
        }
        
        return render(request, self.template_name, context)


# ===== CONFERÊNCIA DE LANÇAMENTOS =====

class ConferenciaListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    """Lista lançamentos para conferência"""
    model = ConferenciaLancamento
    template_name = 'lancamentos/conferencia_list.html'
    context_object_name = 'conferencias'
    paginate_by = 50
    
    def get_queryset(self):
        """Retorna conferências filtradas"""
        empresa_id = self.kwargs.get('empresa_id')
        empresa = get_object_or_404(Empresa, pk=empresa_id)
        
        # Verifica permissão
        if not is_empresa_allowed(self.request.user, empresa.codigo):
            return ConferenciaLancamento.objects.none()
        
        queryset = ConferenciaLancamento.objects.filter(
            lancamento__empresa=empresa
        ).select_related(
            'lancamento__funcionario',
            'lancamento__empresa',
            'conferido_por'
        ).order_by('-criado_em')
        
        # Filtros
        status_filtro = self.request.GET.get('status', 'PENDENTE')
        competencia = self.request.GET.get('competencia')
        funcionario_id = self.request.GET.get('funcionario')
        
        if status_filtro and status_filtro != 'TODOS':
            queryset = queryset.filter(status=status_filtro)
        
        if competencia:
            queryset = queryset.filter(lancamento__competencia=competencia)
        
        if funcionario_id:
            queryset = queryset.filter(lancamento__funcionario_id=funcionario_id)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa_id = self.kwargs.get('empresa_id')
        empresa = get_object_or_404(Empresa, pk=empresa_id)
        
        # Formulário de filtros
        context['filtro_form'] = FiltroConferenciaForm(
            self.request.GET or None,
            empresa=empresa
        )
        
        # Relatório de conferências
        competencia = self.request.GET.get('competencia')
        context['relatorio'] = ConferenciaLancamento.gerar_relatorio_conferencia(
            empresa,
            competencia
        )
        
        context['empresa'] = empresa
        context['competencia_filtro'] = competencia
        context['status_filtro'] = self.request.GET.get('status', 'PENDENTE')
        context['page_title'] = 'Conferência de Lançamentos'
        
        return context


class ConferenciaDetailView(LoginRequiredMixin, EmpresaScopeMixin, DetailView):
    """Exibe detalhes de uma conferência específica"""
    model = ConferenciaLancamento
    template_name = 'lancamentos/conferencia_detail.html'
    context_object_name = 'conferencia'
    pk_url_kwarg = 'conferencia_id'
    
    def get_object(self):
        obj = super().get_object()
        
        # Verifica permissão
        if not is_empresa_allowed(self.request.user, obj.lancamento.empresa.codigo):
            raise HttpResponseForbidden('Sem permissão para acessar esta conferência')
        
        return obj
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Conferência #{self.object.id}'
        context['lancamento'] = self.object.lancamento
        
        # Executar validações
        context['problemas'] = self.object._validar()
        
        return context


class ConferenciaConferirView(LoginRequiredMixin, EmpresaScopeMixin, FormView):
    """Formulário para conferir um lançamento"""
    template_name = 'lancamentos/conferencia_conferir.html'
    form_class = ConferenciaLancamentoForm
    
    def dispatch(self, request, *args, **kwargs):
        self.conferencia = get_object_or_404(
            ConferenciaLancamento,
            pk=kwargs.get('conferencia_id')
        )
        
        # Verifica permissão
        if not is_empresa_allowed(request.user, self.conferencia.lancamento.empresa.codigo):
            return HttpResponseForbidden('Sem permissão para conferir este lançamento')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['conferencia'] = self.conferencia
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['conferencia'] = self.conferencia
        context['lancamento'] = self.conferencia.lancamento
        context['page_title'] = 'Conferir Lançamento'
        
        # Executar validações
        context['problemas'] = self.conferencia._validar()
        
        return context
    
    def form_valid(self, form):
        valor_conferido = form.cleaned_data.get('valor_conferido')
        observacoes = form.cleaned_data.get('observacoes', '')
        
        # Conferir lançamento
        valido = self.conferencia.conferir(
            self.request.user,
            valor_conferido,
            observacoes
        )
        
        if valido:
            messages.success(
                self.request,
                f'✅ Lançamento conferido com sucesso! Status: CONFERIDO'
            )
        else:
            messages.warning(
                self.request,
                f'⚠️ Lançamento conferido COM PROBLEMAS. Revise as validações automáticas.'
            )
        
        return redirect('conferencia-list', empresa_id=self.conferencia.lancamento.empresa_id)
    
    def get_success_url(self):
        return reverse_lazy(
            'conferencia-list',
            kwargs={'empresa_id': self.conferencia.lancamento.empresa_id}
        )


class ConferenciaRejeitarView(LoginRequiredMixin, EmpresaScopeMixin, FormView):
    """Formulário para rejeitar um lançamento"""
    template_name = 'lancamentos/conferencia_rejeitar.html'
    form_class = RejeicaoLancamentoForm
    
    def dispatch(self, request, *args, **kwargs):
        self.conferencia = get_object_or_404(
            ConferenciaLancamento,
            pk=kwargs.get('conferencia_id')
        )
        
        # Verifica permissão
        if not is_empresa_allowed(request.user, self.conferencia.lancamento.empresa.codigo):
            return HttpResponseForbidden('Sem permissão para rejeitar este lançamento')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['conferencia'] = self.conferencia
        context['lancamento'] = self.conferencia.lancamento
        context['page_title'] = 'Rejeitar Lançamento'
        return context
    
    def form_valid(self, form):
        motivo_padrao = form.cleaned_data.get('motivo_padrao')
        motivo_detalhado = form.cleaned_data.get('motivo_detalhado')
        
        # Monta motivo completo
        motivos_dict = dict(RejeicaoLancamentoForm.MOTIVOS_REJEICAO)
        motivo_completo = f"{motivos_dict[motivo_padrao]}: {motivo_detalhado}"
        
        # Rejeita lançamento
        self.conferencia.rejeitar(self.request.user, motivo_completo)
        
        messages.error(
            self.request,
            f'❌ Lançamento rejeitado. Motivo: {motivos_dict[motivo_padrao]}'
        )
        
        return redirect('conferencia-list', empresa_id=self.conferencia.lancamento.empresa_id)
    
    def get_success_url(self):
        return reverse_lazy(
            'conferencia-list',
            kwargs={'empresa_id': self.conferencia.lancamento.empresa_id}
        )


class ConferenciaRelatorioView(LoginRequiredMixin, EmpresaScopeMixin, View):
    """Exibe relatório consolidado de conferências"""
    template_name = 'lancamentos/conferencia_relatorio.html'
    
    def get(self, request, empresa_id):
        empresa = get_object_or_404(Empresa, pk=empresa_id)
        
        # Verifica permissão
        if not is_empresa_allowed(request.user, empresa.codigo):
            return HttpResponseForbidden('Sem permissão para acessar este relatório')
        
        competencia = request.GET.get('competencia')
        
        # Relatório geral
        relatorio = ConferenciaLancamento.gerar_relatorio_conferencia(empresa, competencia)
        
        # Detalhes por status
        conferencias_por_status = {
            'PENDENTE': ConferenciaLancamento.objects.filter(
                lancamento__empresa=empresa,
                status='PENDENTE'
            ).select_related('lancamento__funcionario'),
            'CONFERIDO': ConferenciaLancamento.objects.filter(
                lancamento__empresa=empresa,
                status='CONFERIDO'
            ).select_related('lancamento__funcionario', 'conferido_por'),
            'PROBLEMA': ConferenciaLancamento.objects.filter(
                lancamento__empresa=empresa,
                status='PROBLEMA'
            ).select_related('lancamento__funcionario', 'conferido_por'),
            'REJEITADO': ConferenciaLancamento.objects.filter(
                lancamento__empresa=empresa,
                status='REJEITADO'
            ).select_related('lancamento__funcionario', 'conferido_por'),
        }
        
        if competencia:
            for status, qs in conferencias_por_status.items():
                conferencias_por_status[status] = qs.filter(
                    lancamento__competencia=competencia
                )
        
        # Verificar se pode consolidar
        pode_consolidar, msg_consolidacao = False, ''
        if competencia:
            pode_consolidar, msg_consolidacao = ConferenciaLancamento.pode_consolidar_competencia(
                empresa,
                competencia
            )
        
        context = {
            'empresa': empresa,
            'competencia': competencia,
            'relatorio': relatorio,
            'conferencias_por_status': conferencias_por_status,
            'pode_consolidar': pode_consolidar,
            'msg_consolidacao': msg_consolidacao,
            'page_title': 'Relatório de Conferências',
        }
        
        return render(request, self.template_name, context)


# Create your views here.
