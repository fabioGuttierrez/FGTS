from datetime import datetime, date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import FormView, CreateView, UpdateView, ListView, View
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from billing.models import BillingCustomer
from empresas.models import Empresa
from coefjam.models import CoefJam
from .models import Lancamento
from .forms import RelatorioCompetenciaForm, LancamentoForm
from .services.calculo import (
    calcular_fgts_atualizado,
    calcular_jam_composto,
    calcular_jam_periodo,
    gerar_memoria_calculo,
    get_config_numeric,
    get_config_str,
)
from .services.importacao import LancamentoImportService
from .services.sefip_export import gerar_sefip_conteudo, SefipFilters
from django.conf import settings
from indices.services.indice_service import IndiceFGTSService
from funcionarios.models import Funcionario
from fgtsweb.mixins import get_allowed_empresa_ids, is_empresa_allowed, EmpresaScopeMixin
from django.http import HttpResponseForbidden, HttpResponse


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
        messages.success(self.request, f'✅ Lançamento para {lancamento.funcionario.nome} ({lancamento.competencia}) registrado com sucesso!')
        return super().form_valid(form)


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
        messages.success(self.request, f'✅ Lançamento para {lancamento.funcionario.nome} ({lancamento.competencia}) atualizado com sucesso!')
        return super().form_valid(form)


class LancamentoListView(LoginRequiredMixin, EmpresaScopeMixin, ListView):
    """Listar lançamentos cadastrados"""
    model = Lancamento
    template_name = 'lancamentos/lancamento_list.html'
    context_object_name = 'lancamentos'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related('empresa', 'funcionario')
        
        # Filtra apenas lançamentos de empresas permitidas
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            qs = qs.filter(empresa__codigo__in=allowed_ids)
        
        # Aplicar filtros
        competencia = self.request.GET.get('competencia', '').strip()
        funcionario_id = self.request.GET.get('funcionario', '').strip()
        empresa_id = self.request.GET.get('empresa', '').strip()
        status_pagto = self.request.GET.get('status_pagto', '').strip()
        
        if competencia:
            qs = qs.filter(competencia=competencia)
        
        if funcionario_id:
            qs = qs.filter(funcionario_id=funcionario_id)
        
        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        
        if status_pagto in ['pago', 'nao_pago']:
            qs = qs.filter(pago=(status_pagto == 'pago'))
        
        # Aplicar ordenação
        ordem = self.request.GET.get('ordem', '-competencia').strip()
        if ordem == 'competencia_asc':
            qs = qs.order_by('competencia')
        elif ordem == 'competencia_desc':
            qs = qs.order_by('-competencia')
        elif ordem == 'funcionario_asc':
            qs = qs.order_by('funcionario__nome')
        elif ordem == 'funcionario_desc':
            qs = qs.order_by('-funcionario__nome')
        else:
            qs = qs.order_by('-competencia')
        
        return qs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Adicionar empresas e funcionários permitidos para o filtro
        allowed_ids = get_allowed_empresa_ids(self.request.user)
        if allowed_ids is not None:
            context['empresas'] = Empresa.objects.filter(codigo__in=allowed_ids)
            context['funcionarios'] = Funcionario.objects.filter(empresa__codigo__in=allowed_ids).order_by('nome')
        else:
            context['empresas'] = Empresa.objects.all()
            context['funcionarios'] = Funcionario.objects.all().order_by('nome')
        
        # Passar parâmetros de filtro para o template
        context['competencia_filtro'] = self.request.GET.get('competencia', '')
        context['funcionario_filtro'] = self.request.GET.get('funcionario', '')
        context['empresa_filtro'] = self.request.GET.get('empresa', '')
        context['status_pagto_filtro'] = self.request.GET.get('status_pagto', '')
        context['ordem_filtro'] = self.request.GET.get('ordem', '-competencia')
        
        # Construir um dicionário com a última competência de cada funcionário
        # e marcar quais lançamentos são a última competência
        ultimas_competencias = {}
        lancamentos_list = context.get('lancamentos', [])
        
        for lancamento in lancamentos_list:
            func_id = lancamento.funcionario.id
            if func_id not in ultimas_competencias:
                # Buscar a última competência deste funcionário
                ultimo = Lancamento.objects.filter(
                    funcionario_id=func_id
                ).order_by('-competencia').first()
                if ultimo:
                    ultimas_competencias[func_id] = ultimo.competencia
        
        # Adicionar flag is_ultima_competencia a cada lançamento
        for lancamento in lancamentos_list:
            func_id = lancamento.funcionario.id
            lancamento.is_ultima_competencia = (
                func_id in ultimas_competencias and 
                lancamento.competencia == ultimas_competencias[func_id]
            )
        
        return context


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
            
            if lancamentos_criados > 0:
                messages.success(
                    request, 
                    f'✅ {lancamentos_criados} lançamento(s) gerado(s) automaticamente para {funcionario.nome}!'
                )
            else:
                messages.info(
                    request,
                    f'ℹ️ Todos os lançamentos de {funcionario.nome} já estão cadastrados até hoje.'
                )
            
        except Funcionario.DoesNotExist:
            messages.error(request, '❌ Funcionário não encontrado.')
        except Exception as e:
            messages.error(request, f'❌ Erro ao gerar lançamentos: {str(e)}')
        
        return redirect('lancamento-list')


