from datetime import datetime, date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import FormView, CreateView, UpdateView, ListView, View, DetailView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from billing.models import BillingCustomer
from empresas.models import Empresa
from coefjam.models import CoefJam
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

    def _agrupar_resultados(self, resultados, agrupamento):
        """Agrupa resultados por competência, ano ou funcionário"""
        from collections import defaultdict
        
        grupos = defaultdict(lambda: {
            'items': [],
            'totais': {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}
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
            else:  # competencia
                chave = f"{competencia_raw}|{parcela_13}"
                label = competencia_label
            
            grupos[chave]['label'] = label
            grupos[chave]['items'].append(resultado)
            
            # Acumular totais do grupo
            for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']:
                if k in calc:
                    grupos[chave]['totais'][k] += calc[k]
        
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
        else:  # funcionario
            grupos_ordenados = sorted(grupos.items(), key=lambda x: grupos[x[0]]['label'])
        
        return grupos_ordenados

    def _compute_for(self, empresa, competencia_str, parcela_13, data_pagamento, funcionario=None, jam_state=None):
        if jam_state is None:
            jam_state = {}
        avisos = []
        
        # 🛡️ Verificar se há loop infinito
        try:
            loop_key = competencia_str if parcela_13 is None else f"{competencia_str}|{parcela_13}"
            self._verificar_loop(loop_key)
        except Exception as e:
            return None, None, str(e), jam_state, avisos
        
        try:
            competencia_date = datetime.strptime(competencia_str, '%m/%Y').date().replace(day=1)
        except ValueError:
            return None, None, 'Competência inválida. Use MM/YYYY.', jam_state, avisos

        # Buscar lançamentos pela competência armazenada como string 'MM/YYYY'
        # O modelo `Lancamento.competencia` é CharField, então devemos filtrar por `competencia_str`
        lancs_qs = (Lancamento.objects
            .filter(empresa=empresa, competencia=competencia_str, parcela_13=parcela_13, pago=False)
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
        totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}

        # Buscar coeficiente JAM para esta competência (campo é string MM/YYYY)
        from coefjam.models import CoefJam
        jam_coef_obj = CoefJam.objects.filter(competencia=competencia_str).first()
        jam_coef = jam_coef_obj.valor if jam_coef_obj else Decimal('0')
        
        # Se não há coeficiente JAM, registrar aviso
        if not jam_coef_obj:
            avisos.append(f"⚠️ Coeficiente JAM não encontrado para competência {competencia_str}. Usando JAM=0.")

        comp_display = competencia_str
        if parcela_13 == 1:
            comp_display = f"{competencia_str} (13º 1ª)"
        elif parcela_13 == 2:
            comp_display = f"{competencia_str} (13º 2ª)"

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
            resultados.append({
                'lancamento': l,
                'calc': calc,
                'competencia': competencia_str,
                'parcela_13': parcela_13,
                'competencia_display': comp_display,
            })
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
            totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}
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
                lancamentos_qs = Lancamento.objects.filter(
                    empresa=empresa,
                    pago=False
                )
                if funcionario:
                    lancamentos_qs = lancamentos_qs.filter(funcionario=funcionario)

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
                try:
                    return datetime.strptime(c, '%m/%Y').date()
                except Exception:
                    return None

            competencias_invalidas = [c['competencia'] for c in competencias_list if _parse_comp(c['competencia']) is None]
            competencias_list = [c for c in competencias_list if _parse_comp(c['competencia']) is not None]
            competencias_list.sort(key=lambda x: (_parse_comp(x['competencia']) or date(1900, 1, 1), x.get('parcela_13') or 0))

            # Limitar quantidade para evitar timeouts
            if len(competencias_list) > self.MAX_COMPETENCIAS:
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': f'Limite máximo de {self.MAX_COMPETENCIAS} competências por solicitação. Reduza a lista e tente novamente.'
                })

            if not competencias_list:
                erro_msg = 'Nenhuma competência válida encontrada.'
                if competencias_invalidas:
                    erro_msg += f' Competências inválidas: {", ".join(competencias_invalidas[:5])}'
                return render(self.request, self.template_name, {'form': form, 'erro': erro_msg})

            jam_state = {}
            for comp_data in competencias_list:
                comp = comp_data['competencia']
                parc = comp_data.get('parcela_13')
                res, tot, err, jam_state, avisos = self._compute_for(empresa, comp, parc, data_pagamento, funcionario, jam_state)
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
            totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}
            for chave, grupo_data in resultados_agrupados:
                for k in totais.keys():
                    totais[k] += grupo_data['totais'][k]

            competencias_display = [format_comp_display(c['competencia'], c.get('parcela_13')) for c in competencias_list]
            competencias_param = [f"{c['competencia']}|{c.get('parcela_13') or ''}" for c in competencias_list]
            competencia_primeira = competencias_list[0]['competencia'] if competencias_list else ''

            contexto = {
                'form': form,
                'empresa': empresa,
                'competencias': competencias_display,
                'competencias_param': competencias_param,
                'competencia_primeira': competencia_primeira,
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

def relatorio_por_ids(request):
    """Gera relatório a partir dos IDs de lançamentos selecionados"""
    from django.http import HttpResponse
    from django.shortcuts import render
    
    ids_str = request.GET.get('ids', '')
    if not ids_str:
        return HttpResponse('Nenhum lançamento selecionado.', status=400)
    
    try:
        ids = [int(id_str.strip()) for id_str in ids_str.split(',') if id_str.strip()]
    except ValueError:
        return HttpResponse('IDs inválidos.', status=400)
    
    if not ids:
        return HttpResponse('Nenhum lançamento selecionado.', status=400)
    
    # Buscar lançamentos pelos IDs
    lancamentos = Lancamento.objects.filter(id__in=ids).select_related('empresa', 'funcionario')
    
    if not lancamentos.exists():
        return HttpResponse('Nenhum lançamento encontrado.', status=404)
    
    # Verificar permissões multi-tenant
    allowed_ids = get_allowed_empresa_ids(request.user)
    if allowed_ids is not None:
        lancamentos = lancamentos.filter(empresa__codigo__in=allowed_ids)
        if not lancamentos.exists():
            return HttpResponse('Você não tem permissão para acessar esses lançamentos.', status=403)
    
    # Agrupar por empresa e competência
    from collections import defaultdict
    grupos = defaultdict(lambda: {'competencia': None, 'parcela_13': None, 'lancamentos': []})
    empresa = None
    
    for lanc in lancamentos:
        if empresa is None:
            empresa = lanc.empresa
        key = f"{lanc.competencia}|{lanc.parcela_13 or 0}"
        grupos[key]['competencia'] = lanc.competencia
        grupos[key]['parcela_13'] = lanc.parcela_13
        grupos[key]['lancamentos'].append(lanc)
    
    # Usar data de hoje como padrão para cálculo
    data_pagamento = date.today()
    
    # Preparar competências para processamento
    competencias_list = [
        {'competencia': g['competencia'], 'parcela_13': g['parcela_13']}
        for g in grupos.values()
    ]
    
    # Ordenar por competência
    def _parse_comp(c_dict):
        try:
            comp_str = c_dict['competencia']
            return datetime.strptime(comp_str, '%m/%Y').date()
        except Exception:
            return date(1900, 1, 1)
    
    competencias_list.sort(key=lambda x: (_parse_comp(x), x.get('parcela_13') or 0))
    
    # Calcular relatório usando a mesma lógica da view principal
    view = RelatorioCompetenciaView()
    view.request = request
    
    resultados = []
    totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}
    jam_state = {}
    avisos_total = []
    
    for comp_data in competencias_list:
        comp = comp_data['competencia']
        parc = comp_data.get('parcela_13')
        
        res, tot, err, jam_state, avisos = view._compute_for(empresa, comp, parc, data_pagamento, None, jam_state)
        if err:
            avisos_total.append(f"Erro ao processar {comp}: {err}")
            continue
        
        if avisos:
            avisos_total.extend(avisos)
        
        if res:
            resultados.extend(res)
            for k in totais.keys():
                if k in tot:
                    totais[k] += tot[k]
    
    if not resultados:
        return HttpResponse('Nenhum resultado calculado para os lançamentos selecionados.', status=404)
    
    # Aplicar agrupamento padrão por competência
    resultados_agrupados = view._agrupar_resultados(resultados, 'competencia')
    
    competencias_display = [f"{c['competencia']}" + (f" (13º {c['parcela_13']}ª)" if c.get('parcela_13') else "") 
                           for c in competencias_list]
    
    contexto = {
        'empresa': empresa,
        'competencias': competencias_display,
        'data_pagamento': data_pagamento,
        'resultados': resultados,
        'resultados_agrupados': resultados_agrupados,
        'agrupamento': 'competencia',
        'totais': totais,
        'avisos': avisos_total,
        'from_selection': True,
    }
    
    return render(request, 'lancamentos/relatorio_competencia.html', contexto)

