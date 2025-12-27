from datetime import datetime, date
from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import FormView
from django.shortcuts import render
from django.urls import reverse_lazy
from billing.models import BillingCustomer
from empresas.models import Empresa
from indices.models import Indice, SupabaseIndice
from coefjam.models import CoefJam
from .models import Lancamento
from .forms import RelatorioCompetenciaForm
from .services.calculo import calcular_fgts_atualizado, get_config_numeric, get_config_str
from django.conf import settings
from indices.services.supabase_client import fetch_indices_range
from funcionarios.models import Funcionario


class RelatorioCompetenciaView(LoginRequiredMixin, FormView):
    template_name = 'lancamentos/relatorio_competencia.html'
    form_class = RelatorioCompetenciaForm
    success_url = reverse_lazy('relatorio-competencia')

    def _compute_for(self, empresa, competencia_str, data_pagamento, funcionario=None):
        try:
            competencia_date = datetime.strptime(competencia_str, '%m/%Y').date().replace(day=1)
        except ValueError:
            return None, None, 'Competência inválida. Use MM/YYYY.'

        lancs_qs = (Lancamento.objects
                    .filter(empresa=empresa, competencia=competencia_str)
                    .select_related('funcionario'))
        if funcionario:
            lancs_qs = lancs_qs.filter(funcionario=funcionario)

        # Usar Supabase como fonte de verdade: ORM (Postgres) ou REST; fallback para Indice local
        indices_list = []
        try:
            indices_qs = SupabaseIndice.objects.filter(data_base__gte=competencia_date, data_base__lt=data_pagamento)
            indices_list = [(i.data_base, i.indice) for i in indices_qs]
        except Exception:
            indices_list = []

        if not indices_list and getattr(settings, 'SUPABASE_API_URL', None) and getattr(settings, 'SUPABASE_API_KEY', None):
            indices_list = fetch_indices_range(competencia_date, data_pagamento)

        if not indices_list:
            indices_qs = Indice.objects.filter(data_indice__gte=competencia_date, data_indice__lt=data_pagamento)
            indices_list = [(i.data_indice, i.valor) for i in indices_qs]
        jam = CoefJam.objects.filter(competencia=competencia_str).first()
        jam_coef = jam.valor if jam else Decimal('0')

        juros_tipo = get_config_str('JUROS_TIPO', 'MENSAL')
        juros_mensal = get_config_numeric('JUROS_MENSAL_PERCENT', Decimal('0.5'))
        juros_diario = get_config_numeric('JUROS_DIARIO_PERCENT', Decimal('0.033'))
        multa_percent = get_config_numeric('MULTA_PERCENT', Decimal('10.0'))

        resultados = []
        totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'total']}
        for l in lancs_qs:
            calc = calcular_fgts_atualizado(
                valor_fgts=l.valor_fgts,
                competencia=competencia_date,
                pagamento=data_pagamento,
                indices=indices_list,
                jam_coef=jam_coef,
                juros_tipo=juros_tipo,
                juros_mensal=juros_mensal,
                juros_diario=juros_diario,
                multa_percent=multa_percent,
            )
            resultados.append({'lancamento': l, 'calc': calc, 'competencia': competencia_str})
            for k in totais.keys():
                if k in calc:
                    totais[k] += calc[k]

        return resultados, totais, None

    def form_valid(self, form):
        empresa = form.cleaned_data['empresa']
        competencia_str = form.cleaned_data.get('competencia')
        competencias_multi = form.cleaned_data.get('competencias')
        funcionario = form.cleaned_data.get('funcionario')
        data_pagamento = form.cleaned_data['data_pagamento'] or date.today()

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

        if not competencias_list:
            return render(self.request, self.template_name, {'form': form, 'erro': 'Informe ao menos uma competência.'})

        for comp in competencias_list:
            res, tot, err = self._compute_for(empresa, comp, data_pagamento, funcionario)
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

    rows = []
    totais = {k: Decimal('0') for k in ['valor_corrigido', 'valor_jam', 'valor_juros', 'valor_multa', 'total']}
    for comp in competencias_list:
        res, tot, err = view._compute_for(empresa, comp, data_pagamento, funcionario)
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
                f"{c['valor_juros']}",
                f"{c['valor_multa']}",
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
    for comp in competencias_list:
        res, tot, err = view._compute_for(empresa, comp, data_pagamento, funcionario)
        if err:
            continue
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, f"Competência: {comp}")
        y -= 18
        p.setFont("Helvetica", 9)
        for item in res:
            l = item['lancamento']; c = item['calc']
            line = f"{l.funcionario.nome} — Base: {l.base_fgts} | Corrigido: {c['valor_corrigido']} | JAM: {c['valor_jam']} | Juros: {c['valor_juros']} | Multa: {c['valor_multa']} | Total: {c['total']}"
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
from django.shortcuts import render

# Create your views here.
