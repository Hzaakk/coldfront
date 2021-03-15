import datetime
import pprint

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Case, CharField, F, Q, Value, When
from django.forms import formset_factory
from django.http import (HttpResponse, HttpResponseForbidden,
                         HttpResponseRedirect)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.base import TemplateView
from django.views.generic.edit import FormView

from coldfront.core.allocation.models import (Allocation,
                                              AllocationStatusChoice,
                                              AllocationUser,
                                              AllocationUserAttribute,
                                              AllocationUserStatusChoice)
from coldfront.core.allocation.utils import get_allocation_user_cluster_access_status
from coldfront.core.allocation.signals import (allocation_activate_user,
                                               allocation_remove_user)
# from coldfront.core.grant.models import Grant
from coldfront.core.project.forms import (ProjectAddUserForm,
                                          ProjectAddUsersToAllocationForm,
                                          ProjectRemoveUserForm,
                                          ProjectReviewEmailForm,
                                          ProjectReviewForm,
                                          ProjectReviewUserJoinForm,
                                          ProjectSearchForm,
                                          ProjectUserUpdateForm)
from coldfront.core.project.models import (Project, ProjectReview,
                                           ProjectReviewStatusChoice,
                                           ProjectStatusChoice, ProjectUser,
                                           ProjectUserRoleChoice,
                                           ProjectUserStatusChoice)
from coldfront.core.project.utils import get_project_compute_allocation
# from coldfront.core.publication.models import Publication
# from coldfront.core.research_output.models import ResearchOutput
from coldfront.core.user.forms import UserSearchForm
from coldfront.core.user.utils import CombinedUserSearch
from coldfront.core.utils.common import get_domain_url, import_from_settings
from coldfront.core.utils.mail import send_email, send_email_template

EMAIL_ENABLED = import_from_settings('EMAIL_ENABLED', False)
ALLOCATION_ENABLE_ALLOCATION_RENEWAL = import_from_settings(
    'ALLOCATION_ENABLE_ALLOCATION_RENEWAL', True)
ALLOCATION_DEFAULT_ALLOCATION_LENGTH = import_from_settings(
    'ALLOCATION_DEFAULT_ALLOCATION_LENGTH', 365)

if EMAIL_ENABLED:
    EMAIL_DIRECTOR_EMAIL_ADDRESS = import_from_settings(
        'EMAIL_DIRECTOR_EMAIL_ADDRESS')
    EMAIL_SENDER = import_from_settings('EMAIL_SENDER')


class ProjectDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Project
    template_name = 'project/project_detail.html'
    context_object_name = 'project'

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        if self.request.user.has_perm('project.can_view_all_projects'):
            return True

        project_obj = self.get_object()

        if project_obj.projectuser_set.filter(user=self.request.user, status__name='Active').exists():
            return True

        messages.error(
            self.request, 'You do not have permission to view the previous page.')
        return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Can the user archive the project?
        if self.request.user.is_superuser:
            context['is_allowed_to_archive_project'] = True
        else:
            context['is_allowed_to_archive_project'] = False

        # Can the user update the project?
        if self.request.user.is_superuser:
            context['is_allowed_to_update_project'] = True
        elif self.object.projectuser_set.filter(user=self.request.user).exists():
            project_user = self.object.projectuser_set.get(user=self.request.user)
            if project_user.role.name in ('Principal Investigator', 'Manager'):
                context['is_allowed_to_update_project'] = True
                context['username'] = project_user.user.username
            else:
                context['is_allowed_to_update_project'] = False
        else:
            context['is_allowed_to_update_project'] = False

        # Retrieve cluster access statuses.
        cluster_access_statuses = {}
        try:
            allocation_obj = get_project_compute_allocation(self.object)
            statuses = \
                allocation_obj.allocationuserattribute_set.select_related(
                    'allocation_user__user'
                ).filter(
                    allocation_attribute_type__name='Cluster Account Status',
                    value__in=['Pending - Add', 'Active'])
            for status in statuses:
                username = status.allocation_user.user.username
                cluster_access_statuses[username] = status.value
        except (Allocation.DoesNotExist, Allocation.MultipleObjectsReturned):
            pass

        whens = [
            When(user__username=username, then=Value(status))
            for username, status in cluster_access_statuses.items()
        ]

        # Only show 'Active Users'
        project_users = self.object.projectuser_set.select_related(
            'user'
        ).filter(
            status__name='Active'
        ).annotate(
            cluster_access_status=Case(
                *whens,
                default=Value('None'),
                output_field=CharField(),
            )
        ).order_by('user__username')

        context['mailto'] = 'mailto:' + \
            ','.join([user.user.email for user in project_users])

        if self.request.user.is_superuser or self.request.user.has_perm('allocation.can_view_all_allocations'):
            allocations = Allocation.objects.prefetch_related(
                'resources').filter(project=self.object).order_by('-end_date')
        else:
            if self.object.status.name in ['Active', 'New', ]:
                allocations = Allocation.objects.filter(
                    Q(project=self.object) &
                    Q(project__projectuser__user=self.request.user) &
                    Q(project__projectuser__status__name__in=['Active', ]) &
                    Q(status__name__in=['Active', 'Expired',
                                        'New', 'Renewal Requested',
                                        'Payment Pending', 'Payment Requested',
                                        'Payment Declined', 'Paid']) &
                    Q(allocationuser__user=self.request.user) &
                    Q(allocationuser__status__name__in=['Active', ])
                ).distinct().order_by('-end_date')
            else:
                allocations = Allocation.objects.prefetch_related(
                    'resources').filter(project=self.object)

        context['num_join_requests'] = self.object.projectuser_set.filter(
            status__name='Pending - Add').count()

        # context['publications'] = Publication.objects.filter(project=self.object, status='Active').order_by('-year')
        # context['research_outputs'] = ResearchOutput.objects.filter(project=self.object).order_by('-created')
        # context['grants'] = Grant.objects.filter(project=self.object, status__name__in=['Active', 'Pending'])
        context['allocations'] = allocations
        context['project_users'] = project_users
        context['ALLOCATION_ENABLE_ALLOCATION_RENEWAL'] = ALLOCATION_ENABLE_ALLOCATION_RENEWAL

        # Can the user request cluster access on own or others' behalf?
        try:
            allocation = Allocation.objects.get(
                project=self.object, status__name='Active',
                resources__name='Savio Compute')
        except Allocation.DoesNotExist:
            savio_compute_allocation_pk = None
            cluster_accounts_requestable = False
            cluster_accounts_tooltip = 'Unexpected server error.'
        except Allocation.MultipleObjectsReturned:
            savio_compute_allocation_pk = None
            cluster_accounts_requestable = False
            cluster_accounts_tooltip = 'Unexpected server error.'
        else:
            savio_compute_allocation_pk = allocation.pk
            cluster_accounts_requestable = True
            if context['is_allowed_to_update_project']:
                cluster_accounts_tooltip = (
                    'Request access to the cluster under this project on '
                    'behalf of users.')
            else:
                cluster_accounts_tooltip = (
                    'Request access to the cluster under this project.')
        context['savio_compute_allocation_pk'] = savio_compute_allocation_pk
        context['cluster_accounts_requestable'] = cluster_accounts_requestable
        context['cluster_accounts_tooltip'] = cluster_accounts_tooltip

        return context


