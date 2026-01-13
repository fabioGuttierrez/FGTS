from django import forms
from decimal import Decimal
from .models import Funcionario

class FuncionarioForm(forms.ModelForm):
    salario_inicial = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        label='Salário Inicial (Base FGTS)',
        help_text='Se informado, será criado automaticamente o primeiro lançamento de FGTS na competência de admissão',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: 3500.00',
            'step': '0.01'
        })
    )
    
    class Meta:
        model = Funcionario
        fields = ['empresa', 'matricula', 'nome', 'pis', 'cpf', 'cbo', 'carteira_profissional', 
                  'serie_carteira', 'data_nascimento', 'data_admissao', 'data_demissao', 'observacao']
        widgets = {
            'empresa': forms.Select(attrs={'class': 'form-select'}),
            'matricula': forms.TextInput(attrs={'class': 'form-control'}),
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'pis': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control'}),
            'cbo': forms.TextInput(attrs={'class': 'form-control'}),
            'carteira_profissional': forms.TextInput(attrs={'class': 'form-control'}),
            'serie_carteira': forms.TextInput(attrs={'class': 'form-control'}),
            'data_nascimento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'data_admissao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'data_demissao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
