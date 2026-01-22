from django import forms
from .models import Empresa
from .models_grupo import GrupoEmpresa

class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ['grupo', 'nome', 'cnpj', 'endereco', 'numero', 'bairro', 'cep', 'cidade', 'uf', 
                  'nome_contato', 'fone_contato', 'cnae', 'percentual_rat', 'optante_simples', 
                  'fpas', 'outras_entidades', 'email', 'paga_13_aniversario']
        widgets = {
            'grupo': forms.Select(attrs={'class': 'form-select'}),
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cnpj': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.TextInput(attrs={'class': 'form-control'}),
            'numero': forms.TextInput(attrs={'class': 'form-control'}),
            'bairro': forms.TextInput(attrs={'class': 'form-control'}),
            'cep': forms.TextInput(attrs={'class': 'form-control'}),
            'cidade': forms.TextInput(attrs={'class': 'form-control'}),
            'uf': forms.TextInput(attrs={'class': 'form-control'}),
            'nome_contato': forms.TextInput(attrs={'class': 'form-control'}),
            'fone_contato': forms.TextInput(attrs={'class': 'form-control'}),
            'cnae': forms.TextInput(attrs={'class': 'form-control'}),
            'percentual_rat': forms.NumberInput(attrs={'class': 'form-control'}),
            'optante_simples': forms.Select(attrs={'class': 'form-select'}),
            'fpas': forms.TextInput(attrs={'class': 'form-control'}),
            'outras_entidades': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'paga_13_aniversario': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
