"""Tests for seed data integrity — validate seed.py data structures."""


def test_users_unique_usernames():
    """All USERS have unique usernames."""
    from src.seed import USERS
    usernames = [u["username"] for u in USERS]
    assert len(usernames) == len(set(usernames)), f"Duplicate usernames: {[u for u in usernames if usernames.count(u) > 1]}"


def test_users_valid_user_types():
    """All user_type values are valid."""
    from src.seed import USERS
    valid_types = {"person", "organization", "government", "service"}
    for user in USERS:
        assert user.get("user_type", "person") in valid_types, \
            f"Invalid user_type '{user.get('user_type')}' for {user['username']}"


def test_users_have_required_fields():
    """All users have required fields."""
    from src.seed import USERS
    required = {"username", "display_name"}
    for user in USERS:
        for field in required:
            assert field in user, f"Missing '{field}' in user {user.get('username', '?')}"


def test_service_providers_unique_usernames():
    """All SERVICE_PROVIDERS have unique usernames."""
    from src.seed import SERVICE_PROVIDERS
    usernames = [s["username"] for s in SERVICE_PROVIDERS]
    assert len(usernames) == len(set(usernames)), f"Duplicate service usernames"


def test_network_names_unique():
    """Network names are unique."""
    from src.seed import NETWORKS
    names = [n["name"] for n in NETWORKS]
    assert len(names) == len(set(names)), f"Duplicate network names: {[n for n in names if names.count(n) > 1]}"


def test_connections_reference_valid_users():
    """Connection pairs reference valid usernames."""
    from src.seed import USERS, SERVICE_PROVIDERS, CONNECTIONS
    all_usernames = {u["username"] for u in USERS} | {s["username"] for s in SERVICE_PROVIDERS}

    for conn in CONNECTIONS:
        # CONNECTIONS is a list of tuples: (from_user, to_user, context, rel_type, from_label, to_label)
        from_user = conn[0]
        to_user = conn[1]
        assert from_user in all_usernames, f"Connection references unknown user '{from_user}'"
        assert to_user in all_usernames, f"Connection references unknown user '{to_user}'"


def test_seed_idempotent():
    """Seed data definitions are consistent for repeated use.

    We verify structural consistency rather than calling seed() twice,
    which would require full DB + Zig subsystem lifecycle and pollutes
    shared test state.
    """
    from src.seed import USERS, SERVICE_PROVIDERS, NETWORKS, CONNECTIONS

    # Verify no duplicate usernames (would crash on second seed)
    all_names = [u["username"] for u in USERS] + [s["username"] for s in SERVICE_PROVIDERS]
    assert len(all_names) == len(set(all_names)), "Duplicate usernames would fail on re-seed"

    # Verify no duplicate network names
    net_names = [n["name"] for n in NETWORKS]
    assert len(net_names) == len(set(net_names)), "Duplicate networks would fail on re-seed"

    # Verify connection pairs are unique
    conn_pairs = [(c[0], c[1]) for c in CONNECTIONS]
    assert len(conn_pairs) == len(set(conn_pairs)), "Duplicate connections would fail on re-seed"


def test_no_username_collision_users_services():
    """No username appears in both USERS and SERVICE_PROVIDERS."""
    from src.seed import USERS, SERVICE_PROVIDERS
    user_names = {u["username"] for u in USERS}
    svc_names = {s["username"] for s in SERVICE_PROVIDERS}
    overlap = user_names & svc_names
    assert len(overlap) == 0, f"Username collision: {overlap}"
