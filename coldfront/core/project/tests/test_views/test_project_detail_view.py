from coldfront.api.statistics.utils import create_project_allocation
from coldfront.core.allocation.models import AllocationRenewalRequest
from coldfront.core.allocation.models import AllocationRenewalRequestStatusChoice
from coldfront.core.project.models import ProjectUser
from coldfront.core.project.models import ProjectUserRoleChoice
from coldfront.core.project.models import ProjectUserStatusChoice
from coldfront.core.project.utils_.renewal_utils import get_current_allowance_year_period
from coldfront.core.utils.common import utc_now_offset_aware
from coldfront.core.utils.tests.test_base import TestBase

from decimal import Decimal
from django.contrib.auth.models import User
from django.urls import reverse

from flags.state import enable_flag
from http import HTTPStatus


class TestProjectDetailView(TestBase):
    """A class for testing ProjectDetailView."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.create_test_user()
        self.sign_user_access_agreement(self.user)
        self.client.login(username=self.user.username, password=self.password)

    @staticmethod
    def project_detail_url(pk):
        """Return the URL to the detail view for the Project with the
        given primary key."""
        return reverse('project-detail', kwargs={'pk': pk})

    def test_get_access(self):
        """Test that GET requests are accessible to authenticated
        members of the Project, staff, and superusers."""
        project = self.create_active_project_with_pi('ac_project', self.user)
        create_project_allocation(project, Decimal('0.00'))

        url = self.project_detail_url(project.pk)

        # Unauthenticated user.
        self.client.logout()
        response = self.client.get(url)
        self.assertRedirects(response, f'{reverse("login")}?next={url}')

        # Project member user.
        self.client.login(username=self.user.username, password=self.password)
        project_user = ProjectUser.objects.get(project=project, user=self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        project_user.delete()

        # Non-(project member) user.
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTPStatus.FORBIDDEN)

        # Non-(project member) staff.
        self.user.is_staff = True
        self.user.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.user.is_staff = False
        self.user.save()

        # Non-(project member) superuser.
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.user.is_superuser = False
        self.user.save()

    def test_purchase_sus_button_invisible_for_ineligible_projects(self):
        """Test that the 'Purchase Service Units' button only appears
        for Projects that are eligible to do so."""
        for prefix in ('ac_', 'co_', 'fc_', 'ic_', 'pc_'):
            project = self.create_active_project_with_pi(
                f'{prefix}project', self.user)
            url = self.project_detail_url(project.pk)
            response = self.client.get(url)
            button_text = 'Purchase Service Units'
            if prefix == 'ac_':
                self.assertContains(response, button_text)
            else:
                self.assertNotContains(response, button_text)

    def test_purchase_sus_button_invisible_for_user_roles(self):
        """Test that the 'Purchase Service Units' button only appears
        for superusers, PIs, and Managers."""
        project = self.create_active_project_with_pi('ac_project', self.user)
        create_project_allocation(project, Decimal('0.00'))

        url = self.project_detail_url(project.pk)
        button_text = 'Purchase Service Units'

        project_user = ProjectUser.objects.get(project=project, user=self.user)
        self.assertEqual(project_user.role.name, 'Principal Investigator')
        response = self.client.get(url)
        self.assertContains(response, button_text)

        project_user.role = ProjectUserRoleChoice.objects.get(name='Manager')
        project_user.save()
        response = self.client.get(url)
        self.assertContains(response, button_text)

        project_user.role = ProjectUserRoleChoice.objects.get(name='User')
        project_user.save()
        response = self.client.get(url)
        self.assertNotContains(response, button_text)

        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(url)
        self.assertContains(response, button_text)

    def test_renew_allowance_button_conditionally_enabled(self):
        """Test that the 'Renew Allowance' button is only enabled
        under certain conditions."""
        project = self.create_active_project_with_pi('fc_project', self.user)
        create_project_allocation(project, Decimal('0.00'))

        project_detail_url = self.project_detail_url(project.pk)
        # The existence of the renewal URL on the page indicates that the
        # button is enabled.
        renewal_url = reverse('project-renew', kwargs={'pk': project.pk})

        # Create a second PI on the project.
        pi_2 = User.objects.create(
            email='pi_2@email.com',
            first_name='PI',
            last_name='2',
            username='pi_2')
        ProjectUser.objects.create(
            project=project,
            role=ProjectUserRoleChoice.objects.get(
                name='Principal Investigator'),
            status=ProjectUserStatusChoice.objects.get(name='Active'),
            user=pi_2)

        # 0/2 PIs have non-denied renewal requests under the current period.
        allocation_period = get_current_allowance_year_period()
        self.assertFalse(
            AllocationRenewalRequest.objects.filter(
                allocation_period=allocation_period,
                pi__in=[self.user, pi_2]).exists())
        response = self.client.get(project_detail_url)
        self.assertContains(response, renewal_url)

        # 1/2 PIs have non-denied renewal requests under the current period.
        under_review_request_status = \
            AllocationRenewalRequestStatusChoice.objects.get(
                name='Under Review')
        AllocationRenewalRequest.objects.create(
            requester=self.user,
            pi=self.user,
            allocation_period=allocation_period,
            status=under_review_request_status,
            pre_project=project,
            post_project=project,
            request_time=utc_now_offset_aware())
        response = self.client.get(project_detail_url)
        self.assertContains(response, renewal_url)

        denied_request_status = \
            AllocationRenewalRequestStatusChoice.objects.get(name='Denied')
        request_2 = AllocationRenewalRequest.objects.create(
            requester=self.user,
            pi=pi_2,
            allocation_period=allocation_period,
            status=denied_request_status,
            pre_project=project,
            post_project=project,
            request_time=utc_now_offset_aware())
        response = self.client.get(project_detail_url)
        self.assertContains(response, renewal_url)

        # 2/2 PIs have non-denied renewal requests under the current period.
        approved_request_status = \
            AllocationRenewalRequestStatusChoice.objects.get(name='Approved')
        request_2.status = approved_request_status
        request_2.save()
        response = self.client.get(project_detail_url)
        self.assertNotContains(response, renewal_url)

        # Renewals for the next allocation period can be requested.
        enable_flag('ALLOCATION_RENEWAL_FOR_NEXT_PERIOD_REQUESTABLE')
        response = self.client.get(project_detail_url)
        self.assertContains(response, renewal_url)

    def test_renew_allowance_button_conditionally_visible(self):
        """Test that the 'Renew Allowance' button is only visible to
        certain users for certain allocation types."""
        project = self.create_active_project_with_pi('project', self.user)
        create_project_allocation(project, Decimal('0.00'))

        url = self.project_detail_url(project.pk)
        button_text = 'Renew Allowance'

        project_user = ProjectUser.objects.get(project=project, user=self.user)

        all_roles = ProjectUserRoleChoice.objects.distinct()
        eligible_role_names = {'Manager', 'Principal Investigator'}

        all_project_prefixes = ('ac_', 'co_', 'fc_', 'ic_', 'pc_')
        eligible_project_prefixes = {'fc_'}

        expected_num_successes = len(eligible_role_names)
        actual_num_successes = 0
        expected_num_failures = (
            all_roles.count() * len(all_project_prefixes) -
            expected_num_successes)
        actual_num_failures = 0

        # Non-superuser, project member.
        self.assertFalse(self.user.is_superuser)
        for role in all_roles:
            project_user.role = role
            project_user.save()
            for prefix in all_project_prefixes:
                project.name = f'{prefix}_project'
                project.save()
                response = self.client.get(url)
                if (role.name in eligible_role_names and
                        prefix in eligible_project_prefixes):
                    self.assertContains(response, button_text)
                    actual_num_successes = actual_num_successes + 1
                else:
                    self.assertNotContains(response, button_text)
                    actual_num_failures = actual_num_failures + 1
        self.assertEqual(expected_num_successes, actual_num_successes)
        self.assertEqual(expected_num_failures, actual_num_failures)
        project_user.delete()

        # Superuser, non-(project member).
        self.user.is_superuser = True
        self.user.save()
        for prefix in all_project_prefixes:
            project.name = f'{prefix}_project'
            project.save()
            response = self.client.get(url)
            if prefix in eligible_project_prefixes:
                self.assertContains(response, button_text)
            else:
                self.assertNotContains(response, button_text)
        self.user.is_superuser = False
        self.user.save()

        # Staff, non-(project member).
        self.user.is_staff = True
        self.user.save()
        for prefix in all_project_prefixes:
            project.name = f'{prefix}_project'
            project.save()
            response = self.client.get(url)
            self.assertNotContains(response, button_text)
        self.user.is_staff = False
        self.user.save()

    # TODO