def export_relatorio_competencia_csv(request):
    from django.http import HttpResponse
    import urllib.parse
    
    empresa_id = request.GET.get('empresa')
    competencias_multi = request.GET.get('competencias', '')
    funcionario_id = request.GET.get('funcionario')
    data_pagamento_str = request.GET.get('data_pagamento')
    agrupamento = request.GET.get('agrupamento', 'competencia')

    # Decodificar competências que podem vir URL-encoded
    competencias_multi = urllib.parse.unquote(competencias_multi)

    empresa = Empresa.objects.get(pk=empresa_id)
    data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date() if data_pagamento_str else date.today()
    funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

    view = RelatorioCompetenciaView()
    view.request = request
    
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
        competencias_list.append({'competencia': comp_str, 'parcela_13': parc_val})
    
    # Se não houver competências especificadas, buscar todas em aberto
    if not competencias_list:
        lancamentos_qs = Lancamento.objects.filter(empresa=empresa, pago=False)
        if funcionario:
            lancamentos_qs = lancamentos_qs.filter(funcionario=funcionario)
        
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
    totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}
    jam_state = {}
    
    for comp_dict in competencias_list:
        comp = comp_dict['competencia']
        parcela_13 = comp_dict.get('parcela_13')
        
        res, tot, err, jam_state, _avisos = view._compute_for(empresa, comp, parcela_13, data_pagamento, funcionario, jam_state)
        if err:
            continue
        
        resultados.extend(res)
        
        for k in totais.keys():
            totais[k] += tot.get(k, Decimal('0'))

    if not resultados:
        resp = HttpResponse('Nenhum lançamento encontrado para os filtros aplicados.', status=404)
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
    
    writer.writerow(['Empresa', 'Competência', 'Funcionário', 'FGTS Valor', 'Índice', 'Correção', 'JAM', 'Total'])
    
    for _chave, grupo in resultados_agrupados:
        writer.writerow([])
        writer.writerow([_grupo_label(grupo.get('label'))])
        
        for item in grupo['items']:
            l = item['lancamento']
            c = item['calc']
            comp_out = item.get('competencia_display', item.get('competencia'))
            writer.writerow([
                empresa.nome,
                comp_out,
                l.funcionario.nome,
                f"{c.get('valor_fgts', l.valor_fgts)}",
                f"{c.get('indice', '')}",
                f"{c['valor_corrigido']}",
                f"{c['valor_jam']}",
                f"{c['total']}",
            ])
    
    writer.writerow([])
    writer.writerow(['Totais', '', '', totais['valor_fgts'], '', totais['valor_corrigido'], totais['valor_jam'], totais['total']])
    return resp

