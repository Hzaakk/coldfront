'''
add a command audit_data to ensure that certain invariants hold. These include, but are not limited to:

 Allocations have the expected start_date and end_date values.
 Inactive Projects have "Expired" Allocations and zero SUs.
 Each Project has at least one PI.
 Users with a cluster UID should be associated with at least one Project (maybe).
LRC only:
 Each UserProfile that has access to Lawrencium should have a billing_activity.
 Each Recharge Allocation that has access to Lawrencium should have a "Billing Activity"-typed AllocationAttribute.
 Each Recharge AllocationUser that has access to Lawrencium should have a "Billing Activity"-typed AllocationUserAttribute.
 From Enforce that LRC PIs are LBL employees #392, each PI of a Project on Lawrencium must be an LBL employee.
They might be grouped into subcommands as appropriate. Add a subcommand for running all checks.
'''

import datetime

from django.core.management.base import BaseCommand
from django.db.models import Q

from coldfront.core.allocation.models import Allocation, AllocationPeriod, AllocationUser
from coldfront.core.project.models import Project, ProjectUser
from coldfront.core.user.models import UserProfile
from coldfront.core.allocation.models import AllocationAttribute

class Command(BaseCommand):
    help = 'Audit data to ensure that certain invariants hold.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true',
            help='Run all non-LRC-only checks')
        parser.add_argument('--allocation-date', action='store_true',
            help='Check that allocations have the expected start_date and end_date values')
        parser.add_argument('--project-inactive', action='store_true',
            help='Check that inactive projects have "Expired" allocations and zero SUs')
        parser.add_argument('--project-pi', action='store_true',
            help='Check that projects have at least one PI')
        parser.add_argument('--user-project', action='store_true',
            help='Check that users with a cluster UID should be associated with at least one Project')

        parser.add_argument('--lrc-all', action='store_true',
            help='Run all LRC-only checks')
        parser.add_argument('--lrc-user-billing', action='store_true',
            help='Check that LRC users have a billing_activity')
        parser.add_argument('--lrc-recharge-allocation-billing', action='store_true',
            help='Check that LRC Recharge Allocations have a "Billing Activity"-typed AllocationAttribute')
        parser.add_argument('--lrc-recharge-allocation-user-billing', action='store_true',
            help='Check that LRC Recharge AllocationUsers have a "Billing Activity"-typed AllocationUserAttribute')
        parser.add_argument('--lrc-pis-lbl-employee', action='store_true',
            help='Check that LRC PIs are LBL employees')


    def handle(self, *args, **options):
        if options['all']:
            options['allocation_date'] = True
            options['project_inactive'] = True
            options['project_pi'] = True
            options['user_project'] = True
        if options['lrc_all']:
            options['lrc_user_billing'] = True
            options['lrc_recharge_allocation_billing'] = True
            options['lrc_recharge_allocation_user_billing'] = True
            options['lrc_pis_lbl_employee'] = True
        for option in options:
            if isinstance(options[option], bool) and options[option] and option not in ('all', 'lrc_all'):
                self.stdout.write(self.style.WARNING('Running {}...'.format(option)))
                getattr(self, 'handle_{}'.format(option))()
                self.stdout.write(self.style.SUCCESS('Audit complete.'))

    def handle_allocation_date(self):
        '''
        Assert that all compute allocations have the expected start_date and end_date values.
        - Allocation end date is after the start date
        - Allocation start date is on or after the project start date
        - FCAs and PCAs:
          FCAs and PCAs are valid within a so-called “Allowance Year” (June 1st - May 31st for BRC, October 1st - September 30th for LRC):
                - Inactive ones (ones that were not renewed) should have a start date set to the start of the current allowance year AllocationPeriod, but no end date.
                - Active ones (ones that were renewed, or were created during this allowance year) should have the same start and end date as the current allowance year AllocationPeriod.
          ICAs (Instructional Computing Allowances) are valid within a particular UC Berkeley semester.
            - Inactive ones should have a start date, but no end date.
            - Active ones (currently none on production) should match a current (has started, but has not ended) instructional AllocationPeriod.
          Recharge and Condo may/should have start dates, but don’t have end dates, as they don’t end.
        '''
        allocations = Allocation.objects.select_related('project', 'project__status').prefetch_related('resources') \
            .filter(resources__name__endswith='Compute') \
            .values('id', 'project__status__name', 'project__name','start_date', 'end_date')

        FCA_PCA_ALLOCATION_PERIOD = AllocationPeriod.objects.get(name__startswith='Allowance Year',
                                                                 start_date__lt=datetime.date.today(),
                                                                 end_date__gt=datetime.date.today())
        ICA_ALLOCATION_PERIODS = AllocationPeriod.objects.filter(Q(end_date__gt=datetime.date.today())
                                                                & (Q(name__startswith='Fall Semester')
                                                                 | Q(name__startswith='Spring Semester')
                                                                 | Q(name__startswith='Summer Sessions'))).all()
        FCA_PCA_PREFIXES = ('fc_', 'pc_')
        ICA_PREFIX = 'ic_'
        RECHARGE_CONDO_PREFIX = ('co_', 'ac_')

        for allocation in allocations:
            id = allocation['id']
            start_date = allocation['start_date']
            end_date = allocation['end_date']
            project_status = allocation['project__status__name']
            project = allocation['project__name']

            if end_date is not None and end_date < start_date:
                self.stdout.write(self.style.ERROR('Allocation {} for project {}'
                ' has an end date before its start date.' \
                    .format(allocation['id'], project)))

            if project.startswith(FCA_PCA_PREFIXES):
                if project_status == 'Inactive' and start_date != FCA_PCA_ALLOCATION_PERIOD.start_date:
                    self.stdout.write(self.style.ERROR('Allocation {} for project {}'
                    ' has a start date of {} that is different than its allocation period\'s.' \
                        .format(id, project, start_date)))
                    if start_date == None or end_date == None or start_date.day != 1 or end_date.day != 31:
                        print(project_status, start_date, end_date)
                if project_status == 'Active' and end_date != FCA_PCA_ALLOCATION_PERIOD.end_date:
                    self.stdout.write(self.style.ERROR('Allocation {} for project {}'
                    ' is active and has an end date of {} that is different than its allocation period\'s.' \
                        .format(id, project, end_date)))
                    if start_date == None or end_date == None or start_date.day != 1 or end_date.day != 31:
                        print(project_status, start_date, end_date)
                
            elif project.startswith(ICA_PREFIX):
                if project_status == 'Inactive' and end_date is not None:
                    self.stdout.write(self.style.ERROR('Allocation {} for project {}'
                    ' has an end date while being an inactive ICA.' \
                        .format(id, project)))
                if project_status == 'Active' and not any(end_date != ica.end_date for ica in ICA_ALLOCATION_PERIODS):
                    self.stdout.write(self.style.ERROR('Allocation {} for project {}'
                    ' is an active ICA that has an end date that is different from all ICA allocation periods.' \
                        .format(id, project)))
            elif project.startswith(RECHARGE_CONDO_PREFIX):
                if end_date is not None:
                    self.stdout.write(self.style.ERROR('Allocation {} for project {}'
                    ' is a Recharge or Condo allocation with an end date.' \
                        .format(id, project)))
    
    def handle_project_inactive(self):
        '''
        Assert that inactive Projects have "Expired" allocations and zero SUs.
        '''
        inactive_projects = Project.objects.prefetch_related('allocation_set__status').filter(status__name='Inactive') 
        
        for project in inactive_projects:
            for allocation in project.allocation_set.select_related('status').prefetch_related('allocationattribute_set'):
                if allocation.status.name != 'Expired':
                    self.stdout.write(self.style.ERROR('Project {} ({})'
                    ' is inactive and has unexpired allocations.' \
                        .format(project.id, project.name)))
                try:
                    allocation_attribute = allocation.allocationattribute_set.get(allocation_attribute_type__name='Service Units')
                    if allocation_attribute.value == 0:
                        self.stdout.write(self.style.ERROR('Project {} ({})'
                    ' is inactive and has non-zero SUs.' \
                            .format(project.id, project.name)))
                except AllocationAttribute.DoesNotExist as e:
                    pass

    def handle_project_pi(self):
        '''
        Assert that all projects have at least one PI.
        '''
        projects = Project.objects.all()
        for project in projects:
            if project.pis().count() == 0:
                self.stdout.write(self.style.ERROR('Project {} ({})'
                    ' has no PIs.' \
                    .format(project.id, project.name)))

    def handle_user_project(self):
        '''
        Assert that all users with a cluster UID should be associated with at least one Project.
        '''
        users = UserProfile.objects.filter(cluster_uid__isnull=False) \
            .values('id', 'user__first_name', 'user__last_name', 'user__email')
        for user in users:
            user_project_count = ProjectUser.objects.filter(user_id=user['id']).count()
            if user_project_count == 0:
                self.stdout.write(self.style.ERROR('User {} ({} {}, {})'
                ' has a cluster UID but is not associated with any projects.' \
                    .format(user['id'], user['user__first_name'],
                    user['user__last_name'], user['user__email'])))

    def handle_lrc_user_billing(self):
        '''
        Assert that all LRC users have a billing_activity.
        '''
        users = UserProfile.objects.filter(cluster_uid__isnull=False) \
            .values('id', 'billing_activity', 'user__first_name',
                    'user__last_name', 'user__email')
        for user in users:
            if user['billing_activity'] is None:
                self.stdout.write(self.style.ERROR('User {} ({} {}, {})'
                ' has a cluster UID but is not associated with any billing activity.' \
                    .format(user['id'], user['user__first_name'],
                    user['user__last_name'], user['user__email'])))

    def handle_lrc_recharge_allocation_billing(self):
        '''
        Assert that all LRC Recharge Allocations have a "Billing Activity"-typed AllocationAttribute.
        '''
        allocations = Allocation.objects.filter(project__cluster__name='Lawrencium')
        for allocation in allocations:
            if allocation.allocationattribute_set.filter(type='Billing Activity').count() == 0:
                self.stdout.write(self.style.ERROR('Allocation {}'
                ' has no "Billing Activity"-typed AllocationAttribute.' \
                    .format(allocation.id)))
    
    def handle_lrc_recharge_allocation_user_billing(self):
        '''
        Assert that all LRC Recharge AllocationUsers have a "Billing Activity"-typed AllocationUserAttribute.
        '''
        allocation_users = AllocationUser.objects.filter(allocation__project__cluster__name='Lawrencium')
        for allocation_user in allocation_users:
            if allocation_user.allocationuserattribute_set.filter(type='Billing Activity').count() == 0:
                self.stdout.write(self.style.ERROR('AllocationUser {} ({} {}, {})'
                ' has no "Billing Activity"-typed AllocationUserAttribute.' \
                    .format(allocation_user.id, allocation_user.user.first_name, allocation_user.user.last_name, allocation_user.user.email)))

    def handle_lrc_pis_lbl_employee(self):
        '''
        Assert that all LRC PIs are LBL employees.
        '''
        pis = UserProfile.objects.filter(cluster_uid__isnull=False, project__cluster__name='Lawrencium', is_pi=True)
        for pi in pis:
            if not pi.is_lbl_employee():
                self.stdout.write(self.style.ERROR('User {} ({} {}, {})'
                ' is not an LBL employee.'
                .format(pi.id, pi.user.first_name, pi.user.last_name, pi.user.email)))