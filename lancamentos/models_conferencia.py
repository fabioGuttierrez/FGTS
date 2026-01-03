"""
Sistema de Conferência de Lançamentos
Validação obrigatória antes de consolidar/pagar
"""

from decimal import Decimal
from datetime import datetime
from django.db import models, transaction
from django.contrib.auth.models import User
from lancamentos.models import Lancamento


class ConferenciaLancamento(models.Model):
    """Registro de conferência/validação de lançamento antes de pagamento"""

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente de Conferência'),
        ('CONFERIDO', 'Conferido - OK'),
        ('PROBLEMA', 'Conferido - Com Problema'),
        ('REJEITADO', 'Rejeitado'),
    ]

    lancamento = models.OneToOneField(
        Lancamento,
        on_delete=models.CASCADE,
        related_name='conferencia'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    
    # Quem conferiu
    conferido_por = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='conferencias_lancamentos'
    )
    data_conferencia = models.DateTimeField(null=True, blank=True)
    
    # Validações
    valor_conferido = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Valor conferido manualmente (se diferente de calculado)"
    )
    observacoes = models.TextField(blank=True)
    
    # Rastreamento
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lancamentos_conferencia'
        verbose_name = 'Conferência de Lançamento'
        verbose_name_plural = 'Conferências de Lançamentos'

    def __str__(self):
        return f"Conferência {self.lancamento} - {self.status}"

    def conferir(self, usuario: User, valor_conferido: Decimal = None, observacoes: str = "") -> bool:
        """
        Marca lançamento como conferido

        Args:
            usuario: Usuário que está conferindo
            valor_conferido: Valor conferido (se diferente do calculado)
            observacoes: Observações/notas sobre a conferência

        Returns:
            True se conferência foi válida, False se há problema
        """
        self.conferido_por = usuario
        self.data_conferencia = datetime.now()
        self.observacoes = observacoes
        self.valor_conferido = valor_conferido

        # Validações automáticas
        problemas = self._validar()

        if problemas:
            self.status = 'PROBLEMA'
        else:
            self.status = 'CONFERIDO'

        self.save()
        return self.status == 'CONFERIDO'

    def rejeitar(self, usuario: User, motivo: str = ""):
        """Marca lançamento como rejeitado"""
        self.conferido_por = usuario
        self.data_conferencia = datetime.now()
        self.status = 'REJEITADO'
        self.observacoes = motivo
        self.save()

    def _validar(self) -> list:
        """
        Executa validações automáticas

        Returns:
            Lista de problemas encontrados (vazia = sem problemas)
        """
        problemas = []

        # 1. Validar se valor_fgts está positivo
        if self.lancamento.valor_fgts <= 0:
            problemas.append("Valor FGTS inválido (≤ 0)")

        # 2. Validar se valor_fgts é coerente com base_fgts (8%)
        base_calc = self.lancamento.valor_fgts / Decimal('0.08')
        if abs(base_calc - self.lancamento.base_fgts) > Decimal('1'):  # Tolerância de R$ 1
            problemas.append(f"Base FGTS incongruente: calculada {base_calc:.2f}, informada {self.lancamento.base_fgts:.2f}")

        # 3. Validar se competência é válida (formato MM/YYYY)
        try:
            from datetime import datetime
            datetime.strptime(self.lancamento.competencia, '%m/%Y')
        except ValueError:
            problemas.append(f"Competência inválida: {self.lancamento.competencia}")

        # 4. Validar se data_pagamento faz sentido (posterior à competência)
        if self.lancamento.data_pagamento:
            comp_date = datetime.strptime(self.lancamento.competencia + '/01', '%m/%Y/%d').date()
            if self.lancamento.data_pagamento < comp_date:
                problemas.append(f"Data de pagamento anterior à competência")

        # 5. Se valor_conferido foi fornecido, validar diferença
        if self.valor_conferido is not None:
            diff = abs(self.valor_conferido - self.lancamento.valor_fgts)
            percentual = (diff / self.lancamento.valor_fgts * 100) if self.lancamento.valor_fgts > 0 else 0
            if percentual > 5:  # Mais de 5% de diferença
                problemas.append(f"Valor conferido diverge em {percentual:.1f}% (calculado: {self.lancamento.valor_fgts:.2f}, conferido: {self.valor_conferido:.2f})")

        return problemas

    @classmethod
    def gerar_relatorio_conferencia(cls, empresa, competencia: str = None):
        """
        Gera relatório de conferências para análise

        Returns:
            Dict com estatísticas
        """
        qs = cls.objects.filter(lancamento__empresa=empresa)
        
        if competencia:
            qs = qs.filter(lancamento__competencia=competencia)

        total = qs.count()
        conferidos = qs.filter(status='CONFERIDO').count()
        problemas = qs.filter(status='PROBLEMA').count()
        rejeitados = qs.filter(status='REJEITADO').count()
        pendentes = qs.filter(status='PENDENTE').count()

        return {
            'empresa': empresa,
            'competencia': competencia,
            'total_lancamentos': total,
            'conferidos': conferidos,
            'com_problemas': problemas,
            'rejeitados': rejeitados,
            'pendentes': pendentes,
            'taxa_conferencia': (conferidos / total * 100) if total > 0 else 0,
            'percentual_problemas': (problemas / total * 100) if total > 0 else 0,
        }

    @classmethod
    def pode_consolidar_competencia(cls, empresa, competencia: str) -> Tuple[bool, str]:
        """
        Verifica se uma competência pode ser consolidada/paga

        Returns:
            (pode_consolidar, mensagem)
        """
        conferencias = cls.objects.filter(
            lancamento__empresa=empresa,
            lancamento__competencia=competencia
        )

        if not conferencias.exists():
            return False, "Nenhuma conferência registrada para esta competência"

        rejeitados = conferencias.filter(status='REJEITADO').count()
        if rejeitados > 0:
            return False, f"{rejeitados} lançamentos foram rejeitados"

        pendentes = conferencias.filter(status='PENDENTE').count()
        if pendentes > 0:
            return False, f"{pendentes} lançamentos ainda estão pendentes"

        problemas = conferencias.filter(status='PROBLEMA').count()
        if problemas > 0:
            # Pode consolidar mesmo com problemas, mas com aviso
            msg = f"ATENÇÃO: {problemas} lançamentos com problemas registrados"
            return True, msg

        return True, "Todas as conferências OK - Pronto para consolidar"


