from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = [
        ("client", "Client"),
        ("employee", "Employee"),
        ("admin", "Admin"),
        ("owner", "Owner"),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="client")

    is_ai_specialist = models.BooleanField(default=False, help_text="Qualified to document strategy and custom pricing during Growth Assessments.")

    def can_manage_pricing(self):
        return self.is_active and (self.is_owner() or (self.is_employee_or_admin() and self.is_ai_specialist))

    def is_owner(self):
        return self.role == "owner" or self.is_superuser

    def is_employee_or_admin(self):
        return self.role in ["employee", "admin", "owner"] or self.is_staff or self.is_superuser
