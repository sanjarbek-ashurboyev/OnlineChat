"""Delete avatar files no account points to any more: replaced, removed, or the account deleted (M-16)."""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from accounts.models import User


def delete_when_unused(name):
    # Only after the commit: a rolled-back change must not lose a photo that's still in use.
    def delete():
        if not User.objects.filter(avatar=name).exists():
            User.avatar.field.storage.delete(name)
    transaction.on_commit(delete)


@receiver(pre_save, sender=User)
def remember_old_avatar(sender, instance, update_fields=None, **kwargs):
    # A save that names its fields without the avatar (login's last_login) can't change it: skip the query.
    if instance.pk is None or (update_fields is not None and 'avatar' not in update_fields):
        instance._old_avatar = ''
        return
    instance._old_avatar = sender.objects.filter(pk=instance.pk).values_list('avatar', flat=True).first() or ''


@receiver(post_save, sender=User)
def delete_replaced_avatar(sender, instance, **kwargs):
    old = instance._old_avatar
    if old and old != instance.avatar.name:
        delete_when_unused(old)


@receiver(post_delete, sender=User)
def delete_avatar_of_deleted_user(sender, instance, **kwargs):
    if instance.avatar:
        delete_when_unused(instance.avatar.name)
