def test_fee_config(fee_config):
    # test the general fee config exists
    assert fee_config.minimum_fee == 5.0
    assert fee_config.fixed_fee == 1.0
    assert fee_config.percentage_fee == 0.01
    assert fee_config.minimum_fee == 5.0
    assert fee_config.maximum_fee == 20.0


def test_fee_minimum_fee(fee_config):
    assert fee_config.calculate_fee(0.0) == 5.0


def test_fee_medium_fee(fee_config):
    medium_fee = 1.0 + 0.01 * 1000
    assert fee_config.calculate_fee(1000.0) == medium_fee


def test_fee_maximum_fee(fee_config):
    assert fee_config.calculate_fee(1000000.0) == 20.0
