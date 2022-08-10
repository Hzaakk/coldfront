def assert_identity_linking_request_serialization(identity_linking_request,
                                                  result, fields):
    """Assert that IdentityLinkingRequest serialization gives the
    expected result."""
    for field in fields:
        field_value = getattr(identity_linking_request, field)
        if field == 'requester':
            expected = str(field_value.id)
        elif field in ('request_time', 'completion_time'):
            if field_value is None:
                expected = str(field_value)
            else:
                expected = field_value.isoformat().replace('+00:00', 'Z')
        elif field == 'status':
            expected = field_value.name
        else:
            expected = str(field_value)
        actual = str(result[field])
        assert expected == actual


def assert_user_serialization(user, result, fields):
    """Assert that User serialization gives the expected result."""
    for field in fields:
        field_value = getattr(user, field)
        expected = str(field_value)
        actual = str(result[field])
        assert expected == actual


def assert_account_deactivation_request_serialization(
        request, result, fields):
    """Assert that IdentityLinkingRequest serialization gives the
    expected result."""
    for field in fields:
        if field == 'justification':
            continue

        field_value = getattr(request, field)
        if field == 'user':
            expected = field_value.username
        elif field == 'status':
            expected = field_value.name
        elif field == 'reason':
            reasons = request.reason.all()
            expected = ','.join([reason.name for reason in reasons])
        else:
            expected = str(field_value)

        actual = str(result[field])
        assert expected == actual
