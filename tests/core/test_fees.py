from pytest import approx


def test_fee_calculation(fee_config):
    """Test fee calculation with various transaction sizes"""
    # Test minimum fee
    small_transaction = fee_config.calculate_fee(1)
    assert small_transaction == approx(fee_config.minimum_fee)

    # Test normal fee calculation
    medium_transaction = fee_config.calculate_fee(1000)
    expected_fee = fee_config.fixed_fee + (1000 * fee_config.percentage_fee)
    assert medium_transaction == approx(expected_fee)

    # Test maximum fee
    large_transaction = fee_config.calculate_fee(1e12)
    assert large_transaction == approx(fee_config.maximum_fee)