# ===== VIEWS E FORMS =====

from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.messages import success, error, warning


class ConferenciaLancamentoForm(forms.ModelForm):
    """Form para entrada de dados de conferência"""
    
    class Meta:
        model = ConferenciaLancamento
        fields = ['valor_conferido', 'observacoes']
        widgets = {
            'valor_conferido': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Deixe em branco se for igual ao calculado'
            }),
            'observacoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Notas da conferência...'
            }),
        }


@login_required
@require_http_methods(["GET"])
def listar_conferencias(request, empresa_id: int):
    """Lista lançamentos pendentes de conferência"""
    from empresas.models import Empresa
    
    empresa = get_object_or_404(Empresa, pk=empresa_id)
    
    # Filtros
    competencia = request.GET.get('competencia')
    status_filtro = request.GET.get('status', 'PENDENTE')
    
    conferencias = ConferenciaLancamento.objects.filter(
        lancamento__empresa=empresa
    ).select_related('lancamento__funcionario', 'conferido_por')
    
    if competencia:
        conferencias = conferencias.filter(lancamento__competencia=competencia)
    
    if status_filtro and status_filtro != 'TODOS':
        conferencias = conferencias.filter(status=status_filtro)
    
    # Relatório
    relatorio = ConferenciaLancamento.gerar_relatorio_conferencia(empresa, competencia)
    
    return render(request, 'lancamentos/conferencia_lista.html', {
        'conferencias': conferencias,
        'empresa': empresa,
        'competencia': competencia,
        'relatorio': relatorio,
    })


@login_required
@require_http_methods(["GET", "POST"])
def conferir_lancamento(request, conferencia_id: int):
    """Formulário para conferência individual de lançamento"""
    conferencia = get_object_or_404(ConferenciaLancamento, pk=conferencia_id)
    
    if request.method == "POST":
        form = ConferenciaLancamentoForm(request.POST, instance=conferencia)
        if form.is_valid():
            valor = form.cleaned_data.get('valor_conferido')
            obs = form.cleaned_data.get('observacoes', '')
            
            valido = conferencia.conferir(request.user, valor, obs)
            
            msg = f"Lançamento {'CONFERIDO' if valido else 'COM PROBLEMAS'}"
            (success if valido else warning)(request, msg)
            
            return redirect('listar_conferencias', empresa_id=conferencia.lancamento.empresa_id)
    else:
        form = ConferenciaLancamentoForm(instance=conferencia)
    
    return render(request, 'lancamentos/conferencia_form.html', {
        'form': form,
        'conferencia': conferencia,
        'lancamento': conferencia.lancamento,
    })


@login_required
@require_http_methods(["POST"])
def rejeitar_lancamento(request, conferencia_id: int):
    """Rejeita um lançamento"""
    conferencia = get_object_or_404(ConferenciaLancamento, pk=conferencia_id)
    motivo = request.POST.get('motivo', 'Motivo não informado')
    
    conferencia.rejeitar(request.user, motivo)
    error(request, f"Lançamento {conferencia.lancamento} foi REJEITADO")
    
    return redirect('listar_conferencias', empresa_id=conferencia.lancamento.empresa_id)
