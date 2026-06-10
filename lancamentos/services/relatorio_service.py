"""
Serviço de processamento assíncrono de relatórios FGTS.

Reaplica a lógica de RelatorioCompetenciaView._compute_for em background thread,
serializa os resultados e os armazena em RelatorioTask.resultado_json.
"""
import logging
import time
from datetime import date, datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Proxy classes: mimetizam ORM objects para reusar o template sem alterações
# ---------------------------------------------------------------------------

class _VinculoProxy:
    def __init__(self, d):
        self.pk = d.get('vinculo_id')
        self.id = d.get('vinculo_id')
        self.empresa_id = d.get('empresa_id')
        self.matricula = d.get('vinculo_matricula') or ''
        raw_dem = d.get('vinculo_data_demissao')
        self.data_demissao = date.fromisoformat(raw_dem) if raw_dem else None
        raw_adm = d.get('vinculo_data_admissao')
        self.data_admissao = date.fromisoformat(raw_adm) if raw_adm else None


class _VinculosManager:
    """Mimics funcionario.vinculos queryset manager."""
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FuncionarioProxy:
    def __init__(self, d):
        self.pk = d['funcionario_id']
        self.nome = d['funcionario_nome']
        self.cpf = d.get('funcionario_cpf', '')
        self.pis = d.get('funcionario_pis', '')
        vinculo_proxy = _VinculoProxy(d) if d.get('vinculo_id') else None
        self.vinculos = _VinculosManager([vinculo_proxy] if vinculo_proxy else [])


class _EmpresaProxy:
    def __init__(self, d):
        self.pk = d['empresa_id']
        self.nome = d['empresa_nome']
        self.codigo = d.get('empresa_codigo', '')


class _LancamentoProxy:
    def __init__(self, d):
        self.pk = d['id']
        self.id = d['id']
        self.funcionario_id = d['funcionario_id']
        self.funcionario = _FuncionarioProxy(d)
        self.vinculo_id = d.get('vinculo_id')
        self.vinculo = _VinculoProxy(d) if d.get('vinculo_id') else None
        self.empresa_id = d['empresa_id']
        self.empresa = _EmpresaProxy(d)
        self.base_fgts = Decimal(d['base_fgts']) if d.get('base_fgts') else None
        self.valor_fgts = Decimal(d['valor_fgts'])
        self.parcela_13 = d.get('parcela_13')
        self.competencia = d.get('competencia', '')


# ---------------------------------------------------------------------------
# Serialização / Desserialização de resultados
# ---------------------------------------------------------------------------

