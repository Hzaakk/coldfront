from decimal import Decimal
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from coldfront.api.statistics.utils import create_project_allocation, \
    create_user_project_allocation
from coldfront.core.allocation.models import (Allocation,
                                              AllocationStatusChoice,
                                              SecureDirAddUserRequest,
                                              SecureDirAddUserRequestStatusChoice,
                                              SecureDirRemoveUserRequest,
                                              SecureDirRemoveUserRequestStatusChoice,
                                              AllocationUser,
                                              AllocationUserStatusChoice,
                                              SecureDirRequest,
                                              SecureDirRequestStatusChoice,
                                              AllocationAttribute,
                                              AllocationAttributeType)
from coldfront.core.allocation.tests.test_views.test_secure_dir_manage_users_views import \
    TestSecureDirBase
from coldfront.core.allocation.utils_.secure_dir_utils import create_secure_dirs
from coldfront.core.project.models import (ProjectUser,
                                           ProjectUserStatusChoice,
                                           ProjectUserRoleChoice, Project,
                                           ProjectStatusChoice)
from coldfront.core.resource.models import Resource
from coldfront.core.user.models import UserProfile
from coldfront.core.utils.common import utc_now_offset_aware
from coldfront.core.utils.tests.test_base import TestBase


class TestSecureDirRequestBase(TestBase):
    """A base testing class for secure directory manage user requests."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        # Create two PIs.
        for i in range(2):
            pi = User.objects.create(
                username=f'pi{i}', email=f'pi{i}@nonexistent.com')
            user_profile = UserProfile.objects.get(user=pi)
            user_profile.is_pi = True
            user_profile.save()
            setattr(self, f'pi{i}', pi)

        # Create two Users.
        for i in range(2):
            user = User.objects.create(
                username=f'user{i}', email=f'user{i}@nonexistent.com')
            user_profile = UserProfile.objects.get(user=user)
            user_profile.cluster_uid = f'{i}'
            user_profile.save()
            setattr(self, f'user{i}', user)
            setattr(self, f'user_profile{i}', user_profile)

        # Create Projects and associate Users with them.
        project_status = ProjectStatusChoice.objects.get(name='Active')
        project_user_status = ProjectUserStatusChoice.objects.get(
            name='Active')
        user_role = ProjectUserRoleChoice.objects.get(name='User')
        pi_role = ProjectUserRoleChoice.objects.get(
            name='Principal Investigator')
        for i in range(2):
            # Create a Project and ProjectUsers.
            project = Project.objects.create(
                name=f'fc_project{i}', status=project_status)
            setattr(self, f'project{i}', project)
            for j in range(2):
                ProjectUser.objects.create(
                    user=getattr(self, f'user{j}'), project=project,
                    role=user_role, status=project_user_status)
                ProjectUser.objects.create(
                    user=getattr(self, f'pi{j}'), project=project, role=pi_role,
                    status=project_user_status)

            # Create a compute allocation for the Project.
            allocation = Decimal(f'{i + 1}000.00')
            create_project_allocation(project, allocation)

            # Create a compute allocation for each User on the Project.
            for j in range(2):
                create_user_project_allocation(
                    getattr(self, f'user{j}'), project, allocation / 2)

        # Create superuser
        self.admin = User.objects.create(username='admin')
        self.admin.is_superuser = True
        self.admin.save()

        # Create staff user
        self.staff = User.objects.create(
            username='staff', email='staff@nonexistent.com', is_staff=True)

        self.password = 'password'
        for user in User.objects.all():
            self.sign_user_access_agreement(user)
            user.set_password(self.password)
            user.save()


class TestSecureDirRequestWizard(TestSecureDirRequestBase):
    """A class for testing SecureDirRequestWizard."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.url = 'secure-dir-request'

    def get_form_data(self):
        """Generates valid form data for SecureDirRequestWizard."""
        view_name = 'secure_dir_request_wizard'
        current_step_key = f'{view_name}-current_step'
        data_description_form_data = {
            '0-data_description': 'a' * 20,
            '0-rdm_consultation': True,
            current_step_key: '0',
        }
        rdm_consultation_form_data = {
            '1-rdm_consultants': 'Tom and Jerry',
            current_step_key: '1',
        }
        existing_pi_form_data = {
            '2-PI': self.pi0.pk,
            current_step_key: '2',
        }
        existing_project_data = {
            '3-project': self.project1.pk,
            current_step_key: '3',
        }
        form_data = [
            data_description_form_data,
            rdm_consultation_form_data,
            existing_pi_form_data,
            existing_project_data,
        ]

        return form_data

    def test_access(self):
        url = reverse(self.url)
        self.assert_has_access(url, self.admin, True)
        self.assert_has_access(url, self.pi0, True)
        self.assert_has_access(url, self.pi1, True)
        self.assert_has_access(url, self.user0, False)

    def test_post_creates_request(self):
        """Test that a POST request creates a SecureDirRequest."""
        self.assertEqual(SecureDirRequest.objects.count(), 0)

        pre_time = utc_now_offset_aware()
        form_data = self.get_form_data()

        self.client.login(username=self.pi0.username, password=self.password)
        for i, data in enumerate(form_data):
            response = self.client.post(reverse(self.url), data)
            if i == len(form_data) - 1:
                self.assertRedirects(response, reverse('home'))

            else:
                self.assertEqual(response.status_code, HTTPStatus.OK)

        requests = SecureDirRequest.objects.all()
        self.assertEqual(requests.count(), 1)

        request = requests.first()
        self.assertEqual(request.requester, self.pi0)
        self.assertEqual(
            request.data_description,
            form_data[0]['0-data_description'])
        self.assertEqual(
            request.rdm_consultation,
            form_data[1]['1-rdm_consultants'])
        self.assertEqual(request.pi, self.pi0)
        self.assertEqual(request.project, self.project1)
        self.assertTrue(
            pre_time < request.request_time < utc_now_offset_aware())
        self.assertTrue(request.completion_time is None)
        self.assertEqual(request.status.name, 'Under Review')

    def test_emails_sent(self):
        """Test that a POST request sends the correct emails."""

        form_data = self.get_form_data()

        self.client.login(username=self.pi1.username, password=self.password)
        for i, data in enumerate(form_data):
            response = self.client.post(reverse(self.url), data)
            if i == len(form_data) - 1:
                self.assertRedirects(response, reverse('home'))
            else:
                self.assertEqual(response.status_code, HTTPStatus.OK)

        # Test that the correct emails are sent.
        admin_email = settings.EMAIL_ADMIN_LIST
        pi0_email = self.pi0.email
        pi_email_body = [f'There is a new secure directory request for '
                         f'project {self.project1.name} from requester '
                         f'{self.pi1.first_name} {self.pi1.last_name}'
                         f' ({self.pi1.email})',
                         f'You may view the details of the request here:']
        admin_email_body = [f'There is a new secure directory request for '
                            f'project {self.project1.name} under PI '
                            f'{self.pi0.first_name} {self.pi0.last_name}'
                            f' ({self.pi0.email}) from requester '
                            f'{self.pi1.first_name} {self.pi1.last_name}'
                            f' ({self.pi1.email}).',
                            'Please review the request here:']

        self.assertEqual(2, len(mail.outbox))
        for email in mail.outbox:
            if email.to[0] in admin_email:
                for section in admin_email_body:
                    self.assertIn(section, email.body)
            elif email.to[0] == pi0_email:
                for section in pi_email_body:
                    self.assertIn(section, email.body)
            else:
                self.fail(f'Emails should only be sent to PI0 and admins.')
            self.assertEqual(settings.EMAIL_SENDER, email.from_email)


