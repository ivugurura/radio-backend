from django.core.management.base import BaseCommand, CommandError

from apps.studio.models import StudioMembership
from apps.studio.services.helpers import get_studio
from apps.users.models import User


class Command(BaseCommand):
    help = (
        "Give a user a role in a studio (or change it). With --remove, take the "
        "user out of the studio instead."
    )

    def add_arguments(self, parser):
        parser.add_argument('email', help='Email of an existing user.')
        parser.add_argument('studio', help='Studio slug (or legacy slug / pk).')
        parser.add_argument(
            'role',
            nargs='?',
            choices=StudioMembership.Role.values,
            help='Role to grant. Required unless --remove.',
        )
        parser.add_argument(
            '--remove', action='store_true', help='Remove the membership.'
        )

    def handle(self, *args, email, studio, role=None, remove=False, **options):
        user = User.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            raise CommandError(f'No user with email {email!r}.')
        studio_obj = get_studio(studio)
        if studio_obj is None:
            raise CommandError(f'No studio {studio!r}.')

        if remove:
            membership = StudioMembership.objects.filter(
                studio=studio_obj, user=user
            ).first()
            if membership is None:
                self.stdout.write(f'{user.email} is not a member of {studio_obj.slug}.')
                return
            membership.delete()  # soft delete
            self.stdout.write(
                self.style.SUCCESS(f'Removed {user.email} from {studio_obj.slug}.')
            )
            return

        if not role:
            raise CommandError('A role is required unless --remove is given.')
        membership, created = StudioMembership.objects.update_or_create(
            studio=studio_obj, user=user, defaults={'role': role}
        )
        verb = 'Granted' if created else 'Set'
        self.stdout.write(
            self.style.SUCCESS(
                f'{verb} {membership.role} for {user.email} on {studio_obj.slug}.'
            )
        )
