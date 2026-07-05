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

    def is_owner(self):
        return self.role == "owner" or self.is_superuser

    def is_employee_or_admin(self):
        return self.role in ["employee", "admin", "owner"] or self.is_staff or self.is_superuser
