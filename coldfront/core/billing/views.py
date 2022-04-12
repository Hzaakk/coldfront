from coldfront.core.allocation.models import Allocation
from coldfront.core.allocation.models import AllocationUserAttribute
from coldfront.core.billing.forms import BillingIDUpdateForm
from coldfront.core.billing.forms import BillingIDValidationForm
from coldfront.core.billing.models import BillingActivity
from coldfront.core.project.models import ProjectUser

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.models import User
from django.db.models import Q
from django.forms import formset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse
from django.urls import reverse_lazy
from django.views.generic.base import TemplateView
from django.views.generic.edit import FormView

import logging

# TODO: Replace this module with a directory as needed.


logger = logging.getLogger(__name__)


class UpdateAllocationBillingIDView(LoginRequiredMixin, UserPassesTestMixin,
                                    FormView):
    """Update the default Billing ID for the job usage fee for a
    specific Allocation."""

    form_class = BillingIDValidationForm
    template_name = 'billing/update_allocation_billing_id.html'
    login_url = '/'

    error_message = 'Unexpected failure. Please contact an administrator.'

    allocation_attribute_obj = None
    allocation_obj = None
    current_billing_id = '000000-000'

    def dispatch(self, request, *args, **kwargs):
        """TODO"""
        pk = self.kwargs.get('pk')
        self.allocation_obj = get_object_or_404(
            Allocation.objects.prefetch_related('allocationattribute_set'),
            pk=pk)

        allocation_view_redirect = HttpResponseRedirect(
            reverse('allocation-detail', kwargs={'pk': pk}))

        resource_name = 'LAWRENCIUM Compute'
        if not self.allocation_obj.resources.filter(
                name=resource_name).exists():
            message = (
                f'Project IDs for job usage are not relevant for '
                f'non-Lawrencium Allocation {pk}.')
            messages.error(request, message)
            return allocation_view_redirect

        project = self.allocation_obj.project
        if not project.name.startswith('ac_'):
            message = (
                f'Project IDs for job usage are not relevant for non-Recharge '
                f'Allocation {pk}.')
            messages.error(request, message)
            return allocation_view_redirect

        billing_activity_attributes = \
            self.allocation_obj.allocationattribute_set.filter(
                allocation_attribute_type__name='Billing Activity')
        num_billing_activity_attributes = billing_activity_attributes.count()
        if num_billing_activity_attributes == 0:
            pass
        elif num_billing_activity_attributes == 1:
            attribute = billing_activity_attributes.first()
            billing_activity_pk = int(attribute.value)
            try:
                billing_activity = BillingActivity.objects.get(
                    pk=billing_activity_pk)
            except BillingActivity.DoesNotExist:
                log_message = (
                    f'AllocationAttribute {attribute.pk} stores a '
                    f'BillingActivity primary key {billing_activity_pk} that '
                    f'does not exist.')
                logger.error(log_message)
                messages.error(request, self.error_message)
                return update_view_redirect
            self.allocation_attribute_obj = attribute
            self.current_billing_id = billing_activity.full_id()
        else:
            log_message = (
                f'Unexpectedly found multiple AllocationAttributes with '
                f'unique type "Billing Activity" for Allocation '
                f'{self.allocation_obj.pk}.')
            logger.error(log_message)
            messages.error(request, self.error_message)
            return update_view_redirect
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """TODO"""
        form_data = form.cleaned_data
        billing_id = form_data['billing_id']
        project_identifier, activity_identifier = billing_id.split('-')
        billing_activity = BillingActivity.objects.get(
            billing_project__identifier=project_identifier,
            identifier=activity_identifier,
            is_valid=True)
        self.allocation_attribute_obj.refresh_from_db()
        self.allocation_attribute_obj.value = billing_activity.pk
        self.allocation_attribute_obj.save()

        if self.current_billing_id != '000000-000':
            message = (
                f'Updated Project ID from {self.current_billing_id} to '
                f'{billing_id}.')
        else:
            message = f'Set Project ID to {billing_id}.'
        messages.success(self.request, message)

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        """TODO"""
        context = super().get_context_data(**kwargs)
        context['allocation'] = self.allocation_obj
        choices = []
        if self.current_billing_id != '000000-000':
            choices.append(self.current_billing_id)
        user_billing_activity_attribute_pks = set(
            self.allocation_obj.allocationuserattribute_set.filter(
                allocation_attribute_type__name='Billing Activity'
            ).values_list('pk', flat=True))
        user_billing_activities = BillingActivity.objects.filter(
            pk__in=user_billing_activity_attribute_pks)
        for user_billing_activity in user_billing_activities:
            choices.append(user_billing_activity.full_id())
        context['choices'] = choices
        return context

    def get_initial(self):
        """TODO"""
        initial = super().get_initial()
        initial['billing_id'] = self.current_billing_id
        return initial

    def get_success_url(self):
        """TODO"""
        return reverse(
            'allocation-detail', kwargs={'pk': self.allocation_obj.pk})

    def test_func(self):
        # TODO
        return True


