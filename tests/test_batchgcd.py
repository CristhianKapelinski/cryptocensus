from cryptocensus.batchgcd import batch_gcd


def test_no_shared_factor():
    # Distinct semiprimes with no common prime.
    moduli = [3 * 5, 7 * 11, 13 * 17]
    assert batch_gcd(moduli) == {}


def test_shared_prime_detected():
    p, q, r = 1009, 1013, 1019  # distinct primes
    n0 = p * q
    n1 = p * r  # shares p with n0
    n2 = 1021 * 1031  # coprime to the others
    result = batch_gcd([n0, n1, n2])
    assert set(result.keys()) == {0, 1}
    assert result[0] == p
    assert result[1] == p
    assert 2 not in result


def test_singleton_and_empty():
    assert batch_gcd([]) == {}
    assert batch_gcd([3 * 5]) == {}


def test_odd_length_tree():
    p = 1009
    moduli = [p * 1013, p * 1019, 1021 * 1031, 1033 * 1039, 1049 * 1051]
    result = batch_gcd(moduli)
    assert result.get(0) == p and result.get(1) == p
