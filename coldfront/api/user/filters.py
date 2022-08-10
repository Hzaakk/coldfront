from coldfront.core.allocation.models import \
    ClusterAccountDeactivationRequestStatusChoice, \
    ClusterAccountDeactivationRequest, \
    ClusterAccountDeactivationRequestReasonChoice
from coldfront.core.user.models import IdentityLinkingRequest
from coldfront.core.user.models import IdentityLinkingRequestStatusChoice
import django_filters.filters


class IdentityLinkingRequestFilter(django_filters.FilterSet):
    """A FilterSet for the IdentityLinkingRequest model."""

    status = django_filters.filters.ModelMultipleChoiceFilter(
        field_name='status__name', to_field_name='name',
        queryset=IdentityLinkingRequestStatusChoice.objects.all())

    class Meta:
        model = IdentityLinkingRequest
        fields = ('status',)


class ClusterAccountDeactivationRequestFilter(django_filters.FilterSet):
    """A FilterSet for the ClusterAccountDeactivationRequest model."""

    status = django_filters.filters.ModelMultipleChoiceFilter(
        field_name='status__name', to_field_name='name',
        queryset=ClusterAccountDeactivationRequestStatusChoice.objects.all())

    reason = django_filters.Filter(field_name='reason__name', method='filter_reason')

    def filter_reason(self, queryset, name, value):
        reasons = value.split(',')
        return queryset.filter(reason__name__in=reasons)

    class Meta:
        model = ClusterAccountDeactivationRequest
        fields = ('status', 'reason')


