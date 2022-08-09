from django.urls import path

from flags.urls import flagged_paths

import coldfront.core.allocation.views as allocation_views
import coldfront.core.allocation.views_.cluster_access_views as \
    cluster_access_views
import coldfront.core.allocation.views_.secure_dir_views as secure_dir_views
import coldfront.core.billing.views as billing_views


urlpatterns = [
    path('', allocation_views.AllocationListView.as_view(),
         name='allocation-list'),
    path('project/<int:project_pk>/create',
         allocation_views.AllocationCreateView.as_view(),
         name='allocation-create'),
    path('<int:pk>/',
         allocation_views.AllocationDetailView.as_view(),
         name='allocation-detail'),
    path('<int:pk>/activate-request',
         allocation_views.AllocationActivateRequestView.as_view(),
         name='allocation-activate-request'),
    path('<int:pk>/deny-request',
         allocation_views.AllocationDenyRequestView.as_view(),
         name='allocation-deny-request'),
    path('<int:pk>/add-users',
         allocation_views.AllocationAddUsersView.as_view(),
         name='allocation-add-users'),
    path('<int:pk>/remove-users',
         allocation_views.AllocationRemoveUsersView.as_view(),
         name='allocation-remove-users'),
    path('request-list', allocation_views.AllocationRequestListView.as_view(),
         name='allocation-request-list'),
    # path('<int:pk>/renew', allocation_views.AllocationRenewView.as_view(),
    #      name='allocation-renew'),
    # path('<int:pk>/allocationattribute/add',
    #      allocation_views.AllocationAttributeCreateView.as_view(),
    #      name='allocation-attribute-add'),
    # path('<int:pk>/allocationattribute/delete',
    #      allocation_views.AllocationAttributeDeleteView.as_view(),
    #      name='allocation-attribute-delete'),
    path('allocation-invoice-list',
         allocation_views.AllocationInvoiceListView.as_view(),
         name='allocation-invoice-list'),
    path('<int:pk>/invoice/',
         allocation_views.AllocationInvoiceDetailView.as_view(),
         name='allocation-invoice-detail'),
    path('allocation/<int:pk>/add-invoice-note',
         allocation_views.AllocationAddInvoiceNoteView.as_view(),
         name='allocation-add-invoice-note'),
    path('allocation-invoice-note/<int:pk>/update',
         allocation_views.AllocationUpdateInvoiceNoteView.as_view(),
         name='allocation-update-invoice-note'),
    path('allocation/<int:pk>/invoice/delete/',
         allocation_views.AllocationDeleteInvoiceNoteView.as_view(),
         name='allocation-delete-invoice-note'),
    path('add-allocation-account/',
         allocation_views.AllocationAccountCreateView.as_view(),
         name='add-allocation-account'),
    path('allocation-account-list/',
         allocation_views.AllocationAccountListView.as_view(),
         name='allocation-account-list')]


# Cluster Access Requests
urlpatterns += [
    path('<int:pk>/request-cluster-account/<int:user_pk>',
         cluster_access_views.AllocationRequestClusterAccountView.as_view(),
         name='allocation-request-cluster-account'),
    path('cluster-account/<int:pk>/update-status',
         cluster_access_views.AllocationClusterAccountUpdateStatusView.as_view(),
         name='allocation-cluster-account-update-status'),
    path('cluster-account/<int:pk>/activate-request',
         cluster_access_views.AllocationClusterAccountActivateRequestView.as_view(),
         name='allocation-cluster-account-activate-request'),
    path('cluster-account/<int:pk>/deny-request',
         cluster_access_views.AllocationClusterAccountDenyRequestView.as_view(),
         name='allocation-cluster-account-deny-request'),
    path('cluster-account-request-list',
         cluster_access_views.AllocationClusterAccountRequestListView.as_view(completed=False),
         name='allocation-cluster-account-request-list'),
    path('cluster-account-request-list-completed',
         cluster_access_views.AllocationClusterAccountRequestListView.as_view(completed=True),
         name='allocation-cluster-account-request-list-completed'),
]


# Billing ID Management
with flagged_paths('LRC_ONLY') as f_path:
    urlpatterns += [
        f_path('<int:pk>/update-billing-id',
               billing_views.UpdateAllocationBillingIDView.as_view(),
               name='allocation-update-billing-id'),
        f_path('<int:pk>/update-user-billing-ids',
               billing_views.UpdateAllocationUserBillingIDsView.as_view(),
               name='allocation-users-update-billing-ids'),
    ]


# Secure Directories
with flagged_paths('SECURE_DIRS_REQUESTABLE') as path:
    flagged_url_patterns = [
        path('<int:pk>/secure-dir-<str:action>-users/',
             secure_dir_views.SecureDirManageUsersView.as_view(),
             name='secure-dir-manage-users'),
        path('secure-dir-<str:action>-users-request-list/<str:status>',
             secure_dir_views.SecureDirManageUsersRequestListView.as_view(),
             name='secure-dir-manage-users-request-list'),
        path('<int:pk>/secure-dir-<str:action>-user-update-status',
             secure_dir_views.SecureDirManageUsersUpdateStatusView.as_view(),
             name='secure-dir-manage-user-update-status'),
        path('<int:pk>/secure-dir-<str:action>-user-complete-status',
             secure_dir_views.SecureDirManageUsersCompleteStatusView.as_view(),
             name='secure-dir-manage-user-complete-status'),
        path('<int:pk>/secure-dir-<str:action>-user-deny-request',
             secure_dir_views.SecureDirManageUsersDenyRequestView.as_view(),
             name='secure-dir-manage-user-deny-request'),
        path('secure-dir-pending-requests/',
             secure_dir_views.SecureDirRequestListView.as_view(completed=False),
             name='secure-dir-pending-request-list'),
        path('secure-dir-completed-requests/',
             secure_dir_views.SecureDirRequestListView.as_view(completed=True),
             name='secure-dir-completed-request-list'),
        path('secure-dir-request-detail/<int:pk>',
             secure_dir_views.SecureDirRequestDetailView.as_view(),
             name='secure-dir-request-detail'),
        path('secure-dir-request/<int:pk>/rdm_consultation',
             secure_dir_views.SecureDirRequestReviewRDMConsultView.as_view(),
             name='secure-dir-request-review-rdm-consultation'),
        path('secure-dir-request/<int:pk>/mou',
             secure_dir_views.SecureDirRequestReviewMOUView.as_view(),
             name='secure-dir-request-review-mou'),
        path('secure-dir-request/<int:pk>/setup',
             secure_dir_views.SecureDirRequestReviewSetupView.as_view(),
             name='secure-dir-request-review-setup'),
        path('secure-dir-request/<int:pk>/deny',
             secure_dir_views.SecureDirRequestReviewDenyView.as_view(),
             name='secure-dir-request-review-deny'),
        path('secure-dir-request/<int:pk>/undeny',
             secure_dir_views.SecureDirRequestUndenyRequestView.as_view(),
             name='secure-dir-request-undeny'),
    ]

urlpatterns = urlpatterns + flagged_url_patterns
