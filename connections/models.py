from django.db import models


# Create your models here.
class DatabaseSchema(models.Model):

    schema_data = models.JSONField()

    discovered_at = models.DateTimeField(auto_now=True)