class TestSecureDirRequestListView(TestSecureDirRequestBase):
    """A class for testing SecureDirRequestListView"""

    def setUp(self):
        super().setUp()

        self.completed_url = reverse('secure-dir-completed-request-list')
        self.pending_url = reverse('secure-dir-pending-request-list')

        # Create 2 SecureDirRequests
        self.request0 = SecureDirRequest.objects.create(
            requester=self.pi0,
            data_description='a'*20,
            pi=self.pi0,
            project=self.project0,
            status=SecureDirRequestStatusChoice.objects.get(name='Under Review'),
            request_time=utc_now_offset_aware()
        )

        self.request1 = SecureDirRequest.objects.create(
            requester=self.pi1,
            data_description='a'*20,
            pi=self.pi1,
            project=self.project1,
            status=SecureDirRequestStatusChoice.objects.get(name='Under Review'),
            request_time=utc_now_offset_aware()
        )

    def test_access(self):
        for url in [self.completed_url, self.pending_url]:
            self.assert_has_access(url, self.admin, True)
            self.assert_has_access(url, self.staff, True)
            self.assert_has_access(url, self.user0, False)
            self.assert_has_access(url, self.pi0, False)

    def test_pending_requests(self):
        """Test that pending requests are visible."""
        self.request1.status = \
            SecureDirRequestStatusChoice.objects.get(name='Approved - Processing')
        self.request1.save()
        self.request1.refresh_from_db()

        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.get(self.pending_url)

        format_badge = '<span class="badge badge-warning">{}</span>'
        self.assertContains(response, self.project0.name)
        self.assertContains(response,
                            format_badge.format(self.request0.status.name))
        self.assertContains(response, self.project1.name)
        self.assertContains(response,
                            format_badge.format(self.request1.status.name))

        # Testing that the correct title is displayed.
        self.assertContains(response, 'Pending Secure Directory Requests')

    def test_no_pending_requests(self):
        """Test that the correct content is displayed when there are no
        pending requests."""
        for request in SecureDirRequest.objects.all():
            request.status = \
                SecureDirRequestStatusChoice.objects.get(name='Denied')
            request.save()

        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.get(self.pending_url)

        self.assertNotContains(response, self.project0.name)
        self.assertNotContains(response, self.request0.status.name)
        self.assertNotContains(response, self.project1.name)
        self.assertNotContains(response, self.request1.status.name)

        self.assertContains(response, 'No pending secure directory requests!')

        # Testing that the correct title is displayed.
        self.assertContains(response, 'Pending Secure Directory Requests')

    def test_completed_requests(self):
        """Test that completed requests are visible."""
        self.request0.status = \
            SecureDirRequestStatusChoice.objects.get(name='Approved - Complete')
        self.request0.save()
        self.request1.status = \
            SecureDirRequestStatusChoice.objects.get(name='Denied')
        self.request1.save()

        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.get(self.completed_url)

        self.assertContains(response, self.project0.name)
        self.assertContains(response,
                            '<span class="badge badge-success">Approved - Complete</span>')
        self.assertContains(response, self.project1.name)
        self.assertContains(response,
                            '<span class="badge badge-danger">Denied</span>')

        # Testing that the correct title is displayed.
        self.assertContains(response, 'Completed Secure Directory Requests')

    def test_no_completed_requests(self):
        """Test that the correct content is displayed when there are no
        completed requests."""
        for request in SecureDirRequest.objects.all():
            request.status = \
                SecureDirRequestStatusChoice.objects.get(name='Under Review')
            request.save()

        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.get(self.completed_url)

        self.assertNotContains(response, self.project0.name)
        self.assertNotContains(response, self.request0.status.name)
        self.assertNotContains(response, self.project1.name)
        self.assertNotContains(response, self.request1.status.name)

        self.assertContains(response, 'No completed secure directory requests!')

        # Testing that the correct title is displayed.
        self.assertContains(response, 'Completed Secure Directory Requests')