class RelatorioCompetenciaView(LoginRequiredMixin, FormView):
    template_name = 'lancamentos/relatorio_competencia.html'
    form_class = RelatorioCompetenciaForm
    success_url = reverse_lazy('relatorio-competencia')
    
    # Configurações de proteção contra loops
    MAX_ITERACOES_POR_COMPETENCIA = 10  # Máximo de vezes que a mesma competência pode ser reprocessada
    TIMEOUT_GLOBAL_SEGUNDOS = 60  # Timeout total de 60 segundos
    
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

    def _agrupar_resultados(self, resultados, agrupamento):
        """Agrupa resultados por competência, ano ou funcionário"""
        from collections import defaultdict
        
        grupos = defaultdict(lambda: {
            'items': [],
            'totais': {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}
        })
        
        for resultado in resultados:
            lancamento = resultado['lancamento']
            calc = resultado['calc']
            competencia = resultado['competencia']
            
            # Determinar chave do grupo
            if agrupamento == 'ano':
                # Extrair ano da competência (MM/YYYY)
                ano = competencia.split('/')[-1] if '/' in competencia else competencia
                chave = ano
                label = f"Ano {ano}"
            elif agrupamento == 'funcionario':
                chave = lancamento.funcionario.pk
                label = f"{lancamento.funcionario.nome} - {lancamento.funcionario.cpf}"
            else:  # competencia
                chave = competencia
                label = competencia
            
            grupos[chave]['label'] = label
            grupos[chave]['items'].append(resultado)
            
            # Acumular totais do grupo
            for k in ['valor_corrigido', 'valor_jam', 'total']:
                if k in calc:
                    grupos[chave]['totais'][k] += calc[k]
        
        # Ordenar grupos
        if agrupamento == 'ano':
            grupos_ordenados = sorted(grupos.items(), key=lambda x: x[0])
        elif agrupamento == 'competencia':
            # Ordenar por data (MM/YYYY)
            def parse_comp_key(key):
                try:
                    return datetime.strptime(key, '%m/%Y').date()
                except:
                    return datetime(1900, 1, 1).date()
            grupos_ordenados = sorted(grupos.items(), key=lambda x: parse_comp_key(x[0]))
        else:  # funcionario
            # Ordenar por label (nome do funcionário)
            grupos_ordenados = sorted(grupos.items(), key=lambda x: grupos[x[0]]['label'])
        
        return grupos_ordenados

    def _compute_for(self, empresa, competencia_str, data_pagamento, funcionario=None, jam_state=None):
        if jam_state is None:
            jam_state = {}
        avisos = []
        
        # 🛡️ Verificar se há loop infinito
        try:
            self._verificar_loop(competencia_str)
        except Exception as e:
            return None, None, str(e), jam_state, avisos
        
        try:
            competencia_date = datetime.strptime(competencia_str, '%m/%Y').date().replace(day=1)
        except ValueError:
            return None, None, 'Competência inválida. Use MM/YYYY.', jam_state, avisos

        lancs_qs = (Lancamento.objects
                .filter(empresa=empresa, competencia=competencia_str, pago=False)  # APENAS NÃO PAGOS
                .select_related('funcionario')
                .order_by('funcionario_id'))
        if funcionario:
            lancs_qs = lancs_qs.filter(funcionario=funcionario)
        
        # ⚡ Se não há lançamentos para esta competência, pular silenciosamente
        if not lancs_qs.exists():
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
            # ⚠️ AVISO: Índice não encontrado, pular a competência mas notificar o usuário
            aviso = f"⚠️ Nenhum índice FGTS encontrado para competência {competencia_str}. Competência foi pulada."
            avisos.append(aviso)
            return [], {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}, None, jam_state, avisos

        juros_tipo = get_config_str('JUROS_TIPO', 'MENSAL')
        juros_mensal = get_config_numeric('JUROS_MENSAL_PERCENT', Decimal('0.5'))
        juros_diario = get_config_numeric('JUROS_DIARIO_PERCENT', Decimal('0.033'))
        multa_percent = get_config_numeric('MULTA_PERCENT', Decimal('10.0'))

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}

        # Buscar coeficiente JAM para esta competência
        from coefjam.models import CoefJam
        jam_coef_obj = CoefJam.objects.filter(competencia=competencia_str).first()
        jam_coef = jam_coef_obj.valor if jam_coef_obj else Decimal('0')
        
        # Se não há coeficiente JAM, registrar aviso
        if not jam_coef_obj:
            avisos.append(f"⚠️ Coeficiente JAM não encontrado para competência {competencia_str}. Usando JAM=0.")

        for l in lancs_qs:
            funcionario_key = f"func_{l.funcionario.pk}"
            
            # Inicializar estado do funcionário se não existir
            if funcionario_key not in jam_state:
                # Verificar se esta é a competência de admissão
                competencia_admissao = date(l.funcionario.data_admissao.year, l.funcionario.data_admissao.month, 1)
                is_primeira_competencia = (competencia_date == competencia_admissao)
                
                jam_state[funcionario_key] = {
                    'acumulado': Decimal('0.00'),
                    'primeira_comp': is_primeira_competencia
                }
            
            # Calcular JAM
            if jam_state[funcionario_key]['primeira_comp']:
                # Primeira competência: JAM = 0
                valor_jam = Decimal('0.00')
                jam_state[funcionario_key]['primeira_comp'] = False
            else:
                # Competências seguintes: JAM = Acumulado × Coeficiente
                acumulado_anterior = jam_state[funcionario_key]['acumulado']
                valor_jam = (acumulado_anterior * jam_coef).quantize(Decimal('0.01'))
            
            # Atualizar acumulado para próxima competência
            # Acumulado_Novo = Acumulado_Anterior + JAM + Valor_FGTS
            jam_state[funcionario_key]['acumulado'] = (
                jam_state[funcionario_key]['acumulado'] + 
                valor_jam + 
                l.valor_fgts
            )

            calc = calcular_fgts_atualizado(
                valor_fgts=l.valor_fgts,
                competencia=competencia_date,
                pagamento=data_pagamento,
                indice=indice_valor,
                jam_coef=None,
                valor_jam_override=valor_jam,
                juros_tipo=juros_tipo,
                juros_mensal=juros_mensal,
                juros_diario=juros_diario,
                multa_percent=multa_percent,
            )
            resultados.append({'lancamento': l, 'calc': calc, 'competencia': competencia_str})
            for k in totais.keys():
                if k in calc:
                    totais[k] += calc[k]

        return resultados, totais, None, jam_state, avisos

    def form_valid(self, form):
        import logging
        logger = logging.getLogger(__name__)
        
        # Reset contadores de loop para cada nova requisição
        self.tempo_inicio = None
        self.competencias_processadas = {}
        
        try:
            empresa = form.cleaned_data['empresa']
            competencia_str = (form.cleaned_data.get('competencia') or '').strip()
            competencias_multi = (form.cleaned_data.get('competencias') or '').strip()
            funcionario = form.cleaned_data.get('funcionario')
            agrupamento = form.cleaned_data.get('agrupamento', 'competencia')
            data_pagamento = form.cleaned_data['data_pagamento'] or date.today()

            # Escopo multi-tenant: empresa deve estar autorizada
            if not is_empresa_allowed(self.request.user, empresa.codigo):
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': 'Empresa não permitida para este usuário.'
                })

            resultados = []
            totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}
            avisos_total = []  # Coletar todos os avisos

            # Determinar lista de competências a processar
            if competencias_multi:
                # Múltiplas competências manualmente informadas
                competencias_list = [c.strip() for c in competencias_multi.splitlines() if c.strip()]
            elif competencia_str:
                # Única competência informada
                competencias_list = [competencia_str]
            else:
                # NENHUMA competência informada: buscar TODAS em aberto (não pagas)
                lancamentos_qs = Lancamento.objects.filter(
                    empresa=empresa,
                    pago=False
                )
                if funcionario:
                    lancamentos_qs = lancamentos_qs.filter(funcionario=funcionario)
                
                competencias_list = list(
                    lancamentos_qs.values_list('competencia', flat=True)
                    .distinct()
                    .order_by('competencia')
                )
                
                if not competencias_list:
                    return render(self.request, self.template_name, {
                        'form': form,
                        'erro': 'Nenhum lançamento em aberto encontrado. Verifique se existem lançamentos com status "Não Pago".'
                    })

            # Ordena competências cronologicamente para respeitar o acumulado do JAM legado
            def _parse_comp(c: str):
                try:
                    return datetime.strptime(c, '%m/%Y').date()
                except Exception:
                    return None

            # Filtrar competências inválidas e preparar lista de erros
            competencias_invalidas = [c for c in competencias_list if _parse_comp(c) is None]
            competencias_list = [c for c in competencias_list if _parse_comp(c) is not None]
            competencias_list.sort(key=_parse_comp)

            if not competencias_list:
                erro_msg = 'Nenhuma competência válida encontrada.'
                if competencias_invalidas:
                    erro_msg += f' Competências inválidas: {", ".join(competencias_invalidas[:5])}'
                return render(self.request, self.template_name, {'form': form, 'erro': erro_msg})

            jam_state = {}
            for comp in competencias_list:
                res, tot, err, jam_state, avisos = self._compute_for(empresa, comp, data_pagamento, funcionario, jam_state)
                if err:
                    return render(self.request, self.template_name, {'form': form, 'erro': err})
                # Coletar avisos
                if avisos:
                    avisos_total.extend(avisos)
                if res:
                    resultados.extend(res)
                    # ⚠️ NÃO SOMAR AQUI - os subtotais serão calculados na agregação
            
            if not resultados:
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': 'Nenhum lançamento encontrado com os filtros aplicados. Verifique se há lançamentos com status "Não Pago" para as competências selecionadas.'
                })

            # Aplicar agrupamento
            resultados_agrupados = self._agrupar_resultados(resultados, agrupamento)
            
            # ✅ CORRIGIR: Recalcular totais gerais a partir dos grupos (evitar duplicação)
            totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}
            for chave, grupo_data in resultados_agrupados:
                for k in totais.keys():
                    totais[k] += grupo_data['totais'][k]

            contexto = {
                'form': form,
                'empresa': empresa,
                'competencias': competencias_list,
                'data_pagamento': data_pagamento,
                'resultados': resultados,
                'resultados_agrupados': resultados_agrupados,
                'agrupamento': agrupamento,
                'totais': totais,
                'avisos': avisos_total,  # Adicionar avisos ao contexto
            }
            return render(self.request, self.template_name, contexto)
            
        except Exception as e:
            logger.error(f"🛑 Erro em RelatorioCompetenciaView.form_valid: {str(e)}")
            return render(self.request, self.template_name, {
                'form': form,
                'erro': f"🛑 Erro ao processar relatório: {str(e)}"
            })

