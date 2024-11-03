def test_fee_config(fee_config):

    # test the general fee config exists
    assert fee_config.minimum_fee == 5.0
    assert fee_config.fixed_fee == 1.0
    assert fee_config.percentage_fee == 0.01
    assert fee_config.minimum_fee == 5.0
    assert fee_config.maximum_fee == 20.0

    # test minimum fee
    assert fee_config.calculate_fee(0.0) == 5.0

    # test fixed medium size fee
    medium_fee = 1.0 + 0.01 * 1000
    assert fee_config.calculate_fee(1000.0) == medium_fee

    # test maximum fee
    assert fee_config.calculate_fee(1000000.0) == 20.0