def _serialize_item(item):
    """Converte um resultado de _compute_for em dict serializável para JSON."""
    l = item['lancamento']
    calc = item['calc']

    def _vinculo_fields(vinculo):
        if not vinculo:
            return {}
        return {
            'vinculo_matricula': getattr(vinculo, 'matricula', None),
            'vinculo_data_demissao': vinculo.data_demissao.isoformat() if getattr(vinculo, 'data_demissao', None) else None,
            'vinculo_data_admissao': vinculo.data_admissao.isoformat() if getattr(vinculo, 'data_admissao', None) else None,
        }

    def _safe_decimal(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return v

    return {
        'lancamento_data': {
            'id': l.pk,
            'funcionario_id': l.funcionario_id,
            'funcionario_nome': l.funcionario.nome,
            'funcionario_cpf': getattr(l.funcionario, 'cpf', ''),
            'funcionario_pis': getattr(l.funcionario, 'pis', ''),
            'vinculo_id': l.vinculo_id,
            'empresa_id': l.empresa_id,
            'empresa_nome': l.empresa.nome,
            'empresa_codigo': getattr(l.empresa, 'codigo', ''),
            'base_fgts': str(l.base_fgts) if l.base_fgts is not None else None,
            'valor_fgts': str(l.valor_fgts),
            'parcela_13': l.parcela_13,
            'competencia': l.competencia,
            **_vinculo_fields(l.vinculo),
        },
        'calc': {k: _safe_decimal(v) for k, v in calc.items()},
        'competencia': item['competencia'],
        'parcela_13': item['parcela_13'],
        'competencia_display': item['competencia_display'],
    }


def _deserialize_item(d):
    """Reconstrói um resultado de relatorio a partir de dict JSON."""
    ld = d['lancamento_data']
    calc_raw = d['calc']

    def _to_decimal(v):
        try:
            return Decimal(str(v))
        except Exception:
            return v

    calc = {k: _to_decimal(v) for k, v in calc_raw.items()}
    return {
        'lancamento': _LancamentoProxy(ld),
        'calc': calc,
        'competencia': d['competencia'],
        'parcela_13': d['parcela_13'],
        'competencia_display': d['competencia_display'],
    }


def deserializar_resultado(resultado_json, agrupamento_override=None):
    """Reconstituí o contexto completo a partir de resultado_json armazenado."""
    if not resultado_json:
        return {}

    from empresas.models import Empresa
    from funcionarios.models import Funcionario

    empresa = Empresa.objects.filter(pk=resultado_json['empresa_id']).first()
    funcionario = None
    if resultado_json.get('funcionario_id'):
        funcionario = Funcionario.objects.filter(pk=resultado_json['funcionario_id']).first()

    resultados = [_deserialize_item(d) for d in resultado_json.get('resultados_serializados', [])]

    from lancamentos.views import RelatorioCompetenciaView
    view = RelatorioCompetenciaView()
    agrupamento = agrupamento_override or resultado_json.get('agrupamento', 'competencia')
    resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)

    totais_raw = resultado_json.get('totais', {})
    totais = {k: Decimal(str(v)) for k, v in totais_raw.items()}

    data_pag_str = resultado_json.get('data_pagamento', '')
    data_pagamento = date.fromisoformat(data_pag_str) if data_pag_str else date.today()

    return {
        'empresa': empresa,
        'funcionario': funcionario,
        'matricula': resultado_json.get('matricula') or None,
        'competencias': resultado_json.get('competencias', []),
        'competencias_param': resultado_json.get('competencias_param', []),
        'competencia_primeira': resultado_json.get('competencia_primeira', ''),
        'data_pagamento': data_pagamento,
        'resultados': resultados,
        'resultados_agrupados': resultados_agrupados,
        'agrupamento': agrupamento,
        'totais': totais,
        'avisos': resultado_json.get('avisos', []),
        'kpi_inicio': resultado_json.get('kpi_inicio', ''),
        'kpi_fim': resultado_json.get('kpi_fim', ''),
        'kpi_tempo': resultado_json.get('kpi_tempo', ''),
        'kpi_lancamentos': resultado_json.get('kpi_lancamentos', 0),
        'kpi_competencias': resultado_json.get('kpi_competencias', 0),
        'exibir_indice': False,
        'exibir_jam': True,
        'exibir_correcao': True,
        'from_task': True,
        'from_selection': resultado_json.get('from_selection', False),
        'ids_param': resultado_json.get('ids_param', ''),
    }


# ---------------------------------------------------------------------------
# Processamento em background
# ---------------------------------------------------------------------------