class UpdateAllocationUserBillingIDsView(LoginRequiredMixin,
                                         UserPassesTestMixin, TemplateView):
    """Update the Billing IDs for job usage fee for AllocationUsers
    under a specific Allocation."""

    template_name = 'billing/update_allocation_user_billing_ids.html'

    allocation_obj = None

    def dispatch(self, request, *args, **kwargs):
        """TODO"""
        pk = self.kwargs.get('pk')
        self.allocation_obj = get_object_or_404(
            Allocation.objects.prefetch_related('allocationuser_set'), pk=pk)

        allocation_view_redirect = HttpResponseRedirect(
            reverse('allocation-detail', kwargs={'pk': pk}))

        resource_name = 'LAWRENCIUM Compute'
        if not self.allocation_obj.resources.filter(
                name=resource_name).exists():
            message = (
                f'Project IDs for job usage are not relevant for '
                f'non-Lawrencium Allocation {pk}.')
            messages.error(request, message)
            return allocation_view_redirect

        project = self.allocation_obj.project
        if not project.name.startswith('ac_'):
            message = (
                f'Project IDs for job usage are not relevant for non-Recharge '
                f'Allocation {pk}.')
            messages.error(request, message)
            return allocation_view_redirect

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """TODO"""
        allocation_users = self.allocation_obj.allocationuser_set.order_by(
            'user__username')

        formset_class = formset_factory(
            BillingIDUpdateForm, max_num=allocation_users.count())
        initial = []
        for allocation_user in allocation_users:
            user = allocation_user.user
            # TODO: Improve efficiency / handle errors.
            billing_attributes = \
                allocation_user.allocationuserattribute_set.filter(
                    allocation_attribute_type__name='Billing Activity')
            if billing_attributes.exists():
                current_billing_id = BillingActivity.objects.get(
                    pk=int(billing_attributes.first().value)).full_id()
            else:
                current_billing_id = ''
            initial.append({
                'selected': False,
                'name': f'{user.first_name} {user.last_name}',
                'email': user.email,
                'username': user.username,
                'current_billing_id': current_billing_id,
                'updated_billing_id': current_billing_id,
            })
        formset = formset_class(initial=initial, prefix='update_ids_form')

        context = dict()
        context['allocation'] = self.allocation_obj
        context['formset'] = formset

        return render(request, self.template_name, context)

    def test_func(self):
        """TODO"""
        return True


class UpdateUserBillingIDsView(LoginRequiredMixin, UserPassesTestMixin,
                               TemplateView):
    """Update the Billing IDs for the user account fee for Users
    associated with Projects managed by a specific User."""

    template_name = 'billing/update_user_billing_ids.html'

    managed_project_pks = None
    redirect = reverse_lazy('home')

    def dispatch(self, request, *args, **kwargs):
        """TODO"""
        # Retrieve primary keys for active Lawrencium Projects for which the
        # requesting User is an active PI or Manager.
        prefix_condition = (
            Q(project__name__startswith='ac_') |
            Q(project__name__startswith='fc_') |
            Q(project__name__startswith='lr_'))
        self.managed_project_pks = set(
            ProjectUser.objects.filter(
                prefix_condition &
                Q(project__status__name='Active') &
                Q(role__name__in=['Principal Investigator', 'Manager']) &
                Q(status__name='Active') &
                Q(user=request.user)).values_list('project__pk', flat=True))
        if not self.managed_project_pks:
            message = (
                'You do not have permission to update Project IDs for user '
                'account fees.')
            messages.error(request, message)
            return HttpResponseRedirect(self.redirect)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """TODO"""
        # Retrieve primary keys for compute Allocations associated with the
        # Projects.
        resource_name = 'LAWRENCIUM Compute'
        managed_allocation_pks = set(
            Allocation.objects.filter(
                project__pk__in=self.managed_project_pks,
                resources__name=resource_name,
                status__name='Active').values_list('pk', flat=True))

        # Retrieve Users who have active cluster access under these
        # Allocations.
        managed_user_pks = set(
            AllocationUserAttribute.objects.filter(
                allocation_attribute_type__name='Cluster Account Status',
                allocation__pk__in=managed_allocation_pks,
                value='Active'
            ).values_list('allocation_user__user__pk', flat=True))
        managed_users = User.objects.filter(
            pk__in=managed_user_pks).order_by('username')

        formset_class = formset_factory(BillingIDUpdateForm, max_num=managed_users.count())
        initial = []
        for user in managed_users:
            billing_activity = user.userprofile.billing_activity
            if isinstance(billing_activity, BillingActivity):
                current_billing_id = billing_activity.full_id()
            else:
                current_billing_id = ''
            initial.append({
                'selected': False,
                'name': f'{user.first_name} {user.last_name}',
                'email': user.email,
                'username': user.username,
                'current_billing_id': current_billing_id,
                'updated_billing_id': current_billing_id,
            })
        formset = formset_class(initial=initial, prefix='update_ids_form')

        context = dict()
        context['formset'] = formset

        return render(request, self.template_name, context)

    def test_func(self):
        """TODO"""
        return True