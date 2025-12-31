from django.db import models
from empresas.models import Empresa
from django.core.exceptions import ValidationError


class Funcionario(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='funcionarios', verbose_name='Empresa')
    matricula = models.CharField(max_length=20, blank=True, verbose_name='Matrícula')
    nome = models.CharField(max_length=255, verbose_name='Nome')
    pis = models.CharField(max_length=15, blank=True, verbose_name='PIS')
    cpf = models.CharField(max_length=14, verbose_name='CPF')
    cbo = models.CharField(max_length=10, blank=True, verbose_name='CBO')
    carteira_profissional = models.CharField(max_length=20, blank=True, verbose_name='Carteira Profissional')
    serie_carteira = models.CharField(max_length=10, blank=True, verbose_name='Série Carteira')
    data_nascimento = models.DateField(null=True, blank=True, verbose_name='Data Nascimento')
    data_admissao = models.DateField(verbose_name='Data Admissão')
    data_demissao = models.DateField(null=True, blank=True, verbose_name='Data Demissão')
    observacao = models.TextField(blank=True, verbose_name='Observação')

    def __str__(self):
        return self.nome
    
    def clean(self):
        """Valida se o funcionário pode ser criado dentro do plano da empresa"""
        super().clean()
        
        # Verificar se é nova criação
        if not self.pk:  # Novo funcionário
            try:
                billing_customer = self.empresa.billing_customer
                
                # Se não tem plano, não permite criar
                if not billing_customer.plan:
                    raise ValidationError(
                        'Empresa não possui plano configurado. '
                        'Contacte o administrador.'
                    )
                
                # Verificar limite de colaboradores
                # Contar funcionários ativos (sem data_demissao)
                active_count = self.empresa.funcionarios.filter(
                    data_demissao__isnull=True
                ).count()
                
                if not billing_customer.plan.can_add_employee(active_count):
                    plan_name = billing_customer.plan.get_plan_type_display()
                    max_employees = billing_customer.plan.max_employees
                    raise ValidationError(
                        f'Seu plano {plan_name} permite no máximo '
                        f'{max_employees} colaboradores ativos. '
                        f'Você já possui {active_count}. '
                        f'Faça upgrade para adicionar mais.'
                    )
            except:
                # Se não existe billing_customer, deixa falhar naturalmente
                pass
    
    class Meta:
        verbose_name = 'Funcionário'
        verbose_name_plural = 'Funcionários'
        # Permite múltiplos vínculos de um mesmo CPF (mesma empresa ou não)
        # Exemplo: um funcionário pode ser horista e advogado simultaneamente