def processar_relatorio(task_id: int) -> None:
    """Executado em daemon thread. Processa o relatório e salva em RelatorioTask."""
    from django.db import connection
    task = None
    try:
        from lancamentos.models_relatorio import RelatorioTask
        task = RelatorioTask.objects.get(pk=task_id)
        task.status = 'processing'
        task.save(update_fields=['status', 'atualizado_em'])

        params = task.parametros_json
        empresa_id = params['empresa_id']
        funcionario_id = params.get('funcionario_id')
        matricula = params.get('matricula') or None
        competencias_list = params['competencias_list']
        agrupamento = params.get('agrupamento', 'competencia')
        data_pagamento = date.fromisoformat(params['data_pagamento'])

        from empresas.models import Empresa
        from funcionarios.models import Funcionario
        from lancamentos.views import RelatorioCompetenciaView
        from lancamentos.services.calculo import get_config_str, get_config_numeric

        empresa = Empresa.objects.get(pk=empresa_id)
        funcionario = Funcionario.objects.get(pk=funcionario_id) if funcionario_id else None

        config_juros = {
            'juros_tipo': get_config_str('JUROS_TIPO', 'MENSAL'),
            'juros_mensal': get_config_numeric('JUROS_MENSAL_PERCENT', Decimal('0.5')),
            'juros_diario': get_config_numeric('JUROS_DIARIO_PERCENT', Decimal('0.033')),
            'multa_percent': get_config_numeric('MULTA_PERCENT', Decimal('10.0')),
        }

        view = RelatorioCompetenciaView()
        jam_state = {}
        resultados = []
        avisos_total = []
        total_lancamentos = 0
        inicio_timestamp = time.time()
        inicio_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

        for comp_data in competencias_list:
            comp = comp_data['competencia']
            parc = comp_data.get('parcela_13')
            res, tot, err, jam_state, avisos = view._compute_for(
                empresa, comp, parc, data_pagamento,
                funcionario, matricula, jam_state,
            )
            if err:
                comp_display = f"{comp} (13º {parc})" if parc else comp
                avisos_total.append(f"⚠️ Competência {comp_display} pulada: {err}")
                continue
            if avisos:
                avisos_total.extend(avisos)
            if res:
                resultados.extend(res)
                total_lancamentos += len(res)

        fim_timestamp = time.time()
        fim_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        tempo_total = fim_timestamp - inicio_timestamp

        # Reagrupar para calcular totais corretos
        resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)
        totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
        for _, grupo_data in resultados_agrupados:
            for k in totais:
                totais[k] += grupo_data['totais'][k]

        avisos_unicos = list(dict.fromkeys(avisos_total))

        def _fmt_comp_display(comp, parcela_13):
            if parcela_13 == 1:
                return f"{comp} (13º 1ª)"
            if parcela_13 == 2:
                return f"{comp} (13º 2ª)"
            return comp

        resultado_json = {
            'empresa_id': empresa.pk,
            'empresa_nome': empresa.nome,
            'empresa_codigo': getattr(empresa, 'codigo', ''),
            'funcionario_id': funcionario.pk if funcionario else None,
            'funcionario_nome': funcionario.nome if funcionario else None,
            'matricula': matricula or '',
            'competencias': params.get('competencias_display', [_fmt_comp_display(c['competencia'], c.get('parcela_13')) for c in competencias_list]),
            'competencias_param': params.get('competencias_param', []),
            'competencia_primeira': params.get('competencia_primeira', ''),
            'agrupamento': agrupamento,
            'data_pagamento': data_pagamento.isoformat(),
            'avisos': avisos_unicos,
            'kpi_inicio': inicio_str,
            'kpi_fim': fim_str,
            'kpi_tempo': f'{tempo_total:.2f} segundos',
            'kpi_lancamentos': total_lancamentos,
            'kpi_competencias': len(competencias_list),
            'totais': {k: str(v) for k, v in totais.items()},
            'resultados_serializados': [_serialize_item(r) for r in resultados],
        }

        task.resultado_json = resultado_json
        task.total_lancamentos = total_lancamentos
        task.status = 'done'
        task.save(update_fields=['resultado_json', 'total_lancamentos', 'status', 'atualizado_em'])

    except Exception as exc:
        logger.exception(f'[RelatorioTask #{task_id}] Erro inesperado: {exc}')
        if task:
            try:
                task.status = 'error'
                task.mensagem_erro = str(exc)
                task.save(update_fields=['status', 'mensagem_erro', 'atualizado_em'])
            except Exception:
                pass
    finally:
        try:
            connection.close()
        except Exception:
            pass