def export_relatorio_competencia_csv(request):
    from django.http import HttpResponse
    empresa_id = request.GET.get('empresa')
    competencias_multi = request.GET.get('competencias', '')
    funcionario_id = request.GET.get('funcionario')
    data_pagamento_str = request.GET.get('data_pagamento')

    empresa = Empresa.objects.get(pk=empresa_id)
    data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date() if data_pagamento_str else date.today()
    funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

    view = RelatorioCompetenciaView()
    competencias_list = [c.strip() for c in competencias_multi.splitlines() if c.strip()]

    def _parse_comp(c: str):
        try:
            return datetime.strptime(c, '%m/%Y').date()
        except Exception:
            return None

    competencias_list = [c for c in competencias_list if _parse_comp(c) is not None]
    competencias_list.sort(key=_parse_comp)

    # Mesma ordenação cronológica para manter JAM composto coerente
    def _parse_comp(c: str):
        try:
            return datetime.strptime(c, '%m/%Y').date()
        except Exception:
            return None

    competencias_list = [c for c in competencias_list if _parse_comp(c) is not None]
    competencias_list.sort(key=_parse_comp)

    rows = []
    totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'valor_juros', 'valor_multa', 'total']}
    jam_state = {}
    for comp in competencias_list:
        res, tot, err, jam_state = view._compute_for(empresa, comp, data_pagamento, funcionario, jam_state)
        if err:
            continue
        for item in res:
            l = item['lancamento']
            c = item['calc']
            rows.append([
                empresa.nome,
                comp,
                l.funcionario.nome,
                f"{l.base_fgts}",
                f"{c['valor_corrigido']}",
                f"{c['valor_jam']}",
                f"{c.get('valor_juros', Decimal('0'))}",
                f"{c.get('valor_multa', Decimal('0'))}",
                f"{c['total']}",
            ])
        for k in totais.keys():
            totais[k] += tot[k]

    import csv
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="relatorio_fgts.csv"'
    writer = csv.writer(resp, delimiter=';')
    writer.writerow(['Empresa', 'Competência', 'Funcionário', 'Base FGTS', 'Corrigido', 'JAM', 'Juros', 'Multa', 'Total'])
    for r in rows:
        writer.writerow(r)
    writer.writerow(['Totais', '', '', '', totais['valor_corrigido'], totais['valor_jam'], totais['valor_juros'], totais['valor_multa'], totais['total']])
    return resp