class ProjectListView(LoginRequiredMixin, ListView):

    model = Project
    template_name = 'project/project_list.html'
    prefetch_related = ['status', 'field_of_science', ]
    context_object_name = 'project_list'
    paginate_by = 25

    def get_queryset(self):

        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            if direction == 'asc':
                direction = ''
            else:
                direction = '-'
            order_by = direction + order_by
        else:
            order_by = 'id'

        project_search_form = ProjectSearchForm(self.request.GET)

        if project_search_form.is_valid():
            data = project_search_form.cleaned_data
            if data.get('show_all_projects') and (self.request.user.is_superuser or self.request.user.has_perm('project.can_view_all_projects')):
                projects = Project.objects.prefetch_related('field_of_science', 'status',).filter(
                    status__name__in=['New', 'Active', ]
                ).annotate(
                    cluster_name=Case(
                        When(name__startswith='vector_', then=Value('Vector')),
                        default=Value('Savio'),
                        output_field=CharField(),
                    )
                ).order_by(order_by)
            else:
                projects = Project.objects.prefetch_related('field_of_science', 'status',).filter(
                    Q(status__name__in=['New', 'Active', ]) &
                    Q(projectuser__user=self.request.user) &
                    Q(projectuser__status__name='Active')
                ).annotate(
                    cluster_name=Case(
                        When(name__startswith='vector_', then=Value('Vector')),
                        default=Value('Savio'),
                        output_field=CharField(),
                    ),
                ).order_by(order_by)

            # Last Name
            if data.get('last_name'):
                pi_project_users = ProjectUser.objects.filter(
                    project__in=projects,
                    role__name='Principal Investigator',
                    user__last_name__icontains=data.get('last_name'))
                project_ids = pi_project_users.values_list(
                    'project_id', flat=True)
                projects = projects.filter(id__in=project_ids)

            # Username
            if data.get('username'):
                projects = projects.filter(
                    Q(projectuser__user__username__icontains=data.get(
                        'username')) &
                    (Q(projectuser__role__name='Principal Investigator') |
                     Q(projectuser__status__name='Active'))
                )

            # Field of Science
            if data.get('field_of_science'):
                projects = projects.filter(
                    field_of_science__description__icontains=data.get('field_of_science'))

            # Project Title
            if data.get('project_title'):
                projects = projects.filter(title__icontains=data.get('project_title'))

            # Project Name
            if data.get('project_name'):
                projects = projects.filter(name__icontains=data.get('project_name'))

            # Cluster Name
            if data.get('cluster_name'):
                projects = projects.filter(cluster_name__icontains=data.get('cluster_name'))

        else:
            projects = Project.objects.prefetch_related('field_of_science', 'status',).filter(
                Q(status__name__in=['New', 'Active', ]) &
                Q(projectuser__user=self.request.user) &
                Q(projectuser__status__name='Active')
            ).annotate(
                cluster_name=Case(
                    When(name__startswith='vector_', then=Value('Vector')),
                    default=Value('Savio'),
                    output_field=CharField(),
                ),
            ).order_by(order_by)

        return projects.distinct()

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)
        projects_count = self.get_queryset().count()
        context['projects_count'] = projects_count

        project_search_form = ProjectSearchForm(self.request.GET)
        if project_search_form.is_valid():
            context['project_search_form'] = project_search_form
            data = project_search_form.cleaned_data
            filter_parameters = ''
            for key, value in data.items():
                if value:
                    if isinstance(value, list):
                        for ele in value:
                            filter_parameters += '{}={}&'.format(key, ele)
                    else:
                        filter_parameters += '{}={}&'.format(key, value)
            context['project_search_form'] = project_search_form
        else:
            filter_parameters = None
            context['project_search_form'] = ProjectSearchForm()

        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            filter_parameters_with_order_by = filter_parameters + \
                'order_by=%s&direction=%s&' % (order_by, direction)
        else:
            filter_parameters_with_order_by = filter_parameters

        if filter_parameters:
            context['expand_accordion'] = 'show'

        context['filter_parameters'] = filter_parameters
        context['filter_parameters_with_order_by'] = filter_parameters_with_order_by

        project_list = context.get('project_list')
        paginator = Paginator(project_list, self.paginate_by)

        page = self.request.GET.get('page')

        try:
            project_list = paginator.page(page)
        except PageNotAnInteger:
            project_list = paginator.page(1)
        except EmptyPage:
            project_list = paginator.page(paginator.num_pages)

        return context


