SCHEMA = {
    "root": [
        "root_hash_key",
        "reporting_entity_name",
        "reporting_entity_type",
        "plan_name",
        "plan_id",
        "plan_id_type",
        "plan_market_type",
        "last_updated_on",
        "version",
        "url",
    ],
    "in_network": [
        "root_hash_key",
        "in_network_hash_key",
        "negotiation_arrangement",
        "name",
        "billing_code_type_version",
        "description",
        "billing_code",
        "billing_code_type",
    ],
    "negotiated_prices": [
        "root_hash_key",
        "in_network_hash_key",
        "negotiated_rates_hash_key",
        "billing_class",
        "negotiated_type",
        "service_code",
        "expiration_date",
        "additional_information",
        "billing_code_modifier",
        "negotiated_rate",
    ],
    "provider_groups": [
        "root_hash_key",
        "in_network_hash_key",
        "negotiated_rates_hash_key",
        "tin_type",
        "tin_value",
        "npi_numbers",
    ],
    # "covered_services": [
    #     "root_hash_key",
    #     "in_network_hash_key",
    #     "billing_code_type_version",
    #     "description",
    #     "billing_code",
    #     "billing_code_type",
    #     "covered_services_hash_key",
    # ],
    # "bundled_codes": [
    #     "root_hash_key",
    #     "in_network_hash_key",
    #     "billing_code_type_version",
    #     "description",
    #     "billing_code",
    #     "billing_code_type",
    # ],
    # "negotiated_rates": [
    #     "root_hash_key",
    #     "in_network_hash_key",
    #     "negotiated_rates_hash_key",
    # ],
}
