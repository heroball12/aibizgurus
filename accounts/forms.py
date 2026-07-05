from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

class SignupForm(UserCreationForm):
    business_name = forms.CharField(max_length=200)
    industry_slug = forms.SlugField(max_length=180, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "business_name", "industry_slug", "password1", "password2"]
