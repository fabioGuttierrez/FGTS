from datetime import datetime, date
from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import FormView
from django.shortcuts import render
from django.urls import reverse_lazy
from billing.models import BillingCustomer
from empresas.models import Empresa
from coefjam.models import CoefJam
from .models import Lancamento
from .forms import RelatorioCompetenciaForm
from .services.calculo import (
    calcular_fgts_atualizado,
    calcular_jam_composto,
    calcular_jam_periodo,
    gerar_memoria_calculo,
    get_config_numeric,
    get_config_str,
)
from django.conf import settings
from indices.services.indice_service import IndiceFGTSService
from funcionarios.models import Funcionario
from fgtsweb.mixins import get_allowed_empresa_ids, is_empresa_allowed


class RelatorioCompetenciaView(LoginRequiredMixin, FormView):
    template_name = 'lancamentos/relatorio_competencia.html'
    form_class = RelatorioCompetenciaForm
    success_url = reverse_lazy('relatorio-competencia')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def _compute_for(self, empresa, competencia_str, data_pagamento, funcionario=None, jam_state=None):
        if jam_state is None:
            jam_state = {}
        try:
            competencia_date = datetime.strptime(competencia_str, '%m/%Y').date().replace(day=1)
        except ValueError:
            return None, None, 'Competência inválida. Use MM/YYYY.'

        lancs_qs = (Lancamento.objects
                .filter(empresa=empresa, competencia=competencia_str)
                .select_related('funcionario')
                .order_by('funcionario_id'))
        if funcionario:
            lancs_qs = lancs_qs.filter(funcionario=funcionario)

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
            erro_msg = (
                f'Índice FGTS não encontrado para competência {competencia_str} '
                f'e data de pagamento {data_pagamento.strftime("%d/%m/%Y")}. '
                f'Verifique se o índice está cadastrado na tabela indices_fgts.'
            )
            return None, None, erro_msg

        juros_tipo = get_config_str('JUROS_TIPO', 'MENSAL')
        juros_mensal = get_config_numeric('JUROS_MENSAL_PERCENT', Decimal('0.5'))
        juros_diario = get_config_numeric('JUROS_DIARIO_PERCENT', Decimal('0.033'))
        multa_percent = get_config_numeric('MULTA_PERCENT', Decimal('10.0'))

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}

        for l in lancs_qs:
            # JAM OFICIAL: Calcula para cada mês entre competência e data pagamento
            # Mas a primeira competência da admissão sempre tem JAM zerado
            valor_jam = calcular_jam_periodo(
                l.valor_fgts, 
                competencia_date, 
                data_pagamento,
                l.funcionario.data_admissao
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

        return resultados, totais, None, jam_state

    def form_valid(self, form):
        empresa = form.cleaned_data['empresa']
        competencia_str = form.cleaned_data.get('competencia')
        competencias_multi = form.cleaned_data.get('competencias')
        funcionario = form.cleaned_data.get('funcionario')
        data_pagamento = form.cleaned_data['data_pagamento'] or date.today()

        # Escopo multi-tenant: empresa deve estar autorizada
        if not is_empresa_allowed(self.request.user, empresa.codigo):
            return render(self.request, self.template_name, {
                'form': form,
                'erro': 'Empresa não permitida para este usuário.'
            })

        # Bloqueio: apenas empresas com assinatura ativa
        try:
            bc = BillingCustomer.objects.get(empresa=empresa)
            if bc.status != 'active':
                return render(self.request, self.template_name, {
                    'form': form,
                    'erro': 'Empresa sem assinatura ativa. Assine para visualizar cálculos.'
                })
        except BillingCustomer.DoesNotExist:
            return render(self.request, self.template_name, {
                'form': form,
                'erro': 'Empresa sem assinatura. Assine para visualizar cálculos.'
            })

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}

        if competencias_multi:
            competencias_list = [c.strip() for c in competencias_multi.splitlines() if c.strip()]
        else:
            competencias_list = [competencia_str] if competencia_str else []

        # Ordena competências cronologicamente para respeitar o acumulado do JAM legado
        def _parse_comp(c: str):
            try:
                return datetime.strptime(c, '%m/%Y').date()
            except Exception:
                return None

        competencias_list = [c for c in competencias_list if _parse_comp(c) is not None]
        competencias_list.sort(key=_parse_comp)

        if not competencias_list:
            return render(self.request, self.template_name, {'form': form, 'erro': 'Informe ao menos uma competência.'})

        jam_state = {}
        for comp in competencias_list:
            res, tot, err, jam_state = self._compute_for(empresa, comp, data_pagamento, funcionario, jam_state)
            if err:
                return render(self.request, self.template_name, {'form': form, 'erro': err})
            resultados.extend(res)
            for k in totais.keys():
                totais[k] += tot[k]

        contexto = {
            'form': form,
            'empresa': empresa,
            'competencias': competencias_list,
            'data_pagamento': data_pagamento,
            'resultados': resultados,
            'totais': totais,
        }
        return render(self.request, self.template_name, contexto)

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

# Create your views here.