class TestSecureDirRequestDetailView(TestSecureDirRequestBase):
    """Testing class for SecureDirRequestDetailView"""

    def setUp(self):
        super().setUp()

        # Create SecureDirRequest
        self.request0 = SecureDirRequest.objects.create(
            requester=self.pi0,
            data_description='a'*20,
            pi=self.pi0,
            project=self.project0,
            status=SecureDirRequestStatusChoice.objects.get(name='Approved - Processing'),
            request_time=utc_now_offset_aware()
        )

        self.request0.state['rdm_consultation']['status'] = 'Completed'
        self.request0.state['mou']['status'] = 'Completed'
        self.request0.state['setup']['status'] = 'Completed'
        self.request0.state['setup']['groups'] = 'test_groups'
        self.request0.state['setup']['scratch'] = 'test_scratch'
        self.request0.save()

        self.url0 = reverse('secure-dir-request-detail',
                            kwargs={'pk': self.request0.pk})

    def test_access(self):
        self.assert_has_access(self.url0, self.admin, True)
        self.assert_has_access(self.url0, self.staff, True)
        self.assert_has_access(self.url0, self.user0, False)
        self.assert_has_access(self.url0, self.pi0, False)

    def test_post_request_approves_request(self):
        """Test that a POST request approves the SecureDirRequest."""
        pre_time = utc_now_offset_aware()
        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.post(self.url0, {})

        self.request0.refresh_from_db()
        self.assertRedirects(response, reverse('secure-dir-pending-request-list'))
        self.assertEqual(self.request0.status.name, 'Approved - Complete')
        self.assertTrue(pre_time < self.request0.completion_time < utc_now_offset_aware())

    def test_post_request_creates_allocations(self):
        """Test that a POST request creates the correct allocations."""
        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.post(self.url0, {})

        # Test that the groups directory is created correctly.
        groups_p2p3_directory = Resource.objects.get(name='Groups P2/P3 Directory')
        groups_alloc = Allocation.objects.filter(
            project=self.project0,
            resources__in=[groups_p2p3_directory])
        self.assertTrue(groups_alloc.exists())

        alloc_attr = AllocationAttribute.objects.filter(
            allocation=groups_alloc.first(),
            allocation_attribute_type=AllocationAttributeType.objects.get(
                name='Cluster Directory Access')
        )
        self.assertTrue(alloc_attr.exists())
        alloc_attr = alloc_attr.first()
        self.assertTrue(alloc_attr.value.endswith(self.request0.state['setup']['groups']))

        # Test that the scratch directory is created correctly.
        scratch_p2p3_directory = Resource.objects.get(name='Scratch2 P2/P3 Directory')
        scratch_alloc = Allocation.objects.filter(
            project=self.project0,
            resources__in=[scratch_p2p3_directory])
        self.assertTrue(scratch_alloc.exists())

        alloc_attr = AllocationAttribute.objects.filter(
            allocation=scratch_alloc.first(),
            allocation_attribute_type=AllocationAttributeType.objects.get(
                name='Cluster Directory Access')
        )
        self.assertTrue(alloc_attr.exists())
        alloc_attr = alloc_attr.first()
        self.assertTrue(alloc_attr.value.endswith(self.request0.state['setup']['scratch']))

    def test_post_request_emails_sent(self):
        """Test that a POST request sends the correct emails."""
        self.client.login(username=self.admin.username, password=self.password)
        response = self.client.post(self.url0, {})

        # Test that the correct emails are sent.
        pi_emails = self.project0.projectuser_set.filter(
            role__name='Principal Investigator'
        ).values_list('user__email', flat=True)
        email_body = [f'Your request for a secure directory for project '
                      f'\'{self.project0.name}\' was approved. Setup '
                      f'on the cluster is complete.',
                      f'The paths to your secure group and scratch directories '
                      f'are \'/global/home/groups/pl1_data/'
                      f'{self.request0.state["setup"]["groups"]}\' and '
                      f'\'/global/scratch/pl1_data/'
                      f'{self.request0.state["setup"]["scratch"]}\', '
                      f'respectively.']

        self.assertEqual(len(pi_emails), len(mail.outbox))
        for email in mail.outbox:
            self.assertIn(email.to[0], pi_emails)
            for section in email_body:
                self.assertIn(section, email.body)
            self.assertEqual(settings.EMAIL_SENDER, email.from_email)