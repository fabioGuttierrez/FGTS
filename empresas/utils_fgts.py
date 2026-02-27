from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from .models_relatorio import RelatorioPremium
from .models import EmailLog

def gerar_pdf_fgts(memoria, email):
    # Validação dos campos obrigatórios
    obrigatorios = [
        'competencia', 'data_pagamento', 'base_fgts', 'fgts_mes', 'indice',
        'deposito_fgts', 'correcao', 'jam', 'total', 'meses_jam'
    ]
    for campo in obrigatorios:
        if campo not in memoria:
            print(f"[ERRO PDF] Campo ausente em memoria: {campo}")
            raise ValueError(f"Campo obrigatório ausente: {campo}")

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    p.setFont("Helvetica-Bold", 18)
    p.drawString(30, height - 50, "Relatório FGTS Corrigido")
    p.setFont("Helvetica", 12)
    y = height - 90
    p.drawString(30, y, f"E-mail: {email}")
    y -= 30
    p.drawString(30, y, f"Competência: {memoria['competencia']}")
    y -= 20
    p.drawString(30, y, f"Data de Pagamento: {memoria['data_pagamento']}")
    y -= 20
    p.drawString(30, y, f"Base FGTS: R$ {memoria['base_fgts']:.2f}")
    y -= 20
    p.drawString(30, y, f"FGTS do mês: R$ {memoria['fgts_mes']:.2f}")
    y -= 20
    p.drawString(30, y, f"Índice FGTS: {memoria['indice']}")
    y -= 20
    p.drawString(30, y, f"Depósito Corrigido: R$ {memoria['deposito_fgts']:.2f}")
    y -= 20
    p.drawString(30, y, f"Correção: R$ {memoria['correcao']:.2f}")
    y -= 20
    p.drawString(30, y, f"JAM: R$ {memoria['jam']:.2f}")
    y -= 20
    p.drawString(30, y, f"Total Corrigido: R$ {memoria['total']:.2f}")
    y -= 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(30, y, "Detalhamento JAM mês a mês:")
    y -= 20
    p.setFont("Helvetica", 10)
    p.drawString(30, y, "Mês         Coef.     JAM Mês     Saldo")
    for m in memoria.get('meses_jam', []):
        y -= 15
        if y < 60:
            p.showPage()
            y = height - 60
        p.drawString(30, y, f"{m['mes']}   {m['coef'] or '-'}   R$ {m['jam_mes']:.2f}   R$ {m['saldo']:.2f}")
    p.showPage()
    p.save()
    buffer.seek(0)
    print(f"[DEBUG PDF] PDF gerado com sucesso para {email}")
    return buffer

def _salvar_log_erro(email, mensagem, relatorio=None):
    try:
        EmailLog.objects.create(email=email, status='erro', mensagem=mensagem, relatorio=relatorio)
    except Exception:
        pass


def enviar_relatorio_fgts(email, memoria):
    """
    Envia o relatório FGTS por e-mail com PDF em anexo.
    Retorna (sucesso: bool, steps: list[dict]) para diagnóstico visual.
    Cada step: {'descricao': str, 'status': 'ok'|'erro'|'aviso', 'detalhe': str|None}
    """
    steps = []
    relatorio = None

    # Etapa 1: Gerar PDF
    try:
        pdf_buffer = gerar_pdf_fgts(memoria, email)
        steps.append({'descricao': 'Gerar PDF', 'status': 'ok', 'detalhe': None})
    except Exception as e:
        steps.append({'descricao': 'Gerar PDF', 'status': 'erro', 'detalhe': str(e)})
        _salvar_log_erro(email, str(e))
        return False, steps

    # Etapa 2: Montar corpo do e-mail (HTML)
    try:
        corpo = render_to_string('empresas/email_fgts.html', {
            'email': email,
            'memoria': memoria,
            'plataforma_url': getattr(settings, 'SITE_URL', ''),
        })
        steps.append({'descricao': 'Montar corpo do e-mail (HTML)', 'status': 'ok', 'detalhe': None})
    except Exception as e:
        steps.append({'descricao': 'Montar corpo do e-mail (HTML)', 'status': 'erro', 'detalhe': str(e)})
        _salvar_log_erro(email, str(e))
        return False, steps

    # Etapa 3: Criar mensagem de e-mail
    try:
        relatorio = RelatorioPremium.objects.filter(email=email).order_by('-data_geracao').first()
        msg = EmailMessage(
            'Seu FGTS corrigido com memória auditável está pronto',
            corpo,
            settings.DEFAULT_FROM_EMAIL,
            [email],
        )
        msg.content_subtype = 'html'
        steps.append({
            'descricao': f'Criar mensagem (de: {settings.DEFAULT_FROM_EMAIL} → para: {email})',
            'status': 'ok',
            'detalhe': None,
        })
    except Exception as e:
        steps.append({'descricao': 'Criar mensagem de e-mail', 'status': 'erro', 'detalhe': str(e)})
        _salvar_log_erro(email, str(e), relatorio)
        return False, steps

    # Etapa 4: Anexar PDF
    try:
        msg.attach('relatorio_fgts.pdf', pdf_buffer.read(), 'application/pdf')
        steps.append({'descricao': 'Anexar PDF ao e-mail', 'status': 'ok', 'detalhe': None})
    except Exception as e:
        steps.append({'descricao': 'Anexar PDF ao e-mail', 'status': 'erro', 'detalhe': str(e)})
        _salvar_log_erro(email, str(e), relatorio)
        return False, steps

    # Etapa 5: Enviar via SMTP
    try:
        msg.send()
        steps.append({'descricao': 'Enviar e-mail via SMTP (Brevo)', 'status': 'ok', 'detalhe': None})
    except Exception as e:
        steps.append({'descricao': 'Enviar e-mail via SMTP (Brevo)', 'status': 'erro', 'detalhe': str(e)})
        _salvar_log_erro(email, str(e), relatorio)
        return False, steps

    # Etapa 6: Registrar log de auditoria
    try:
        EmailLog.objects.create(
            email=email, status='sucesso',
            mensagem='E-mail enviado com sucesso.', relatorio=relatorio,
        )
        steps.append({'descricao': 'Registrar log de auditoria', 'status': 'ok', 'detalhe': None})
    except Exception as e:
        steps.append({'descricao': 'Registrar log de auditoria', 'status': 'aviso', 'detalhe': str(e)})

    return True, steps
