"""
Comando para testar envio de emails
Uso: python manage.py testar_email seu@email.com
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from emails.services import EmailService


class Command(BaseCommand):
    help = 'Testa o envio de email usando as configurações do Brevo'

    def add_arguments(self, parser):
        parser.add_argument(
            'destinatario',
            type=str,
            help='Email do destinatário para teste'
        )

    def handle(self, *args, **options):
        destinatario = options['destinatario']
        
        self.stdout.write(self.style.WARNING('\n🔧 Configurações de Email:'))
        self.stdout.write(f'  Backend: {settings.EMAIL_BACKEND}')
        self.stdout.write(f'  Host: {settings.EMAIL_HOST}')
        self.stdout.write(f'  Port: {settings.EMAIL_PORT}')
        self.stdout.write(f'  TLS: {settings.EMAIL_USE_TLS}')
        self.stdout.write(f'  From: {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write(f'  User: {settings.EMAIL_HOST_USER or "(não configurado)"}')
        self.stdout.write(f'  Password: {"*" * len(settings.EMAIL_HOST_PASSWORD) if settings.EMAIL_HOST_PASSWORD else "(não configurado)"}')
        
        self.stdout.write(self.style.WARNING(f'\n📧 Enviando email de teste para: {destinatario}'))
        
        sucesso = EmailService.enviar_email_simples(
            assunto='✅ Teste de Email - Sistema FGTS',
            mensagem='''
Olá!

Este é um email de teste do Sistema de Gestão FGTS.

Se você recebeu esta mensagem, significa que a integração com 
o Brevo (Sendinblue) está funcionando corretamente! 🎉

Configurações:
- Provedor: Brevo SMTP
- Host: smtp-relay.brevo.com
- Porta: 587 (TLS)

Atenciosamente,
Equipe FGTS
            '''.strip(),
            destinatarios=[destinatario]
        )
        
        if sucesso:
            self.stdout.write(self.style.SUCCESS('\n✅ Email enviado com sucesso!'))
            self.stdout.write(self.style.SUCCESS(f'Verifique a caixa de entrada de: {destinatario}'))
        else:
            self.stdout.write(self.style.ERROR('\n❌ Falha ao enviar email'))
            self.stdout.write(self.style.ERROR('Verifique os logs para mais detalhes'))
