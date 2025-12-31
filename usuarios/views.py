from django import forms
from django.contrib.auth import authenticate, login
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from .models import Usuario


class UsuarioRegisterForm(forms.ModelForm):
    """Formulário de registro de usuário"""
    password1 = forms.CharField(
        label='Senha',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Senha'}),
        min_length=8,
        help_text='Mínimo 8 caracteres'
    )
    password2 = forms.CharField(
        label='Confirmar Senha',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirme a senha'}),
        min_length=8
    )
    
    class Meta:
        model = Usuario
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome de usuário'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'E-mail'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sobrenome'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError('As senhas não conferem.')
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class UsuarioRegisterView(CreateView):
    """View para criar nova conta de usuário"""
    model = Usuario
    form_class = UsuarioRegisterForm
    template_name = 'usuarios/register.html'
    success_url = reverse_lazy('dashboard')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Passar plano selecionado se houver na sessão
        plan_type = self.request.session.get('selected_plan_type')
        if plan_type:
            try:
                from billing.models import Plan
                context['selected_plan'] = Plan.objects.get(plan_type=plan_type, active=True)
            except:
                pass
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Autenticar e fazer login automaticamente
        username = form.cleaned_data['username']
        password = form.cleaned_data['password1']
        user = authenticate(username=username, password=password)
        if user is not None:
            login(self.request, user)
            
            # Se há plano selecionado em sessão, redirecionar para criar empresa
            if 'selected_plan_type' in self.request.session:
                return redirect('empresa-create')
        
        return response
