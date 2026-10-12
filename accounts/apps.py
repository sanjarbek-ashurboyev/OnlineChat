from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from accounts import signals  # noqa: F401  (connects the receivers)
