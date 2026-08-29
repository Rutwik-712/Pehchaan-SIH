from app.entity_policy import is_supported_graph_entity


def test_network_entities_accept_real_world_entities_and_identifiers() -> None:
    assert is_supported_graph_entity("PERSON", "Kavya Nair")
    assert is_supported_graph_entity("PERSON", "Aditi Rao Demo 02")
    assert is_supported_graph_entity("LOCATION", "Majestic Bus Stand")
    assert is_supported_graph_entity("ORGANIZATION", "Northstar Logistics")
    assert is_supported_graph_entity("PHONE_NUMBER", "9988776601")
    assert is_supported_graph_entity("VEHICLE", "KA05MN4821")


def test_network_entities_reject_metadata_and_non_entity_values() -> None:
    assert not is_supported_graph_entity("ORGANIZATION", "KSP-CR-2048 Language")
    assert not is_supported_graph_entity("PERSON", "01")
    assert not is_supported_graph_entity("PERSON", "Vehicle")
    assert not is_supported_graph_entity("ORGANIZATION", "ALLEGATIONS")
    assert not is_supported_graph_entity("ORGANIZATION", "KSP")
    assert not is_supported_graph_entity("PERSON", "व्यक्ति")
    assert not is_supported_graph_entity("PERSON", "याचा")
    assert not is_supported_graph_entity("PERSON", "ಪ್ರಥಮ")
    assert not is_supported_graph_entity("PERSON", "ಪ್ರದರ್ಶನಕ್ಕಾಗಿ")
    assert not is_supported_graph_entity("PERSON", "Rao Demo")
    assert not is_supported_graph_entity("DATE", "27/08/2026")
    assert not is_supported_graph_entity("AMOUNT", "INR 5000")