def export_relatorio_competencia_pdf(request):
    from django.http import HttpResponse
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    import urllib.parse
    
    empresa_id = request.GET.get('empresa')
    competencias_multi = request.GET.get('competencias', '')
    funcionario_id = request.GET.get('funcionario')
    data_pagamento_str = request.GET.get('data_pagamento')
    agrupamento = request.GET.get('agrupamento', 'competencia')

    # Decodificar competências que podem vir URL-encoded com %0A para \n
    competencias_multi = urllib.parse.unquote(competencias_multi)

    empresa = Empresa.objects.get(pk=empresa_id)
    data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d').date() if data_pagamento_str else date.today()
    funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

    view = RelatorioCompetenciaView()
    view.request = request  # Necessário para EmpresaScopeMixin
    
    # Parse competências como dicionários com parcela_13
    # Separar por \n ou %0A (pode vir URL-encoded)
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
        competencias_list.append({'competencia': comp_str, 'parcela_13': parc_val})
    
    # Se não houver competências especificadas, buscar todas em aberto
    if not competencias_list:
        lancamentos_qs = Lancamento.objects.filter(empresa=empresa, pago=False)
        if funcionario:
            lancamentos_qs = lancamentos_qs.filter(funcionario=funcionario)
        
        # Extrair competências únicas com parcela_13
        competencias_unicas = (
            lancamentos_qs.values('competencia', 'parcela_13')
            .distinct()
            .order_by('competencia', 'parcela_13')
        )
        competencias_list = [
            {'competencia': item['competencia'], 'parcela_13': item['parcela_13']}
            for item in competencias_unicas
        ]

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
    totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'total']}
    jam_state = {}

    for comp_dict in competencias_list:
        comp = comp_dict['competencia']
        parcela_13 = comp_dict.get('parcela_13')

        res, tot, err, jam_state, _avisos = view._compute_for(empresa, comp, parcela_13, data_pagamento, funcionario, jam_state)

        if err or not res:
            continue

        resultados.extend(res)

        for k in totais.keys():
            totais[k] += tot.get(k, Decimal('0'))

    if not resultados:
        resp = HttpResponse('Nenhum lançamento encontrado para os filtros aplicados.', status=404)
        resp['Content-Type'] = 'text/plain; charset=utf-8'
        return resp

    resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)

    def _grupo_label(label):
        if agrupamento == 'funcionario':
            return f"Funcionário: {label}"
        if agrupamento == 'ano':
            return f"{label}"
        return f"Competência: {label}"

    for _chave, grupo in resultados_agrupados:
        story.append(Spacer(1, 6))
        story.append(Paragraph(_grupo_label(grupo.get('label')), subtitle_style))

        table_data = [
            [
                "Competência",
                "Funcionário",
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
            table_data.append([
                comp_label,
                l.funcionario.nome,
                f"{c.get('valor_fgts', l.valor_fgts)}",
                f"{c['valor_corrigido']}",
                f"{c['valor_jam']}",
                f"{c['total']}",
            ])

        table = Table(
            table_data,
            # Larguras ajustadas para caber em A4 com margens de 20mm (largura útil ~170mm)
            colWidths=[24 * mm, 42 * mm, 24 * mm, 20 * mm, 18 * mm, 24 * mm],
            hAlign='LEFT',
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#333333')),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
                    ('ALIGN', (0, 0), (1, -1), 'LEFT'),
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
    totais_table = Table(
        [
            [
                "Valor sem juros",
                "Correção",
                "JAM",
                "Valor com juros",
            ],
            [
                f"{totais['valor_fgts']}",
                f"{totais['valor_corrigido']}",
                f"{totais['valor_jam']}",
                f"{totais['total']}",
            ],
        ],
        colWidths=[35 * mm, 30 * mm, 25 * mm, 35 * mm],
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
                    registros_criados, erros = importer.importar_funcionarios(tmp_path, empresa_id=empresa.id)
                
                elif import_type == 'lancamentos' and empresa:
                    registros_criados, erros = importer.importar_lancamentos(tmp_path, empresa_id=empresa.id)
                
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