class ProjectArchivedListView(LoginRequiredMixin, ListView):

    model = Project
    template_name = 'project/project_archived_list.html'
    prefetch_related = ['status', 'field_of_science', ]
    context_object_name = 'project_list'
    paginate_by = 10

    def get_queryset(self):

        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            if direction == 'asc':
                direction = ''
            else:
                direction = '-'
            order_by = direction + order_by
        else:
            order_by = 'id'

        project_search_form = ProjectSearchForm(self.request.GET)

        if project_search_form.is_valid():
            data = project_search_form.cleaned_data
            if data.get('show_all_projects') and (self.request.user.is_superuser or self.request.user.has_perm('project.can_view_all_projects')):
                projects = Project.objects.prefetch_related('field_of_science', 'status',).filter(
                    status__name__in=['Archived', ]).order_by(order_by)
            else:

                projects = Project.objects.prefetch_related('field_of_science', 'status',).filter(
                    Q(status__name__in=['Archived', ]) &
                    Q(projectuser__user=self.request.user) &
                    Q(projectuser__status__name='Active')
                ).order_by(order_by)

            # Last Name
            if data.get('last_name'):
                pi_project_users = ProjectUser.objects.filter(
                    project__in=projects,
                    role__name='Principal Investigator',
                    user__last_name__icontains=data.get('last_name'))
                project_ids = pi_project_users.values_list(
                    'project_id', flat=True)
                projects = projects.filter(id__in=project_ids)

            # Username
            if data.get('username'):
                projects = projects.filter(
                    projectuser__user__username__icontains=data.get('username'),
                    projectuser__role__name='Principal Investigator')

            # Field of Science
            if data.get('field_of_science'):
                projects = projects.filter(
                    field_of_science__description__icontains=data.get('field_of_science'))

            # Project Title
            if data.get('project_title'):
                projects = projects.filter(title__icontains=data.get('project_title'))

            # Project Name
            if data.get('project_name'):
                projects = projects.filter(name__icontains=data.get('project_name'))

        else:
            projects = Project.objects.prefetch_related('field_of_science', 'status',).filter(
                Q(status__name__in=['Archived', ]) &
                Q(projectuser__user=self.request.user) &
                Q(projectuser__status__name='Active')
            ).order_by(order_by)

        return projects

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)
        projects_count = self.get_queryset().count()
        context['projects_count'] = projects_count
        context['expand'] = False

        project_search_form = ProjectSearchForm(self.request.GET)
        if project_search_form.is_valid():
            context['project_search_form'] = project_search_form
            data = project_search_form.cleaned_data
            filter_parameters = ''
            for key, value in data.items():
                if value:
                    if isinstance(value, list):
                        for ele in value:
                            filter_parameters += '{}={}&'.format(key, ele)
                    else:
                        filter_parameters += '{}={}&'.format(key, value)
            context['project_search_form'] = project_search_form
        else:
            filter_parameters = None
            context['project_search_form'] = ProjectSearchForm()

        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            filter_parameters_with_order_by = filter_parameters + \
                'order_by=%s&direction=%s&' % (order_by, direction)
        else:
            filter_parameters_with_order_by = filter_parameters

        if filter_parameters:
            context['expand_accordion'] = 'show'

        context['filter_parameters'] = filter_parameters
        context['filter_parameters_with_order_by'] = filter_parameters_with_order_by

        project_list = context.get('project_list')
        paginator = Paginator(project_list, self.paginate_by)

        page = self.request.GET.get('page')

        try:
            project_list = paginator.page(page)
        except PageNotAnInteger:
            project_list = paginator.page(1)
        except EmptyPage:
            project_list = paginator.page(paginator.num_pages)

        return context


class ProjectArchiveProjectView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'project/project_archive.html'

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        if self.request.method == 'POST':
            return False

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get('pk')
        project = get_object_or_404(Project, pk=pk)

        context['project'] = project
        context['is_allowed_to_archive_project'] = self.request.user.is_superuser

        return context

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        project = get_object_or_404(Project, pk=pk)
        project_status_archive = ProjectStatusChoice.objects.get(
            name='Archived')
        allocation_status_expired = AllocationStatusChoice.objects.get(
            name='Expired')
        end_date = datetime.datetime.now()
        project.status = project_status_archive
        project.save()
        for allocation in project.allocation_set.filter(status__name='Active'):
            allocation.status = allocation_status_expired
            allocation.end_date = end_date
            allocation.save()
        return redirect(reverse('project-detail', kwargs={'pk': project.pk}))


class ProjectCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Project
    template_name_suffix = '_create_form'
    fields = ['title', 'description', 'field_of_science', ]

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        if self.request.user.userprofile.is_pi:
            return True

    def form_valid(self, form):
        project_obj = form.save(commit=False)
        form.instance.status = ProjectStatusChoice.objects.get(name='New')
        project_obj.save()
        self.object = project_obj

        project_user_obj = ProjectUser.objects.create(
            user=self.request.user,
            project=project_obj,
            role=ProjectUserRoleChoice.objects.get(name='Manager'),
            status=ProjectUserStatusChoice.objects.get(name='Active')
        )

        return super().form_valid(form)

    def get_success_url(self):
        return reverse('project-detail', kwargs={'pk': self.object.pk})


