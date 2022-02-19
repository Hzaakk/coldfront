from decimal import Decimal

from django.template.loader import render_to_string

from coldfront.api.statistics.utils import get_accounting_allocation_objects, \
    set_project_allocation_value, set_project_user_allocation_value, \
    set_project_usage_value, set_project_user_usage_value
from coldfront.config import settings
from coldfront.core.allocation.models import AllocationStatusChoice
from coldfront.core.allocation.utils import get_project_compute_allocation
from coldfront.core.project.models import Project
from coldfront.core.project.models import ProjectStatusChoice
from django.core.management.base import BaseCommand
import logging

from coldfront.core.statistics.models import ProjectTransaction, \
    ProjectUserTransaction
from coldfront.core.utils.common import utc_now_offset_aware
from coldfront.core.utils.mail import send_email_template

"""An admin command that sets expired ICA Projects to 'Inactive' and
their corresponding compute Allocations to 'Expired'."""


class Command(BaseCommand):

    help = ('Expire ICA projects whose end dates have passed and optionally '
            'notify project owners')
    logger = logging.getLogger(__name__)

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry_run',
            action='store_true',
            help='Display updates without performing them.')
        parser.add_argument(
            '--send_emails',
            action='store_true',
            default=False,
            help='Send emails to PIs/managers about project deactivation.')

    def handle(self, *args, **options):
        """For each expired ICA Project, set its status to 'Inactive' and its
        compute Allocation's status to 'Expired'. Zero out Service Units for
        the Allocation and AllocationUsers.
        """
        current_date = utc_now_offset_aware()
        ica_projects = Project.objects.filter(name__startswith='ic_')

        for project in ica_projects:
            allocation = get_project_compute_allocation(project)
            expiry_date = allocation.end_date

            if expiry_date and expiry_date < current_date.date():
                self.reset_service_units(project, options['dry_run'])
                self.deactivate_project(project, allocation, options['dry_run'])

                if options['send_emails']:
                    self.send_emails(project, expiry_date, options['dry_run'])

    def deactivate_project(self, project, allocation, dry_run):
        """
        Expire ICA projects whose end dates have passed and optionally
        notify project owners

        If dry_run is True, write to stdout without changing object fields.
        """
        project_status = ProjectStatusChoice.objects.get(name='Inactive')
        allocation_status = AllocationStatusChoice.objects.get(name='Expired')
        current_date = utc_now_offset_aware()

        if dry_run:
            message = (
                f'Would update Project {project.name} ({project.pk})\'s '
                f'status to {project_status.name} and Allocation '
                f'{allocation.pk}\'s status to {allocation_status.name}.')

            self.stdout.write(self.style.WARNING(message))
        else:
            project.status = project_status
            project.save()
            allocation.status = allocation_status
            allocation.start_date = current_date
            allocation.end_date = None
            allocation.save()

            message = (
                f'Updated Project {project.name} ({project.pk})\'s status to '
                f'{project_status.name} and Allocation {allocation.pk}\'s '
                f'status to {allocation_status.name}.')

            self.logger.info(message)
            self.stdout.write(self.style.SUCCESS(message))

    def set_historical_reason(self, obj, reason):
        """Set the latest historical object reason"""
        obj.refresh_from_db()
        historical_obj = obj.history.latest('id')
        historical_obj.history_change_reason = reason
        historical_obj.save()

    def reset_service_units(self, project, dry_run):
        """
        Resets service units for a project and its users to 0.00. Creates
        the relevant transaction objects to record the change. Updates the
        relevant historical objects with the reason for the SU change.

        If dry_run is True, write to stdout without changing object fields.
        """
        allocation_objects = get_accounting_allocation_objects(project)
        current_allocation = Decimal(allocation_objects.allocation_attribute.value)
        current_date = utc_now_offset_aware()
        reason = 'Resetting SUs while deactivating expired ICA project.'
        updated_su = Decimal('0.00')

        if dry_run:
            message = f'Would reset {project.name} and its users\'s SUs from ' \
                      f'{current_allocation} to {updated_su}. The reason ' \
                      f'would be: "Resetting SUs while deactivating expired ' \
                      f'ICA project."'

            self.stdout.write(self.style.WARNING(message))

        else:
            # Set the value for the Project.
            set_project_allocation_value(project, updated_su)
            set_project_usage_value(project, updated_su)

            # Create a transaction to record the change.
            ProjectTransaction.objects.create(
                project=project,
                date_time=current_date,
                allocation=updated_su)

            # Set the reason for the change in the newly-created historical object.
            self.set_historical_reason(
                allocation_objects.allocation_attribute, reason)

            # Do the same for each ProjectUser.
            for project_user in project.projectuser_set.all():
                user = project_user.user
                # Attempt to set the value for the ProjectUser. The method returns whether
                # it succeeded; it may not because not every ProjectUser has a
                # corresponding AllocationUser (e.g., PIs). Only proceed with further steps
                # if an update occurred.

                allocation_updated = set_project_user_allocation_value(
                    user, project, updated_su)
                allocation_usage_updated = set_project_user_usage_value(
                    user, project, updated_su)

                if allocation_updated and allocation_usage_updated:
                    # Create a transaction to record the change.
                    ProjectUserTransaction.objects.create(
                        project_user=project_user,
                        date_time=current_date,
                        allocation=updated_su)
                    # Set the reason for the change in the newly-created historical object.

                    allocation_user_obj = get_accounting_allocation_objects(
                        project, user=user)
                    self.set_historical_reason(
                        allocation_user_obj.allocation_user_attribute, reason)

            message = f'Successfully reset SUs for {project.name} ' \
                      f'and its users, updating {project.name}\'s SUs from ' \
                      f'{current_allocation} to {updated_su}. The reason ' \
                      f'was: "{reason}".'

            self.logger.info(message)
            self.stdout.write(self.style.SUCCESS(message))

        return current_allocation

    def send_emails(self, project, expiry_date, dry_run):
        """
        Send emails to managers/PIs of the project that have notifications
        enabled about the project deactivation.

        If dry_run is True, write the emails to stdout instead.
        """

        if settings.EMAIL_ENABLED:
            context = {
                'project_name': project.name,
                'expiry_date': expiry_date.strftime('%m-%d-%Y'),
                'support_email': settings.CENTER_HELP_EMAIL,
                'signature': settings.EMAIL_SIGNATURE,
            }

            recipients = list(project.managers_and_pis_with_notifications()
                              .values_list('user__email', flat=True))

            if dry_run:
                msg_plain = \
                    render_to_string('email/expired_ica_project.txt',
                                     context)

                message = f'Would send the following email to ' \
                          f'{len(recipients)} users:'
                self.stdout.write(self.style.WARNING(message))
                self.stdout.write(self.style.WARNING(msg_plain))

            else:
                try:
                    send_email_template(
                        'Expired ICA Project Deactivation',
                        'email/expired_ica_project.txt',
                        context,
                        settings.EMAIL_SENDER,
                        recipients)

                    message = f'Sent deactivation notification email to ' \
                              f'{len(recipients)} users.'
                    self.stdout.write(self.style.SUCCESS(message))

                except Exception as e:
                    message = 'Failed to send notification email. Details:'
                    self.stderr.write(self.style.ERROR(message))
                    self.stderr.write(self.style.ERROR(str(e)))
                    self.logger.error(message)
                    self.logger.exception(e)
        else:
            message = 'settings.EMAIL_ENABLED set to False. ' \
                      'No emails will be sent.'
            self.stderr.write(self.style.ERROR(message))