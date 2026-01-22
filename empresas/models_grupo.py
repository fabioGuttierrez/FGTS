from django.db import models
from django.conf import settings

class GrupoEmpresa(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    cnpj_base = models.CharField(max_length=20, blank=True, null=True)
    data_criacao = models.DateField(auto_now_add=True)
    observacoes = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nome

class FuncionarioVinculo(models.Model):
    MOTIVO_SAIDA_CHOICES = [
        ("demissao", "Demissão"),
        ("transferencia", "Transferência para outra empresa do grupo"),
        ("outro", "Outro")
    ]
    funcionario = models.ForeignKey('funcionarios.Funcionario', on_delete=models.CASCADE, related_name='vinculos')
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE)
    data_admissao = models.DateField()
    data_demissao = models.DateField(blank=True, null=True)
    motivo_saida = models.CharField(max_length=20, choices=MOTIVO_SAIDA_CHOICES, blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)
    cargo = models.CharField(max_length=100, blank=True, null=True)
    salario = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    data_transferencia = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.funcionario.nome} - {self.empresa.nome} ({self.data_admissao} a {self.data_demissao or 'atual'})"

class TransferenciaFuncionario(models.Model):
    funcionario = models.ForeignKey('funcionarios.Funcionario', on_delete=models.CASCADE)
    empresa_origem = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='transferencias_saida')
    empresa_destino = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='transferencias_entrada')
    data_transferencia = models.DateField(auto_now_add=True)
    usuario_responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    observacoes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.funcionario.nome}: {self.empresa_origem.nome} → {self.empresa_destino.nome} em {self.data_transferencia}"