class ProjectUpdateView(SuccessMessageMixin, LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Project
    template_name_suffix = '_update_form'
    fields = [
        'title',
        'description',
        'field_of_science',
        'joins_require_approval',
    ]
    success_message = 'Project updated.'

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = self.get_object()

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        if project_obj.status.name not in ['Active', 'New', ]:
            messages.error(request, 'You cannot update an archived project.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('project-detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        # If joins_require_approval is set to False, automatically approve all
        # pending join requests.
        joins_require_approval = form.cleaned_data['joins_require_approval']
        if not joins_require_approval:
            project_obj = self.get_object()
            active_status = ProjectUserStatusChoice.objects.get(name='Active')
            num_requests_approved = project_obj.projectuser_set.filter(
                status__name='Pending - Add').update(status=active_status)
            message = (
                f'Join requests no longer require approval, so '
                f'{num_requests_approved} pending requests were automatically '
                f'approved.')
            messages.warning(self.request, message)
        return super().form_valid(form)


class ProjectAddUsersSearchView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'project/project_add_users.html'

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        if project_obj.status.name not in ['Active', 'New', ]:
            messages.error(
                request, 'You cannot add users to an archived project.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['user_search_form'] = UserSearchForm()
        context['project'] = Project.objects.get(pk=self.kwargs.get('pk'))
        return context


class ProjectAddUsersSearchResultsView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'project/add_user_search_results.html'
    raise_exception = True

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        if project_obj.status.name not in ['Active', 'New', ]:
            messages.error(
                request, 'You cannot add users to an archived project.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        user_search_string = request.POST.get('q')
        search_by = request.POST.get('search_by')
        pk = self.kwargs.get('pk')

        project_obj = get_object_or_404(Project, pk=pk)

        users_to_exclude = [ele.user.username for ele in project_obj.projectuser_set.filter(
            status__name='Active')]

        cobmined_user_search_obj = CombinedUserSearch(
            user_search_string, search_by, users_to_exclude)

        context = cobmined_user_search_obj.search()

        matches = context.get('matches')
        for match in matches:
            match.update(
                {'role': ProjectUserRoleChoice.objects.get(name='User')})

        if matches:
            formset = formset_factory(ProjectAddUserForm, max_num=len(matches))
            formset = formset(initial=matches, prefix='userform')
            context['formset'] = formset
            context['user_search_string'] = user_search_string
            context['search_by'] = search_by

        users_already_in_project = []
        for ele in user_search_string.split():
            if ele in users_to_exclude:
                users_already_in_project.append(ele)
        context['users_already_in_project'] = users_already_in_project

        # The following block of code is used to hide/show the allocation div in the form.
        if project_obj.allocation_set.filter(status__name__in=['Active', 'New', 'Renewal Requested']).exists():
            div_allocation_class = 'placeholder_div_class'
        else:
            div_allocation_class = 'd-none'
        context['div_allocation_class'] = div_allocation_class
        ###

        allocation_form = ProjectAddUsersToAllocationForm(
            request.user, project_obj.pk, prefix='allocationform')
        context['pk'] = pk
        context['allocation_form'] = allocation_form
        return render(request, self.template_name, context)


class ProjectAddUsersView(LoginRequiredMixin, UserPassesTestMixin, View):

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        if project_obj.status.name not in ['Active', 'New', ]:
            messages.error(
                request, 'You cannot add users to an archived project.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        user_search_string = request.POST.get('q')
        search_by = request.POST.get('search_by')
        pk = self.kwargs.get('pk')

        project_obj = get_object_or_404(Project, pk=pk)

        users_to_exclude = [ele.user.username for ele in project_obj.projectuser_set.filter(
            status__name='Active')]

        cobmined_user_search_obj = CombinedUserSearch(
            user_search_string, search_by, users_to_exclude)

        context = cobmined_user_search_obj.search()

        matches = context.get('matches')
        for match in matches:
            match.update(
                {'role': ProjectUserRoleChoice.objects.get(name='User')})

        formset = formset_factory(ProjectAddUserForm, max_num=len(matches))
        formset = formset(request.POST, initial=matches, prefix='userform')

        allocation_form = ProjectAddUsersToAllocationForm(
            request.user, project_obj.pk, request.POST, prefix='allocationform')

        added_users_count = 0
        if formset.is_valid() and allocation_form.is_valid():
            project_user_active_status_choice = ProjectUserStatusChoice.objects.get(
                name='Active')
            allocation_user_active_status_choice = AllocationUserStatusChoice.objects.get(
                name='Active')
            allocation_form_data = allocation_form.cleaned_data['allocation']
            if '__select_all__' in allocation_form_data:
                allocation_form_data.remove('__select_all__')
            for form in formset:
                user_form_data = form.cleaned_data
                if user_form_data['selected']:
                    added_users_count += 1

                    # Will create local copy of user if not already present in local database
                    user_obj, _ = User.objects.get_or_create(
                        username=user_form_data.get('username'))
                    user_obj.first_name = user_form_data.get('first_name')
                    user_obj.last_name = user_form_data.get('last_name')
                    user_obj.email = user_form_data.get('email')
                    user_obj.save()

                    role_choice = user_form_data.get('role')
                    # Is the user already in the project?
                    if project_obj.projectuser_set.filter(user=user_obj).exists():
                        project_user_obj = project_obj.projectuser_set.get(
                            user=user_obj)
                        project_user_obj.role = role_choice
                        project_user_obj.status = project_user_active_status_choice
                        project_user_obj.save()
                    else:
                        project_user_obj = ProjectUser.objects.create(
                            user=user_obj, project=project_obj, role=role_choice, status=project_user_active_status_choice)

                    for allocation in Allocation.objects.filter(pk__in=allocation_form_data):
                        if allocation.allocationuser_set.filter(user=user_obj).exists():
                            allocation_user_obj = allocation.allocationuser_set.get(
                                user=user_obj)
                            allocation_user_obj.status = allocation_user_active_status_choice
                            allocation_user_obj.save()
                        else:
                            allocation_user_obj = AllocationUser.objects.create(
                                allocation=allocation,
                                user=user_obj,
                                status=allocation_user_active_status_choice)
                        allocation_activate_user.send(sender=self.__class__,
                                                      allocation_user_pk=allocation_user_obj.pk)

            messages.success(
                request, 'Added {} users to project.'.format(added_users_count))
        else:
            if not formset.is_valid():
                for error in formset.errors:
                    messages.error(request, error)

            if not allocation_form.is_valid():
                for error in allocation_form.errors:
                    messages.error(request, error)

        return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': pk}))


class ProjectRemoveUsersView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'project/project_remove_users.html'

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        if project_obj.status.name not in ['Active', 'New', ]:
            messages.error(
                request, 'You cannot remove users from an archived project.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            return super().dispatch(request, *args, **kwargs)

    def get_users_to_remove(self, project_obj):
        users_to_remove = [

            {'username': ele.user.username,
             'first_name': ele.user.first_name,
             'last_name': ele.user.last_name,
             'email': ele.user.email,
             'role': ele.role}

            for ele in project_obj.projectuser_set.filter(
                status__name='Active').exclude(
                role__name='Principal Investigator').order_by(
                'user__username') if ele.user != self.request.user
        ]

        return users_to_remove

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        project_obj = get_object_or_404(Project, pk=pk)

        users_to_remove = self.get_users_to_remove(project_obj)
        context = {}

        if users_to_remove:
            formset = formset_factory(
                ProjectRemoveUserForm, max_num=len(users_to_remove))
            formset = formset(initial=users_to_remove, prefix='userform')
            context['formset'] = formset

        context['project'] = get_object_or_404(Project, pk=pk)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        project_obj = get_object_or_404(Project, pk=pk)

        users_to_remove = self.get_users_to_remove(project_obj)

        formset = formset_factory(
            ProjectRemoveUserForm, max_num=len(users_to_remove))
        formset = formset(
            request.POST, initial=users_to_remove, prefix='userform')

        remove_users_count = 0

        if formset.is_valid():
            project_user_removed_status_choice = ProjectUserStatusChoice.objects.get(
                name='Removed')
            allocation_user_removed_status_choice = AllocationUserStatusChoice.objects.get(
                name='Removed')
            for form in formset:
                user_form_data = form.cleaned_data
                if user_form_data['selected']:

                    remove_users_count += 1

                    user_obj = User.objects.get(
                        username=user_form_data.get('username'))

                    if project_obj.projectuser_set.filter(
                            user=user_obj,
                            role__name='Principal Investigator').exists():
                        continue

                    project_user_obj = project_obj.projectuser_set.get(
                        user=user_obj)
                    project_user_obj.status = project_user_removed_status_choice
                    project_user_obj.save()

                    # get allocation to remove users from
                    allocations_to_remove_user_from = project_obj.allocation_set.filter(
                        status__name__in=['Active', 'New', 'Renewal Requested'])
                    for allocation in allocations_to_remove_user_from:
                        for allocation_user_obj in allocation.allocationuser_set.filter(user=user_obj, status__name__in=['Active', ]):
                            allocation_user_obj.status = allocation_user_removed_status_choice
                            allocation_user_obj.save()

                            allocation_remove_user.send(sender=self.__class__,
                                                        allocation_user_pk=allocation_user_obj.pk)

            messages.success(
                request, 'Removed {} users from project.'.format(remove_users_count))
        else:
            for error in formset.errors:
                messages.error(request, error)

        return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': pk}))


class ProjectUserDetail(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'project/project_user_detail.html'

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def get(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        project_user_pk = self.kwargs.get('project_user_pk')

        if project_obj.projectuser_set.filter(pk=project_user_pk).exists():
            project_user_obj = project_obj.projectuser_set.get(
                pk=project_user_pk)

            project_user_update_form = ProjectUserUpdateForm(
                initial={'role': project_user_obj.role, 'enable_notifications': project_user_obj.enable_notifications})

            context = {}
            context['project_obj'] = project_obj
            context['project_user_update_form'] = project_user_update_form
            context['project_user_obj'] = project_user_obj
            context['project_user_is_manager'] = project_user_obj.role.name == 'Manager'

            try:
                allocation_obj = get_project_compute_allocation(project_obj)
            except (Allocation.DoesNotExist,
                    Allocation.MultipleObjectsReturned):
                allocation_obj = None
                cluster_access_status = 'Error'
            else:
                try:
                    cluster_access_status = \
                        get_allocation_user_cluster_access_status(
                            allocation_obj, project_user_obj.user).value
                except AllocationUserAttribute.DoesNotExist:
                    cluster_access_status = 'None'
                except AllocationUserAttribute.MultipleObjectsReturned:
                    cluster_access_status = 'Error'
            context['allocation_obj'] = allocation_obj
            context['cluster_access_status'] = cluster_access_status

            return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        project_user_pk = self.kwargs.get('project_user_pk')

        if project_obj.status.name not in ['Active', 'New', ]:
            messages.error(
                request, 'You cannot update a user in an archived project.')
            return HttpResponseRedirect(reverse('project-user-detail', kwargs={'pk': project_user_pk}))

        if project_obj.projectuser_set.filter(id=project_user_pk).exists():
            project_user_obj = project_obj.projectuser_set.get(
                pk=project_user_pk)

            pi_role = ProjectUserRoleChoice.objects.get(
                name='Principal Investigator')
            if project_user_obj.role == pi_role:
                messages.error(
                    request, 'PI role and email notification option cannot be changed.')
                return HttpResponseRedirect(reverse('project-user-detail', kwargs={'pk': project_user_pk}))

            project_user_update_form = ProjectUserUpdateForm(request.POST,
                                                             initial={'role': project_user_obj.role.name,
                                                                      'enable_notifications': project_user_obj.enable_notifications})

            if project_user_update_form.is_valid():
                form_data = project_user_update_form.cleaned_data
                project_user_obj.enable_notifications = form_data.get('enable_notifications')

                old_role = project_user_obj.role
                new_role = ProjectUserRoleChoice.objects.get(name=form_data.get('role'))
                only_manager = not project_obj.projectuser_set.filter(~Q(pk=project_user_pk),
                                                                      role__name='Manager').exists()

                if old_role.name == 'Manager' and only_manager:
                    if new_role.name == 'User':
                        project_pis = project_obj.projectuser_set.filter(role__name='Principal Investigator')

                        if not project_pis.exists():
                            # no pis exist, cannot demote
                            new_role = old_role
                            messages.error(
                                request, 'The project must have at least one PI or manager with notifications enabled.')
                        else:
                            messages.warning(request, 'User {} is no longer a manager. All PIs will now receive notifications.'
                                             .format(project_user_obj.user.username))
                            for pi in project_pis:
                                pi.enable_notifications = True
                                pi.save()

                    elif new_role.name == 'Principal Investigator':
                        project_user_obj.enable_notifications = True

                project_user_obj.role = new_role
                project_user_obj.save()

                messages.success(request, 'User details updated.')
                return HttpResponseRedirect(reverse('project-user-detail', kwargs={'pk': project_obj.pk, 'project_user_pk': project_user_obj.pk}))


def project_update_email_notification(request):

    if request.method == "POST":
        data = request.POST
        project_user_obj = get_object_or_404(
            ProjectUser, pk=data.get('user_project_id'))
        checked = data.get('checked')
        if checked == 'true':
            project_user_obj.enable_notifications = True
            project_user_obj.save()
            return HttpResponse('', status=200)
        elif checked == 'false':
            project_user_obj.enable_notifications = False
            project_user_obj.save()
            return HttpResponse('', status=200)
        else:
            return HttpResponse('', status=400)
    else:
        return HttpResponse('', status=400)


class ProjectReviewView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'project/project_review.html'
    login_url = "/"  # redirect URL if fail test_func

    def test_func(self):
        """ UserPassesTestMixin Tests"""
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

        messages.error(
            self.request, 'You do not have permissions to review this project.')

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if not project_obj.needs_review:
            messages.error(request, 'You do not need to review this project.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))

        if 'Auto-Import Project'.lower() in project_obj.title.lower():
            messages.error(
                request, 'You must update the project title before reviewing your project. You cannot have "Auto-Import Project" in the title.')
            return HttpResponseRedirect(reverse('project-update', kwargs={'pk': project_obj.pk}))

        if 'We do not have information about your research. Please provide a detailed description of your work and update your field of science. Thank you!' in project_obj.description:
            messages.error(
                request, 'You must update the project description before reviewing your project.')
            return HttpResponseRedirect(reverse('project-update', kwargs={'pk': project_obj.pk}))

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        project_review_form = ProjectReviewForm(project_obj.pk)

        context = {}
        context['project'] = project_obj
        context['project_review_form'] = project_review_form
        context['project_users'] = ', '.join(['{} {}'.format(ele.user.first_name, ele.user.last_name)
                                              for ele in project_obj.projectuser_set.filter(status__name='Active').order_by('user__last_name')])

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        project_review_form = ProjectReviewForm(project_obj.pk, request.POST)

        project_review_status_choice = ProjectReviewStatusChoice.objects.get(
            name='Pending')

        if project_review_form.is_valid():
            form_data = project_review_form.cleaned_data
            project_review_obj = ProjectReview.objects.create(
                project=project_obj,
                reason_for_not_updating_project=form_data.get('reason'),
                status=project_review_status_choice)

            project_obj.force_review = False
            project_obj.save()

            domain_url = get_domain_url(self.request)
            url = '{}{}'.format(domain_url, reverse('project-review-list'))

            if EMAIL_ENABLED:
                send_email_template(
                    'New project review has been submitted',
                    'email/new_project_review.txt',
                    {'url': url},
                    EMAIL_SENDER,
                    [EMAIL_DIRECTOR_EMAIL_ADDRESS, ]
                )

            messages.success(request, 'Project reviewed successfully.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            messages.error(
                request, 'There was an error in processing  your project review.')
            return HttpResponseRedirect(reverse('project-detail', kwargs={'pk': project_obj.pk}))


class ProjectReviewListView(LoginRequiredMixin, UserPassesTestMixin, ListView):

    model = ProjectReview
    template_name = 'project/project_review_list.html'
    prefetch_related = ['project', ]
    context_object_name = 'project_review_list'

    def get_queryset(self):
        return ProjectReview.objects.filter(status__name='Pending')

    def test_func(self):
        """ UserPassesTestMixin Tests"""

        if self.request.user.is_superuser:
            return True

        if self.request.user.has_perm('project.can_review_pending_project_reviews'):
            return True

        messages.error(
            self.request, 'You do not have permission to review pending project reviews.')


class ProjectReviewCompleteView(LoginRequiredMixin, UserPassesTestMixin, View):
    login_url = "/"

    def test_func(self):
        """ UserPassesTestMixin Tests"""

        if self.request.user.is_superuser:
            return True

        if self.request.user.has_perm('project.can_review_pending_project_reviews'):
            return True

        messages.error(
            self.request, 'You do not have permission to mark a pending project review as completed.')

    def get(self, request, project_review_pk):
        project_review_obj = get_object_or_404(
            ProjectReview, pk=project_review_pk)

        project_review_status_completed_obj = ProjectReviewStatusChoice.objects.get(
            name='Completed')
        project_review_obj.status = project_review_status_completed_obj
        project_review_obj.project.project_needs_review = False
        project_review_obj.save()

        messages.success(request, 'Project review for {} has been completed'.format(
            project_review_obj.project.title)
        )

        return HttpResponseRedirect(reverse('project-review-list'))


class ProjectReivewEmailView(LoginRequiredMixin, UserPassesTestMixin, FormView):
    form_class = ProjectReviewEmailForm
    template_name = 'project/project_review_email.html'
    login_url = "/"

    def test_func(self):
        """ UserPassesTestMixin Tests"""

        if self.request.user.is_superuser:
            return True

        if self.request.user.has_perm('project.can_review_pending_project_reviews'):
            return True

        messages.error(
            self.request, 'You do not have permission to send email for a pending project review.')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get('pk')
        project_review_obj = get_object_or_404(ProjectReview, pk=pk)
        context['project_review'] = project_review_obj

        return context

    def get_form(self, form_class=None):
        """Return an instance of the form to be used in this view."""
        if form_class is None:
            form_class = self.get_form_class()
        return form_class(self.kwargs.get('pk'), **self.get_form_kwargs())

    def form_valid(self, form):
        pk = self.kwargs.get('pk')
        project_review_obj = get_object_or_404(ProjectReview, pk=pk)
        form_data = form.cleaned_data

        pi_users = project_review_obj.project.pis()
        receiver_list = [pi_user.email for pi_user in pi_users]
        cc = form_data.get('cc').strip()
        if cc:
            cc = cc.split(',')
        else:
            cc = []

        send_email(
            'Request for more information',
            form_data.get('email_body'),
            EMAIL_DIRECTOR_EMAIL_ADDRESS,
            receiver_list,
            cc
        )

        if receiver_list:
            message = 'Email sent to:'
            for i, pi in enumerate(pi_users):
                message = message + (
                    f'\n{pi.first_name} {pi.last_name} ({pi.username})')
            messages.success(self.request, message)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('project-review-list')


class ProjectJoinView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    login_url = '/'

    def test_func(self):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        user_obj = self.request.user
        project_users = project_obj.projectuser_set.filter(user=user_obj)

        if not project_users.exists():
            return True

        project_user = project_users.first()
        if project_user.status.name == 'Active':
            message = (
                f'You are already a member of Project {project_obj.name}.')
            messages.error(self.request, message)
            return False

        if project_user.status.name == 'Pending - Add':
            message = (
                f'You have already requested to join Project '
                f'{project_obj.name}.')
            messages.warning(self.request, message)
            return False

        return True

    def get(self, *args, **kwargs):
        return redirect(self.login_url)

    def post(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        user_obj = self.request.user
        project_users = project_obj.projectuser_set.filter(user=user_obj)
        role = ProjectUserRoleChoice.objects.get(name='User')
        status = ProjectUserStatusChoice.objects.get(name='Pending - Add')

        if project_users.exists():
            project_user = project_users.first()
            project_user.role = role
            project_user.status = status
            project_user.save()
        else:
            project_user = ProjectUser.objects.create(
                user=user_obj,
                project=project_obj,
                role=role,
                status=status)

        if project_obj.joins_require_approval:
            message = (
                f'You have requested to join Project {project_obj.name}. The '
                f'managers have been notified and will approve or deny your '
                f'request.')
            messages.success(self.request, message)
            next_view = reverse('project-join-list')
        else:
            status = ProjectUserStatusChoice.objects.get(name='Active')
            project_user.status = status
            project_user.save()

            allocations = project_obj.allocation_set.filter(
                resources__name='Savio Compute', status__name='Active')
            if allocations.count() != 1:
                message = (
                    'Unexpected server error. Please contact an '
                    'administrator.')
                messages.error(self.request, message)
            else:
                allocation = allocations.first()
                allocation_user_active_status_choice = \
                    AllocationUserStatusChoice.objects.get(name='Active')
                if allocation.allocationuser_set.filter(
                        user=user_obj).exists():
                    allocation_user_obj = allocation.allocationuser_set.get(
                        user=user_obj)
                    allocation_user_obj.status = \
                        allocation_user_active_status_choice
                    allocation_user_obj.save()
                else:
                    allocation_user_obj = AllocationUser.objects.create(
                        allocation=allocation,
                        user=user_obj,
                        status=allocation_user_active_status_choice)
                allocation_activate_user.send(
                    sender=self.__class__,
                    allocation_user_pk=allocation_user_obj.pk)

                message = (
                    f'You have requested to join Project {project_obj.name}. '
                    f'Your request has automatically been approved.')
                messages.success(self.request, message)
                next_view = reverse(
                    'project-detail', kwargs={'pk': project_obj.pk})

        return redirect(next_view)


class ProjectJoinListView(ProjectListView):

    template_name = 'project/project_join_list.html'

    def get_queryset(self):

        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            if direction == 'asc':
                direction = ''
            else:
                direction = '-'
            order_by = direction + order_by
        else:
            order_by = 'id'

        project_search_form = ProjectSearchForm(self.request.GET)

        projects = Project.objects.prefetch_related(
            'field_of_science', 'status').filter(
                status__name__in=['New', 'Active', ]
        ).annotate(
            cluster_name=Case(
                When(name__startswith='vector_', then=Value('Vector')),
                default=Value('Savio'),
                output_field=CharField(),
            ),
        ).order_by(order_by)

        if project_search_form.is_valid():
            data = project_search_form.cleaned_data

            # Last Name
            if data.get('last_name'):
                pi_project_users = ProjectUser.objects.filter(
                    project__in=projects,
                    role__name='Principal Investigator',
                    user__last_name__icontains=data.get('last_name'))
                project_ids = pi_project_users.values_list(
                    'project_id', flat=True)
                projects = projects.filter(id__in=project_ids)

            # Username
            if data.get('username'):
                projects = projects.filter(
                    Q(projectuser__user__username__icontains=data.get(
                        'username')) &
                    (Q(projectuser__role__name='Principal Investigator') |
                     Q(projectuser__status__name='Active'))
                )

            # Field of Science
            if data.get('field_of_science'):
                projects = projects.filter(
                    field_of_science__description__icontains=data.get(
                        'field_of_science'))

            # Project Title
            if data.get('project_title'):
                projects = projects.filter(title__icontains=data.get('project_title'))

            # Project Name
            if data.get('project_name'):
                projects = projects.filter(name__icontains=data.get('project_name'))

            # Cluster Name
            if data.get('cluster_name'):
                projects = projects.filter(cluster_name__icontains=data.get('cluster_name'))

        return projects.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        projects = self.get_queryset()
        not_joinable = projects.filter(
            projectuser__user=self.request.user,
            projectuser__status__name__in=['Pending - Add', 'Active', ]
        ).values_list('name', flat=True)
        context['not_joinable'] = not_joinable
        return context


class ProjectReviewJoinRequestsView(LoginRequiredMixin, UserPassesTestMixin,
                                    TemplateView):
    template_name = 'project/project_review_join_requests.html'

    def test_func(self):
        if self.request.user.is_superuser:
            return True

        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))

        if project_obj.projectuser_set.filter(
                user=self.request.user,
                role__name__in=['Manager', 'Principal Investigator'],
                status__name='Active').exists():
            return True

    def dispatch(self, request, *args, **kwargs):
        project_obj = get_object_or_404(Project, pk=self.kwargs.get('pk'))
        if project_obj.status.name not in ['Active', 'New', ]:
            message = 'You cannot review join requests to an archived project.'
            messages.error(request, message)
            return HttpResponseRedirect(
                reverse('project-detail', kwargs={'pk': project_obj.pk}))
        else:
            return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def get_users_to_review(project_obj):
        users_to_review = [
            {
                'username': ele.user.username,
                'first_name': ele.user.first_name,
                'last_name': ele.user.last_name,
                'email': ele.user.email,
                'role': ele.role,
            }
            for ele in project_obj.projectuser_set.filter(
                status__name='Pending - Add').order_by('user__username')
        ]
        return users_to_review

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        project_obj = get_object_or_404(Project, pk=pk)

        users_to_review = self.get_users_to_review(project_obj)
        context = {}

        if users_to_review:
            formset = formset_factory(
                ProjectReviewUserJoinForm, max_num=len(users_to_review))
            formset = formset(initial=users_to_review, prefix='userform')
            context['formset'] = formset

        context['project'] = get_object_or_404(Project, pk=pk)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        project_obj = get_object_or_404(Project, pk=pk)

        users_to_review = self.get_users_to_review(project_obj)

        formset = formset_factory(
            ProjectReviewUserJoinForm, max_num=len(users_to_review))
        formset = formset(
            request.POST, initial=users_to_review, prefix='userform')

        reviewed_users_count = 0

        decision = request.POST.get('decision', None)
        if decision not in ('approve', 'deny'):
            return HttpResponse('', status=400)

        if formset.is_valid():
            if decision == 'approve':
                status_name = 'Active'
                message_verb = 'Approved'
            else:
                status_name = 'Denied'
                message_verb = 'Denied'

            project_user_active_status_choice = \
                ProjectUserStatusChoice.objects.get(name=status_name)
            allocation_user_active_status_choice = \
                AllocationUserStatusChoice.objects.get(name='Active')

            allocations = project_obj.allocation_set.filter(
                resources__name='Savio Compute', status__name='Active')
            if allocations.count() != 1:
                message = (
                    'Unexpected server error. Please contact an '
                    'administrator.')
                messages.error(self.request, message)
                return HttpResponseRedirect(
                    reverse('project-detail', kwargs={'pk': pk}))
            else:
                allocation = allocations.first()

            for form in formset:
                user_form_data = form.cleaned_data
                if user_form_data['selected']:

                    reviewed_users_count += 1

                    user_obj = User.objects.get(
                        username=user_form_data.get('username'))

                    project_user_obj = project_obj.projectuser_set.get(
                        user=user_obj)
                    project_user_obj.status = project_user_active_status_choice
                    project_user_obj.save()

                    if allocation.allocationuser_set.filter(
                            user=user_obj).exists():
                        allocation_user_obj = \
                            allocation.allocationuser_set.get(user=user_obj)
                        allocation_user_obj.status = \
                            allocation_user_active_status_choice
                        allocation_user_obj.save()
                    else:
                        allocation_user_obj = AllocationUser.objects.create(
                            allocation=allocation,
                            user=user_obj,
                            status=allocation_user_active_status_choice)
                    allocation_activate_user.send(
                        sender=self.__class__,
                        allocation_user_pk=allocation_user_obj.pk)

            message = (
                f'{message_verb} {reviewed_users_count} user requests to join '
                f'the project.')
            messages.success(request, message)
        else:
            for error in formset.errors:
                messages.error(request, error)

        return HttpResponseRedirect(
            reverse('project-detail', kwargs={'pk': pk}))