def processar_relatorio_por_ids(task_id: int) -> None:
    """Executado em daemon thread. Processa relatório a partir de lista de IDs."""
    import re
    from collections import defaultdict
    from django.db import connection
    task = None
    try:
        from lancamentos.models_relatorio import RelatorioTask
        task = RelatorioTask.objects.get(pk=task_id)
        task.status = 'processing'
        task.save(update_fields=['status', 'atualizado_em'])

        params = task.parametros_json
        ids = params['ids']
        agrupamento = params.get('agrupamento', 'competencia')

        from lancamentos.models import Lancamento
        from indices.services.indice_service import IndiceFGTSService
        from lancamentos.views import RelatorioCompetenciaView

        lancamentos = (
            Lancamento.objects
            .filter(id__in=ids, pago=False)
            .select_related('empresa', 'funcionario', 'vinculo')
            .prefetch_related('funcionario__vinculos')
        )

        data_pagamento = IndiceFGTSService.obter_ultima_data_base() or date.today()
        view = RelatorioCompetenciaView()

        # Filtrar por vínculo ativo na competência (replica lógica da view síncrona)
        lancamentos_filtrados = []
        empresa = None
        for lanc in lancamentos:
            if empresa is None:
                empresa = lanc.empresa
            competencia = lanc.competencia
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
                empresa_id = getattr(lanc.empresa, 'id', None) or getattr(lanc.empresa, 'codigo', None)
                for v in vinculos.all():
                    if str(v.empresa_id) == str(empresa_id) and v.is_ativo_em_competencia(competencia_norm):
                        vinculo_ativo = True
                        break

            if (vinculo_ativo or not vinculos):
                lancamentos_filtrados.append(lanc)

        ids_set = {l.id for l in lancamentos_filtrados}
        grupos = defaultdict(list)
        for lanc in lancamentos_filtrados:
            comp_norm = view.normalizar_competencia(lanc.competencia)
            key = (lanc.empresa_id, comp_norm, lanc.parcela_13 or 0)
            grupos[key].append(lanc)

        resultados = []
        avisos_total = []
        jam_state = {}
        inicio_timestamp = time.time()
        inicio_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

        for (empresa_id, comp_norm, parcela_13), _lancs in grupos.items():
            empresa_grupo = _lancs[0].empresa
            res, _tot, err, jam_state, avisos = view._compute_for(
                empresa_grupo, comp_norm, parcela_13, data_pagamento,
                funcionario=None, matricula=None, jam_state=jam_state,
            )
            if avisos:
                avisos_total.extend(avisos)
            if err:
                continue
            res_filtrados = [r for r in res if r.get('lancamento') and r['lancamento'].id in ids_set]
            resultados.extend(res_filtrados)

        fim_timestamp = time.time()
        fim_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        tempo_total = fim_timestamp - inicio_timestamp

        resultados_agrupados = view._agrupar_resultados(resultados, agrupamento)
        totais = {k: Decimal('0') for k in ['valor_fgts', 'valor_corrigido', 'valor_jam', 'valor_deposito_fgts', 'total']}
        for _, grupo_data in resultados_agrupados:
            for k in totais:
                totais[k] += grupo_data['totais'][k]

        def _fmt_comp_display(comp, parcela_13):
            if parcela_13 == 1:
                return f"{comp} (13º 1ª)"
            if parcela_13 == 2:
                return f"{comp} (13º 2ª)"
            return comp

        competencias_display = [_fmt_comp_display(k[1], k[2]) for k in grupos.keys()]
        competencias_param = [f"{k[1]}|{k[2] or ''}" for k in grupos.keys()]
        avisos_unicos = list(dict.fromkeys(avisos_total))
        total_lancamentos = len(resultados)

        resultado_json = {
            'empresa_id': empresa.pk if empresa else None,
            'empresa_nome': empresa.nome if empresa else '',
            'empresa_codigo': getattr(empresa, 'codigo', '') if empresa else '',
            'funcionario_id': None,
            'funcionario_nome': None,
            'matricula': '',
            'competencias': competencias_display,
            'competencias_param': competencias_param,
            'competencia_primeira': competencias_display[0] if competencias_display else '',
            'agrupamento': agrupamento,
            'data_pagamento': data_pagamento.isoformat(),
            'avisos': avisos_unicos,
            'kpi_inicio': inicio_str,
            'kpi_fim': fim_str,
            'kpi_tempo': f'{tempo_total:.2f} segundos',
            'kpi_lancamentos': total_lancamentos,
            'kpi_competencias': len(grupos),
            'totais': {k: str(v) for k, v in totais.items()},
            'resultados_serializados': [_serialize_item(r) for r in resultados],
            'from_selection': True,
            'ids_param': ','.join(str(i) for i in ids),
        }

        task.resultado_json = resultado_json
        task.total_lancamentos = total_lancamentos
        task.status = 'done'
        task.save(update_fields=['resultado_json', 'total_lancamentos', 'status', 'atualizado_em'])

    except Exception as exc:
        logger.exception(f'[RelatorioTask #{task_id}] Erro inesperado (por_ids): {exc}')
        if task:
            try:
                task.status = 'error'
                task.mensagem_erro = str(exc)
                task.save(update_fields=['status', 'mensagem_erro', 'atualizado_em'])
            except Exception:
                pass
    finally:
        try:
            connection.close()
        except Exception:
            pass
