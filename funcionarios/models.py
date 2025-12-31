from django.db import models
from empresas.models import Empresa

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
    
    class Meta:
        verbose_name = 'Funcionário'
        verbose_name_plural = 'Funcionários'
        # Permite múltiplos vínculos de um mesmo CPF (mesma empresa ou não)
        # Exemplo: um funcionário pode ser horista e advogado simultaneamente
