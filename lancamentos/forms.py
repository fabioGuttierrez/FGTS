from django import forms
from empresas.models import Empresa
from funcionarios.models import Funcionario
from fgtsweb.mixins import get_allowed_empresa_ids
from .models import Lancamento


class LancamentoForm(forms.ModelForm):
    """Formulário para cadastro/edição de lançamentos mensais (base FGTS)"""
    
    class Meta:
        model = Lancamento
        fields = ['empresa', 'funcionario', 'competencia', 'base_fgts', 'pago', 'data_pagto', 'valor_pago']
        widgets = {
            'empresa': forms.Select(attrs={'autocomplete': 'off', 'class': 'form-select'}),
            'funcionario': forms.Select(attrs={'autocomplete': 'off', 'class': 'form-select'}),
            'competencia': forms.TextInput(attrs={
                'placeholder': 'MM/YYYY (ex: 01/2025)',
                'autocomplete': 'off',
                'class': 'form-control'
            }),
            'base_fgts': forms.NumberInput(attrs={
                'placeholder': 'Valor base para cálculo do FGTS',
                'step': '0.01',
                'class': 'form-control'
            }),
            'pago': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'data_pagto': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'valor_pago': forms.NumberInput(attrs={
                'placeholder': 'Valor efetivamente pago',
                'step': '0.01',
                'class': 'form-control'
            }),
        }
        labels = {
            'empresa': 'Empresa *',
            'funcionario': 'Funcionário *',
            'competencia': 'Competência (MM/YYYY) *',
            'base_fgts': 'Base FGTS (Salário)',
            'pago': 'FGTS Pago?',
            'data_pagto': 'Data do Pagamento',
            'valor_pago': 'Valor Pago',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filtrar empresas permitidas
        if user is not None:
            allowed_ids = get_allowed_empresa_ids(user)
            if allowed_ids is not None:
                self.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        
        # Filtrar funcionários se empresa foi selecionada
        if 'data' in kwargs and kwargs['data'].get('empresa'):
            try:
                empresa_id = int(kwargs['data'].get('empresa'))
                self.fields['funcionario'].queryset = Funcionario.objects.filter(empresa_id=empresa_id)
            except (ValueError, TypeError):
                self.fields['funcionario'].queryset = Funcionario.objects.none()
    
    def save(self, commit=True):
        """Sobrescrever save para calcular valor_fgts automaticamente"""
        lancamento = super().save(commit=False)
        # ⚡ Calcular valor_fgts automaticamente (8% da base_fgts)
        base_fgts = lancamento.base_fgts
        if base_fgts and (lancamento.valor_fgts is None or lancamento.valor_fgts == 0):
            from decimal import Decimal
            lancamento.valor_fgts = base_fgts * Decimal('0.08')
        if commit:
            lancamento.save()
        return lancamento


class RelatorioCompetenciaForm(forms.Form):
    empresa = forms.ModelChoiceField(
        queryset=Empresa.objects.all(), 
        label='Empresa',
        widget=forms.Select(attrs={'autocomplete': 'off'})
    )
    funcionario = forms.ModelChoiceField(
        queryset=Funcionario.objects.none(), 
        label='Funcionário (opcional)', 
        required=False,
        widget=forms.Select(attrs={'autocomplete': 'off'})
    )
    competencia = forms.CharField(
        label='Competência Única', 
        required=False, 
        help_text='MM/YYYY - Deixe vazio para calcular TODAS as competências em aberto',
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Vazio = todas em aberto'})
    )
    competencias = forms.CharField(
        label='Múltiplas competências (uma por linha)', 
        required=False, 
        help_text='Uma por linha no formato MM/YYYY. Ignora se competência única estiver preenchida', 
        widget=forms.Textarea(attrs={'rows': 3, 'autocomplete': 'off', 'placeholder': '01/2024\n02/2024\n03/2024'})
    )
    agrupamento = forms.ChoiceField(
        label='Agrupar por',
        choices=[
            ('competencia', 'Competência'),
            ('ano', 'Ano'),
            ('funcionario', 'Funcionário'),
        ],
        initial='competencia',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    data_pagamento = forms.DateField(
        label='Data de Pagamento', 
        required=False, 
        widget=forms.DateInput(attrs={'type': 'date', 'autocomplete': 'off'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            allowed_ids = get_allowed_empresa_ids(user)
            if allowed_ids is not None:
                self.fields['empresa'].queryset = Empresa.objects.filter(codigo__in=allowed_ids)
        
        # Se o formulário tem dados (POST), filtra funcionários pela empresa selecionada
        if 'data' in kwargs and kwargs['data'].get('empresa'):
            try:
                empresa_id = int(kwargs['data'].get('empresa'))
                self.fields['funcionario'].queryset = Funcionario.objects.filter(empresa_id=empresa_id)
            except (ValueError, TypeError):
                self.fields['funcionario'].queryset = Funcionario.objects.none()
        elif user is not None and allowed_ids is not None:
            # Se não tem empresa selecionada, mostra todos das empresas permitidas
            self.fields['funcionario'].queryset = Funcionario.objects.filter(empresa__codigo__in=allowed_ids)