def export_relatorio_competencia_pdf(request):
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    empresa_id = request.GET.get('empresa')
    competencias_multi = request.GET.get('competencias', '')
    funcionario_id = request.GET.get('funcionario')
    data_pagamento_str = request.GET.get('data_pagamento')

    empresa = Empresa.objects.get(pk=empresa_id)
    data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date() if data_pagamento_str else date.today()
    funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

    view = RelatorioCompetenciaView()
    competencias_list = [c.strip() for c in competencias_multi.splitlines() if c.strip()]

    resp = HttpResponse(content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="relatorio_fgts.pdf"'
    p = canvas.Canvas(resp, pagesize=A4)
    width, height = A4
    y = height - 50
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, f"Relatório FGTS — {empresa.nome}")
    y -= 20
    p.setFont("Helvetica", 10)
    p.drawString(40, y, f"Pagamento: {data_pagamento.strftime('%d/%m/%Y')}")
    y -= 30

    totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'valor_juros', 'valor_multa', 'total']}
    jam_state = {}
    for comp in competencias_list:
        res, tot, err, jam_state = view._compute_for(empresa, comp, data_pagamento, funcionario, jam_state)
        if err:
            continue
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, f"Competência: {comp}")
        y -= 18
        p.setFont("Helvetica", 9)
        for item in res:
            l = item['lancamento']; c = item['calc']
            line = f"{l.funcionario.nome} — Base: {l.base_fgts} | Corrigido: {c['valor_corrigido']} | JAM: {c['valor_jam']} | Juros: {c.get('valor_juros', Decimal('0'))} | Multa: {c.get('valor_multa', Decimal('0'))} | Total: {c['total']}"
            p.drawString(40, y, line)
            y -= 14
            if y < 80:
                p.showPage(); y = height - 50
        for k in totais.keys():
            totais[k] += tot[k]
        y -= 10

    p.setFont("Helvetica-Bold", 11)
    p.drawString(40, y, f"Totais — Corrigido: {totais['valor_corrigido']} | JAM: {totais['valor_jam']} | Juros: {totais['valor_juros']} | Multa: {totais['valor_multa']} | Total: {totais['total']}")
    p.showPage()
    p.save()
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
    competencia_str = request.GET.get('competencia')
    data_pagamento_str = request.GET.get('data_pagamento')
    
    if not all([empresa_id, funcionario_id, competencia_str, data_pagamento_str]):
        return HttpResponse('Parâmetros incompletos', status=400)
    
    empresa = Empresa.objects.get(pk=empresa_id)
    funcionario = Funcionario.objects.get(pk=funcionario_id)
    data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date()
    competencia_date = datetime.strptime(competencia_str, '%m/%Y').date().replace(day=1)
    
    # Busca o lançamento
    lancamento = Lancamento.objects.filter(
        empresa=empresa,
        funcionario=funcionario,
        competencia=competencia_str
    ).first()
    
    if not lancamento:
        return HttpResponse('Lançamento não encontrado', status=404)
    
    # Busca índice
    indice_valor = IndiceFGTSService.buscar_indice(
        competencia=competencia_date,
        data_pagamento=data_pagamento
    )
    
    if indice_valor is None:
        indice_valor = Decimal('1.0')
    
    # Calcula JAM
    valor_jam = calcular_jam_periodo(
        lancamento.valor_fgts,
        competencia_date,
        data_pagamento,
        funcionario.data_admissao
    )
    
    # Calcula valores
    valor_corrigido = (lancamento.valor_fgts * indice_valor).quantize(Decimal('0.01'))
    total = (valor_corrigido + valor_jam).quantize(Decimal('0.01'))
    
    # Formata data de admissão para competência
    data_admissao_mes = funcionario.data_admissao.strftime('%m/%Y')
    
    # Gera memória de cálculo
    memoria = gerar_memoria_calculo(
        funcionario_nome=funcionario.nome,
        funcionario_cpf=funcionario.cpf,
        data_admissao=funcionario.data_admissao,
        valor_fgts=lancamento.valor_fgts,
        competencia_str=competencia_str,
        data_pagamento=data_pagamento,
        indice=indice_valor,
        valor_jam=valor_jam,
        valor_corrigido=valor_corrigido,
        total=total,
        data_admissao_mes=data_admissao_mes
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
        
        # Validar empresa selecionada
        empresa_codigo = request.POST.get('empresa')
        if not empresa_codigo:
            messages.error(request, '❌ Selecione uma empresa.')
            return redirect('lancamento-import')
        
        try:
            empresa = Empresa.objects.get(codigo=empresa_codigo)
        except Empresa.DoesNotExist:
            messages.error(request, '❌ Empresa não encontrada.')
            return redirect('lancamento-import')
        
        # Validar permissões
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
            if result['success'] > 0:
                messages.success(
                    request,
                    f"📊 Resumo: {result['success']} sucesso(s), {len(result['errors'])} erro(s), {result['skipped']} pulado(s)"
                )
            
            return redirect('lancamento-list')
            
        except ValueError as e:
            messages.error(request, f'❌ {str(e)}')
            return redirect('lancamento-import')
        except Exception as e:
            messages.error(request, f'❌ Erro inesperado: {str(e)}')
            return redirect('lancamento-import')


# Create your views here.
