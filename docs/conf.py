from documenteer.conf.guide import *

autodoc_pydantic_field_swap_name_and_alias = True
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_json_error_strategy = "coerce"
autodoc_pydantic_settings_show_config_summary = False
autodoc_pydantic_settings_show_json = False
exclude_patterns.append("_templates/**")
