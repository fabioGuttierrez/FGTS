from django import forms
from .models import Funcionario

class FuncionarioForm(forms.ModelForm):
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
